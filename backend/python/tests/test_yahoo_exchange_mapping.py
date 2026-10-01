from __future__ import annotations

import pytest

from app.modules.market_data.yahoo_exchange_mapping import (
    suggest_yahoo_symbol,
    yahoo_exchange,
)


@pytest.mark.parametrize(
    ("symbol", "mic", "expected"),
    [
        ("AAPL", "XNAS", "AAPL"),
        ("SPY", "ARCX", "SPY"),
        ("BARC", "XLON", "BARC.L"),
        ("VWCE", "XETR", "VWCE.DE"),
        ("CEZ", "XPRA", "CEZ.PR"),
        ("NESN", "XSWX", "NESN.SW"),
        ("7203", "XTKS", "7203.T"),
        ("AIR", "XPAR", "AIR.PA"),
    ],
)
def test_known_venue_can_suggest_exact_yahoo_identity(symbol: str, mic: str, expected: str) -> None:
    assert suggest_yahoo_symbol(symbol=symbol, mic=mic) == expected


def test_unknown_venue_and_crypto_do_not_infer_a_listing() -> None:
    assert suggest_yahoo_symbol(symbol="BTC-USD", mic="") is None
    assert suggest_yahoo_symbol(symbol="VUAA", mic="UNKNOWN") is None
    assert yahoo_exchange("CRYPTO") is None
