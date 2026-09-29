from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.db.models.enums import ExchangeRateSource, PriceSource
from app.modules.fx.providers import create_production_exchange_rate_registry
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.market_data.models import MarketEvidenceStateError


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **cast(dict[str, Any], overrides))


def test_twelve_data_fx_settings_defaults_and_valid_override() -> None:
    settings = _settings()
    assert settings.twelve_data_fx_base_url == "https://api.twelvedata.com/time_series"
    assert settings.twelve_data_timeout_seconds == 10
    assert settings.twelve_data_max_response_bytes == 1_048_576
    assert settings.twelve_data_user_agent == "finance-app/0.1"

    custom = _settings(
        twelve_data_fx_base_url="https://example.test/time_series",
        twelve_data_timeout_seconds=1.5,
        twelve_data_max_response_bytes=1024,
        twelve_data_user_agent="test-agent",
        twelve_data_api_key="test-key",
    )
    assert custom.twelve_data_timeout_seconds == 1.5
    assert custom.twelve_data_api_key is not None
    assert custom.twelve_data_api_key.get_secret_value() == "test-key"


@pytest.mark.parametrize(
    "overrides",
    [
        {"twelve_data_fx_base_url": "http://example.test/time_series"},
        {"twelve_data_fx_base_url": "https://user:pass@example.test/time_series"},
        {"twelve_data_fx_base_url": "https://example.test/time_series?pair=EUR/USD"},
        {"twelve_data_fx_base_url": "https://example.test/time_series#fragment"},
        {"twelve_data_timeout_seconds": 0},
        {"twelve_data_timeout_seconds": 121},
        {"twelve_data_max_response_bytes": 0},
        {"twelve_data_max_response_bytes": 10_485_761},
        {"twelve_data_user_agent": ""},
        {"twelve_data_user_agent": "unsafe\r\nheader"},
        {"twelve_data_api_key": " unsafe "},
    ],
)
def test_invalid_twelve_data_fx_settings_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _settings(**overrides)


def test_production_registry_contains_only_twelve_data() -> None:
    registry = create_production_exchange_rate_registry(_settings())

    assert registry.sources == frozenset({ExchangeRateSource.twelve_data})
    assert registry.get(ExchangeRateSource.twelve_data).source is ExchangeRateSource.twelve_data
    with pytest.raises(MarketEvidenceStateError):
        registry.get(ExchangeRateSource.cnb)


def test_production_service_uses_price_registries_and_twelve_data_fx() -> None:
    session = MagicMock(spec=AsyncSession)

    service = create_production_market_evidence_service(session, _settings())

    assert service.price_registry.sources == frozenset(
        {PriceSource.coingecko, PriceSource.twelve_data}
    )
    assert service.fx_registry.sources == frozenset({ExchangeRateSource.twelve_data})
    assert service.fx_source is ExchangeRateSource.twelve_data
