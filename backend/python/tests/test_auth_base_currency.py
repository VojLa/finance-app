from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import (
    AuthenticatedPrincipal,
    BaseCurrencyChangeRequest,
    BaseCurrencyChangeResponse,
)
from app.auth.service import AuthService
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.users import UserModel
from app.main import create_app
from app.modules.portfolio_history.invalidation.service import (
    PortfolioHistoryInvalidationService,
)

PATH = "/api/v1/auth/me/base-currency"


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-a",
        email="user-a@example.test",
        name="User A",
    )


def _user(*, currency: str = "CZK") -> UserModel:
    at = datetime(2026, 8, 25, 12, 0, 0)
    return UserModel(
        id="user-a",
        email="user-a@example.test",
        name="User A",
        password_hash=None,
        base_currency=currency,
        created_at=at,
        updated_at=at,
    )


def _service() -> tuple[AuthService, AsyncSession, SimpleNamespace]:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    # AsyncSession.begin() returns an awaitable transaction object, while a
    # spec-backed AsyncMock represents the factory itself as a MagicMock.
    cast(Any, session).begin = AsyncMock()
    history = SimpleNamespace(
        lock_generation_users=AsyncMock(),
        invalidate_scope_users=AsyncMock(),
    )
    service = AuthService(
        session,
        history=cast(PortfolioHistoryInvalidationService, history),
    )
    return service, session, history


@pytest.mark.parametrize(
    "value",
    ("eur", " EUR", "EUR ", "EU", "EURO", "E1R", "€UR", ""),
)
def test_base_currency_request_requires_exact_uppercase_ascii_triplet(value: str) -> None:
    with pytest.raises(ValidationError):
        BaseCurrencyChangeRequest.model_validate({"baseCurrency": value})

    with pytest.raises(ValidationError):
        BaseCurrencyChangeRequest.model_validate({"baseCurrency": "EUR", "unexpected": True})


@pytest.mark.asyncio
async def test_real_base_currency_change_locks_updates_and_invalidates_atomically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session, history = _service()
    user = _user()
    events: list[str] = []
    cast(AsyncMock, session.begin).side_effect = lambda: events.append("begin")
    history.lock_generation_users.side_effect = lambda _users: events.append("generation-lock")

    async def find_for_update(_user_id: str) -> UserModel:
        events.append("user-for-update")
        return user

    monkeypatch.setattr(service.repository, "find_by_id_for_update", find_for_update)
    cast(AsyncMock, session.flush).side_effect = lambda: events.append("flush")
    history.invalidate_scope_users.side_effect = lambda **_kwargs: events.append(
        "history-invalidation"
    )
    cast(AsyncMock, session.commit).side_effect = lambda: events.append("commit")

    result = await service.change_base_currency(
        principal=_principal(),
        payload=BaseCurrencyChangeRequest(baseCurrency="EUR"),
    )

    assert result == BaseCurrencyChangeResponse(base_currency="EUR")
    assert user.base_currency == "EUR"
    assert user.updated_at.microsecond % 1_000 == 0
    assert events == [
        "begin",
        "generation-lock",
        "user-for-update",
        "flush",
        "history-invalidation",
        "commit",
    ]
    history.lock_generation_users.assert_awaited_once_with(("user-a",))
    assert history.invalidate_scope_users.await_args.kwargs == {
        "user_ids": ("user-a",),
        "now": user.updated_at,
    }
    cast(AsyncMock, session.rollback).assert_not_awaited()


@pytest.mark.asyncio
async def test_same_base_currency_is_a_complete_no_op_after_serialized_revalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session, history = _service()
    user = _user()
    original_updated_at = user.updated_at
    monkeypatch.setattr(
        service.repository,
        "find_by_id_for_update",
        AsyncMock(return_value=user),
    )

    result = await service.change_base_currency(
        principal=_principal(),
        payload=BaseCurrencyChangeRequest(baseCurrency="CZK"),
    )

    assert result.base_currency == "CZK"
    assert user.updated_at == original_updated_at
    history.lock_generation_users.assert_awaited_once_with(("user-a",))
    history.invalidate_scope_users.assert_not_awaited()
    cast(AsyncMock, session.flush).assert_not_awaited()
    cast(AsyncMock, session.commit).assert_awaited_once_with()
    cast(AsyncMock, session.rollback).assert_not_awaited()


@pytest.mark.asyncio
async def test_history_invalidation_failure_rolls_back_user_currency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, session, history = _service()
    user = _user()
    monkeypatch.setattr(
        service.repository,
        "find_by_id_for_update",
        AsyncMock(return_value=user),
    )
    history.invalidate_scope_users.side_effect = RuntimeError("history unavailable")

    with pytest.raises(RuntimeError, match="history unavailable"):
        await service.change_base_currency(
            principal=_principal(),
            payload=BaseCurrencyChangeRequest(baseCurrency="EUR"),
        )

    cast(AsyncMock, session.commit).assert_not_awaited()
    cast(AsyncMock, session.rollback).assert_awaited_once_with()


def test_base_currency_endpoint_contract_auth_validation_and_no_store(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(test_settings)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = session_override
    app.dependency_overrides[get_current_principal] = _principal
    change = AsyncMock(return_value=BaseCurrencyChangeResponse(base_currency="EUR"))
    monkeypatch.setattr(AuthService, "change_base_currency", change)

    with TestClient(app) as client:
        response = client.put(PATH, json={"baseCurrency": "EUR"})
        invalid = client.put(PATH, json={"baseCurrency": "eur"})

    assert response.status_code == 200
    assert response.json() == {"baseCurrency": "EUR"}
    assert response.headers["Cache-Control"] == "no-store"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert change.await_args is not None
    assert change.await_args.kwargs == {
        "principal": _principal(),
        "payload": BaseCurrencyChangeRequest(baseCurrency="EUR"),
    }

    operation = app.openapi()["paths"][PATH]["put"]
    assert operation["security"] == [{"InternalSessionToken": []}]
    assert operation["requestBody"]["required"] is True
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/BaseCurrencyChangeResponse"
    }

    unauthenticated = create_app(test_settings)
    with TestClient(unauthenticated) as client:
        assert client.put(PATH, json={"baseCurrency": "EUR"}).status_code == 401
