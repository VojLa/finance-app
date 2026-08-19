from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
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
from app.db.models.enums import AccountMemberRole, LiabilityBalanceSource
from app.main import create_app
from app.modules.accounts.access import AccountAccessDeniedError, AccountNotFoundError
from app.modules.liabilities import manual_service
from app.modules.liabilities.manual_models import (
    ManualLiabilityBalanceCreateRequest,
    ManualLiabilityBalanceCreateResponse,
)
from app.modules.liabilities.manual_service import (
    CreateManualLiabilityBalanceCommand,
    ManualLiabilityBalanceConflictError,
    ManualLiabilityBalanceService,
    ManualLiabilityBalanceUnavailableError,
)
from app.modules.liabilities.writer import (
    LiabilityBalanceWriteConflictError,
    LiabilityBalanceWriteDisposition,
    LiabilityBalanceWriteResult,
    LiabilityBalanceWriteStateError,
)

EFFECTIVE_AT = datetime(2036, 8, 19, 10, 20, 30, 123000)
CREATED_AT = datetime(2036, 8, 19, 10, 21, 0, 456000)
PATH = "/api/v1/accounts/account-a/liability-balances"
BODY = {
    "effectiveAt": "2036-08-19T10:20:30.123",
    "currency": "CZK",
    "outstandingPrincipal": "100.000000",
    "accruedInterest": "2.000000",
    "feesOutstanding": "3.000000",
}


def test_runtime_clock_respects_database_millisecond_precision() -> None:
    value = manual_service.current_liability_balance_timestamp()

    assert value.tzinfo is None
    assert value.microsecond % 1_000 == 0


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="user-a", email="a@example.test", name="A")


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


def _write_result(
    disposition: LiabilityBalanceWriteDisposition = LiabilityBalanceWriteDisposition.created,
) -> LiabilityBalanceWriteResult:
    return LiabilityBalanceWriteResult(
        balance_id="balance-a",
        account_id="account-a",
        effective_at=EFFECTIVE_AT,
        currency="CZK",
        total_outstanding=Decimal("105.000000"),
        source=LiabilityBalanceSource.manual,
        disposition=disposition,
    )


@pytest.mark.parametrize(
    "role",
    [AccountMemberRole.owner, AccountMemberRole.admin, AccountMemberRole.editor],
)
async def test_authorized_roles_force_manual_writer_command(
    role: AccountMemberRole,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    access = AsyncMock(return_value=Mock(role=role))
    writer = Mock(write=AsyncMock(return_value=_write_result()))
    factory = Mock(return_value=writer)
    monkeypatch.setattr(manual_service, "require_account_access", access)

    result = await ManualLiabilityBalanceService(
        session,
        clock=lambda: CREATED_AT,
        writer_factory=factory,
    ).create(
        CreateManualLiabilityBalanceCommand(
            principal=_principal(),
            account_id="account-a",
            effective_at=EFFECTIVE_AT,
            currency="CZK",
            outstanding_principal=Decimal("100.000000"),
            accrued_interest=Decimal("2.000000"),
            fees_outstanding=Decimal("3.000000"),
        )
    )

    assert result.status == "created"
    assert result.source == "manual"
    assert access.await_args is not None
    assert access.await_args.kwargs["allowed_roles"] == manual_service.WRITE_ROLES
    cast(Any, session.commit).assert_awaited_once_with()
    writer.write.assert_awaited_once()
    command = writer.write.await_args.args[0]
    assert command.source is LiabilityBalanceSource.manual
    assert command.external_id is None
    assert command.created_at == CREATED_AT
    assert command.outstanding_principal == Decimal("100.000000")
    assert command.accrued_interest == Decimal("2.000000")
    assert command.fees_outstanding == Decimal("3.000000")


async def test_viewer_foreign_and_archived_access_remain_indistinguishable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    monkeypatch.setattr(
        manual_service,
        "require_account_access",
        AsyncMock(side_effect=AccountAccessDeniedError()),
    )
    writer_factory = Mock()

    with pytest.raises(AccountNotFoundError):
        await ManualLiabilityBalanceService(session, writer_factory=writer_factory).create(
            CreateManualLiabilityBalanceCommand(
                principal=_principal(),
                account_id="account-a",
                effective_at=EFFECTIVE_AT,
                currency="CZK",
                outstanding_principal=Decimal(0),
                accrued_interest=Decimal(0),
                fees_outstanding=Decimal(0),
            )
        )

    cast(Any, session.rollback).assert_awaited_once_with()
    writer_factory.assert_not_called()


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (LiabilityBalanceWriteStateError(), ManualLiabilityBalanceUnavailableError),
        (LiabilityBalanceWriteConflictError(), ManualLiabilityBalanceConflictError),
    ],
)
async def test_writer_errors_are_mapped_to_safe_application_errors(
    failure: Exception,
    expected: type[Exception],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    monkeypatch.setattr(manual_service, "require_account_access", AsyncMock())
    writer = Mock(write=AsyncMock(side_effect=failure))

    with pytest.raises(expected) as raised:
        await ManualLiabilityBalanceService(
            session,
            writer_factory=Mock(return_value=writer),
        ).create(
            CreateManualLiabilityBalanceCommand(
                principal=_principal(),
                account_id="account-a",
                effective_at=EFFECTIVE_AT,
                currency="CZK",
                outstanding_principal=Decimal(0),
                accrued_interest=Decimal(0),
                fees_outstanding=Decimal(0),
            )
        )

    assert str(failure) not in str(raised.value)


def test_request_requires_all_exact_explicit_components_and_accepts_zero() -> None:
    request = ManualLiabilityBalanceCreateRequest.model_validate(
        {
            "effectiveAt": "2036-08-19T10:20:30.123",
            "currency": "CZK",
            "outstandingPrincipal": "0.000000",
            "accruedInterest": "0.000000",
            "feesOutstanding": "0.000000",
        }
    )
    assert (
        request.outstanding_principal == request.accrued_interest == request.fees_outstanding == 0
    )

    invalid = [
        {},
        {key: value for key, value in BODY.items() if key != "outstandingPrincipal"},
        {**BODY, "outstandingPrincipal": 100},
        {**BODY, "accruedInterest": "-0.000001"},
        {**BODY, "feesOutstanding": "0.0000001"},
        {**BODY, "currency": "eur"},
        {**BODY, "effectiveAt": "2036-08-19T10:20:30.123Z"},
        {**BODY, "unknown": "value"},
    ]
    for payload in invalid:
        with pytest.raises(ValidationError):
            ManualLiabilityBalanceCreateRequest.model_validate(payload)


def _client(test_settings: Settings) -> tuple[TestClient, AsyncSession]:
    app = create_app(test_settings)
    session = _session()

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_current_principal] = _principal
    app.dependency_overrides[get_db_session] = session_override
    return TestClient(app), session


def test_endpoint_openapi_contract_is_authenticated_and_explicit(test_settings: Settings) -> None:
    schema = create_app(test_settings).openapi()
    operation = schema["paths"]["/api/v1/accounts/{account_id}/liability-balances"]["post"]

    assert operation["security"] == [{"InternalSessionToken": []}]
    assert operation["tags"] == ["liabilities"]
    assert operation["requestBody"]["required"] is True
    assert operation["responses"]["201"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ManualLiabilityBalanceCreateResponse"
    }
    request_schema = schema["components"]["schemas"]["ManualLiabilityBalanceCreateRequest"]
    assert set(request_schema["required"]) == {
        "effectiveAt",
        "currency",
        "outstandingPrincipal",
        "accruedInterest",
        "feesOutstanding",
    }
    assert request_schema["additionalProperties"] is False


def test_endpoint_is_thin_and_serializes_only_safe_result(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = AsyncMock(
        return_value=manual_service.CreateManualLiabilityBalanceResult(
            balance_id="balance-a",
            account_id="account-a",
            effective_at=EFFECTIVE_AT,
            currency="CZK",
            total_outstanding=Decimal("105.000000"),
            source="manual",
            status="replayed",
        )
    )
    monkeypatch.setattr(ManualLiabilityBalanceService, "create", create)
    client, _ = _client(test_settings)

    with client:
        response = client.post(PATH, json=BODY)

    assert response.status_code == 201
    assert response.json() == {
        "balanceId": "balance-a",
        "accountId": "account-a",
        "effectiveAt": "2036-08-19T10:20:30.123",
        "currency": "CZK",
        "totalOutstanding": "105.000000",
        "source": "manual",
        "status": "replayed",
    }
    assert create.await_args is not None
    command = create.await_args.args[0]
    assert command.account_id == "account-a"
    assert command.effective_at == EFFECTIVE_AT
    assert command.outstanding_principal == Decimal("100.000000")


def test_endpoint_rejects_invalid_request_before_service(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = AsyncMock()
    monkeypatch.setattr(ManualLiabilityBalanceService, "create", create)
    client, _ = _client(test_settings)

    with client:
        response = client.post(PATH, json={**BODY, "feesOutstanding": 0})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    create.assert_not_awaited()


def test_response_contract_excludes_input_components_and_internal_fields() -> None:
    response = ManualLiabilityBalanceCreateResponse.model_validate(
        {
            "balance_id": "balance-a",
            "account_id": "account-a",
            "effective_at": EFFECTIVE_AT,
            "currency": "CZK",
            "total_outstanding": Decimal("0.000000"),
            "source": "manual",
            "status": "created",
        }
    )
    assert response.model_dump(mode="json", by_alias=True) == {
        "balanceId": "balance-a",
        "accountId": "account-a",
        "effectiveAt": "2036-08-19T10:20:30.123",
        "currency": "CZK",
        "totalOutstanding": "0.000000",
        "source": "manual",
        "status": "created",
    }
    with pytest.raises(ValidationError):
        ManualLiabilityBalanceCreateResponse.model_validate(
            {**response.model_dump(), "created_at": CREATED_AT}
        )
