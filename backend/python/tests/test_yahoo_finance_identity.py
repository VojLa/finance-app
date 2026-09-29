from __future__ import annotations

import pytest

from app.db.models.enums import AssetAliasProvider, AssetType
from app.modules.asset_aliases.identity import canonical_external_id, provider_asset_types
from app.modules.prices.providers.yahoo_finance_identity import (
    YahooFinanceAssetIdentityError,
    parse_yahoo_finance_asset_identity,
)


@pytest.mark.parametrize(
    "value",
    ["", " VUAA.MI", "VUAA.MI ", "vuaa.mi", "A/B"],
)
def test_yahoo_identity_rejects_noncanonical_tickers(value: str) -> None:
    with pytest.raises(YahooFinanceAssetIdentityError):
        parse_yahoo_finance_asset_identity(value)


def test_yahoo_identity_accepts_exact_vuaa_milan_ticker() -> None:
    assert parse_yahoo_finance_asset_identity("VUAA.MI") == "VUAA.MI"
    assert canonical_external_id(AssetAliasProvider.yahoo_finance, "VUAA.MI") == "VUAA.MI"
    assert AssetType.crypto in provider_asset_types(AssetAliasProvider.yahoo_finance)


def test_yahoo_crypto_ticker_syntax_is_an_explicit_eligible_alias() -> None:
    assert parse_yahoo_finance_asset_identity("BTC-USD") == "BTC-USD"
    assert AssetType.crypto in provider_asset_types(AssetAliasProvider.yahoo_finance)


def test_yahoo_identity_keeps_generic_ticker_validation_provider_agnostic() -> None:
    assert parse_yahoo_finance_asset_identity("BRK-B") == "BRK-B"
    assert parse_yahoo_finance_asset_identity("BTC-CZK") == "BTC-CZK"
