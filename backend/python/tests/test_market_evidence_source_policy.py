from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.db.models.enums import AssetType, ExchangeRateSource, PriceSource
from app.modules.fx.providers import create_local_free_exchange_rate_registry
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.market_data.source_policy import (
    CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
    MarketEvidenceSourcePolicyError,
    market_evidence_source_policy_from_settings,
)
from app.modules.prices.providers import create_local_free_price_registry


def test_source_policy_defaults_to_canonical_provider_selection() -> None:
    policy = market_evidence_source_policy_from_settings(Settings(_env_file=None))
    assert policy is CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY
    assert policy.price_source_for(AssetType.crypto) is PriceSource.coingecko
    assert policy.price_source_for(AssetType.etf) is PriceSource.twelve_data
    assert policy.fx_source is ExchangeRateSource.twelve_data


def test_local_free_policy_routes_all_supported_assets_and_fx_to_yahoo() -> None:
    policy = market_evidence_source_policy_from_settings(
        Settings(market_evidence_source_mode="local_free", _env_file=None)
    )
    assert policy is LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY
    assert policy.price_sources == frozenset({PriceSource.yahoo_finance})
    assert policy.price_source_for(AssetType.crypto) is PriceSource.yahoo_finance
    assert policy.price_source_for(AssetType.etf) is PriceSource.yahoo_finance
    assert policy.fx_source is ExchangeRateSource.yahoo_finance


def test_production_rejects_local_free_mode() -> None:
    with pytest.raises(ValidationError, match="must be canonical"):
        Settings(
            environment="production",
            database_url="postgresql://example.test/db",
            log_json=True,
            docs_enabled=False,
            internal_auth_secret="x" * 32,
            twelve_data_api_key="server-key",
            market_evidence_source_mode="local_free",
            _env_file=None,
        )


def test_local_free_factory_registers_only_yahoo_price_and_fx_sources() -> None:
    service = create_production_market_evidence_service(
        MagicMock(spec=AsyncSession),
        Settings(market_evidence_source_mode="local_free", _env_file=None),
    )
    assert service.price_registry.sources == frozenset({PriceSource.yahoo_finance})
    assert service.fx_source is ExchangeRateSource.yahoo_finance


@pytest.mark.parametrize(
    "settings",
    (
        Settings(_env_file=None),
        Settings(
            environment="production",
            database_url="postgresql://example.test/db",
            log_json=True,
            docs_enabled=False,
            internal_auth_secret="x" * 32,
            twelve_data_api_key="server-key",
            portfolio_history_runtime_enabled=True,
            scheduled_snapshot_refresh_runner_enabled=True,
            _env_file=None,
        ),
    ),
)
def test_direct_local_free_registries_reject_canonical_or_production_settings(
    settings: Settings,
) -> None:
    with pytest.raises(MarketEvidenceSourcePolicyError):
        create_local_free_price_registry(settings)
    with pytest.raises(MarketEvidenceSourcePolicyError):
        create_local_free_exchange_rate_registry(settings)
