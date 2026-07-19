from collections.abc import AsyncIterator
from datetime import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.enums import AccountMemberRole, AccountRelationType
from app.main import create_app
from app.modules.accounts.models import AccountMemberResponse, AccountMemberRoleUpdateRequest
from app.modules.accounts.service import AccountOwnerImmutableError, AccountService


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="owner-user", email="owner@example.com", name="Owner")


def _member(role: AccountMemberRole = AccountMemberRole.viewer) -> AccountMemberResponse:
    now = datetime(2026, 7, 19, 14, 0, 0)
    return AccountMemberResponse(
        id="member-a",
        user_id="user-a",
        email="user-a@example.com",
        name="User A",
        role=role,
        relation_type=AccountRelationType.owner,
        accepted_at=now,
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


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/v1/accounts/account-a/members", None),
        ("patch", "/api/v1/accounts/account-a/members/member-a", {"role": "editor"}),
        ("delete", "/api/v1/accounts/account-a/members/member-a", None),
    ],
)
def test_membership_endpoints_require_authentication(
    test_settings: Settings,
    method: str,
    path: str,
    payload: dict[str, str] | None,
) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.request(method, path, json=payload)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_membership_endpoints_use_authenticated_principal(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_members = AsyncMock(return_value=[_member()])
    monkeypatch.setattr(AccountService, "list_members", list_members)

    with _client(test_settings) as client:
        response = client.get("/api/v1/accounts/account-a/members")

    assert response.status_code == 200
    assert response.json()[0]["email"] == "user-a@example.com"
    assert list_members.await_args is not None
    assert list_members.await_args.kwargs["principal"].user_id == "owner-user"
    assert list_members.await_args.kwargs["account_id"] == "account-a"


def test_member_role_update_rejects_owner_assignment(test_settings: Settings) -> None:
    with _client(test_settings) as client:
        response = client.patch(
            "/api/v1/accounts/account-a/members/member-a",
            json={"role": "owner"},
        )

    assert response.status_code == 422


def test_member_removal_returns_204(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remove = AsyncMock()
    monkeypatch.setattr(AccountService, "remove_member", remove)

    with _client(test_settings) as client:
        response = client.delete("/api/v1/accounts/account-a/members/member-a")

    assert response.status_code == 204
    assert response.content == b""
    remove.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_member_role_authorizes_owner_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    service = AccountService(session)
    membership = SimpleNamespace(
        id="member-a",
        role=AccountMemberRole.viewer,
        updated_at=datetime(2026, 7, 19, 13, 0, 0),
    )
    access = AsyncMock()
    monkeypatch.setattr("app.modules.accounts.service.require_account_access", access)
    monkeypatch.setattr(service.repository, "get_member", AsyncMock(return_value=membership))
    monkeypatch.setattr(
        service.repository,
        "list_members",
        AsyncMock(return_value=[_member(AccountMemberRole.editor)]),
    )

    result = await service.update_member_role(
        principal=_principal(),
        account_id="account-a",
        member_id="member-a",
        payload=AccountMemberRoleUpdateRequest(role=AccountMemberRole.editor),
    )

    assert result.role is AccountMemberRole.editor
    assert membership.role is AccountMemberRole.editor
    session.commit.assert_awaited_once()
    assert access.await_args is not None
    assert access.await_args.kwargs["allowed_roles"] == {AccountMemberRole.owner}


@pytest.mark.asyncio
async def test_owner_membership_cannot_be_changed_or_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    service = AccountService(session)
    membership = SimpleNamespace(role=AccountMemberRole.owner)
    monkeypatch.setattr("app.modules.accounts.service.require_account_access", AsyncMock())
    monkeypatch.setattr(service.repository, "get_member", AsyncMock(return_value=membership))

    with pytest.raises(AccountOwnerImmutableError):
        await service.update_member_role(
            principal=_principal(),
            account_id="account-a",
            member_id="owner-member",
            payload=AccountMemberRoleUpdateRequest(role=AccountMemberRole.admin),
        )

    with pytest.raises(AccountOwnerImmutableError):
        await service.remove_member(
            principal=_principal(),
            account_id="account-a",
            member_id="owner-member",
        )

    session.commit.assert_not_awaited()


def test_membership_openapi_contract(test_settings: Settings) -> None:
    schema = create_app(test_settings).openapi()
    list_operation = schema["paths"]["/api/v1/accounts/{account_id}/members"]["get"]
    member_path = schema["paths"]["/api/v1/accounts/{account_id}/members/{member_id}"]

    assert list_operation["security"] == [{"InternalSessionToken": []}]
    assert member_path["patch"]["security"] == [{"InternalSessionToken": []}]
    assert member_path["delete"]["security"] == [{"InternalSessionToken": []}]
    assert "204" in member_path["delete"]["responses"]
