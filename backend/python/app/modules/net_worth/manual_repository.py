"""Read boundary for authenticated manual net-worth recalculation."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.users import UserModel


class ManualNetWorthSnapshotRepository:
    """Load only the persisted user metadata required by public orchestration."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_user(self, user_id: str) -> UserModel | None:
        return await self.session.scalar(
            select(UserModel)
            .where(UserModel.id == user_id)
            .execution_options(autoflush=False, populate_existing=True)
        )
