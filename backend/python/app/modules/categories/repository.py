from sqlalchemy import exists, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.categories import CategoryModel
from app.db.models.enums import CategoryType, TransactionType
from app.db.models.transactions import TransactionModel


class CategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_idempotency_key(self, value: str) -> None:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:value))"),
            {"value": value},
        )

    async def list_accessible(self, user_id: str) -> list[CategoryModel]:
        return list(
            (
                await self.session.scalars(
                    select(CategoryModel)
                    .where(
                        or_(CategoryModel.is_default.is_(True), CategoryModel.user_id == user_id)
                    )
                    .order_by(CategoryModel.name.asc(), CategoryModel.id.asc())
                )
            ).all()
        )

    async def get_accessible(self, *, category_id: str, user_id: str) -> CategoryModel | None:
        return await self.session.scalar(
            select(CategoryModel).where(
                CategoryModel.id == category_id,
                or_(CategoryModel.is_default.is_(True), CategoryModel.user_id == user_id),
            )
        )

    async def get_owned_for_update(
        self,
        *,
        category_id: str,
        user_id: str,
    ) -> CategoryModel | None:
        return await self.session.scalar(
            select(CategoryModel)
            .where(
                CategoryModel.id == category_id,
                CategoryModel.user_id == user_id,
                CategoryModel.is_default.is_(False),
            )
            .with_for_update()
        )

    async def has_incompatible_active_transactions(
        self,
        *,
        category_id: str,
        category_type: CategoryType,
    ) -> bool:
        if category_type is CategoryType.both:
            return False
        compatible_type = (
            TransactionType.income
            if category_type is CategoryType.income
            else TransactionType.expense
        )
        return bool(
            await self.session.scalar(
                select(
                    exists().where(
                        TransactionModel.category_id == category_id,
                        TransactionModel.archived_at.is_(None),
                        TransactionModel.deleted_at.is_(None),
                        TransactionModel.type != compatible_type,
                    )
                )
            )
        )

    def add(self, category: CategoryModel) -> None:
        self.session.add(category)
