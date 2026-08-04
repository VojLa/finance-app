"""Production foreign-exchange providers and registry composition."""

from __future__ import annotations

import httpx

from app.config.settings import Settings
from app.modules.fx.providers.cnb import CnbExchangeRateProvider
from app.modules.fx.providers.cnb_transport import CnbFxTransport, HttpxCnbFxTransport
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
)
from app.modules.market_data.providers import ExchangeRateProviderRegistry


def create_production_exchange_rate_registry(
    settings: Settings,
    *,
    policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
    cnb_transport: CnbFxTransport | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> ExchangeRateProviderRegistry:
    transport = cnb_transport or HttpxCnbFxTransport(
        base_url=settings.cnb_fx_base_url,
        timeout_seconds=settings.cnb_fx_timeout_seconds,
        max_response_bytes=settings.cnb_fx_max_response_bytes,
        user_agent=settings.cnb_fx_user_agent,
        transport=http_transport,
    )
    return ExchangeRateProviderRegistry((CnbExchangeRateProvider(transport, policy=policy),))


__all__ = [
    "CnbExchangeRateProvider",
    "CnbFxTransport",
    "HttpxCnbFxTransport",
    "create_production_exchange_rate_registry",
]
