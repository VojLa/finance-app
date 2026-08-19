from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.canonical_lineage import (
    AccountCanonicalChangeModel,
    AccountCanonicalStateModel,
)
from app.db.models.categories import CategoryModel
from app.db.models.enums import AccountMemberRole, TransactionType
from app.db.models.transactions import (
    TransactionModel,
    TransactionPairModel,
    TransactionSplitModel,
)
from app.modules.transactions.operational_visibility import (
    OperationalTransaction,
    operational_effective_type_expression,
    operational_projection_columns,
    operational_transaction_from_values,
    operational_visibility_predicate,
)

WRITE_ROLES = {
    AccountMemberRole.owner,
    AccountMemberRole.admin,
    AccountMemberRole.editor,
}


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_idempotency_key(self, value: str) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:value))"),
            {"value": value},
        )

    async def accessible_account_ids(self, user_id: str) -> tuple[str, ...]:
        return tuple(
            (
                await self.session.scalars(
                    select(AccountMemberModel.account_id)
                    .join(AccountModel, AccountModel.id == AccountMemberModel.account_id)
                    .where(
                        AccountMemberModel.user_id == user_id,
                        AccountModel.is_archived.is_(False),
                    )
                    .order_by(AccountMemberModel.account_id)
                )
            ).all()
        )

    def _list_statement(
        self,
        *,
        account_ids: tuple[str, ...],
        transaction_type: TransactionType | None,
        category_id: str | None,
        account_id: str | None,
        search: str | None,
    ) -> Select:
        selected_ids = (
            (account_id,) if account_id is not None and account_id in account_ids else account_ids
        )
        statement = select(TransactionModel).where(
            TransactionModel.account_id.in_(selected_ids),
            TransactionModel.archived_at.is_(None),
            TransactionModel.deleted_at.is_(None),
            operational_visibility_predicate(),
        )
        if account_id is not None and account_id not in account_ids:
            statement = statement.where(text("false"))
        if transaction_type is not None:
            statement = statement.where(operational_effective_type_expression() == transaction_type)
        if category_id is not None:
            statement = statement.where(TransactionModel.category_id == category_id)
        if search is not None:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            statement = statement.where(
                or_(
                    TransactionModel.description.ilike(pattern, escape="\\"),
                    TransactionModel.counterparty.ilike(pattern, escape="\\"),
                )
            )
        return statement

    async def count_list(
        self,
        *,
        account_ids: tuple[str, ...],
        transaction_type: TransactionType | None,
        category_id: str | None,
        account_id: str | None,
        search: str | None,
    ) -> int:
        statement = self._list_statement(
            account_ids=account_ids,
            transaction_type=transaction_type,
            category_id=category_id,
            account_id=account_id,
            search=search,
        )
        return int(
            (await self.session.scalar(select(func.count()).select_from(statement.subquery()))) or 0
        )

    async def list_page(
        self,
        *,
        account_ids: tuple[str, ...],
        transaction_type: TransactionType | None,
        category_id: str | None,
        account_id: str | None,
        search: str | None,
        offset: int,
        limit: int,
    ) -> list[OperationalTransaction]:
        statement = self._list_statement(
            account_ids=account_ids,
            transaction_type=transaction_type,
            category_id=category_id,
            account_id=account_id,
            search=search,
        )
        rows = (
            await self.session.execute(
                statement.add_columns(*operational_projection_columns())
                .order_by(TransactionModel.date.desc(), TransactionModel.id.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [
            operational_transaction_from_values(transaction, classification, amount, currency)
            for transaction, classification, amount, currency in rows
        ]

    async def load_for_user(
        self,
        *,
        transaction_id: str,
        user_id: str,
        active_only: bool,
        for_update: bool,
    ) -> TransactionModel | None:
        statement = (
            select(TransactionModel)
            .join(AccountMemberModel, AccountMemberModel.account_id == TransactionModel.account_id)
            .join(AccountModel, AccountModel.id == TransactionModel.account_id)
            .where(
                TransactionModel.id == transaction_id,
                AccountMemberModel.user_id == user_id,
                AccountMemberModel.role.in_(WRITE_ROLES),
                AccountModel.is_archived.is_(False),
            )
        )
        if active_only:
            statement = statement.where(
                TransactionModel.archived_at.is_(None),
                TransactionModel.deleted_at.is_(None),
                operational_visibility_predicate(),
            )
        if for_update:
            statement = statement.with_for_update(of=TransactionModel)
        return await self.session.scalar(statement)

    async def category(self, category_id: str) -> CategoryModel | None:
        return await self.session.get(CategoryModel, category_id)

    async def account(self, account_id: str) -> AccountModel | None:
        return await self.session.get(AccountModel, account_id)

    async def has_pair_or_splits(self, transaction_id: str) -> bool:
        pair = await self.session.scalar(
            select(TransactionPairModel.id).where(
                or_(
                    TransactionPairModel.from_transaction_id == transaction_id,
                    TransactionPairModel.to_transaction_id == transaction_id,
                )
            )
        )
        split = await self.session.scalar(
            select(TransactionSplitModel.id).where(
                TransactionSplitModel.transaction_id == transaction_id
            )
        )
        return pair is not None or split is not None

    async def ensure_canonical_state(self, account_id: str, now: datetime) -> None:
        state = await self.session.scalar(
            select(AccountCanonicalStateModel)
            .where(AccountCanonicalStateModel.account_id == account_id)
            .with_for_update()
        )
        if state is not None:
            return
        count = await self.session.scalar(
            select(func.count())
            .select_from(AccountCanonicalChangeModel)
            .where(AccountCanonicalChangeModel.account_id == account_id)
        )
        if count:
            raise RuntimeError("Canonical account state is unavailable.")
        self.session.add(
            AccountCanonicalStateModel(
                account_id=account_id,
                last_revision=0,
                last_investment_revision=0,
                holding_revision=None,
                updated_at=now,
            )
        )
        await self.session.flush()

    def add(self, transaction: TransactionModel) -> None:
        self.session.add(transaction)
