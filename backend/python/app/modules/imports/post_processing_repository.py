"""Persistence boundary for deterministic import post-processing audit logs."""

from __future__ import annotations

from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.imports import ImportLogModel


def import_post_processing_audit_lock_id(log_id: str) -> int:
    scope = f"imports:post-processing:audit\0{log_id}"
    return int.from_bytes(sha256(scope.encode()).digest()[:8], "big", signed=True)


class ImportBatchPostProcessingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def acquire_audit_lock(self, log_id: str) -> None:
        await self.session.execute(
            select(func.pg_advisory_xact_lock(import_post_processing_audit_lock_id(log_id)))
        )

    async def load_log_for_update(self, log_id: str) -> ImportLogModel | None:
        return await self.session.scalar(
            select(ImportLogModel)
            .where(ImportLogModel.id == log_id)
            .with_for_update()
            .execution_options(autoflush=False, populate_existing=True)
        )

    def add_log(self, log: ImportLogModel) -> None:
        self.session.add(log)

    async def flush(self) -> None:
        await self.session.flush()
