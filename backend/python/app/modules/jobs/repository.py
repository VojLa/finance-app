from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_jobs import BackgroundJobModel
from app.db.models.enums import BackgroundJobKind, BackgroundJobStatus


@dataclass(frozen=True, slots=True)
class EnqueuedBackgroundJob:
    job: BackgroundJobModel
    created: bool


class BackgroundJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue_import_job(
        self,
        *,
        user_id: str,
        account_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
        checkpoint: dict[str, Any],
        progress: dict[str, Any],
        max_attempts: int,
        now: datetime,
    ) -> EnqueuedBackgroundJob:
        values = {
            "id": str(uuid4()),
            "user_id": user_id,
            "account_id": account_id,
            "kind": BackgroundJobKind.import_workflow,
            "status": BackgroundJobStatus.queued,
            "idempotency_key": idempotency_key,
            "payload": payload,
            "checkpoint": checkpoint,
            "progress": progress,
            "result": None,
            "error_code": None,
            "error_message": None,
            "attempt_count": 0,
            "max_attempts": max_attempts,
            "manual_retry_count": 0,
            "run_after": now,
            "lease_owner": None,
            "lease_version": 0,
            "lease_expires_at": None,
            "lease_heartbeat_at": None,
            "started_at": None,
            "finished_at": None,
            "created_at": now,
            "updated_at": now,
        }
        statement = (
            insert(BackgroundJobModel)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=("userId", "accountId", "kind", "idempotencyKey")
            )
            .returning(BackgroundJobModel)
        )
        created = (await self.session.scalars(statement)).one_or_none()
        if created is not None:
            return EnqueuedBackgroundJob(job=created, created=True)
        replay = await self.get_owned_by_key(
            user_id=user_id,
            account_id=account_id,
            idempotency_key=idempotency_key,
        )
        if replay is None:
            raise RuntimeError("The canonical background job replay is missing.")
        return EnqueuedBackgroundJob(job=replay, created=False)

    async def get_owned_by_key(
        self,
        *,
        user_id: str,
        account_id: str,
        idempotency_key: str,
    ) -> BackgroundJobModel | None:
        return await self.session.scalar(
            select(BackgroundJobModel).where(
                BackgroundJobModel.user_id == user_id,
                BackgroundJobModel.account_id == account_id,
                BackgroundJobModel.kind == BackgroundJobKind.import_workflow,
                BackgroundJobModel.idempotency_key == idempotency_key,
            )
        )

    async def get_owned(
        self,
        *,
        user_id: str,
        account_id: str,
        job_id: str,
        for_update: bool = False,
    ) -> BackgroundJobModel | None:
        statement = select(BackgroundJobModel).where(
            BackgroundJobModel.id == job_id,
            BackgroundJobModel.user_id == user_id,
            BackgroundJobModel.account_id == account_id,
            BackgroundJobModel.kind == BackgroundJobKind.import_workflow,
        )
        if for_update:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return await self.session.scalar(statement)
