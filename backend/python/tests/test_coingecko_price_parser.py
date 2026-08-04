from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.prices.providers.coingecko_parser import parse_coingecko_simple_price


def _parse(body: bytes):
    return parse_coingecko_simple_price(
        body,
        provider_symbol="bitcoin",
        quote_currency="eur",
    )


def test_parser_returns_exact_decimal_and_unix_timestamp() -> None:
    result = _parse(
        b'{"bitcoin":{"eur":61234.123456789,"last_updated_at":1785841140,"safe_extra":"ignored"}}'
    )

    assert result.price == Decimal("61234.123456789")
    assert result.last_updated_at == 1_785_841_140


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{",
        b"[]",
        b"null",
        b'"bitcoin"',
        b'{"bitcoin":null}',
        b'{"ethereum":{"eur":1,"last_updated_at":1785841140}}',
        b'{"bitcoin":{"eur":1,"last_updated_at":1785841140},"ethereum":{}}',
        b'{"bitcoin":{"usd":1,"last_updated_at":1785841140}}',
        b'{"bitcoin":{"eur":null,"last_updated_at":1785841140}}',
        b'{"bitcoin":{"eur":"1","last_updated_at":1785841140}}',
        b'{"bitcoin":{"eur":true,"last_updated_at":1785841140}}',
        b'{"bitcoin":{"eur":0,"last_updated_at":1785841140}}',
        b'{"bitcoin":{"eur":-1,"last_updated_at":1785841140}}',
        b'{"bitcoin":{"eur":NaN,"last_updated_at":1785841140}}',
        b'{"bitcoin":{"eur":Infinity,"last_updated_at":1785841140}}',
        b'{"bitcoin":{"eur":1}}',
        b'{"bitcoin":{"eur":1,"last_updated_at":null}}',
        b'{"bitcoin":{"eur":1,"last_updated_at":"1785841140"}}',
        b'{"bitcoin":{"eur":1,"last_updated_at":true}}',
        b'{"bitcoin":{"eur":1,"last_updated_at":1785841140.0}}',
        b'{"bitcoin":{"eur":1,"last_updated_at":-1}}',
        b'{"bitcoin":{"eur":1,"eur":2,"last_updated_at":1785841140}}',
        b'{"bitcoin":{"eur":1,"last_updated_at":1785841140,'
        b'"nested":{"a":{"b":{"c":{"d":{"e":{"f":1}}}}}}}}',
    ],
)
def test_parser_fails_closed_for_incompatible_json(body: bytes) -> None:
    with pytest.raises(MarketEvidenceStateError, match="unavailable"):
        _parse(body)


def test_parser_rejects_excessive_item_count() -> None:
    fields = b",".join(f'"field{index}":{index}'.encode() for index in range(65))
    body = b'{"bitcoin":{"eur":1,"last_updated_at":1785841140,' + fields + b"}}"

    with pytest.raises(MarketEvidenceStateError):
        _parse(body)


def test_parser_does_not_use_float_or_response_json() -> None:
    source = __import__("inspect").getsource(parse_coingecko_simple_price)
    assert "parse_float=Decimal" in source
    assert "parse_int=Decimal" in source
    assert ".json(" not in source
    assert "float(" not in source
