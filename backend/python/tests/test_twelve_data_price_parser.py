from __future__ import annotations

import inspect
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.prices.providers.twelve_data_identity import TwelveDataQuoteIdentity
from app.modules.prices.providers.twelve_data_parser import parse_twelve_data_quote

IDENTITY = TwelveDataQuoteIdentity("AAPL", "XNAS")
OBSERVED_AT = datetime(2026, 8, 5, 12, 34)
EPOCH = int(OBSERVED_AT.replace(tzinfo=UTC).timestamp())


def _body(
    *,
    symbol: str = "AAPL",
    mic_code: str = "XNAS",
    currency: str = "USD",
    datetime_text: str = "2026-08-05 12:34:00",
    timestamp: str | int = EPOCH,
    last_quote_at: str | int = EPOCH,
    close: str = '"225.3200000000"',
    extra: str = '"name":"Example Corp","exchange":"NASDAQ",',
) -> bytes:
    return (
        "{"
        f'"symbol":"{symbol}",{extra}'
        f'"mic_code":"{mic_code}","currency":"{currency}",'
        f'"datetime":"{datetime_text}","timestamp":{timestamp},'
        f'"last_quote_at":{last_quote_at},"close":{close}'
        "}"
    ).encode()


def _parse(body: bytes):
    return parse_twelve_data_quote(body, identity=IDENTITY, listing_currency="USD")


def test_parser_returns_exact_identity_price_and_utc_timestamp() -> None:
    result = _parse(_body())
    assert result.symbol == "AAPL"
    assert result.mic_code == "XNAS"
    assert result.currency == "USD"
    assert result.close == Decimal("225.3200000000")
    assert result.timestamp == EPOCH
    assert result.last_quote_at == EPOCH
    assert result.last_quote_at_utc == OBSERVED_AT


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{",
        b"\xff",
        b"[]",
        b"null",
        b'"quote"',
        b'{"status":"error","code":400,"message":"bad"}',
        b'{"code":400,"message":"bad"}',
        _body(symbol="MSFT"),
        _body(mic_code="XNYS"),
        _body(currency="EUR"),
        _body(close="225.32"),
        _body(close="0"),
        _body(close='"0"'),
        _body(close='"-1"'),
        _body(close='"NaN"'),
        _body(close='"Infinity"'),
        _body(close='"225.32000000001"'),
        _body(close='"1234567890123456789.0"'),
        _body(timestamp='"1785933240"'),
        _body(timestamp="1785933240.0"),
        _body(timestamp="-1"),
        _body(last_quote_at='"1785933240"'),
        _body(last_quote_at="1785933300"),
        _body(timestamp="1785933241", last_quote_at="1785933241"),
        _body(datetime_text="2026-08-05"),
        _body(datetime_text="2026-08-05 12:35:00"),
        _body(extra='"symbol":"AAPL",'),
        _body(extra='"nested":{"a":{"b":{"c":{"d":{"e":{"f":1}}}}}},'),
    ],
)
def test_parser_fails_closed_for_incompatible_quote(body: bytes) -> None:
    with pytest.raises(MarketEvidenceStateError, match="unavailable"):
        _parse(body)


def test_parser_rejects_excessive_json_items() -> None:
    extra = ",".join(f'"field{index}":{index}' for index in range(129)) + ","
    with pytest.raises(MarketEvidenceStateError):
        _parse(_body(extra=extra))


def test_parser_never_uses_float_or_response_json() -> None:
    source = inspect.getsource(parse_twelve_data_quote)
    assert "parse_float=Decimal" in source
    assert "parse_int=Decimal" in source
    assert ".json(" not in source
    assert "float(" not in source
    assert "quantize(" not in source
