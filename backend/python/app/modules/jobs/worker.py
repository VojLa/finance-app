from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.jobs.lifecycle import automatic_retry_at
from app.modules.jobs.models import (
    ImportJobCheckpoint,
    ImportJobPhase,
    ImportJobProgress,
    ImportJobResult,
)
from app.modules.jobs.repository import (
    BackgroundJobLeaseLostError,
    BackgroundJobRepository,
    ClaimedBackgroundJob,
)

logger = logging.getLogger(__name__)

type CheckpointCallback = Callable[[ImportJobCheckpoint, ImportJobProgress], Awaitable[None]]


class ImportJobExecutor(Protocol):
    async def execute(
        self,
        claimed: ClaimedBackgroundJob,
        *,
        checkpoint: CheckpointCallback,
    ) -> ImportJobResult: ...


class RetryableBackgroundJobError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PermanentBackgroundJobError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class BackgroundJobWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        executor: ImportJobExecutor,
        *,
        worker_id: str,
        lease_duration: timedelta,
        heartbeat_interval: timedelta,
    ) -> None:
        if (
            not worker_id
            or worker_id != worker_id.strip()
            or heartbeat_interval <= timedelta(0)
            or heartbeat_interval >= lease_duration
        ):
            raise ValueError("The background worker boundary is invalid.")
        self.session_factory = session_factory
        self.executor = executor
        self.worker_id = worker_id
        self.lease_duration = lease_duration
        self.heartbeat_interval = heartbeat_interval

    async def run_once(self) -> bool:
        async with self.session_factory() as session:
            claimed = await BackgroundJobRepository(session).claim_next(
                worker_id=self.worker_id,
                now=_now(),
                lease_duration=self.lease_duration,
            )
            await session.commit()
        if claimed is None:
            return False

        heartbeat_stop = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(claimed, heartbeat_stop),
            name=f"background-job-heartbeat:{claimed.job.id}",
        )
        execution_task = asyncio.create_task(
            self.executor.execute(
                claimed,
                checkpoint=lambda checkpoint, progress: self._checkpoint(
                    claimed,
                    checkpoint=checkpoint,
                    progress=progress,
                ),
            ),
            name=f"background-job-execution:{claimed.job.id}",
        )
        try:
            done, _pending = await asyncio.wait(
                {execution_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done:
                execution_task.cancel()
                await asyncio.gather(execution_task, return_exceptions=True)
                heartbeat_error = heartbeat_task.exception()
                if heartbeat_error is not None:
                    raise heartbeat_error
                raise BackgroundJobLeaseLostError(
                    "The background job heartbeat stopped before execution completed."
                )
            result = await execution_task
            await self._complete(claimed, result)
        except asyncio.CancelledError:
            execution_task.cancel()
            await asyncio.gather(execution_task, return_exceptions=True)
            await self._release(claimed)
            raise
        except BackgroundJobLeaseLostError:
            logger.warning("background_job_lease_lost", extra={"job_id": claimed.job.id})
        except PermanentBackgroundJobError as exc:
            await self._fail(claimed, code=exc.code, message=exc.message)
        except RetryableBackgroundJobError as exc:
            await self._retry_or_fail(claimed, code=exc.code, message=exc.message)
        except Exception:
            logger.exception("background_job_execution_failed", extra={"job_id": claimed.job.id})
            await self._retry_or_fail(
                claimed,
                code="background_job_transient_failure",
                message="Background processing was interrupted and will be retried.",
            )
        finally:
            heartbeat_stop.set()
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        return True

    async def _heartbeat_loop(
        self,
        claimed: ClaimedBackgroundJob,
        stop: asyncio.Event,
    ) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.heartbeat_interval.total_seconds())
                return
            except TimeoutError:
                pass
            async with self.session_factory() as session:
                try:
                    await BackgroundJobRepository(session).heartbeat(
                        lease=claimed.lease,
                        now=_now(),
                        lease_duration=self.lease_duration,
                    )
                    await session.commit()
                except BackgroundJobLeaseLostError:
                    await session.rollback()
                    return

    async def _checkpoint(
        self,
        claimed: ClaimedBackgroundJob,
        *,
        checkpoint: ImportJobCheckpoint,
        progress: ImportJobProgress,
    ) -> None:
        async with self.session_factory() as session:
            await BackgroundJobRepository(session).checkpoint(
                lease=claimed.lease,
                checkpoint=checkpoint.model_dump(mode="json"),
                progress=progress.model_dump(mode="json"),
                now=_now(),
            )
            await session.commit()

    async def _complete(
        self,
        claimed: ClaimedBackgroundJob,
        result: ImportJobResult,
    ) -> None:
        initial = ImportJobProgress.model_validate(claimed.job.progress)
        progress = ImportJobProgress(
            phase=ImportJobPhase.completed,
            completed_units=initial.total_units,
            total_units=initial.total_units,
            completed_batches=initial.total_batches,
            total_batches=initial.total_batches,
        )
        async with self.session_factory() as session:
            await BackgroundJobRepository(session).complete(
                lease=claimed.lease,
                result=result.model_dump(mode="json"),
                progress=progress.model_dump(mode="json"),
                now=_now(),
            )
            await session.commit()

    async def _retry_or_fail(
        self,
        claimed: ClaimedBackgroundJob,
        *,
        code: str,
        message: str,
    ) -> None:
        now = _now()
        async with self.session_factory() as session:
            repository = BackgroundJobRepository(session)
            if claimed.job.attempt_count >= claimed.job.max_attempts:
                await repository.fail(
                    lease=claimed.lease,
                    error_code="background_job_attempts_exhausted",
                    error_message="Background processing could not be completed after all retries.",
                    now=now,
                )
            else:
                await repository.schedule_retry(
                    lease=claimed.lease,
                    run_after=automatic_retry_at(
                        now=now,
                        attempt_count=claimed.job.attempt_count,
                    ),
                    error_code=code,
                    error_message=message,
                    now=now,
                )
            await session.commit()

    async def _fail(self, claimed: ClaimedBackgroundJob, *, code: str, message: str) -> None:
        async with self.session_factory() as session:
            await BackgroundJobRepository(session).fail(
                lease=claimed.lease,
                error_code=code,
                error_message=message,
                now=_now(),
            )
            await session.commit()

    async def _release(self, claimed: ClaimedBackgroundJob) -> None:
        async with self.session_factory() as session:
            try:
                await BackgroundJobRepository(session).release(lease=claimed.lease, now=_now())
                await session.commit()
            except BackgroundJobLeaseLostError:
                await session.rollback()


class WorkerRunner:
    def __init__(self, worker: BackgroundJobWorker, *, poll_interval: float) -> None:
        if not 0.1 <= poll_interval <= 60:
            raise ValueError("The worker poll interval is invalid.")
        self.worker = worker
        self.poll_interval = poll_interval
        self.stop_event = asyncio.Event()

    async def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                worked = await self.worker.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("background_job_runner_iteration_failed")
                worked = False
            if worked:
                continue
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=self.poll_interval)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self.stop_event.set()
