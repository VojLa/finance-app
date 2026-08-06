from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.db.models.enums import AssetAliasProvider, AssetType
from app.modules.asset_aliases.identity import (
    canonical_external_id,
    validate_onboard_asset_alias_command,
)
from app.modules.asset_aliases.models import (
    AssetAliasInvalidError,
    OnboardAssetAliasCommand,
)
from app.modules.prices.providers.coingecko_identity import (
    CoinGeckoAssetIdentityError,
    parse_coingecko_asset_identity,
)

CREATED_AT = datetime(2026, 8, 5, 12, 30, 0, 123000)
TWELVE_ID = '{"symbol":"AAPL","mic_code":"XNAS"}'


def _command(**overrides: object) -> OnboardAssetAliasCommand:
    values: dict[str, object] = {
        "asset_id": "asset-a",
        "provider": AssetAliasProvider.coingecko,
        "external_id": "bitcoin",
        "expected_symbol": "BTC",
        "expected_asset_type": AssetType.crypto,
        "expected_currency": "EUR",
        "expected_isin": None,
        "created_at": CREATED_AT,
    }
    values.update(overrides)
    return OnboardAssetAliasCommand(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    [
        "",
        " bitcoin",
        "bitcoin ",
        "bit\tcoin",
        "bit\ncoin",
        "bitcoin,ethereum",
        "https://example.test/bitcoin",
        "bitcoin?currency=eur",
        "bitcoin#fragment",
        "a" * 129,
        "bitcóin",
    ],
)
def test_coingecko_identity_rejects_nonexact_or_list_values(value: str) -> None:
    with pytest.raises(CoinGeckoAssetIdentityError):
        parse_coingecko_asset_identity(value)


def test_coingecko_identity_accepts_one_exact_id() -> None:
    identity = parse_coingecko_asset_identity("bitcoin")

    assert identity.coin_id == "bitcoin"


@pytest.mark.parametrize(
    "value",
    [
        '{"mic_code":"XNAS","symbol":"AAPL"}',
        '{ "symbol":"AAPL","mic_code":"XNAS"}',
        '{"symbol":"AAPL","mic_code":"xnas"}',
        '{"symbol":"AAPL","mic_code":"XN"}',
        '{"symbol":"AAPL","symbol":"MSFT","mic_code":"XNAS"}',
        '{"symbol":"AAPL","mic_code":"XNAS","exchange":"NASDAQ"}',
    ],
)
def test_twelve_data_identity_rejects_noncanonical_json(value: str) -> None:
    with pytest.raises(AssetAliasInvalidError):
        canonical_external_id(AssetAliasProvider.twelve_data, value)


def test_twelve_data_identity_accepts_exact_canonical_json() -> None:
    assert canonical_external_id(AssetAliasProvider.twelve_data, TWELVE_ID) == TWELVE_ID


@pytest.mark.parametrize(
    "overrides",
    [
        {"asset_id": ""},
        {"asset_id": " asset-a"},
        {"provider": AssetAliasProvider.broker},
        {"provider": True},
        {"external_id": "bitcoin,ethereum"},
        {"expected_symbol": "btc"},
        {"expected_symbol": "BTC USD"},
        {"expected_asset_type": True},
        {"expected_currency": "eur"},
        {"expected_currency": "EURO"},
        {"expected_isin": " us0378331005"},
        {"created_at": datetime(2026, 8, 5, 12, 30, tzinfo=UTC)},
        {"created_at": datetime(2026, 8, 5, 12, 30, 0, 1)},
        {
            "provider": AssetAliasProvider.coingecko,
            "expected_asset_type": AssetType.stock,
        },
        {
            "provider": AssetAliasProvider.twelve_data,
            "external_id": TWELVE_ID,
            "expected_asset_type": AssetType.crypto,
        },
        {
            "provider": AssetAliasProvider.twelve_data,
            "external_id": TWELVE_ID,
            "expected_asset_type": AssetType.cash,
        },
    ],
)
def test_command_rejects_invalid_or_incompatible_values(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(AssetAliasInvalidError):
        validate_onboard_asset_alias_command(_command(**overrides))


@pytest.mark.parametrize(
    "asset_type",
    [
        AssetType.stock,
        AssetType.etf,
        AssetType.bond,
        AssetType.commodity,
        AssetType.other,
    ],
)
def test_twelve_data_command_accepts_supported_asset_types(
    asset_type: AssetType,
) -> None:
    command = _command(
        provider=AssetAliasProvider.twelve_data,
        external_id=TWELVE_ID,
        expected_symbol="AAPL",
        expected_asset_type=asset_type,
        expected_currency="USD",
        expected_isin="US0378331005",
    )

    assert validate_onboard_asset_alias_command(command) is command
