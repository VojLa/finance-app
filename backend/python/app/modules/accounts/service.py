from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import AccountMemberRole, AccountRelationType, AccountType
from app.modules.accounts.access import AccountNotFoundError, require_account_access
from app.modules.accounts.models import (
    AccountCreateRequest,
    AccountMemberResponse,
    AccountMemberRoleUpdateRequest,
    AccountResponse,
    AccountUpdateRequest,
)
from app.modules.accounts.repository import AccountRepository
from app.modules.market_data.source_policy import (
    MarketEvidenceSourcePolicy,
)
from app.modules.portfolio_history.invalidation.service import (
    PortfolioHistoryInvalidationService,
    PortfolioHistoryInvalidationStateError,
)
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
OWNER_ONLY = {AccountMemberRole.owner}


class AccountNotArchivedError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="account_not_archived",
            message="The account is not archived.",
            status_code=409,
        )


class AccountMemberNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="account_member_not_found",
            message="The account member was not found.",
            status_code=404,
        )


class AccountOwnerImmutableError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="account_owner_immutable",
            message="The account owner cannot be changed or removed.",
            status_code=409,
        )


def _now() -> datetime:
    value = datetime.now(UTC)
    return value.replace(tzinfo=None, microsecond=value.microsecond // 1_000 * 1_000)


class AccountService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        source_policy: MarketEvidenceSourcePolicy | None = None,
        history: PortfolioHistoryInvalidationService | None = None,
    ) -> None:
        self.session = session
        self.repository = AccountRepository(session)
        self.history = history or PortfolioHistoryInvalidationService(
            session,
            source_policy=source_policy,
        )

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
            credit_limit=payload.credit_limit,
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
            if not self.session.in_transaction():
                await self.session.begin()
            await self.history.lock_generation_users((principal.user_id,))
            self.repository.add_account(account)
            await self.session.flush()
            self.repository.add_membership(membership)
            await self.history.invalidate_scope_users(
                user_ids=(principal.user_id,),
                now=now,
            )
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
        updates = payload.model_dump(exclude_unset=True)
        currency_requested = "currency" in updates
        expected_users: tuple[str, ...] = ()
        if currency_requested:
            expected_users = await self.repository.accepted_user_ids(account_id)
            if not expected_users:
                raise PortfolioHistoryInvalidationStateError(
                    "Account currency scope has no accepted members."
                )
            await self.history.lock_generation_users(expected_users)
        account = await self.repository.get_account_for_update(account_id)
        if account is None:
            raise AccountNotFoundError()
        if "credit_limit" in updates and account.type is not AccountType.credit_card:
            raise ValueError("Credit limit is only supported for credit-card accounts.")
        if "credit_limit" in updates and (
            updates["credit_limit"] is None or updates["credit_limit"] <= 0
        ):
            raise ValueError("Credit-card accounts require a positive credit limit.")
        if currency_requested:
            authorized = await require_account_access(
                session=self.session,
                principal=principal,
                account_id=account_id,
                allowed_roles=EDIT_ROLES,
                for_update=True,
            )
            await self._revalidate_accepted_users(account_id, expected_users)

        currency_changed = currency_requested and updates["currency"] != account.currency
        now = _now()
        if currency_changed:
            await self.history.invalidate_scope_users(user_ids=expected_users, now=now)
        for field, value in updates.items():
            setattr(account, field, value)
        account.updated_at = now

        await self._commit()
        return self._response(account, authorized.role, authorized.relation_type)

    async def list_members(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
    ) -> list[AccountMemberResponse]:
        await self._require_owner(principal=principal, account_id=account_id)
        return await self.repository.list_members(account_id)

    async def update_member_role(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        member_id: str,
        payload: AccountMemberRoleUpdateRequest,
    ) -> AccountMemberResponse:
        await self._require_owner(principal=principal, account_id=account_id)
        if await self.repository.get_account_for_update(account_id) is None:
            raise AccountNotFoundError()
        membership = await self.repository.get_member(account_id=account_id, member_id=member_id)
        if membership is None:
            raise AccountMemberNotFoundError()
        if membership.role is AccountMemberRole.owner:
            raise AccountOwnerImmutableError()

        membership.role = payload.role
        membership.updated_at = _now()
        await self._commit()
        response = await self.repository.get_member_response(
            account_id=account_id,
            member_id=member_id,
        )
        if response is None:
            raise AccountMemberNotFoundError()
        return response

    async def remove_member(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        member_id: str,
    ) -> None:
        await self._require_owner(principal=principal, account_id=account_id)
        candidate = await self.repository.get_member(account_id=account_id, member_id=member_id)
        if candidate is None:
            raise AccountMemberNotFoundError()
        if candidate.role is AccountMemberRole.owner:
            raise AccountOwnerImmutableError()
        affected_users = () if candidate.accepted_at is None else (candidate.user_id,)
        if affected_users:
            await self.history.lock_generation_users(affected_users)
        if await self.repository.get_account_for_update(account_id) is None:
            raise AccountNotFoundError()
        await self._require_owner(principal=principal, account_id=account_id, for_update=True)
        membership = await self.repository.get_member_for_update(
            account_id=account_id,
            member_id=member_id,
        )
        if membership is None:
            raise AccountMemberNotFoundError()
        if membership.role is AccountMemberRole.owner:
            raise AccountOwnerImmutableError()
        if membership.user_id != candidate.user_id or (membership.accepted_at is None) != (
            candidate.accepted_at is None
        ):
            raise PortfolioHistoryInvalidationStateError(
                "Account membership changed while its history scope was locking."
            )

        if affected_users:
            await self.history.invalidate_scope_users(user_ids=affected_users, now=_now())
        await self.repository.delete_membership(membership)
        await self._commit()

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
        expected_users = await self.repository.accepted_user_ids(account_id)
        if not expected_users:
            raise PortfolioHistoryInvalidationStateError(
                "Account lifecycle scope has no accepted members."
            )
        await self.history.lock_generation_users(expected_users)
        account = await self.repository.get_account_for_lifecycle(account_id)
        if account is None or account.is_archived:
            raise AccountNotFoundError()
        authorized = await require_account_access(
            session=self.session,
            principal=principal,
            account_id=account_id,
            allowed_roles=LIFECYCLE_ROLES,
            for_update=True,
        )
        await self._revalidate_accepted_users(account_id, expected_users)

        now = _now()
        await self.history.invalidate_scope_users(user_ids=expected_users, now=now)
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
        expected_users = await self.repository.accepted_user_ids(account_id)
        if not expected_users:
            raise PortfolioHistoryInvalidationStateError(
                "Account lifecycle scope has no accepted members."
            )
        await self.history.lock_generation_users(expected_users)
        account = await self.repository.get_account_for_lifecycle(account_id)
        if account is None:
            raise AccountNotFoundError()
        if not account.is_archived:
            raise AccountNotArchivedError()
        authorized = await require_account_access(
            session=self.session,
            principal=principal,
            account_id=account_id,
            allowed_roles=LIFECYCLE_ROLES,
            include_archived=True,
            for_update=True,
        )
        await self._revalidate_accepted_users(account_id, expected_users)

        now = _now()
        account.is_archived = False
        account.archived_at = None
        account.updated_at = now
        await self.history.invalidate_scope_users(user_ids=expected_users, now=now)
        await self._commit()
        return self._response(account, authorized.role, authorized.relation_type)

    async def _require_owner(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        for_update: bool = False,
    ) -> None:
        await require_account_access(
            session=self.session,
            principal=principal,
            account_id=account_id,
            allowed_roles=OWNER_ONLY,
            for_update=for_update,
        )

    async def _revalidate_accepted_users(
        self,
        account_id: str,
        expected_users: tuple[str, ...],
    ) -> None:
        memberships = await self.repository.lock_accepted_memberships(account_id)
        actual = tuple(membership.user_id for membership in memberships)
        if actual != expected_users or len(actual) != len(set(actual)):
            raise PortfolioHistoryInvalidationStateError(
                "Account membership changed while its history scope was locking."
            )

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
            credit_limit=getattr(account, "credit_limit", None),
            color=account.color,
            notes=account.notes,
            is_archived=account.is_archived,
            role=role,
            relation_type=relation_type,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )
