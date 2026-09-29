from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.shared.numeric_serialization import serialize_money, serialize_percentage


class OperationalSummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_month_income_czk: Decimal = Field(serialization_alias="currentMonthIncomeCzk")
    current_month_expense_czk: Decimal = Field(serialization_alias="currentMonthExpenseCzk")
    current_month_net_czk: Decimal = Field(serialization_alias="currentMonthNetCzk")

    @field_serializer(
        "current_month_income_czk", "current_month_expense_czk", "current_month_net_czk"
    )
    def serialize_money_value(self, value: Decimal) -> str:
        return serialize_money(value)


class OperationalBudgetItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    category_id: str = Field(serialization_alias="categoryId")
    name: str
    icon: str | None
    color: str | None
    limit_czk: Decimal = Field(serialization_alias="limitCzk")
    spent_czk: Decimal = Field(serialization_alias="spentCzk")
    remaining_czk: Decimal = Field(serialization_alias="remainingCzk")
    progress_pct: Decimal = Field(serialization_alias="progressPct")
    is_over: bool = Field(serialization_alias="isOver")

    @field_serializer("limit_czk", "spent_czk", "remaining_czk")
    def serialize_money_value(self, value: Decimal) -> str:
        return serialize_money(value)

    @field_serializer("progress_pct")
    def serialize_percentage_value(self, value: Decimal) -> str:
        return serialize_percentage(value)


class OperationalBudgetResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    month: int
    year: int
    limit_czk: Decimal = Field(serialization_alias="limitCzk")
    spent_czk: Decimal = Field(serialization_alias="spentCzk")
    remaining_czk: Decimal = Field(serialization_alias="remainingCzk")
    progress_pct: Decimal = Field(serialization_alias="progressPct")
    items: list[OperationalBudgetItemResponse]

    @field_serializer("limit_czk", "spent_czk", "remaining_czk")
    def serialize_money_value(self, value: Decimal) -> str:
        return serialize_money(value)

    @field_serializer("progress_pct")
    def serialize_percentage_value(self, value: Decimal) -> str:
        return serialize_percentage(value)


class OperationalExpenseCategoryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category_id: str | None = Field(serialization_alias="categoryId")
    name: str
    icon: str | None
    color: str | None
    amount_czk: Decimal = Field(serialization_alias="amountCzk")

    @field_serializer("amount_czk")
    def serialize_money_value(self, value: Decimal) -> str:
        return serialize_money(value)


class OperationalMonthlyTrendResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    month: str
    label: str
    income_czk: Decimal = Field(serialization_alias="incomeCzk")
    expense_czk: Decimal = Field(serialization_alias="expenseCzk")
    net_czk: Decimal = Field(serialization_alias="netCzk")

    @field_serializer("income_czk", "expense_czk", "net_czk")
    def serialize_money_value(self, value: Decimal) -> str:
        return serialize_money(value)


class OperationalRecentTransactionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    date: datetime
    amount: Decimal
    amount_czk: Decimal = Field(serialization_alias="amountCzk")
    currency: str
    type: str
    description: str | None
    counterparty: str | None
    account_name: str = Field(serialization_alias="accountName")
    category_name: str | None = Field(serialization_alias="categoryName")
    category_icon: str | None = Field(serialization_alias="categoryIcon")

    @field_serializer("amount", "amount_czk")
    def serialize_money_value(self, value: Decimal) -> str:
        return serialize_money(value)


class OperationalDashboardResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    summary: OperationalSummaryResponse
    budget: OperationalBudgetResponse | None
    expense_by_category: list[OperationalExpenseCategoryResponse] = Field(
        serialization_alias="expenseByCategory"
    )
    monthly_trends: list[OperationalMonthlyTrendResponse] = Field(
        serialization_alias="monthlyTrends"
    )
    recent_transactions: list[OperationalRecentTransactionResponse] = Field(
        serialization_alias="recentTransactions"
    )
