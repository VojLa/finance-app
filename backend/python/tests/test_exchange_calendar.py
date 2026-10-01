from datetime import UTC, datetime

import pytest

from app.modules.market_data.exchange_calendar import assess_market
from app.modules.market_data.exchange_registry import exchange_venue


def test_registry_contains_exact_supported_calendar_mics() -> None:
    venues = [
        exchange_venue(mic)
        for mic in ("XNAS", "XNYS", "ARCX", "XETR", "XLON", "XPRA", "XSWX", "XTKS")
    ]
    assert all(venue is not None for venue in venues)
    assert [venue.mic for venue in venues if venue is not None] == [
        "XNAS",
        "XNYS",
        "ARCX",
        "XETR",
        "XLON",
        "XPRA",
        "XSWX",
        "XTKS",
    ]
    assert exchange_venue("XFRA") is None


def test_regular_session_open_and_closed() -> None:
    assert assess_market("XNAS", datetime(2026, 9, 30, 14, 0, tzinfo=UTC)).status == "open"
    assert assess_market("XNAS", datetime(2026, 9, 30, 21, 0, tzinfo=UTC)).status == "closed"
    assert assess_market(
        "XNAS", datetime(2026, 9, 30, 21, 0, tzinfo=UTC)
    ).next_session_at == datetime(2026, 10, 1, 13, 30, tzinfo=UTC)


def test_weekend_and_holiday_are_explicit_closures() -> None:
    assert assess_market("XNAS", datetime(2026, 10, 3, 15, 0, tzinfo=UTC)).status == "weekend"
    assert assess_market("XNAS", datetime(2026, 7, 3, 15, 0, tzinfo=UTC)).status == "holiday"
    assert assess_market(
        "XNAS", datetime(2026, 7, 3, 15, 0, tzinfo=UTC)
    ).next_session_at == datetime(2026, 7, 6, 13, 30, tzinfo=UTC)


def test_expected_previous_close_is_latest_completed_session_close_in_utc() -> None:
    result = assess_market("XNAS", datetime(2026, 10, 5, 13, 0, tzinfo=UTC))
    assert result.expected_previous_close == datetime(2026, 10, 2, 20, 0, tzinfo=UTC)


def test_crypto_and_unknown_mic_have_no_guessed_calendar() -> None:
    now = datetime(2026, 9, 30, 14, 0, tzinfo=UTC)
    assert assess_market("XNAS", now, asset_type="crypto").status == "not_applicable"
    assert assess_market("XZZZ", now).status == "unknown_calendar"


def test_naive_instant_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        assess_market("XNAS", datetime(2026, 9, 30, 14, 0))
