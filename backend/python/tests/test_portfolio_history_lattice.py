from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from zoneinfo import ZoneInfo

import pytest

from app.modules.portfolio_history.lattice import (
    CORE_HISTORY_RESOLUTIONS,
    LONG_TERM_HISTORY_RESOLUTIONS,
    MAX_PUBLIC_HISTORY_POINTS,
    PORTFOLIO_HISTORY_LATTICE_POLICY_VERSION,
    PRAGUE_TIMEZONE_NAME,
    HistoryFinancialClose,
    HistoryOhlcRollup,
    HistoryPublicRange,
    HistoryResolution,
    PortfolioHistoryLatticeError,
    history_bucket,
    history_buckets_between,
    is_history_point_retained,
    next_history_resolution,
    parent_history_bucket,
    resolution_level,
    resolution_minutes,
    retention_cutoff,
    rollup_history_children,
    rollup_history_closes,
    select_history_range,
)

PRAGUE = ZoneInfo(PRAGUE_TIMEZONE_NAME)


def _utc(local: datetime) -> datetime:
    assert local.tzinfo is not None
    return local.astimezone(UTC).replace(tzinfo=None)


def _local_date(value: datetime) -> date:
    return value.replace(tzinfo=UTC).astimezone(PRAGUE).date()


def _close(
    observed_at: datetime,
    net_worth: str,
    *,
    investment: str = "0.000000",
    liabilities: str = "0.000000",
) -> HistoryFinancialClose:
    investment_value = Decimal(investment)
    liabilities_value = Decimal(liabilities)
    net_worth_value = Decimal(net_worth)
    return HistoryFinancialClose(
        observed_at=observed_at,
        cash_value=net_worth_value - investment_value + liabilities_value,
        investment_value=investment_value,
        liabilities_value=liabilities_value,
        net_worth_value=net_worth_value,
    )


def test_resolution_lattice_is_exact_and_nested() -> None:
    resolutions = tuple(HistoryResolution)
    assert PORTFOLIO_HISTORY_LATTICE_POLICY_VERSION == 1
    assert CORE_HISTORY_RESOLUTIONS == resolutions[:10]
    assert LONG_TERM_HISTORY_RESOLUTIONS == resolutions[7:]
    assert [resolution_level(value) for value in resolutions] == list(range(len(resolutions)))
    assert [resolution_minutes(value) for value in resolutions] == [
        30,
        120,
        360,
        720,
        1_440,
        2_880,
        5_760,
        11_520,
        23_040,
        46_080,
        92_160,
        184_320,
        368_640,
        737_280,
        1_474_560,
        2_949_120,
        5_898_240,
        11_796_480,
    ]
    assert [next_history_resolution(value) for value in resolutions] == [
        *resolutions[1:],
        None,
    ]

    child = history_bucket(datetime(2026, 8, 20, 12, 34, 56), resolutions[0])
    while (parent_resolution := next_history_resolution(child.resolution)) is not None:
        parent = parent_history_bucket(child)
        assert parent.resolution is parent_resolution
        assert parent.start <= child.start < child.end <= parent.end
        child = parent


@pytest.mark.parametrize(
    ("local_day", "expected_half_hours"),
    [
        (date(2024, 3, 31), 46),
        (date(2024, 10, 27), 50),
        (date(2025, 3, 30), 46),
        (date(2025, 10, 26), 50),
    ],
)
def test_prague_dst_days_iterate_on_utc_timeline_without_losing_fold(
    local_day: date,
    expected_half_hours: int,
) -> None:
    local_midnight = datetime.combine(local_day, datetime.min.time(), tzinfo=PRAGUE)
    next_midnight = datetime.combine(
        local_day + timedelta(days=1), datetime.min.time(), tzinfo=PRAGUE
    )
    start = _utc(local_midnight)
    end = _utc(next_midnight)
    buckets = history_buckets_between(start, end, HistoryResolution.minutes_30)

    assert len(buckets) == expected_half_hours
    assert buckets[0].start == start
    assert buckets[-1].end == end
    assert all(left.end == right.start for left, right in pairwise(buckets))

    for half_hour in buckets:
        child = half_hour
        while child.resolution is not HistoryResolution.day_1:
            parent = parent_history_bucket(child)
            assert parent.start <= child.start < child.end <= parent.end
            child = parent
        assert child.start == start
        assert child.end == end


def test_fall_fold_contains_both_local_0230_instants_as_distinct_buckets() -> None:
    first = datetime(2024, 10, 27, 0, 30)
    second = datetime(2024, 10, 27, 1, 30)
    first_local = first.replace(tzinfo=UTC).astimezone(PRAGUE)
    second_local = second.replace(tzinfo=UTC).astimezone(PRAGUE)

    assert (first_local.hour, first_local.minute, first_local.fold) == (2, 30, 0)
    assert (second_local.hour, second_local.minute, second_local.fold) == (2, 30, 1)
    assert history_bucket(first, HistoryResolution.minutes_30).start == first
    assert history_bucket(second, HistoryResolution.minutes_30).start == second


def test_ordinary_prague_day_has_48_half_hours() -> None:
    day = history_bucket(datetime(2026, 8, 20, 12), HistoryResolution.day_1)
    assert len(history_buckets_between(day.start, day.end, HistoryResolution.minutes_30)) == 48


@pytest.mark.parametrize(
    "resolution",
    [
        HistoryResolution.days_2,
        HistoryResolution.days_4,
        HistoryResolution.days_8,
        HistoryResolution.days_16,
        HistoryResolution.days_32,
    ],
)
def test_calendar_parents_use_1970_01_05_local_monday_anchor(
    resolution: HistoryResolution,
) -> None:
    days = resolution_minutes(resolution) // 1_440
    anchor = date(1970, 1, 5)
    anchor_utc = _utc(datetime(1970, 1, 5, tzinfo=PRAGUE))
    at_anchor = history_bucket(anchor_utc, resolution)
    assert _local_date(at_anchor.start) == anchor
    assert _local_date(at_anchor.end) == anchor + timedelta(days=days)

    before_anchor = history_bucket(_utc(datetime(1970, 1, 4, 12, tzinfo=PRAGUE)), resolution)
    assert _local_date(before_anchor.start) == anchor - timedelta(days=days)
    assert _local_date(before_anchor.end) == anchor

    current = history_bucket(datetime(2026, 8, 20, 12), resolution)
    expected_ordinal = (
        anchor.toordinal() + ((date(2026, 8, 20).toordinal() - anchor.toordinal()) // days) * days
    )
    assert _local_date(current.start).toordinal() == expected_ordinal
    assert _local_date(current.end).toordinal() == expected_ordinal + days


def test_leap_day_is_one_complete_local_calendar_bucket() -> None:
    leap_day = history_bucket(
        _utc(datetime(2024, 2, 29, 12, tzinfo=PRAGUE)),
        HistoryResolution.day_1,
    )
    assert _local_date(leap_day.start) == date(2024, 2, 29)
    assert _local_date(leap_day.end) == date(2024, 3, 1)


@pytest.mark.parametrize(
    ("history_range", "resolution"),
    [
        (HistoryPublicRange.one_day, HistoryResolution.minutes_30),
        (HistoryPublicRange.one_week, HistoryResolution.hours_2),
        (HistoryPublicRange.one_month, HistoryResolution.hours_6),
        (HistoryPublicRange.three_months, HistoryResolution.hours_12),
        (HistoryPublicRange.six_months, HistoryResolution.day_1),
        (HistoryPublicRange.one_year, HistoryResolution.day_1),
        (HistoryPublicRange.five_years, HistoryResolution.days_4),
        (HistoryPublicRange.ten_years, HistoryResolution.days_8),
    ],
)
def test_fixed_public_ranges_select_approved_resolution_below_cap(
    history_range: HistoryPublicRange,
    resolution: HistoryResolution,
) -> None:
    result = select_history_range(
        history_range,
        through=datetime(2026, 8, 20, 12, 34, 56),
        first_event_at=datetime(2000, 1, 1),
    )
    assert result.resolution is resolution
    assert result.start == history_bucket(result.start, resolution).start
    assert 1 <= result.maximum_point_count <= MAX_PUBLIC_HISTORY_POINTS


def test_month_and_year_ranges_use_calendar_clamping_including_leap_year() -> None:
    through = _utc(datetime(2024, 3, 31, 12, 15, tzinfo=PRAGUE))
    month = select_history_range(HistoryPublicRange.one_month, through=through)
    year = select_history_range(
        HistoryPublicRange.one_year,
        through=_utc(datetime(2024, 2, 29, 12, 15, tzinfo=PRAGUE)),
    )

    assert _local_date(month.start) == date(2024, 2, 29)
    assert _local_date(year.start) == date(2023, 2, 28)


@pytest.mark.parametrize(
    "through",
    [
        datetime(2024, 3, 31, 21, 59, 59, 999000),
        datetime(2024, 10, 27, 22, 59, 59, 999000),
        datetime(2025, 3, 30, 21, 59, 59, 999000),
        datetime(2025, 10, 26, 22, 59, 59, 999000),
        datetime(2024, 2, 29, 12),
    ],
)
def test_every_fixed_range_has_a_conservative_maximum_below_480(
    through: datetime,
) -> None:
    for history_range in HistoryPublicRange:
        if history_range is HistoryPublicRange.all:
            continue
        selection = select_history_range(
            history_range,
            through=through,
            first_event_at=datetime(2000, 1, 1),
        )
        assert selection.maximum_point_count <= MAX_PUBLIC_HISTORY_POINTS


@pytest.mark.parametrize(
    ("first_event", "expected_resolution"),
    [
        (datetime(2020, 1, 1), HistoryResolution.days_8),
        (datetime(2010, 1, 1), HistoryResolution.days_16),
        (datetime(1995, 1, 1), HistoryResolution.days_32),
    ],
)
def test_all_selects_finest_long_term_layer_below_cap(
    first_event: datetime,
    expected_resolution: HistoryResolution,
) -> None:
    selection = select_history_range(
        HistoryPublicRange.all,
        through=datetime(2026, 8, 20),
        first_event_at=first_event,
    )
    assert selection.start == first_event
    assert selection.resolution is expected_resolution
    assert selection.maximum_point_count <= MAX_PUBLIC_HISTORY_POINTS


@pytest.mark.parametrize(
    ("first_event", "expected_resolution"),
    [
        (datetime(1976, 1, 1), HistoryResolution.days_64),
        (datetime(1926, 1, 1), HistoryResolution.days_128),
    ],
)
def test_all_extends_nested_long_term_layers_for_50_and_100_year_history(
    first_event: datetime,
    expected_resolution: HistoryResolution,
) -> None:
    selection = select_history_range(
        HistoryPublicRange.all,
        through=datetime(2026, 8, 20),
        first_event_at=first_event,
    )
    assert selection.resolution is expected_resolution
    assert selection.maximum_point_count <= MAX_PUBLIC_HISTORY_POINTS


@pytest.mark.parametrize(
    ("resolution", "days"),
    [
        (HistoryResolution.hours_2, 32),
        (HistoryResolution.hours_6, 90),
        (HistoryResolution.hours_12, 90),
        (HistoryResolution.day_1, 400),
        (HistoryResolution.days_2, 800),
    ],
)
def test_day_retention_cutoffs_are_calendar_shifted_and_bucket_aligned(
    resolution: HistoryResolution,
    days: int,
) -> None:
    through = _utc(datetime(2026, 8, 20, 14, 15, tzinfo=PRAGUE))
    shifted = _utc(datetime(2026, 8, 20, 14, 15, tzinfo=PRAGUE) - timedelta(days=days))
    assert (
        retention_cutoff(resolution, through=through) == history_bucket(shifted, resolution).start
    )


def test_thirty_minute_retention_is_one_rolling_day_and_bucket_aligned() -> None:
    through = datetime(2026, 8, 20, 12, 15)
    shifted = through - timedelta(hours=24)
    assert (
        retention_cutoff(HistoryResolution.minutes_30, through=through)
        == history_bucket(shifted, HistoryResolution.minutes_30).start
    )


def test_year_retention_is_leap_safe_and_long_term_layers_are_indefinite() -> None:
    through = _utc(datetime(2024, 2, 29, 12, 15, tzinfo=PRAGUE))
    assert (
        retention_cutoff(HistoryResolution.days_4, through=through)
        == history_bucket(
            _utc(datetime(2018, 2, 28, 12, 15, tzinfo=PRAGUE)),
            HistoryResolution.days_4,
        ).start
    )
    assert (
        retention_cutoff(HistoryResolution.days_8, through=through)
        == history_bucket(
            _utc(datetime(2012, 2, 29, 12, 15, tzinfo=PRAGUE)),
            HistoryResolution.days_8,
        ).start
    )
    assert retention_cutoff(HistoryResolution.days_16, through=through) is None
    assert retention_cutoff(HistoryResolution.days_32, through=through) is None


def test_first_event_boundary_is_retained_after_detail_expiry() -> None:
    first = datetime(2020, 1, 1)
    through = datetime(2026, 8, 20)
    assert is_history_point_retained(
        first,
        resolution=HistoryResolution.minutes_30,
        through=through,
        first_event_at=first,
    )
    assert not is_history_point_retained(
        first + timedelta(minutes=30),
        resolution=HistoryResolution.minutes_30,
        through=through,
        first_event_at=first,
    )
    assert is_history_point_retained(
        through - timedelta(days=1),
        resolution=HistoryResolution.minutes_30,
        through=through,
        first_event_at=first,
    )
    assert not is_history_point_retained(
        first - timedelta(milliseconds=1),
        resolution=HistoryResolution.minutes_30,
        through=through,
        first_event_at=first,
    )


def test_ohlc_uses_first_true_extrema_and_last_without_averaging() -> None:
    bucket = history_bucket(datetime(2026, 8, 20, 12), HistoryResolution.hours_2)
    closes = (
        _close(bucket.start, "10.000000"),
        _close(bucket.start + timedelta(minutes=30), "30.000000"),
        _close(bucket.start + timedelta(minutes=60), "-5.000000"),
        _close(bucket.start + timedelta(minutes=90), "20.000000"),
    )
    rollup = rollup_history_closes(bucket, closes)

    assert rollup.open == closes[0]
    assert rollup.high == closes[1]
    assert rollup.low == closes[2]
    assert rollup.close == closes[3]
    assert rollup.close.net_worth_value == Decimal("20.000000")
    assert rollup.close.net_worth_value != sum(
        (value.net_worth_value for value in closes), Decimal(0)
    ) / len(closes)
    assert rollup.sample_count == 4


def test_ohlc_equal_extrema_choose_earliest_sample_deterministically() -> None:
    bucket = history_bucket(datetime(2026, 8, 20, 12), HistoryResolution.hours_2)
    first = _close(bucket.start, "10.000000")
    second = _close(bucket.start + timedelta(minutes=30), "10.000000")
    rollup = rollup_history_closes(bucket, (first, second))
    assert rollup.high == first
    assert rollup.low == first
    assert rollup.high.observed_at == first.observed_at
    assert rollup.close == second


def test_parent_rollup_preserves_child_extrema_close_and_sample_count() -> None:
    parent = history_bucket(datetime(2026, 8, 20, 12), HistoryResolution.hours_2)
    child_buckets = history_buckets_between(
        parent.start,
        parent.end,
        HistoryResolution.minutes_30,
    )
    child_values = ("10.000000", "40.000000", "-2.000000", "25.000000")
    children = tuple(
        rollup_history_closes(bucket, (_close(bucket.start, value),))
        for bucket, value in zip(child_buckets, child_values, strict=True)
    )
    rollup = rollup_history_children(parent, children)

    assert rollup.open.net_worth_value == Decimal("10.000000")
    assert rollup.high.net_worth_value == Decimal("40.000000")
    assert rollup.low.net_worth_value == Decimal("-2.000000")
    assert rollup.close.net_worth_value == Decimal("25.000000")
    assert rollup.sample_count == 4


@pytest.mark.parametrize("local_day", [date(2024, 3, 31), date(2024, 10, 27)])
def test_last_partial_dst_parent_rolls_up_only_its_real_children(local_day: date) -> None:
    day = history_bucket(
        _utc(datetime.combine(local_day, datetime.min.time(), tzinfo=PRAGUE)),
        HistoryResolution.day_1,
    )
    half_hours = history_buckets_between(
        day.start,
        day.end,
        HistoryResolution.minutes_30,
    )
    final_parent = parent_history_bucket(half_hours[-1])
    children = tuple(
        rollup_history_closes(bucket, (_close(bucket.start, "1.000000"),))
        for bucket in half_hours
        if parent_history_bucket(bucket) == final_parent
    )

    assert len(children) == 2
    assert final_parent.end == day.end
    assert rollup_history_children(final_parent, children).sample_count == 2
    for incomplete in (children[1:], children[:-1]):
        with pytest.raises(PortfolioHistoryLatticeError):
            rollup_history_children(final_parent, incomplete)


@pytest.mark.parametrize(
    "closes",
    [
        (),
        (
            _close(datetime(2026, 8, 20, 12, 30), "1.000000"),
            _close(datetime(2026, 8, 20, 12), "2.000000"),
        ),
        (
            _close(datetime(2026, 8, 20, 12), "1.000000"),
            _close(datetime(2026, 8, 20, 12), "2.000000"),
        ),
        (_close(datetime(2026, 8, 20, 14), "1.000000"),),
    ],
)
def test_ohlc_rejects_empty_unsorted_duplicate_or_outside_samples(
    closes: tuple[HistoryFinancialClose, ...],
) -> None:
    bucket = history_bucket(datetime(2026, 8, 20, 12), HistoryResolution.hours_2)
    with pytest.raises(PortfolioHistoryLatticeError):
        rollup_history_closes(bucket, closes)


def test_ohlc_rejects_noncanonical_or_incoherent_money() -> None:
    bucket = history_bucket(datetime(2026, 8, 20, 12), HistoryResolution.hours_2)
    exact = _close(bucket.start, "1.000000")
    invalid = (
        replace(exact, cash_value=Decimal("1.0000001")),
        replace(exact, investment_value=Decimal("-1.000000"), cash_value=Decimal("2.000000")),
        replace(exact, net_worth_value=Decimal("2.000000")),
    )
    for close in invalid:
        with pytest.raises(PortfolioHistoryLatticeError):
            rollup_history_closes(bucket, (close,))


def test_invalid_timestamp_enum_range_and_immutable_models_fail_closed() -> None:
    with pytest.raises(PortfolioHistoryLatticeError):
        history_bucket(datetime(2026, 1, 1, tzinfo=UTC), HistoryResolution.day_1)
    with pytest.raises(PortfolioHistoryLatticeError):
        history_bucket(datetime(2026, 1, 1, microsecond=1), HistoryResolution.day_1)
    with pytest.raises(PortfolioHistoryLatticeError):
        history_bucket(datetime(2026, 1, 1), "1d")  # type: ignore[arg-type]
    with pytest.raises(PortfolioHistoryLatticeError):
        history_buckets_between(
            datetime(2026, 1, 2),
            datetime(2026, 1, 1),
            HistoryResolution.day_1,
        )
    with pytest.raises(PortfolioHistoryLatticeError):
        select_history_range(
            HistoryPublicRange.all,
            through=datetime(2026, 1, 1),
        )
    with pytest.raises(PortfolioHistoryLatticeError):
        select_history_range(
            HistoryPublicRange.all,
            through=datetime(2026, 1, 1),
            first_event_at=datetime(2026, 1, 2),
        )

    bucket = history_bucket(datetime(2026, 1, 1), HistoryResolution.day_1)
    with pytest.raises(FrozenInstanceError):
        bucket.start = datetime(2025, 1, 1)  # type: ignore[misc]


@pytest.mark.parametrize(
    "boundary",
    [datetime.min, datetime.max.replace(microsecond=999_000)],
)
@pytest.mark.parametrize(
    "resolution",
    [
        HistoryResolution.minutes_30,
        HistoryResolution.day_1,
        HistoryResolution.days_8192,
    ],
)
def test_timestamp_bounds_fail_closed_without_raw_datetime_overflow(
    boundary: datetime,
    resolution: HistoryResolution,
) -> None:
    with pytest.raises(PortfolioHistoryLatticeError):
        history_bucket(boundary, resolution)

    if resolution is HistoryResolution.days_8192:
        assert retention_cutoff(resolution, through=boundary) is None
    else:
        with pytest.raises(PortfolioHistoryLatticeError):
            retention_cutoff(resolution, through=boundary)


def test_parent_rejects_top_level_and_children_reject_wrong_layer_or_order() -> None:
    top = history_bucket(datetime(2026, 1, 1), HistoryResolution.days_8192)
    with pytest.raises(PortfolioHistoryLatticeError):
        parent_history_bucket(top)

    parent = history_bucket(datetime(2026, 8, 20, 12), HistoryResolution.hours_2)
    children = tuple(
        rollup_history_closes(bucket, (_close(bucket.start, "1.000000"),))
        for bucket in history_buckets_between(
            parent.start,
            parent.end,
            HistoryResolution.minutes_30,
        )
    )
    with pytest.raises(PortfolioHistoryLatticeError):
        rollup_history_children(parent, tuple(reversed(children)))
    for incomplete in (children[1:], children[:2] + children[3:], children[:-1]):
        with pytest.raises(PortfolioHistoryLatticeError):
            rollup_history_children(parent, incomplete)
    wrong = rollup_history_closes(parent, (_close(parent.start, "1.000000"),))
    with pytest.raises(PortfolioHistoryLatticeError):
        rollup_history_children(parent, (wrong,))


def test_rollup_contract_is_immutable() -> None:
    bucket = history_bucket(datetime(2026, 8, 20, 12), HistoryResolution.hours_2)
    rollup = rollup_history_closes(bucket, (_close(bucket.start, "1.000000"),))
    assert isinstance(rollup, HistoryOhlcRollup)
    with pytest.raises(FrozenInstanceError):
        rollup.sample_count = 2  # type: ignore[misc]


def test_tampered_child_extrema_outside_open_close_interval_fail() -> None:
    parent = history_bucket(datetime(2026, 8, 20, 12), HistoryResolution.hours_2)
    children = tuple(
        rollup_history_closes(bucket, (_close(bucket.start, "1.000000"),))
        for bucket in history_buckets_between(
            parent.start,
            parent.end,
            HistoryResolution.minutes_30,
        )
    )
    first = children[0]
    tampered = replace(
        first,
        high=replace(first.high, observed_at=first.bucket.end - timedelta(milliseconds=1)),
    )
    with pytest.raises(PortfolioHistoryLatticeError):
        rollup_history_children(parent, (tampered, *children[1:]))
