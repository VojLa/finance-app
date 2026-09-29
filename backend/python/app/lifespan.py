from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Protocol
from uuid import uuid4

from fastapi import FastAPI

from app.config.settings import Settings, get_settings
from app.db.connection import close_database, create_database
from app.modules.jobs.import_executor import DurableImportJobExecutor
from app.modules.jobs.worker import BackgroundJobWorker, WorkerRunner
from app.modules.portfolio_history.runtime import create_portfolio_history_runtime
from app.modules.snapshot_refresh.scheduled_runner import ScheduledSnapshotRefreshRunner

logger = logging.getLogger(__name__)


class _Runner(Protocol):
    async def run(self) -> None: ...

    def stop(self) -> None: ...


async def _shutdown_runner(
    runner: _Runner,
    task: asyncio.Task[None],
    *,
    grace_seconds: float,
    log_name: str,
) -> None:
    try:
        runner.stop()
    except Exception:
        logger.exception("runtime_stop_failed", extra={"runtime": log_name})
    _, pending = await asyncio.wait({task}, timeout=grace_seconds)
    if pending:
        task.cancel()
        second_grace = max(grace_seconds, 0.1)
        _, pending = await asyncio.wait({task}, timeout=second_grace)
        if pending:
            task.cancel()
            _, pending = await asyncio.wait({task}, timeout=0.1)
            if pending:
                logger.error(
                    "runtime_task_ignored_cancellation",
                    extra={"runtime": log_name},
                )
        else:
            logger.warning("runtime_task_cancelled_after_grace", extra={"runtime": log_name})
    if task.done() and not task.cancelled():
        error = task.exception()
        if error is not None:
            logger.error(
                "runtime_task_stopped_with_error",
                extra={"runtime": log_name},
                exc_info=(type(error), error, error.__traceback__),
            )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = getattr(app.state, "settings", None) or get_settings()
    app.state.database = create_database(settings)
    runners: list[tuple[_Runner, asyncio.Task[None], float, str]] = []
    try:
        background_runner: WorkerRunner | None = None
        history_runtime = None
        scheduled_snapshot_refresh_runner = None
        if settings.background_jobs_enabled:
            if app.state.database is None:
                raise RuntimeError("Background jobs require a configured database.")
            worker = BackgroundJobWorker(
                app.state.database.session_factory,
                DurableImportJobExecutor(app.state.database.session_factory, settings),
                worker_id=f"api-{uuid4()}",
                lease_duration=timedelta(seconds=settings.background_job_lease_seconds),
                heartbeat_interval=timedelta(seconds=settings.background_job_heartbeat_seconds),
            )
            background_runner = WorkerRunner(
                worker, poll_interval=settings.background_job_poll_seconds
            )
        if settings.portfolio_history_runtime_enabled:
            if app.state.database is None:
                raise RuntimeError("Portfolio history runtime requires a configured database.")
            history_runtime = await create_portfolio_history_runtime(
                app.state.database.session_factory,
                settings=settings,
            )
        if settings.scheduled_snapshot_refresh_runner_enabled:
            if app.state.database is None:
                raise RuntimeError("Scheduled snapshot refresh requires a configured database.")
            scheduled_snapshot_refresh_runner = ScheduledSnapshotRefreshRunner(
                app.state.database.session_factory,
                settings=settings,
                interval_seconds=settings.scheduled_snapshot_refresh_interval_seconds,
            )

        if background_runner is not None:
            app.state.background_job_runner = background_runner
            task = asyncio.create_task(background_runner.run(), name="background-job-worker")
            runners.append(
                (
                    background_runner,
                    task,
                    settings.background_job_shutdown_grace_seconds,
                    "background-job-worker",
                )
            )
        if history_runtime is not None:
            app.state.portfolio_history_runtime = history_runtime
            worker_task = asyncio.create_task(
                history_runtime.worker.run(), name="portfolio-history-worker"
            )
            runners.append(
                (
                    history_runtime.worker,
                    worker_task,
                    settings.portfolio_history_shutdown_grace_seconds,
                    "portfolio-history-worker",
                )
            )
            scheduler_task = asyncio.create_task(
                history_runtime.scheduler.run(), name="portfolio-history-scheduler"
            )
            runners.append(
                (
                    history_runtime.scheduler,
                    scheduler_task,
                    settings.portfolio_history_shutdown_grace_seconds,
                    "portfolio-history-scheduler",
                )
            )
            app.state.portfolio_history_runtime_tasks = (
                worker_task,
                scheduler_task,
            )
        if scheduled_snapshot_refresh_runner is not None:
            app.state.scheduled_snapshot_refresh_runner = scheduled_snapshot_refresh_runner
            task = asyncio.create_task(
                scheduled_snapshot_refresh_runner.run(),
                name="scheduled-snapshot-refresh-runner",
            )
            app.state.scheduled_snapshot_refresh_runner_task = task
            runners.append(
                (
                    scheduled_snapshot_refresh_runner,
                    task,
                    settings.scheduled_snapshot_refresh_shutdown_grace_seconds,
                    "scheduled-snapshot-refresh-runner",
                )
            )
        yield
    finally:
        try:
            for runner, task, grace_seconds, log_name in reversed(runners):
                await _shutdown_runner(
                    runner,
                    task,
                    grace_seconds=grace_seconds,
                    log_name=log_name,
                )
        finally:
            await close_database(getattr(app.state, "database", None))
