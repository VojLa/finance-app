from collections.abc import AsyncIterator
from datetime import datetime
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.enums import AccountMemberRole, AccountRelationType, AccountType
from app.main import create_app
from app.modules.accounts.models import AccountResponse
from app.modules.accounts.service import AccountService


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-a",
        email="user-a@example.com",
        name="User A",
    )


def _account() -> AccountResponse:
    now = datetime(2026, 7, 18, 12, 0, 0)
    return AccountResponse(
        id="account-a",
        name="Main account",
        type=AccountType.bank,
        currency="CZK",
        color=None,
        notes=None,
        is_archived=False,
        role=AccountMemberRole.owner,
        relation_type=AccountRelationType.owner,
        created_at=now,
        updated_at=now,
    )


def _client(test_settings: Settings) -> TestClient:
    app = create_app(test_settings)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_current_principal] = _principal
    app.dependency_overrides[get_db_session] = session_override
    return TestClient(app)


def test_accounts_require_authentication(test_settings: Settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/api/v1/accounts")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_list_accounts_uses_principal(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_accounts = AsyncMock(return_value=[_account()])
    monkeypatch.setattr(AccountService, "list_accounts", list_accounts)

    with _client(test_settings) as client:
        response = client.get("/api/v1/accounts?user_id=user-b")

    assert response.status_code == 200
    list_accounts.assert_awaited_once()
    assert list_accounts.await_args is not None
    assert list_accounts.await_args.args[0].user_id == "user-a"


def test_create_account_returns_201_and_normalizes_input(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_account = AsyncMock(return_value=_account())
    monkeypatch.setattr(AccountService, "create_account", create_account)

    with _client(test_settings) as client:
        response = client.post(
            "/api/v1/accounts",
            json={"name": "  Main account  ", "type": "bank", "currency": "czk"},
        )

    assert response.status_code == 201
    assert create_account.await_args is not None
    payload = create_account.await_args.kwargs["payload"]
    principal = create_account.await_args.kwargs["principal"]
    assert payload.name == "Main account"
    assert payload.currency == "CZK"
    assert principal.user_id == "user-a"


def test_create_account_rejects_identity_and_role_fields(test_settings: Settings) -> None:
    with _client(test_settings) as client:
        response = client.post(
            "/api/v1/accounts",
            json={
                "name": "Main",
                "type": "bank",
                "currency": "CZK",
                "user_id": "user-b",
                "role": "owner",
            },
        )

    assert response.status_code == 422


def test_patch_account_rejects_empty_payload(test_settings: Settings) -> None:
    with _client(test_settings) as client:
        response = client.patch("/api/v1/accounts/account-a", json={})

    assert response.status_code == 422


def test_patch_account_calls_role_protected_service(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_account = AsyncMock(return_value=_account())
    monkeypatch.setattr(AccountService, "update_account", update_account)

    with _client(test_settings) as client:
        response = client.patch(
            "/api/v1/accounts/account-a",
            json={"name": "Updated"},
        )

    assert response.status_code == 200
    update_account.assert_awaited_once()
    assert update_account.await_args is not None
    assert update_account.await_args.kwargs["account_id"] == "account-a"
    assert update_account.await_args.kwargs["principal"].user_id == "user-a"


def test_accounts_openapi_contract(test_settings: Settings) -> None:
    schema = create_app(test_settings).openapi()
    for path, method in [
        ("/api/v1/accounts", "get"),
        ("/api/v1/accounts", "post"),
        ("/api/v1/accounts/{account_id}", "patch"),
    ]:
        assert schema["paths"][path][method]["security"] == [{"InternalSessionToken": []}]

    parameters = schema["paths"]["/api/v1/accounts"]["get"].get("parameters", [])
    assert "user_id" not in {parameter["name"] for parameter in parameters}
    assert schema["paths"]["/api/v1/accounts"]["post"]["responses"].get("201") is not None
