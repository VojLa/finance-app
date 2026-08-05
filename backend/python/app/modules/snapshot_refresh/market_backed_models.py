"""Immutable contracts for market-backed coordinated snapshot refresh."""

from dataclasses import dataclass
from datetime import datetime

from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.modules.market_data.models import MarketEvidenceRefreshResult
from app.modules.snapshot_refresh.executor import ExecuteUserSnapshotRefreshResult

_UNAVAILABLE_MESSAGE = "Market-backed snapshot refresh could not be completed."
_CONFLICT_MESSAGE = "Market-backed snapshot refresh conflicts with persisted state."


class MarketBackedSnapshotRefreshUnavailableError(RuntimeError):
    """Raised when required market or snapshot state is unavailable."""

    def __init__(self) -> None:
        super().__init__(_UNAVAILABLE_MESSAGE)


class MarketBackedSnapshotRefreshConflictError(RuntimeError):
    """Raised when an immutable market or snapshot identity conflicts."""

    def __init__(self) -> None:
        super().__init__(_CONFLICT_MESSAGE)


@dataclass(frozen=True, slots=True)
class ExecuteMarketBackedSnapshotRefreshCommand:
    user_id: str
    snapshot_timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    calculation_version: int
    calculated_at: datetime
    created_at: datetime
    is_recalculated: bool


@dataclass(frozen=True, slots=True)
class ExecuteMarketBackedSnapshotRefreshResult:
    market: MarketEvidenceRefreshResult
    snapshots: ExecuteUserSnapshotRefreshResult


__all__ = [
    "ExecuteMarketBackedSnapshotRefreshCommand",
    "ExecuteMarketBackedSnapshotRefreshResult",
    "MarketBackedSnapshotRefreshConflictError",
    "MarketBackedSnapshotRefreshUnavailableError",
]
