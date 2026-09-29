from __future__ import annotations

from datetime import date as Date
from datetime import datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.db.models.enums import CategoryType, TransactionType


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _timestamp(value: datetime | Date) -> datetime:
    result = (
        datetime.combine(value, time.min)
        if isinstance(value, Date) and not isinstance(value, datetime)
        else value
    )
    if result.tzinfo is not None:
        raise ValueError("Transaction date must not include a timezone.")
    return result.replace(microsecond=(result.microsecond // 1000) * 1000)


def _currency(value: str) -> str:
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isascii() or not normalized.isalpha():
        raise ValueError("A three-letter currency is required.")
    return normalized


def _key(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Idempotency key is required.")
    return normalized


class TransactionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    date: datetime | Date
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    currency: str
    type: TransactionType
    account_id: str = Field(alias="accountId", min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    counterparty: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=2000)
    category_id: str | None = Field(default=None, alias="categoryId", max_length=200)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=200)

    @field_validator("date")
    @classmethod
    def normalize_date(cls, value: datetime | Date) -> datetime:
        return _timestamp(value)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return _currency(value)

    @field_validator("account_id", "idempotency_key")
    @classmethod
    def normalize_required(cls, value: str) -> str:
        return _key(value)

    @field_validator("description", "counterparty", "note", "category_id")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        return _optional_text(value)


class TransactionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    date: datetime | Date | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=6)
    currency: str | None = None
    type: TransactionType | None = None
    description: str | None = Field(default=None, max_length=1000)
    counterparty: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=2000)
    category_id: str | None = Field(default=None, alias="categoryId", max_length=200)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=200)

    @field_validator("date")
    @classmethod
    def normalize_date(cls, value: datetime | Date | None) -> datetime | None:
        return None if value is None else _timestamp(value)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return None if value is None else _currency(value)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        return _key(value)

    @field_validator("description", "counterparty", "note", "category_id")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        return _optional_text(value)

    @model_validator(mode="after")
    def require_update(self) -> TransactionUpdateRequest:
        if self.model_fields_set == {"idempotency_key"}:
            raise ValueError("At least one transaction field is required.")
        return self


class TransactionDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    idempotency_key: str = Field(alias="idempotencyKey", min_length=1, max_length=200)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_key(cls, value: str) -> str:
        return _key(value)


class TransactionCategoryResponse(BaseModel):
    id: str
    name: str
    icon: str | None
    color: str | None
    type: CategoryType


class TransactionAccountResponse(BaseModel):
    name: str
    currency: str


class TransactionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    date: datetime
    amount: Decimal
    currency: str
    type: TransactionType
    description: str | None
    counterparty: str | None
    note: str | None
    account_id: str = Field(serialization_alias="accountId")
    category_id: str | None = Field(serialization_alias="categoryId")
    category: TransactionCategoryResponse | None
    account: TransactionAccountResponse


class TransactionPageResponse(BaseModel):
    transactions: list[TransactionResponse]
    total: int
    page: int
    pages: int


class TransactionDeleteResponse(BaseModel):
    ok: bool
