from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import AccountMemberRole, AccountRelationType
from app.modules.accounts.access import (
    AccountAccessDeniedError,
    AccountNotFoundError,
    require_account_access,
)


class _Result:
    def __init__(self, row: object | None) -> None:
        self._row = row

    def one_or_none(self) -> object | None:
        return self._row


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-a",
        email="user-a@example.com",
        name="User A",
    )


@pytest.mark.asyncio
async def test_require_account_access_returns_membership() -> None:
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=_Result(
                SimpleNamespace(
                    account_id="account-a",
                    role=AccountMemberRole.editor,
                    relation_type=AccountRelationType.collaborator,
                )
            )
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
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_require_account_access_hides_missing_or_foreign_account() -> None:
    session = SimpleNamespace(execute=AsyncMock(return_value=_Result(None)))

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
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=_Result(
                SimpleNamespace(
                    account_id="account-a",
                    role=AccountMemberRole.viewer,
                    relation_type=AccountRelationType.beneficiary,
                )
            )
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
