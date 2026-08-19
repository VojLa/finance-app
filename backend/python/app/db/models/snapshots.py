from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import JSONB, MONEY, PERCENTAGE, QUANTITY, TIMESTAMP
from app.db.models.enums import (
    PRICE_SOURCE_DB,
    SNAPSHOT_GRANULARITY_DB,
    SNAPSHOT_SOURCE_DB,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)


class NetWorthSnapshotModel(Base):
    __tablename__ = "NetWorthSnapshot"
    __table_args__ = (
        UniqueConstraint("userId", "timestamp", "currency", "granularity"),
        Index(None, "userId", "granularity", "timestamp"),
        Index(None, "source", "timestamp"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("public.User.id", ondelete="RESTRICT"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    granularity: Mapped[SnapshotGranularity] = mapped_column(
        SNAPSHOT_GRANULARITY_DB,
        nullable=False,
    )
    source: Mapped[SnapshotSource] = mapped_column(SNAPSHOT_SOURCE_DB, nullable=False)
    currency: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'CZK'::text"),
    )
    cash_value: Mapped[Decimal] = mapped_column("cashValue", MONEY, nullable=False)
    portfolio_value: Mapped[Decimal] = mapped_column("portfolioValue", MONEY, nullable=False)
    liabilities_value: Mapped[Decimal] = mapped_column(
        "liabilitiesValue",
        MONEY,
        nullable=False,
    )
    total_net_worth: Mapped[Decimal] = mapped_column("totalNetWorth", MONEY, nullable=False)
    is_recalculated: Mapped[bool] = mapped_column(
        "isRecalculated",
        nullable=False,
        server_default=text("false"),
    )
    calculated_at: Mapped[datetime] = mapped_column(
        "calculatedAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    calculation_version: Mapped[int] = mapped_column(
        "calculationVersion",
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    cash_value_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "cashValueByCurrency",
        JSONB,
    )
    portfolio_value_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "portfolioValueByCurrency",
        JSONB,
    )
    liabilities_value_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "liabilitiesValueByCurrency",
        JSONB,
    )
    total_net_worth_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "totalNetWorthByCurrency",
        JSONB,
    )
    exchange_rates: Mapped[dict[str, Any] | None] = mapped_column("exchangeRates", JSONB)


class AccountSnapshotModel(Base):
    __tablename__ = "AccountSnapshot"
    __table_args__ = (
        UniqueConstraint("accountId", "timestamp", "currency", "granularity"),
        Index(None, "accountId", "granularity", "timestamp"),
        Index(None, "source", "timestamp"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    granularity: Mapped[SnapshotGranularity] = mapped_column(
        SNAPSHOT_GRANULARITY_DB,
        nullable=False,
    )
    source: Mapped[SnapshotSource] = mapped_column(SNAPSHOT_SOURCE_DB, nullable=False)
    currency: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        server_default=text("'CZK'::text"),
    )
    cash_value: Mapped[Decimal] = mapped_column("cashValue", MONEY, nullable=False)
    investment_value: Mapped[Decimal] = mapped_column("investmentValue", MONEY, nullable=False)
    investment_cost_basis: Mapped[Decimal | None] = mapped_column(
        "investmentCostBasis",
        MONEY,
    )
    liabilities_value: Mapped[Decimal] = mapped_column(
        "liabilitiesValue",
        MONEY,
        nullable=False,
    )
    total_value: Mapped[Decimal] = mapped_column("totalValue", MONEY, nullable=False)
    is_recalculated: Mapped[bool] = mapped_column(
        "isRecalculated",
        nullable=False,
        server_default=text("false"),
    )
    calculated_at: Mapped[datetime] = mapped_column(
        "calculatedAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    calculation_version: Mapped[int] = mapped_column(
        "calculationVersion",
        Integer,
        nullable=False,
        server_default=text("1"),
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    net_deposits_value: Mapped[Decimal | None] = mapped_column(
        "netDepositsValue",
        MONEY,
    )
    realized_pnl_value: Mapped[Decimal | None] = mapped_column(
        "realizedPnlValue",
        MONEY,
    )
    unrealized_pnl_value: Mapped[Decimal | None] = mapped_column(
        "unrealizedPnlValue",
        MONEY,
    )
    fees_value: Mapped[Decimal] = mapped_column(
        "feesValue",
        MONEY,
        nullable=False,
        server_default=text("0"),
    )
    taxes_value: Mapped[Decimal] = mapped_column(
        "taxesValue",
        MONEY,
        nullable=False,
        server_default=text("0"),
    )
    cash_value_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "cashValueByCurrency",
        JSONB(none_as_null=True),
    )
    investment_value_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "investmentValueByCurrency",
        JSONB(none_as_null=True),
    )
    investment_cost_basis_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "investmentCostBasisByCurrency",
        JSONB(none_as_null=True),
    )
    net_deposits_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "netDepositsByCurrency",
        JSONB(none_as_null=True),
    )
    realized_pnl_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "realizedPnlByCurrency",
        JSONB(none_as_null=True),
    )
    unrealized_pnl_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "unrealizedPnlByCurrency",
        JSONB(none_as_null=True),
    )
    fees_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "feesByCurrency",
        JSONB(none_as_null=True),
    )
    taxes_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "taxesByCurrency",
        JSONB(none_as_null=True),
    )
    exchange_rates: Mapped[dict[str, Any] | None] = mapped_column(
        "exchangeRates",
        JSONB(none_as_null=True),
    )


class AccountSnapshotItemModel(Base):
    __tablename__ = "AccountSnapshotItem"
    __table_args__ = (
        UniqueConstraint("snapshotId", "listingId"),
        CheckConstraint(
            '"nativeCostBasisByCurrency" IS NULL OR '
            "(jsonb_typeof(\"nativeCostBasisByCurrency\") = 'object' "
            "AND \"nativeCostBasisByCurrency\" <> '{}'::jsonb)",
            name="AccountSnapshotItem_nativeCostBasisByCurrency_nonempty_object",
        ),
        CheckConstraint(
            '("costBasis" IS NULL) = ("costCurrency" IS NULL) '
            'AND ("costBasis" IS NULL) = ("nativeCostBasis" IS NULL) '
            'AND ("costBasis" IS NULL) = ("nativeCostCurrency" IS NULL) '
            'AND ("costBasis" IS NULL) = ("nativeCostBasisByCurrency" IS NULL) '
            'AND ("costBasis" IS NULL) = ("averageBuyPrice" IS NULL) '
            'AND ("costBasis" IS NULL) = ("averageBuyPriceCurrency" IS NULL)',
            name="AccountSnapshotItem_cost_basis_completeness",
        ),
        Index(None, "assetId"),
        Index(None, "listingId"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(
        "snapshotId",
        ForeignKey("public.AccountSnapshot.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_id: Mapped[str | None] = mapped_column(
        "assetId",
        ForeignKey("public.Asset.id", ondelete="SET NULL"),
    )
    listing_id: Mapped[str] = mapped_column(
        "listingId",
        ForeignKey("public.AssetListing.id", ondelete="RESTRICT"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    price_per_unit: Mapped[Decimal] = mapped_column("pricePerUnit", QUANTITY, nullable=False)
    price_currency: Mapped[str | None] = mapped_column("priceCurrency", Text)
    price_source: Mapped[PriceSource | None] = mapped_column("priceSource", PRICE_SOURCE_DB)
    price_timestamp: Mapped[datetime | None] = mapped_column("priceTimestamp", TIMESTAMP)
    value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cost_basis: Mapped[Decimal | None] = mapped_column("costBasis", QUANTITY)
    cost_currency: Mapped[str | None] = mapped_column("costCurrency", Text)
    allocation_pct: Mapped[Decimal] = mapped_column("allocationPct", PERCENTAGE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    native_value: Mapped[Decimal | None] = mapped_column("nativeValue", QUANTITY)
    value_currency: Mapped[str | None] = mapped_column("valueCurrency", Text)
    native_cost_basis: Mapped[Decimal | None] = mapped_column("nativeCostBasis", QUANTITY)
    native_cost_currency: Mapped[str | None] = mapped_column("nativeCostCurrency", Text)
    native_cost_basis_by_currency: Mapped[dict[str, object] | None] = mapped_column(
        "nativeCostBasisByCurrency",
        JSONB(none_as_null=True),
    )
    average_buy_price: Mapped[Decimal | None] = mapped_column("averageBuyPrice", QUANTITY)
    average_buy_price_currency: Mapped[str | None] = mapped_column(
        "averageBuyPriceCurrency",
        Text,
    )
