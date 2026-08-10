"""Production composition for exact market-evidence refresh."""

from typing import Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.db.models.enums import ExchangeRateSource
from app.modules.fx.providers import (
    TwelveDataFxTransport,
    create_production_exchange_rate_registry,
)
from app.modules.market_data.models import MarketEvidenceRefreshPlan
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
)
from app.modules.market_data.requirements import BuildMarketEvidenceRefreshPlanCommand
from app.modules.market_data.service import MarketEvidenceRefreshService
from app.modules.prices.providers import (
    CoinGeckoPriceTransport,
    TwelveDataPriceTransport,
    create_production_price_registry,
)


class MarketEvidencePlanBuilder(Protocol):
    async def build(
        self,
        command: BuildMarketEvidenceRefreshPlanCommand,
    ) -> MarketEvidenceRefreshPlan: ...


def create_production_market_evidence_service(
    session: AsyncSession,
    settings: Settings,
    *,
    policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
    twelve_data_fx_transport: TwelveDataFxTransport | None = None,
    twelve_data_fx_http_transport: httpx.AsyncBaseTransport | None = None,
    coingecko_transport: CoinGeckoPriceTransport | None = None,
    coingecko_http_transport: httpx.AsyncBaseTransport | None = None,
    twelve_data_transport: TwelveDataPriceTransport | None = None,
    twelve_data_http_transport: httpx.AsyncBaseTransport | None = None,
    planner: MarketEvidencePlanBuilder | None = None,
) -> MarketEvidenceRefreshService:
    return MarketEvidenceRefreshService(
        session,
        price_registry=create_production_price_registry(
            settings,
            policy=policy,
            coingecko_transport=coingecko_transport,
            twelve_data_transport=twelve_data_transport,
            coingecko_http_transport=coingecko_http_transport,
            twelve_data_http_transport=twelve_data_http_transport,
        ),
        fx_registry=create_production_exchange_rate_registry(
            settings,
            policy=policy,
            twelve_data_fx_transport=twelve_data_fx_transport,
            http_transport=twelve_data_fx_http_transport,
        ),
        fx_source=ExchangeRateSource.twelve_data,
        policy=policy,
        planner=planner,
    )


__all__ = ["create_production_market_evidence_service"]
