from pydantic import BaseModel, Field


class AccountSummary(BaseModel):
    id: str
    name: str
    type: str
    currency: str


class HoldingSummary(BaseModel):
    id: str
    account_id: str
    account_name: str | None
    symbol: str
    name: str | None
    asset_type: str
    quantity: float
    avg_buy_price: float
    currency: str
    listing_id: str | None
    cost_value: float
    cost_value_account_currency: float
    account_currency: str


class PortfolioSummary(BaseModel):
    display_currency: str
    total_cost: float
    accounts: list[AccountSummary]
    holdings: list[HoldingSummary]
    warnings: list[str] = Field(default_factory=list)
