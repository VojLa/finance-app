from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import asdict
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
from app.main import create_app
from app.modules.holdings import orchestration
from app.modules.holdings.models import HoldingRebuildResponse
from app.modules.holdings.orchestration import (
    HoldingRebuildApplicationService,
    HoldingRebuildUnavailableError,
    RebuildHoldingsCommand,
    normalize_rebuild_timestamp,
)
from app.modules.holdings.projection import HoldingProjectionStateError
from app.modules.holdings.rebuild_service import HoldingRebuildResult

NOW = datetime(2026, 7, 27, 15, 0, 0, 123000)


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-a",
        email="user-a@example.com",
        name="User A",
    )


def _result(*, replayed: bool = False) -> HoldingRebuildResult:
    return HoldingRebuildResult(
        account_id="account-a",
        created=0 if replayed else 1,
        updated=0,
        deleted=0,
        total=1,
        replayed=replayed,
        rebuilt_at=None if replayed else NOW,
    )


def _client(test_settings: Settings) -> tuple[TestClient, AsyncSession]:
    app = create_app(test_settings)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_current_principal] = _principal
    app.dependency_overrides[get_db_session] = session_override
    return TestClient(app), session


def test_rebuild_endpoint_is_registered_without_request_body(test_settings: Settings) -> None:
    operation = create_app(test_settings).openapi()["paths"][
        "/api/v1/accounts/{account_id}/holdings/rebuild"
    ]["post"]

    assert "requestBody" not in operation
    assert operation["tags"] == ["holdings"]
    assert operation["security"] == [{"InternalSessionToken": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/HoldingRebuildResponse"
    }


def test_rebuild_endpoint_requires_valid_authentication(test_settings: Settings) -> None:
    app = create_app(test_settings)
    with TestClient(app) as client:
        missing = client.post("/api/v1/accounts/account-a/holdings/rebuild")
        invalid = client.post(
            "/api/v1/accounts/account-a/holdings/rebuild",
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


def test_rebuild_endpoint_is_thin_and_exposes_only_public_result(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rebuild = AsyncMock(
        return_value=HoldingRebuildResponse(
            account_id="account-a",
            created=1,
            updated=0,
            deleted=0,
            total=1,
            replayed=False,
            rebuilt_at=NOW,
        )
    )
    monkeypatch.setattr(HoldingRebuildApplicationService, "rebuild", rebuild)
    client, _ = _client(test_settings)

    with client:
        response = client.post("/api/v1/accounts/account-a/holdings/rebuild")

    assert response.status_code == 200
    assert response.json() == {
        "account_id": "account-a",
        "created": 1,
        "updated": 0,
        "deleted": 0,
        "total": 1,
        "replayed": False,
        "rebuilt_at": "2026-07-27T15:00:00.123000",
    }
    assert set(response.json()) == {
        "account_id",
        "created",
        "updated",
        "deleted",
        "total",
        "replayed",
        "rebuilt_at",
    }
    assert rebuild.await_args is not None
    command = rebuild.await_args.args[0]
    assert command.principal.user_id == "user-a"
    assert command.account_id == "account-a"


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (
            HoldingRebuildUnavailableError(),
            409,
            "holding_rebuild_unavailable",
        ),
    ],
)
def test_rebuild_endpoint_maps_public_domain_error(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    monkeypatch.setattr(
        HoldingRebuildApplicationService,
        "rebuild",
        AsyncMock(side_effect=error),
    )
    client, _ = _client(test_settings)
    with client:
        response = client.post("/api/v1/accounts/account-a/holdings/rebuild")

    assert response.status_code == status_code
    assert response.json()["error"] == {
        "code": code,
        "message": "Holdings cannot be rebuilt from the current canonical history.",
        "request_id": response.headers["x-request-id"],
    }


def test_rebuild_endpoint_does_not_convert_unexpected_failure(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = RuntimeError("controlled unexpected failure")
    monkeypatch.setattr(
        HoldingRebuildApplicationService,
        "rebuild",
        AsyncMock(side_effect=failure),
    )
    client, _ = _client(test_settings)

    with client, pytest.raises(RuntimeError) as raised:
        client.post("/api/v1/accounts/account-a/holdings/rebuild")

    assert raised.value is failure


async def test_application_service_locks_membership_uses_one_clock_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    access = AsyncMock()
    rebuild = AsyncMock(return_value=_result())
    clock = Mock(
        return_value=datetime(
            2026,
            7,
            27,
            17,
            0,
            0,
            123999,
            tzinfo=timezone(timedelta(hours=2)),
        )
    )
    monkeypatch.setattr(orchestration, "require_account_access", access)
    monkeypatch.setattr(orchestration.HoldingRebuildService, "rebuild", rebuild)

    response = await HoldingRebuildApplicationService(session, clock=clock).rebuild(
        RebuildHoldingsCommand(principal=_principal(), account_id="account-a")
    )

    assert response == HoldingRebuildResponse.model_validate(asdict(_result()))
    assert access.await_args is not None
    assert rebuild.await_args is not None
    assert access.await_args.kwargs["for_update"] is True
    assert access.await_args.kwargs["allowed_roles"] == orchestration.WRITE_ROLES
    assert rebuild.await_args.kwargs["rebuilt_at"] == NOW
    clock.assert_called_once_with()
    cast(Any, session.commit).assert_awaited_once_with()
    cast(Any, session.rollback).assert_not_awaited()


async def test_application_service_preserves_exact_replay_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    monkeypatch.setattr(orchestration, "require_account_access", AsyncMock())
    monkeypatch.setattr(
        orchestration.HoldingRebuildService,
        "rebuild",
        AsyncMock(return_value=_result(replayed=True)),
    )

    response = await HoldingRebuildApplicationService(session, clock=lambda: NOW).rebuild(
        RebuildHoldingsCommand(principal=_principal(), account_id="account-a")
    )

    assert response.replayed is True
    assert response.rebuilt_at is None
    assert (response.created, response.updated, response.deleted, response.total) == (0, 0, 0, 1)
    cast(Any, session.commit).assert_awaited_once_with()


async def test_domain_failure_rolls_back_and_maps_to_stable_public_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    monkeypatch.setattr(orchestration, "require_account_access", AsyncMock())
    monkeypatch.setattr(
        orchestration.HoldingRebuildService,
        "rebuild",
        AsyncMock(side_effect=HoldingProjectionStateError()),
    )

    with pytest.raises(HoldingRebuildUnavailableError):
        await HoldingRebuildApplicationService(session, clock=lambda: NOW).rebuild(
            RebuildHoldingsCommand(principal=_principal(), account_id="account-a")
        )

    cast(Any, session.rollback).assert_awaited_once_with()
    cast(Any, session.commit).assert_not_awaited()


async def test_unexpected_failure_rolls_back_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    failure = RuntimeError("controlled database failure")
    monkeypatch.setattr(orchestration, "require_account_access", AsyncMock())
    monkeypatch.setattr(
        orchestration.HoldingRebuildService,
        "rebuild",
        AsyncMock(side_effect=failure),
    )

    with pytest.raises(RuntimeError) as raised:
        await HoldingRebuildApplicationService(session, clock=lambda: NOW).rebuild(
            RebuildHoldingsCommand(principal=_principal(), account_id="account-a")
        )

    assert raised.value is failure
    cast(Any, session.rollback).assert_awaited_once_with()
    cast(Any, session.commit).assert_not_awaited()


async def test_response_is_validated_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    monkeypatch.setattr(orchestration, "require_account_access", AsyncMock())
    monkeypatch.setattr(
        orchestration.HoldingRebuildService,
        "rebuild",
        AsyncMock(return_value=_result()),
    )
    monkeypatch.setattr(
        orchestration,
        "HoldingRebuildResponse",
        Mock(side_effect=ValueError("controlled response failure")),
    )

    with pytest.raises(ValueError, match="controlled response failure"):
        await HoldingRebuildApplicationService(session, clock=lambda: NOW).rebuild(
            RebuildHoldingsCommand(principal=_principal(), account_id="account-a")
        )

    cast(Any, session.commit).assert_not_awaited()
    cast(Any, session.rollback).assert_awaited_once_with()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            datetime(2026, 7, 27, 15, 0, 0, 123999),
            datetime(2026, 7, 27, 15, 0, 0, 123000),
        ),
        (
            datetime(
                2026,
                7,
                27,
                17,
                0,
                0,
                123999,
                tzinfo=timezone(timedelta(hours=2)),
            ),
            datetime(2026, 7, 27, 15, 0, 0, 123000),
        ),
    ],
)
def test_clock_timestamp_is_normalized_once_to_naive_timestamp_precision(
    raw: datetime,
    expected: datetime,
) -> None:
    assert normalize_rebuild_timestamp(raw) == expected


def test_response_contract_rejects_internal_fields() -> None:
    with pytest.raises(ValueError):
        HoldingRebuildResponse.model_validate(
            {
                "account_id": "account-a",
                "created": 1,
                "updated": 0,
                "deleted": 0,
                "total": 1,
                "replayed": False,
                "rebuilt_at": NOW,
                "holding_ids": ["secret"],
            }
        )
