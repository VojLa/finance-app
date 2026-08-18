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

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.background_jobs import BackgroundJobModel
from app.db.models.canonical_lineage import (
    AccountCanonicalStateModel,
    DailySnapshotBaselineAccountModel,
    DailySnapshotBaselineModel,
)
from app.db.models.enums import (
    BackgroundJobKind,
    BackgroundJobStatus,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.publication_targets import ImportJobPublicationTargetModel
from app.modules.jobs.lifecycle import MAX_MANUAL_RETRIES, LeaseIdentity


@dataclass(frozen=True, slots=True)
class EnqueuedBackgroundJob:
    job: BackgroundJobModel
    created: bool


@dataclass(frozen=True, slots=True)
class ClaimedBackgroundJob:
    job: BackgroundJobModel
    lease: LeaseIdentity


@dataclass(frozen=True, slots=True)
class ManualRetryBackgroundJob:
    job: BackgroundJobModel
    retried: bool


class BackgroundJobLeaseLostError(RuntimeError):
    """A stale worker attempted to mutate a lease it no longer owns."""


class BackgroundJobPublicationStaleError(RuntimeError):
    """Anchors no longer prove a publishable canonical state; retry safely."""


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

    async def find_owned_import_jobs_for_batch(
        self,
        *,
        user_id: str,
        account_id: str,
        batch_id: str,
    ) -> list[BackgroundJobModel]:
        """Return at most two scoped workflows containing one exact batch ID.

        The JSONB containment predicate deliberately targets the `batch_ids`
        array rather than text-searching an opaque payload.  Two rows are
        enough to distinguish the only valid cardinality (zero or one) from a
        corrupt duplicate state without loading an unbounded result.
        """

        # Registration already holds the account writer lock and exact batch
        # lock.  Do not lock BackgroundJob here: completion owns the inverse
        # Job -> publication targets -> Account order, and this is a
        # read-only recovery decision where a concurrent status transition may
        # safely resolve to either a safe resume or a safe conflict.
        result = await self.session.scalars(
            select(BackgroundJobModel)
            .where(
                BackgroundJobModel.user_id == user_id,
                BackgroundJobModel.account_id == account_id,
                BackgroundJobModel.kind == BackgroundJobKind.import_workflow,
                BackgroundJobModel.payload["batch_ids"].contains([batch_id]),
            )
            .order_by(BackgroundJobModel.created_at, BackgroundJobModel.id)
            .limit(2)
        )
        return list(result.all())

    async def retry_failed(
        self,
        *,
        user_id: str,
        account_id: str,
        job_id: str,
        now: datetime,
    ) -> ManualRetryBackgroundJob | None:
        job = await self.get_owned(
            user_id=user_id, account_id=account_id, job_id=job_id, for_update=True
        )
        if job is None:
            return None
        if (
            job.status is not BackgroundJobStatus.failed
            or job.manual_retry_count >= MAX_MANUAL_RETRIES
        ):
            return ManualRetryBackgroundJob(job=job, retried=False)
        job.status = BackgroundJobStatus.queued
        job.attempt_count = 0
        job.manual_retry_count += 1
        job.run_after = now
        job.result = None
        job.error_code = None
        job.error_message = None
        job.lease_owner = None
        job.lease_expires_at = None
        job.lease_heartbeat_at = None
        job.started_at = None
        job.finished_at = None
        job.updated_at = now
        await self.session.flush()
        return ManualRetryBackgroundJob(job=job, retried=True)

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
        job = await self.session.scalar(
            select(BackgroundJobModel)
            .where(BackgroundJobModel.id == lease.job_id)
            .with_for_update()
        )
        if job is None:
            raise BackgroundJobLeaseLostError("The background job is no longer owned.")
        targets = tuple(
            (
                await self.session.scalars(
                    select(ImportJobPublicationTargetModel)
                    .where(ImportJobPublicationTargetModel.job_id == lease.job_id)
                    .with_for_update()
                )
            ).all()
        )
        # Every BackgroundJob is an import workflow.  A terminal transition is
        # therefore also the publication boundary: without durable targets, it
        # would release the current-value fence without an immutable baseline.
        if not targets:
            raise BackgroundJobLeaseLostError("The import publication targets are missing.")
        account = await self.session.scalar(
            select(AccountModel).where(AccountModel.id == job.account_id).with_for_update()
        )
        if account is None:
            raise BackgroundJobLeaseLostError("The import publication account was removed.")
        current_members = set(
            (
                await self.session.scalars(
                    select(AccountMemberModel.user_id).where(
                        AccountMemberModel.account_id == job.account_id
                    )
                )
            ).all()
        )
        anchor_pairs = set(
            (
                await self.session.execute(
                    select(
                        DailySnapshotBaselineModel.user_id,
                        DailySnapshotBaselineModel.timestamp,
                    ).where(
                        DailySnapshotBaselineModel.background_job_id == lease.job_id,
                        DailySnapshotBaselineModel.granularity == SnapshotGranularity.minute,
                        DailySnapshotBaselineModel.source == SnapshotSource.import_event,
                    )
                )
            ).all()
        )
        expected_anchors = {(target.user_id, target.bucket) for target in targets}
        if (
            {target.user_id for target in targets} != current_members
            or any(target.published_at is not None for target in targets)
            or anchor_pairs != expected_anchors
        ):
            raise BackgroundJobLeaseLostError("The import publication membership changed.")
        canonical_state = await self.session.scalar(
            select(AccountCanonicalStateModel)
            .where(AccountCanonicalStateModel.account_id == job.account_id)
            .with_for_update()
        )
        anchor_revisions = set(
            (
                await self.session.execute(
                    select(
                        DailySnapshotBaselineModel.user_id,
                        DailySnapshotBaselineAccountModel.canonical_revision,
                    )
                    .join(
                        DailySnapshotBaselineAccountModel,
                        DailySnapshotBaselineAccountModel.baseline_id
                        == DailySnapshotBaselineModel.id,
                    )
                    .where(
                        DailySnapshotBaselineModel.background_job_id == lease.job_id,
                        DailySnapshotBaselineAccountModel.account_id == job.account_id,
                    )
                )
            ).all()
        )
        if canonical_state is None or anchor_revisions != {
            (target.user_id, canonical_state.last_revision) for target in targets
        }:
            raise BackgroundJobPublicationStaleError(
                "The import publication canonical state changed."
            )
        for target in targets:
            target.published_at = now
        await self.session.flush()
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
        run_after: datetime | None = None,
    ) -> None:
        effective_run_after = run_after or now
        if (
            now.tzinfo is not None
            or effective_run_after.tzinfo is not None
            or effective_run_after < now
        ):
            raise ValueError("The release timestamp is invalid.")
        await self._fenced_update(
            lease,
            values={
                "status": BackgroundJobStatus.queued,
                "run_after": effective_run_after,
                "attempt_count": BackgroundJobModel.attempt_count - 1,
                "lease_owner": None,
                "lease_expires_at": None,
                "lease_heartbeat_at": None,
                "updated_at": now,
            },
        )

    async def defer(
        self,
        *,
        lease: LeaseIdentity,
        run_after: datetime,
        now: datetime,
    ) -> None:
        if now.tzinfo is not None or run_after.tzinfo is not None or run_after <= now:
            raise ValueError("The deferred publication timestamp is invalid.")
        await self._fenced_update(
            lease,
            values={
                "status": BackgroundJobStatus.retry_wait,
                "run_after": run_after,
                "attempt_count": BackgroundJobModel.attempt_count - 1,
                "error_code": None,
                "error_message": None,
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
