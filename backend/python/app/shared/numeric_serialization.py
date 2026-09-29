"""Canonical fixed-scale serialization for public financial numerics."""

from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from sqlalchemy import Numeric

from app.db.models.common import MONEY, PERCENTAGE, QUANTITY, RATE


def serialize_numeric(value: Decimal, numeric: Numeric[Any]) -> str:
    """Serialize one exactly representable SQL Numeric value without rounding."""

    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("Canonical numeric serialization requires a finite Decimal.")

    precision = numeric.precision
    scale = numeric.scale
    if precision is None or scale is None:
        raise ValueError("Canonical numeric serialization requires precision and scale.")

    quantum = Decimal(1).scaleb(-scale)
    limit = Decimal(10) ** (precision - scale)
    try:
        with localcontext() as context:
            context.prec = max(precision + scale, len(value.as_tuple().digits) + scale + 1)
            canonical = value.quantize(quantum)
    except InvalidOperation as exc:
        raise ValueError("Value is not representable by the canonical numeric contract.") from exc

    if canonical != value or abs(canonical) >= limit:
        raise ValueError("Value is not representable by the canonical numeric contract.")
    if canonical.is_zero():
        canonical = canonical.copy_abs()
    return format(canonical, f".{scale}f")


def serialize_money(value: Decimal) -> str:
    return serialize_numeric(value, MONEY)


def serialize_native_money(value: Decimal) -> str:
    """Preserve every stored native-currency digit from a JSON breakdown."""

    if type(value) is not Decimal or not value.is_finite():
        raise ValueError("Native money serialization requires a finite Decimal.")
    return format(value.copy_abs() if value.is_zero() else value, "f")


def serialize_quantity(value: Decimal) -> str:
    return serialize_numeric(value, QUANTITY)


def serialize_rate(value: Decimal) -> str:
    return serialize_numeric(value, RATE)


def serialize_percentage(value: Decimal) -> str:
    return serialize_numeric(value, PERCENTAGE)
