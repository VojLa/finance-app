from datetime import datetime

from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import AssetAliasProvider, AssetType, PriceSource
from app.modules.market_data.source_policy import (
    CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
)
from app.modules.portfolio_history_rebuild.repository import _resolve_historical_price_identity

NOW = datetime(2026, 10, 1)


def _asset() -> AssetModel:
    return AssetModel(
        id="asset-btc",
        symbol="BTC",
        isin=None,
        name="Bitcoin",
        asset_type=AssetType.crypto,
        currency="CZK",
        created_at=NOW,
        updated_at=NOW,
    )


def _listing() -> AssetListingModel:
    return AssetListingModel(
        id="listing-btc-czk",
        asset_id="asset-btc",
        symbol="BTC",
        exchange=None,
        mic=None,
        currency="CZK",
        country=None,
        provider=PriceSource.exchange,
        provider_symbol="BTC",
        is_primary=False,
        created_at=NOW,
        updated_at=NOW,
        base_priority=0,
    )


def _yahoo_listing(*, provider_symbol: str = "BTC-USD") -> AssetListingModel:
    return AssetListingModel(
        id="listing-btc-usd",
        asset_id="asset-btc",
        symbol="BTC-USD",
        exchange=None,
        mic=None,
        currency="USD",
        country=None,
        provider=PriceSource.yahoo_finance,
        provider_symbol=provider_symbol,
        is_primary=False,
        created_at=NOW,
        updated_at=NOW,
        base_priority=0,
    )


def _alias(
    provider: AssetAliasProvider,
    external_id: str,
    *,
    listing_id: str | None,
) -> AssetAliasModel:
    return AssetAliasModel(
        id=f"alias-{provider.value}",
        asset_id="asset-btc",
        listing_id=listing_id,
        provider=provider,
        external_id=external_id,
        created_at=NOW,
    )


def test_local_free_history_prefers_explicit_yahoo_crypto_identity() -> None:
    identity, evidence_listing_id = _resolve_historical_price_identity(
        listing=_listing(),
        asset=_asset(),
        aliases=(
            _alias(AssetAliasProvider.coingecko, "bitcoin", listing_id=None),
            _alias(
                AssetAliasProvider.yahoo_finance,
                "BTC-USD",
                listing_id="listing-btc-usd",
            ),
        ),
        asset_listings=(_listing(), _yahoo_listing()),
        source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
    )

    assert (identity.provider, identity.provider_symbol, identity.price_currency) == (
        PriceSource.yahoo_finance,
        "BTC-USD",
        "USD",
    )
    assert evidence_listing_id == "listing-btc-usd"


def test_canonical_history_keeps_coingecko_crypto_identity() -> None:
    identity, evidence_listing_id = _resolve_historical_price_identity(
        listing=_listing(),
        asset=_asset(),
        aliases=(
            _alias(AssetAliasProvider.coingecko, "bitcoin", listing_id=None),
            _alias(
                AssetAliasProvider.yahoo_finance,
                "BTC-USD",
                listing_id="listing-btc-usd",
            ),
        ),
        asset_listings=(_listing(), _yahoo_listing()),
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    )

    assert (identity.provider, identity.provider_symbol, identity.price_currency) == (
        PriceSource.coingecko,
        "bitcoin",
        "CZK",
    )
    assert evidence_listing_id == "listing-btc-czk"


def test_local_free_history_ignores_untrusted_yahoo_crypto_symbol() -> None:
    identity, evidence_listing_id = _resolve_historical_price_identity(
        listing=_listing(),
        asset=_asset(),
        aliases=(
            _alias(AssetAliasProvider.coingecko, "bitcoin", listing_id=None),
            _alias(
                AssetAliasProvider.yahoo_finance,
                "BTC-EUR",
                listing_id="listing-btc-usd",
            ),
        ),
        asset_listings=(_listing(), _yahoo_listing(provider_symbol="BTC-EUR")),
        source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
    )

    assert identity.provider is PriceSource.coingecko
    assert evidence_listing_id == "listing-btc-czk"
