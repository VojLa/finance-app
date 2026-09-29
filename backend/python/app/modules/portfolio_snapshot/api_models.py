"""Public response contracts for an exact portfolio snapshot view."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.modules.portfolio_snapshot.models import (
    AccountType,
    AssetType,
    SnapshotGranularity,
    SnapshotSource,
)
from app.shared.numeric_serialization import (
    serialize_money,
    serialize_percentage,
    serialize_quantity,
)

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    populate_by_name=True,
    from_attributes=True,
)


class PortfolioSnapshotAccountResponse(BaseModel):
    model_config = _MODEL_CONFIG

    account_id: str = Field(serialization_alias="accountId")
    name: str
    account_type: AccountType = Field(serialization_alias="accountType")
    currency: str


class PortfolioCurrencyAmountResponse(BaseModel):
    model_config = _MODEL_CONFIG

    currency: str
    amount: Decimal

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return serialize_money(value)


class PortfolioQuantityCurrencyAmountResponse(BaseModel):
    model_config = _MODEL_CONFIG

    currency: str
    amount: Decimal

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return serialize_quantity(value)


class PortfolioSnapshotSummaryResponse(BaseModel):
    model_config = _MODEL_CONFIG

    cash_value: Decimal = Field(serialization_alias="cashValue")
    cash_by_currency: tuple[PortfolioCurrencyAmountResponse, ...] = Field(
        serialization_alias="cashByCurrency"
    )
    investment_value: Decimal = Field(serialization_alias="investmentValue")
    investment_cost_basis: Decimal | None = Field(serialization_alias="investmentCostBasis")
    liabilities_value: Decimal = Field(serialization_alias="liabilitiesValue")
    total_value: Decimal = Field(serialization_alias="totalValue")
    net_deposits_value: Decimal | None = Field(serialization_alias="netDepositsValue")
    net_deposits_by_currency: tuple[PortfolioCurrencyAmountResponse, ...] | None = Field(
        serialization_alias="netDepositsByCurrency"
    )
    realized_pnl_value: Decimal | None = Field(serialization_alias="realizedPnlValue")
    unrealized_pnl_value: Decimal | None = Field(serialization_alias="unrealizedPnlValue")
    fees_value: Decimal = Field(serialization_alias="feesValue")
    taxes_value: Decimal = Field(serialization_alias="taxesValue")
    position_count: int = Field(serialization_alias="positionCount")

    @field_serializer(
        "cash_value",
        "investment_value",
        "investment_cost_basis",
        "liabilities_value",
        "total_value",
        "net_deposits_value",
        "realized_pnl_value",
        "unrealized_pnl_value",
        "fees_value",
        "taxes_value",
    )
    def serialize_decimal(self, value: Decimal | None) -> str | None:
        return None if value is None else serialize_money(value)


class PortfolioSnapshotPositionResponse(BaseModel):
    model_config = _MODEL_CONFIG

    listing_id: str = Field(serialization_alias="listingId")
    asset_id: str = Field(serialization_alias="assetId")
    symbol: str
    name: str
    asset_type: AssetType = Field(serialization_alias="assetType")
    quantity: Decimal
    price_per_unit: Decimal = Field(serialization_alias="pricePerUnit")
    price_currency: str = Field(serialization_alias="priceCurrency")
    price_timestamp: datetime = Field(serialization_alias="priceTimestamp")
    value: Decimal
    value_currency: str = Field(serialization_alias="valueCurrency")
    cost_basis: Decimal | None = Field(serialization_alias="costBasis")
    cost_currency: str | None = Field(serialization_alias="costCurrency")
    unrealized_pnl: Decimal | None = Field(serialization_alias="unrealizedPnl")
    allocation_pct: Decimal = Field(serialization_alias="allocationPct")
    native_value: Decimal = Field(serialization_alias="nativeValue")
    native_value_currency: str = Field(serialization_alias="nativeValueCurrency")
    native_cost_basis: Decimal | None = Field(serialization_alias="nativeCostBasis")
    native_cost_currency: str | None = Field(serialization_alias="nativeCostCurrency")
    native_cost_basis_by_currency: tuple[PortfolioQuantityCurrencyAmountResponse, ...] | None = (
        Field(serialization_alias="nativeCostBasisByCurrency")
    )

    @field_serializer(
        "quantity",
        "price_per_unit",
        "cost_basis",
        "unrealized_pnl",
        "native_value",
        "native_cost_basis",
    )
    def serialize_quantity(self, value: Decimal | None) -> str | None:
        return None if value is None else serialize_quantity(value)

    @field_serializer("value")
    def serialize_money(self, value: Decimal) -> str:
        return serialize_money(value)

    @field_serializer("allocation_pct")
    def serialize_percentage(self, value: Decimal) -> str:
        return serialize_percentage(value)

    @field_serializer("price_timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")


class PortfolioSnapshotResponse(BaseModel):
    model_config = _MODEL_CONFIG

    snapshot_id: str = Field(serialization_alias="snapshotId")
    account: PortfolioSnapshotAccountResponse
    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    source: SnapshotSource
    calculation_version: int = Field(serialization_alias="calculationVersion")
    summary: PortfolioSnapshotSummaryResponse
    positions: tuple[PortfolioSnapshotPositionResponse, ...]

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")
