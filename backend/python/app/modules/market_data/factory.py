"""Production composition for exact market-evidence refresh."""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.db.models.enums import ExchangeRateSource
from app.modules.fx.providers import (
    CnbFxTransport,
    create_production_exchange_rate_registry,
)
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
)
from app.modules.market_data.service import MarketEvidenceRefreshService
from app.modules.prices.providers import (
    CoinGeckoPriceTransport,
    create_production_price_registry,
)


def create_production_market_evidence_service(
    session: AsyncSession,
    settings: Settings,
    *,
    policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
    cnb_transport: CnbFxTransport | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
    coingecko_transport: CoinGeckoPriceTransport | None = None,
    coingecko_http_transport: httpx.AsyncBaseTransport | None = None,
) -> MarketEvidenceRefreshService:
    return MarketEvidenceRefreshService(
        session,
        price_registry=create_production_price_registry(
            settings,
            policy=policy,
            coingecko_transport=coingecko_transport,
            http_transport=coingecko_http_transport,
        ),
        fx_registry=create_production_exchange_rate_registry(
            settings,
            policy=policy,
            cnb_transport=cnb_transport,
            http_transport=http_transport,
        ),
        fx_source=ExchangeRateSource.cnb,
        policy=policy,
    )


__all__ = ["create_production_market_evidence_service"]
