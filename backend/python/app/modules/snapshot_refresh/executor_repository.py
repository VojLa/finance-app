"""Transaction-boundary SQL for coordinated snapshot refresh execution."""

from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.canonical_lineage import (
    SnapshotGenerationModel,
    SnapshotGenerationTargetModel,
)


class SnapshotRefreshExecutorRepository:
    """Own only the executor's initial coverage-transaction isolation statement."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_transaction_repeatable_read(self) -> None:
        await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))

    async def ensure_staged_generation(
        self,
        *,
        generation_id: str,
        user_id: str,
        created_at: datetime,
    ) -> None:
        generation = await self.session.get(SnapshotGenerationModel, generation_id)
        if generation is None:
            generation = SnapshotGenerationModel(
                id=generation_id,
                state="staged",
                created_at=created_at,
                published_at=None,
            )
            self.session.add(generation)
            await self.session.flush()
        elif generation.state == "published" and generation.published_at is not None:
            pass
        elif generation.state != "staged" or generation.published_at is not None:
            raise RuntimeError("Snapshot generation is no longer stageable.")
        target = await self.session.get(
            SnapshotGenerationTargetModel,
            (generation_id, user_id),
        )
        if target is None:
            self.session.add(
                SnapshotGenerationTargetModel(
                    generation_id=generation_id,
                    user_id=user_id,
                    created_at=created_at,
                )
            )
            await self.session.flush()
