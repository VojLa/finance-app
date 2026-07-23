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
    missing_investment_type = "missing_investment_type"
    unsupported_investment_type = "unsupported_investment_type"
    unsupported_linked_cash_transaction = "unsupported_linked_cash_transaction"


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
            "transfer": (TransactionType.transfer, TransactionClassification.internal_transfer),
            "internal transfer": (
                TransactionType.transfer,
                TransactionClassification.internal_transfer,
            ),
            "account transfer": (
                TransactionType.transfer,
                TransactionClassification.internal_transfer,
            ),
            "převod": (TransactionType.transfer, TransactionClassification.internal_transfer),
            "interní převod": (
                TransactionType.transfer,
                TransactionClassification.internal_transfer,
            ),
        }
    )
)

_INVESTMENT_EVENT_RULES: Final[
    Mapping[str, tuple[InvestmentEventType, InvestmentAction | None]]
] = MappingProxyType(
    {
        "buy": (InvestmentEventType.trade, InvestmentAction.buy),
        "purchase": (InvestmentEventType.trade, InvestmentAction.buy),
        "market buy": (InvestmentEventType.trade, InvestmentAction.buy),
        "limit buy": (InvestmentEventType.trade, InvestmentAction.buy),
        "stop buy": (InvestmentEventType.trade, InvestmentAction.buy),
        "crypto purchase": (InvestmentEventType.trade, InvestmentAction.buy),
        "nákup": (InvestmentEventType.trade, InvestmentAction.buy),
        "sell": (InvestmentEventType.trade, InvestmentAction.sell),
        "sale": (InvestmentEventType.trade, InvestmentAction.sell),
        "market sell": (InvestmentEventType.trade, InvestmentAction.sell),
        "limit sell": (InvestmentEventType.trade, InvestmentAction.sell),
        "stop sell": (InvestmentEventType.trade, InvestmentAction.sell),
        "stop loss": (InvestmentEventType.trade, InvestmentAction.sell),
        "take profit": (InvestmentEventType.trade, InvestmentAction.sell),
        "crypto sale": (InvestmentEventType.trade, InvestmentAction.sell),
        "prodej": (InvestmentEventType.trade, InvestmentAction.sell),
        "deposit": (InvestmentEventType.cash_deposit, None),
        "fiat deposit": (InvestmentEventType.cash_deposit, None),
        "crypto deposit": (InvestmentEventType.cash_deposit, None),
        "receive": (InvestmentEventType.cash_deposit, None),
        "incoming": (InvestmentEventType.cash_deposit, None),
        "top up": (InvestmentEventType.cash_deposit, None),
        "funding": (InvestmentEventType.cash_deposit, None),
        "vklad": (InvestmentEventType.cash_deposit, None),
        "withdrawal": (InvestmentEventType.cash_withdrawal, None),
        "fiat withdrawal": (InvestmentEventType.cash_withdrawal, None),
        "crypto withdrawal": (InvestmentEventType.cash_withdrawal, None),
        "send": (InvestmentEventType.cash_withdrawal, None),
        "outgoing": (InvestmentEventType.cash_withdrawal, None),
        "výběr": (InvestmentEventType.cash_withdrawal, None),
        "dividend": (InvestmentEventType.dividend, None),
        "dividends": (InvestmentEventType.dividend, None),
        "dividend (ordinary)": (InvestmentEventType.dividend, None),
        "dividend (dividends paid by us corporations)": (
            InvestmentEventType.dividend,
            None,
        ),
        "dividend (dividend)": (InvestmentEventType.dividend, None),
        "dividend (dividend manufactured payment)": (
            InvestmentEventType.dividend,
            None,
        ),
        "dividend (tax exempted)": (InvestmentEventType.dividend, None),
        "dividend reinvestment": (InvestmentEventType.dividend, None),
        "dividenda": (InvestmentEventType.dividend, None),
        "interest": (InvestmentEventType.interest, None),
        "interest on cash": (InvestmentEventType.interest, None),
        "cash interest": (InvestmentEventType.interest, None),
        "savings interest": (InvestmentEventType.interest, None),
        "earn interest": (InvestmentEventType.interest, None),
        "lending interest": (InvestmentEventType.interest, None),
        "úrok": (InvestmentEventType.interest, None),
        "currency conversion": (InvestmentEventType.currency_conversion, None),
        "fx conversion": (InvestmentEventType.currency_conversion, None),
        "exchange": (InvestmentEventType.currency_conversion, None),
        "convert": (InvestmentEventType.currency_conversion, None),
        "swap": (InvestmentEventType.currency_conversion, None),
        "směna": (InvestmentEventType.currency_conversion, None),
        "konverze měny": (InvestmentEventType.currency_conversion, None),
        "asset transfer": (InvestmentEventType.asset_transfer, None),
        "internal transfer": (InvestmentEventType.asset_transfer, None),
        "portfolio transfer": (InvestmentEventType.asset_transfer, None),
        "fee": (InvestmentEventType.fee, None),
        "commission": (InvestmentEventType.fee, None),
        "currency conversion fee": (InvestmentEventType.fee, None),
        "transaction fee": (InvestmentEventType.fee, None),
        "trading fee": (InvestmentEventType.fee, None),
        "withdrawal fee": (InvestmentEventType.fee, None),
        "service fee": (InvestmentEventType.fee, None),
        "poplatek": (InvestmentEventType.fee, None),
        "staking": (InvestmentEventType.staking_reward, None),
        "staking reward": (InvestmentEventType.staking_reward, None),
        "staking income": (InvestmentEventType.staking_reward, None),
        "eth2 staking reward": (InvestmentEventType.staking_reward, None),
        "airdrop": (InvestmentEventType.airdrop, None),
        "fork": (InvestmentEventType.airdrop, None),
        "token distribution": (InvestmentEventType.airdrop, None),
        "free share": (InvestmentEventType.airdrop, None),
        "free shares": (InvestmentEventType.airdrop, None),
        "free stock": (InvestmentEventType.airdrop, None),
        "free stocks": (InvestmentEventType.airdrop, None),
    }
)

_TRADING212_LINKED_CASH_TYPES: Final = frozenset({"card debit", "card cost", "new card cost"})
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


def _classify_investment_event(
    *,
    source: ImportSource,
    normalized_data: Mapping[str, object],
    normalized_date: str,
    amount: Decimal,
    currency: str,
) -> PostingIntent:
    raw_type = normalized_data.get("type")
    normalized_type = _normalize_type(raw_type)
    if normalized_type is None:
        if raw_type is not None and not (isinstance(raw_type, str) and not raw_type.strip()):
            return _review(
                _issue(
                    "type",
                    PostingIntentIssueCode.unsupported_investment_type,
                    "The investment action is not supported by the explicit allowlist.",
                )
            )
        return _review(
            _issue(
                "type",
                PostingIntentIssueCode.missing_investment_type,
                "An explicit investment action is required.",
            )
        )
    if source is ImportSource.trading212 and normalized_type in _TRADING212_LINKED_CASH_TYPES:
        return _review(
            _issue(
                "type",
                PostingIntentIssueCode.unsupported_linked_cash_transaction,
                "This Trading212 card action requires a linked cash transaction contract.",
            )
        )
    rule = _INVESTMENT_EVENT_RULES.get(normalized_type)
    if rule is None:
        return _review(
            _issue(
                "type",
                PostingIntentIssueCode.unsupported_investment_type,
                "The investment action is not supported by the explicit allowlist.",
            )
        )
    if amount.is_zero():
        return _review(
            _issue(
                "amount",
                PostingIntentIssueCode.zero_amount,
                "A zero amount cannot be classified for posting.",
            )
        )

    event_type, action = rule
    return InvestmentEventPostingIntent(
        source=source,
        date=normalized_date,
        amount=amount,
        currency=currency,
        investment_event_type=event_type,
        action=action,
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
        return _classify_investment_event(
            source=source,
            normalized_data=normalized_data,
            normalized_date=normalized_date,
            amount=amount,
            currency=currency,
        )
    return _review(
        _issue(
            "source",
            PostingIntentIssueCode.source_mismatch,
            "The source argument is not supported.",
        )
    )
