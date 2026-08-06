"""Validation for explicit, non-inferred provider alias identities."""

from __future__ import annotations

import re
from datetime import datetime

from app.db.models.enums import AssetAliasProvider, AssetType
from app.modules.asset_aliases.models import (
    AssetAliasInvalidError,
    OnboardAssetAliasCommand,
)
from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.prices.providers.coingecko_identity import (
    CoinGeckoAssetIdentityError,
    parse_coingecko_asset_identity,
)
from app.modules.prices.providers.twelve_data_identity import (
    parse_twelve_data_quote_identity,
)

SUPPORTED_ASSET_ALIAS_PROVIDERS = frozenset(
    {
        AssetAliasProvider.coingecko,
        AssetAliasProvider.twelve_data,
    }
)
COINGECKO_ASSET_TYPES = frozenset({AssetType.crypto})
TWELVE_DATA_ASSET_TYPES = frozenset(
    {
        AssetType.stock,
        AssetType.etf,
        AssetType.bond,
        AssetType.commodity,
        AssetType.other,
    }
)

_SYMBOL = re.compile(r"[A-Z0-9][A-Z0-9._-]{0,63}\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")


def _fail() -> AssetAliasInvalidError:
    return AssetAliasInvalidError()


def provider_asset_types(provider: AssetAliasProvider) -> frozenset[AssetType]:
    if provider is AssetAliasProvider.coingecko:
        return COINGECKO_ASSET_TYPES
    if provider is AssetAliasProvider.twelve_data:
        return TWELVE_DATA_ASSET_TYPES
    raise _fail()


def canonical_external_id(
    provider: AssetAliasProvider,
    value: object,
) -> str:
    if provider is AssetAliasProvider.coingecko:
        try:
            return parse_coingecko_asset_identity(value).coin_id
        except CoinGeckoAssetIdentityError as exc:
            raise _fail() from exc
    if provider is AssetAliasProvider.twelve_data:
        try:
            return parse_twelve_data_quote_identity(value).canonical_external_id
        except MarketEvidenceStateError as exc:
            raise _fail() from exc
    raise _fail()


def validate_onboard_asset_alias_command(
    value: object,
) -> OnboardAssetAliasCommand:
    if (
        not isinstance(value, OnboardAssetAliasCommand)
        or not isinstance(value.asset_id, str)
        or not value.asset_id
        or value.asset_id != value.asset_id.strip()
        or not isinstance(value.provider, AssetAliasProvider)
        or value.provider not in SUPPORTED_ASSET_ALIAS_PROVIDERS
        or not isinstance(value.external_id, str)
        or not isinstance(value.expected_symbol, str)
        or not _SYMBOL.fullmatch(value.expected_symbol)
        or not isinstance(value.expected_asset_type, AssetType)
        or not isinstance(value.expected_currency, str)
        or not _CURRENCY.fullmatch(value.expected_currency)
        or (
            value.expected_isin is not None
            and (
                not isinstance(value.expected_isin, str)
                or not value.expected_isin
                or value.expected_isin != value.expected_isin.strip()
                or value.expected_isin != value.expected_isin.upper()
                or not value.expected_isin.isascii()
                or len(value.expected_isin) > 32
            )
        )
        or not isinstance(value.created_at, datetime)
        or value.created_at.tzinfo is not None
        or value.created_at.microsecond % 1_000 != 0
        or value.expected_asset_type not in provider_asset_types(value.provider)
    ):
        raise _fail()
    if canonical_external_id(value.provider, value.external_id) != value.external_id:
        raise _fail()
    return value


__all__ = [
    "COINGECKO_ASSET_TYPES",
    "SUPPORTED_ASSET_ALIAS_PROVIDERS",
    "TWELVE_DATA_ASSET_TYPES",
    "canonical_external_id",
    "provider_asset_types",
    "validate_onboard_asset_alias_command",
]
