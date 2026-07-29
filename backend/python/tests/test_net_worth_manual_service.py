from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.db.models.users import UserModel
from app.main import create_app
from app.modules.net_worth.evidence_service import (
    NetWorthEvidenceStateError,
    SelectedAccountSnapshotIdentity,
)
from app.modules.net_worth.manual_service import (
    CURRENT_NET_WORTH_CALCULATION_VERSION,
    ManualNetWorthSnapshotService,
    NetWorthSnapshotConflictError,
    NetWorthSnapshotUnavailableError,
    RecalculateNetWorthSnapshotCommand,
    RecalculateNetWorthSnapshotResult,
    canonical_manual_net_worth_bucket,
)
from app.modules.net_worth.models import NetWorthSnapshotRecalculateResponse
from app.modules.net_worth.persistence_projection import (
    NetWorthSnapshotPersistenceProjectionError,
)
from app.modules.net_worth.writer import (
    NetWorthSnapshotWriteConflictError,
    NetWorthSnapshotWriteDisposition,
    NetWorthSnapshotWriteResult,
    NetWorthSnapshotWriteStateError,
)

BUCKET = datetime(2026, 7, 28, 16, 47)
RAW_NOW = datetime(
    2026,
    7,
    28,
    18,
    47,
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


def _user(user_id: str = "user-a", currency: str = "CZK") -> UserModel:
    return UserModel(
        id=user_id,
        email=f"{user_id}@example.com",
        name=user_id,
        password_hash=None,
        base_currency=currency,
        created_at=BUCKET,
        updated_at=BUCKET,
    )


def _write_result(
    disposition: NetWorthSnapshotWriteDisposition = NetWorthSnapshotWriteDisposition.created,
) -> NetWorthSnapshotWriteResult:
    return NetWorthSnapshotWriteResult(
        snapshot_id="snapshot-a",
        user_id="user-a",
        disposition=disposition,
        timestamp=BUCKET,
        granularity=SnapshotGranularity.minute,
        currency="CZK",
        account_count=3,
        selected_account_snapshot_count=3,
    )


def _session(*, active: bool = True, remain_active_after_commit: bool = False) -> AsyncSession:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    state = {"active": active}
    cast(Any, session.in_transaction).side_effect = lambda: state["active"]

    async def commit() -> None:
        if not remain_active_after_commit:
            state["active"] = False

    async def rollback() -> None:
        state["active"] = False

    cast(Any, session.commit).side_effect = commit
    cast(Any, session.rollback).side_effect = rollback
    return session


async def test_principal_user_and_persisted_currency_build_exact_writer_command() -> None:
    session = _session()
    repository = Mock(load_user=AsyncMock(return_value=_user(currency="EUR")))
    writer = Mock(
        write=AsyncMock(
            return_value=NetWorthSnapshotWriteResult(
                snapshot_id="snapshot-eur",
                user_id="user-a",
                disposition=NetWorthSnapshotWriteDisposition.created,
                timestamp=BUCKET,
                granularity=SnapshotGranularity.minute,
                currency="EUR",
                account_count=2,
                selected_account_snapshot_count=2,
            )
        )
    )
    clock = Mock(return_value=RAW_NOW)
    factory = Mock(return_value=writer)

    result = await ManualNetWorthSnapshotService(
        session,
        repository=repository,
        clock=clock,
        writer_factory=factory,
    ).recalculate(RecalculateNetWorthSnapshotCommand(principal=_principal()))

    repository.load_user.assert_awaited_once_with("user-a")
    cast(Any, session.commit).assert_awaited_once_with()
    cast(Any, session.rollback).assert_not_awaited()
    factory.assert_called_once_with(session)
    writer.write.assert_awaited_once()
    command = writer.write.await_args.args[0]
    assert command.user_id == "user-a"
    assert command.snapshot_timestamp == BUCKET
    assert command.granularity is SnapshotGranularity.minute
    assert command.currency == "EUR"
    assert command.source is SnapshotSource.manual_recalculation
    assert command.calculation_version == CURRENT_NET_WORTH_CALCULATION_VERSION
    assert command.calculated_at == BUCKET
    assert command.created_at == BUCKET
    assert command.is_recalculated is True
    assert command.required_account_snapshot_identities is None
    assert result.currency == "EUR"
    assert result.status == "created"
    clock.assert_called_once_with()


@pytest.mark.parametrize(
    "command",
    [
        cast(Any, object()),
        RecalculateNetWorthSnapshotCommand(principal=cast(Any, object())),
        RecalculateNetWorthSnapshotCommand(principal=_principal("")),
        RecalculateNetWorthSnapshotCommand(principal=_principal(" user-a ")),
    ],
)
async def test_malformed_command_rolls_back_before_repository_or_writer(
    command: object,
) -> None:
    session = _session()
    repository = Mock(load_user=AsyncMock())
    factory = Mock()

    with pytest.raises(NetWorthSnapshotUnavailableError):
        await ManualNetWorthSnapshotService(
            session,
            repository=repository,
            writer_factory=factory,
        ).recalculate(cast(Any, command))

    repository.load_user.assert_not_awaited()
    factory.assert_not_called()
    cast(Any, session.rollback).assert_awaited_once_with()
    cast(Any, session.commit).assert_not_awaited()


@pytest.mark.parametrize(
    "user",
    [
        None,
        cast(Any, object()),
        _user("different-user"),
        _user(currency="czk"),
        _user(currency=" CZK"),
        _user(currency="CZK "),
        _user(currency="CZ"),
        _user(currency="CZKK"),
        _user(currency="C1K"),
    ],
)
async def test_invalid_persisted_user_or_currency_fails_closed(
    user: object,
) -> None:
    session = _session()
    repository = Mock(load_user=AsyncMock(return_value=user))
    factory = Mock()

    with pytest.raises(NetWorthSnapshotUnavailableError):
        await ManualNetWorthSnapshotService(
            session,
            repository=repository,
            writer_factory=factory,
        ).recalculate(RecalculateNetWorthSnapshotCommand(principal=_principal()))

    factory.assert_not_called()
    cast(Any, session.rollback).assert_awaited_once_with()
    cast(Any, session.rollback).assert_awaited_once_with()
    cast(Any, session.commit).assert_not_awaited()


async def test_repository_failure_rolls_back_and_propagates() -> None:
    failure = RuntimeError("controlled repository failure")
    session = _session()
    factory = Mock()

    with pytest.raises(RuntimeError) as raised:
        await ManualNetWorthSnapshotService(
            session,
            repository=Mock(load_user=AsyncMock(side_effect=failure)),
            writer_factory=factory,
        ).recalculate(RecalculateNetWorthSnapshotCommand(principal=_principal()))

    assert raised.value is failure
    cast(Any, session.rollback).assert_awaited_once_with()
    factory.assert_not_called()


async def test_commit_finishes_before_writer_factory_receives_idle_session() -> None:
    session = _session()
    events: list[str] = []
    repository = Mock(load_user=AsyncMock(return_value=_user()))
    writer = Mock(write=AsyncMock(return_value=_write_result()))
    original_commit = cast(Any, session.commit).side_effect

    async def commit() -> None:
        events.append("commit")
        await original_commit()

    cast(Any, session.commit).side_effect = commit

    def factory(received: AsyncSession) -> object:
        events.append("factory")
        assert received is session
        assert received.in_transaction() is False
        return writer

    await ManualNetWorthSnapshotService(
        session,
        repository=repository,
        clock=lambda: BUCKET,
        writer_factory=cast(Any, factory),
    ).recalculate(RecalculateNetWorthSnapshotCommand(principal=_principal()))

    assert events == ["commit", "factory"]


async def test_transaction_remaining_active_after_commit_is_internal_failure() -> None:
    session = _session(remain_active_after_commit=True)
    factory = Mock()

    with pytest.raises(
        RuntimeError,
        match="Net-worth snapshot writer requires an idle database session",
    ):
        await ManualNetWorthSnapshotService(
            session,
            repository=Mock(load_user=AsyncMock(return_value=_user())),
            clock=lambda: BUCKET,
            writer_factory=factory,
        ).recalculate(RecalculateNetWorthSnapshotCommand(principal=_principal()))

    factory.assert_not_called()


def test_manual_bucket_converts_aware_time_to_utc_and_is_deterministic() -> None:
    assert canonical_manual_net_worth_bucket(RAW_NOW) == BUCKET
    assert (
        canonical_manual_net_worth_bucket(BUCKET.replace(second=59, microsecond=999999)) == BUCKET
    )
    assert canonical_manual_net_worth_bucket(RAW_NOW + timedelta(minutes=1)) == (
        BUCKET + timedelta(minutes=1)
    )
    assert canonical_manual_net_worth_bucket(BUCKET).tzinfo is None


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (NetWorthEvidenceStateError(), NetWorthSnapshotUnavailableError),
        (
            NetWorthSnapshotPersistenceProjectionError(),
            NetWorthSnapshotUnavailableError,
        ),
        (NetWorthSnapshotWriteStateError(), NetWorthSnapshotUnavailableError),
        (NetWorthSnapshotWriteConflictError(), NetWorthSnapshotConflictError),
    ],
)
async def test_writer_failures_map_to_generic_public_errors_with_cause(
    failure: Exception,
    expected: type[Exception],
) -> None:
    session = _session()
    writer = Mock(write=AsyncMock(side_effect=failure))

    with pytest.raises(expected) as raised:
        await ManualNetWorthSnapshotService(
            session,
            repository=Mock(load_user=AsyncMock(return_value=_user())),
            clock=lambda: BUCKET,
            writer_factory=Mock(return_value=writer),
        ).recalculate(RecalculateNetWorthSnapshotCommand(principal=_principal()))

    assert raised.value.__cause__ is failure
    assert str(failure) not in str(raised.value)
    writer.write.assert_awaited_once()


async def test_unexpected_writer_failure_propagates_unchanged() -> None:
    failure = RuntimeError("controlled internal detail")
    session = _session()
    writer = Mock(write=AsyncMock(side_effect=failure))

    with pytest.raises(RuntimeError) as raised:
        await ManualNetWorthSnapshotService(
            session,
            repository=Mock(load_user=AsyncMock(return_value=_user())),
            clock=lambda: BUCKET,
            writer_factory=Mock(return_value=writer),
        ).recalculate(RecalculateNetWorthSnapshotCommand(principal=_principal()))

    assert raised.value is failure


async def test_replayed_result_maps_counts_without_orm_or_identity_leakage() -> None:
    session = _session()
    internal_identities = (SelectedAccountSnapshotIdentity("account-a", "source-a"),)
    writer = Mock(
        write=AsyncMock(
            return_value=NetWorthSnapshotWriteResult(
                snapshot_id="snapshot-a",
                user_id="user-a",
                disposition=NetWorthSnapshotWriteDisposition.replayed,
                timestamp=BUCKET,
                granularity=SnapshotGranularity.minute,
                currency="CZK",
                account_count=1,
                selected_account_snapshot_count=1,
                selected_account_snapshot_identities=internal_identities,
            )
        )
    )

    result = await ManualNetWorthSnapshotService(
        session,
        repository=Mock(load_user=AsyncMock(return_value=_user())),
        clock=lambda: BUCKET,
        writer_factory=Mock(return_value=writer),
    ).recalculate(RecalculateNetWorthSnapshotCommand(principal=_principal()))

    assert result.status == "replayed"
    assert result.account_count == 1
    assert result.selected_account_snapshot_count == 1
    assert not hasattr(result, "user_id")
    assert not hasattr(result, "selected_account_ids")
    assert not hasattr(result, "selected_account_snapshot_identities")
    with pytest.raises(FrozenInstanceError):
        result.__setattr__("status", "created")


def _client(
    test_settings: Settings,
    *,
    principal: AuthenticatedPrincipal | None = None,
) -> tuple[TestClient, AsyncSession]:
    app = create_app(test_settings)
    session = _session()

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = session_override
    if principal is not None:
        app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app), session


def test_endpoint_openapi_has_no_body_path_or_query_and_uses_authentication(
    test_settings: Settings,
) -> None:
    operation = create_app(test_settings).openapi()["paths"][
        "/api/v1/net-worth/snapshots/recalculate"
    ]["post"]

    assert "requestBody" not in operation
    assert operation.get("parameters", []) == []
    assert operation["tags"] == ["net-worth"]
    assert operation["security"] == [{"InternalSessionToken": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/NetWorthSnapshotRecalculateResponse"
    }


def test_missing_and_invalid_authentication_keep_existing_public_errors(
    test_settings: Settings,
) -> None:
    app = create_app(test_settings)
    session_calls = 0

    async def session_override() -> AsyncIterator[AsyncSession]:
        nonlocal session_calls
        session_calls += 1
        yield _session()

    app.dependency_overrides[get_db_session] = session_override
    with TestClient(app) as client:
        missing = client.post("/api/v1/net-worth/snapshots/recalculate")
        invalid = client.post(
            "/api/v1/net-worth/snapshots/recalculate",
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
    assert session_calls == 0


def test_endpoint_is_thin_and_returns_exact_camel_case_contract(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = RecalculateNetWorthSnapshotResult(
        snapshot_id="snapshot-a",
        status="created",
        timestamp=BUCKET,
        granularity=SnapshotGranularity.minute,
        currency="CZK",
        account_count=3,
        selected_account_snapshot_count=3,
    )
    recalculate = AsyncMock(return_value=result)
    monkeypatch.setattr(ManualNetWorthSnapshotService, "recalculate", recalculate)
    client, _ = _client(test_settings, principal=_principal())

    with client:
        response = client.post("/api/v1/net-worth/snapshots/recalculate")

    assert response.status_code == 200
    assert response.json() == {
        "snapshotId": "snapshot-a",
        "status": "created",
        "timestamp": "2026-07-28T16:47:00.000",
        "granularity": "minute",
        "currency": "CZK",
        "accountCount": 3,
        "selectedAccountSnapshotCount": 3,
    }
    recalculate.assert_awaited_once()
    assert recalculate.await_args is not None
    command = recalculate.await_args.args[0]
    assert command.principal.user_id == "user-a"
    assert not hasattr(command, "user_id")


@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (
            NetWorthSnapshotUnavailableError(),
            "net_worth_snapshot_unavailable",
            "Net-worth snapshot cannot be created from the current account data.",
        ),
        (
            NetWorthSnapshotConflictError(),
            "net_worth_snapshot_conflict",
            "Net-worth snapshot conflicts with existing data.",
        ),
    ],
)
def test_endpoint_returns_only_generic_409_errors(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    code: str,
    message: str,
) -> None:
    monkeypatch.setattr(
        ManualNetWorthSnapshotService,
        "recalculate",
        AsyncMock(side_effect=error),
    )
    client, _ = _client(test_settings, principal=_principal())
    with client:
        response = client.post("/api/v1/net-worth/snapshots/recalculate")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["message"] == message
    payload = response.text
    assert "user-a" not in payload
    assert "account-" not in payload
    assert "snapshot-" not in payload


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("userId", "user-a"),
        ("selectedAccountIds", ["account-a"]),
        ("selectedAccountSnapshotIds", ["source-a"]),
        (
            "selectedAccountSnapshotIdentities",
            [{"accountId": "account-a", "snapshotId": "source-a"}],
        ),
        ("projection", {}),
        ("audit", {}),
    ],
)
def test_response_rejects_every_internal_extra_field(field: str, value: object) -> None:
    payload: dict[str, object] = {
        "snapshot_id": "snapshot-a",
        "status": "created",
        "timestamp": BUCKET,
        "granularity": "minute",
        "currency": "CZK",
        "account_count": 3,
        "selected_account_snapshot_count": 3,
        field: value,
    }
    with pytest.raises(ValueError):
        NetWorthSnapshotRecalculateResponse.model_validate(payload)
