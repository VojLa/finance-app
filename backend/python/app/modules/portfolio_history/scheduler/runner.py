"""Process-ready polling loop for durable portfolio-history scheduling."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.portfolio_history.scheduler.models import (
    PortfolioHistorySchedulerTickResult,
)
from app.modules.portfolio_history.scheduler.service import (
    MAX_SCHEDULES_PER_TICK,
    PortfolioHistorySchedulerService,
)

logger = logging.getLogger(__name__)
type Clock = Callable[[], datetime]
type SchedulerFactory = Callable[[AsyncSession], PortfolioHistorySchedulerService]
_MAX_TRANSACTION_ATTEMPTS = 3
_RETRYABLE_SQLSTATES = {"40001", "40P01"}


def _utc_now() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1_000) * 1_000)


class PortfolioHistorySchedulerRunner:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        poll_interval: float,
        clock: Clock = _utc_now,
        scheduler_factory: SchedulerFactory = PortfolioHistorySchedulerService,
    ) -> None:
        if not 0.1 <= poll_interval <= 300:
            raise ValueError("The history scheduler poll interval is invalid.")
        self.session_factory = session_factory
        self.poll_interval = poll_interval
        self.clock = clock
        self.scheduler_factory = scheduler_factory
        self.stop_event = asyncio.Event()

    async def run_once(self) -> PortfolioHistorySchedulerTickResult:
        now = self.clock()
        for attempt in range(_MAX_TRANSACTION_ATTEMPTS):
            try:
                async with self.session_factory() as session:
                    return await self.scheduler_factory(session).tick(
                        now=now,
                        limit=MAX_SCHEDULES_PER_TICK,
                    )
            except DBAPIError as exc:
                if (
                    getattr(exc.orig, "sqlstate", None) not in _RETRYABLE_SQLSTATES
                    or attempt + 1 == _MAX_TRANSACTION_ATTEMPTS
                ):
                    raise
                await asyncio.sleep(0)
        raise AssertionError("unreachable")

    async def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("portfolio_history_scheduler_iteration_failed")
            try:
                await asyncio.wait_for(self.stop_event.wait(), self.poll_interval)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self.stop_event.set()


__all__ = ["PortfolioHistorySchedulerRunner"]
