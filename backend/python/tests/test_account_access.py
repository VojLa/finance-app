from typing import NamedTuple, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import AccountMemberRole, AccountRelationType
from app.modules.accounts.access import (
    AccountAccessDeniedError,
    AccountNotFoundError,
    require_account_access,
)


class _MembershipRow(NamedTuple):
    account_id: str
    role: AccountMemberRole
    relation_type: AccountRelationType


class _Result:
    def __init__(self, row: _MembershipRow | None) -> None:
        self._row = row

    def one_or_none(self) -> _MembershipRow | None:
        return self._row


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-a",
        email="user-a@example.com",
        name="User A",
    )


def _session(row: _MembershipRow | None) -> tuple[AsyncSession, AsyncMock]:
    execute = AsyncMock(return_value=_Result(row))
    session_mock = AsyncMock(spec=AsyncSession)
    session_mock.configure_mock(execute=execute)
    return cast(AsyncSession, session_mock), execute


@pytest.mark.asyncio
async def test_require_account_access_returns_membership() -> None:
    session, execute = _session(
        _MembershipRow(
            account_id="account-a",
            role=AccountMemberRole.editor,
            relation_type=AccountRelationType.collaborator,
        )
    )

    result = await require_account_access(
        session=session,
        principal=_principal(),
        account_id="account-a",
    )

    assert result.account_id == "account-a"
    assert result.role is AccountMemberRole.editor
    assert result.relation_type is AccountRelationType.collaborator
    execute.assert_awaited_once()
    assert execute.await_args is not None
    statement = execute.await_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert '"AccountMember"."accountId" = \'account-a\'' in compiled
    assert '"AccountMember"."userId" = \'user-a\'' in compiled
    assert '"Account"."isArchived" IS false' in compiled


@pytest.mark.asyncio
async def test_require_account_access_hides_missing_or_foreign_account() -> None:
    session, _ = _session(None)

    with pytest.raises(AccountNotFoundError) as exc_info:
        await require_account_access(
            session=session,
            principal=_principal(),
            account_id="foreign-account",
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "account_not_found"


@pytest.mark.asyncio
async def test_require_account_access_enforces_allowed_roles() -> None:
    session, _ = _session(
        _MembershipRow(
            account_id="account-a",
            role=AccountMemberRole.viewer,
            relation_type=AccountRelationType.beneficiary,
        )
    )

    with pytest.raises(AccountAccessDeniedError) as exc_info:
        await require_account_access(
            session=session,
            principal=_principal(),
            account_id="account-a",
            allowed_roles={AccountMemberRole.owner, AccountMemberRole.admin},
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "account_access_denied"


@pytest.mark.parametrize("role", list(AccountMemberRole))
async def test_require_account_access_accepts_any_membership_without_role_constraint(
    role: AccountMemberRole,
) -> None:
    session, _ = _session(
        _MembershipRow(
            account_id="account-a",
            role=role,
            relation_type=AccountRelationType.owner,
        )
    )

    result = await require_account_access(
        session=session,
        principal=_principal(),
        account_id="account-a",
    )

    assert result.role is role


@pytest.mark.parametrize("role", [AccountMemberRole.owner, AccountMemberRole.admin])
async def test_require_account_access_accepts_explicitly_allowed_role(
    role: AccountMemberRole,
) -> None:
    session, _ = _session(
        _MembershipRow(
            account_id="account-a",
            role=role,
            relation_type=AccountRelationType.owner,
        )
    )

    result = await require_account_access(
        session=session,
        principal=_principal(),
        account_id="account-a",
        allowed_roles={AccountMemberRole.owner, AccountMemberRole.admin},
    )

    assert result.role is role


@pytest.mark.asyncio
async def test_require_account_access_can_include_archived_without_weakening_membership_filters() -> (
    None
):
    session, execute = _session(
        _MembershipRow(
            account_id="account-a",
            role=AccountMemberRole.owner,
            relation_type=AccountRelationType.owner,
        )
    )

    await require_account_access(
        session=session,
        principal=_principal(),
        account_id="account-a",
        include_archived=True,
    )

    assert execute.await_args is not None
    compiled = str(execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True}))
    assert '"AccountMember"."accountId" = \'account-a\'' in compiled
    assert '"AccountMember"."userId" = \'user-a\'' in compiled
    assert 'public."Account".id = public."AccountMember"."accountId"' in compiled
    assert '"Account"."isArchived"' not in compiled
