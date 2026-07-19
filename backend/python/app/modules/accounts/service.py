from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import AccountMemberRole, AccountRelationType
from app.modules.accounts.access import AccountNotFoundError, require_account_access
from app.modules.accounts.models import AccountCreateRequest, AccountResponse, AccountUpdateRequest
from app.modules.accounts.repository import AccountRepository
from app.shared.errors import ApplicationError

EDIT_ROLES = {
    AccountMemberRole.owner,
    AccountMemberRole.admin,
    AccountMemberRole.editor,
}
LIFECYCLE_ROLES = {
    AccountMemberRole.owner,
    AccountMemberRole.admin,
}


class AccountNotArchivedError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="account_not_archived",
            message="The account is not archived.",
            status_code=409,
        )


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AccountService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = AccountRepository(session)

    async def list_accounts(self, principal: AuthenticatedPrincipal) -> list[AccountResponse]:
        return await self.repository.list_accessible(principal.user_id)

    async def create_account(
        self,
        *,
        principal: AuthenticatedPrincipal,
        payload: AccountCreateRequest,
    ) -> AccountResponse:
        now = _now()
        account_id = str(uuid4())
        account = AccountModel(
            id=account_id,
            name=payload.name,
            type=payload.type,
            currency=payload.currency,
            color=payload.color,
            notes=payload.notes,
            is_archived=False,
            archived_at=None,
            created_at=now,
            updated_at=now,
        )
        membership = AccountMemberModel(
            id=str(uuid4()),
            account_id=account_id,
            user_id=principal.user_id,
            role=AccountMemberRole.owner,
            relation_type=AccountRelationType.owner,
            invited_by_id=None,
            accepted_at=now,
            created_at=now,
            updated_at=now,
        )

        try:
            self.repository.add_account(account)
            await self.session.flush()
            self.repository.add_membership(membership)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return self._response(account, membership.role, membership.relation_type)

    async def update_account(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        payload: AccountUpdateRequest,
    ) -> AccountResponse:
        authorized = await require_account_access(
            session=self.session,
            principal=principal,
            account_id=account_id,
            allowed_roles=EDIT_ROLES,
        )
        account = await self.repository.get_account_for_update(account_id)
        if account is None:
            raise AccountNotFoundError()

        updates = payload.model_dump(exclude_unset=True)
        for field, value in updates.items():
            setattr(account, field, value)
        account.updated_at = _now()

        await self._commit()
        return self._response(account, authorized.role, authorized.relation_type)

    async def archive_account(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
    ) -> AccountResponse:
        authorized = await require_account_access(
            session=self.session,
            principal=principal,
            account_id=account_id,
            allowed_roles=LIFECYCLE_ROLES,
        )
        account = await self.repository.get_account_for_lifecycle(account_id)
        if account is None or account.is_archived:
            raise AccountNotFoundError()

        now = _now()
        account.is_archived = True
        account.archived_at = now
        account.updated_at = now
        await self._commit()
        return self._response(account, authorized.role, authorized.relation_type)

    async def restore_account(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
    ) -> AccountResponse:
        authorized = await require_account_access(
            session=self.session,
            principal=principal,
            account_id=account_id,
            allowed_roles=LIFECYCLE_ROLES,
            include_archived=True,
        )
        account = await self.repository.get_account_for_lifecycle(account_id)
        if account is None:
            raise AccountNotFoundError()
        if not account.is_archived:
            raise AccountNotArchivedError()

        account.is_archived = False
        account.archived_at = None
        account.updated_at = _now()
        await self._commit()
        return self._response(account, authorized.role, authorized.relation_type)

    async def _commit(self) -> None:
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    @staticmethod
    def _response(
        account: AccountModel,
        role: AccountMemberRole,
        relation_type: AccountRelationType,
    ) -> AccountResponse:
        return AccountResponse(
            id=account.id,
            name=account.name,
            type=account.type,
            currency=account.currency,
            color=account.color,
            notes=account.notes,
            is_archived=account.is_archived,
            role=role,
            relation_type=relation_type,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )
