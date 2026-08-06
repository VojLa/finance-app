from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest

from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.modules.portfolio_history.models import (
    CanonicalPortfolioHistoryPoint,
    PersistedPortfolioHistoryPoint,
    PortfolioHistoryRange,
)
from app.modules.portfolio_history.selection import (
    MAX_PORTFOLIO_HISTORY_POINTS,
    PortfolioHistorySelectionError,
    canonicalize_portfolio_history_points,
    downsample_portfolio_history_points,
    portfolio_history_range_start,
)

END = datetime(2024, 3, 31, 12, 30, 0, 123000)


def _persisted(
    timestamp: datetime = END,
    *,
    snapshot_id: object = "snapshot-a",
    user_id: object = "user-a",
    currency: object = "EUR",
    granularity: object = SnapshotGranularity.day,
    source: object = SnapshotSource.scheduled,
    calculation_version: object = 1,
    cash: object = Decimal("-50.000000"),
    investment: object = Decimal("100.000000"),
    liabilities: object = Decimal("25.000000"),
    total: object = Decimal("25.000000"),
) -> PersistedPortfolioHistoryPoint:
    return PersistedPortfolioHistoryPoint(
        snapshot_id=snapshot_id,
        user_id=user_id,
        timestamp=timestamp,
        granularity=granularity,
        source=source,
        currency=currency,
        cash_value=cash,
        portfolio_value=investment,
        liabilities_value=liabilities,
        total_net_worth=total,
        calculation_version=calculation_version,
    )


def _canonical(index: int) -> CanonicalPortfolioHistoryPoint:
    timestamp = datetime(2020, 1, 1) + timedelta(minutes=index * index + index)
    return CanonicalPortfolioHistoryPoint(
        snapshot_id=f"snapshot-{index:05d}",
        timestamp=timestamp,
        granularity=SnapshotGranularity.minute,
        source=SnapshotSource.scheduled,
        calculation_version=1,
        cash_value=Decimal("1.000000"),
        investment_value=Decimal("2.000000"),
        liabilities_value=Decimal("0.000000"),
        net_worth_value=Decimal("3.000000"),
    )


@pytest.mark.parametrize(
    ("history_range", "expected"),
    [
        (PortfolioHistoryRange.one_week, datetime(2024, 3, 24, 12, 30, 0, 123000)),
        (PortfolioHistoryRange.one_month, datetime(2024, 2, 29, 12, 30, 0, 123000)),
        (PortfolioHistoryRange.three_months, datetime(2023, 12, 31, 12, 30, 0, 123000)),
        (PortfolioHistoryRange.six_months, datetime(2023, 9, 30, 12, 30, 0, 123000)),
        (PortfolioHistoryRange.one_year, datetime(2023, 3, 31, 12, 30, 0, 123000)),
        (PortfolioHistoryRange.all, None),
    ],
)
def test_all_range_values_use_calendar_safe_boundaries(
    history_range: PortfolioHistoryRange,
    expected: datetime | None,
) -> None:
    assert portfolio_history_range_start(history_range, END) == expected


def test_calendar_year_handles_leap_day() -> None:
    assert portfolio_history_range_start(
        PortfolioHistoryRange.one_year,
        datetime(2024, 2, 29, 8, 0),
    ) == datetime(2023, 2, 28, 8, 0)


@pytest.mark.parametrize(
    "history_range,end",
    [
        ("1Y", END),
        (PortfolioHistoryRange.one_year, END.replace(tzinfo=UTC)),
        (PortfolioHistoryRange.one_year, END.replace(microsecond=123456)),
    ],
)
def test_invalid_range_or_end_fails_closed(
    history_range: object,
    end: datetime,
) -> None:
    with pytest.raises(PortfolioHistorySelectionError):
        portfolio_history_range_start(history_range, end)  # type: ignore[arg-type]


def test_valid_point_supports_negative_cash_and_net_worth_and_zero_liabilities() -> None:
    point = _persisted(
        cash=Decimal("-150.000000"),
        investment=Decimal("100.000000"),
        liabilities=Decimal("0.000000"),
        total=Decimal("-50.000000"),
    )

    result = canonicalize_portfolio_history_points(
        (point,),
        user_id="user-a",
        currency="EUR",
        start=END - timedelta(days=1),
        end=END,
    )

    assert result[0].cash_value == Decimal("-150.000000")
    assert result[0].net_worth_value == Decimal("-50.000000")


@pytest.mark.parametrize(
    "changes",
    [
        {"snapshot_id": ""},
        {"snapshot_id": " padded"},
        {"user_id": "user-b"},
        {"currency": "CZ"},
        {"currency": "eur"},
        {"granularity": "day"},
        {"source": "scheduled"},
        {"calculation_version": 0},
        {"calculation_version": True},
        {"cash": Decimal("NaN")},
        {"cash": Decimal("Infinity")},
        {"cash": Decimal("1.0000001")},
        {"cash": Decimal("1000000000000.000000")},
        {"investment": Decimal("-1.000000"), "total": Decimal("-76.000000")},
        {"liabilities": Decimal("-1.000000"), "total": Decimal("51.000000")},
        {"total": Decimal("25.000001")},
    ],
)
def test_malformed_persisted_point_fails_whole_series(changes: dict[str, object]) -> None:
    with pytest.raises(PortfolioHistorySelectionError):
        canonicalize_portfolio_history_points(
            (_persisted(**cast(Any, changes)),),
            user_id="user-a",
            currency="EUR",
            start=None,
            end=END,
        )


def test_future_or_out_of_range_dependency_result_fails_closed() -> None:
    for timestamp in (END + timedelta(milliseconds=1), END - timedelta(days=8)):
        with pytest.raises(PortfolioHistorySelectionError):
            canonicalize_portfolio_history_points(
                (_persisted(timestamp),),
                user_id="user-a",
                currency="EUR",
                start=END - timedelta(days=7),
                end=END,
            )


def test_identical_timestamp_prefers_granularity_then_snapshot_id() -> None:
    day = _persisted(granularity=SnapshotGranularity.day, snapshot_id="snapshot-day")
    minute_b = _persisted(
        granularity=SnapshotGranularity.minute,
        snapshot_id="snapshot-minute-b",
    )
    minute_a = _persisted(
        granularity=SnapshotGranularity.minute,
        snapshot_id="snapshot-minute-a",
    )

    result = canonicalize_portfolio_history_points(
        (day, minute_b, minute_a),
        user_id="user-a",
        currency="EUR",
        start=None,
        end=END,
    )

    assert len(result) == 1
    assert result[0].snapshot_id == "snapshot-minute-a"


@pytest.mark.parametrize(
    "changes",
    [
        {"cash": Decimal("-49.000000"), "total": Decimal("26.000000")},
        {"investment": Decimal("101.000000"), "total": Decimal("26.000000")},
        {"liabilities": Decimal("24.000000"), "total": Decimal("26.000000")},
        {"total": Decimal("24.000000")},
    ],
)
def test_conflicting_same_timestamp_finance_fails_closed(changes: dict[str, object]) -> None:
    with pytest.raises(PortfolioHistorySelectionError):
        canonicalize_portfolio_history_points(
            (
                _persisted(),
                _persisted(snapshot_id="snapshot-b", **cast(Any, changes)),
            ),
            user_id="user-a",
            currency="EUR",
            start=None,
            end=END,
        )


def test_canonicalization_orders_unique_timestamps_and_is_immutable() -> None:
    points = (
        _persisted(END, snapshot_id="later"),
        _persisted(END - timedelta(days=1), snapshot_id="earlier"),
    )
    result = canonicalize_portfolio_history_points(
        points,
        user_id="user-a",
        currency="EUR",
        start=None,
        end=END,
    )

    assert tuple(point.snapshot_id for point in result) == ("earlier", "later")
    with pytest.raises(FrozenInstanceError):
        result[0].snapshot_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("count", [0, 1, MAX_PORTFOLIO_HISTORY_POINTS])
def test_downsampling_preserves_every_point_at_or_below_cap(count: int) -> None:
    points = tuple(_canonical(index) for index in range(count))
    assert downsample_portfolio_history_points(points) == points


@pytest.mark.parametrize("count", [513, 5000])
def test_downsampling_is_deterministic_bounded_and_retains_endpoints(count: int) -> None:
    points = tuple(_canonical(index) for index in range(count))

    first = downsample_portfolio_history_points(points)
    second = downsample_portfolio_history_points(points)

    assert first == second
    assert first[0] is points[0]
    assert first[-1] is points[-1]
    assert len(first) <= MAX_PORTFOLIO_HISTORY_POINTS
    timestamps = tuple(point.timestamp for point in first)
    assert timestamps == tuple(sorted(timestamps))
    assert len(timestamps) == len(set(timestamps))


def test_downsampling_rejects_noncanonical_input() -> None:
    points = (_canonical(1), _canonical(0))
    with pytest.raises(PortfolioHistorySelectionError):
        downsample_portfolio_history_points(points)

    duplicate = (_canonical(0), replace(_canonical(1), timestamp=_canonical(0).timestamp))
    with pytest.raises(PortfolioHistorySelectionError):
        downsample_portfolio_history_points(duplicate)
