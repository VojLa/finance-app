"""Exact decoding and validation for persisted portfolio currency breakdowns."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, localcontext

from app.modules.portfolio_snapshot.models import PortfolioCurrencyAmount

_MONEY_SCALE = 6
_MONEY_LIMIT = Decimal("1000000000000")
_CANONICAL_MONEY = re.compile(r"-?(?:0|[1-9][0-9]{0,11})\.[0-9]{6}\Z")


class PortfolioCurrencyBreakdownError(ValueError):
    """Raised when physical currency evidence is incomplete or noncanonical."""


def _fail() -> PortfolioCurrencyBreakdownError:
    return PortfolioCurrencyBreakdownError()


def _currency(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 3
        or any(character < "A" or character > "Z" for character in value)
    ):
        raise _fail()
    return value


def _money(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail()
    try:
        with localcontext() as context:
            context.prec = 112
            scaled = value.quantize(Decimal(1).scaleb(-_MONEY_SCALE))
    except InvalidOperation as exc:
        raise _fail() from exc
    if value != scaled or value.copy_abs() >= _MONEY_LIMIT:
        raise _fail()
    return value


def _canonical_money(value: object) -> Decimal:
    if not isinstance(value, str) or _CANONICAL_MONEY.fullmatch(value) is None:
        raise _fail()
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise _fail() from exc
    exact = _money(parsed)
    if format(exact, ".6f") != value:
        raise _fail()
    return exact


def validate_portfolio_currency_breakdown(
    value: object,
    *,
    scalar_total: object,
    output_currency: object,
) -> tuple[PortfolioCurrencyAmount, ...]:
    """Validate one already-decoded immutable breakdown without repairing it."""

    if not isinstance(value, tuple):
        raise _fail()
    total = _money(scalar_total)
    output = _currency(output_currency)
    currencies: list[str] = []
    validated: list[PortfolioCurrencyAmount] = []
    for item in value:
        if not isinstance(item, PortfolioCurrencyAmount):
            raise _fail()
        currency = _currency(item.currency)
        amount = _money(item.amount)
        currencies.append(currency)
        validated.append(item)
        if item.currency != currency or item.amount != amount:
            raise _fail()
    if currencies != sorted(currencies) or len(set(currencies)) != len(currencies):
        raise _fail()
    if not validated and total != 0:
        raise _fail()
    if len(validated) == 1 and validated[0].currency == output:
        if validated[0].amount != total:
            raise _fail()
    return value


def decode_portfolio_currency_breakdown(
    value: object,
    *,
    scalar_total: object,
    output_currency: object,
) -> tuple[PortfolioCurrencyAmount, ...]:
    """Decode the exact JSONB inverse of the AccountSnapshot MONEY serializer."""

    if not isinstance(value, dict):
        raise _fail()
    for currency, amount in value.items():
        _currency(currency)
        if not isinstance(amount, str):
            raise _fail()
    decoded = tuple(
        PortfolioCurrencyAmount(
            currency=_currency(currency),
            amount=_canonical_money(amount),
        )
        for currency, amount in sorted(value.items())
    )
    return validate_portfolio_currency_breakdown(
        decoded,
        scalar_total=scalar_total,
        output_currency=output_currency,
    )


__all__ = [
    "PortfolioCurrencyBreakdownError",
    "decode_portfolio_currency_breakdown",
    "validate_portfolio_currency_breakdown",
]
