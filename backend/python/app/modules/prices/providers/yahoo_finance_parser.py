"""Strict parser for one exact Yahoo Finance chart response."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.prices.providers.yahoo_finance_models import (
    YahooFinanceChart,
    YahooFinanceChartPoint,
)

_MAX_DEPTH = 8
# A three-day 1m chart has roughly 1,500 timestamps and Yahoo's one quote
# record carries close/open/high/low/volume arrays. Keep the parser bounded
# while allowing that legitimate live payload shape.
_MAX_ITEMS = 32_768
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")


def _fail() -> MarketEvidenceStateError:
    return MarketEvidenceStateError()


def _reject_constant(_: str) -> None:
    raise _fail()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len(pairs) > _MAX_ITEMS:
        raise _fail()
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _fail()
        result[key] = value
    return result


def _validate_shape(value: object, *, depth: int = 0) -> int:
    if depth > _MAX_DEPTH:
        raise _fail()
    if isinstance(value, dict):
        total = len(value)
        for key, item in value.items():
            if not isinstance(key, str):
                raise _fail()
            total += _validate_shape(item, depth=depth + 1)
    elif isinstance(value, list):
        total = len(value)
        for item in value:
            total += _validate_shape(item, depth=depth + 1)
    else:
        total = 1
    if total > _MAX_ITEMS:
        raise _fail()
    return total


def _timestamp(value: object) -> datetime:
    if (
        isinstance(value, bool)
        or not isinstance(value, Decimal)
        or not value.is_finite()
        or value.as_tuple().exponent != 0
        or value < 0
    ):
        raise _fail()
    try:
        return datetime.fromtimestamp(int(value), tz=UTC).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError) as exc:
        raise _fail() from exc


def _price_hint(value: object, *, maximum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, Decimal)
        or not value.is_finite()
        or value.as_tuple().exponent != 0
        or value < 0
        or value > maximum
    ):
        raise _fail()
    return int(value)


def _price(value: object, *, price_hint: int) -> Decimal:
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, str) and _DECIMAL.fullmatch(value):
        try:
            result = Decimal(value)
        except InvalidOperation as exc:
            raise _fail() from exc
    else:
        raise _fail()
    try:
        result = result.quantize(Decimal(1).scaleb(-price_hint), rounding=ROUND_HALF_EVEN)
    except InvalidOperation as exc:
        raise _fail() from exc
    exponent = result.as_tuple().exponent
    if (
        not result.is_finite()
        or result <= 0
        or not isinstance(exponent, int)
        or exponent < -10
        or max(result.adjusted() + 1, 0) > 18
    ):
        raise _fail()
    return result


def parse_yahoo_finance_chart(
    body: bytes,
    *,
    expected_symbol: str,
    expected_currency: str,
    maximum_price_hint: int,
) -> YahooFinanceChart:
    if not isinstance(body, bytes) or not body:
        raise _fail()
    try:
        document = json.loads(
            body,
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=_reject_constant,
            object_pairs_hook=_strict_object,
        )
    except MarketEvidenceStateError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
        raise _fail() from exc
    _validate_shape(document)
    if not isinstance(document, dict) or tuple(document) != ("chart",):
        raise _fail()
    chart = document.get("chart")
    if (
        not isinstance(chart, dict)
        or set(chart) != {"result", "error"}
        or chart["error"] is not None
    ):
        raise _fail()
    results = chart["result"]
    if not isinstance(results, list) or len(results) != 1 or not isinstance(results[0], dict):
        raise _fail()
    result = results[0]
    meta = result.get("meta")
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    if (
        not isinstance(meta, dict)
        or meta.get("symbol") != expected_symbol
        or meta.get("currency") != expected_currency
        or not isinstance(timestamps, list)
        or not timestamps
        or len(timestamps) > 4_096
        or not isinstance(indicators, dict)
        or not {"quote"} <= set(indicators) <= {"quote", "adjclose"}
    ):
        raise _fail()
    quote = indicators["quote"]
    if not isinstance(quote, list) or len(quote) != 1 or not isinstance(quote[0], dict):
        raise _fail()
    price_hint = _price_hint(meta.get("priceHint"), maximum=maximum_price_hint)
    closes = quote[0].get("close")
    if not isinstance(closes, list) or len(closes) != len(timestamps):
        raise _fail()
    points: list[YahooFinanceChartPoint] = []
    seen: set[datetime] = set()
    for raw_timestamp, raw_close in zip(timestamps, closes, strict=True):
        if raw_close is None:
            continue
        observed_at = _timestamp(raw_timestamp)
        if observed_at in seen:
            raise _fail()
        seen.add(observed_at)
        points.append(
            YahooFinanceChartPoint(
                observed_at=observed_at,
                close=_price(raw_close, price_hint=price_hint),
            )
        )
    if not points:
        raise _fail()
    return YahooFinanceChart(
        symbol=expected_symbol,
        currency=expected_currency,
        points=tuple(sorted(points, key=lambda item: item.observed_at, reverse=True)),
    )


__all__ = ["parse_yahoo_finance_chart"]
