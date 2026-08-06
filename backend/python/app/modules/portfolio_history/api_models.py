"""Public response models for snapshot-backed portfolio history."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.modules.portfolio_history.models import PortfolioHistoryRange

_MODEL_CONFIG = ConfigDict(extra="forbid", populate_by_name=True, from_attributes=True)


class PortfolioHistoryPointResponse(BaseModel):
    model_config = _MODEL_CONFIG

    timestamp: datetime
    cash_value: Decimal = Field(serialization_alias="cashValue")
    investment_value: Decimal = Field(serialization_alias="investmentValue")
    liabilities_value: Decimal = Field(serialization_alias="liabilitiesValue")
    net_worth_value: Decimal = Field(serialization_alias="netWorthValue")

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")

    @field_serializer(
        "cash_value",
        "investment_value",
        "liabilities_value",
        "net_worth_value",
    )
    def serialize_money(self, value: Decimal) -> str:
        return f"{value:.6f}"


class PortfolioHistoryResponse(BaseModel):
    model_config = _MODEL_CONFIG

    range: PortfolioHistoryRange
    currency: str
    points: tuple[PortfolioHistoryPointResponse, ...]
