"""Explicit production runtime composition for history worker and scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.modules.portfolio_history.jobs.composition import (
    HistoricalProviderBundle,
    PortfolioHistoryWorkerSettings,
    create_portfolio_history_dispatch_executor,
    create_portfolio_history_worker_runner,
)
from app.modules.portfolio_history.jobs.worker import PortfolioHistoryWorkerRunner
from app.modules.portfolio_history.scheduler.runner import PortfolioHistorySchedulerRunner


@dataclass(frozen=True, slots=True)
class PortfolioHistoryRuntime:
    worker: PortfolioHistoryWorkerRunner
    scheduler: PortfolioHistorySchedulerRunner


async def verify_portfolio_history_runtime_schema(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        row = (
            await session.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) = 4 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = ANY(ARRAY["
                    "'SnapshotSeriesRebuildJob','SnapshotSeriesDirtyState',"
                    "'SnapshotSeriesCanonicalInvalidation',"
                    "'SnapshotSeriesScheduleState'])) AS tables_ready,"
                    "(SELECT count(*) = 2 FROM information_schema.columns WHERE "
                    "(table_schema, table_name, column_name) IN "
                    "(('public','SnapshotSeriesCanonicalInvalidation','resolvedAt'),"
                    "('public','SnapshotSeriesCanonicalInvalidation',"
                    "'resolvedSnapshotGenerationId'))) "
                    "AS columns_ready,"
                    "EXISTS (SELECT 1 FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
                    "JOIN pg_namespace n ON n.oid = t.typnamespace "
                    "WHERE n.nspname = 'public' AND t.typname = 'SnapshotSeriesJobKind' "
                    "AND e.enumlabel = 'rebuild') AS enum_ready,"
                    "(SELECT count(*) = 2 FROM pg_constraint c JOIN pg_namespace n "
                    "ON n.oid = c.connamespace WHERE n.nspname = 'public' AND c.conname = ANY(ARRAY["
                    "'SnapshotSeriesDirtyState_valid',"
                    "'SnapshotSeriesCanonicalInvalidation_firstDirtyEpoch_positive'])) "
                    "AS constraints_ready"
                )
            )
        ).one()
        await session.rollback()
    if (
        row.tables_ready is not True
        or row.columns_ready is not True
        or row.enum_ready is not True
        or row.constraints_ready is not True
    ):
        raise RuntimeError("Snapshot-series runtime requires the complete 3z schema.")


async def create_portfolio_history_runtime(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    providers: HistoricalProviderBundle | None = None,
) -> PortfolioHistoryRuntime:
    if not isinstance(settings, Settings) or not settings.portfolio_history_runtime_enabled:
        raise ValueError("Portfolio history runtime is not enabled.")
    if settings.database_url is None:
        raise ValueError("Portfolio history runtime requires a configured database.")
    await verify_portfolio_history_runtime_schema(session_factory)
    dispatch = create_portfolio_history_dispatch_executor(
        session_factory,
        settings=settings,
        providers=providers,
    )
    worker_id = f"{settings.portfolio_history_worker_id}-{uuid4()}"
    worker = create_portfolio_history_worker_runner(
        session_factory,
        settings=PortfolioHistoryWorkerSettings(
            worker_id=worker_id,
            lease_duration=timedelta(seconds=settings.portfolio_history_worker_lease_seconds),
            heartbeat_interval=timedelta(
                seconds=settings.portfolio_history_worker_heartbeat_seconds
            ),
            poll_interval=settings.portfolio_history_worker_poll_seconds,
        ),
        executor=dispatch,
    )
    scheduler = PortfolioHistorySchedulerRunner(
        session_factory,
        poll_interval=settings.portfolio_history_scheduler_poll_seconds,
    )
    return PortfolioHistoryRuntime(worker, scheduler)


__all__ = [
    "PortfolioHistoryRuntime",
    "create_portfolio_history_runtime",
    "verify_portfolio_history_runtime_schema",
]
