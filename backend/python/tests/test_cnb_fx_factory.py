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


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **cast(dict[str, Any], overrides))


def test_cnb_settings_defaults_and_valid_override() -> None:
    settings = _settings()
    assert settings.cnb_fx_base_url.startswith("https://www.cnb.cz/")
    assert settings.cnb_fx_timeout_seconds == 10
    assert settings.cnb_fx_max_response_bytes == 1_048_576
    assert settings.cnb_fx_user_agent == "finance-app/0.1"

    custom = _settings(
        cnb_fx_base_url="https://example.test/rates.xml",
        cnb_fx_timeout_seconds=1.5,
        cnb_fx_max_response_bytes=1024,
        cnb_fx_user_agent="test-agent",
    )
    assert custom.cnb_fx_timeout_seconds == 1.5


@pytest.mark.parametrize(
    "overrides",
    [
        {"cnb_fx_base_url": "http://example.test/rates.xml"},
        {"cnb_fx_base_url": "https://user:pass@example.test/rates.xml"},
        {"cnb_fx_base_url": "https://example.test/rates.xml?date=today"},
        {"cnb_fx_base_url": "https://example.test/rates.xml#fragment"},
        {"cnb_fx_timeout_seconds": 0},
        {"cnb_fx_timeout_seconds": 121},
        {"cnb_fx_max_response_bytes": 0},
        {"cnb_fx_max_response_bytes": 10_485_761},
        {"cnb_fx_user_agent": ""},
        {"cnb_fx_user_agent": "unsafe\r\nheader"},
    ],
)
def test_invalid_cnb_settings_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _settings(**overrides)


def test_production_registry_contains_exactly_cnb() -> None:
    registry = create_production_exchange_rate_registry(_settings())

    assert registry.sources == frozenset({ExchangeRateSource.cnb})
    assert registry.get(ExchangeRateSource.cnb).source is ExchangeRateSource.cnb


def test_production_service_uses_coingecko_price_registry_and_cnb_source() -> None:
    session = MagicMock(spec=AsyncSession)

    service = create_production_market_evidence_service(session, _settings())

    assert service.price_registry.sources == frozenset(
        {PriceSource.coingecko, PriceSource.twelve_data}
    )
    assert service.fx_registry.sources == frozenset({ExchangeRateSource.cnb})
    assert service.fx_source is ExchangeRateSource.cnb
