"""Production composition for exact market-evidence refresh."""

from typing import Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.modules.fx.providers import (
    TwelveDataFxTransport,
    YahooFinanceChartTransport,
    create_local_free_exchange_rate_registry,
    create_production_exchange_rate_registry,
)
from app.modules.market_data.acquisition_cache import CycleMarketAcquisitionCache
from app.modules.market_data.health_repository import MarketDataHealthRepository
from app.modules.market_data.health_service import MarketDataHealthService
from app.modules.market_data.models import MarketEvidenceRefreshPlan
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
)
from app.modules.market_data.requirements import BuildMarketEvidenceRefreshPlanCommand
from app.modules.market_data.service import MarketEvidenceRefreshService
from app.modules.market_data.source_policy import market_evidence_source_policy_from_settings
from app.modules.prices.providers import (
    CoinGeckoPriceTransport,
    TwelveDataPriceTransport,
    create_local_free_price_registry,
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
    yahoo_finance_transport: YahooFinanceChartTransport | None = None,
    yahoo_finance_http_transport: httpx.AsyncBaseTransport | None = None,
    planner: MarketEvidencePlanBuilder | None = None,
    acquisition_cache: CycleMarketAcquisitionCache | None = None,
) -> MarketEvidenceRefreshService:
    source_policy = market_evidence_source_policy_from_settings(settings)
    if source_policy.mode == "local_free":
        price_registry = create_local_free_price_registry(
            settings,
            policy=policy,
            coingecko_transport=coingecko_transport,
            coingecko_http_transport=coingecko_http_transport,
            yahoo_finance_transport=yahoo_finance_transport,
            yahoo_finance_http_transport=yahoo_finance_http_transport,
        )
        fx_registry = create_local_free_exchange_rate_registry(
            settings,
            policy=policy,
            yahoo_finance_transport=yahoo_finance_transport,
            http_transport=yahoo_finance_http_transport,
        )
    else:
        price_registry = create_production_price_registry(
            settings,
            policy=policy,
            coingecko_transport=coingecko_transport,
            twelve_data_transport=twelve_data_transport,
            coingecko_http_transport=coingecko_http_transport,
            twelve_data_http_transport=twelve_data_http_transport,
        )
        fx_registry = create_production_exchange_rate_registry(
            settings,
            policy=policy,
            twelve_data_fx_transport=twelve_data_fx_transport,
            http_transport=twelve_data_fx_http_transport,
        )
    if acquisition_cache is not None:
        price_registry = acquisition_cache.wrap_price_registry(price_registry)
        fx_registry = acquisition_cache.wrap_fx_registry(fx_registry)
    return MarketEvidenceRefreshService(
        session,
        price_registry=price_registry,
        fx_registry=fx_registry,
        fx_source=source_policy.fx_source,
        source_policy=source_policy,
        policy=policy,
        planner=planner,
        health=MarketDataHealthService(MarketDataHealthRepository(session)),
    )


__all__ = ["create_production_market_evidence_service"]
