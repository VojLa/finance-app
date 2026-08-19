"""Canonical arithmetic at explicit derived-snapshot storage boundaries.

Evidence is validated by its caller without repair. These helpers are only for
values derived from that evidence (for example quantity x price and direct FX
conversion) immediately before a documented storage/output boundary.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext

from sqlalchemy import Numeric


class DerivedSnapshotCalculationError(ValueError):
    """Raised when a derived value cannot safely fit its canonical boundary."""


type DerivedSnapshotNumericContract = Numeric | tuple[int, int]


def _numeric_contract(numeric: DerivedSnapshotNumericContract) -> tuple[int, int]:
    precision: object
    scale: object
    if isinstance(numeric, tuple):
        if len(numeric) != 2:
            raise RuntimeError("Canonical numeric types must define precision and scale.")
        precision, scale = numeric
    else:
        precision, scale = numeric.precision, numeric.scale
    if (
        not isinstance(precision, int)
        or isinstance(precision, bool)
        or not isinstance(scale, int)
        or isinstance(scale, bool)
        or precision <= 0
        or not 0 <= scale <= precision
    ):
        raise RuntimeError("Canonical numeric types must define precision and scale.")
    return precision, scale


def _finite_decimal(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise DerivedSnapshotCalculationError()
    return value


def round_derived_snapshot_value(
    value: object,
    numeric: DerivedSnapshotNumericContract,
) -> Decimal:
    """Round one derived Decimal half-even at its sole declared boundary.

    A nonzero value that becomes zero would silently lose evidence, so it is
    rejected. The returned zero is normalized to ``Decimal(0)``.
    """

    raw = _finite_decimal(value)
    precision, scale = _numeric_contract(numeric)
    limit = Decimal(10) ** (precision - scale)
    if abs(raw) >= limit * Decimal(10):
        raise DerivedSnapshotCalculationError()
    try:
        with localcontext() as context:
            # Inputs are bounded canonical Decimal values. This remains well
            # above their combined significant digits and is independent from
            # the process-wide Decimal context.
            context.prec = max(precision * 4, 112)
            rounded = raw.quantize(
                Decimal(1).scaleb(-scale),
                rounding=ROUND_HALF_EVEN,
            )
    except (InvalidOperation, OverflowError) as exc:
        raise DerivedSnapshotCalculationError() from exc
    if abs(rounded) >= limit or (raw != 0 and rounded == 0):
        raise DerivedSnapshotCalculationError()
    return Decimal(0) if rounded.is_zero() else rounded


def multiply_derived_snapshot_values(
    left: object,
    right: object,
    numeric: DerivedSnapshotNumericContract,
) -> Decimal:
    """Multiply finite evidence with high precision, then round once."""

    first = _finite_decimal(left)
    second = _finite_decimal(right)
    precision, _ = _numeric_contract(numeric)
    try:
        with localcontext() as context:
            context.prec = max(precision * 4, 112)
            result = first * second
    except (InvalidOperation, OverflowError) as exc:
        raise DerivedSnapshotCalculationError() from exc
    return round_derived_snapshot_value(result, numeric)
