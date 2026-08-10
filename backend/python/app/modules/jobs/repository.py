from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import case, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_jobs import BackgroundJobModel
from app.db.models.enums import BackgroundJobKind, BackgroundJobStatus
from app.modules.jobs.lifecycle import LeaseIdentity


@dataclass(frozen=True, slots=True)
class EnqueuedBackgroundJob:
    job: BackgroundJobModel
    created: bool


@dataclass(frozen=True, slots=True)
class ClaimedBackgroundJob:
    job: BackgroundJobModel
    lease: LeaseIdentity


class BackgroundJobLeaseLostError(RuntimeError):
    """A stale worker attempted to mutate a lease it no longer owns."""


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

    async def claim_next(
        self,
        *,
        worker_id: str,
        now: datetime,
        lease_duration: timedelta,
    ) -> ClaimedBackgroundJob | None:
        if (
            not worker_id
            or worker_id != worker_id.strip()
            or len(worker_id) > 200
            or now.tzinfo is not None
            or lease_duration <= timedelta(0)
            or lease_duration > timedelta(minutes=30)
        ):
            raise ValueError("The background job claim boundary is invalid.")

        await self.session.execute(
            update(BackgroundJobModel)
            .where(
                BackgroundJobModel.status == BackgroundJobStatus.running,
                BackgroundJobModel.lease_expires_at <= now,
                BackgroundJobModel.attempt_count >= BackgroundJobModel.max_attempts,
            )
            .values(
                status=BackgroundJobStatus.failed,
                result=None,
                error_code="background_job_attempts_exhausted",
                error_message="Background processing could not be completed after all retries.",
                lease_owner=None,
                lease_expires_at=None,
                lease_heartbeat_at=None,
                finished_at=now,
                updated_at=now,
            )
        )

        candidate = BackgroundJobModel
        other = BackgroundJobModel.__table__.alias("other_running_job")
        other_running = exists(
            select(1)
            .select_from(other)
            .where(
                other.c.accountId == candidate.account_id,
                other.c.status == BackgroundJobStatus.running,
                other.c.id != candidate.id,
            )
        )
        ready = (
            select(candidate)
            .where(
                candidate.attempt_count < candidate.max_attempts,
                or_(
                    (
                        (candidate.status == BackgroundJobStatus.running)
                        & (candidate.lease_expires_at <= now)
                    ),
                    (
                        candidate.status.in_(
                            (BackgroundJobStatus.queued, BackgroundJobStatus.retry_wait)
                        )
                        & (candidate.run_after <= now)
                        & ~other_running
                    ),
                ),
            )
            .order_by(
                case((candidate.status == BackgroundJobStatus.running, 0), else_=1),
                candidate.run_after,
                candidate.created_at,
                candidate.id,
            )
            .with_for_update(skip_locked=True)
            .limit(1)
            .execution_options(populate_existing=True)
        )
        job = await self.session.scalar(ready)
        if job is None:
            return None

        lock_scope = f"background-job-account:{job.account_id}"
        lock_id = int.from_bytes(sha256(lock_scope.encode()).digest()[:8], "big", signed=True)
        await self.session.execute(select(func.pg_advisory_xact_lock(lock_id)))
        conflicting = await self.session.scalar(
            select(BackgroundJobModel.id).where(
                BackgroundJobModel.account_id == job.account_id,
                BackgroundJobModel.status == BackgroundJobStatus.running,
                BackgroundJobModel.id != job.id,
            )
        )
        if conflicting is not None:
            return None

        job.status = BackgroundJobStatus.running
        job.lease_owner = worker_id
        job.lease_version += 1
        job.lease_expires_at = now + lease_duration
        job.lease_heartbeat_at = now
        job.attempt_count += 1
        job.started_at = job.started_at or now
        job.finished_at = None
        job.updated_at = now
        await self.session.flush()
        lease = LeaseIdentity(job_id=job.id, owner=worker_id, version=job.lease_version)
        return ClaimedBackgroundJob(job=job, lease=lease)

    async def heartbeat(
        self,
        *,
        lease: LeaseIdentity,
        now: datetime,
        lease_duration: timedelta,
    ) -> None:
        if now.tzinfo is not None or not timedelta(0) < lease_duration <= timedelta(minutes=30):
            raise ValueError("The heartbeat boundary is invalid.")
        await self._fenced_update(
            lease,
            values={
                "lease_expires_at": now + lease_duration,
                "lease_heartbeat_at": now,
                "updated_at": now,
            },
        )

    async def checkpoint(
        self,
        *,
        lease: LeaseIdentity,
        checkpoint: dict[str, Any],
        progress: dict[str, Any],
        now: datetime,
    ) -> None:
        if now.tzinfo is not None:
            raise ValueError("The checkpoint timestamp is invalid.")
        await self._fenced_update(
            lease,
            values={"checkpoint": checkpoint, "progress": progress, "updated_at": now},
        )

    async def complete(
        self,
        *,
        lease: LeaseIdentity,
        result: dict[str, Any],
        progress: dict[str, Any],
        now: datetime,
    ) -> None:
        if now.tzinfo is not None:
            raise ValueError("The completion timestamp is invalid.")
        await self._fenced_update(
            lease,
            values={
                "status": BackgroundJobStatus.completed,
                "result": result,
                "progress": progress,
                "error_code": None,
                "error_message": None,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_heartbeat_at": None,
                "finished_at": now,
                "updated_at": now,
            },
        )

    async def schedule_retry(
        self,
        *,
        lease: LeaseIdentity,
        run_after: datetime,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> None:
        self._validate_safe_error(error_code, error_message)
        if now.tzinfo is not None or run_after.tzinfo is not None or run_after <= now:
            raise ValueError("The retry timestamp is invalid.")
        await self._fenced_update(
            lease,
            values={
                "status": BackgroundJobStatus.retry_wait,
                "run_after": run_after,
                "error_code": error_code,
                "error_message": error_message,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_heartbeat_at": None,
                "updated_at": now,
            },
        )

    async def fail(
        self,
        *,
        lease: LeaseIdentity,
        error_code: str,
        error_message: str,
        now: datetime,
    ) -> None:
        self._validate_safe_error(error_code, error_message)
        if now.tzinfo is not None:
            raise ValueError("The failure timestamp is invalid.")
        await self._fenced_update(
            lease,
            values={
                "status": BackgroundJobStatus.failed,
                "result": None,
                "error_code": error_code,
                "error_message": error_message,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_heartbeat_at": None,
                "finished_at": now,
                "updated_at": now,
            },
        )

    async def release(
        self,
        *,
        lease: LeaseIdentity,
        now: datetime,
    ) -> None:
        if now.tzinfo is not None:
            raise ValueError("The release timestamp is invalid.")
        await self._fenced_update(
            lease,
            values={
                "status": BackgroundJobStatus.queued,
                "run_after": now,
                "attempt_count": BackgroundJobModel.attempt_count - 1,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_heartbeat_at": None,
                "updated_at": now,
            },
        )

    async def _fenced_update(
        self,
        lease: LeaseIdentity,
        *,
        values: dict[str, Any],
    ) -> None:
        statement = (
            update(BackgroundJobModel)
            .where(
                BackgroundJobModel.id == lease.job_id,
                BackgroundJobModel.status == BackgroundJobStatus.running,
                BackgroundJobModel.lease_owner == lease.owner,
                BackgroundJobModel.lease_version == lease.version,
            )
            .values(**values)
        )
        result = cast(CursorResult[Any], await self.session.execute(statement))
        if result.rowcount != 1:
            raise BackgroundJobLeaseLostError("The background job lease is no longer owned.")

    @staticmethod
    def _validate_safe_error(code: str, message: str) -> None:
        if (
            not code
            or code != code.strip()
            or len(code) > 100
            or not message
            or message != message.strip()
            or len(message) > 1000
            or "\n" in code
            or "\r" in code
            or "\n" in message
            or "\r" in message
        ):
            raise ValueError("The public background job error is invalid.")
