"""Immutable output contracts for pure multi-account portfolio aggregation."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.modules.portfolio_snapshot.models import (
    PortfolioAccountView,
    PortfolioCurrencyAmount,
    PortfolioPositionView,
    PortfolioSummaryView,
    SnapshotGranularity,
    SnapshotSource,
)


@dataclass(frozen=True, slots=True)
class MultiAccountPortfolioSummary:
    """Exact output-currency totals across complete account snapshot views."""

    cash_value: Decimal
    cash_by_currency: tuple[PortfolioCurrencyAmount, ...]
    investment_value: Decimal
    investment_cost_basis: Decimal
    liabilities_value: Decimal
    total_value: Decimal
    net_deposits_value: Decimal
    net_deposits_by_currency: tuple[PortfolioCurrencyAmount, ...]
    realized_pnl_value: Decimal
    unrealized_pnl_value: Decimal
    fees_value: Decimal
    taxes_value: Decimal
    account_count: int
    position_count: int


@dataclass(frozen=True, slots=True)
class MultiAccountPortfolioAccountView:
    """One unchanged primary account-scoped aggregate contribution."""

    snapshot_id: str
    account: PortfolioAccountView
    source: SnapshotSource
    summary: PortfolioSummaryView
    positions: tuple[PortfolioPositionView, ...]


@dataclass(frozen=True, slots=True)
class MultiAccountPortfolioView:
    """Deterministic aggregate over one coherent set of account views."""

    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    calculation_version: int
    summary: MultiAccountPortfolioSummary
    accounts: tuple[MultiAccountPortfolioAccountView, ...]


@dataclass(frozen=True, slots=True)
class AccountPortfolioPresentationView:
    """Exact account-currency view linked to its primary manifest snapshot."""

    primary_snapshot_id: str
    presentation_snapshot_id: str
    currency: str
    account: PortfolioAccountView
    source: SnapshotSource
    summary: PortfolioSummaryView
    positions: tuple[PortfolioPositionView, ...]
