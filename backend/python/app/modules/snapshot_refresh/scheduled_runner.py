"""Process-local scheduler for renewable market-backed snapshot projections."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.canonical_lineage import AccountCanonicalChangeModel
from app.db.models.enums import BackgroundJobStatus, SnapshotGranularity, SnapshotSource
from app.db.models.snapshot_series_jobs import SnapshotSeriesRebuildJobModel
from app.modules.market_data.acquisition_cache import CycleMarketAcquisitionCache
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.snapshot_refresh.market_backed_models import (
    ExecuteMarketBackedSnapshotRefreshCommand,
)
from app.modules.snapshot_refresh.market_backed_service import MarketBackedSnapshotRefreshService
from app.modules.snapshot_refresh.version import current_coordinated_snapshot_calculation_version

logger = logging.getLogger(__name__)
type Clock = Callable[[], datetime]
type RefreshServiceFactory = Callable[[AsyncSession, Settings], MarketBackedSnapshotRefreshService]


def _utc_minute_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)


def scheduled_snapshot_refresh_lock_id() -> int:
    """Stable cross-process lock namespace, independent of user financial data."""
    digest = sha256(b"scheduled-snapshot-refresh\0v1").digest()
    return int.from_bytes(digest[:8], "big", signed=True)


class ScheduledSnapshotRefreshRunner:
    """Refresh every eligible user's published projections outside request reads."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        settings: Settings,
        interval_seconds: float = 300.0,
        clock: Clock = _utc_minute_now,
        refresh_service_factory: RefreshServiceFactory = MarketBackedSnapshotRefreshService,
    ) -> None:
        if not 30 <= interval_seconds <= 3600:
            raise ValueError("The scheduled snapshot refresh interval is invalid.")
        self.session_factory = session_factory
        self.settings = settings
        self.interval_seconds = interval_seconds
        self.clock = clock
        self.refresh_service_factory = refresh_service_factory
        self.stop_event = asyncio.Event()

    async def _eligible_user_ids(self, session: AsyncSession) -> tuple[str, ...]:
        has_canonical_history = exists(
            select(1).where(AccountCanonicalChangeModel.account_id == AccountModel.id)
        )
        has_active_history_rebuild = exists(
            select(1).where(
                SnapshotSeriesRebuildJobModel.user_id == AccountMemberModel.user_id,
                SnapshotSeriesRebuildJobModel.status.in_(
                    (
                        BackgroundJobStatus.queued,
                        BackgroundJobStatus.retry_wait,
                        BackgroundJobStatus.running,
                    )
                ),
            )
        )
        return tuple(
            await session.scalars(
                select(AccountMemberModel.user_id)
                .join(AccountModel, AccountModel.id == AccountMemberModel.account_id)
                .where(
                    AccountMemberModel.accepted_at.is_not(None),
                    AccountModel.is_archived.is_(False),
                    has_canonical_history,
                    ~has_active_history_rebuild,
                )
                .distinct()
                .order_by(AccountMemberModel.user_id)
            )
        )

    async def _refresh_user(
        self,
        *,
        user_id: str,
        timestamp: datetime,
        acquisition_cache: CycleMarketAcquisitionCache,
    ) -> None:
        async with self.session_factory() as session:
            refresh_service = self.refresh_service_factory(session, self.settings)
            if self.refresh_service_factory is MarketBackedSnapshotRefreshService:
                refresh_service = MarketBackedSnapshotRefreshService(
                    session,
                    self.settings,
                    market_service_factory=lambda market_session, market_settings: (
                        create_production_market_evidence_service(
                            market_session,
                            market_settings,
                            acquisition_cache=acquisition_cache,
                        )
                    ),
                )
            await refresh_service.execute(
                ExecuteMarketBackedSnapshotRefreshCommand(
                    user_id=user_id,
                    snapshot_timestamp=timestamp,
                    granularity=SnapshotGranularity.minute,
                    source=SnapshotSource.price_refresh,
                    calculation_version=current_coordinated_snapshot_calculation_version(),
                    calculated_at=timestamp,
                    created_at=timestamp,
                    is_recalculated=False,
                )
            )

    async def run_once(self) -> bool:
        """Run a single globally locked cycle; false means another process owns it."""
        timestamp = self.clock()
        if timestamp.tzinfo is not None or timestamp.second or timestamp.microsecond:
            raise ValueError("Scheduled snapshot refresh clock must return a UTC-naive minute.")
        async with self.session_factory() as lock_session, lock_session.begin():
            locked = bool(
                await lock_session.scalar(
                    select(func.pg_try_advisory_xact_lock(scheduled_snapshot_refresh_lock_id()))
                )
            )
            if not locked:
                return False
            user_ids = await self._eligible_user_ids(lock_session)
            acquisition_cache = CycleMarketAcquisitionCache()
            for user_id in user_ids:
                if self.stop_event.is_set():
                    return True
                try:
                    await self._refresh_user(
                        user_id=user_id,
                        timestamp=timestamp,
                        acquisition_cache=acquisition_cache,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning(
                        "scheduled_snapshot_refresh_user_failed",
                        extra={"user_id": user_id, "error_type": type(exc).__name__},
                    )
            return True

    async def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduled_snapshot_refresh_iteration_failed")
            try:
                await asyncio.wait_for(self.stop_event.wait(), self.interval_seconds)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self.stop_event.set()


__all__ = ["ScheduledSnapshotRefreshRunner", "scheduled_snapshot_refresh_lock_id"]
