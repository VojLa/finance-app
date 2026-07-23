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
    dividend = "dividend"
    interest = "interest"
    cash_deposit = "cash_deposit"
    cash_withdrawal = "cash_withdrawal"
    currency_conversion = "currency_conversion"
    asset_transfer = "asset_transfer"
    fee = "fee"
    staking_reward = "staking_reward"
    airdrop = "airdrop"


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
    invalid_investment_payload = "invalid_investment_payload"


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


class InvestmentAssetPostingIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str | None
    isin: str | None
    name: str | None
    asset_type_hint: str | None


class InvestmentMoneyPostingIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: Decimal
    currency: str


class InvestmentConversionPostingIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    from_: InvestmentMoneyPostingIntent
    to: InvestmentMoneyPostingIntent
    exchange_rate: Decimal | None


class InvestmentEventPostingIntent(_PostingIntentBase):
    target: Literal[PostingIntentTarget.investment_event] = PostingIntentTarget.investment_event
    source: ImportSource
    date: str
    investment_event_type: InvestmentEventType
    action: InvestmentAction
    external_id: str | None
    raw_action: str | None
    asset: InvestmentAssetPostingIntent
    quantity: Decimal | None
    price: InvestmentMoneyPostingIntent | None
    total: InvestmentMoneyPostingIntent | None
    fee: InvestmentMoneyPostingIntent | None
    conversion: InvestmentConversionPostingIntent | None
    realized_pnl: InvestmentMoneyPostingIntent | None
    is_promotional: bool
    note: str | None


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


_INVESTMENT_EVENT_TYPES: Final[Mapping[InvestmentAction, InvestmentEventType]] = MappingProxyType(
    {
        InvestmentAction.buy: InvestmentEventType.trade,
        InvestmentAction.sell: InvestmentEventType.trade,
        InvestmentAction.dividend: InvestmentEventType.dividend,
        InvestmentAction.interest: InvestmentEventType.interest,
        InvestmentAction.cash_deposit: InvestmentEventType.cash_deposit,
        InvestmentAction.cash_withdrawal: InvestmentEventType.cash_withdrawal,
        InvestmentAction.currency_conversion: InvestmentEventType.currency_conversion,
        InvestmentAction.asset_transfer: InvestmentEventType.asset_transfer,
        InvestmentAction.fee: InvestmentEventType.fee,
        InvestmentAction.staking_reward: InvestmentEventType.staking_reward,
        InvestmentAction.airdrop: InvestmentEventType.airdrop,
    }
)


def _investment_review() -> NeedsReviewPostingIntent:
    return _review(
        _issue(
            "normalized_data",
            PostingIntentIssueCode.invalid_investment_payload,
            "Trading212 normalized investment data is invalid.",
        )
    )


def _investment_money(value: object) -> InvestmentMoneyPostingIntent | None | bool:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        return False
    amount = _validated_amount(value.get("amount"))
    currency = _validated_currency(value.get("currency"))
    if amount is None or currency is None:
        return False
    return InvestmentMoneyPostingIntent(amount=amount, currency=currency)


def _classify_trading212(normalized_data: Mapping[str, object]) -> PostingIntent:
    if normalized_data.get("kind") != "investment_event":
        return _investment_review()
    normalized_date = _validated_date(normalized_data.get("date"))
    action_value = normalized_data.get("action")
    if not isinstance(action_value, str):
        return _investment_review()
    try:
        action = InvestmentAction(action_value)
    except (TypeError, ValueError):
        return _investment_review()
    asset_data = normalized_data.get("asset")
    if normalized_date is None or not isinstance(asset_data, Mapping):
        return _investment_review()
    asset_values = tuple(
        asset_data.get(field) for field in ("symbol", "isin", "name", "asset_type_hint")
    )
    if any(value is not None and not isinstance(value, str) for value in asset_values):
        return _investment_review()
    quantity_raw = normalized_data.get("quantity")
    quantity = None if quantity_raw is None else _validated_amount(quantity_raw)
    if quantity_raw is not None and quantity is None:
        return _investment_review()
    money_values = [
        _investment_money(normalized_data.get(field))
        for field in ("price", "total", "fee", "realized_pnl")
    ]
    if any(value is False for value in money_values):
        return _investment_review()
    price, total, fee, realized_pnl = money_values
    if not all(
        value is None or isinstance(value, InvestmentMoneyPostingIntent)
        for value in (price, total, fee, realized_pnl)
    ):
        return _investment_review()
    assert price is None or isinstance(price, InvestmentMoneyPostingIntent)
    assert total is None or isinstance(total, InvestmentMoneyPostingIntent)
    assert fee is None or isinstance(fee, InvestmentMoneyPostingIntent)
    assert realized_pnl is None or isinstance(realized_pnl, InvestmentMoneyPostingIntent)
    conversion_data = normalized_data.get("conversion")
    conversion: InvestmentConversionPostingIntent | None
    if conversion_data is None:
        conversion = None
    elif not isinstance(conversion_data, Mapping):
        return _investment_review()
    else:
        from_money = _investment_money(conversion_data.get("from"))
        to_money = _investment_money(conversion_data.get("to"))
        rate_raw = conversion_data.get("exchange_rate")
        rate = None if rate_raw is None else _validated_amount(rate_raw)
        if (
            from_money is False
            or to_money is False
            or from_money is None
            or to_money is None
            or (rate_raw is not None and rate is None)
        ):
            return _investment_review()
        conversion = InvestmentConversionPostingIntent(
            from_=from_money, to=to_money, exchange_rate=rate
        )
    external_id = normalized_data.get("external_id")
    raw_action = normalized_data.get("raw_action")
    note = normalized_data.get("note")
    promotional = normalized_data.get("is_promotional")
    if (
        (external_id is not None and not isinstance(external_id, str))
        or (raw_action is not None and not isinstance(raw_action, str))
        or (note is not None and not isinstance(note, str))
        or type(promotional) is not bool
    ):
        return _investment_review()
    asset = InvestmentAssetPostingIntent(
        symbol=asset_values[0],
        isin=asset_values[1],
        name=asset_values[2],
        asset_type_hint=asset_values[3],
    )
    asset_identity = bool(asset.symbol or asset.isin)
    positive_quantity = quantity is not None and quantity > 0
    positive_total = total is not None and total.amount > 0
    if (
        (price is not None and price.amount <= 0)
        or (fee is not None and fee.amount < 0)
        or (
            action in {InvestmentAction.buy, InvestmentAction.sell}
            and not (asset_identity and positive_quantity and positive_total)
        )
        or (action is InvestmentAction.dividend and not (asset_identity and positive_total))
        or (
            action
            in {
                InvestmentAction.interest,
                InvestmentAction.cash_deposit,
                InvestmentAction.cash_withdrawal,
                InvestmentAction.fee,
            }
            and not positive_total
        )
        or (
            action
            in {
                InvestmentAction.asset_transfer,
                InvestmentAction.staking_reward,
                InvestmentAction.airdrop,
            }
            and not (asset_identity and positive_quantity)
        )
        or (action is InvestmentAction.currency_conversion and conversion is None)
        or (
            conversion is not None
            and (
                conversion.from_.currency == conversion.to.currency
                or conversion.from_.amount <= 0
                or conversion.to.amount <= 0
                or (conversion.exchange_rate is not None and conversion.exchange_rate <= 0)
            )
        )
    ):
        return _investment_review()
    return InvestmentEventPostingIntent(
        source=ImportSource.trading212,
        date=normalized_date,
        investment_event_type=_INVESTMENT_EVENT_TYPES[action],
        action=action,
        external_id=external_id,
        raw_action=raw_action,
        asset=asset,
        quantity=quantity,
        price=price,
        total=total,
        fee=fee,
        conversion=conversion,
        realized_pnl=realized_pnl,
        is_promotional=promotional,
        note=note,
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
    if type(schema_version) is not int or schema_version not in {1, 2}:
        return _review(
            _issue(
                "schema_version",
                PostingIntentIssueCode.unsupported_schema_version,
                "Only supported normalized schema versions are accepted.",
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

    if schema_version == 2:
        if source is ImportSource.trading212:
            return _classify_trading212(normalized_data)
        return _review(
            _issue(
                "schema_version",
                PostingIntentIssueCode.unsupported_schema_version,
                "Normalized schema version 2 is only supported for Trading212.",
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
