"""Immutable contracts for snapshot-backed portfolio history."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from app.db.models.enums import SnapshotGranularity, SnapshotSource


class PortfolioHistoryRange(StrEnum):
    """Supported calendar ranges for public portfolio history."""

    one_week = "1W"
    one_month = "1M"
    three_months = "3M"
    six_months = "6M"
    one_year = "1Y"
    all = "ALL"


@dataclass(frozen=True, slots=True)
class PersistedPortfolioHistoryPoint:
    """Exact physical fields read from one NetWorthSnapshot row."""

    snapshot_id: object
    user_id: object
    timestamp: object
    granularity: object
    source: object
    currency: object
    cash_value: object
    portfolio_value: object
    liabilities_value: object
    total_net_worth: object
    calculation_version: object


@dataclass(frozen=True, slots=True)
class CanonicalPortfolioHistoryPoint:
    """Validated history point retaining internal persistence lineage."""

    snapshot_id: str
    timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    calculation_version: int
    cash_value: Decimal
    investment_value: Decimal
    liabilities_value: Decimal
    net_worth_value: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioHistoryPoint:
    """Public-safe financial values at one persisted snapshot timestamp."""

    timestamp: datetime
    cash_value: Decimal
    investment_value: Decimal
    liabilities_value: Decimal
    net_worth_value: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioHistoryView:
    """Pure deterministic history returned to the HTTP boundary."""

    range: PortfolioHistoryRange
    currency: str
    points: tuple[PortfolioHistoryPoint, ...]
