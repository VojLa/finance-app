"""Public API models for snapshot-backed portfolio history."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.modules.snapshot_history_contracts import (
    HistoryPublicRange,
    PortfolioHistoryReadState,
)
from app.shared.numeric_serialization import serialize_money, serialize_native_money

_MODEL_CONFIG = ConfigDict(extra="forbid", populate_by_name=True, from_attributes=True)


class PortfolioHistoryCurrencyAmountResponse(BaseModel):
    model_config = _MODEL_CONFIG

    currency: str
    value: Decimal

    @field_serializer("value")
    def serialize_value(self, value: Decimal) -> str:
        return serialize_native_money(value)


class PortfolioHistoryPositionAccountResponse(BaseModel):
    model_config = _MODEL_CONFIG

    account_id: str = Field(serialization_alias="accountId")
    quantity: Decimal
    value: Decimal
    cost_basis: Decimal | None = Field(default=None, serialization_alias="costBasis")
    allocation_pct: Decimal = Field(serialization_alias="allocationPct")

    @field_serializer("quantity")
    def serialize_quantity(self, value: Decimal) -> str:
        return format(value, "f")

    @field_serializer("value", "cost_basis", when_used="unless-none")
    def serialize_position_money(self, value: Decimal) -> str:
        return serialize_money(value)

    @field_serializer("allocation_pct")
    def serialize_percentage(self, value: Decimal) -> str:
        return format(value, "f")


class PortfolioHistoryPositionResponse(BaseModel):
    model_config = _MODEL_CONFIG

    listing_id: str = Field(serialization_alias="listingId")
    symbol: str
    quantity: Decimal
    value: Decimal
    cost_basis: Decimal | None = Field(default=None, serialization_alias="costBasis")
    allocation_pct: Decimal = Field(serialization_alias="allocationPct")
    accounts: tuple[PortfolioHistoryPositionAccountResponse, ...] = ()

    @field_serializer("quantity")
    def serialize_quantity(self, value: Decimal) -> str:
        return format(value, "f")

    @field_serializer("value", "cost_basis", when_used="unless-none")
    def serialize_position_money(self, value: Decimal) -> str:
        return serialize_money(value)

    @field_serializer("allocation_pct")
    def serialize_percentage(self, value: Decimal) -> str:
        return format(value, "f")


class PortfolioHistoryPointResponse(BaseModel):
    model_config = _MODEL_CONFIG

    timestamp: datetime
    cash_value: Decimal = Field(serialization_alias="cashValue")
    investment_value: Decimal = Field(serialization_alias="investmentValue")
    liabilities_value: Decimal = Field(serialization_alias="liabilitiesValue")
    net_worth_value: Decimal = Field(serialization_alias="netWorthValue")
    net_invested_value: Decimal | None = Field(default=None, serialization_alias="netInvestedValue")
    portfolio_snapshot_id: str | None = Field(
        default=None, serialization_alias="portfolioSnapshotId"
    )
    realized_pnl_value: Decimal | None = Field(default=None, serialization_alias="realizedPnlValue")
    unrealized_pnl_value: Decimal | None = Field(
        default=None, serialization_alias="unrealizedPnlValue"
    )
    cash_by_currency: tuple[PortfolioHistoryCurrencyAmountResponse, ...] | None = Field(
        default=None, serialization_alias="cashByCurrency"
    )
    investment_by_currency: tuple[PortfolioHistoryCurrencyAmountResponse, ...] | None = Field(
        default=None, serialization_alias="investmentByCurrency"
    )
    liabilities_by_currency: tuple[PortfolioHistoryCurrencyAmountResponse, ...] | None = Field(
        default=None, serialization_alias="liabilitiesByCurrency"
    )
    net_invested_by_currency: tuple[PortfolioHistoryCurrencyAmountResponse, ...] | None = Field(
        default=None, serialization_alias="netInvestedByCurrency"
    )
    positions: tuple[PortfolioHistoryPositionResponse, ...] | None = None

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")

    @field_serializer("cash_value", "investment_value", "liabilities_value", "net_worth_value")
    def serialize_money(self, value: Decimal) -> str:
        return serialize_money(value)

    @field_serializer(
        "net_invested_value",
        "realized_pnl_value",
        "unrealized_pnl_value",
        when_used="unless-none",
    )
    def serialize_optional_money(self, value: Decimal) -> str:
        return serialize_money(value)


class GenerationPortfolioHistoryPointResponse(PortfolioHistoryPointResponse):
    resolution_minutes: int = Field(gt=0, serialization_alias="resolutionMinutes")


class PortfolioHistoryCoverageResponse(BaseModel):
    model_config = _MODEL_CONFIG

    resolution_minutes: int = Field(gt=0, serialization_alias="resolutionMinutes")
    start: datetime
    end: datetime

    @field_serializer("start", "end")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")


class PortfolioHistoryResponse(BaseModel):
    model_config = _MODEL_CONFIG

    range: HistoryPublicRange
    state: PortfolioHistoryReadState
    currency: str
    generation_id: str | None = Field(default=None, serialization_alias="generationId")
    publication_version: int | None = Field(
        default=None, gt=0, serialization_alias="publicationVersion"
    )
    covered_through: datetime | None = Field(default=None, serialization_alias="coveredThrough")
    preferred_resolution_minutes: int | None = Field(
        default=None, gt=0, serialization_alias="preferredResolutionMinutes"
    )
    resolutions: tuple[int, ...]
    coverage: tuple[PortfolioHistoryCoverageResponse, ...]
    points: tuple[GenerationPortfolioHistoryPointResponse, ...]
    publication_id: str | None = Field(default=None, serialization_alias="publicationId")
    valuation_timestamp: datetime | None = Field(
        default=None, serialization_alias="valuationTimestamp"
    )
    is_stale: bool | None = Field(default=None, serialization_alias="isStale")

    @field_serializer("covered_through", when_used="unless-none")
    def serialize_covered_through(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")

    @field_serializer("valuation_timestamp", when_used="unless-none")
    def serialize_valuation_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")

    @model_validator(mode="after")
    def validate_state_shape(self) -> PortfolioHistoryResponse:
        metadata = (
            self.generation_id,
            self.publication_version,
            self.covered_through,
            self.preferred_resolution_minutes,
        )
        present = tuple(value is not None for value in metadata)
        if any(present) != all(present):
            raise ValueError("Portfolio history generation metadata is incomplete.")
        has_generation = all(present)
        if not has_generation:
            if (
                self.state is PortfolioHistoryReadState.ready
                or self.resolutions
                or self.coverage
                or self.points
            ):
                raise ValueError("Unpublished history cannot expose generation data.")
            return self
        if self.state is PortfolioHistoryReadState.empty or not self.points:
            raise ValueError("Published portfolio history must contain points.")
        coverage_resolutions = {item.resolution_minutes for item in self.coverage}
        point_resolutions = {item.resolution_minutes for item in self.points}
        if (
            not self.resolutions
            or set(self.resolutions) != coverage_resolutions
            or not point_resolutions <= coverage_resolutions
        ):
            raise ValueError("Published history resolution evidence is incomplete.")
        return self


__all__ = [
    "GenerationPortfolioHistoryPointResponse",
    "PortfolioHistoryCoverageResponse",
    "PortfolioHistoryCurrencyAmountResponse",
    "PortfolioHistoryPointResponse",
    "PortfolioHistoryPositionAccountResponse",
    "PortfolioHistoryPositionResponse",
    "PortfolioHistoryResponse",
]
