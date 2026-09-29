"""Process-ready graceful worker loop for the dedicated history queue."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.jobs.lifecycle import automatic_retry_at
from app.modules.portfolio_history.jobs.models import (
    PortfolioHistoryJobCheckpoint,
    PortfolioHistoryJobProgress,
    PortfolioHistoryJobResult,
)
from app.modules.portfolio_history.jobs.repository import (
    ClaimedPortfolioHistoryJob,
    PortfolioHistoryJobLeaseLostError,
    PortfolioHistoryJobRepository,
)

logger = logging.getLogger(__name__)
type CheckpointCallback = Callable[
    [PortfolioHistoryJobCheckpoint, PortfolioHistoryJobProgress], Awaitable[None]
]


class PortfolioHistoryJobExecutor(Protocol):
    async def execute(
        self, claimed: ClaimedPortfolioHistoryJob, *, checkpoint: CheckpointCallback
    ) -> PortfolioHistoryJobResult: ...


class RetryablePortfolioHistoryJobError(RuntimeError):
    def __init__(self, *, code: str, message: str) -> None:
        self.code, self.message = code, message
        super().__init__(message)


class PermanentPortfolioHistoryJobError(RetryablePortfolioHistoryJobError):
    pass


def _now() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1_000) * 1_000)


class PortfolioHistoryJobWorker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        executor: PortfolioHistoryJobExecutor,
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
            raise ValueError("The history worker boundary is invalid.")
        self.session_factory, self.executor = session_factory, executor
        self.worker_id, self.lease_duration, self.heartbeat_interval = (
            worker_id,
            lease_duration,
            heartbeat_interval,
        )

    async def run_once(self) -> bool:
        async with self.session_factory() as session:
            claimed = await PortfolioHistoryJobRepository(session).claim_next(
                worker_id=self.worker_id, now=_now(), lease_duration=self.lease_duration
            )
            await session.commit()
        if claimed is None:
            return False
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat_loop(claimed, stop), name=f"history-job-heartbeat:{claimed.job.id}"
        )
        execution = asyncio.create_task(
            self.executor.execute(
                claimed,
                checkpoint=lambda checkpoint, progress: self._checkpoint(
                    claimed, checkpoint, progress
                ),
            ),
            name=f"history-job-execution:{claimed.job.id}",
        )
        try:
            done, _ = await asyncio.wait(
                {heartbeat, execution}, return_when=asyncio.FIRST_COMPLETED
            )
            if heartbeat in done:
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
                if (error := heartbeat.exception()) is not None:
                    raise error
                raise PortfolioHistoryJobLeaseLostError("History job heartbeat stopped.")
            await self._complete(claimed, await execution)
        except asyncio.CancelledError:
            execution.cancel()
            await asyncio.gather(execution, return_exceptions=True)
            await self._release(claimed)
            raise
        except PortfolioHistoryJobLeaseLostError:
            logger.warning("portfolio_history_job_lease_lost", extra={"job_id": claimed.job.id})
        except PermanentPortfolioHistoryJobError as exc:
            await self._fail(claimed, exc.code, exc.message)
        except RetryablePortfolioHistoryJobError as exc:
            await self._retry_or_fail(claimed, exc.code, exc.message)
        except Exception:
            logger.exception(
                "portfolio_history_job_execution_failed", extra={"job_id": claimed.job.id}
            )
            await self._retry_or_fail(
                claimed,
                "history_job_transient_failure",
                "History processing was interrupted and will be retried.",
            )
        finally:
            stop.set()
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
        return True

    async def _heartbeat_loop(
        self, claimed: ClaimedPortfolioHistoryJob, stop: asyncio.Event
    ) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), self.heartbeat_interval.total_seconds())
                return
            except TimeoutError:
                async with self.session_factory() as session:
                    try:
                        await PortfolioHistoryJobRepository(session).heartbeat(
                            lease=claimed.lease, now=_now(), lease_duration=self.lease_duration
                        )
                        await session.commit()
                    except PortfolioHistoryJobLeaseLostError:
                        await session.rollback()
                        return

    async def _checkpoint(
        self,
        claimed: ClaimedPortfolioHistoryJob,
        checkpoint: PortfolioHistoryJobCheckpoint,
        progress: PortfolioHistoryJobProgress,
    ) -> None:
        async with self.session_factory() as session:
            await PortfolioHistoryJobRepository(session).checkpoint(
                lease=claimed.lease,
                checkpoint=checkpoint.model_dump(mode="json"),
                progress=progress.model_dump(mode="json"),
                now=_now(),
            )
            await session.commit()

    async def _complete(
        self, claimed: ClaimedPortfolioHistoryJob, result: PortfolioHistoryJobResult
    ) -> None:
        progress = PortfolioHistoryJobProgress(phase="completed", completed_units=1, total_units=1)
        async with self.session_factory() as session:
            await PortfolioHistoryJobRepository(session).complete(
                lease=claimed.lease,
                result=result.model_dump(mode="json"),
                progress=progress.model_dump(mode="json"),
                now=_now(),
            )
            await session.commit()

    async def _retry_or_fail(
        self, claimed: ClaimedPortfolioHistoryJob, code: str, message: str
    ) -> None:
        async with self.session_factory() as session:
            repository = PortfolioHistoryJobRepository(session)
            if claimed.job.attempt_count >= claimed.job.max_attempts:
                await repository.fail(
                    lease=claimed.lease,
                    error_code=code,
                    error_message=message,
                    now=_now(),
                )
            else:
                now = _now()
                await repository.schedule_retry(
                    lease=claimed.lease,
                    run_after=automatic_retry_at(now=now, attempt_count=claimed.job.attempt_count),
                    error_code=code,
                    error_message=message,
                    now=now,
                )
            await session.commit()

    async def _fail(self, claimed: ClaimedPortfolioHistoryJob, code: str, message: str) -> None:
        async with self.session_factory() as session:
            await PortfolioHistoryJobRepository(session).fail(
                lease=claimed.lease, error_code=code, error_message=message, now=_now()
            )
            await session.commit()

    async def _release(self, claimed: ClaimedPortfolioHistoryJob) -> None:
        async with self.session_factory() as session:
            try:
                await PortfolioHistoryJobRepository(session).release(
                    lease=claimed.lease, now=_now()
                )
                await session.commit()
            except PortfolioHistoryJobLeaseLostError:
                await session.rollback()


class PortfolioHistoryWorkerRunner:
    def __init__(self, worker: PortfolioHistoryJobWorker, *, poll_interval: float) -> None:
        if not 0.1 <= poll_interval <= 60:
            raise ValueError("The history worker poll interval is invalid.")
        self.worker, self.poll_interval, self.stop_event = worker, poll_interval, asyncio.Event()

    async def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                worked = await self.worker.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("portfolio_history_worker_iteration_failed")
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(self.stop_event.wait(), self.poll_interval)
                except TimeoutError:
                    pass

    def stop(self) -> None:
        self.stop_event.set()
