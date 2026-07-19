from collections.abc import AsyncIterator
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.enums import AccountMemberRole
from app.main import create_app
from app.modules.accounts.invitations import AccountInviteCreateRequest


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-a",
        email="user-a@example.com",
        name="User A",
    )


def _client(test_settings: Settings) -> TestClient:
    app = create_app(test_settings)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_current_principal] = _principal
    app.dependency_overrides[get_db_session] = session_override
    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/v1/accounts/account-a/invites", {"email": "b@example.com"}),
        ("get", "/api/v1/accounts/account-a/invites", None),
        ("delete", "/api/v1/accounts/account-a/invites/invite-a", None),
        ("post", "/api/v1/accounts/invites/accept", {"token": "x" * 43}),
    ],
)
def test_invitation_endpoints_require_authentication(
    test_settings: Settings,
    method: str,
    path: str,
    payload: dict[str, str] | None,
) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.request(method, path, json=payload)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_invite_input_normalizes_email_and_rejects_owner() -> None:
    payload = AccountInviteCreateRequest(email="  USER@Example.COM  ")
    assert payload.email == "user@example.com"

    with pytest.raises(ValueError):
        AccountInviteCreateRequest(
            email="owner@example.com",
            role=AccountMemberRole.owner,
        )


def test_invitation_openapi_contract(test_settings: Settings) -> None:
    schema = create_app(test_settings).openapi()
    operations = [
        schema["paths"]["/api/v1/accounts/{account_id}/invites"]["post"],
        schema["paths"]["/api/v1/accounts/{account_id}/invites"]["get"],
        schema["paths"]["/api/v1/accounts/{account_id}/invites/{invite_id}"]["delete"],
        schema["paths"]["/api/v1/accounts/invites/accept"]["post"],
    ]
    for operation in operations:
        assert operation["security"] == [{"InternalSessionToken": []}]
    assert "201" in operations[0]["responses"]
    assert "204" in operations[2]["responses"]
    assert "201" in operations[3]["responses"]
