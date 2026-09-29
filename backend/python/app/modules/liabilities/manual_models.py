"""Public contracts for explicit, manually entered liability observations."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.modules.liabilities.validation import (
    LiabilityBalanceValidationError,
    canonical_currency,
    canonical_money,
    canonical_timestamp,
)


def _exact_decimal(value: object) -> Decimal:
    # JSON numbers pass through a binary float before Decimal sees them.  Manual
    # financial input therefore has one explicit transport representation: text.
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("Amounts must be exact decimal strings.")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Amounts must be exact decimal strings.") from exc


class ManualLiabilityBalanceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=False)

    effective_at: datetime = Field(alias="effectiveAt")
    currency: str
    outstanding_principal: Decimal = Field(alias="outstandingPrincipal")
    accrued_interest: Decimal = Field(alias="accruedInterest")
    fees_outstanding: Decimal = Field(alias="feesOutstanding")

    @field_validator("effective_at", mode="before")
    @classmethod
    def require_timestamp_text(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("Effective timestamp must be an ISO timestamp string.")
        return value

    @field_validator("effective_at")
    @classmethod
    def validate_effective_at(cls, value: datetime) -> datetime:
        try:
            return canonical_timestamp(value)
        except LiabilityBalanceValidationError as exc:
            raise ValueError("Effective timestamp must be a millisecond naive timestamp.") from exc

    @field_validator("currency", mode="before")
    @classmethod
    def validate_currency(cls, value: object) -> str:
        try:
            return canonical_currency(value)
        except LiabilityBalanceValidationError as exc:
            raise ValueError("Currency must be a three-letter uppercase code.") from exc

    @field_validator(
        "outstanding_principal",
        "accrued_interest",
        "fees_outstanding",
        mode="before",
    )
    @classmethod
    def require_exact_amount(cls, value: object) -> Decimal:
        return _exact_decimal(value)

    @field_validator("outstanding_principal", "accrued_interest", "fees_outstanding")
    @classmethod
    def validate_nonnegative_money(cls, value: Decimal) -> Decimal:
        try:
            result = canonical_money(value)
        except LiabilityBalanceValidationError as exc:
            raise ValueError("Amount must be an exact six-decimal nonnegative value.") from exc
        if result < 0:
            raise ValueError("Amount must be nonnegative.")
        return result


class ManualLiabilityBalanceCreateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    balance_id: str = Field(serialization_alias="balanceId")
    account_id: str = Field(serialization_alias="accountId")
    effective_at: datetime = Field(serialization_alias="effectiveAt")
    currency: str
    total_outstanding: Decimal = Field(serialization_alias="totalOutstanding")
    source: Literal["manual"]
    status: Literal["created", "replayed"]

    @field_serializer("effective_at")
    def serialize_effective_at(self, value: datetime) -> str:
        return value.isoformat(timespec="milliseconds")

    @field_serializer("total_outstanding")
    def serialize_total_outstanding(self, value: Decimal) -> str:
        return format(value, ".6f")
