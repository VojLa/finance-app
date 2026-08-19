"""Public exact-string contracts for ephemeral current portfolio/dashboard reads."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.modules.dashboard_snapshot.api_models import (
    DashboardAssetTypeAllocationResponse,
    DashboardSnapshotSummaryResponse,
    DashboardTopPositionResponse,
)
from app.modules.portfolio_snapshot.api_models import (
    PortfolioSnapshotAccountResponse,
    PortfolioSnapshotPositionResponse,
    PortfolioSnapshotSummaryResponse,
)
from app.modules.portfolio_snapshot.models import AccountType
from app.modules.portfolio_snapshot.multi_account_api_models import (
    MultiAccountPortfolioAggregatePositionResponse,
    MultiAccountPortfolioSummaryResponse,
)
from app.shared.numeric_serialization import serialize_money

_CONFIG = ConfigDict(extra="forbid", populate_by_name=True, from_attributes=True)


class CurrentPortfolioAccountResponse(BaseModel):
    model_config = _CONFIG

    baseline_snapshot_id: str = Field(serialization_alias="baselineSnapshotId")
    primary_baseline_snapshot_id: str = Field(serialization_alias="primaryBaselineSnapshotId")
    currency: str
    account: PortfolioSnapshotAccountResponse
    summary: PortfolioSnapshotSummaryResponse
    positions: tuple[PortfolioSnapshotPositionResponse, ...]


class CurrentPortfolioResponse(BaseModel):
    model_config = _CONFIG

    as_of: datetime = Field(serialization_alias="asOf")
    baseline_timestamp: datetime = Field(serialization_alias="baselineTimestamp")
    history_anchor_snapshot_id: str = Field(serialization_alias="historyAnchorSnapshotId")
    currency: str
    calculation_version: int = Field(serialization_alias="calculationVersion")
    summary: MultiAccountPortfolioSummaryResponse
    accounts: tuple[CurrentPortfolioAccountResponse, ...]
    aggregate_positions: tuple[MultiAccountPortfolioAggregatePositionResponse, ...] = Field(
        serialization_alias="aggregatePositions"
    )

    @field_serializer("as_of", "baseline_timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")


class CurrentDashboardAccountResponse(BaseModel):
    model_config = _CONFIG

    account_id: str = Field(serialization_alias="accountId")
    baseline_snapshot_id: str = Field(serialization_alias="baselineSnapshotId")
    primary_baseline_snapshot_id: str = Field(serialization_alias="primaryBaselineSnapshotId")
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


class CurrentDashboardResponse(BaseModel):
    model_config = _CONFIG

    as_of: datetime = Field(serialization_alias="asOf")
    baseline_timestamp: datetime = Field(serialization_alias="baselineTimestamp")
    history_anchor_snapshot_id: str = Field(serialization_alias="historyAnchorSnapshotId")
    currency: str
    calculation_version: int = Field(serialization_alias="calculationVersion")
    summary: DashboardSnapshotSummaryResponse
    accounts: tuple[CurrentDashboardAccountResponse, ...]
    asset_type_allocations: tuple[DashboardAssetTypeAllocationResponse, ...] = Field(
        serialization_alias="assetTypeAllocations"
    )
    top_positions: tuple[DashboardTopPositionResponse, ...] = Field(
        serialization_alias="topPositions"
    )

    @field_serializer("as_of", "baseline_timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")
