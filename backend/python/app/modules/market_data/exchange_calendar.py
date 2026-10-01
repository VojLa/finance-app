"""Pure regular-session calendar policy for explicitly supported MICs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.modules.market_data.exchange_registry import ExchangeVenue, exchange_venue

_FIXTURE_YEARS = range(2025, 2028)


def _nth_weekday(year: int, month: int, weekday: int, occurrence: int) -> date:
    day = date(year, month, 1)
    day += timedelta(days=(weekday - day.weekday()) % 7 + 7 * (occurrence - 1))
    return day


def _last_weekday(year: int, month: int, weekday: int) -> date:
    day = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    return day - timedelta(days=(day.weekday() - weekday) % 7)


def _easter_sunday(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    correction = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * correction) // 451
    month = (h + correction - 7 * m + 114) // 31
    day = (h + correction - 7 * m + 114) % 31 + 1
    return date(year, month, day)


def _observed(day: date) -> date:
    return (
        day - timedelta(days=1)
        if day.weekday() == 5
        else day + timedelta(days=1)
        if day.weekday() == 6
        else day
    )


def _holidays(mic: str, year: int) -> frozenset[date]:
    easter = _easter_sunday(year)
    if mic in {"XNAS", "XNYS", "ARCX"}:
        fixed = {date(year, 1, 1), date(year, 6, 19), date(year, 7, 4), date(year, 12, 25)}
        return frozenset(
            {_observed(d) for d in fixed}
            | {
                _nth_weekday(year, 1, 0, 3),
                _nth_weekday(year, 2, 0, 3),
                easter - timedelta(days=2),
                _last_weekday(year, 5, 0),
                _nth_weekday(year, 9, 0, 1),
                _nth_weekday(year, 11, 3, 4),
            }
        )
    if mic == "XETR":
        return frozenset(
            {
                date(year, 1, 1),
                easter - timedelta(days=2),
                easter + timedelta(days=1),
                date(year, 5, 1),
                date(year, 12, 25),
                date(year, 12, 26),
            }
        )
    if mic == "XLON":
        return frozenset(
            {
                date(year, 1, 1),
                easter - timedelta(days=2),
                easter + timedelta(days=1),
                _nth_weekday(year, 5, 0, 1),
                _last_weekday(year, 5, 0),
                _last_weekday(year, 8, 0),
                date(year, 12, 25),
                date(year, 12, 26),
            }
        )
    if mic == "XPRA":
        return frozenset(
            {
                date(year, 1, 1),
                easter - timedelta(days=2),
                easter + timedelta(days=1),
                date(year, 5, 1),
                date(year, 5, 8),
                date(year, 7, 5),
                date(year, 7, 6),
                date(year, 9, 28),
                date(year, 10, 28),
                date(year, 11, 17),
                date(year, 12, 24),
                date(year, 12, 25),
                date(year, 12, 26),
            }
        )
    if mic == "XSWX":
        return frozenset(
            {
                date(year, 1, 1),
                date(year, 1, 2),
                easter - timedelta(days=2),
                easter + timedelta(days=1),
                date(year, 5, 1),
                date(year, 8, 1),
                date(year, 12, 25),
                date(year, 12, 26),
            }
        )
    if mic == "XTKS":
        return frozenset(
            {
                date(year, 1, 1),
                date(year, 1, 2),
                date(year, 1, 3),
                _nth_weekday(year, 1, 0, 2),
                date(year, 2, 11),
                date(year, 2, 23),
                date(year, 4, 29),
                date(year, 5, 3),
                date(year, 5, 4),
                date(year, 5, 5),
                _nth_weekday(year, 7, 0, 3),
                _nth_weekday(year, 9, 0, 3),
                _nth_weekday(year, 10, 0, 2),
                date(year, 11, 3),
                date(year, 11, 23),
                date(year, 12, 31),
            }
        )
    return frozenset()


@dataclass(frozen=True, slots=True)
class CalendarAssessment:
    status: str
    expected_previous_close: datetime | None
    next_session_at: datetime | None


def _close_on(venue: ExchangeVenue, day: date) -> datetime:
    return datetime.combine(day, venue.session_close, ZoneInfo(venue.timezone)).astimezone(UTC)


def _session_day(mic: str, day: date) -> bool:
    return day.year in _FIXTURE_YEARS and day.weekday() < 5 and day not in _holidays(mic, day.year)


def assess_market(
    mic: str | None, instant: datetime, *, asset_type: str | None = None
) -> CalendarAssessment:
    """Assess regular-session state at an aware instant; output close is UTC.

    ``asset_type="crypto"`` has no exchange calendar. Unsupported MICs stay
    explicit rather than receiving a guessed weekday schedule.
    """
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("instant must be timezone-aware")
    if asset_type and asset_type.strip().lower() == "crypto":
        return CalendarAssessment("not_applicable", None, None)
    venue = exchange_venue(mic)
    if venue is None:
        return CalendarAssessment("unknown_calendar", None, None)
    local = instant.astimezone(ZoneInfo(venue.timezone))
    previous = _previous_close(venue, local.date(), instant.astimezone(UTC))
    if local.year not in _FIXTURE_YEARS:
        return CalendarAssessment("unknown_calendar", previous, None)
    next_session = _next_session_open(venue, local.date(), instant.astimezone(UTC))
    if local.weekday() >= 5:
        return CalendarAssessment("weekend", previous, next_session)
    if local.date() in _holidays(venue.mic, local.year):
        return CalendarAssessment("holiday", previous, next_session)
    clock = local.timetz().replace(tzinfo=None)
    opened = venue.session_open <= clock < venue.session_close
    if venue.lunch_start is not None and venue.lunch_start <= clock < (
        venue.lunch_end or venue.lunch_start
    ):
        opened = False
    return CalendarAssessment(
        "open" if opened else "closed", previous, None if opened else next_session
    )


def _previous_close(
    venue: ExchangeVenue, local_day: date, utc_instant: datetime
) -> datetime | None:
    day = local_day
    for _ in range(8):
        if _session_day(venue.mic, day):
            close = _close_on(venue, day)
            if close <= utc_instant:
                return close
        day -= timedelta(days=1)
    return None


def _next_session_open(
    venue: ExchangeVenue, local_day: date, utc_instant: datetime
) -> datetime | None:
    day = local_day
    for _ in range(9):
        if _session_day(venue.mic, day):
            opened = datetime.combine(day, venue.session_open, ZoneInfo(venue.timezone)).astimezone(
                UTC
            )
            if opened > utc_instant:
                return opened
        day += timedelta(days=1)
    return None


def price_is_acceptable_for_market(
    *,
    mic: str | None,
    asset_type: str,
    observed_at: datetime,
    through: datetime,
    maximum_age: timedelta,
) -> bool:
    """Apply one freshness rule to planning and valuation evidence."""
    if (
        observed_at.tzinfo is not None
        or through.tzinfo is not None
        or not isinstance(maximum_age, timedelta)
        or maximum_age < timedelta(0)
        or observed_at > through
    ):
        return False
    if through - observed_at <= maximum_age:
        return True
    calendar = assess_market(mic, through.replace(tzinfo=UTC), asset_type=asset_type)
    return (
        calendar.status in {"closed", "weekend", "holiday"}
        and calendar.expected_previous_close is not None
        and observed_at.replace(tzinfo=UTC) >= calendar.expected_previous_close
    )


__all__ = ["CalendarAssessment", "assess_market", "price_is_acceptable_for_market"]
