from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.modules.jobs.lifecycle import LeaseIdentity
from app.modules.jobs.models import (
    ImportJobCheckpoint,
    ImportJobPhase,
    ImportJobProgress,
    ImportJobResult,
)
from app.modules.jobs.repository import (
    BackgroundJobPublicationStaleError,
    BackgroundJobRepository,
    ClaimedBackgroundJob,
)
from app.modules.jobs.worker import (
    BackgroundJobWorker,
    DeferredBackgroundJobError,
    RetryableBackgroundJobError,
    WorkerRunner,
)


class _Session:
    commit = AsyncMock()
    rollback = AsyncMock()


class _SessionContext:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> _Session:
        return self.session

    async def __aexit__(self, *_args: object) -> None:
        return None


class _SessionFactory:
    def __init__(self) -> None:
        self.sessions: list[_Session] = []

    def __call__(self) -> _SessionContext:
        session = _Session()
        self.sessions.append(session)
        return _SessionContext(session)


def _claimed(*, attempt_count: int = 1, max_attempts: int = 5) -> ClaimedBackgroundJob:
    progress = ImportJobProgress(
        phase=ImportJobPhase.queued,
        completed_units=0,
        total_units=7,
        completed_batches=0,
        total_batches=1,
    )
    job = SimpleNamespace(
        id="job-1",
        progress=progress.model_dump(mode="json"),
        attempt_count=attempt_count,
        max_attempts=max_attempts,
    )
    return ClaimedBackgroundJob(
        job=cast(Any, job),
        lease=LeaseIdentity(job_id="job-1", owner="worker-1", version=1),
    )


class _SuccessfulExecutor:
    async def execute(self, claimed, *, checkpoint):
        assert claimed.job.id == "job-1"
        await checkpoint(
            ImportJobCheckpoint(
                phase=ImportJobPhase.posting,
                completed_batch_ids=("batch-a",),
            ),
            ImportJobProgress(
                phase=ImportJobPhase.posting,
                completed_units=5,
                total_units=7,
                completed_batches=1,
                total_batches=1,
            ),
        )
        return ImportJobResult(
            batch_ids=("batch-a",),
            rows_total=10,
            rows_imported=9,
            rows_skipped=1,
            snapshot_refresh_status="created",
            completed_at=datetime(2030, 1, 1),
        )


class _RetryExecutor:
    async def execute(self, claimed, *, checkpoint):
        del claimed, checkpoint
        raise RetryableBackgroundJobError(
            code="snapshot_temporarily_unavailable",
            message="Snapshot evidence is temporarily unavailable.",
        )


class _AwaitingLiabilityExecutor:
    async def execute(self, claimed, *, checkpoint):
        del claimed, checkpoint
        raise DeferredBackgroundJobError(
            run_after=datetime(2030, 1, 1, 0, 5),
            code="import_liability_balance_required",
            message="An explicit liability balance is required before portfolio publication.",
        )


class _BlockingExecutor:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def execute(self, claimed, *, checkpoint):
        del claimed, checkpoint
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


@pytest.mark.asyncio
async def test_worker_checkpoints_and_completes_with_fenced_updates(monkeypatch) -> None:
    factory = _SessionFactory()
    claim = AsyncMock(return_value=_claimed())
    checkpoint = AsyncMock()
    complete = AsyncMock()
    heartbeat = AsyncMock()
    monkeypatch.setattr(BackgroundJobRepository, "claim_next", claim)
    monkeypatch.setattr(BackgroundJobRepository, "checkpoint", checkpoint)
    monkeypatch.setattr(BackgroundJobRepository, "complete", complete)
    monkeypatch.setattr(BackgroundJobRepository, "heartbeat", heartbeat)

    worker = BackgroundJobWorker(
        cast(Any, factory),
        _SuccessfulExecutor(),
        worker_id="worker-1",
        lease_duration=timedelta(minutes=5),
        heartbeat_interval=timedelta(minutes=1),
    )

    assert await worker.run_once() is True
    checkpoint.assert_awaited_once()
    complete.assert_awaited_once()
    complete_call = complete.await_args
    assert complete_call is not None
    assert complete_call.kwargs["progress"]["phase"] == "completed"
    heartbeat.assert_not_awaited()


@pytest.mark.asyncio
async def test_retryable_failure_is_rescheduled_without_public_exception_detail(
    monkeypatch,
) -> None:
    factory = _SessionFactory()
    monkeypatch.setattr(
        BackgroundJobRepository,
        "claim_next",
        AsyncMock(return_value=_claimed(attempt_count=1)),
    )
    retry = AsyncMock()
    fail = AsyncMock()
    monkeypatch.setattr(BackgroundJobRepository, "schedule_retry", retry)
    monkeypatch.setattr(BackgroundJobRepository, "fail", fail)
    monkeypatch.setattr(BackgroundJobRepository, "heartbeat", AsyncMock())

    worker = BackgroundJobWorker(
        cast(Any, factory),
        _RetryExecutor(),
        worker_id="worker-1",
        lease_duration=timedelta(minutes=5),
        heartbeat_interval=timedelta(minutes=1),
    )

    assert await worker.run_once() is True
    retry.assert_awaited_once()
    retry_call = retry.await_args
    assert retry_call is not None
    assert retry_call.kwargs["error_code"] == "snapshot_temporarily_unavailable"
    fail.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_liability_waits_with_actionable_error_without_attempt_spend(
    monkeypatch,
) -> None:
    factory = _SessionFactory()
    monkeypatch.setattr(
        BackgroundJobRepository,
        "claim_next",
        AsyncMock(return_value=_claimed(attempt_count=1)),
    )
    defer = AsyncMock()
    monkeypatch.setattr(BackgroundJobRepository, "defer", defer)
    monkeypatch.setattr(BackgroundJobRepository, "heartbeat", AsyncMock())

    worker = BackgroundJobWorker(
        cast(Any, factory),
        _AwaitingLiabilityExecutor(),
        worker_id="worker-1",
        lease_duration=timedelta(minutes=5),
        heartbeat_interval=timedelta(minutes=1),
    )

    assert await worker.run_once() is True
    defer.assert_awaited_once()
    call = defer.await_args
    assert call is not None
    assert call.kwargs["error_code"] == "import_liability_balance_required"
    assert "explicit liability balance" in call.kwargs["error_message"]
    assert call.kwargs["run_after"] == datetime(2030, 1, 1, 0, 5)


@pytest.mark.asyncio
async def test_stale_publication_boundary_is_retried_without_waiting_for_lease_expiry(
    monkeypatch,
) -> None:
    factory = _SessionFactory()
    monkeypatch.setattr(
        BackgroundJobRepository,
        "claim_next",
        AsyncMock(return_value=_claimed(attempt_count=1)),
    )
    monkeypatch.setattr(BackgroundJobRepository, "checkpoint", AsyncMock())
    monkeypatch.setattr(
        BackgroundJobRepository,
        "complete",
        AsyncMock(side_effect=BackgroundJobPublicationStaleError()),
    )
    monkeypatch.setattr(BackgroundJobRepository, "heartbeat", AsyncMock())
    retry = AsyncMock()
    monkeypatch.setattr(BackgroundJobRepository, "schedule_retry", retry)

    worker = BackgroundJobWorker(
        cast(Any, factory),
        _SuccessfulExecutor(),
        worker_id="worker-1",
        lease_duration=timedelta(minutes=5),
        heartbeat_interval=timedelta(minutes=1),
    )

    assert await worker.run_once() is True
    retry.assert_awaited_once()
    call = retry.await_args
    assert call is not None
    assert call.kwargs["error_code"] == "import_publication_stale"
    assert call.kwargs["error_message"] == "Portfolio publication changed and will be retried."


@pytest.mark.asyncio
async def test_exhausted_retry_preserves_the_actionable_terminal_cause(monkeypatch) -> None:
    factory = _SessionFactory()
    monkeypatch.setattr(
        BackgroundJobRepository,
        "claim_next",
        AsyncMock(return_value=_claimed(attempt_count=5, max_attempts=5)),
    )
    retry = AsyncMock()
    fail = AsyncMock()
    monkeypatch.setattr(BackgroundJobRepository, "schedule_retry", retry)
    monkeypatch.setattr(BackgroundJobRepository, "fail", fail)
    monkeypatch.setattr(BackgroundJobRepository, "heartbeat", AsyncMock())

    worker = BackgroundJobWorker(
        cast(Any, factory),
        _RetryExecutor(),
        worker_id="worker-1",
        lease_duration=timedelta(minutes=5),
        heartbeat_interval=timedelta(minutes=1),
    )

    assert await worker.run_once() is True
    fail.assert_awaited_once()
    fail_call = fail.await_args
    assert fail_call is not None
    assert fail_call.kwargs["error_code"] == "snapshot_temporarily_unavailable"
    assert fail_call.kwargs["error_message"] == "Snapshot evidence is temporarily unavailable."
    retry.assert_not_awaited()


@pytest.mark.asyncio
async def test_heartbeat_failure_cancels_execution_before_lease_can_expire(monkeypatch) -> None:
    factory = _SessionFactory()
    executor = _BlockingExecutor()
    monkeypatch.setattr(
        BackgroundJobRepository,
        "claim_next",
        AsyncMock(return_value=_claimed(attempt_count=1)),
    )
    monkeypatch.setattr(
        BackgroundJobRepository,
        "heartbeat",
        AsyncMock(side_effect=RuntimeError("database unavailable")),
    )
    retry = AsyncMock()
    monkeypatch.setattr(BackgroundJobRepository, "schedule_retry", retry)

    worker = BackgroundJobWorker(
        cast(Any, factory),
        executor,
        worker_id="worker-1",
        lease_duration=timedelta(seconds=30),
        heartbeat_interval=timedelta(milliseconds=1),
    )

    assert await worker.run_once() is True
    assert executor.started.is_set()
    assert executor.cancelled.is_set()
    retry.assert_awaited_once()


@pytest.mark.asyncio
async def test_runner_recovers_from_operational_failure_and_keeps_polling() -> None:
    class _FailOnceWorker:
        calls = 0
        runner: WorkerRunner

        async def run_once(self) -> bool:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("database temporarily unavailable")
            self.runner.stop()
            return False

    worker = _FailOnceWorker()
    runner = WorkerRunner(cast(Any, worker), poll_interval=0.1)
    worker.runner = runner

    await asyncio.wait_for(runner.run(), timeout=1)
    assert worker.calls == 2
