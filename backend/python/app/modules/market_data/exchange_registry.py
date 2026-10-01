"""Explicit exchange metadata used by deterministic market calendars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True, slots=True)
class ExchangeVenue:
    mic: str
    name: str
    country: str
    timezone: str
    session_open: time
    session_close: time
    lunch_start: time | None = None
    lunch_end: time | None = None


_VENUES = {
    v.mic: v
    for v in (
        ExchangeVenue("XNAS", "NASDAQ", "US", "America/New_York", time(9, 30), time(16)),
        ExchangeVenue("XNYS", "NYSE", "US", "America/New_York", time(9, 30), time(16)),
        ExchangeVenue("ARCX", "NYSE Arca", "US", "America/New_York", time(9, 30), time(16)),
        ExchangeVenue("XETR", "Xetra", "DE", "Europe/Berlin", time(9), time(17, 30)),
        ExchangeVenue(
            "XLON", "London Stock Exchange", "GB", "Europe/London", time(8), time(16, 30)
        ),
        ExchangeVenue(
            "XPRA", "Prague Stock Exchange", "CZ", "Europe/Prague", time(9), time(16, 10)
        ),
        ExchangeVenue("XSWX", "SIX Swiss Exchange", "CH", "Europe/Zurich", time(9), time(17, 30)),
        ExchangeVenue(
            "XTKS",
            "Tokyo Stock Exchange",
            "JP",
            "Asia/Tokyo",
            time(9),
            time(15),
            time(11, 30),
            time(12, 30),
        ),
    )
}


def exchange_venue(mic: str | None) -> ExchangeVenue | None:
    """Return explicit supported venue metadata, or ``None`` for unknown MICs."""

    return _VENUES.get(mic.strip().upper()) if mic else None


__all__ = ["ExchangeVenue", "exchange_venue"]
