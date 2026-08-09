from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.categories import CategoryModel
from app.db.models.transactions import TransactionModel


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
    ) -> list[tuple[TransactionModel, CategoryModel | None]]:
        if not account_ids:
            return []
        return [
            (transaction, category)
            for transaction, category in (
                await self.session.execute(
                    select(TransactionModel, CategoryModel)
                    .outerjoin(CategoryModel, CategoryModel.id == TransactionModel.category_id)
                    .where(
                        TransactionModel.account_id.in_(account_ids),
                        TransactionModel.type.in_(("income", "expense")),
                        TransactionModel.date >= start,
                        TransactionModel.date < end,
                        TransactionModel.archived_at.is_(None),
                        TransactionModel.deleted_at.is_(None),
                    )
                    .order_by(TransactionModel.date, TransactionModel.id)
                )
            ).all()
        ]

    async def recent_transactions(
        self, *, account_ids: tuple[str, ...], limit: int
    ) -> list[tuple[TransactionModel, AccountModel, CategoryModel | None]]:
        if not account_ids:
            return []
        return [
            (transaction, account, category)
            for transaction, account, category in (
                await self.session.execute(
                    select(TransactionModel, AccountModel, CategoryModel)
                    .join(AccountModel, AccountModel.id == TransactionModel.account_id)
                    .outerjoin(CategoryModel, CategoryModel.id == TransactionModel.category_id)
                    .where(
                        TransactionModel.account_id.in_(account_ids),
                        TransactionModel.archived_at.is_(None),
                        TransactionModel.deleted_at.is_(None),
                    )
                    .order_by(TransactionModel.date.desc(), TransactionModel.id.desc())
                    .limit(limit)
                )
            ).all()
        ]
