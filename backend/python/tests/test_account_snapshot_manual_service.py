from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.enums import AccountMemberRole, SnapshotGranularity, SnapshotSource
from app.main import create_app
from app.modules.accounts.access import AccountAccessDeniedError, AccountNotFoundError
from app.modules.snapshots import manual_service
from app.modules.snapshots.financial_metrics import AccountSnapshotEvidenceStateError
from app.modules.snapshots.manual_service import (
    CURRENT_ACCOUNT_SNAPSHOT_CALCULATION_VERSION,
    AccountSnapshotConflictError,
    AccountSnapshotUnavailableError,
    ManualAccountSnapshotService,
    RecalculateAccountSnapshotCommand,
    canonical_manual_snapshot_bucket,
)
from app.modules.snapshots.models import (
    AccountSnapshotRecalculateRequest,
    AccountSnapshotRecalculateResponse,
)
from app.modules.snapshots.persistence_projection import (
    AccountSnapshotPersistenceProjectionError,
)
from app.modules.snapshots.writer import (
    AccountSnapshotWriteConflictError,
    AccountSnapshotWriteDisposition,
    AccountSnapshotWriteResult,
    AccountSnapshotWriteStateError,
)

NOW = datetime(2026, 7, 28, 10, 20)
RAW_NOW = datetime(
    2026,
    7,
    28,
    12,
    20,
    59,
    987654,
    tzinfo=timezone(timedelta(hours=2)),
)


def _principal(user_id: str = "user-a") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.com",
        name=user_id,
    )


def _write_result(
    disposition: AccountSnapshotWriteDisposition = AccountSnapshotWriteDisposition.created,
    *,
    currency: str = "CZK",
) -> AccountSnapshotWriteResult:
    return AccountSnapshotWriteResult(
        snapshot_id="snapshot-a",
        account_id="account-a",
        disposition=disposition,
        item_count=2,
        timestamp=NOW,
        granularity=SnapshotGranularity.minute,
        currency=currency,
    )


def _session(*, active: bool = True) -> AsyncSession:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    state = {"active": active}
    cast(Any, session.in_transaction).side_effect = lambda: state["active"]

    async def commit() -> None:
        state["active"] = False

    async def rollback() -> None:
        state["active"] = False

    cast(Any, session.commit).side_effect = commit
    cast(Any, session.rollback).side_effect = rollback
    return session


@pytest.mark.parametrize(
    "role",
    [AccountMemberRole.owner, AccountMemberRole.admin, AccountMemberRole.editor],
)
async def test_write_roles_authorize_then_call_writer_once_with_idle_session(
    role: AccountMemberRole,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    access = AsyncMock(return_value=Mock(role=role))
    writer = Mock(write=AsyncMock(return_value=_write_result()))
    factory = Mock(return_value=writer)
    clock = Mock(return_value=RAW_NOW)
    monkeypatch.setattr(manual_service, "require_account_access", access)

    result = await ManualAccountSnapshotService(
        session,
        clock=clock,
        writer_factory=factory,
    ).recalculate(RecalculateAccountSnapshotCommand(principal=_principal(), account_id="account-a"))

    assert result.status == "created"
    assert result.timestamp == NOW
    assert access.await_args is not None
    assert access.await_args.kwargs["allowed_roles"] == manual_service.WRITE_ROLES
    cast(Any, session.commit).assert_awaited_once_with()
    cast(Any, session.rollback).assert_not_awaited()
    factory.assert_called_once_with(session)
    writer.write.assert_awaited_once()
    assert session.in_transaction() is False
    command = writer.write.await_args.args[0]
    assert command.account_id == "account-a"
    assert command.snapshot_timestamp == NOW
    assert command.calculated_at == NOW
    assert command.created_at == NOW
    assert command.granularity is SnapshotGranularity.minute
    assert command.source is SnapshotSource.manual_recalculation
    assert command.calculation_version == CURRENT_ACCOUNT_SNAPSHOT_CALCULATION_VERSION
    assert command.is_recalculated is True
    assert command.output_currency is None
    clock.assert_called_once_with()


async def test_explicit_output_currency_is_forwarded_exactly_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    access = AsyncMock()
    writer = Mock(write=AsyncMock(return_value=_write_result(currency="EUR")))
    factory = Mock(return_value=writer)
    clock = Mock(return_value=RAW_NOW)
    monkeypatch.setattr(manual_service, "require_account_access", access)

    result = await ManualAccountSnapshotService(
        session,
        clock=clock,
        writer_factory=factory,
    ).recalculate(
        RecalculateAccountSnapshotCommand(
            principal=_principal(),
            account_id="account-a",
            output_currency="EUR",
        )
    )

    assert result.currency == "EUR"
    access.assert_awaited_once()
    factory.assert_called_once_with(session)
    writer.write.assert_awaited_once()
    assert writer.write.await_args.args[0].output_currency == "EUR"
    clock.assert_called_once_with()


@pytest.mark.parametrize(
    "output_currency",
    ["", " ", "eur", "EuR", " EUR", "EUR ", "EU", "EURO", "ČES", 123, True, [], {}],
)
async def test_invalid_direct_output_currency_fails_before_authorization_and_writer(
    output_currency: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    access = AsyncMock()
    factory = Mock()
    clock = Mock(return_value=RAW_NOW)
    monkeypatch.setattr(manual_service, "require_account_access", access)

    with pytest.raises(AccountSnapshotUnavailableError):
        await ManualAccountSnapshotService(
            session,
            clock=clock,
            writer_factory=factory,
        ).recalculate(
            RecalculateAccountSnapshotCommand(
                principal=_principal(),
                account_id="account-a",
                output_currency=cast(Any, output_currency),
            )
        )

    cast(Any, session.rollback).assert_awaited_once_with()
    cast(Any, session.commit).assert_not_awaited()
    access.assert_not_awaited()
    factory.assert_not_called()
    clock.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [AccountAccessDeniedError(), AccountNotFoundError()],
)
async def test_inaccessible_accounts_share_hidden_error_and_never_call_writer(
    failure: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    monkeypatch.setattr(
        manual_service,
        "require_account_access",
        AsyncMock(side_effect=failure),
    )
    factory = Mock()

    with pytest.raises(AccountNotFoundError):
        await ManualAccountSnapshotService(
            session,
            clock=lambda: NOW,
            writer_factory=factory,
        ).recalculate(
            RecalculateAccountSnapshotCommand(principal=_principal(), account_id="account-a")
        )

    cast(Any, session.rollback).assert_awaited_once_with()
    cast(Any, session.commit).assert_not_awaited()
    factory.assert_not_called()


async def test_blank_account_is_hidden_before_writer() -> None:
    session = _session()
    factory = Mock()
    with pytest.raises(AccountNotFoundError):
        await ManualAccountSnapshotService(
            session,
            clock=lambda: NOW,
            writer_factory=factory,
        ).recalculate(RecalculateAccountSnapshotCommand(principal=_principal(), account_id=" "))
    factory.assert_not_called()


async def test_exact_replay_is_mapped_without_orm_leakage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    monkeypatch.setattr(manual_service, "require_account_access", AsyncMock())
    writer = Mock(
        write=AsyncMock(return_value=_write_result(AccountSnapshotWriteDisposition.replayed))
    )

    result = await ManualAccountSnapshotService(
        session,
        clock=lambda: RAW_NOW,
        writer_factory=Mock(return_value=writer),
    ).recalculate(RecalculateAccountSnapshotCommand(principal=_principal(), account_id="account-a"))

    assert result.status == "replayed"
    assert result.snapshot_id == "snapshot-a"
    assert not hasattr(result, "_sa_instance_state")


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (AccountSnapshotEvidenceStateError(), AccountSnapshotUnavailableError),
        (
            AccountSnapshotPersistenceProjectionError(),
            AccountSnapshotUnavailableError,
        ),
        (AccountSnapshotWriteStateError(), AccountSnapshotUnavailableError),
        (AccountSnapshotWriteConflictError(), AccountSnapshotConflictError),
    ],
)
async def test_writer_failures_map_to_generic_application_errors(
    failure: Exception,
    expected: type[Exception],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    monkeypatch.setattr(manual_service, "require_account_access", AsyncMock())
    writer = Mock(write=AsyncMock(side_effect=failure))

    with pytest.raises(expected) as raised:
        await ManualAccountSnapshotService(
            session,
            clock=lambda: NOW,
            writer_factory=Mock(return_value=writer),
        ).recalculate(
            RecalculateAccountSnapshotCommand(principal=_principal(), account_id="account-a")
        )

    assert str(raised.value) not in {str(failure)}
    writer.write.assert_awaited_once()


async def test_unexpected_writer_failure_is_not_converted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    monkeypatch.setattr(manual_service, "require_account_access", AsyncMock())
    failure = RuntimeError("controlled internal detail")
    writer = Mock(write=AsyncMock(side_effect=failure))

    with pytest.raises(RuntimeError) as raised:
        await ManualAccountSnapshotService(
            session,
            clock=lambda: NOW,
            writer_factory=Mock(return_value=writer),
        ).recalculate(
            RecalculateAccountSnapshotCommand(principal=_principal(), account_id="account-a")
        )
    assert raised.value is failure


def test_manual_bucket_is_deterministic_across_one_minute() -> None:
    assert canonical_manual_snapshot_bucket(RAW_NOW) == NOW
    assert canonical_manual_snapshot_bucket(RAW_NOW.replace(second=1, microsecond=1)) == NOW
    assert canonical_manual_snapshot_bucket(RAW_NOW + timedelta(minutes=1)) == NOW + timedelta(
        minutes=1
    )


def _client(test_settings: Settings) -> tuple[TestClient, AsyncSession]:
    app = create_app(test_settings)
    session = _session()

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_current_principal] = _principal
    app.dependency_overrides[get_db_session] = session_override
    return TestClient(app), session


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({}, None),
        ({"outputCurrency": None}, None),
        ({"outputCurrency": "EUR"}, "EUR"),
    ],
)
def test_request_model_accepts_optional_exact_output_currency(
    payload: dict[str, object],
    expected: str | None,
) -> None:
    request = AccountSnapshotRecalculateRequest.model_validate(payload)
    assert request.output_currency == expected


@pytest.mark.parametrize(
    "payload",
    [
        {"outputCurrency": ""},
        {"outputCurrency": " "},
        {"outputCurrency": "eur"},
        {"outputCurrency": "EuR"},
        {"outputCurrency": " EUR"},
        {"outputCurrency": "EUR "},
        {"outputCurrency": "EU"},
        {"outputCurrency": "EURO"},
        {"outputCurrency": "ČES"},
        {"outputCurrency": 123},
        {"outputCurrency": True},
        {"outputCurrency": []},
        {"outputCurrency": {}},
        {"outputCurrency": "EUR", "unknown": True},
        {"output_currency": "EUR"},
    ],
)
def test_request_model_rejects_noncanonical_or_extra_input(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AccountSnapshotRecalculateRequest.model_validate(payload)


def test_endpoint_openapi_contract_has_optional_body_and_authentication(
    test_settings: Settings,
) -> None:
    schema = create_app(test_settings).openapi()
    operation = schema["paths"]["/api/v1/accounts/{account_id}/snapshots/recalculate"]["post"]

    assert "required" not in operation["requestBody"]
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "anyOf": [
            {"$ref": "#/components/schemas/AccountSnapshotRecalculateRequest"},
            {"type": "null"},
        ],
        "title": "Request",
    }
    assert schema["components"]["schemas"]["AccountSnapshotRecalculateRequest"]["properties"] == {
        "outputCurrency": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "title": "Outputcurrency",
        }
    }
    assert (
        schema["components"]["schemas"]["AccountSnapshotRecalculateRequest"]["additionalProperties"]
        is False
    )
    assert operation["tags"] == ["snapshots"]
    assert operation["security"] == [{"InternalSessionToken": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AccountSnapshotRecalculateResponse"
    }


def test_endpoint_requires_valid_authentication(test_settings: Settings) -> None:
    app = create_app(test_settings)
    with TestClient(app) as client:
        missing = client.post("/api/v1/accounts/account-a/snapshots/recalculate")
        invalid = client.post(
            "/api/v1/accounts/account-a/snapshots/recalculate",
            headers={"Authorization": "Bearer invalid"},
        )
    assert (missing.status_code, missing.json()["error"]["code"]) == (
        401,
        "authentication_required",
    )
    assert (invalid.status_code, invalid.json()["error"]["code"]) == (
        401,
        "invalid_session_token",
    )


def test_endpoint_is_thin_and_serializes_public_camel_case_response(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = manual_service.RecalculateAccountSnapshotResult(
        snapshot_id="snapshot-a",
        account_id="account-a",
        status="created",
        item_count=2,
        timestamp=NOW,
        granularity=SnapshotGranularity.minute,
        currency="CZK",
    )
    recalculate = AsyncMock(return_value=result)
    monkeypatch.setattr(ManualAccountSnapshotService, "recalculate", recalculate)
    client, _ = _client(test_settings)

    with client:
        response = client.post("/api/v1/accounts/account-a/snapshots/recalculate")

    assert response.status_code == 200
    assert response.json() == {
        "snapshotId": "snapshot-a",
        "accountId": "account-a",
        "status": "created",
        "itemCount": 2,
        "timestamp": "2026-07-28T10:20:00.000",
        "granularity": "minute",
        "currency": "CZK",
    }
    assert recalculate.await_args is not None
    command = recalculate.await_args.args[0]
    assert command.account_id == "account-a"
    assert command.principal.user_id == "user-a"
    assert command.output_currency is None


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({}, None),
        (None, None),
        ({"outputCurrency": None}, None),
        ({"outputCurrency": "EUR"}, "EUR"),
    ],
)
def test_endpoint_forwards_optional_output_currency_exactly(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, object] | None,
    expected: str | None,
) -> None:
    result = manual_service.RecalculateAccountSnapshotResult(
        snapshot_id="snapshot-a",
        account_id="account-a",
        status="created",
        item_count=2,
        timestamp=NOW,
        granularity=SnapshotGranularity.minute,
        currency="EUR" if expected == "EUR" else "CZK",
    )
    recalculate = AsyncMock(return_value=result)
    monkeypatch.setattr(ManualAccountSnapshotService, "recalculate", recalculate)
    client, _ = _client(test_settings)

    with client:
        response = client.post(
            "/api/v1/accounts/account-a/snapshots/recalculate",
            json=body,
        )

    assert response.status_code == 200
    assert response.json()["currency"] == ("EUR" if expected == "EUR" else "CZK")
    recalculate.assert_awaited_once()
    assert recalculate.await_args is not None
    assert recalculate.await_args.args[0].output_currency == expected


@pytest.mark.parametrize(
    "body",
    [
        {"outputCurrency": ""},
        {"outputCurrency": "eur"},
        {"outputCurrency": "EUR "},
        {"outputCurrency": "EU"},
        {"outputCurrency": "EURO"},
        {"outputCurrency": "ČES"},
        {"outputCurrency": 123},
        {"outputCurrency": True},
        {"outputCurrency": []},
        {"outputCurrency": {}},
        {"outputCurrency": "EUR", "unknown": True},
    ],
)
def test_endpoint_rejects_invalid_body_before_service(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, object],
) -> None:
    recalculate = AsyncMock()
    monkeypatch.setattr(ManualAccountSnapshotService, "recalculate", recalculate)
    client, _ = _client(test_settings)

    with client:
        response = client.post(
            "/api/v1/accounts/account-a/snapshots/recalculate",
            json=body,
        )

    assert response.status_code == 422
    recalculate.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (
            AccountSnapshotUnavailableError(),
            "account_snapshot_unavailable",
            "Account snapshot cannot be created from the current account data.",
        ),
        (
            AccountSnapshotConflictError(),
            "account_snapshot_conflict",
            "Account snapshot conflicts with existing data.",
        ),
    ],
)
def test_endpoint_maps_only_generic_public_errors(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    code: str,
    message: str,
) -> None:
    monkeypatch.setattr(
        ManualAccountSnapshotService,
        "recalculate",
        AsyncMock(side_effect=error),
    )
    client, _ = _client(test_settings)
    with client:
        response = client.post("/api/v1/accounts/account-a/snapshots/recalculate")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"] == message


def test_response_contract_rejects_internal_evidence() -> None:
    with pytest.raises(ValueError):
        AccountSnapshotRecalculateResponse.model_validate(
            {
                "snapshot_id": "snapshot-a",
                "account_id": "account-a",
                "status": "created",
                "item_count": 0,
                "timestamp": NOW,
                "granularity": "minute",
                "currency": "CZK",
                "selected_price_ids": ["secret"],
            }
        )


def test_application_command_and_result_are_frozen() -> None:
    command = RecalculateAccountSnapshotCommand(
        principal=_principal(),
        account_id="account-a",
        output_currency="EUR",
    )
    result = manual_service.RecalculateAccountSnapshotResult(
        snapshot_id="snapshot-a",
        account_id="account-a",
        status="created",
        item_count=0,
        timestamp=NOW,
        granularity=SnapshotGranularity.minute,
        currency="EUR",
    )

    def mutate(value: object, attribute: str) -> None:
        setattr(value, attribute, "USD")

    with pytest.raises(FrozenInstanceError):
        mutate(command, "output_currency")
    with pytest.raises(FrozenInstanceError):
        mutate(result, "currency")
