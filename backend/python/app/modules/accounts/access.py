from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import AccountMemberRole, AccountRelationType
from app.shared.errors import ApplicationError


class AccountNotFoundError(ApplicationError):
    """Hide whether an account is missing or belongs to another user."""

    def __init__(self) -> None:
        super().__init__(
            code="account_not_found",
            message="The account was not found.",
            status_code=404,
        )


class AccountAccessDeniedError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="account_access_denied",
            message="The account access level is insufficient.",
            status_code=403,
        )


@dataclass(frozen=True, slots=True)
class AuthorizedAccount:
    account_id: str
    role: AccountMemberRole
    relation_type: AccountRelationType


async def require_account_access(
    *,
    session: AsyncSession,
    principal: AuthenticatedPrincipal,
    account_id: str,
    allowed_roles: Collection[AccountMemberRole] | None = None,
) -> AuthorizedAccount:
    """Resolve account membership without revealing foreign account existence."""

    statement = (
        select(
            AccountMemberModel.account_id,
            AccountMemberModel.role,
            AccountMemberModel.relation_type,
        )
        .join(AccountModel, AccountModel.id == AccountMemberModel.account_id)
        .where(
            AccountMemberModel.account_id == account_id,
            AccountMemberModel.user_id == principal.user_id,
            AccountModel.is_archived.is_(False),
        )
    )
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        raise AccountNotFoundError()

    resolved_account_id, role, relation_type = row
    authorized = AuthorizedAccount(
        account_id=resolved_account_id,
        role=role,
        relation_type=relation_type,
    )
    if allowed_roles is not None and authorized.role not in allowed_roles:
        raise AccountAccessDeniedError()
    return authorized
