from collections.abc import AsyncIterator
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.enums import AccountMemberRole
from app.main import create_app
from app.modules.accounts.invitations import (
    AccountInvitationService,
    AccountInviteCreateRequest,
)


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


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("post", "/api/v1/accounts/account-a/invites", {"email": "b@example.com"}),
        ("get", "/api/v1/accounts/account-a/invites", None),
        ("delete", "/api/v1/accounts/account-a/invites/invite-a", None),
        ("post", "/api/v1/accounts/invites/accept", {"token": "x" * 43}),
    ],
)
def test_invitation_endpoints_reject_invalid_authentication(
    test_settings: Settings,
    method: str,
    path: str,
    payload: dict[str, str] | None,
) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.request(
            method,
            path,
            json=payload,
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session_token"


def test_invite_input_normalizes_email_and_rejects_owner() -> None:
    payload = AccountInviteCreateRequest(email="  USER@Example.COM  ")
    assert payload.email == "user@example.com"

    with pytest.raises(ValueError):
        AccountInviteCreateRequest(
            email="owner@example.com",
            role=AccountMemberRole.owner,
        )


@pytest.mark.parametrize(
    "email",
    [
        "invalid",
        "a b@example.com",
        ".a@example.com",
        "a..b@example.com",
        "a@-example.com",
        "a@example..com",
        "a@exam_ple.com",
    ],
)
def test_invite_input_rejects_clearly_malformed_email(email: str) -> None:
    with pytest.raises(ValueError):
        AccountInviteCreateRequest(email=email)


@pytest.mark.parametrize("expires_in_hours", [0, 169])
def test_invite_input_rejects_expiration_outside_bounds(expires_in_hours: int) -> None:
    with pytest.raises(ValueError):
        AccountInviteCreateRequest(email="a@example.com", expires_in_hours=expires_in_hours)


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "a@example.com", "unknown": "value"},
        {"email": "a@example.com", "role": "owner"},
    ],
)
def test_invite_input_forbids_extra_fields_and_owner(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        AccountInviteCreateRequest.model_validate(payload)


@pytest.mark.asyncio
async def test_create_persists_only_sha256_token_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    add = cast(Mock, session.add)
    commit = cast(AsyncMock, session.commit)
    service = AccountInvitationService(session)
    monkeypatch.setattr(service, "_require_owner", AsyncMock())
    monkeypatch.setattr(service.repository, "pending_for_email", AsyncMock(return_value=None))

    response = await service.create_invite(
        principal=_principal(),
        account_id="account-a",
        payload=AccountInviteCreateRequest(email="invitee@example.com"),
    )

    invite = add.call_args.args[0]
    assert invite.token_hash != response.token
    assert len(invite.token_hash) == 64
    assert invite.email == "invitee@example.com"
    assert invite.inviter_id == "user-a"
    assert response.role is AccountMemberRole.viewer
    commit.assert_awaited_once()


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
    assert "content" not in operations[2]["responses"]["204"]
    assert schema["paths"]["/api/v1/health/live"]["get"].get("security") is None
    assert sorted(path for path in schema["paths"] if "invite" in path) == [
        "/api/v1/accounts/invites/accept",
        "/api/v1/accounts/{account_id}/invites",
        "/api/v1/accounts/{account_id}/invites/{invite_id}",
    ]
