from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models.enums import BackgroundJobStatus, SnapshotSeriesJobKind
from app.modules.portfolio_history.builder.executor import _covered_through
from app.modules.portfolio_history.jobs.repository import (
    MAX_SCHEDULED_CAPTURE_ATTEMPTS,
    PortfolioHistoryJobRepository,
)
from app.modules.portfolio_history.jobs.worker import _now as history_worker_now
from app.modules.portfolio_history.scheduler.models import (
    PortfolioHistoryScheduleAction,
    PortfolioHistorySchedulerTickResult,
)
from app.modules.portfolio_history.scheduler.runner import PortfolioHistorySchedulerRunner
from app.modules.portfolio_history.scheduler.service import PortfolioHistorySchedulerService

NOW = datetime(2026, 8, 25, 12, 0)
RESULT = PortfolioHistorySchedulerTickResult(True, ())


def test_history_worker_clock_is_utc_naive_and_millisecond_bounded() -> None:
    value = history_worker_now()

    assert value.tzinfo is None
    assert value.microsecond % 1_000 == 0


def test_rebuild_coverage_never_extends_to_future_capture_bucket_end() -> None:
    created_at = datetime(2026, 9, 4, 21, 37, 52, 579000)

    assert _covered_through(created_at) == datetime(2026, 9, 4, 21, 37)


class _SessionContext:
    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Sessions:
    def __init__(self) -> None:
        self.created: list[object] = []

    def __call__(self) -> _SessionContext:
        session = object()
        self.created.append(session)
        return _SessionContext(session)


class _Scheduler:
    def __init__(self, tick: object) -> None:
        self._tick = tick

    async def tick(self, *, now: datetime, limit: int) -> PortfolioHistorySchedulerTickResult:
        return await cast(Any, self._tick)(now=now, limit=limit)


def _runner(
    sessions: _Sessions,
    tick: object,
    *,
    poll_interval: float = 0.1,
) -> PortfolioHistorySchedulerRunner:
    return PortfolioHistorySchedulerRunner(
        cast(async_sessionmaker[AsyncSession], sessions),
        poll_interval=poll_interval,
        clock=lambda: NOW,
        scheduler_factory=cast(
            Any,
            lambda _session: cast(PortfolioHistorySchedulerService, _Scheduler(tick)),
        ),
    )


@pytest.mark.asyncio
async def test_scheduler_runner_ticks_immediately_and_uses_fresh_sessions() -> None:
    sessions = _Sessions()
    calls: list[tuple[datetime, int]] = []

    async def tick(*, now: datetime, limit: int) -> PortfolioHistorySchedulerTickResult:
        calls.append((now, limit))
        return RESULT

    runner = _runner(sessions, tick)

    assert await runner.run_once() == RESULT
    assert await runner.run_once() == RESULT
    assert calls == [(NOW, 100), (NOW, 100)]
    assert len(sessions.created) == 2
    assert sessions.created[0] is not sessions.created[1]


@pytest.mark.asyncio
async def test_scheduler_runner_retries_serialization_failure_in_a_fresh_session() -> None:
    sessions = _Sessions()
    calls = 0

    async def tick(*, now: datetime, limit: int) -> PortfolioHistorySchedulerTickResult:
        del now, limit
        nonlocal calls
        calls += 1
        if calls == 1:
            original = RuntimeError("serialization conflict")
            original.sqlstate = "40001"  # type: ignore[attr-defined]
            raise DBAPIError(None, None, original, False)
        return RESULT

    assert await _runner(sessions, tick).run_once() == RESULT
    assert calls == 2
    assert len(sessions.created) == 2


@pytest.mark.asyncio
async def test_scheduler_runner_retries_after_iteration_exception() -> None:
    sessions = _Sessions()
    calls = 0
    completed = asyncio.Event()
    runner: PortfolioHistorySchedulerRunner

    async def tick(*, now: datetime, limit: int) -> PortfolioHistorySchedulerTickResult:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient scheduler failure")
        runner.stop()
        completed.set()
        return RESULT

    runner = _runner(sessions, tick)
    task = asyncio.create_task(runner.run())

    await asyncio.wait_for(completed.wait(), timeout=0.5)
    await asyncio.wait_for(task, timeout=0.5)

    assert calls == 2
    assert len(sessions.created) == 2


@pytest.mark.asyncio
async def test_scheduler_runner_propagates_cancellation() -> None:
    sessions = _Sessions()
    entered = asyncio.Event()

    async def tick(*, now: datetime, limit: int) -> PortfolioHistorySchedulerTickResult:
        entered.set()
        await asyncio.Event().wait()
        return RESULT

    task = asyncio.create_task(_runner(sessions, tick).run())
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_scheduler_runner_idle_stop_releases_poll_wait() -> None:
    sessions = _Sessions()
    ticked = asyncio.Event()

    async def tick(*, now: datetime, limit: int) -> PortfolioHistorySchedulerTickResult:
        ticked.set()
        return RESULT

    runner = _runner(sessions, tick, poll_interval=1)
    task = asyncio.create_task(runner.run())
    await ticked.wait()

    runner.stop()
    await asyncio.wait_for(task, timeout=0.2)

    assert len(sessions.created) == 1


@pytest.mark.asyncio
async def test_scheduled_capture_retry_is_one_bounded_cycle_and_keeps_manual_budget() -> None:
    capture_at = NOW - timedelta(minutes=30)
    job = SimpleNamespace(
        id="capture-job",
        user_id="user-1",
        kind=SnapshotSeriesJobKind.capture,
        status=BackgroundJobStatus.failed,
        payload={"capture_at": capture_at},
        checkpoint={},
        error_code="history_evidence_unavailable",
        attempt_count=5,
        max_attempts=5,
        manual_retry_count=0,
        finished_at=NOW - timedelta(hours=1),
    )
    session = SimpleNamespace(scalar=AsyncMock(return_value=job), flush=AsyncMock())
    repository = PortfolioHistoryJobRepository(cast(AsyncSession, session))

    retried = await repository.retry_failed_scheduled_capture(
        actor_user_id="user-1", job_id=job.id, now=NOW
    )

    assert retried is not None
    assert job.status is BackgroundJobStatus.queued
    assert job.attempt_count == 5
    assert job.max_attempts == MAX_SCHEDULED_CAPTURE_ATTEMPTS == 10
    assert job.manual_retry_count == 0
    job.status = BackgroundJobStatus.failed
    job.attempt_count = 10
    job.finished_at = NOW
    assert (
        await repository.retry_failed_scheduled_capture(
            actor_user_id="user-1", job_id=job.id, now=NOW + timedelta(hours=1)
        )
        is None
    )
    assert job.attempt_count == 10
    assert job.manual_retry_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_code",
    [
        "history_source_lookback_unavailable",
        "history_capture_superseded",
        "history_job_attempts_exhausted",
    ],
)
async def test_scheduler_never_requeues_permanent_or_exhausted_capture(
    error_code: str,
) -> None:
    capture_at = NOW - timedelta(minutes=30)
    job = SimpleNamespace(
        id="capture-job",
        user_id="user-1",
        kind=SnapshotSeriesJobKind.capture,
        status=BackgroundJobStatus.failed,
        payload={"capture_at": capture_at},
        error_code=error_code,
        attempt_count=5,
        max_attempts=5,
        finished_at=NOW - timedelta(hours=1),
    )
    jobs = SimpleNamespace(retry_failed_scheduled_capture=AsyncMock())
    service = PortfolioHistorySchedulerService(cast(AsyncSession, object()), jobs=cast(Any, jobs))
    locked = SimpleNamespace(
        state=SimpleNamespace(user_id="user-1", next_capture_at=capture_at),
        has_building_generation=False,
        has_active_job=False,
        has_publication=True,
        dirty=None,
        failed_capture_jobs=(job,),
    )

    decisions = [
        await service._process_locked(
            cast(Any, locked), now=NOW + timedelta(hours=tick), daily_slot=NOW
        )
        for tick in range(3)
    ]

    assert all(
        decision.action is PortfolioHistoryScheduleAction.deferred_failed_job
        for decision in decisions
    )
    jobs.retry_failed_scheduled_capture.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduler_requeues_transient_capture_once_then_defers_exhaustion() -> None:
    capture_at = NOW - timedelta(minutes=30)
    job = SimpleNamespace(
        id="capture-job",
        user_id="user-1",
        kind=SnapshotSeriesJobKind.capture,
        status=BackgroundJobStatus.failed,
        payload={"capture_at": capture_at},
        error_code="history_evidence_unavailable",
        attempt_count=5,
        max_attempts=5,
        finished_at=NOW - timedelta(hours=1),
    )
    jobs = SimpleNamespace(retry_failed_scheduled_capture=AsyncMock())
    service = PortfolioHistorySchedulerService(cast(AsyncSession, object()), jobs=cast(Any, jobs))
    locked = SimpleNamespace(
        state=SimpleNamespace(user_id="user-1", next_capture_at=capture_at),
        has_building_generation=False,
        has_active_job=False,
        has_publication=True,
        dirty=None,
        failed_capture_jobs=(job,),
    )

    first = await service._process_locked(cast(Any, locked), now=NOW, daily_slot=NOW)
    assert first.action is PortfolioHistoryScheduleAction.capture_retry_enqueued
    jobs.retry_failed_scheduled_capture.assert_awaited_once_with(
        actor_user_id="user-1", job_id=job.id, now=NOW
    )

    job.attempt_count = job.max_attempts = 10
    job.finished_at = NOW
    later = [
        await service._process_locked(
            cast(Any, locked), now=NOW + timedelta(hours=tick), daily_slot=NOW
        )
        for tick in range(1, 4)
    ]
    assert all(
        decision.action is PortfolioHistoryScheduleAction.deferred_failed_job for decision in later
    )
    assert jobs.retry_failed_scheduled_capture.await_count == 1
