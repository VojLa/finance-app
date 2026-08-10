"""Strict parser for one Twelve Data direct FX time series."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.modules.fx.providers.twelve_data_models import TwelveDataFxPoint


class TwelveDataFxParseError(ValueError):
    pass


def _fail() -> TwelveDataFxParseError:
    return TwelveDataFxParseError("Twelve Data FX response is invalid.")


def parse_twelve_data_fx(body: bytes, *, expected_symbol: str) -> tuple[TwelveDataFxPoint, ...]:
    try:
        value = json.loads(body.decode("utf-8"), parse_float=Decimal, parse_int=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail() from exc
    if not isinstance(value, dict) or value.get("status") != "ok":
        raise _fail()
    meta = value.get("meta")
    rows = value.get("values")
    if not isinstance(meta, dict) or meta.get("symbol") != expected_symbol:
        raise _fail()
    if not isinstance(rows, list) or not rows or len(rows) > 16:
        raise _fail()
    points: list[TwelveDataFxPoint] = []
    timestamps: set[datetime] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise _fail()
        raw_timestamp = row.get("datetime")
        raw_rate = row.get("close")
        if not isinstance(raw_timestamp, str) or not isinstance(raw_rate, (str, Decimal)):
            raise _fail()
        try:
            effective_at = datetime.strptime(raw_timestamp, "%Y-%m-%d")
            rate = Decimal(raw_rate) if isinstance(raw_rate, str) else raw_rate
        except (ValueError, InvalidOperation) as exc:
            raise _fail() from exc
        exponent = rate.as_tuple().exponent
        if (
            effective_at in timestamps
            or not rate.is_finite()
            or rate <= 0
            or not isinstance(exponent, int)
            or exponent < -8
        ):
            raise _fail()
        timestamps.add(effective_at)
        points.append(TwelveDataFxPoint(expected_symbol, effective_at, rate))
    return tuple(sorted(points, key=lambda item: item.effective_at, reverse=True))
