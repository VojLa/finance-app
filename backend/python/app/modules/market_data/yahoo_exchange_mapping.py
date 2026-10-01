"""Small explicit Yahoo suffix catalogue for assisted listing onboarding.

Persisted ``provider_symbol`` is always authoritative.  This module may suggest or
validate an identity for a known venue; it must never rewrite an existing symbol.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class YahooExchange:
    mic: str
    name: str
    suffix: str


_EXCHANGES: dict[str, YahooExchange] = {
    "XNAS": YahooExchange("XNAS", "NASDAQ", ""),
    "XNYS": YahooExchange("XNYS", "New York Stock Exchange", ""),
    "ARCX": YahooExchange("ARCX", "NYSE Arca", ""),
    "XLON": YahooExchange("XLON", "London Stock Exchange", ".L"),
    "XETR": YahooExchange("XETR", "Xetra", ".DE"),
    "XFRA": YahooExchange("XFRA", "Frankfurt Stock Exchange", ".F"),
    "XPRA": YahooExchange("XPRA", "Prague Stock Exchange", ".PR"),
    "XSWX": YahooExchange("XSWX", "SIX Swiss Exchange", ".SW"),
    "XTKS": YahooExchange("XTKS", "Tokyo Stock Exchange", ".T"),
    "XMIL": YahooExchange("XMIL", "Borsa Italiana", ".MI"),
    "XPAR": YahooExchange("XPAR", "Euronext Paris", ".PA"),
    "XAMS": YahooExchange("XAMS", "Euronext Amsterdam", ".AS"),
    "XBRU": YahooExchange("XBRU", "Euronext Brussels", ".BR"),
    "XLIS": YahooExchange("XLIS", "Euronext Lisbon", ".LS"),
}


def yahoo_exchange(mic: str) -> YahooExchange | None:
    """Return explicit venue metadata; unknown or non-MIC values stay unresolved."""

    return _EXCHANGES.get(mic.strip().upper())


def suggest_yahoo_symbol(*, symbol: str, mic: str) -> str | None:
    """Suggest a Yahoo identity only for a venue with an explicit mapping."""

    exchange = yahoo_exchange(mic)
    canonical = symbol.strip().upper()
    if exchange is None or not canonical:
        return None
    return f"{canonical}{exchange.suffix}"


__all__ = ["YahooExchange", "suggest_yahoo_symbol", "yahoo_exchange"]
