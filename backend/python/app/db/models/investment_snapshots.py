from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
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


class InvestmentAccountSnapshotModel(Base):
    """Immutable investment-only projection of one account snapshot."""

    __tablename__ = "InvestmentAccountSnapshot"
    __table_args__ = (
        UniqueConstraint("accountSnapshotId", name="InvestmentAccountSnapshot_accountSnapshot_key"),
        UniqueConstraint(
            "id",
            "generationId",
            "accountId",
            name="InvestmentAccountSnapshot_id_generation_account_key",
        ),
        UniqueConstraint(
            "id",
            "accountSnapshotId",
            "generationId",
            "accountId",
            name="InvestmentAccountSnapshot_input_coordinate_key",
        ),
        ForeignKeyConstraint(
            ("accountSnapshotId", "generationId", "accountId"),
            (
                "public.AccountSnapshot.id",
                "public.AccountSnapshot.generationId",
                "public.AccountSnapshot.accountId",
            ),
            name="InvestmentAccountSnapshot_account_snapshot_generation_fkey",
            ondelete="CASCADE",
        ),
        Index(
            "InvestmentAccountSnapshot_generation_account_timestamp_idx",
            "generationId",
            "accountId",
            "timestamp",
        ),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_snapshot_id: Mapped[str] = mapped_column("accountSnapshotId", Text, nullable=False)
    account_id: Mapped[str] = mapped_column("accountId", Text, nullable=False)
    generation_id: Mapped[str] = mapped_column("generationId", Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    valuation_timestamp: Mapped[datetime] = mapped_column(
        "valuationTimestamp", TIMESTAMP, nullable=False
    )
    granularity: Mapped[SnapshotGranularity] = mapped_column(
        SNAPSHOT_GRANULARITY_DB, nullable=False
    )
    source: Mapped[SnapshotSource] = mapped_column(SNAPSHOT_SOURCE_DB, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    cash_value: Mapped[Decimal] = mapped_column("cashValue", MONEY, nullable=False)
    investment_value: Mapped[Decimal] = mapped_column("investmentValue", MONEY, nullable=False)
    investment_cost_basis: Mapped[Decimal | None] = mapped_column("investmentCostBasis", MONEY)
    net_deposits_value: Mapped[Decimal | None] = mapped_column("netDepositsValue", MONEY)
    realized_pnl_value: Mapped[Decimal | None] = mapped_column("realizedPnlValue", MONEY)
    unrealized_pnl_value: Mapped[Decimal | None] = mapped_column("unrealizedPnlValue", MONEY)
    fees_value: Mapped[Decimal] = mapped_column(
        "feesValue", MONEY, nullable=False, server_default=text("0")
    )
    taxes_value: Mapped[Decimal] = mapped_column(
        "taxesValue", MONEY, nullable=False, server_default=text("0")
    )
    cash_value_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "cashValueByCurrency", JSONB(none_as_null=True)
    )
    investment_value_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "investmentValueByCurrency", JSONB(none_as_null=True)
    )
    investment_cost_basis_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "investmentCostBasisByCurrency", JSONB(none_as_null=True)
    )
    net_deposits_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "netDepositsByCurrency", JSONB(none_as_null=True)
    )
    realized_pnl_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "realizedPnlByCurrency", JSONB(none_as_null=True)
    )
    unrealized_pnl_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "unrealizedPnlByCurrency", JSONB(none_as_null=True)
    )
    fees_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "feesByCurrency", JSONB(none_as_null=True)
    )
    taxes_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "taxesByCurrency", JSONB(none_as_null=True)
    )
    price_evidence: Mapped[dict[str, Any] | None] = mapped_column(
        "priceEvidence", JSONB(none_as_null=True)
    )
    exchange_rates: Mapped[dict[str, Any] | None] = mapped_column(
        "exchangeRates", JSONB(none_as_null=True)
    )
    calculated_at: Mapped[datetime] = mapped_column(
        "calculatedAt", TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    calculation_version: Mapped[int] = mapped_column(
        "calculationVersion", Integer, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class InvestmentAccountSnapshotItemModel(Base):
    __tablename__ = "InvestmentAccountSnapshotItem"
    __table_args__ = (
        UniqueConstraint(
            "investmentAccountSnapshotId",
            "listingId",
            name="InvestmentAccountSnapshotItem_snapshot_listing_key",
        ),
        ForeignKeyConstraint(
            ("investmentAccountSnapshotId", "generationId", "accountId"),
            (
                "public.InvestmentAccountSnapshot.id",
                "public.InvestmentAccountSnapshot.generationId",
                "public.InvestmentAccountSnapshot.accountId",
            ),
            name="InvestmentAccountSnapshotItem_snapshot_generation_account_fkey",
            ondelete="CASCADE",
        ),
        Index(None, "listingId"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    investment_account_snapshot_id: Mapped[str] = mapped_column(
        "investmentAccountSnapshotId", Text, nullable=False
    )
    generation_id: Mapped[str] = mapped_column("generationId", Text, nullable=False)
    account_id: Mapped[str] = mapped_column("accountId", Text, nullable=False)
    asset_id: Mapped[str | None] = mapped_column(
        "assetId", ForeignKey("public.Asset.id", ondelete="SET NULL")
    )
    listing_id: Mapped[str] = mapped_column(
        "listingId", ForeignKey("public.AssetListing.id", ondelete="RESTRICT"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    price_per_unit: Mapped[Decimal] = mapped_column("pricePerUnit", QUANTITY, nullable=False)
    price_currency: Mapped[str | None] = mapped_column("priceCurrency", Text)
    price_source: Mapped[PriceSource | None] = mapped_column("priceSource", PRICE_SOURCE_DB)
    price_timestamp: Mapped[datetime | None] = mapped_column("priceTimestamp", TIMESTAMP)
    value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cost_basis: Mapped[Decimal | None] = mapped_column("costBasis", MONEY)
    allocation_pct: Mapped[Decimal] = mapped_column("allocationPct", PERCENTAGE, nullable=False)
    native_value: Mapped[Decimal | None] = mapped_column("nativeValue", QUANTITY)
    value_currency: Mapped[str | None] = mapped_column("valueCurrency", Text)
    native_cost_basis: Mapped[Decimal | None] = mapped_column("nativeCostBasis", QUANTITY)
    native_cost_currency: Mapped[str | None] = mapped_column("nativeCostCurrency", Text)
    price_evidence: Mapped[dict[str, Any] | None] = mapped_column(
        "priceEvidence", JSONB(none_as_null=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class PortfolioSnapshotModel(Base):
    """Immutable user-specific aggregate of authorized investment account snapshots."""

    __tablename__ = "PortfolioSnapshot"
    __table_args__ = (
        UniqueConstraint(
            "userId",
            "timestamp",
            "currency",
            "granularity",
            "generationId",
            name="PortfolioSnapshot_coordinate_generation_key",
        ),
        UniqueConstraint(
            "id", "generationId", "userId", name="PortfolioSnapshot_id_generation_user_key"
        ),
        ForeignKeyConstraint(
            ("generationId", "userId"),
            (
                "public.SnapshotGenerationTarget.generationId",
                "public.SnapshotGenerationTarget.userId",
            ),
            name="PortfolioSnapshot_generation_target_fkey",
            ondelete="RESTRICT",
        ),
        Index(
            "PortfolioSnapshot_generation_user_timestamp_idx",
            "generationId",
            "userId",
            "timestamp",
        ),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "userId", ForeignKey("public.User.id", ondelete="RESTRICT"), nullable=False
    )
    generation_id: Mapped[str] = mapped_column("generationId", Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    valuation_timestamp: Mapped[datetime] = mapped_column(
        "valuationTimestamp", TIMESTAMP, nullable=False
    )
    granularity: Mapped[SnapshotGranularity] = mapped_column(
        SNAPSHOT_GRANULARITY_DB, nullable=False
    )
    source: Mapped[SnapshotSource] = mapped_column(SNAPSHOT_SOURCE_DB, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    cash_value: Mapped[Decimal] = mapped_column("cashValue", MONEY, nullable=False)
    investment_value: Mapped[Decimal] = mapped_column("investmentValue", MONEY, nullable=False)
    investment_cost_basis: Mapped[Decimal | None] = mapped_column("investmentCostBasis", MONEY)
    net_deposits_value: Mapped[Decimal | None] = mapped_column("netDepositsValue", MONEY)
    realized_pnl_value: Mapped[Decimal | None] = mapped_column("realizedPnlValue", MONEY)
    unrealized_pnl_value: Mapped[Decimal | None] = mapped_column("unrealizedPnlValue", MONEY)
    fees_value: Mapped[Decimal] = mapped_column(
        "feesValue", MONEY, nullable=False, server_default=text("0")
    )
    taxes_value: Mapped[Decimal] = mapped_column(
        "taxesValue", MONEY, nullable=False, server_default=text("0")
    )
    cash_value_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "cashValueByCurrency", JSONB(none_as_null=True)
    )
    investment_value_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "investmentValueByCurrency", JSONB(none_as_null=True)
    )
    investment_cost_basis_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "investmentCostBasisByCurrency", JSONB(none_as_null=True)
    )
    net_deposits_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "netDepositsByCurrency", JSONB(none_as_null=True)
    )
    realized_pnl_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "realizedPnlByCurrency", JSONB(none_as_null=True)
    )
    unrealized_pnl_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "unrealizedPnlByCurrency", JSONB(none_as_null=True)
    )
    fees_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "feesByCurrency", JSONB(none_as_null=True)
    )
    taxes_by_currency: Mapped[dict[str, Any] | None] = mapped_column(
        "taxesByCurrency", JSONB(none_as_null=True)
    )
    price_evidence: Mapped[dict[str, Any] | None] = mapped_column(
        "priceEvidence", JSONB(none_as_null=True)
    )
    exchange_rates: Mapped[dict[str, Any] | None] = mapped_column(
        "exchangeRates", JSONB(none_as_null=True)
    )
    calculated_at: Mapped[datetime] = mapped_column(
        "calculatedAt", TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    calculation_version: Mapped[int] = mapped_column(
        "calculationVersion", Integer, nullable=False, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class PortfolioSnapshotInputModel(Base):
    """An authorized investment-account input used for one portfolio projection."""

    __tablename__ = "PortfolioSnapshotInput"
    __table_args__ = (
        UniqueConstraint(
            "portfolioSnapshotId",
            "investmentAccountSnapshotId",
            "accountSnapshotId",
            "generationId",
            "userId",
            "accountId",
            name="PortfolioSnapshotInput_coordinate_key",
        ),
        ForeignKeyConstraint(
            ("portfolioSnapshotId", "generationId", "userId"),
            (
                "public.PortfolioSnapshot.id",
                "public.PortfolioSnapshot.generationId",
                "public.PortfolioSnapshot.userId",
            ),
            name="PortfolioSnapshotInput_portfolio_generation_user_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            (
                "investmentAccountSnapshotId",
                "accountSnapshotId",
                "generationId",
                "accountId",
            ),
            (
                "public.InvestmentAccountSnapshot.id",
                "public.InvestmentAccountSnapshot.accountSnapshotId",
                "public.InvestmentAccountSnapshot.generationId",
                "public.InvestmentAccountSnapshot.accountId",
            ),
            name="PortfolioSnapshotInput_investment_generation_account_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("accountSnapshotId", "generationId", "accountId"),
            (
                "public.AccountSnapshot.id",
                "public.AccountSnapshot.generationId",
                "public.AccountSnapshot.accountId",
            ),
            name="PortfolioSnapshotInput_account_snapshot_generation_fkey",
            ondelete="RESTRICT",
        ),
        {"schema": "public"},
    )

    portfolio_snapshot_id: Mapped[str] = mapped_column(
        "portfolioSnapshotId", Text, primary_key=True
    )
    investment_account_snapshot_id: Mapped[str] = mapped_column(
        "investmentAccountSnapshotId", Text, primary_key=True
    )
    account_snapshot_id: Mapped[str] = mapped_column("accountSnapshotId", Text, nullable=False)
    generation_id: Mapped[str] = mapped_column("generationId", Text, nullable=False)
    user_id: Mapped[str] = mapped_column("userId", Text, nullable=False)
    account_id: Mapped[str] = mapped_column("accountId", Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class PortfolioSnapshotItemModel(Base):
    __tablename__ = "PortfolioSnapshotItem"
    __table_args__ = (
        UniqueConstraint(
            "portfolioSnapshotId",
            "listingId",
            name="PortfolioSnapshotItem_snapshot_listing_key",
        ),
        UniqueConstraint(
            "id",
            "portfolioSnapshotId",
            "generationId",
            "userId",
            "listingId",
            name="PortfolioSnapshotItem_identity_key",
        ),
        ForeignKeyConstraint(
            ("portfolioSnapshotId", "generationId", "userId"),
            (
                "public.PortfolioSnapshot.id",
                "public.PortfolioSnapshot.generationId",
                "public.PortfolioSnapshot.userId",
            ),
            name="PortfolioSnapshotItem_snapshot_generation_user_fkey",
            ondelete="CASCADE",
        ),
        Index(None, "listingId"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    portfolio_snapshot_id: Mapped[str] = mapped_column("portfolioSnapshotId", Text, nullable=False)
    generation_id: Mapped[str] = mapped_column("generationId", Text, nullable=False)
    user_id: Mapped[str] = mapped_column("userId", Text, nullable=False)
    asset_id: Mapped[str | None] = mapped_column(
        "assetId", ForeignKey("public.Asset.id", ondelete="SET NULL")
    )
    listing_id: Mapped[str] = mapped_column(
        "listingId", ForeignKey("public.AssetListing.id", ondelete="RESTRICT"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    price_per_unit: Mapped[Decimal] = mapped_column("pricePerUnit", QUANTITY, nullable=False)
    price_currency: Mapped[str | None] = mapped_column("priceCurrency", Text)
    price_source: Mapped[PriceSource | None] = mapped_column("priceSource", PRICE_SOURCE_DB)
    price_timestamp: Mapped[datetime | None] = mapped_column("priceTimestamp", TIMESTAMP)
    value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cost_basis: Mapped[Decimal | None] = mapped_column("costBasis", MONEY)
    allocation_pct: Mapped[Decimal] = mapped_column("allocationPct", PERCENTAGE, nullable=False)
    native_value: Mapped[Decimal | None] = mapped_column("nativeValue", QUANTITY)
    value_currency: Mapped[str | None] = mapped_column("valueCurrency", Text)
    native_cost_basis: Mapped[Decimal | None] = mapped_column("nativeCostBasis", QUANTITY)
    native_cost_currency: Mapped[str | None] = mapped_column("nativeCostCurrency", Text)
    price_evidence: Mapped[dict[str, Any] | None] = mapped_column(
        "priceEvidence", JSONB(none_as_null=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class PortfolioSnapshotItemAccountModel(Base):
    """Per-account contribution to one aggregate portfolio listing position."""

    __tablename__ = "PortfolioSnapshotItemAccount"
    __table_args__ = (
        ForeignKeyConstraint(
            (
                "portfolioSnapshotId",
                "investmentAccountSnapshotId",
                "accountSnapshotId",
                "generationId",
                "userId",
                "accountId",
            ),
            (
                "public.PortfolioSnapshotInput.portfolioSnapshotId",
                "public.PortfolioSnapshotInput.investmentAccountSnapshotId",
                "public.PortfolioSnapshotInput.accountSnapshotId",
                "public.PortfolioSnapshotInput.generationId",
                "public.PortfolioSnapshotInput.userId",
                "public.PortfolioSnapshotInput.accountId",
            ),
            name="PortfolioSnapshotItemAccount_input_coordinate_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            (
                "portfolioSnapshotItemId",
                "portfolioSnapshotId",
                "generationId",
                "userId",
                "listingId",
            ),
            (
                "public.PortfolioSnapshotItem.id",
                "public.PortfolioSnapshotItem.portfolioSnapshotId",
                "public.PortfolioSnapshotItem.generationId",
                "public.PortfolioSnapshotItem.userId",
                "public.PortfolioSnapshotItem.listingId",
            ),
            name="PortfolioSnapshotItemAccount_item_coordinate_fkey",
            ondelete="CASCADE",
        ),
        {"schema": "public"},
    )

    portfolio_snapshot_item_id: Mapped[str] = mapped_column(
        "portfolioSnapshotItemId", Text, primary_key=True
    )
    account_id: Mapped[str] = mapped_column("accountId", Text, primary_key=True)
    portfolio_snapshot_id: Mapped[str] = mapped_column("portfolioSnapshotId", Text, nullable=False)
    investment_account_snapshot_id: Mapped[str] = mapped_column(
        "investmentAccountSnapshotId", Text, nullable=False
    )
    account_snapshot_id: Mapped[str] = mapped_column("accountSnapshotId", Text, nullable=False)
    generation_id: Mapped[str] = mapped_column("generationId", Text, nullable=False)
    user_id: Mapped[str] = mapped_column("userId", Text, nullable=False)
    listing_id: Mapped[str] = mapped_column("listingId", Text, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cost_basis: Mapped[Decimal | None] = mapped_column("costBasis", MONEY)
    allocation_pct: Mapped[Decimal] = mapped_column("allocationPct", PERCENTAGE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
