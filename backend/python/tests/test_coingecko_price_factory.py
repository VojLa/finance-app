from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.db.models.enums import ExchangeRateSource, PriceSource
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.prices.providers import create_production_price_registry


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **cast(dict[str, Any], overrides))


def test_coingecko_settings_defaults_and_safe_secret() -> None:
    settings = _settings(coingecko_demo_api_key="demo-secret")
    assert settings.coingecko_price_base_url == ("https://api.coingecko.com/api/v3/simple/price")
    assert settings.coingecko_price_timeout_seconds == 10
    assert settings.coingecko_price_max_response_bytes == 1_048_576
    assert settings.coingecko_price_user_agent == "finance-app/0.1"
    assert "demo-secret" not in repr(settings)


def test_repository_env_example_keeps_optional_coingecko_key_absent() -> None:
    env_example = Path(__file__).resolve().parents[3] / ".env.example"

    settings = Settings(_env_file=env_example)

    assert settings.coingecko_demo_api_key is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"coingecko_price_base_url": "http://api.coingecko.com/api/v3/simple/price"},
        {"coingecko_price_base_url": "https://u:p@example.test/price"},
        {"coingecko_price_base_url": "https://example.test/price?ids=bitcoin"},
        {"coingecko_price_base_url": "https://example.test/price#fragment"},
        {"coingecko_price_base_url": "https://example.test/price path"},
        {"coingecko_price_timeout_seconds": 0},
        {"coingecko_price_timeout_seconds": 121},
        {"coingecko_price_max_response_bytes": 0},
        {"coingecko_price_max_response_bytes": 10_485_761},
        {"coingecko_price_user_agent": ""},
        {"coingecko_price_user_agent": "unsafe\r\nagent"},
        {"coingecko_demo_api_key": ""},
        {"coingecko_demo_api_key": " unsafe"},
        {"coingecko_demo_api_key": "unsafe\r\nkey"},
    ],
)
def test_invalid_coingecko_settings_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _settings(**overrides)


def test_production_price_registry_contains_exactly_coingecko() -> None:
    registry = create_production_price_registry(_settings())
    assert registry.sources == frozenset({PriceSource.coingecko})
    assert registry.get(PriceSource.coingecko).source is PriceSource.coingecko
    assert PriceSource.twelve_data not in registry.sources
    with pytest.raises(MarketEvidenceStateError):
        registry.get(PriceSource.twelve_data)


def test_production_service_composes_coingecko_and_cnb() -> None:
    service = create_production_market_evidence_service(
        MagicMock(spec=AsyncSession),
        _settings(),
    )
    assert service.price_registry.sources == frozenset({PriceSource.coingecko})
    assert service.fx_registry.sources == frozenset({ExchangeRateSource.cnb})
    assert service.fx_source is ExchangeRateSource.cnb
