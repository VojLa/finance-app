from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from app.modules.fx.providers.twelve_data_parser import (
    TwelveDataFxParseError,
    parse_twelve_data_fx,
)


def _body(*, symbol: str = "EUR/USD", values: str | None = None) -> bytes:
    rows = values or (
        '[{"datetime":"2026-08-03","close":"1.15320000"},'
        '{"datetime":"2026-07-31","close":"1.14750000"}]'
    )
    return f'{{"meta":{{"symbol":"{symbol}"}},"values":{rows},"status":"ok"}}'.encode()


def test_parser_returns_exact_descending_direct_pair_points() -> None:
    result = parse_twelve_data_fx(_body(), expected_symbol="EUR/USD")

    assert [(point.symbol, point.effective_at, point.rate) for point in result] == [
        ("EUR/USD", datetime(2026, 8, 3), Decimal("1.15320000")),
        ("EUR/USD", datetime(2026, 7, 31), Decimal("1.14750000")),
    ]


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        b'{"status":"error","message":"quota exceeded"}',
        _body(symbol="USD/EUR"),
        _body(values="[]"),
        _body(values='[{"datetime":"2026-08-03","close":"0"}]'),
        _body(values='[{"datetime":"2026-08-03","close":"1.123456789"}]'),
        _body(
            values=(
                '[{"datetime":"2026-08-03","close":"1.1"},{"datetime":"2026-08-03","close":"1.2"}]'
            )
        ),
    ],
)
def test_parser_rejects_errors_wrong_direction_and_noncanonical_rows(body: bytes) -> None:
    with pytest.raises(TwelveDataFxParseError, match="invalid"):
        parse_twelve_data_fx(body, expected_symbol="EUR/USD")
