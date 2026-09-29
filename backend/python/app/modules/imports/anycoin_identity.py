"""Exact source-owned display identity for the one supported Anycoin BTC asset."""

from __future__ import annotations

from app.db.models.enums import AssetType, PriceSource

ANYCOIN_BTC_SYMBOL = "BTC"
ANYCOIN_BTC_DISPLAY_NAME = "Bitcoin"


class AnycoinAssetIdentityError(ValueError):
    pass


def anycoin_crypto_display_name(symbol: object) -> str | None:
    """Return a name only for the closed, exact Anycoin BTC identity."""
    return ANYCOIN_BTC_DISPLAY_NAME if symbol == ANYCOIN_BTC_SYMBOL else None


def canonical_anycoin_crypto_display_name(
    *,
    symbol: object,
    supplied_name: object,
) -> str | None:
    expected = anycoin_crypto_display_name(symbol)
    if expected is None:
        if supplied_name is not None:
            raise AnycoinAssetIdentityError()
        return None
    if supplied_name not in {None, expected}:
        raise AnycoinAssetIdentityError()
    return expected


def is_exact_anycoin_btc_resolution(
    *,
    symbol: object,
    name: object,
    isin: object,
    asset_type: object,
    provider: object,
    provider_symbol: object,
    exchange: object,
    asset_currency_hint: object,
) -> bool:
    return (
        symbol == ANYCOIN_BTC_SYMBOL
        and name == ANYCOIN_BTC_DISPLAY_NAME
        and isin is None
        and asset_type is AssetType.crypto
        and provider is PriceSource.exchange
        and provider_symbol == ANYCOIN_BTC_SYMBOL
        and exchange == "anycoin"
        and asset_currency_hint == ANYCOIN_BTC_SYMBOL
    )


__all__ = [
    "ANYCOIN_BTC_DISPLAY_NAME",
    "ANYCOIN_BTC_SYMBOL",
    "AnycoinAssetIdentityError",
    "anycoin_crypto_display_name",
    "canonical_anycoin_crypto_display_name",
    "is_exact_anycoin_btc_resolution",
]
