"""Explicit deterministic rounding for derived canonical numeric values."""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from typing import Any

from sqlalchemy import Numeric


class CanonicalArithmeticError(ValueError):
    pass


def _contract(contract: Numeric[Any]) -> tuple[int, int, Decimal, Decimal]:
    precision = contract.precision
    scale = contract.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical numeric type must define precision and scale.")
    return (
        precision,
        scale,
        Decimal(1).scaleb(-scale),
        Decimal(10) ** (precision - scale),
    )


def canonical_rounded(value: Decimal, contract: Numeric[Any]) -> Decimal:
    """Round one derived value at its declared storage boundary using half-even."""
    precision, _, quantum, limit = _contract(contract)
    if not isinstance(value, Decimal) or not value.is_finite():
        raise CanonicalArithmeticError()
    try:
        with localcontext() as context:
            context.prec = max(precision * 4, 112)
            result = value.quantize(quantum, rounding=ROUND_HALF_EVEN)
    except InvalidOperation as exc:
        raise CanonicalArithmeticError() from exc
    if abs(result) >= limit:
        raise CanonicalArithmeticError()
    return result


def canonical_ratio(
    numerator: Decimal,
    denominator: Decimal,
    contract: Numeric[Any],
) -> Decimal:
    """Return a representable ratio while preserving exact numerator evidence."""
    precision, _, _, _ = _contract(contract)
    if (
        not isinstance(numerator, Decimal)
        or not isinstance(denominator, Decimal)
        or not numerator.is_finite()
        or not denominator.is_finite()
        or denominator == 0
    ):
        raise CanonicalArithmeticError()
    try:
        with localcontext() as context:
            context.prec = max(precision * 4, 112)
            value = numerator / denominator
    except (InvalidOperation, ZeroDivisionError) as exc:
        raise CanonicalArithmeticError() from exc
    return canonical_rounded(value, contract)
