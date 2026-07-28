"""Shared exact validation for canonical liability balance evidence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from app.db.models.common import MONEY, TIMESTAMP
from app.db.models.enums import AccountType

LIABILITY_ACCOUNT_TYPES = frozenset(
    {
        AccountType.credit_card,
        AccountType.loan,
        AccountType.mortgage,
    }
)


class LiabilityBalanceValidationError(ValueError):
    """Internal validation failure mapped by each application boundary."""


def canonical_nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise LiabilityBalanceValidationError
    return value


def canonical_timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or precision is None
        or not 0 <= precision <= 6
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise LiabilityBalanceValidationError
    return value


def canonical_currency(value: object) -> str:
    currency = canonical_nonblank(value)
    if len(currency) != 3 or currency != currency.upper() or not currency.isalpha():
        raise LiabilityBalanceValidationError
    return currency


def canonical_money(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise LiabilityBalanceValidationError
    precision, scale = MONEY.precision, MONEY.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical MONEY must define precision and scale.")
    try:
        with localcontext() as context:
            context.prec = max(precision * 4, 84)
            scaled = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise LiabilityBalanceValidationError from exc
    if value != scaled or abs(value) >= Decimal(10) ** (precision - scale):
        raise LiabilityBalanceValidationError
    return value


def canonical_total(principal: Decimal, interest: Decimal, fees: Decimal) -> Decimal:
    precision = MONEY.precision
    if precision is None:
        raise RuntimeError("Canonical MONEY must define precision and scale.")
    try:
        with localcontext() as context:
            context.prec = max(precision * 4, 84)
            result = principal + interest + fees
    except (InvalidOperation, OverflowError) as exc:
        raise LiabilityBalanceValidationError from exc
    return canonical_money(result)


def canonical_external_id(value: object) -> str | None:
    if value is None:
        return None
    return canonical_nonblank(value)
