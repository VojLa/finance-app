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
from app.db.models.enums import AccountMemberRole, AccountRelationType, AccountType
from app.main import create_app
from app.modules.accounts.access import AccountAccessDeniedError
from app.modules.accounts.models import AccountResponse
from app.modules.accounts.service import AccountNotArchivedError, AccountService


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-a",
        email="user-a@example.com",
        name="User A",
    )


def _response(*, archived: bool) -> AccountResponse:
    now = datetime(2026, 7, 19, 10, 0, 0)
    return AccountResponse(
        id="account-a",
        name="Main account",
        type=AccountType.bank,
        currency="CZK",
        color=None,
        notes=None,
        is_archived=archived,
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


def _session() -> tuple[AsyncSession, AsyncMock, AsyncMock]:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    return session, cast(AsyncMock, session.commit), cast(AsyncMock, session.rollback)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/accounts/account-a/archive",
        "/api/v1/accounts/account-a/restore",
    ],
)
def test_lifecycle_endpoints_require_authentication(
    test_settings: Settings,
    path: str,
) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.post(path)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/accounts/account-a/archive",
        "/api/v1/accounts/account-a/restore",
    ],
)
def test_lifecycle_endpoints_reject_invalid_token(
    test_settings: Settings,
    path: str,
) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.post(path, headers={"Authorization": "Bearer invalid"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session_token"


def test_archive_endpoint_uses_authenticated_principal(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = AsyncMock(return_value=_response(archived=True))
    monkeypatch.setattr(AccountService, "archive_account", archive)

    with _client(test_settings) as client:
        response = client.post("/api/v1/accounts/account-a/archive")

    assert response.status_code == 200
    assert response.json()["is_archived"] is True
    archive.assert_awaited_once()
    assert archive.await_args is not None
    assert archive.await_args.kwargs["principal"].user_id == "user-a"
    assert archive.await_args.kwargs["account_id"] == "account-a"


def test_restore_endpoint_uses_authenticated_principal(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    restore = AsyncMock(return_value=_response(archived=False))
    monkeypatch.setattr(AccountService, "restore_account", restore)

    with _client(test_settings) as client:
        response = client.post("/api/v1/accounts/account-a/restore")

    assert response.status_code == 200
    assert response.json()["is_archived"] is False
    restore.assert_awaited_once()
    assert restore.await_args is not None
    assert restore.await_args.kwargs["principal"].user_id == "user-a"


@pytest.mark.asyncio
async def test_archive_sets_archive_fields_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, commit, _rollback = _session()
    service = AccountService(session)
    account = SimpleNamespace(
        id="account-a",
        name="Main account",
        type=AccountType.bank,
        currency="CZK",
        color=None,
        notes=None,
        is_archived=False,
        archived_at=None,
        created_at=datetime(2026, 7, 19, 9, 0, 0),
        updated_at=datetime(2026, 7, 19, 9, 0, 0),
    )
    access = AsyncMock(
        return_value=SimpleNamespace(
            role=AccountMemberRole.owner,
            relation_type=AccountRelationType.owner,
        )
    )
    monkeypatch.setattr("app.modules.accounts.service.require_account_access", access)
    monkeypatch.setattr(
        service.repository,
        "get_account_for_lifecycle",
        AsyncMock(return_value=account),
    )

    result = await service.archive_account(principal=_principal(), account_id="account-a")

    assert result.is_archived is True
    assert account.archived_at is not None
    assert account.updated_at == account.archived_at
    commit.assert_awaited_once()
    access.assert_awaited_once()
    assert access.await_args is not None
    assert access.await_args.kwargs["allowed_roles"] == {
        AccountMemberRole.owner,
        AccountMemberRole.admin,
    }


@pytest.mark.asyncio
async def test_restore_requires_archived_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, commit, _rollback = _session()
    service = AccountService(session)
    account = SimpleNamespace(is_archived=False)
    access = AsyncMock(
        return_value=SimpleNamespace(
            role=AccountMemberRole.owner,
            relation_type=AccountRelationType.owner,
        )
    )
    monkeypatch.setattr("app.modules.accounts.service.require_account_access", access)
    monkeypatch.setattr(
        service.repository,
        "get_account_for_lifecycle",
        AsyncMock(return_value=account),
    )

    with pytest.raises(AccountNotArchivedError):
        await service.restore_account(principal=_principal(), account_id="account-a")

    commit.assert_not_awaited()
    assert access.await_args is not None
    assert access.await_args.kwargs["include_archived"] is True


@pytest.mark.asyncio
async def test_lifecycle_commit_failure_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, commit, rollback = _session()
    commit.side_effect = RuntimeError("commit failed")
    service = AccountService(session)
    account = SimpleNamespace(
        id="account-a",
        name="Main account",
        type=AccountType.bank,
        currency="CZK",
        color=None,
        notes=None,
        is_archived=False,
        archived_at=None,
        created_at=datetime(2026, 7, 19, 9, 0, 0),
        updated_at=datetime(2026, 7, 19, 9, 0, 0),
    )
    monkeypatch.setattr(
        "app.modules.accounts.service.require_account_access",
        AsyncMock(
            return_value=SimpleNamespace(
                role=AccountMemberRole.owner,
                relation_type=AccountRelationType.owner,
            )
        ),
    )
    monkeypatch.setattr(
        service.repository,
        "get_account_for_lifecycle",
        AsyncMock(return_value=account),
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await service.archive_account(principal=_principal(), account_id="account-a")

    rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_restore_clears_archive_fields_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, commit, rollback = _session()
    service = AccountService(session)
    created_at = datetime(2026, 7, 19, 8, 0, 0)
    previous_updated_at = datetime(2026, 7, 19, 9, 0, 0)
    account = SimpleNamespace(
        id="account-a",
        name="Main account",
        type=AccountType.bank,
        currency="CZK",
        color=None,
        notes=None,
        is_archived=True,
        archived_at=previous_updated_at,
        created_at=created_at,
        updated_at=previous_updated_at,
    )
    access = AsyncMock(
        return_value=SimpleNamespace(
            role=AccountMemberRole.admin,
            relation_type=AccountRelationType.collaborator,
        )
    )
    monkeypatch.setattr("app.modules.accounts.service.require_account_access", access)
    lookup = AsyncMock(return_value=account)
    monkeypatch.setattr(service.repository, "get_account_for_lifecycle", lookup)

    result = await service.restore_account(principal=_principal(), account_id="account-a")

    assert result.is_archived is False
    assert account.archived_at is None
    assert account.updated_at > previous_updated_at
    assert account.created_at == created_at
    commit.assert_awaited_once()
    rollback.assert_not_awaited()
    assert access.await_args is not None
    assert access.await_args.kwargs["include_archived"] is True


@pytest.mark.asyncio
async def test_restore_commit_failure_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, commit, rollback = _session()
    commit.side_effect = RuntimeError("commit failed")
    service = AccountService(session)
    account = SimpleNamespace(
        id="account-a",
        name="Main account",
        type=AccountType.bank,
        currency="CZK",
        color=None,
        notes=None,
        is_archived=True,
        archived_at=datetime(2026, 7, 19, 9, 0, 0),
        created_at=datetime(2026, 7, 19, 8, 0, 0),
        updated_at=datetime(2026, 7, 19, 9, 0, 0),
    )
    monkeypatch.setattr(
        "app.modules.accounts.service.require_account_access",
        AsyncMock(
            return_value=SimpleNamespace(
                role=AccountMemberRole.owner,
                relation_type=AccountRelationType.owner,
            )
        ),
    )
    monkeypatch.setattr(
        service.repository,
        "get_account_for_lifecycle",
        AsyncMock(return_value=account),
    )

    with pytest.raises(RuntimeError, match="commit failed"):
        await service.restore_account(principal=_principal(), account_id="account-a")

    rollback.assert_awaited_once()


@pytest.mark.parametrize("method_name", ["archive_account", "restore_account"])
@pytest.mark.asyncio
async def test_authorization_failure_prevents_lifecycle_lookup_and_commit(
    method_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, commit, rollback = _session()
    service = AccountService(session)
    authorize = AsyncMock(side_effect=AccountAccessDeniedError())
    lookup = AsyncMock()
    monkeypatch.setattr("app.modules.accounts.service.require_account_access", authorize)
    monkeypatch.setattr(service.repository, "get_account_for_lifecycle", lookup)

    method = getattr(service, method_name)
    with pytest.raises(AccountAccessDeniedError):
        await method(principal=_principal(), account_id="account-a")

    lookup.assert_not_awaited()
    commit.assert_not_awaited()
    rollback.assert_not_awaited()


def test_lifecycle_openapi_contract(test_settings: Settings) -> None:
    schema = create_app(test_settings).openapi()

    for path in (
        "/api/v1/accounts/{account_id}/archive",
        "/api/v1/accounts/{account_id}/restore",
    ):
        operation = schema["paths"][path]["post"]
        assert operation["security"] == [{"InternalSessionToken": []}]
        assert operation["parameters"][0]["name"] == "account_id"
        assert operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert "user_id" not in {parameter["name"] for parameter in operation["parameters"]}

    assert schema["paths"]["/api/v1/health/live"]["get"].get("security") is None
    assert "/accounts/{account_id}/archive" not in schema["paths"]
