from __future__ import annotations

import json
from datetime import datetime

import pytest

from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.prices.providers.yahoo_finance_parser import parse_yahoo_finance_chart


def _body(*, timestamps: list[int]) -> bytes:
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "VUAA.MI", "currency": "EUR", "priceHint": 2},
                        "timestamp": timestamps,
                        "indicators": {"quote": [{"close": [128.039993286133] * len(timestamps)}]},
                    }
                ],
                "error": None,
            }
        },
        separators=(",", ":"),
    ).encode()


def test_parser_rejects_duplicate_observation_timestamp() -> None:
    with pytest.raises(MarketEvidenceStateError):
        parse_yahoo_finance_chart(
            _body(timestamps=[1722859200, 1722859200]),
            expected_symbol="VUAA.MI",
            expected_currency="EUR",
            maximum_price_hint=10,
        )


def test_parser_uses_provider_price_hint_not_binary_float_tail() -> None:
    chart = parse_yahoo_finance_chart(
        _body(timestamps=[1722859200]),
        expected_symbol="VUAA.MI",
        expected_currency="EUR",
        maximum_price_hint=10,
    )
    assert chart.points[0].observed_at == datetime(2024, 8, 5, 12)
    assert str(chart.points[0].close) == "128.04"


def test_parser_accepts_bounded_live_minute_quote_shape() -> None:
    timestamps = list(range(1722859200, 1722859200 + 1_500 * 60, 60))
    document = {
        "chart": {
            "result": [
                {
                    "meta": {"symbol": "VUAA.MI", "currency": "EUR", "priceHint": 2},
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [
                            {
                                "close": [128.039993286133] * len(timestamps),
                                "open": [128.039993286133] * len(timestamps),
                                "high": [128.039993286133] * len(timestamps),
                                "low": [128.039993286133] * len(timestamps),
                                "volume": [1] * len(timestamps),
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }
    chart = parse_yahoo_finance_chart(
        json.dumps(document, separators=(",", ":")).encode(),
        expected_symbol="VUAA.MI",
        expected_currency="EUR",
        maximum_price_hint=10,
    )
    assert len(chart.points) == len(timestamps)
