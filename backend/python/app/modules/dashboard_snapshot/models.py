"""Immutable contracts for the pure dashboard snapshot projection."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.modules.portfolio_snapshot.models import (
    AccountType,
    AssetType,
    SnapshotGranularity,
)


@dataclass(frozen=True, slots=True)
class DashboardSnapshotSummary:
    """Exact portfolio totals and structural dashboard counts."""

    total_value: Decimal
    assets_value: Decimal
    liabilities_value: Decimal
    cash_value: Decimal
    investment_value: Decimal
    investment_cost_basis: Decimal
    unrealized_pnl_value: Decimal
    realized_pnl_value: Decimal
    net_deposits_value: Decimal
    fees_value: Decimal
    taxes_value: Decimal
    account_count: int
    investment_account_count: int
    liability_account_count: int
    position_count: int


@dataclass(frozen=True, slots=True)
class DashboardAccountCard:
    """Account-scoped values copied from one immutable snapshot view."""

    account_id: str
    snapshot_id: str
    name: str
    account_type: AccountType
    account_currency: str
    output_currency: str
    total_value: Decimal
    cash_value: Decimal
    investment_value: Decimal
    liabilities_value: Decimal
    unrealized_pnl_value: Decimal
    position_count: int


@dataclass(frozen=True, slots=True)
class DashboardAssetTypeAllocation:
    """Global investment allocation grouped by pure asset type."""

    asset_type: AssetType
    value: Decimal
    allocation_pct: Decimal
    position_count: int
    account_count: int


@dataclass(frozen=True, slots=True)
class DashboardTopPosition:
    """One account-scoped position with a global portfolio allocation."""

    account_id: str
    listing_id: str
    asset_id: str
    symbol: str
    name: str
    asset_type: AssetType
    value: Decimal
    value_currency: str
    unrealized_pnl: Decimal
    allocation_pct: Decimal


@dataclass(frozen=True, slots=True)
class DashboardSnapshotView:
    """Deterministic dashboard presentation of one coherent portfolio snapshot."""

    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    calculation_version: int
    summary: DashboardSnapshotSummary
    accounts: tuple[DashboardAccountCard, ...]
    asset_type_allocations: tuple[DashboardAssetTypeAllocation, ...]
    top_positions: tuple[DashboardTopPosition, ...]
