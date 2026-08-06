"""Public request and response contracts for an exact portfolio snapshot set."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.modules.portfolio_snapshot.api_models import (
    PortfolioCurrencyAmountResponse,
    PortfolioSnapshotAccountResponse,
    PortfolioSnapshotPositionResponse,
    PortfolioSnapshotSummaryResponse,
)
from app.modules.portfolio_snapshot.models import SnapshotGranularity, SnapshotSource

_MODEL_CONFIG = ConfigDict(
    extra="forbid",
    populate_by_name=True,
    from_attributes=True,
)


class ExactAccountSnapshotRequest(BaseModel):
    """One explicit account identity and optional snapshot lineage guard."""

    model_config = _MODEL_CONFIG

    account_id: str = Field(alias="accountId")
    snapshot_id: str | None = Field(default=None, alias="snapshotId")


class ExactPortfolioSnapshotSetRequest(BaseModel):
    """Complete explicit selector set shared by portfolio and dashboard APIs."""

    model_config = _MODEL_CONFIG

    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    calculation_version: int = Field(alias="calculationVersion")
    accounts: tuple[ExactAccountSnapshotRequest, ...] = Field(min_length=1)


class MultiAccountPortfolioSummaryResponse(BaseModel):
    model_config = _MODEL_CONFIG

    cash_value: Decimal = Field(serialization_alias="cashValue")
    cash_by_currency: tuple[PortfolioCurrencyAmountResponse, ...] = Field(
        serialization_alias="cashByCurrency"
    )
    investment_value: Decimal = Field(serialization_alias="investmentValue")
    investment_cost_basis: Decimal = Field(serialization_alias="investmentCostBasis")
    liabilities_value: Decimal = Field(serialization_alias="liabilitiesValue")
    total_value: Decimal = Field(serialization_alias="totalValue")
    net_deposits_value: Decimal = Field(serialization_alias="netDepositsValue")
    net_deposits_by_currency: tuple[PortfolioCurrencyAmountResponse, ...] = Field(
        serialization_alias="netDepositsByCurrency"
    )
    realized_pnl_value: Decimal = Field(serialization_alias="realizedPnlValue")
    unrealized_pnl_value: Decimal = Field(serialization_alias="unrealizedPnlValue")
    fees_value: Decimal = Field(serialization_alias="feesValue")
    taxes_value: Decimal = Field(serialization_alias="taxesValue")
    account_count: int = Field(serialization_alias="accountCount")
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
    def serialize_decimal(self, value: Decimal) -> str:
        return format(value, "f")


class MultiAccountPortfolioAccountResponse(BaseModel):
    model_config = _MODEL_CONFIG

    snapshot_id: str = Field(serialization_alias="snapshotId")
    account: PortfolioSnapshotAccountResponse
    source: SnapshotSource
    summary: PortfolioSnapshotSummaryResponse
    positions: tuple[PortfolioSnapshotPositionResponse, ...]


class MultiAccountPortfolioResponse(BaseModel):
    model_config = _MODEL_CONFIG

    timestamp: datetime
    granularity: SnapshotGranularity
    currency: str
    calculation_version: int = Field(serialization_alias="calculationVersion")
    summary: MultiAccountPortfolioSummaryResponse
    accounts: tuple[MultiAccountPortfolioAccountResponse, ...]

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")
