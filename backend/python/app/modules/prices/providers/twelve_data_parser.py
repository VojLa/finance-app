"""Strict parser for one exact Twelve Data /quote response."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.prices.providers.twelve_data_identity import TwelveDataQuoteIdentity
from app.modules.prices.providers.twelve_data_models import TwelveDataQuote

_MAX_DEPTH = 6
_MAX_ITEMS = 128
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


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


def _integer(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, Decimal)
        or not value.is_finite()
        or value.as_tuple().exponent != 0
        or value < 0
    ):
        raise _fail()
    try:
        return int(value)
    except (OverflowError, ValueError) as exc:
        raise _fail() from exc


def _price(value: object) -> Decimal:
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise _fail()
    try:
        result = Decimal(value)
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


def parse_twelve_data_quote(
    body: bytes,
    *,
    identity: TwelveDataQuoteIdentity,
    listing_currency: str,
) -> TwelveDataQuote:
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
    if not isinstance(document, dict) or document.get("status") == "error":
        raise _fail()
    if any(key in document for key in ("code", "message", "status")):
        raise _fail()
    symbol = document.get("symbol")
    mic_code = document.get("mic_code")
    currency = document.get("currency")
    datetime_text = document.get("datetime")
    if (
        symbol != identity.symbol
        or mic_code != identity.mic_code
        or currency != listing_currency
        or not isinstance(datetime_text, str)
    ):
        raise _fail()
    timestamp = _integer(document.get("timestamp"))
    last_quote_at = _integer(document.get("last_quote_at"))
    if timestamp != last_quote_at or last_quote_at % 60 != 0:
        raise _fail()
    try:
        parsed_datetime = datetime.strptime(datetime_text, _DATETIME_FORMAT)
        if parsed_datetime.strftime(_DATETIME_FORMAT) != datetime_text:
            raise _fail()
        epoch_datetime = datetime.fromtimestamp(last_quote_at, tz=UTC).replace(tzinfo=None)
    except (OverflowError, OSError, ValueError) as exc:
        raise _fail() from exc
    if parsed_datetime != epoch_datetime or parsed_datetime.microsecond != 0:
        raise _fail()
    return TwelveDataQuote(
        symbol=symbol,
        mic_code=mic_code,
        currency=currency,
        close=_price(document.get("close")),
        timestamp=timestamp,
        last_quote_at=last_quote_at,
        last_quote_at_utc=epoch_datetime,
    )
