"""Short PostgreSQL transaction boundary for portfolio-history scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.canonical_lineage import (
    SnapshotGenerationModel,
    SnapshotGenerationTargetModel,
    UserReadModelPublicationModel,
)
from app.db.models.enums import BackgroundJobStatus, SnapshotSeriesJobKind
from app.db.models.snapshot_series_jobs import (
    SnapshotSeriesDirtyStateModel as PortfolioHistoryDirtyStateModel,
)
from app.db.models.snapshot_series_jobs import (
    SnapshotSeriesRebuildJobModel as PortfolioHistoryJobModel,
)
from app.db.models.snapshot_series_jobs import (
    SnapshotSeriesScheduleStateModel as PortfolioHistoryScheduleStateModel,
)
from app.db.models.snapshot_series_publication import SnapshotSeriesPublicationReceiptModel
from app.db.models.users import UserModel

_ACTIVE_JOB_STATUSES = (
    BackgroundJobStatus.queued,
    BackgroundJobStatus.running,
    BackgroundJobStatus.retry_wait,
)


def scheduler_lock_id() -> int:
    digest = sha256(b"portfolio-history-scheduler\0v1").digest()
    return int.from_bytes(digest[:8], "big", signed=True)


@dataclass(frozen=True, slots=True)
class LockedSchedule:
    state: PortfolioHistoryScheduleStateModel
    dirty: PortfolioHistoryDirtyStateModel | None
    has_publication: bool
    has_building_generation: bool
    has_active_job: bool
    failed_capture_jobs: tuple[PortfolioHistoryJobModel, ...] = ()


class PortfolioHistorySchedulerRepository:
    """Every method is called inside one service-owned SERIALIZABLE transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_serializable(self) -> None:
        await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))

    async def try_lock_scheduler(self) -> bool:
        return bool(
            await self.session.scalar(select(func.pg_try_advisory_xact_lock(scheduler_lock_id())))
        )

    async def lock_due_schedules(
        self, *, now: datetime, daily_slot: datetime, limit: int
    ) -> tuple[PortfolioHistoryScheduleStateModel, ...]:
        job = PortfolioHistoryJobModel.__table__.alias("active_scheduler_job")
        active_job = exists(
            select(1)
            .select_from(job)
            .where(
                job.c.userId == PortfolioHistoryScheduleStateModel.user_id,
                job.c.status.in_(_ACTIVE_JOB_STATUSES),
            )
        )
        rows = await self.session.scalars(
            select(PortfolioHistoryScheduleStateModel)
            .join(UserModel, UserModel.id == PortfolioHistoryScheduleStateModel.user_id)
            .where(
                PortfolioHistoryScheduleStateModel.enabled.is_(True),
                PortfolioHistoryScheduleStateModel.next_capture_at <= now,
            )
            .order_by(
                active_job,
                PortfolioHistoryScheduleStateModel.next_capture_at,
                PortfolioHistoryScheduleStateModel.user_id,
            )
            .with_for_update(of=(PortfolioHistoryScheduleStateModel, UserModel), skip_locked=True)
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        return tuple(rows)

    async def inspect_locked(
        self, state: PortfolioHistoryScheduleStateModel, *, now: datetime | None = None
    ) -> LockedSchedule:
        user_id = state.user_id
        dirty = await self.session.get(PortfolioHistoryDirtyStateModel, user_id)
        pending = tuple(
            (
                await self.session.scalars(
                    select(PortfolioHistoryJobModel)
                    .where(
                        PortfolioHistoryJobModel.user_id == user_id,
                        PortfolioHistoryJobModel.status.in_(_ACTIVE_JOB_STATUSES),
                    )
                    .with_for_update()
                )
            ).all()
        )
        effective_now = now or datetime.now(UTC).replace(tzinfo=None)
        for job in pending:
            if job.kind is not SnapshotSeriesJobKind.rebuild:
                continue
            if job.status is BackgroundJobStatus.running and (
                job.lease_expires_at is None or job.lease_expires_at > effective_now
            ):
                continue
            receipt = await self.session.scalar(
                select(SnapshotSeriesPublicationReceiptModel.id).where(
                    SnapshotSeriesPublicationReceiptModel.user_id == user_id,
                    SnapshotSeriesPublicationReceiptModel.job_id == job.id,
                )
            )
            if receipt is not None:
                continue
            if dirty is not None and job.payload.get("dirty_epoch") == dirty.dirty_epoch:
                continue
            job.status = BackgroundJobStatus.failed
            job.result = None
            job.error_code = "history_job_dirty_epoch_superseded"
            job.error_message = "A newer history rebuild request replaced this job."
            job.lease_owner = None
            job.lease_expires_at = None
            job.lease_heartbeat_at = None
            job.finished_at = effective_now
            job.updated_at = effective_now
        await self.session.flush()
        has_publication = (
            await self.session.scalar(
                select(UserReadModelPublicationModel.user_id).where(
                    UserReadModelPublicationModel.user_id == user_id
                )
            )
            is not None
        )
        has_building = (
            await self.session.scalar(
                select(SnapshotGenerationModel.id)
                .join(
                    SnapshotGenerationTargetModel,
                    SnapshotGenerationTargetModel.generation_id == SnapshotGenerationModel.id,
                )
                .join(
                    PortfolioHistoryJobModel,
                    (PortfolioHistoryJobModel.id == SnapshotGenerationTargetModel.staged_by_job_id)
                    & (PortfolioHistoryJobModel.user_id == SnapshotGenerationTargetModel.user_id),
                )
                .where(
                    SnapshotGenerationTargetModel.user_id == user_id,
                    SnapshotGenerationModel.state == "staged",
                    PortfolioHistoryJobModel.status == BackgroundJobStatus.running,
                    PortfolioHistoryJobModel.lease_version
                    == SnapshotGenerationTargetModel.staged_lease_version,
                    PortfolioHistoryJobModel.lease_owner
                    == SnapshotGenerationTargetModel.staged_lease_owner,
                    PortfolioHistoryJobModel.lease_expires_at > effective_now,
                )
            )
            is not None
        )
        has_active_job = (
            await self.session.scalar(
                select(PortfolioHistoryJobModel.id).where(
                    PortfolioHistoryJobModel.user_id == user_id,
                    (
                        PortfolioHistoryJobModel.status.in_(
                            (BackgroundJobStatus.queued, BackgroundJobStatus.retry_wait)
                        )
                        | (
                            (PortfolioHistoryJobModel.status == BackgroundJobStatus.running)
                            & (PortfolioHistoryJobModel.lease_expires_at > effective_now)
                        )
                    ),
                )
            )
            is not None
        )
        failed_capture_jobs = tuple(
            await self.session.scalars(
                select(PortfolioHistoryJobModel)
                .where(
                    PortfolioHistoryJobModel.user_id == user_id,
                    PortfolioHistoryJobModel.kind == SnapshotSeriesJobKind.capture,
                    PortfolioHistoryJobModel.status == BackgroundJobStatus.failed,
                )
                .order_by(PortfolioHistoryJobModel.finished_at.desc(), PortfolioHistoryJobModel.id)
                .with_for_update()
            )
        )
        return LockedSchedule(
            state=state,
            dirty=dirty,
            has_publication=has_publication,
            has_building_generation=has_building,
            has_active_job=has_active_job,
            failed_capture_jobs=failed_capture_jobs,
        )

    async def advance_capture(
        self,
        *,
        state: PortfolioHistoryScheduleStateModel,
        captured_at: datetime,
        next_at: datetime,
        now: datetime,
    ) -> None:
        state.last_captured_bucket = captured_at
        state.next_capture_at = next_at
        state.updated_at = now
        await self.session.flush()


__all__ = [
    "LockedSchedule",
    "PortfolioHistorySchedulerRepository",
    "scheduler_lock_id",
]
