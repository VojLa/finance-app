"""Strict JSON parser for one exact CoinGecko simple-price identity."""

from __future__ import annotations

import json
from decimal import Decimal

from app.db.models.enums import MarketDataFailureReason
from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.market_data.provider_failure import ProviderFailure
from app.modules.prices.providers.coingecko_models import CoinGeckoSimplePrice

_MAX_DEPTH = 6
_MAX_ITEMS = 64
type _JsonObject = dict[str, object]


def _fail() -> MarketEvidenceStateError:
    return MarketEvidenceStateError()


def _reject_constant(_: str) -> None:
    raise _fail()


def _strict_object(pairs: list[tuple[str, object]]) -> _JsonObject:
    if len(pairs) > _MAX_ITEMS:
        raise _fail()
    result: _JsonObject = {}
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


def parse_coingecko_simple_price(
    body: bytes,
    *,
    provider_symbol: str,
    quote_currency: str,
) -> CoinGeckoSimplePrice:
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
    if isinstance(document, dict) and not document:
        raise ProviderFailure(MarketDataFailureReason.unknown_symbol)
    if isinstance(document, dict) and len(document) == 1 and provider_symbol not in document:
        raise ProviderFailure(MarketDataFailureReason.provider_identity_conflict)
    if not isinstance(document, dict) or tuple(document) != (provider_symbol,):
        raise _fail()
    coin = document.get(provider_symbol)
    if not isinstance(coin, dict):
        raise _fail()
    if quote_currency not in coin and any(
        isinstance(key, str) and key != "last_updated_at" for key in coin
    ):
        raise ProviderFailure(MarketDataFailureReason.currency_conflict)
    price = coin.get(quote_currency)
    timestamp = coin.get("last_updated_at")
    if (
        isinstance(price, bool)
        or not isinstance(price, Decimal)
        or not price.is_finite()
        or price <= 0
        or isinstance(timestamp, bool)
        or not isinstance(timestamp, Decimal)
        or timestamp.as_tuple().exponent != 0
        or timestamp < 0
    ):
        raise ProviderFailure(MarketDataFailureReason.invalid_price)
    try:
        timestamp_integer = int(timestamp)
    except (OverflowError, ValueError) as exc:
        raise _fail() from exc
    return CoinGeckoSimplePrice(price=price, last_updated_at=timestamp_integer)
