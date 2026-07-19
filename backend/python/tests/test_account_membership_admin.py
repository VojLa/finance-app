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
from app.modules.accounts.access import AccountAccessDeniedError
from app.modules.accounts.models import AccountMemberResponse, AccountMemberRoleUpdateRequest
from app.modules.accounts.service import (
    AccountMemberNotFoundError,
    AccountOwnerImmutableError,
    AccountService,
)


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


def _session() -> tuple[AsyncSession, AsyncMock, AsyncMock]:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    return session, cast(AsyncMock, session.commit), cast(AsyncMock, session.rollback)


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


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/accounts/account-a/members"),
        ("patch", "/api/v1/accounts/account-a/members/member-a"),
        ("delete", "/api/v1/accounts/account-a/members/member-a"),
    ],
)
def test_membership_endpoints_reject_invalid_token(
    test_settings: Settings,
    method: str,
    path: str,
) -> None:
    kwargs = {"json": {"role": "editor"}} if method == "patch" else {}
    with TestClient(create_app(test_settings)) as client:
        response = client.request(
            method,
            path,
            headers={"Authorization": "Bearer invalid"},
            **kwargs,
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session_token"


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


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"role": "invalid"},
        {"relation_type": "owner"},
        {"role": "admin", "user_id": "other-user"},
        {"role": "admin", "member_id": "other-member"},
        {"role": "admin", "accepted_at": "2026-07-19T14:00:00"},
    ],
)
def test_member_role_update_rejects_invalid_or_extra_fields(
    test_settings: Settings,
    payload: dict[str, object],
) -> None:
    with _client(test_settings) as client:
        response = client.patch(
            "/api/v1/accounts/account-a/members/member-a",
            json=payload,
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
    session, commit, _rollback = _session()
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
        "get_member_response",
        AsyncMock(return_value=_member(AccountMemberRole.editor)),
    )

    result = await service.update_member_role(
        principal=_principal(),
        account_id="account-a",
        member_id="member-a",
        payload=AccountMemberRoleUpdateRequest(role=AccountMemberRole.editor),
    )

    assert result.role is AccountMemberRole.editor
    assert membership.role is AccountMemberRole.editor
    commit.assert_awaited_once()
    assert access.await_args is not None
    assert access.await_args.kwargs["allowed_roles"] == {AccountMemberRole.owner}


@pytest.mark.asyncio
async def test_owner_membership_cannot_be_changed_or_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, commit, _rollback = _session()
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

    commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_member_response_is_controlled_after_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, commit, _rollback = _session()
    service = AccountService(session)
    membership = SimpleNamespace(
        id="member-a",
        role=AccountMemberRole.viewer,
        updated_at=datetime(2026, 7, 19, 13, 0, 0),
    )
    monkeypatch.setattr("app.modules.accounts.service.require_account_access", AsyncMock())
    monkeypatch.setattr(service.repository, "get_member", AsyncMock(return_value=membership))
    monkeypatch.setattr(service.repository, "get_member_response", AsyncMock(return_value=None))

    with pytest.raises(AccountMemberNotFoundError):
        await service.update_member_role(
            principal=_principal(),
            account_id="account-a",
            member_id="member-a",
            payload=AccountMemberRoleUpdateRequest(role=AccountMemberRole.editor),
        )

    commit.assert_awaited_once()


@pytest.mark.parametrize("operation", ["update", "delete"])
@pytest.mark.asyncio
async def test_membership_commit_failure_rolls_back(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, commit, rollback = _session()
    commit.side_effect = RuntimeError("commit failed")
    service = AccountService(session)
    membership = SimpleNamespace(
        id="member-a",
        role=AccountMemberRole.viewer,
        updated_at=datetime(2026, 7, 19, 13, 0, 0),
    )
    monkeypatch.setattr("app.modules.accounts.service.require_account_access", AsyncMock())
    monkeypatch.setattr(service.repository, "get_member", AsyncMock(return_value=membership))
    delete_membership = AsyncMock()
    monkeypatch.setattr(service.repository, "delete_membership", delete_membership)

    with pytest.raises(RuntimeError, match="commit failed"):
        if operation == "update":
            await service.update_member_role(
                principal=_principal(),
                account_id="account-a",
                member_id="member-a",
                payload=AccountMemberRoleUpdateRequest(role=AccountMemberRole.editor),
            )
        else:
            await service.remove_member(
                principal=_principal(),
                account_id="account-a",
                member_id="member-a",
            )

    rollback.assert_awaited_once()


@pytest.mark.parametrize("operation", ["list", "update", "delete"])
@pytest.mark.asyncio
async def test_authorization_failure_prevents_membership_repository_access(
    operation: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, commit, rollback = _session()
    service = AccountService(session)
    authorize = AsyncMock(side_effect=AccountAccessDeniedError())
    get_member = AsyncMock()
    list_members = AsyncMock()
    delete_membership = AsyncMock()
    monkeypatch.setattr("app.modules.accounts.service.require_account_access", authorize)
    monkeypatch.setattr(service.repository, "get_member", get_member)
    monkeypatch.setattr(service.repository, "list_members", list_members)
    monkeypatch.setattr(service.repository, "delete_membership", delete_membership)

    with pytest.raises(AccountAccessDeniedError):
        if operation == "list":
            await service.list_members(principal=_principal(), account_id="account-a")
        elif operation == "update":
            await service.update_member_role(
                principal=_principal(),
                account_id="account-a",
                member_id="member-a",
                payload=AccountMemberRoleUpdateRequest(role=AccountMemberRole.editor),
            )
        else:
            await service.remove_member(
                principal=_principal(),
                account_id="account-a",
                member_id="member-a",
            )

    get_member.assert_not_awaited()
    list_members.assert_not_awaited()
    delete_membership.assert_not_awaited()
    commit.assert_not_awaited()
    rollback.assert_not_awaited()


def test_membership_openapi_contract(test_settings: Settings) -> None:
    schema = create_app(test_settings).openapi()
    list_operation = schema["paths"]["/api/v1/accounts/{account_id}/members"]["get"]
    member_path = schema["paths"]["/api/v1/accounts/{account_id}/members/{member_id}"]

    assert list_operation["security"] == [{"InternalSessionToken": []}]
    assert member_path["patch"]["security"] == [{"InternalSessionToken": []}]
    assert member_path["delete"]["security"] == [{"InternalSessionToken": []}]
    assert "204" in member_path["delete"]["responses"]
    assert "content" not in member_path["delete"]["responses"]["204"]
    assert member_path["patch"]["requestBody"]
    assert member_path["patch"]["responses"]["200"]["content"]
    assert {parameter["name"] for parameter in member_path["patch"]["parameters"]} == {
        "account_id",
        "member_id",
    }
    assert schema["paths"]["/api/v1/health/live"]["get"].get("security") is None
