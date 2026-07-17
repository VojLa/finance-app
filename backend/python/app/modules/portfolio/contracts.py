from decimal import Decimal
from typing import TypedDict


class AccountRow(TypedDict):
    id: str
    name: str
    type: str
    currency: str


class HoldingRow(TypedDict):
    id: str
    account_id: str
    account_name: str
    account_currency: str
    symbol: str
    name: str | None
    asset_type: str
    quantity: Decimal
    avg_buy_price: Decimal
    currency: str
    listing_id: str
