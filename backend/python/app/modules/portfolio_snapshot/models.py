"""Immutable input and output contracts for a pure portfolio snapshot view."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class AccountType(StrEnum):
    """Account types represented by validated AccountSnapshot evidence."""

    bank = "bank"
    cash = "cash"
    savings = "savings"
    broker = "broker"
    exchange = "exchange"
    crypto_wallet = "crypto_wallet"
    credit_card = "credit_card"
    loan = "loan"
    mortgage = "mortgage"


class AssetType(StrEnum):
    """Asset classification copied into the portfolio presentation contract."""

    stock = "stock"
    etf = "etf"
    crypto = "crypto"
    commodity = "commodity"
    cash = "cash"
    bond = "bond"
    other = "other"


class SnapshotGranularity(StrEnum):
    """Persisted AccountSnapshot bucket alignment."""

    minute = "minute"
    hour = "hour"
    day = "day"
    week = "week"
    month = "month"


class SnapshotSource(StrEnum):
    """Persisted AccountSnapshot creation source."""

    import_event = "import_event"
    price_refresh = "price_refresh"
    holdings_recalculation = "holdings_recalculation"
    scheduled = "scheduled"
    manual_recalculation = "manual_recalculation"


@dataclass(frozen=True, slots=True)
class PortfolioCurrencyAmount:
    """One exact original-currency amount from persisted snapshot evidence."""

    currency: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioSnapshotItemSource:
    """Complete validated evidence for one immutable AccountSnapshot item."""

    item_id: str
    listing_id: str
    asset_id: str
    symbol: str
    name: str
    asset_type: AssetType
    quantity: Decimal
    price_per_unit: Decimal
    price_currency: str
    price_timestamp: datetime
    value: Decimal
    value_currency: str
    cost_basis: Decimal | None
    cost_currency: str | None
    unrealized_pnl: Decimal | None
    allocation_pct: Decimal
    native_value: Decimal
    native_value_currency: str
    native_cost_basis: Decimal | None
    native_cost_currency: str | None
    native_cost_basis_by_currency: tuple[PortfolioCurrencyAmount, ...] | None
    average_buy_price: Decimal | None
    average_buy_price_currency: str | None


@dataclass(frozen=True, slots=True)
class PortfolioSnapshotSource:
    """Complete validated evidence for one immutable AccountSnapshot graph."""

    snapshot_id: str
    account_id: str
    account_name: str
    account_type: AccountType
    account_currency: str
    output_currency: str
    timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    calculation_version: int
    calculated_at: datetime
    created_at: datetime
    cash_value: Decimal
    cash_by_currency: tuple[PortfolioCurrencyAmount, ...]
    investment_value: Decimal
    investment_cost_basis: Decimal | None
    liabilities_value: Decimal
    total_value: Decimal
    net_deposits_value: Decimal | None
    net_deposits_by_currency: tuple[PortfolioCurrencyAmount, ...] | None
    realized_pnl_value: Decimal | None
    unrealized_pnl_value: Decimal | None
    fees_value: Decimal
    taxes_value: Decimal
    items: tuple[PortfolioSnapshotItemSource, ...]


@dataclass(frozen=True, slots=True)
class PortfolioAccountView:
    """Account presentation metadata attached to one snapshot view."""

    account_id: str
    name: str
    account_type: AccountType
    currency: str


@dataclass(frozen=True, slots=True)
class PortfolioSummaryView:
    """Exact output-currency aggregates copied from AccountSnapshot evidence."""

    cash_value: Decimal
    cash_by_currency: tuple[PortfolioCurrencyAmount, ...]
    investment_value: Decimal
    investment_cost_basis: Decimal | None
    liabilities_value: Decimal
    total_value: Decimal
    net_deposits_value: Decimal | None
    net_deposits_by_currency: tuple[PortfolioCurrencyAmount, ...] | None
    realized_pnl_value: Decimal | None
    unrealized_pnl_value: Decimal | None
    fees_value: Decimal
    taxes_value: Decimal
    position_count: int


@dataclass(frozen=True, slots=True)
class PortfolioPositionView:
    """Exact presentation fields copied from one validated snapshot item."""

    listing_id: str
    asset_id: str
    symbol: str
    name: str
    asset_type: AssetType
    quantity: Decimal
    price_per_unit: Decimal
    price_currency: str
    price_timestamp: datetime
    value: Decimal
    value_currency: str
    cost_basis: Decimal | None
    cost_currency: str | None
    unrealized_pnl: Decimal | None
    allocation_pct: Decimal
    native_value: Decimal
    native_value_currency: str
    native_cost_basis: Decimal | None
    native_cost_currency: str | None
    native_cost_basis_by_currency: tuple[PortfolioCurrencyAmount, ...] | None
    average_buy_price: Decimal | None
    average_buy_price_currency: str | None


@dataclass(frozen=True, slots=True)
class PortfolioSnapshotView:
    """Immutable single-account snapshot-backed portfolio view."""

    snapshot_id: str
    account: PortfolioAccountView
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    source: SnapshotSource
    calculation_version: int
    summary: PortfolioSummaryView
    positions: tuple[PortfolioPositionView, ...]
