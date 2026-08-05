from __future__ import annotations

import pytest

from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.prices.providers.twelve_data_identity import (
    TwelveDataQuoteIdentity,
    parse_twelve_data_quote_identity,
)


@pytest.mark.parametrize(
    ("external_id", "symbol"),
    [
        ('{"symbol":"AAPL","mic_code":"XNAS"}', "AAPL"),
        ('{"symbol":"BRK.B","mic_code":"XNYS"}', "BRK.B"),
        ('{"symbol":"TEST-1","mic_code":"XNAS"}', "TEST-1"),
        ('{"symbol":"TEST_1","mic_code":"XNAS"}', "TEST_1"),
    ],
)
def test_identity_accepts_only_exact_canonical_json(
    external_id: str,
    symbol: str,
) -> None:
    identity = parse_twelve_data_quote_identity(external_id)
    assert identity == TwelveDataQuoteIdentity(symbol=symbol, mic_code=external_id[-6:-2])
    assert identity.canonical_external_id == external_id


@pytest.mark.parametrize(
    "external_id",
    [
        "",
        "[]",
        "null",
        '"AAPL"',
        '{"mic_code":"XNAS","symbol":"AAPL"}',
        '{"symbol": "AAPL","mic_code":"XNAS"}',
        '{"symbol":"AAPL", "mic_code":"XNAS"}',
        '{"symbol":"AAPL","mic_code":"XNAS","extra":1}',
        '{"symbol":"AAPL"}',
        '{"mic_code":"XNAS"}',
        '{"symbol":"AAPL","symbol":"MSFT","mic_code":"XNAS"}',
        '{"symbol":"AAPL","mic_code":"XNAS","mic_code":"XNYS"}',
        '{"symbol":"\\u0041APL","mic_code":"XNAS"}',
        '{"symbol":"AAPL","mic_code":"xnas"}',
        '{"symbol":"AAPL","mic_code":"XNA"}',
        '{"symbol":"AAPL","mic_code":"XNAS1"}',
        '{"symbol":"AAPL,MSFT","mic_code":"XNAS"}',
        '{"symbol":"AAPL&MSFT","mic_code":"XNAS"}',
        '{"symbol":"AAPL?x","mic_code":"XNAS"}',
        '{"symbol":"AAPL#x","mic_code":"XNAS"}',
        '{"symbol":"AAPL\\\\x","mic_code":"XNAS"}',
        '{"symbol":" AAPL","mic_code":"XNAS"}',
        '{"symbol":"AAPL ","mic_code":"XNAS"}',
        '{"symbol":"AAPL/US","mic_code":"XNAS"}',
        '{"symbol":"ÄAPL","mic_code":"XNAS"}',
        '{"symbol":"AAPL","mic_code":"XN@S"}',
        '{"symbol":"' + ("A" * 65) + '","mic_code":"XNAS"}',
    ],
)
def test_identity_fails_closed_for_noncanonical_or_unsafe_values(
    external_id: str,
) -> None:
    with pytest.raises(MarketEvidenceStateError, match="unavailable"):
        parse_twelve_data_quote_identity(external_id)


def test_identity_rejects_non_string_and_invalid_utf8_surrogate() -> None:
    for value in (None, b'{"symbol":"AAPL","mic_code":"XNAS"}', 1, "\ud800"):
        with pytest.raises(MarketEvidenceStateError):
            parse_twelve_data_quote_identity(value)
