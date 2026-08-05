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
from app.modules.prices.providers import create_production_price_registry


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **cast(dict[str, Any], overrides))


def test_twelve_data_settings_defaults_and_secret_repr() -> None:
    settings = _settings(twelve_data_api_key="server-secret")
    assert settings.twelve_data_quote_base_url == "https://api.twelvedata.com/quote"
    assert settings.twelve_data_timeout_seconds == 10
    assert settings.twelve_data_max_response_bytes == 1_048_576
    assert settings.twelve_data_user_agent == "finance-app/0.1"
    assert "server-secret" not in repr(settings)


def test_env_example_has_only_commented_twelve_data_key() -> None:
    env_example = Path(__file__).resolve().parents[3] / ".env.example"
    text = env_example.read_text(encoding="utf-8")
    assert '# TWELVE_DATA_API_KEY="replace-with-a-server-side-api-key"' in text
    settings = Settings(_env_file=env_example)
    assert settings.twelve_data_api_key is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"twelve_data_quote_base_url": "http://api.twelvedata.com/quote"},
        {"twelve_data_quote_base_url": "https://u:p@example.test/quote"},
        {"twelve_data_quote_base_url": "https://example.test/quote?symbol=AAPL"},
        {"twelve_data_quote_base_url": "https://example.test/quote#fragment"},
        {"twelve_data_quote_base_url": "https://example.test/quote path"},
        {"twelve_data_timeout_seconds": 0},
        {"twelve_data_timeout_seconds": 121},
        {"twelve_data_max_response_bytes": 0},
        {"twelve_data_max_response_bytes": 10_485_761},
        {"twelve_data_user_agent": ""},
        {"twelve_data_user_agent": " unsafe"},
        {"twelve_data_user_agent": "unsafe\r\nagent"},
        {"twelve_data_user_agent": "x" * 257},
        {"twelve_data_api_key": ""},
        {"twelve_data_api_key": " unsafe"},
        {"twelve_data_api_key": "unsafe\r\nkey"},
        {"twelve_data_api_key": "x" * 513},
    ],
)
def test_invalid_twelve_data_settings_are_rejected(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        _settings(**overrides)


def test_production_environment_requires_twelve_data_key() -> None:
    with pytest.raises(ValidationError, match="TWELVE_DATA_API_KEY is required"):
        _settings(
            environment="production",
            database_url="postgresql://example.test/db",
            log_json=True,
            docs_enabled=False,
            internal_auth_secret="x" * 32,
        )


def test_production_registry_contains_exact_price_and_fx_sources() -> None:
    registry = create_production_price_registry(_settings())
    assert registry.sources == frozenset({PriceSource.coingecko, PriceSource.twelve_data})
    assert registry.get(PriceSource.coingecko).source is PriceSource.coingecko
    assert registry.get(PriceSource.twelve_data).source is PriceSource.twelve_data

    service = create_production_market_evidence_service(
        MagicMock(spec=AsyncSession),
        _settings(),
    )
    assert service.price_registry.sources == frozenset(
        {PriceSource.coingecko, PriceSource.twelve_data}
    )
    assert service.fx_registry.sources == frozenset({ExchangeRateSource.cnb})
