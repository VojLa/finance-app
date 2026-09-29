"""Public response contracts for one exact dashboard snapshot."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.modules.portfolio_snapshot.models import (
    AccountType,
    AssetType,
    SnapshotGranularity,
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


class DashboardSnapshotSummaryResponse(BaseModel):
    model_config = _MODEL_CONFIG

    total_value: Decimal = Field(serialization_alias="totalValue")
    assets_value: Decimal = Field(serialization_alias="assetsValue")
    liabilities_value: Decimal = Field(serialization_alias="liabilitiesValue")
    cash_value: Decimal = Field(serialization_alias="cashValue")
    investment_value: Decimal = Field(serialization_alias="investmentValue")
    investment_cost_basis: Decimal | None = Field(serialization_alias="investmentCostBasis")
    unrealized_pnl_value: Decimal | None = Field(serialization_alias="unrealizedPnlValue")
    realized_pnl_value: Decimal | None = Field(serialization_alias="realizedPnlValue")
    net_deposits_value: Decimal | None = Field(serialization_alias="netDepositsValue")
    fees_value: Decimal = Field(serialization_alias="feesValue")
    taxes_value: Decimal = Field(serialization_alias="taxesValue")
    account_count: int = Field(serialization_alias="accountCount")
    investment_account_count: int = Field(serialization_alias="investmentAccountCount")
    liability_account_count: int = Field(serialization_alias="liabilityAccountCount")
    position_count: int = Field(serialization_alias="positionCount")

    @field_serializer(
        "total_value",
        "assets_value",
        "liabilities_value",
        "cash_value",
        "investment_value",
        "investment_cost_basis",
        "unrealized_pnl_value",
        "realized_pnl_value",
        "net_deposits_value",
        "fees_value",
        "taxes_value",
    )
    def serialize_decimal(self, value: Decimal | None) -> str | None:
        return None if value is None else serialize_money(value)


class DashboardAccountCardResponse(BaseModel):
    model_config = _MODEL_CONFIG

    account_id: str = Field(serialization_alias="accountId")
    snapshot_id: str = Field(serialization_alias="snapshotId")
    primary_snapshot_id: str = Field(serialization_alias="primarySnapshotId")
    name: str
    account_type: AccountType = Field(serialization_alias="accountType")
    account_currency: str = Field(serialization_alias="accountCurrency")
    output_currency: str = Field(serialization_alias="outputCurrency")
    total_value: Decimal = Field(serialization_alias="totalValue")
    cash_value: Decimal = Field(serialization_alias="cashValue")
    investment_value: Decimal = Field(serialization_alias="investmentValue")
    liabilities_value: Decimal = Field(serialization_alias="liabilitiesValue")
    net_deposits_value: Decimal | None = Field(serialization_alias="netDepositsValue")
    unrealized_pnl_value: Decimal | None = Field(serialization_alias="unrealizedPnlValue")
    position_count: int = Field(serialization_alias="positionCount")

    @field_serializer(
        "total_value",
        "cash_value",
        "investment_value",
        "liabilities_value",
        "net_deposits_value",
        "unrealized_pnl_value",
    )
    def serialize_decimal(self, value: Decimal | None) -> str | None:
        return None if value is None else serialize_money(value)


class DashboardAssetTypeAllocationResponse(BaseModel):
    model_config = _MODEL_CONFIG

    asset_type: AssetType = Field(serialization_alias="assetType")
    value: Decimal
    allocation_pct: Decimal = Field(serialization_alias="allocationPct")
    position_count: int = Field(serialization_alias="positionCount")
    account_count: int = Field(serialization_alias="accountCount")

    @field_serializer("value")
    def serialize_money(self, value: Decimal) -> str:
        return serialize_money(value)

    @field_serializer("allocation_pct")
    def serialize_percentage(self, value: Decimal) -> str:
        return serialize_percentage(value)


class DashboardTopPositionResponse(BaseModel):
    model_config = _MODEL_CONFIG

    account_id: str = Field(serialization_alias="accountId")
    listing_id: str = Field(serialization_alias="listingId")
    asset_id: str = Field(serialization_alias="assetId")
    symbol: str
    name: str
    asset_type: AssetType = Field(serialization_alias="assetType")
    value: Decimal
    value_currency: str = Field(serialization_alias="valueCurrency")
    unrealized_pnl: Decimal | None = Field(serialization_alias="unrealizedPnl")
    allocation_pct: Decimal = Field(serialization_alias="allocationPct")

    @field_serializer("value")
    def serialize_money(self, value: Decimal) -> str:
        return serialize_money(value)

    @field_serializer("unrealized_pnl")
    def serialize_quantity(self, value: Decimal | None) -> str | None:
        return None if value is None else serialize_quantity(value)

    @field_serializer("allocation_pct")
    def serialize_percentage(self, value: Decimal) -> str:
        return serialize_percentage(value)


class DashboardSnapshotResponse(BaseModel):
    model_config = _MODEL_CONFIG

    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    calculation_version: int = Field(serialization_alias="calculationVersion")
    summary: DashboardSnapshotSummaryResponse
    accounts: tuple[DashboardAccountCardResponse, ...]
    asset_type_allocations: tuple[DashboardAssetTypeAllocationResponse, ...] = Field(
        serialization_alias="assetTypeAllocations"
    )
    top_positions: tuple[DashboardTopPositionResponse, ...] = Field(
        serialization_alias="topPositions"
    )

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")
