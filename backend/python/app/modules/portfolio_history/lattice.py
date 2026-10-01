"""Pure Prague-local bucket, range, retention, and OHLC contracts."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.modules.snapshot_history_contracts import HistoryPublicRange
from app.shared.numeric_serialization import serialize_money

PRAGUE_TIMEZONE_NAME = "Europe/Prague"
PRAGUE_TIMEZONE = ZoneInfo(PRAGUE_TIMEZONE_NAME)
MAX_PUBLIC_HISTORY_POINTS = 480
PORTFOLIO_HISTORY_LATTICE_POLICY_VERSION = 1
_MILLISECOND = timedelta(milliseconds=1)
_POSTGRES_INTEGER_MAX = 2_147_483_647
_CALENDAR_LATTICE_ANCHOR = date(1970, 1, 5)


class PortfolioHistoryLatticeError(ValueError):
    """Raised when a value cannot satisfy the immutable lattice contract."""


class HistoryResolution(StrEnum):
    minutes_30 = "30m"
    hours_2 = "2h"
    hours_6 = "6h"
    hours_12 = "12h"
    day_1 = "1d"
    days_2 = "2d"
    days_4 = "4d"
    days_8 = "8d"
    days_16 = "16d"
    days_32 = "32d"
    days_64 = "64d"
    days_128 = "128d"
    days_256 = "256d"
    days_512 = "512d"
    days_1024 = "1024d"
    days_2048 = "2048d"
    days_4096 = "4096d"
    days_8192 = "8192d"


_RESOLUTION_MINUTES = {
    HistoryResolution.minutes_30: 30,
    HistoryResolution.hours_2: 120,
    HistoryResolution.hours_6: 360,
    HistoryResolution.hours_12: 720,
    HistoryResolution.day_1: 1_440,
    HistoryResolution.days_2: 2_880,
    HistoryResolution.days_4: 5_760,
    HistoryResolution.days_8: 11_520,
    HistoryResolution.days_16: 23_040,
    HistoryResolution.days_32: 46_080,
    HistoryResolution.days_64: 92_160,
    HistoryResolution.days_128: 184_320,
    HistoryResolution.days_256: 368_640,
    HistoryResolution.days_512: 737_280,
    HistoryResolution.days_1024: 1_474_560,
    HistoryResolution.days_2048: 2_949_120,
    HistoryResolution.days_4096: 5_898_240,
    HistoryResolution.days_8192: 11_796_480,
}
_INTRADAY_RESOLUTIONS = {
    HistoryResolution.minutes_30,
    HistoryResolution.hours_2,
    HistoryResolution.hours_6,
    HistoryResolution.hours_12,
}
_CALENDAR_DAYS = {
    HistoryResolution.day_1: 1,
    HistoryResolution.days_2: 2,
    HistoryResolution.days_4: 4,
    HistoryResolution.days_8: 8,
    HistoryResolution.days_16: 16,
    HistoryResolution.days_32: 32,
    HistoryResolution.days_64: 64,
    HistoryResolution.days_128: 128,
    HistoryResolution.days_256: 256,
    HistoryResolution.days_512: 512,
    HistoryResolution.days_1024: 1_024,
    HistoryResolution.days_2048: 2_048,
    HistoryResolution.days_4096: 4_096,
    HistoryResolution.days_8192: 8_192,
}
_NEXT_RESOLUTION = {
    HistoryResolution.minutes_30: HistoryResolution.hours_2,
    HistoryResolution.hours_2: HistoryResolution.hours_6,
    HistoryResolution.hours_6: HistoryResolution.hours_12,
    HistoryResolution.hours_12: HistoryResolution.day_1,
    HistoryResolution.day_1: HistoryResolution.days_2,
    HistoryResolution.days_2: HistoryResolution.days_4,
    HistoryResolution.days_4: HistoryResolution.days_8,
    HistoryResolution.days_8: HistoryResolution.days_16,
    HistoryResolution.days_16: HistoryResolution.days_32,
    HistoryResolution.days_32: HistoryResolution.days_64,
    HistoryResolution.days_64: HistoryResolution.days_128,
    HistoryResolution.days_128: HistoryResolution.days_256,
    HistoryResolution.days_256: HistoryResolution.days_512,
    HistoryResolution.days_512: HistoryResolution.days_1024,
    HistoryResolution.days_1024: HistoryResolution.days_2048,
    HistoryResolution.days_2048: HistoryResolution.days_4096,
    HistoryResolution.days_4096: HistoryResolution.days_8192,
}
CORE_HISTORY_RESOLUTIONS = (
    HistoryResolution.minutes_30,
    HistoryResolution.hours_2,
    HistoryResolution.hours_6,
    HistoryResolution.hours_12,
    HistoryResolution.day_1,
    HistoryResolution.days_2,
    HistoryResolution.days_4,
    HistoryResolution.days_8,
    HistoryResolution.days_16,
    HistoryResolution.days_32,
)
LONG_TERM_HISTORY_RESOLUTIONS = tuple(
    resolution
    for resolution in HistoryResolution
    if _RESOLUTION_MINUTES[resolution] >= _RESOLUTION_MINUTES[HistoryResolution.days_8]
)
# ``ALL`` uses the ordered lattice from its finest tier. The first tier that
# covers the complete span under the public point cap owns the entire graph.
ALL_RANGE_HISTORY_RESOLUTIONS = tuple(HistoryResolution)
_RESOLUTION_LEVEL = {resolution: level for level, resolution in enumerate(HistoryResolution)}
_FIXED_RANGE_RESOLUTION = {
    HistoryPublicRange.one_day: HistoryResolution.minutes_30,
    HistoryPublicRange.one_week: HistoryResolution.hours_2,
    HistoryPublicRange.one_month: HistoryResolution.hours_6,
    HistoryPublicRange.three_months: HistoryResolution.hours_12,
    HistoryPublicRange.six_months: HistoryResolution.day_1,
    HistoryPublicRange.one_year: HistoryResolution.day_1,
    HistoryPublicRange.five_years: HistoryResolution.days_4,
    HistoryPublicRange.ten_years: HistoryResolution.days_8,
}
_FIXED_RANGE_SHIFT = {
    HistoryPublicRange.one_day: (0, 0, 1),
    HistoryPublicRange.one_week: (0, 0, 7),
    HistoryPublicRange.one_month: (0, 1, 0),
    HistoryPublicRange.three_months: (0, 3, 0),
    HistoryPublicRange.six_months: (0, 6, 0),
    HistoryPublicRange.one_year: (1, 0, 0),
    HistoryPublicRange.five_years: (5, 0, 0),
    HistoryPublicRange.ten_years: (10, 0, 0),
}
_RETENTION_HOURS = {
    HistoryResolution.minutes_30: 24,
}
_RETENTION_DAYS = {
    HistoryResolution.hours_2: 32,
    HistoryResolution.hours_6: 90,
    HistoryResolution.hours_12: 90,
    HistoryResolution.day_1: 400,
    HistoryResolution.days_2: 800,
}
_RETENTION_YEARS = {
    HistoryResolution.days_4: 6,
    HistoryResolution.days_8: 12,
}


@dataclass(frozen=True, slots=True)
class HistoryBucket:
    """One half-open bucket with UTC-naive millisecond boundaries."""

    resolution: HistoryResolution
    start: datetime
    end: datetime


@dataclass(frozen=True, slots=True)
class HistoryRangeSelection:
    """One public range through an inclusive UTC-naive timestamp."""

    history_range: HistoryPublicRange
    resolution: HistoryResolution
    start: datetime
    through: datetime
    maximum_point_count: int


@dataclass(frozen=True, slots=True)
class HistoryFinancialClose:
    """Exact financial state observed at one instant."""

    observed_at: datetime
    cash_value: Decimal
    investment_value: Decimal
    liabilities_value: Decimal
    net_worth_value: Decimal


@dataclass(frozen=True, slots=True)
class HistoryOhlcRollup:
    """Lossless first/net-worth-extrema/last summary; graph display uses ``close``."""

    bucket: HistoryBucket
    open: HistoryFinancialClose
    high: HistoryFinancialClose
    low: HistoryFinancialClose
    close: HistoryFinancialClose
    sample_count: int


def _fail() -> PortfolioHistoryLatticeError:
    return PortfolioHistoryLatticeError("Portfolio history lattice input is invalid.")


def _timestamp(value: object) -> datetime:
    if type(value) is not datetime or value.tzinfo is not None or value.microsecond % 1_000 != 0:
        raise _fail()
    return value


def _resolution(value: object) -> HistoryResolution:
    if type(value) is not HistoryResolution:
        raise _fail()
    return value


def resolution_minutes(value: HistoryResolution) -> int:
    return _RESOLUTION_MINUTES[_resolution(value)]


def resolution_level(value: HistoryResolution) -> int:
    return _RESOLUTION_LEVEL[_resolution(value)]


def _utc_aware(value: datetime) -> datetime:
    return _timestamp(value).replace(tzinfo=UTC)


def _utc_naive(value: datetime) -> datetime:
    result = value.astimezone(UTC).replace(tzinfo=None)
    return _timestamp(result)


def _local_midnight(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=PRAGUE_TIMEZONE)


def _calendar_bucket_start(value: date, days: int) -> date:
    anchor_ordinal = _CALENDAR_LATTICE_ANCHOR.toordinal()
    start_ordinal = anchor_ordinal + ((value.toordinal() - anchor_ordinal) // days) * days
    try:
        return date.fromordinal(start_ordinal)
    except ValueError as exc:
        raise _fail() from exc


def history_bucket(value: datetime, resolution: HistoryResolution) -> HistoryBucket:
    """Return the unique lattice bucket containing one UTC instant."""

    try:
        canonical_resolution = _resolution(resolution)
        utc_value = _utc_aware(value)
        local_value = utc_value.astimezone(PRAGUE_TIMEZONE)
        if canonical_resolution in _INTRADAY_RESOLUTIONS:
            local_start = _local_midnight(local_value.date())
            local_end = _local_midnight(local_value.date() + timedelta(days=1))
            day_start = local_start.astimezone(UTC)
            day_end = local_end.astimezone(UTC)
            span = timedelta(minutes=_RESOLUTION_MINUTES[canonical_resolution])
            bucket_index = (utc_value - day_start) // span
            bucket_start = day_start + bucket_index * span
            bucket_end = min(bucket_start + span, day_end)
        else:
            days = _CALENDAR_DAYS[canonical_resolution]
            start_date = _calendar_bucket_start(local_value.date(), days)
            end_date = date.fromordinal(start_date.toordinal() + days)
            bucket_start = _local_midnight(start_date).astimezone(UTC)
            bucket_end = _local_midnight(end_date).astimezone(UTC)
        result = HistoryBucket(
            resolution=canonical_resolution,
            start=_utc_naive(bucket_start),
            end=_utc_naive(bucket_end),
        )
        if not result.start <= _timestamp(value) < result.end:
            raise _fail()
        return result
    except (OverflowError, ValueError) as exc:
        raise _fail() from exc


def next_history_resolution(value: HistoryResolution) -> HistoryResolution | None:
    return _NEXT_RESOLUTION.get(_resolution(value))


def parent_history_bucket(value: HistoryBucket) -> HistoryBucket:
    """Return the immediate parent and prove exact child containment."""

    child = _validated_bucket(value)
    parent_resolution = next_history_resolution(child.resolution)
    if parent_resolution is None:
        raise _fail()
    parent = history_bucket(child.start, parent_resolution)
    if not parent.start <= child.start < child.end <= parent.end:
        raise _fail()
    return parent


def _validated_bucket(value: object) -> HistoryBucket:
    if type(value) is not HistoryBucket:
        raise _fail()
    resolution = _resolution(value.resolution)
    start = _timestamp(value.start)
    end = _timestamp(value.end)
    if start >= end or history_bucket(start, resolution) != value:
        raise _fail()
    return value


def history_buckets_between(
    start: datetime,
    end: datetime,
    resolution: HistoryResolution,
    *,
    limit: int | None = None,
) -> tuple[HistoryBucket, ...]:
    """Return buckets intersecting the half-open range ``start <= t < end``."""

    canonical_start = _timestamp(start)
    canonical_end = _timestamp(end)
    canonical_resolution = _resolution(resolution)
    if canonical_start >= canonical_end or (
        limit is not None and (type(limit) is not int or isinstance(limit, bool) or limit < 1)
    ):
        raise _fail()
    result: list[HistoryBucket] = []
    bucket = history_bucket(canonical_start, canonical_resolution)
    while bucket.start < canonical_end:
        result.append(bucket)
        if limit is not None and len(result) > limit:
            raise _fail()
        bucket = history_bucket(bucket.end, canonical_resolution)
    return tuple(result)


def _shift_local_calendar(
    value: datetime,
    *,
    years: int = 0,
    months: int = 0,
    days: int = 0,
) -> datetime:
    try:
        local_value = _utc_aware(value).astimezone(PRAGUE_TIMEZONE)
        month_index = local_value.year * 12 + local_value.month - 1 - years * 12 - months
        year, zero_month = divmod(month_index, 12)
        if year < 1 or year > 9999:
            raise _fail()
        month = zero_month + 1
        day = min(local_value.day, monthrange(year, month)[1])
        target_date = date(year, month, day) - timedelta(days=days)
        candidate = datetime.combine(
            target_date,
            local_value.timetz().replace(tzinfo=None),
            tzinfo=PRAGUE_TIMEZONE,
        ).replace(fold=local_value.fold)
        # A shifted wall time can land in the Prague spring gap. A UTC round trip
        # deterministically normalizes it to the first real instant after the gap.
        normalized = candidate.astimezone(UTC).astimezone(PRAGUE_TIMEZONE)
        return _utc_naive(normalized)
    except (OverflowError, ValueError) as exc:
        raise _fail() from exc


def _inclusive_range_end(value: datetime) -> datetime:
    canonical = _timestamp(value)
    try:
        return canonical + _MILLISECOND
    except OverflowError as exc:
        raise _fail() from exc


def _point_upper_bound(
    *,
    start: datetime,
    through: datetime,
    resolution: HistoryResolution,
    first_event_at: datetime | None,
) -> int:
    count = len(
        history_buckets_between(
            start,
            _inclusive_range_end(through),
            resolution,
            limit=MAX_PUBLIC_HISTORY_POINTS,
        )
    )
    if first_event_at is not None and start <= first_event_at <= through:
        count += 1
    return count


def select_history_range(
    history_range: HistoryPublicRange,
    *,
    through: datetime,
    first_event_at: datetime | None = None,
) -> HistoryRangeSelection:
    """Select one approved layer with a conservative 480-point upper bound."""

    if type(history_range) is not HistoryPublicRange:
        raise _fail()
    canonical_through = _timestamp(through)
    canonical_first = None if first_event_at is None else _timestamp(first_event_at)
    if canonical_first is not None and canonical_first > canonical_through:
        raise _fail()

    if history_range is HistoryPublicRange.all:
        if canonical_first is None:
            raise _fail()
        for candidate in ALL_RANGE_HISTORY_RESOLUTIONS:
            start = canonical_first
            try:
                point_count = _point_upper_bound(
                    start=start,
                    through=canonical_through,
                    resolution=candidate,
                    first_event_at=canonical_first,
                )
            except PortfolioHistoryLatticeError:
                continue
            if point_count <= MAX_PUBLIC_HISTORY_POINTS:
                return HistoryRangeSelection(
                    history_range=history_range,
                    resolution=candidate,
                    start=start,
                    through=canonical_through,
                    maximum_point_count=point_count,
                )
        raise _fail()

    resolution = _FIXED_RANGE_RESOLUTION[history_range]
    years, months, days = _FIXED_RANGE_SHIFT[history_range]
    shifted = _shift_local_calendar(
        canonical_through,
        years=years,
        months=months,
        days=days,
    )
    start = history_bucket(shifted, resolution).start
    point_count = _point_upper_bound(
        start=start,
        through=canonical_through,
        resolution=resolution,
        first_event_at=(
            canonical_first
            if canonical_first is not None and start <= canonical_first <= canonical_through
            else None
        ),
    )
    if point_count > MAX_PUBLIC_HISTORY_POINTS:
        raise _fail()
    return HistoryRangeSelection(
        history_range=history_range,
        resolution=resolution,
        start=start,
        through=canonical_through,
        maximum_point_count=point_count,
    )


def retention_cutoff(
    resolution: HistoryResolution,
    *,
    through: datetime,
) -> datetime | None:
    """Return an aligned cutoff; layers at 16 days and above are indefinite."""

    canonical_resolution = _resolution(resolution)
    canonical_through = _timestamp(through)
    if hours := _RETENTION_HOURS.get(canonical_resolution):
        try:
            shifted = canonical_through - timedelta(hours=hours)
        except OverflowError as exc:
            raise _fail() from exc
    elif days := _RETENTION_DAYS.get(canonical_resolution):
        shifted = _shift_local_calendar(canonical_through, days=days)
    elif years := _RETENTION_YEARS.get(canonical_resolution):
        shifted = _shift_local_calendar(canonical_through, years=years)
    else:
        return None
    return history_bucket(shifted, canonical_resolution).start


def is_history_point_retained(
    point_at: datetime,
    *,
    resolution: HistoryResolution,
    through: datetime,
    first_event_at: datetime,
) -> bool:
    """Apply retention while preserving the exact first-event boundary point."""

    point = _timestamp(point_at)
    first = _timestamp(first_event_at)
    canonical_through = _timestamp(through)
    if first > canonical_through or point > canonical_through:
        raise _fail()
    if point == first:
        return True
    if point < first:
        return False
    cutoff = retention_cutoff(resolution, through=canonical_through)
    return cutoff is None or point >= cutoff


def _money(value: object) -> Decimal:
    if type(value) is not Decimal:
        raise _fail()
    try:
        canonical = serialize_money(value)
    except ValueError as exc:
        raise _fail() from exc
    return Decimal(canonical)


def _close(value: object, *, bucket: HistoryBucket) -> HistoryFinancialClose:
    if type(value) is not HistoryFinancialClose:
        raise _fail()
    observed_at = _timestamp(value.observed_at)
    cash = _money(value.cash_value)
    investment = _money(value.investment_value)
    liabilities = _money(value.liabilities_value)
    net_worth = _money(value.net_worth_value)
    if (
        not bucket.start <= observed_at < bucket.end
        or investment < 0
        or liabilities < 0
        or cash + investment - liabilities != net_worth
    ):
        raise _fail()
    return HistoryFinancialClose(
        observed_at=observed_at,
        cash_value=cash,
        investment_value=investment,
        liabilities_value=liabilities,
        net_worth_value=net_worth,
    )


def rollup_history_closes(
    bucket: HistoryBucket,
    closes: tuple[HistoryFinancialClose, ...],
) -> HistoryOhlcRollup:
    """Build OHLC from exact samples without averaging any financial value."""

    canonical_bucket = _validated_bucket(bucket)
    if type(closes) is not tuple or not closes:
        raise _fail()
    values = tuple(_close(value, bucket=canonical_bucket) for value in closes)
    timestamps = tuple(value.observed_at for value in values)
    if timestamps != tuple(sorted(timestamps)) or len(set(timestamps)) != len(timestamps):
        raise _fail()
    return HistoryOhlcRollup(
        bucket=canonical_bucket,
        open=values[0],
        high=max(values, key=lambda value: value.net_worth_value),
        low=min(values, key=lambda value: value.net_worth_value),
        close=values[-1],
        sample_count=len(values),
    )


def _rollup(value: object) -> HistoryOhlcRollup:
    if type(value) is not HistoryOhlcRollup:
        raise _fail()
    bucket = _validated_bucket(value.bucket)
    if (
        type(value.sample_count) is not int
        or isinstance(value.sample_count, bool)
        or not 1 <= value.sample_count <= _POSTGRES_INTEGER_MAX
    ):
        raise _fail()
    open_value = _close(value.open, bucket=bucket)
    high = _close(value.high, bucket=bucket)
    low = _close(value.low, bucket=bucket)
    close = _close(value.close, bucket=bucket)
    if (
        open_value.observed_at > close.observed_at
        or not open_value.observed_at <= high.observed_at <= close.observed_at
        or not open_value.observed_at <= low.observed_at <= close.observed_at
        or high.net_worth_value < max(open_value.net_worth_value, close.net_worth_value)
        or low.net_worth_value > min(open_value.net_worth_value, close.net_worth_value)
    ):
        raise _fail()
    return value


def rollup_history_children(
    parent_bucket: HistoryBucket,
    children: tuple[HistoryOhlcRollup, ...],
) -> HistoryOhlcRollup:
    """Combine immediate children while retaining their true extrema and close."""

    parent = _validated_bucket(parent_bucket)
    if type(children) is not tuple or not children:
        raise _fail()
    expected_child_resolution = next(
        (
            child
            for child, candidate_parent in _NEXT_RESOLUTION.items()
            if candidate_parent is parent.resolution
        ),
        None,
    )
    if expected_child_resolution is None:
        raise _fail()
    canonical = tuple(_rollup(value) for value in children)
    previous_end: datetime | None = None
    for index, child in enumerate(canonical):
        if (
            child.bucket.resolution is not expected_child_resolution
            or parent_history_bucket(child.bucket) != parent
            or (index == 0 and child.bucket.start != parent.start)
            or (previous_end is not None and child.bucket.start != previous_end)
        ):
            raise _fail()
        previous_end = child.bucket.end
    if previous_end != parent.end:
        raise _fail()
    sample_count = sum(value.sample_count for value in canonical)
    if sample_count > _POSTGRES_INTEGER_MAX:
        raise _fail()
    return HistoryOhlcRollup(
        bucket=parent,
        open=canonical[0].open,
        high=max((value.high for value in canonical), key=lambda value: value.net_worth_value),
        low=min((value.low for value in canonical), key=lambda value: value.net_worth_value),
        close=canonical[-1].close,
        sample_count=sample_count,
    )


__all__ = [
    "ALL_RANGE_HISTORY_RESOLUTIONS",
    "CORE_HISTORY_RESOLUTIONS",
    "LONG_TERM_HISTORY_RESOLUTIONS",
    "MAX_PUBLIC_HISTORY_POINTS",
    "PORTFOLIO_HISTORY_LATTICE_POLICY_VERSION",
    "PRAGUE_TIMEZONE_NAME",
    "HistoryBucket",
    "HistoryFinancialClose",
    "HistoryOhlcRollup",
    "HistoryPublicRange",
    "HistoryRangeSelection",
    "HistoryResolution",
    "PortfolioHistoryLatticeError",
    "history_bucket",
    "history_buckets_between",
    "is_history_point_retained",
    "next_history_resolution",
    "parent_history_bucket",
    "resolution_level",
    "resolution_minutes",
    "retention_cutoff",
    "rollup_history_children",
    "rollup_history_closes",
    "select_history_range",
]
