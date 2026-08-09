from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.budgets import (
    BudgetAccountModel,
    BudgetAlertModel,
    BudgetItemCategoryModel,
    BudgetItemModel,
    BudgetModel,
)
from app.db.models.categories import CategoryModel
from app.db.models.transactions import TransactionModel


class BudgetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_month(self, user_id: str, month: int, year: int) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:value))"),
            {"value": f"budget:{user_id}:{year:04d}-{month:02d}"},
        )

    async def load_budget(
        self,
        *,
        user_id: str,
        start: datetime,
        end: datetime,
        for_update: bool = False,
    ) -> BudgetModel | None:
        statement = select(BudgetModel).where(
            BudgetModel.user_id == user_id,
            BudgetModel.period_start == start,
            BudgetModel.period_end == end,
            BudgetModel.name == "Monthly budget",
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

    async def items_with_categories(
        self, budget_id: str
    ) -> list[tuple[BudgetItemModel, CategoryModel]]:
        return [
            (item, category)
            for item, category in (
                await self.session.execute(
                    select(BudgetItemModel, CategoryModel)
                    .join(
                        BudgetItemCategoryModel,
                        BudgetItemCategoryModel.budget_item_id == BudgetItemModel.id,
                    )
                    .join(CategoryModel, CategoryModel.id == BudgetItemCategoryModel.category_id)
                    .where(BudgetItemModel.budget_id == budget_id)
                    .order_by(BudgetItemModel.created_at, BudgetItemModel.id, CategoryModel.id)
                )
            ).all()
        ]

    async def budget_account_ids(self, budget_id: str) -> tuple[str, ...]:
        return tuple(
            (
                await self.session.scalars(
                    select(BudgetAccountModel.account_id)
                    .where(BudgetAccountModel.budget_id == budget_id)
                    .order_by(BudgetAccountModel.account_id)
                )
            ).all()
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

    async def accessible_categories(
        self, *, user_id: str, category_ids: tuple[str, ...]
    ) -> list[CategoryModel]:
        if not category_ids:
            return []
        return list(
            (
                await self.session.scalars(
                    select(CategoryModel).where(
                        CategoryModel.id.in_(category_ids),
                        or_(CategoryModel.is_default.is_(True), CategoryModel.user_id == user_id),
                    )
                )
            ).all()
        )

    async def expense_transactions(
        self,
        *,
        account_ids: tuple[str, ...],
        category_ids: tuple[str, ...],
        start: datetime,
        end: datetime,
    ) -> list[TransactionModel]:
        if not account_ids or not category_ids:
            return []
        return list(
            (
                await self.session.scalars(
                    select(TransactionModel).where(
                        TransactionModel.account_id.in_(account_ids),
                        TransactionModel.category_id.in_(category_ids),
                        TransactionModel.type == "expense",
                        TransactionModel.date >= start,
                        TransactionModel.date < end,
                        TransactionModel.archived_at.is_(None),
                        TransactionModel.deleted_at.is_(None),
                    )
                )
            ).all()
        )

    async def replace_children(self, budget_id: str) -> None:
        item_ids = select(BudgetItemModel.id).where(BudgetItemModel.budget_id == budget_id)
        await self.session.execute(
            delete(BudgetAlertModel).where(BudgetAlertModel.budget_item_id.in_(item_ids))
        )
        await self.session.execute(
            delete(BudgetItemCategoryModel).where(
                BudgetItemCategoryModel.budget_item_id.in_(item_ids)
            )
        )
        await self.session.execute(
            delete(BudgetItemModel).where(BudgetItemModel.budget_id == budget_id)
        )
        await self.session.execute(
            delete(BudgetAccountModel).where(BudgetAccountModel.budget_id == budget_id)
        )

    def add(self, value: object) -> None:
        self.session.add(value)
