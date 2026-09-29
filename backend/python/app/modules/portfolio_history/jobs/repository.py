"""Fenced PostgreSQL lifecycle for ``PortfolioHistoryJob`` only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from sqlalchemy import case, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import BackgroundJobStatus, SnapshotSeriesJobKind
from app.db.models.snapshot_series_jobs import (
    SnapshotSeriesRebuildJobModel as PortfolioHistoryJobModel,
)
from app.modules.jobs.lifecycle import MAX_MANUAL_RETRIES, LeaseIdentity
from app.modules.portfolio_history.jobs.models import (
    PortfolioHistoryJobCheckpoint,
    PortfolioHistoryJobError,
    PortfolioHistoryJobProgress,
    PortfolioHistoryJobResult,
)

SAFE_EXHAUSTED_CODE = "history_job_attempts_exhausted"
SAFE_EXHAUSTED_MESSAGE = "History processing could not be completed after all retries."
SAFE_SCOPE_RETIRED_CODE = "history_scope_retired"
SAFE_SCOPE_RETIRED_MESSAGE = "History processing was retired after the user scope became empty."
_SCHEDULED_CAPTURE_INITIAL_ATTEMPTS = 5
MAX_SCHEDULED_CAPTURE_ATTEMPTS = 10
_SCHEDULED_CAPTURE_TRANSIENT_CODES = frozenset(
    {
        "history_market_evidence_conflict",
        "history_evidence_unavailable",
        "history_replay_input_unavailable",
        "history_market_identity_unavailable",
        "history_valuation_evidence_invalid",
        "history_snapshot_series_unavailable",
    }
)


def can_retry_failed_scheduled_capture(job: PortfolioHistoryJobModel) -> bool:
    """Permit one extra worker retry cycle for a failed transient capture."""

    return (
        job.kind is SnapshotSeriesJobKind.capture
        and job.status is BackgroundJobStatus.failed
        and job.error_code in _SCHEDULED_CAPTURE_TRANSIENT_CODES
        and job.max_attempts == _SCHEDULED_CAPTURE_INITIAL_ATTEMPTS
        and job.attempt_count == _SCHEDULED_CAPTURE_INITIAL_ATTEMPTS
    )


@dataclass(frozen=True, slots=True)
class EnqueuedPortfolioHistoryJob:
    job: PortfolioHistoryJobModel
    created: bool


@dataclass(frozen=True, slots=True)
class ClaimedPortfolioHistoryJob:
    job: PortfolioHistoryJobModel
    lease: LeaseIdentity


class PortfolioHistoryJobLeaseLostError(RuntimeError):
    """A stale history worker attempted a fenced mutation."""


class PortfolioHistoryJobReplayMismatchError(RuntimeError):
    """An idempotency key was replayed with a different immutable payload."""


class PortfolioHistoryJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(
        self,
        *,
        user_id: str,
        kind: SnapshotSeriesJobKind,
        idempotency_key: str,
        payload: dict[str, Any],
        checkpoint: dict[str, Any],
        progress: dict[str, Any],
        max_attempts: int,
        now: datetime,
        requested_by_background_job_id: str | None = None,
    ) -> EnqueuedPortfolioHistoryJob:
        values = {
            "id": str(uuid4()),
            "user_id": user_id,
            "requested_by_background_job_id": requested_by_background_job_id,
            "kind": kind,
            "status": BackgroundJobStatus.queued,
            "idempotency_key": idempotency_key,
            "payload": payload,
            "checkpoint": checkpoint,
            "progress": progress,
            "result": None,
            "error_code": None,
            "error_message": None,
            "attempt_count": 0,
            "manual_retry_count": 0,
            "max_attempts": max_attempts,
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
        created = (
            await self.session.scalars(
                insert(PortfolioHistoryJobModel)
                .values(**values)
                .on_conflict_do_nothing(index_elements=("userId", "kind", "idempotencyKey"))
                .returning(PortfolioHistoryJobModel)
            )
        ).one_or_none()
        if created is not None:
            return EnqueuedPortfolioHistoryJob(created, True)
        replay = await self.session.scalar(
            select(PortfolioHistoryJobModel).where(
                PortfolioHistoryJobModel.user_id == user_id,
                PortfolioHistoryJobModel.kind == kind,
                PortfolioHistoryJobModel.idempotency_key == idempotency_key,
            )
        )
        if replay is None:
            raise RuntimeError("The history job idempotency replay is missing.")
        if replay.payload != payload:
            raise PortfolioHistoryJobReplayMismatchError(
                "The history job payload does not match its idempotency replay."
            )
        return EnqueuedPortfolioHistoryJob(replay, False)

    async def claim_next(
        self, *, worker_id: str, now: datetime, lease_duration: timedelta
    ) -> ClaimedPortfolioHistoryJob | None:
        if not worker_id or worker_id != worker_id.strip() or len(worker_id) > 200:
            raise ValueError("The history worker identity is invalid.")
        if now.tzinfo is not None or not timedelta(0) < lease_duration <= timedelta(minutes=30):
            raise ValueError("The history job lease boundary is invalid.")
        await self.session.execute(
            update(PortfolioHistoryJobModel)
            .where(
                PortfolioHistoryJobModel.status == BackgroundJobStatus.running,
                PortfolioHistoryJobModel.lease_expires_at <= now,
                PortfolioHistoryJobModel.attempt_count >= PortfolioHistoryJobModel.max_attempts,
            )
            .values(
                status=BackgroundJobStatus.failed,
                result=None,
                error_code=func.coalesce(
                    PortfolioHistoryJobModel.error_code,
                    SAFE_EXHAUSTED_CODE,
                ),
                error_message=func.coalesce(
                    PortfolioHistoryJobModel.error_message,
                    SAFE_EXHAUSTED_MESSAGE,
                ),
                lease_owner=None,
                lease_expires_at=None,
                lease_heartbeat_at=None,
                finished_at=now,
                updated_at=now,
            )
        )
        candidate = PortfolioHistoryJobModel
        other = PortfolioHistoryJobModel.__table__.alias("other_running_history_job")
        other_running = exists(
            select(1)
            .select_from(other)
            .where(
                other.c.userId == candidate.user_id,
                other.c.status == BackgroundJobStatus.running,
                other.c.id != candidate.id,
            )
        )
        ready = (
            select(candidate)
            .where(
                candidate.attempt_count < candidate.max_attempts,
                or_(
                    (candidate.status == BackgroundJobStatus.running)
                    & (candidate.lease_expires_at <= now),
                    (
                        candidate.status.in_(
                            (BackgroundJobStatus.queued, BackgroundJobStatus.retry_wait)
                        )
                    )
                    & (candidate.run_after <= now)
                    & ~other_running,
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
        # Claim contenders serialise on one user lock. Re-check after acquiring
        # it because another transaction can have selected another queued job
        # for the same user before either one became running.
        lock_scope = f"portfolio-history-user:{job.user_id}"
        lock_id = int.from_bytes(sha256(lock_scope.encode()).digest()[:8], "big", signed=True)
        await self.session.execute(select(func.pg_advisory_xact_lock(lock_id)))
        conflicting = await self.session.scalar(
            select(PortfolioHistoryJobModel.id).where(
                PortfolioHistoryJobModel.user_id == job.user_id,
                PortfolioHistoryJobModel.status == BackgroundJobStatus.running,
                PortfolioHistoryJobModel.id != job.id,
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
        return ClaimedPortfolioHistoryJob(job, LeaseIdentity(job.id, worker_id, job.lease_version))

    async def heartbeat(
        self, *, lease: LeaseIdentity, now: datetime, lease_duration: timedelta
    ) -> None:
        if now.tzinfo is not None or not timedelta(0) < lease_duration <= timedelta(minutes=30):
            raise ValueError("The history job heartbeat boundary is invalid.")
        await self._fenced_update(
            lease,
            {
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
            raise ValueError("The history job checkpoint timestamp is invalid.")
        canonical_checkpoint = PortfolioHistoryJobCheckpoint.model_validate(checkpoint)
        canonical_progress = PortfolioHistoryJobProgress.model_validate(progress)
        await self._fenced_update(
            lease,
            {
                "checkpoint": canonical_checkpoint.model_dump(mode="json"),
                "progress": canonical_progress.model_dump(mode="json"),
                "updated_at": now,
            },
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
            raise ValueError("The history job completion timestamp is invalid.")
        canonical_result = PortfolioHistoryJobResult.model_validate(result)
        canonical_progress = PortfolioHistoryJobProgress.model_validate(progress)
        if canonical_progress.phase != "completed":
            raise ValueError("The completed history job progress is invalid.")
        await self._fenced_update(
            lease,
            {
                "status": BackgroundJobStatus.completed,
                "result": canonical_result.model_dump(mode="json", exclude_none=True),
                "progress": canonical_progress.model_dump(mode="json"),
                "error_code": None,
                "error_message": None,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_heartbeat_at": None,
                "finished_at": now,
                "updated_at": now,
            },
        )

    async def fail(
        self, *, lease: LeaseIdentity, error_code: str, error_message: str, now: datetime
    ) -> None:
        error = PortfolioHistoryJobError(code=error_code, message=error_message)
        if now.tzinfo is not None:
            raise ValueError("The history job failure timestamp is invalid.")
        await self._fenced_update(
            lease,
            {
                "status": BackgroundJobStatus.failed,
                "result": None,
                "error_code": error.code,
                "error_message": error.message,
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
        error = PortfolioHistoryJobError(code=error_code, message=error_message)
        if now.tzinfo is not None or run_after.tzinfo is not None or run_after <= now:
            raise ValueError("The history job retry timestamp is invalid.")
        await self._fenced_update(
            lease,
            {
                "status": BackgroundJobStatus.retry_wait,
                "run_after": run_after,
                "error_code": error.code,
                "error_message": error.message,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_heartbeat_at": None,
                "updated_at": now,
            },
        )

    async def release(self, *, lease: LeaseIdentity, now: datetime) -> None:
        if now.tzinfo is not None:
            raise ValueError("The history job release timestamp is invalid.")
        await self._fenced_update(
            lease,
            {
                "status": BackgroundJobStatus.queued,
                "run_after": now,
                "attempt_count": PortfolioHistoryJobModel.attempt_count - 1,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_heartbeat_at": None,
                "updated_at": now,
            },
        )

    async def retry_failed(
        self, *, actor_user_id: str, job_id: str, now: datetime
    ) -> PortfolioHistoryJobModel | None:
        if now.tzinfo is not None:
            raise ValueError("The history job manual retry timestamp is invalid.")
        job = await self.session.scalar(
            select(PortfolioHistoryJobModel)
            .where(
                PortfolioHistoryJobModel.id == job_id,
                PortfolioHistoryJobModel.user_id == actor_user_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            job is None
            or job.status is not BackgroundJobStatus.failed
            or job.error_code == SAFE_SCOPE_RETIRED_CODE
            or job.manual_retry_count >= MAX_MANUAL_RETRIES
        ):
            return None
        job.status = BackgroundJobStatus.queued
        job.attempt_count = 0
        job.manual_retry_count += 1
        job.run_after = now
        job.result = None
        job.error_code = None
        job.error_message = None
        job.lease_owner = job.lease_expires_at = job.lease_heartbeat_at = None
        # A retry resumes the checkpointed immutable generation.  Preserve its
        # original start timestamp so deterministic snapshot IDs and metadata
        # remain byte-for-byte idempotent across attempts.
        job.finished_at = None
        job.updated_at = now
        await self.session.flush()
        return job

    async def retry_failed_scheduled_capture(
        self, *, actor_user_id: str, job_id: str, now: datetime
    ) -> PortfolioHistoryJobModel | None:
        """Release one failed scheduler-owned capture without consuming manual retries."""

        if now.tzinfo is not None:
            raise ValueError("The history job scheduled retry timestamp is invalid.")
        job = await self.session.scalar(
            select(PortfolioHistoryJobModel)
            .where(
                PortfolioHistoryJobModel.id == job_id,
                PortfolioHistoryJobModel.user_id == actor_user_id,
                PortfolioHistoryJobModel.kind == SnapshotSeriesJobKind.capture,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None or not can_retry_failed_scheduled_capture(job):
            return None
        job.status = BackgroundJobStatus.queued
        job.max_attempts = MAX_SCHEDULED_CAPTURE_ATTEMPTS
        job.run_after = now
        # Keep the deterministic generation fence. A capture may have published
        # before its worker crashed, and retry must resume finalization against
        # that exact snapshot generation and causal timestamp.
        PortfolioHistoryJobCheckpoint.model_validate(job.checkpoint)
        job.result = None
        job.error_code = None
        job.error_message = None
        job.lease_owner = job.lease_expires_at = job.lease_heartbeat_at = None
        # Scheduled capture retries resume the same checkpointed generation.
        job.finished_at = None
        job.updated_at = now
        await self.session.flush()
        return job

    async def _fenced_update(self, lease: LeaseIdentity, values: dict[str, Any]) -> None:
        result = await self.session.execute(
            update(PortfolioHistoryJobModel)
            .where(
                PortfolioHistoryJobModel.id == lease.job_id,
                PortfolioHistoryJobModel.status == BackgroundJobStatus.running,
                PortfolioHistoryJobModel.lease_owner == lease.owner,
                PortfolioHistoryJobModel.lease_version == lease.version,
            )
            .values(**values)
        )
        if getattr(result, "rowcount", None) != 1:
            raise PortfolioHistoryJobLeaseLostError("The history job lease is no longer owned.")
