"""Transaction-boundary SQL for coordinated snapshot refresh execution."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class SnapshotRefreshExecutorRepository:
    """Own only the executor's initial coverage-transaction isolation statement."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_transaction_repeatable_read(self) -> None:
        await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
