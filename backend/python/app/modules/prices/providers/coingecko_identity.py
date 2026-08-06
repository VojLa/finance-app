"""Exact persisted CoinGecko asset identity."""

from __future__ import annotations

from dataclasses import dataclass

_FORBIDDEN_CHARACTERS = frozenset(",&?#/\\")
_MAX_COIN_ID_LENGTH = 128


class CoinGeckoAssetIdentityError(ValueError):
    """The value is not one exact canonical CoinGecko asset ID."""


@dataclass(frozen=True, slots=True)
class CoinGeckoAssetIdentity:
    coin_id: str


def parse_coingecko_asset_identity(value: object) -> CoinGeckoAssetIdentity:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or not value.isascii()
        or len(value) > _MAX_COIN_ID_LENGTH
        or any(character in _FORBIDDEN_CHARACTERS for character in value)
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise CoinGeckoAssetIdentityError()
    return CoinGeckoAssetIdentity(coin_id=value)


__all__ = [
    "CoinGeckoAssetIdentity",
    "CoinGeckoAssetIdentityError",
    "parse_coingecko_asset_identity",
]
