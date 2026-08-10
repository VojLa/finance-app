import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

from fastapi import FastAPI

from app.config.settings import Settings, get_settings
from app.db.connection import close_database, create_database
from app.modules.jobs.import_executor import DurableImportJobExecutor
from app.modules.jobs.worker import BackgroundJobWorker, WorkerRunner

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = getattr(app.state, "settings", None) or get_settings()
    app.state.database = create_database(settings)
    runner: WorkerRunner | None = None
    worker_task: asyncio.Task[None] | None = None
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
        runner = WorkerRunner(worker, poll_interval=settings.background_job_poll_seconds)
        app.state.background_job_runner = runner
        worker_task = asyncio.create_task(runner.run(), name="background-job-worker")
    try:
        yield
    finally:
        if runner is not None and worker_task is not None:
            runner.stop()
            try:
                await asyncio.wait_for(
                    asyncio.shield(worker_task),
                    timeout=settings.background_job_shutdown_grace_seconds,
                )
            except TimeoutError:
                worker_task.cancel()
                try:
                    await asyncio.wait_for(
                        asyncio.gather(worker_task, return_exceptions=True),
                        timeout=settings.background_job_shutdown_grace_seconds,
                    )
                except TimeoutError:
                    logger.error("background_job_worker_shutdown_timed_out")
        await close_database(getattr(app.state, "database", None))
