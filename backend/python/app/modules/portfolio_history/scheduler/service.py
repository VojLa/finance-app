"""Deterministic 30-minute capture and daily maintenance scheduler."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import BackgroundJobStatus, SnapshotSeriesJobKind
from app.modules.portfolio_history.jobs.models import HistoryCapturePayload
from app.modules.portfolio_history.jobs.repository import can_retry_failed_scheduled_capture
from app.modules.portfolio_history.jobs.service import PortfolioHistoryJobService
from app.modules.portfolio_history.lattice import (
    PRAGUE_TIMEZONE,
    HistoryResolution,
    history_bucket,
)
from app.modules.portfolio_history.scheduler.models import (
    PortfolioHistoryScheduleAction,
    PortfolioHistoryScheduleDecision,
    PortfolioHistorySchedulerTickResult,
)
from app.modules.portfolio_history.scheduler.repository import (
    LockedSchedule,
    PortfolioHistorySchedulerRepository,
)

DEFAULT_HISTORY_JOB_MAX_ATTEMPTS = 5
MAX_SCHEDULES_PER_TICK = 100
_MILLISECOND = timedelta(milliseconds=1)
_FAILED_CAPTURE_RETRY_DELAY = timedelta(minutes=30)


class PortfolioHistorySchedulerStateError(RuntimeError):
    """The caller did not provide a clean scheduler transaction boundary."""


def _timestamp(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is not None or value.microsecond % 1_000 != 0:
        raise PortfolioHistorySchedulerStateError("Scheduler time must be naive UTC milliseconds.")
    return value


def _daily_slot(value: datetime) -> datetime:
    local_date = value.replace(tzinfo=UTC).astimezone(PRAGUE_TIMEZONE).date()
    return (
        datetime.combine(local_date, time.min, tzinfo=PRAGUE_TIMEZONE)
        .astimezone(UTC)
        .replace(tzinfo=None)
    )


def _next_capture_at(capture_at: datetime) -> datetime:
    # A cursor is a bucket close, so the containing bucket immediately after
    # that boundary determines the next close. This remains exact on both DST
    # transition days (46/50 Prague half-hour slots).
    previous = history_bucket(capture_at - _MILLISECOND, HistoryResolution.minutes_30)
    if previous.end != capture_at:
        raise PortfolioHistorySchedulerStateError("Capture cursor is not a Prague bucket close.")
    return history_bucket(capture_at, HistoryResolution.minutes_30).end


class PortfolioHistorySchedulerService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: PortfolioHistorySchedulerRepository | None = None,
        jobs: PortfolioHistoryJobService | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or PortfolioHistorySchedulerRepository(session)
        self.jobs = jobs or PortfolioHistoryJobService(session)

    async def tick(
        self, *, now: datetime, limit: int = MAX_SCHEDULES_PER_TICK
    ) -> PortfolioHistorySchedulerTickResult:
        canonical_now = _timestamp(now)
        if type(limit) is not int or isinstance(limit, bool) or not 1 <= limit <= 1_000:
            raise PortfolioHistorySchedulerStateError("Scheduler batch limit is invalid.")
        if self.session.in_transaction():
            raise PortfolioHistorySchedulerStateError(
                "Scheduler requires a fresh transaction for SERIALIZABLE isolation."
            )
        async with self.session.begin():
            await self.repository.set_serializable()
            if not await self.repository.try_lock_scheduler():
                return PortfolioHistorySchedulerTickResult(False, ())
            daily_slot = _daily_slot(canonical_now)
            states = await self.repository.lock_due_schedules(
                now=canonical_now, daily_slot=daily_slot, limit=limit
            )
            decisions = tuple(
                [
                    await self._process_locked(
                        await self.repository.inspect_locked(state, now=canonical_now),
                        now=canonical_now,
                        daily_slot=daily_slot,
                    )
                    for state in states
                ]
            )
        return PortfolioHistorySchedulerTickResult(True, decisions)

    async def _process_locked(
        self, locked: LockedSchedule, *, now: datetime, daily_slot: datetime
    ) -> PortfolioHistoryScheduleDecision:
        state = locked.state
        due_capture = state.next_capture_at <= now
        try:
            next_capture = _next_capture_at(state.next_capture_at)
        except (OverflowError, PortfolioHistorySchedulerStateError, ValueError):
            return PortfolioHistoryScheduleDecision(
                state.user_id, PortfolioHistoryScheduleAction.invalid_schedule
            )
        if locked.has_building_generation:
            return PortfolioHistoryScheduleDecision(
                state.user_id, PortfolioHistoryScheduleAction.deferred_building
            )
        if locked.has_active_job:
            return PortfolioHistoryScheduleDecision(
                state.user_id, PortfolioHistoryScheduleAction.deferred_active_job
            )
        if not locked.has_publication:
            if locked.dirty is None:
                return PortfolioHistoryScheduleDecision(
                    state.user_id, PortfolioHistoryScheduleAction.rebuild_boundary_required
                )
            enqueued = await self.jobs.enqueue(
                actor_user_id=state.user_id,
                kind=SnapshotSeriesJobKind.rebuild,
                payload={
                    "dirty_epoch": locked.dirty.dirty_epoch,
                    "dirty_from": locked.dirty.dirty_from,
                },
                max_attempts=DEFAULT_HISTORY_JOB_MAX_ATTEMPTS,
                now=now,
            )
            if enqueued.job.status is BackgroundJobStatus.failed:
                return PortfolioHistoryScheduleDecision(
                    state.user_id, PortfolioHistoryScheduleAction.deferred_failed_job
                )
            return PortfolioHistoryScheduleDecision(
                state.user_id, PortfolioHistoryScheduleAction.rebuild_enqueued
            )
        if locked.dirty is not None:
            return PortfolioHistoryScheduleDecision(
                state.user_id, PortfolioHistoryScheduleAction.deferred_dirty
            )

        if due_capture:
            capture_at = state.next_capture_at
            failed_capture = next(
                (
                    job
                    for job in locked.failed_capture_jobs
                    if _failed_capture_at(job) == capture_at
                ),
                None,
            )
            if failed_capture is not None:
                if (
                    not can_retry_failed_scheduled_capture(failed_capture)
                    or failed_capture.finished_at is None
                    or now < failed_capture.finished_at + _FAILED_CAPTURE_RETRY_DELAY
                ):
                    return PortfolioHistoryScheduleDecision(
                        state.user_id,
                        PortfolioHistoryScheduleAction.deferred_failed_job,
                        capture_at=capture_at,
                    )
                await self.jobs.retry_failed_scheduled_capture(
                    actor_user_id=state.user_id,
                    job_id=failed_capture.id,
                    now=now,
                )
                return PortfolioHistoryScheduleDecision(
                    state.user_id,
                    PortfolioHistoryScheduleAction.capture_retry_enqueued,
                    capture_at=capture_at,
                )
            enqueued = await self.jobs.enqueue(
                actor_user_id=state.user_id,
                kind=SnapshotSeriesJobKind.capture,
                payload={"capture_at": capture_at},
                max_attempts=DEFAULT_HISTORY_JOB_MAX_ATTEMPTS,
                now=now,
            )
            if enqueued.job.status is BackgroundJobStatus.failed:
                return PortfolioHistoryScheduleDecision(
                    state.user_id,
                    PortfolioHistoryScheduleAction.deferred_failed_job,
                    capture_at=capture_at,
                )
            if enqueued.job.status is BackgroundJobStatus.completed:
                await self.repository.advance_capture(
                    state=state, captured_at=capture_at, next_at=next_capture, now=now
                )
                return PortfolioHistoryScheduleDecision(
                    state.user_id,
                    PortfolioHistoryScheduleAction.capture_completed,
                    capture_at=capture_at,
                )
            return PortfolioHistoryScheduleDecision(
                state.user_id,
                PortfolioHistoryScheduleAction.capture_enqueued,
                capture_at=capture_at,
            )

        return PortfolioHistoryScheduleDecision(
            state.user_id, PortfolioHistoryScheduleAction.invalid_schedule
        )


def _failed_capture_at(job: Any) -> datetime | None:
    try:
        return HistoryCapturePayload.model_validate(job.payload).capture_at
    except (AttributeError, TypeError, ValueError):
        return None


__all__ = [
    "DEFAULT_HISTORY_JOB_MAX_ATTEMPTS",
    "MAX_SCHEDULES_PER_TICK",
    "PortfolioHistorySchedulerService",
    "PortfolioHistorySchedulerStateError",
]
