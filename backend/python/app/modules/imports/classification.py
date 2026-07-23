from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

from app.db.models.enums import (
    ImportSource,
    InvestmentEventType,
    TransactionClassification,
    TransactionType,
)

POSTING_INTENT_SCHEMA_VERSION: Final[Literal[1]] = 1


class PostingIntentTarget(StrEnum):
    transaction = "transaction"
    investment_event = "investment_event"
    needs_review = "needs_review"


class InvestmentAction(StrEnum):
    buy = "buy"
    sell = "sell"


class PostingIntentIssueCode(StrEnum):
    invalid_payload = "invalid_payload"
    unsupported_schema_version = "unsupported_schema_version"
    source_mismatch = "source_mismatch"
    invalid_date = "invalid_date"
    invalid_amount = "invalid_amount"
    invalid_currency = "invalid_currency"
    zero_amount = "zero_amount"
    conflicting_transaction_type = "conflicting_transaction_type"
    ambiguous_transfer_type = "ambiguous_transfer_type"
    investment_normalization_required = "investment_normalization_required"


class PostingIntentIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    code: PostingIntentIssueCode
    message: str


class _PostingIntentBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = POSTING_INTENT_SCHEMA_VERSION


class TransactionPostingIntent(_PostingIntentBase):
    target: Literal[PostingIntentTarget.transaction] = PostingIntentTarget.transaction
    source: ImportSource
    date: str
    amount: Decimal
    currency: str
    transaction_type: TransactionType
    transaction_classification: TransactionClassification


class InvestmentEventPostingIntent(_PostingIntentBase):
    target: Literal[PostingIntentTarget.investment_event] = PostingIntentTarget.investment_event
    source: ImportSource
    date: str
    amount: Decimal
    currency: str
    investment_event_type: InvestmentEventType
    action: InvestmentAction | None = None


class NeedsReviewPostingIntent(_PostingIntentBase):
    target: Literal[PostingIntentTarget.needs_review] = PostingIntentTarget.needs_review
    errors: tuple[PostingIntentIssue, ...]


PostingIntent = TransactionPostingIntent | InvestmentEventPostingIntent | NeedsReviewPostingIntent

_TRANSACTION_SOURCES: Final = frozenset({ImportSource.raiffeisenbank, ImportSource.manual})
_INVESTMENT_SOURCES: Final = frozenset({ImportSource.trading212, ImportSource.anycoin})

_TRANSACTION_TYPE_RULES: Final[Mapping[str, tuple[TransactionType, TransactionClassification]]] = (
    MappingProxyType(
        {
            "income": (TransactionType.income, TransactionClassification.real_income),
            "příjem": (TransactionType.income, TransactionClassification.real_income),
            "incoming payment": (TransactionType.income, TransactionClassification.real_income),
            "příchozí platba": (TransactionType.income, TransactionClassification.real_income),
            "expense": (TransactionType.expense, TransactionClassification.real_expense),
            "výdaj": (TransactionType.expense, TransactionClassification.real_expense),
            "outgoing payment": (TransactionType.expense, TransactionClassification.real_expense),
            "odchozí platba": (TransactionType.expense, TransactionClassification.real_expense),
            "card payment": (TransactionType.expense, TransactionClassification.real_expense),
            "platba kartou": (TransactionType.expense, TransactionClassification.real_expense),
            "internal transfer": (
                TransactionType.transfer,
                TransactionClassification.internal_transfer,
            ),
            "interní převod": (
                TransactionType.transfer,
                TransactionClassification.internal_transfer,
            ),
        }
    )
)
_AMBIGUOUS_TRANSFER_TYPES: Final = frozenset({"transfer", "account transfer", "převod"})
_CURRENCY_PATTERN = re.compile(r"[A-Z0-9._-]{2,20}")


def _issue(
    field: str,
    code: PostingIntentIssueCode,
    message: str,
) -> PostingIntentIssue:
    return PostingIntentIssue(field=field, code=code, message=message)


def _review(*errors: PostingIntentIssue) -> NeedsReviewPostingIntent:
    return NeedsReviewPostingIntent(errors=errors)


def _normalize_type(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().casefold().split())
    return normalized or None


def _validated_date(value: object) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    try:
        if len(value) == 10:
            date.fromisoformat(value)
        else:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def _validated_amount(value: object) -> Decimal | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        return None
    return amount if amount.is_finite() else None


def _validated_currency(value: object) -> str | None:
    if not isinstance(value, str) or _CURRENCY_PATTERN.fullmatch(value) is None:
        return None
    return value


def _validated_financial_fields(
    normalized_data: Mapping[str, object],
) -> tuple[str, Decimal, str] | NeedsReviewPostingIntent:
    normalized_date = _validated_date(normalized_data.get("date"))
    amount = _validated_amount(normalized_data.get("amount"))
    currency = _validated_currency(normalized_data.get("currency"))
    errors: list[PostingIntentIssue] = []
    if normalized_date is None:
        errors.append(
            _issue(
                "date",
                PostingIntentIssueCode.invalid_date,
                "A valid normalized date is required.",
            )
        )
    if amount is None:
        errors.append(
            _issue(
                "amount",
                PostingIntentIssueCode.invalid_amount,
                "A finite decimal amount string is required.",
            )
        )
    if currency is None:
        errors.append(
            _issue(
                "currency",
                PostingIntentIssueCode.invalid_currency,
                "A valid normalized currency is required.",
            )
        )
    if errors:
        return _review(*errors)
    assert normalized_date is not None
    assert amount is not None
    assert currency is not None
    return normalized_date, amount, currency


def _classify_transaction(
    *,
    source: ImportSource,
    normalized_data: Mapping[str, object],
    normalized_date: str,
    amount: Decimal,
    currency: str,
) -> PostingIntent:
    normalized_type = _normalize_type(normalized_data.get("type"))
    explicit_rule = (
        _TRANSACTION_TYPE_RULES.get(normalized_type) if normalized_type is not None else None
    )

    if amount.is_zero():
        return _review(
            _issue(
                "amount",
                PostingIntentIssueCode.zero_amount,
                "A zero amount cannot be classified for posting.",
            )
        )

    if normalized_type in _AMBIGUOUS_TRANSFER_TYPES:
        return _review(
            _issue(
                "type",
                PostingIntentIssueCode.ambiguous_transfer_type,
                "The transfer type does not prove an internal transfer.",
            )
        )

    if explicit_rule is None:
        transaction_type, classification = (
            (TransactionType.income, TransactionClassification.real_income)
            if amount > 0
            else (TransactionType.expense, TransactionClassification.real_expense)
        )
    else:
        transaction_type, classification = explicit_rule
        if (transaction_type is TransactionType.income and amount < 0) or (
            transaction_type is TransactionType.expense and amount > 0
        ):
            return _review(
                _issue(
                    "type",
                    PostingIntentIssueCode.conflicting_transaction_type,
                    "The explicit transaction type conflicts with the amount sign.",
                )
            )

    return TransactionPostingIntent(
        source=source,
        date=normalized_date,
        amount=amount,
        currency=currency,
        transaction_type=transaction_type,
        transaction_classification=classification,
    )


def classify_import_row(
    *,
    source: ImportSource,
    normalized_data: object,
) -> PostingIntent:
    """Classify one normalized row without performing I/O or mutating the input."""
    if not isinstance(normalized_data, Mapping):
        return _review(
            _issue(
                "normalized_data",
                PostingIntentIssueCode.invalid_payload,
                "Normalized data must be an object.",
            )
        )
    schema_version = normalized_data.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        return _review(
            _issue(
                "schema_version",
                PostingIntentIssueCode.unsupported_schema_version,
                "Only normalized schema version 1 is supported.",
            )
        )
    if normalized_data.get("source") != source.value:
        return _review(
            _issue(
                "source",
                PostingIntentIssueCode.source_mismatch,
                "The source argument must match the normalized source.",
            )
        )

    financial_fields = _validated_financial_fields(normalized_data)
    if isinstance(financial_fields, NeedsReviewPostingIntent):
        return financial_fields
    normalized_date, amount, currency = financial_fields

    if source in _TRANSACTION_SOURCES:
        return _classify_transaction(
            source=source,
            normalized_data=normalized_data,
            normalized_date=normalized_date,
            amount=amount,
            currency=currency,
        )
    if source in _INVESTMENT_SOURCES:
        return _review(
            _issue(
                "normalized_data",
                PostingIntentIssueCode.investment_normalization_required,
                "Source-specific investment normalization is required before classification.",
            )
        )
    return _review(
        _issue(
            "source",
            PostingIntentIssueCode.source_mismatch,
            "The source argument is not supported.",
        )
    )
