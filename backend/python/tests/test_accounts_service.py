from datetime import datetime
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import AccountMemberRole, AccountRelationType, AccountType
from app.modules.accounts.access import AccountAccessDeniedError, AuthorizedAccount
from app.modules.accounts.models import AccountCreateRequest, AccountUpdateRequest
from app.modules.accounts.service import AccountService


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="user-a", email="a@example.com", name="A")


def _session() -> tuple[AsyncSession, AsyncMock, AsyncMock, AsyncMock]:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    return (
        session,
        cast(AsyncMock, session.flush),
        cast(AsyncMock, session.commit),
        cast(AsyncMock, session.rollback),
    )


@pytest.mark.asyncio
async def test_create_forces_authenticated_owner_membership_and_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, flush, commit, rollback = _session()
    service = AccountService(session)
    add_account = Mock()
    add_membership = Mock()
    monkeypatch.setattr(service.repository, "add_account", add_account)
    monkeypatch.setattr(service.repository, "add_membership", add_membership)

    response = await service.create_account(
        principal=_principal(),
        payload=AccountCreateRequest(name="Main", type="bank", currency="czk"),
    )

    account = cast(AccountModel, add_account.call_args.args[0])
    membership = cast(AccountMemberModel, add_membership.call_args.args[0])
    assert account.id == membership.account_id == response.id
    assert membership.user_id == "user-a"
    assert membership.role is AccountMemberRole.owner
    assert membership.relation_type is AccountRelationType.owner
    assert account.currency == "CZK"
    flush.assert_awaited_once()
    commit.assert_awaited_once()
    rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_rolls_back_when_membership_persistence_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, flush, commit, rollback = _session()
    service = AccountService(session)
    add_account = Mock()
    add_membership = Mock(side_effect=RuntimeError("membership failed"))
    monkeypatch.setattr(service.repository, "add_account", add_account)
    monkeypatch.setattr(service.repository, "add_membership", add_membership)

    with pytest.raises(RuntimeError, match="membership failed"):
        await service.create_account(
            principal=_principal(),
            payload=AccountCreateRequest(name="Main", type="bank", currency="CZK"),
        )

    add_account.assert_called_once()
    flush.assert_awaited_once()
    commit.assert_not_awaited()
    rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_rolls_back_when_commit_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    session, _flush, commit, rollback = _session()
    commit.side_effect = RuntimeError("write failed")
    service = AccountService(session)
    now = datetime(2026, 7, 18, 12, 0, 0)
    account = AccountModel(
        id="account-a",
        name="Before",
        type=AccountType.bank,
        currency="CZK",
        color=None,
        notes=None,
        is_archived=False,
        archived_at=None,
        created_at=now,
        updated_at=now,
    )
    get_account = AsyncMock(return_value=account)
    monkeypatch.setattr(service.repository, "get_account_for_update", get_account)
    authorize = AsyncMock(
        return_value=AuthorizedAccount(
            account_id="account-a",
            role=AccountMemberRole.owner,
            relation_type=AccountRelationType.owner,
        )
    )
    monkeypatch.setattr("app.modules.accounts.service.require_account_access", authorize)

    with pytest.raises(RuntimeError, match="write failed"):
        await service.update_account(
            principal=_principal(),
            account_id="account-a",
            payload=AccountUpdateRequest(name="After"),
        )

    rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_authorization_prevents_read_mutation_and_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, _flush, commit, rollback = _session()
    service = AccountService(session)
    get_account = AsyncMock()
    monkeypatch.setattr(service.repository, "get_account_for_update", get_account)
    authorize = AsyncMock(side_effect=AccountAccessDeniedError())
    monkeypatch.setattr("app.modules.accounts.service.require_account_access", authorize)

    with pytest.raises(AccountAccessDeniedError):
        await service.update_account(
            principal=_principal(),
            account_id="account-a",
            payload=AccountUpdateRequest(name="After"),
        )

    get_account.assert_not_awaited()
    commit.assert_not_awaited()
    rollback.assert_not_awaited()
