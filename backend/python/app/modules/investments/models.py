from __future__ import annotations

from datetime import date as Date
from datetime import datetime, time
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.db.models.enums import AssetType
from app.shared.numeric_serialization import serialize_quantity


class ManualInvestmentAction(StrEnum):
    buy = "buy"
    sell = "sell"
    dividend = "dividend"
    interest = "interest"
    staking_reward = "staking_reward"
    deposit = "deposit"
    withdrawal = "withdrawal"
    fee = "fee"
    currency_conversion = "currency_conversion"
    airdrop = "airdrop"


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    result = value.strip()
    return result or None


def _currency(value: str | None) -> str | None:
    if value is None:
        return None
    result = value.strip().upper()
    if len(result) != 3 or not result.isascii() or not result.isalpha():
        raise ValueError("A three-letter currency is required.")
    return result


def _symbol(value: str | None) -> str | None:
    if value is None:
        return None
    result = value.strip().upper()
    if not result or not result.isascii() or len(result) > 64:
        raise ValueError("A valid asset symbol is required.")
    return result


class ManualInvestmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    account_id: str = Field(alias="accountId", min_length=1, max_length=200)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=200)
    date: datetime | Date
    type: ManualInvestmentAction
    symbol: str | None = None
    name: str | None = Field(default=None, max_length=500)
    asset_type: AssetType | None = Field(default=None, alias="assetType")
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=28, decimal_places=10)
    price_per_unit: Decimal | None = Field(
        default=None, alias="pricePerUnit", gt=0, max_digits=28, decimal_places=10
    )
    price_currency: str | None = Field(default=None, alias="priceCurrency")
    total_amount: Decimal | None = Field(
        default=None, alias="totalAmount", gt=0, max_digits=28, decimal_places=10
    )
    total_currency: str | None = Field(default=None, alias="totalCurrency")
    fee: Decimal | None = Field(default=None, gt=0, max_digits=28, decimal_places=10)
    fee_currency: str | None = Field(default=None, alias="feeCurrency")
    conversion_from_amount: Decimal | None = Field(
        default=None,
        alias="conversionFromAmount",
        gt=0,
        max_digits=28,
        decimal_places=10,
    )
    conversion_from_currency: str | None = Field(default=None, alias="conversionFromCurrency")
    conversion_to_amount: Decimal | None = Field(
        default=None,
        alias="conversionToAmount",
        gt=0,
        max_digits=28,
        decimal_places=10,
    )
    conversion_to_currency: str | None = Field(default=None, alias="conversionToCurrency")

    @field_validator("date")
    @classmethod
    def normalize_date(cls, value: datetime | Date) -> datetime:
        result = (
            datetime.combine(value, time.min)
            if isinstance(value, Date) and not isinstance(value, datetime)
            else value
        )
        if result.tzinfo is not None:
            raise ValueError("Investment date must not include a timezone.")
        return result.replace(microsecond=(result.microsecond // 1000) * 1000)

    @field_validator("account_id", "idempotency_key")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("A non-empty value is required.")
        return result

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str | None) -> str | None:
        return _symbol(value)

    @field_validator(
        "price_currency",
        "total_currency",
        "fee_currency",
        "conversion_from_currency",
        "conversion_to_currency",
    )
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return _currency(value)

    @field_validator("name")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def validate_action_shape(self) -> ManualInvestmentCreateRequest:
        asset_required = self.type in {
            ManualInvestmentAction.buy,
            ManualInvestmentAction.sell,
            ManualInvestmentAction.dividend,
            ManualInvestmentAction.staking_reward,
            ManualInvestmentAction.airdrop,
        }
        if asset_required and (self.symbol is None or self.asset_type is None):
            raise ValueError("This action requires an asset symbol and type.")
        if (
            self.type
            in {
                ManualInvestmentAction.buy,
                ManualInvestmentAction.sell,
                ManualInvestmentAction.staking_reward,
                ManualInvestmentAction.airdrop,
            }
            and self.quantity is None
        ):
            raise ValueError("This action requires an asset quantity.")
        if self.type in {
            ManualInvestmentAction.buy,
            ManualInvestmentAction.sell,
            ManualInvestmentAction.dividend,
            ManualInvestmentAction.interest,
            ManualInvestmentAction.fee,
        } and (self.total_amount is None or self.total_currency is None):
            raise ValueError("This action requires a total amount and currency.")
        if self.type in {ManualInvestmentAction.deposit, ManualInvestmentAction.withdrawal}:
            is_asset_transfer = self.symbol is not None
            if is_asset_transfer:
                if (
                    self.asset_type is None
                    or self.quantity is None
                    or self.total_amount is not None
                ):
                    raise ValueError("An asset transfer requires asset fields and no cash total.")
            elif self.total_amount is None or self.total_currency is None:
                raise ValueError("A cash transfer requires a total amount and currency.")
        if self.type is ManualInvestmentAction.currency_conversion and any(
            value is None
            for value in (
                self.conversion_from_amount,
                self.conversion_from_currency,
                self.conversion_to_amount,
                self.conversion_to_currency,
            )
        ):
            raise ValueError("A currency conversion requires both exact legs.")
        if (self.price_per_unit is None) != (self.price_currency is None):
            raise ValueError("Unit price and currency must be supplied together.")
        if (self.total_amount is None) != (self.total_currency is None):
            raise ValueError("Total amount and currency must be supplied together.")
        if (self.fee is None) != (self.fee_currency is None):
            raise ValueError("Fee and currency must be supplied together.")
        if self.type is not ManualInvestmentAction.currency_conversion and any(
            value is not None
            for value in (
                self.conversion_from_amount,
                self.conversion_from_currency,
                self.conversion_to_amount,
                self.conversion_to_currency,
            )
        ):
            raise ValueError("Conversion legs are valid only for currency conversion.")
        if self.type is ManualInvestmentAction.currency_conversion and any(
            value is not None
            for value in (
                self.symbol,
                self.asset_type,
                self.quantity,
                self.price_per_unit,
                self.price_currency,
                self.total_amount,
                self.total_currency,
            )
        ):
            raise ValueError("Currency conversion accepts only its two conversion legs.")
        if self.symbol is None and any(
            value is not None
            for value in (self.asset_type, self.quantity, self.price_per_unit, self.price_currency)
        ):
            raise ValueError("Asset fields require a symbol.")
        if (
            self.symbol is not None
            and self.asset_type is not AssetType.crypto
            and self.price_currency is None
            and self.total_currency is None
        ):
            raise ValueError("A non-crypto asset requires its listing currency.")
        if self.type is ManualInvestmentAction.dividend and any(
            value is not None for value in (self.quantity, self.price_per_unit, self.price_currency)
        ):
            raise ValueError("Dividend uses its linked symbol and exact cash total.")
        if self.type in {ManualInvestmentAction.interest, ManualInvestmentAction.fee} and any(
            value is not None
            for value in (
                self.symbol,
                self.asset_type,
                self.quantity,
                self.price_per_unit,
                self.price_currency,
            )
        ):
            raise ValueError("This cash action does not accept asset fields.")
        if self.type is ManualInvestmentAction.fee and self.fee is not None:
            raise ValueError("A standalone fee uses total amount, not an additional fee.")
        if (
            self.price_currency is not None
            and self.total_currency is not None
            and self.price_currency != self.total_currency
        ):
            raise ValueError("Unit price and total must use the same currency.")
        return self


class ManualInvestmentHoldingResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    created: int
    updated: int
    deleted: int
    total: int
    replayed: bool


class ManualInvestmentSnapshotResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    status: Literal["ready", "unavailable", "conflict"]
    net_worth_snapshot_id: str | None = Field(
        default=None, serialization_alias="netWorthSnapshotId"
    )
    timestamp: datetime | None = None

    @field_serializer("timestamp")
    def serialize_timestamp(self, value: datetime | None) -> str | None:
        return None if value is None else value.isoformat(timespec="milliseconds")


class ManualInvestmentCreateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    event_id: str = Field(serialization_alias="eventId")
    replayed: bool
    holdings: ManualInvestmentHoldingResult
    snapshot: ManualInvestmentSnapshotResult


class SymbolPositionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    account_id: str = Field(serialization_alias="accountId")
    account_name: str = Field(serialization_alias="accountName")
    asset_id: str | None = Field(serialization_alias="assetId")
    listing_id: str = Field(serialization_alias="listingId")
    symbol: str
    name: str | None
    asset_type: AssetType = Field(serialization_alias="assetType")
    quantity: Decimal
    avg_buy_price: Decimal = Field(serialization_alias="avgBuyPrice")
    currency: str
    current_price: Decimal | None = Field(serialization_alias="currentPrice")
    current_value: Decimal | None = Field(serialization_alias="currentValue")
    unrealized_pnl: Decimal | None = Field(serialization_alias="unrealizedPnl")
    realized_pnl: Decimal | None = Field(serialization_alias="realizedPnl")
    calculated_at: datetime = Field(serialization_alias="calculatedAt")

    @field_serializer("quantity", "avg_buy_price")
    def serialize_required_numeric(self, value: Decimal) -> str:
        return serialize_quantity(value)

    @field_serializer(
        "current_price",
        "current_value",
        "unrealized_pnl",
        "realized_pnl",
    )
    def serialize_optional_numeric(self, value: Decimal | None) -> str | None:
        return None if value is None else serialize_quantity(value)

    @field_serializer("calculated_at")
    def serialize_calculated_at(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")


class SymbolEventResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    account_id: str = Field(serialization_alias="accountId")
    account_name: str = Field(serialization_alias="accountName")
    date: datetime
    type: ManualInvestmentAction | Literal["transfer"]
    description: str | None
    quantity: Decimal | None
    price_per_unit: Decimal | None = Field(serialization_alias="pricePerUnit")
    price_currency: str | None = Field(serialization_alias="priceCurrency")
    total_amount: Decimal | None = Field(serialization_alias="totalAmount")
    total_currency: str | None = Field(serialization_alias="totalCurrency")
    fee: Decimal | None
    fee_currency: str | None = Field(serialization_alias="feeCurrency")
    realized_pnl: Decimal | None = Field(serialization_alias="realizedPnl")
    realized_pnl_currency: str | None = Field(serialization_alias="realizedPnlCurrency")

    @field_serializer(
        "quantity",
        "price_per_unit",
        "total_amount",
        "fee",
        "realized_pnl",
    )
    def serialize_numeric(self, value: Decimal | None) -> str | None:
        return None if value is None else serialize_quantity(value)

    @field_serializer("date")
    def serialize_date(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")


class SymbolDetailResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    symbol: str
    positions: list[SymbolPositionResponse]
    events: list[SymbolEventResponse]
