"""Production foreign-exchange providers and registry composition."""

from __future__ import annotations

import httpx

from app.config.settings import Settings
from app.modules.fx.providers.twelve_data import TwelveDataExchangeRateProvider
from app.modules.fx.providers.twelve_data_transport import (
    HttpxTwelveDataFxTransport,
    TwelveDataFxTransport,
)
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
)
from app.modules.market_data.providers import ExchangeRateProviderRegistry


def create_production_exchange_rate_registry(
    settings: Settings,
    *,
    policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
    twelve_data_fx_transport: TwelveDataFxTransport | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> ExchangeRateProviderRegistry:
    transport = twelve_data_fx_transport or HttpxTwelveDataFxTransport(
        base_url=settings.twelve_data_fx_base_url,
        api_key=(
            settings.twelve_data_api_key.get_secret_value()
            if settings.twelve_data_api_key is not None
            else None
        ),
        timeout_seconds=settings.twelve_data_timeout_seconds,
        max_response_bytes=settings.twelve_data_max_response_bytes,
        user_agent=settings.twelve_data_user_agent,
        transport=http_transport,
    )
    return ExchangeRateProviderRegistry((TwelveDataExchangeRateProvider(transport, policy=policy),))


__all__ = [
    "HttpxTwelveDataFxTransport",
    "TwelveDataExchangeRateProvider",
    "TwelveDataFxTransport",
    "create_production_exchange_rate_registry",
]
