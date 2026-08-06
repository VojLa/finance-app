"""Pure validation, range calculation, collapse, and downsampling."""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from itertools import groupby

from app.db.models.common import MONEY, TIMESTAMP
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.modules.portfolio_history.models import (
    CanonicalPortfolioHistoryPoint,
    PersistedPortfolioHistoryPoint,
    PortfolioHistoryPoint,
    PortfolioHistoryRange,
)

MAX_PORTFOLIO_HISTORY_POINTS = 512
_POSTGRES_INTEGER_MAX = 2_147_483_647
_GRANULARITY_PRIORITY = {
    SnapshotGranularity.minute: 0,
    SnapshotGranularity.hour: 1,
    SnapshotGranularity.day: 2,
    SnapshotGranularity.week: 3,
    SnapshotGranularity.month: 4,
}


class PortfolioHistorySelectionError(ValueError):
    """Raised when persisted history cannot produce one exact public series."""


def _fail() -> PortfolioHistorySelectionError:
    return PortfolioHistorySelectionError(
        "Persisted NetWorthSnapshot evidence cannot produce portfolio history."
    )


def validate_timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        type(value) is not datetime
        or value.tzinfo is not None
        or precision is None
        or not 0 <= precision <= 6
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise _fail()
    return value


def validate_nonblank(value: object) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise _fail()
    return value


def validate_currency(value: object) -> str:
    currency = validate_nonblank(value)
    if len(currency) != 3 or any(character < "A" or character > "Z" for character in currency):
        raise _fail()
    return currency


def _exact_money(value: object, *, nonnegative: bool = False) -> Decimal:
    if type(value) is not Decimal or not value.is_finite():
        raise _fail()
    precision, scale = MONEY.precision, MONEY.scale
    if precision is None or scale is None:
        raise RuntimeError("MONEY must define precision and scale.")
    try:
        with localcontext() as context:
            context.prec = max(precision * 4, 112)
            scaled = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise _fail() from exc
    if (
        value != scaled
        or abs(value) >= Decimal(10) ** (precision - scale)
        or (nonnegative and value < 0)
    ):
        raise _fail()
    return value


def _calculation_version(value: object) -> int:
    if type(value) is not int or isinstance(value, bool) or not 1 <= value <= _POSTGRES_INTEGER_MAX:
        raise _fail()
    return value


def _subtract_months(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def portfolio_history_range_start(
    history_range: PortfolioHistoryRange,
    end: datetime,
) -> datetime | None:
    """Return an inclusive calendar-safe lower bound for one validated range."""

    canonical_end = validate_timestamp(end)
    if type(history_range) is not PortfolioHistoryRange:
        raise _fail()
    if history_range is PortfolioHistoryRange.one_week:
        return canonical_end - timedelta(days=7)
    if history_range is PortfolioHistoryRange.one_month:
        return _subtract_months(canonical_end, 1)
    if history_range is PortfolioHistoryRange.three_months:
        return _subtract_months(canonical_end, 3)
    if history_range is PortfolioHistoryRange.six_months:
        return _subtract_months(canonical_end, 6)
    if history_range is PortfolioHistoryRange.one_year:
        return _subtract_months(canonical_end, 12)
    if history_range is PortfolioHistoryRange.all:
        return None
    raise _fail()


def _validated_point(
    value: object,
    *,
    user_id: str,
    currency: str,
    start: datetime | None,
    end: datetime,
) -> CanonicalPortfolioHistoryPoint:
    if type(value) is not PersistedPortfolioHistoryPoint:
        raise _fail()
    snapshot_id = validate_nonblank(value.snapshot_id)
    if validate_nonblank(value.user_id) != user_id or validate_currency(value.currency) != currency:
        raise _fail()
    timestamp = validate_timestamp(value.timestamp)
    if timestamp > end or (start is not None and timestamp < start):
        raise _fail()
    if (
        type(value.granularity) is not SnapshotGranularity
        or type(value.source) is not SnapshotSource
    ):
        raise _fail()
    calculation_version = _calculation_version(value.calculation_version)
    cash = _exact_money(value.cash_value)
    portfolio = _exact_money(value.portfolio_value, nonnegative=True)
    liabilities = _exact_money(value.liabilities_value, nonnegative=True)
    total = _exact_money(value.total_net_worth)
    try:
        with localcontext() as context:
            context.prec = 112
            expected_total = cash + portfolio - liabilities
    except (InvalidOperation, OverflowError) as exc:
        raise _fail() from exc
    if expected_total != total:
        raise _fail()
    return CanonicalPortfolioHistoryPoint(
        snapshot_id=snapshot_id,
        timestamp=timestamp,
        granularity=value.granularity,
        source=value.source,
        calculation_version=calculation_version,
        cash_value=cash,
        investment_value=portfolio,
        liabilities_value=liabilities,
        net_worth_value=total,
    )


def canonicalize_portfolio_history_points(
    values: object,
    *,
    user_id: object,
    currency: object,
    start: datetime | None,
    end: datetime,
) -> tuple[CanonicalPortfolioHistoryPoint, ...]:
    """Validate all candidates and deterministically collapse equal timestamps."""

    if type(values) is not tuple:
        raise _fail()
    canonical_user_id = validate_nonblank(user_id)
    canonical_currency = validate_currency(currency)
    canonical_end = validate_timestamp(end)
    canonical_start = None if start is None else validate_timestamp(start)
    if canonical_start is not None and canonical_start > canonical_end:
        raise _fail()

    validated = tuple(
        _validated_point(
            value,
            user_id=canonical_user_id,
            currency=canonical_currency,
            start=canonical_start,
            end=canonical_end,
        )
        for value in values
    )
    snapshot_ids = [point.snapshot_id for point in validated]
    if len(snapshot_ids) != len(set(snapshot_ids)):
        raise _fail()
    ordered = sorted(
        validated,
        key=lambda point: (
            point.timestamp,
            _GRANULARITY_PRIORITY[point.granularity],
            point.snapshot_id,
        ),
    )
    collapsed: list[CanonicalPortfolioHistoryPoint] = []
    for _, timestamp_points_iterator in groupby(ordered, key=lambda point: point.timestamp):
        timestamp_points = tuple(timestamp_points_iterator)
        reference = timestamp_points[0]
        financial_identity = (
            reference.cash_value,
            reference.investment_value,
            reference.liabilities_value,
            reference.net_worth_value,
        )
        if any(
            (
                point.cash_value,
                point.investment_value,
                point.liabilities_value,
                point.net_worth_value,
            )
            != financial_identity
            for point in timestamp_points[1:]
        ):
            raise _fail()
        collapsed.append(reference)
    return tuple(collapsed)


def _microseconds(value: timedelta) -> int:
    return value.days * 86_400_000_000 + value.seconds * 1_000_000 + value.microseconds


def downsample_portfolio_history_points(
    points: object,
    *,
    cap: int = MAX_PORTFOLIO_HISTORY_POINTS,
) -> tuple[CanonicalPortfolioHistoryPoint, ...]:
    """Retain endpoints and the last point of each deterministic UTC time bucket."""

    if type(points) is not tuple or type(cap) is not int or isinstance(cap, bool) or cap < 2:
        raise _fail()
    if any(type(point) is not CanonicalPortfolioHistoryPoint for point in points):
        raise _fail()
    timestamps = tuple(point.timestamp for point in points)
    if timestamps != tuple(sorted(timestamps)) or len(timestamps) != len(set(timestamps)):
        raise _fail()
    if len(points) <= cap:
        return points

    first, last = points[0], points[-1]
    span = _microseconds(last.timestamp - first.timestamp)
    if span <= 0:
        raise _fail()
    interior_bucket_count = cap - 2
    buckets: dict[int, CanonicalPortfolioHistoryPoint] = {}
    for point in points[1:-1]:
        elapsed = _microseconds(point.timestamp - first.timestamp)
        bucket = min(interior_bucket_count - 1, elapsed * interior_bucket_count // span)
        buckets[bucket] = point
    selected = (first, *tuple(buckets[index] for index in sorted(buckets)), last)
    result = tuple(
        point
        for index, point in enumerate(selected)
        if index == 0 or point.timestamp != selected[index - 1].timestamp
    )
    if len(result) > cap:
        raise _fail()
    return result


def public_portfolio_history_points(
    points: tuple[CanonicalPortfolioHistoryPoint, ...],
) -> tuple[PortfolioHistoryPoint, ...]:
    """Remove persistence lineage without changing selected financial values."""

    return tuple(
        PortfolioHistoryPoint(
            timestamp=point.timestamp,
            cash_value=point.cash_value,
            investment_value=point.investment_value,
            liabilities_value=point.liabilities_value,
            net_worth_value=point.net_worth_value,
        )
        for point in points
    )


__all__ = [
    "MAX_PORTFOLIO_HISTORY_POINTS",
    "PortfolioHistorySelectionError",
    "canonicalize_portfolio_history_points",
    "downsample_portfolio_history_points",
    "portfolio_history_range_start",
    "public_portfolio_history_points",
    "validate_currency",
    "validate_nonblank",
    "validate_timestamp",
]
