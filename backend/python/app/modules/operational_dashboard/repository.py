from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.categories import CategoryModel
from app.db.models.transactions import TransactionModel
from app.modules.transactions.operational_visibility import (
    OperationalTransaction,
    operational_projection_columns,
    operational_transaction_from_values,
    operational_transactions_for_candidates,
    operational_visibility_predicate,
)


class OperationalDashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

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

    async def trend_transactions(
        self, *, account_ids: tuple[str, ...], start: datetime, end: datetime
    ) -> list[tuple[OperationalTransaction, CategoryModel | None]]:
        if not account_ids:
            return []
        return [
            (
                operational_transaction_from_values(transaction, classification, amount, currency),
                category,
            )
            for transaction, classification, amount, currency, category in (
                await self.session.execute(
                    select(TransactionModel, *operational_projection_columns(), CategoryModel)
                    .outerjoin(CategoryModel, CategoryModel.id == TransactionModel.category_id)
                    .where(
                        TransactionModel.account_id.in_(account_ids),
                        TransactionModel.date >= start,
                        TransactionModel.date < end,
                        TransactionModel.archived_at.is_(None),
                        TransactionModel.deleted_at.is_(None),
                        operational_visibility_predicate(),
                    )
                    .order_by(TransactionModel.date, TransactionModel.id)
                )
            ).all()
        ]

    async def recent_transactions(
        self, *, account_ids: tuple[str, ...], limit: int
    ) -> list[tuple[OperationalTransaction, AccountModel, CategoryModel | None]]:
        if not account_ids or limit <= 0:
            return []
        result: list[tuple[OperationalTransaction, AccountModel, CategoryModel | None]] = []
        last_key: tuple[datetime, str] | None = None
        page_size = max(64, min(limit, 128))
        while len(result) < limit:
            query = (
                select(TransactionModel, AccountModel, CategoryModel)
                .join(AccountModel, AccountModel.id == TransactionModel.account_id)
                .outerjoin(CategoryModel, CategoryModel.id == TransactionModel.category_id)
                .where(
                    TransactionModel.account_id.in_(account_ids),
                    TransactionModel.archived_at.is_(None),
                    TransactionModel.deleted_at.is_(None),
                )
                .order_by(TransactionModel.date.desc(), TransactionModel.id.desc())
                .limit(page_size)
            )
            if last_key is not None:
                last_date, last_id = last_key
                query = query.where(
                    or_(
                        TransactionModel.date < last_date,
                        and_(TransactionModel.date == last_date, TransactionModel.id < last_id),
                    )
                )
            candidates = (await self.session.execute(query)).all()
            if not candidates:
                break
            visible = await operational_transactions_for_candidates(
                self.session, [transaction for transaction, _, _ in candidates]
            )
            for transaction, account, category in candidates:
                operational = visible.get(transaction.id)
                if operational is not None:
                    result.append((operational, account, category))
                    if len(result) == limit:
                        break
            last_transaction = candidates[-1][0]
            last_key = (last_transaction.date, last_transaction.id)
            if len(candidates) < page_size:
                break
        return result
