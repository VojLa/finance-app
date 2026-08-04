"""Production market-price providers and registry composition."""

from __future__ import annotations

import httpx

from app.config.settings import Settings
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
)
from app.modules.market_data.providers import PriceProviderRegistry
from app.modules.prices.providers.coingecko import CoinGeckoPriceProvider
from app.modules.prices.providers.coingecko_transport import (
    CoinGeckoPriceTransport,
    HttpxCoinGeckoPriceTransport,
)


def create_production_price_registry(
    settings: Settings,
    *,
    policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
    coingecko_transport: CoinGeckoPriceTransport | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> PriceProviderRegistry:
    transport = coingecko_transport or HttpxCoinGeckoPriceTransport(
        base_url=settings.coingecko_price_base_url,
        timeout_seconds=settings.coingecko_price_timeout_seconds,
        max_response_bytes=settings.coingecko_price_max_response_bytes,
        user_agent=settings.coingecko_price_user_agent,
        demo_api_key=(
            settings.coingecko_demo_api_key.get_secret_value()
            if settings.coingecko_demo_api_key is not None
            else None
        ),
        transport=http_transport,
    )
    return PriceProviderRegistry((CoinGeckoPriceProvider(transport, policy=policy),))


__all__ = [
    "CoinGeckoPriceProvider",
    "CoinGeckoPriceTransport",
    "HttpxCoinGeckoPriceTransport",
    "create_production_price_registry",
]
