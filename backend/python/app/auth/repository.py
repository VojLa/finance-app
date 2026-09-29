from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.users import UserModel


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_email(self, email: str) -> UserModel | None:
        return await self.session.scalar(
            select(UserModel).where(func.lower(UserModel.email) == email)
        )

    async def find_by_id_for_update(self, user_id: str) -> UserModel | None:
        return await self.session.scalar(
            select(UserModel).where(UserModel.id == user_id).with_for_update()
        )

    def add(self, user: UserModel) -> None:
        self.session.add(user)
