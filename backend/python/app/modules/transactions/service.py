from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountModel
from app.db.models.categories import CategoryModel
from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    AccountMemberRole,
    CategoryType,
    TransactionClassification,
    TransactionType,
)
from app.db.models.transactions import TransactionModel
from app.modules.accounts.access import require_account_access
from app.modules.canonical_state import (
    CanonicalChangeKind,
    CanonicalStateError,
    CanonicalStateService,
)
from app.modules.portfolio_history.invalidation.service import (
    PortfolioHistoryInvalidationService,
    PortfolioHistoryInvalidationStateError,
)
from app.modules.transactions.models import (
    TransactionAccountResponse,
    TransactionCategoryResponse,
    TransactionCreateRequest,
    TransactionPageResponse,
    TransactionResponse,
    TransactionUpdateRequest,
)
from app.modules.transactions.repository import TransactionRepository
from app.shared.errors import ApplicationError

_TRANSACTION_NAMESPACE = UUID("c093d0b8-56cc-5756-a7ec-918d0cd51694")
_WRITE_ROLES = {
    AccountMemberRole.owner,
    AccountMemberRole.admin,
    AccountMemberRole.editor,
}


class TransactionNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="transaction_not_found",
            message="The transaction was not found.",
            status_code=404,
        )


class TransactionConflictError(ApplicationError):
    def __init__(self, message: str = "The transaction cannot be changed safely.") -> None:
        super().__init__(code="transaction_conflict", message=message, status_code=409)


class TransactionCategoryError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="transaction_category_invalid",
            message="The category is not available for this transaction.",
            status_code=422,
        )


def _now() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    precision = TIMESTAMP.precision
    if precision is None:
        raise RuntimeError("Timestamp precision is unavailable.")
    unit = 10 ** (6 - precision)
    return value.replace(microsecond=value.microsecond - (value.microsecond % unit))


def _classification(transaction_type: TransactionType) -> TransactionClassification:
    return {
        TransactionType.income: TransactionClassification.real_income,
        TransactionType.expense: TransactionClassification.real_expense,
        TransactionType.transfer: TransactionClassification.internal_transfer,
    }[transaction_type]


def _signed_amount(amount: Decimal, transaction_type: TransactionType) -> Decimal:
    absolute = abs(amount)
    return -absolute if transaction_type is TransactionType.expense else absolute


class TransactionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = TransactionRepository(session)

    async def list_transactions(
        self,
        *,
        principal: AuthenticatedPrincipal,
        page: int,
        transaction_type: TransactionType | None,
        category_id: str | None,
        account_id: str | None,
        search: str | None,
    ) -> TransactionPageResponse:
        limit = 50
        account_ids = await self.repository.accessible_account_ids(principal.user_id)
        total = await self.repository.count_list(
            account_ids=account_ids,
            transaction_type=transaction_type,
            category_id=category_id,
            account_id=account_id,
            search=search,
        )
        rows = await self.repository.list_page(
            offset=(page - 1) * limit,
            limit=limit,
            account_ids=account_ids,
            transaction_type=transaction_type,
            category_id=category_id,
            account_id=account_id,
            search=search,
        )
        responses = [
            await self._response(row.transaction, transaction_type=row.effective_type)
            for row in rows
        ]
        await self.session.commit()
        return TransactionPageResponse(
            transactions=responses,
            total=total,
            page=page,
            pages=(total + limit - 1) // limit,
        )

    async def create(
        self,
        *,
        principal: AuthenticatedPrincipal,
        payload: TransactionCreateRequest,
    ) -> TransactionResponse:
        await require_account_access(
            session=self.session,
            principal=principal,
            account_id=payload.account_id,
            allowed_roles=_WRITE_ROLES,
            for_update=True,
        )
        history = PortfolioHistoryInvalidationService(self.session)
        locked_memberships = await history.lock_current_memberships((payload.account_id,))
        key = (
            f"transaction:create:{principal.user_id}:{payload.account_id}:{payload.idempotency_key}"
        )
        await self.repository.lock_idempotency_key(key)
        transaction_id = str(uuid5(_TRANSACTION_NAMESPACE, key))
        existing = await self.repository.load_for_user(
            transaction_id=transaction_id,
            user_id=principal.user_id,
            active_only=False,
            for_update=False,
        )
        amount = _signed_amount(payload.amount, payload.type)
        category = await self._category(
            principal=principal,
            category_id=payload.category_id,
            transaction_type=payload.type,
        )
        if existing is not None:
            if not self._matches_payload(existing, payload, amount):
                await self.session.rollback()
                raise TransactionConflictError("The idempotency key has already been used.")
            await self._record(
                existing,
                replay=True,
                history=history,
                locked_memberships=locked_memberships,
            )
            await self.session.commit()
            return await self._response(existing, category=category)

        now = _now()
        await self.repository.ensure_canonical_state(payload.account_id, now)
        transaction = TransactionModel(
            id=transaction_id,
            date=payload.date,
            booking_date=None,
            amount=amount,
            currency=payload.currency,
            reporting_amount=None,
            reporting_currency=None,
            type=payload.type,
            classification=_classification(payload.type),
            description=payload.description,
            note=payload.note,
            counterparty=payload.counterparty,
            external_id=None,
            is_reviewed=True,
            archived_at=None,
            deleted_at=None,
            category_id=payload.category_id,
            account_id=payload.account_id,
            import_batch_id=None,
            created_at=now,
            updated_at=now,
        )
        await self._record(
            transaction,
            replay=False,
            history=history,
            locked_memberships=locked_memberships,
        )
        self.repository.add(transaction)
        await self._commit()
        return await self._response(transaction, category=category)

    async def update(
        self,
        *,
        principal: AuthenticatedPrincipal,
        transaction_id: str,
        payload: TransactionUpdateRequest,
    ) -> TransactionResponse:
        key = f"transaction:update:{principal.user_id}:{transaction_id}:{payload.idempotency_key}"
        await self.repository.lock_idempotency_key(key)
        replacement_id = str(uuid5(_TRANSACTION_NAMESPACE, key))
        replacement = await self.repository.load_for_user(
            transaction_id=replacement_id,
            user_id=principal.user_id,
            active_only=False,
            for_update=False,
        )
        if replacement is not None:
            original = await self.repository.load_for_user(
                transaction_id=transaction_id,
                user_id=principal.user_id,
                active_only=False,
                for_update=False,
            )
            if original is None or not self._matches_update(replacement, original, payload):
                await self.session.rollback()
                raise TransactionConflictError("The idempotency key has already been used.")
            history = PortfolioHistoryInvalidationService(self.session)
            locked_memberships = await history.lock_current_memberships((replacement.account_id,))
            await self._record(
                replacement,
                replay=True,
                history=history,
                locked_memberships=locked_memberships,
            )
            await self.session.commit()
            return await self._response(replacement)

        original = await self.repository.load_for_user(
            transaction_id=transaction_id,
            user_id=principal.user_id,
            active_only=True,
            for_update=True,
        )
        if original is None:
            await self.session.rollback()
            raise TransactionNotFoundError()
        if await self.repository.has_pair_or_splits(original.id):
            await self.session.rollback()
            raise TransactionConflictError(
                "Paired or split transactions require a dedicated edit operation."
            )
        history = PortfolioHistoryInvalidationService(self.session)
        locked_memberships = await history.lock_current_memberships((original.account_id,))

        transaction_type = payload.type or original.type
        raw_amount = payload.amount if payload.amount is not None else abs(original.amount)
        category_id = (
            payload.category_id
            if "category_id" in payload.model_fields_set
            else original.category_id
        )
        category = await self._category(
            principal=principal,
            category_id=category_id,
            transaction_type=transaction_type,
        )
        now = _now()
        await self.repository.ensure_canonical_state(original.account_id, now)
        replacement = TransactionModel(
            id=replacement_id,
            date=payload.date if payload.date is not None else original.date,
            booking_date=original.booking_date,
            amount=_signed_amount(raw_amount, transaction_type),
            currency=payload.currency or original.currency,
            reporting_amount=None,
            reporting_currency=None,
            type=transaction_type,
            classification=_classification(transaction_type),
            description=(
                payload.description
                if "description" in payload.model_fields_set
                else original.description
            ),
            note=payload.note if "note" in payload.model_fields_set else original.note,
            counterparty=(
                payload.counterparty
                if "counterparty" in payload.model_fields_set
                else original.counterparty
            ),
            external_id=None,
            is_reviewed=True,
            archived_at=None,
            deleted_at=None,
            category_id=category_id,
            account_id=original.account_id,
            import_batch_id=None,
            created_at=now,
            updated_at=now,
        )
        original.deleted_at = now
        original.updated_at = now
        await self._record(
            replacement,
            replay=False,
            history=history,
            locked_memberships=locked_memberships,
        )
        self.repository.add(replacement)
        await self._commit()
        return await self._response(replacement, category=category)

    async def delete(
        self,
        *,
        principal: AuthenticatedPrincipal,
        transaction_id: str,
        idempotency_key: str,
    ) -> None:
        key = f"transaction:delete:{principal.user_id}:{transaction_id}:{idempotency_key}"
        await self.repository.lock_idempotency_key(key)
        tombstone_id = str(uuid5(_TRANSACTION_NAMESPACE, key))
        tombstone = await self.repository.load_for_user(
            transaction_id=tombstone_id,
            user_id=principal.user_id,
            active_only=False,
            for_update=False,
        )
        if tombstone is not None:
            if tombstone.deleted_at is None:
                await self.session.rollback()
                raise TransactionConflictError()
            history = PortfolioHistoryInvalidationService(self.session)
            locked_memberships = await history.lock_current_memberships((tombstone.account_id,))
            await self._record(
                tombstone,
                replay=True,
                history=history,
                locked_memberships=locked_memberships,
            )
            await self.session.commit()
            return

        original = await self.repository.load_for_user(
            transaction_id=transaction_id,
            user_id=principal.user_id,
            active_only=True,
            for_update=True,
        )
        if original is None:
            await self.session.rollback()
            raise TransactionNotFoundError()
        if await self.repository.has_pair_or_splits(original.id):
            await self.session.rollback()
            raise TransactionConflictError(
                "Paired or split transactions require a dedicated delete operation."
            )
        history = PortfolioHistoryInvalidationService(self.session)
        locked_memberships = await history.lock_current_memberships((original.account_id,))
        now = _now()
        await self.repository.ensure_canonical_state(original.account_id, now)
        original.deleted_at = now
        original.updated_at = now
        tombstone = TransactionModel(
            id=tombstone_id,
            date=original.date,
            booking_date=original.booking_date,
            amount=original.amount,
            currency=original.currency,
            reporting_amount=original.reporting_amount,
            reporting_currency=original.reporting_currency,
            type=original.type,
            classification=original.classification,
            description=original.description,
            note=original.note,
            counterparty=original.counterparty,
            external_id=None,
            is_reviewed=original.is_reviewed,
            archived_at=None,
            deleted_at=now,
            category_id=original.category_id,
            account_id=original.account_id,
            import_batch_id=None,
            created_at=now,
            updated_at=now,
        )
        await self._record(
            tombstone,
            replay=False,
            history=history,
            locked_memberships=locked_memberships,
        )
        self.repository.add(tombstone)
        await self._commit()

    async def _category(
        self,
        *,
        principal: AuthenticatedPrincipal,
        category_id: str | None,
        transaction_type: TransactionType,
    ) -> CategoryModel | None:
        if category_id is None:
            return None
        category = await self.repository.category(category_id)
        expected_type = (
            CategoryType.income
            if transaction_type is TransactionType.income
            else CategoryType.expense
            if transaction_type is TransactionType.expense
            else CategoryType.both
        )
        if (
            category is None
            or (not category.is_default and category.user_id != principal.user_id)
            or category.type not in {CategoryType.both, expected_type}
        ):
            raise TransactionCategoryError()
        return category

    async def _record(
        self,
        transaction: TransactionModel,
        *,
        replay: bool,
        history: PortfolioHistoryInvalidationService,
        locked_memberships: tuple[tuple[str, str], ...],
    ) -> None:
        try:
            recorded = await CanonicalStateService(self.session).record(
                account_id=transaction.account_id,
                kind=CanonicalChangeKind.transaction,
                entity_id=transaction.id,
                financial_timestamp=transaction.date,
                created_at=transaction.created_at,
                replay=replay,
            )
            await history.invalidate_recorded_changes(
                changes=(recorded,),
                locked_memberships=locked_memberships,
                now=_now(),
            )
        except (CanonicalStateError, PortfolioHistoryInvalidationStateError) as exc:
            raise TransactionConflictError("Canonical transaction state is unavailable.") from exc

    async def _response(
        self,
        transaction: TransactionModel,
        *,
        category: CategoryModel | None = None,
        transaction_type: TransactionType | None = None,
    ) -> TransactionResponse:
        account = await self.repository.account(transaction.account_id)
        if account is None:
            raise TransactionConflictError()
        if category is None and transaction.category_id is not None:
            category = await self.repository.category(transaction.category_id)
        return self._to_response(transaction, account, category, transaction_type=transaction_type)

    async def _commit(self) -> None:
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    @staticmethod
    def _to_response(
        transaction: TransactionModel,
        account: AccountModel,
        category: CategoryModel | None,
        *,
        transaction_type: TransactionType | None = None,
    ) -> TransactionResponse:
        return TransactionResponse(
            id=transaction.id,
            date=transaction.date,
            amount=transaction.amount,
            currency=transaction.currency,
            type=transaction.type if transaction_type is None else transaction_type,
            description=transaction.description,
            counterparty=transaction.counterparty,
            note=transaction.note,
            account_id=transaction.account_id,
            category_id=transaction.category_id,
            category=(
                None
                if category is None
                else TransactionCategoryResponse(
                    id=category.id,
                    name=category.name,
                    icon=category.icon,
                    color=category.color,
                    type=category.type,
                )
            ),
            account=TransactionAccountResponse(name=account.name, currency=account.currency),
        )

    @staticmethod
    def _matches_payload(
        transaction: TransactionModel,
        payload: TransactionCreateRequest,
        amount: Decimal,
    ) -> bool:
        return (
            transaction.date == payload.date
            and transaction.amount == amount
            and transaction.currency == payload.currency
            and transaction.type is payload.type
            and transaction.description == payload.description
            and transaction.counterparty == payload.counterparty
            and transaction.note == payload.note
            and transaction.category_id == payload.category_id
            and transaction.account_id == payload.account_id
            and transaction.deleted_at is None
        )

    @staticmethod
    def _matches_update(
        replacement: TransactionModel,
        original: TransactionModel,
        payload: TransactionUpdateRequest,
    ) -> bool:
        transaction_type = payload.type or original.type
        raw_amount = payload.amount if payload.amount is not None else abs(original.amount)
        category_id = (
            payload.category_id
            if "category_id" in payload.model_fields_set
            else original.category_id
        )
        return (
            replacement.date == (payload.date if payload.date is not None else original.date)
            and replacement.amount == _signed_amount(raw_amount, transaction_type)
            and replacement.currency == (payload.currency or original.currency)
            and replacement.type is transaction_type
            and replacement.description
            == (
                payload.description
                if "description" in payload.model_fields_set
                else original.description
            )
            and replacement.counterparty
            == (
                payload.counterparty
                if "counterparty" in payload.model_fields_set
                else original.counterparty
            )
            and replacement.note
            == (payload.note if "note" in payload.model_fields_set else original.note)
            and replacement.category_id == category_id
            and replacement.account_id == original.account_id
            and replacement.deleted_at is None
        )
