from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.shared.numeric_serialization import serialize_money, serialize_percentage


class BudgetSaveItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    category_id: str = Field(alias="categoryId", min_length=1, max_length=200)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    currency: str = "CZK"

    @field_validator("category_id")
    @classmethod
    def normalize_category_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Category ID is required.")
        return normalized

    @field_validator("currency")
    @classmethod
    def require_czk(cls, value: str) -> str:
        if value.strip().upper() != "CZK":
            raise ValueError("Version 0.1 budgets require CZK.")
        return "CZK"


class BudgetSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    month: int = Field(ge=1, le=12)
    year: int = Field(ge=1970, le=9999)
    rollover: bool = False
    items: list[BudgetSaveItemRequest] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def unique_categories(self) -> BudgetSaveRequest:
        category_ids = [item.category_id for item in self.items]
        if len(category_ids) != len(set(category_ids)):
            raise ValueError("A category may occur only once in a monthly budget.")
        return self


class BudgetCategoryResponse(BaseModel):
    id: str
    name: str
    icon: str | None
    color: str | None


class BudgetProgressItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    amount: Decimal
    rollover_amount: Decimal = Field(serialization_alias="rolloverAmount")
    effective_amount: Decimal = Field(serialization_alias="effectiveAmount")
    spent: Decimal
    remaining: Decimal
    progress_pct: Decimal = Field(serialization_alias="progressPct")
    is_approaching: bool = Field(serialization_alias="isApproaching")
    is_over: bool = Field(serialization_alias="isOver")
    currency: str
    category_id: str = Field(serialization_alias="categoryId")
    category: BudgetCategoryResponse

    @field_serializer("amount", "rollover_amount", "effective_amount", "spent", "remaining")
    def serialize_money_value(self, value: Decimal) -> str:
        return serialize_money(value)

    @field_serializer("progress_pct")
    def serialize_percentage_value(self, value: Decimal) -> str:
        return serialize_percentage(value)


class BudgetAlertResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    type: str
    category_id: str = Field(serialization_alias="categoryId")
    category_name: str = Field(serialization_alias="categoryName")
    threshold: Decimal
    triggered_at: datetime = Field(serialization_alias="triggeredAt")
    acknowledged_at: datetime | None = Field(default=None, serialization_alias="acknowledgedAt")

    @field_serializer("threshold")
    def serialize_threshold(self, value: Decimal) -> str:
        return format(value, ".4f")


class BudgetProgressResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    month: int
    year: int
    period_type: str = Field(serialization_alias="periodType")
    currency: str
    rollover: bool
    account_ids: list[str] = Field(serialization_alias="accountIds")
    total_limit: Decimal = Field(serialization_alias="totalLimit")
    total_base_limit: Decimal = Field(serialization_alias="totalBaseLimit")
    total_rollover: Decimal = Field(serialization_alias="totalRollover")
    total_spent: Decimal = Field(serialization_alias="totalSpent")
    total_remaining: Decimal = Field(serialization_alias="totalRemaining")
    progress_pct: Decimal = Field(serialization_alias="progressPct")
    is_over: bool = Field(serialization_alias="isOver")
    alerts: list[BudgetAlertResponse]
    items: list[BudgetProgressItemResponse]

    @field_serializer(
        "total_limit",
        "total_base_limit",
        "total_rollover",
        "total_spent",
        "total_remaining",
    )
    def serialize_money_value(self, value: Decimal) -> str:
        return serialize_money(value)

    @field_serializer("progress_pct")
    def serialize_percentage_value(self, value: Decimal) -> str:
        return serialize_percentage(value)
