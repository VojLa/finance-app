"""Runtime composition for direct Raiffeisenbank reporting FX evidence."""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.modules.fx.providers import (
    TwelveDataFxTransport,
    YahooFinanceChartTransport,
    create_local_free_exchange_rate_registry,
    create_production_exchange_rate_registry,
)
from app.modules.imports.raiffeisenbank_reporting_fx import (
    RaiffeisenbankReportingFxService,
)
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
)
from app.modules.market_data.source_policy import market_evidence_source_policy_from_settings


def create_raiffeisenbank_reporting_fx_service(
    session: AsyncSession,
    settings: Settings,
    *,
    policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
    twelve_data_fx_transport: TwelveDataFxTransport | None = None,
    twelve_data_fx_http_transport: httpx.AsyncBaseTransport | None = None,
    yahoo_finance_transport: YahooFinanceChartTransport | None = None,
    yahoo_finance_http_transport: httpx.AsyncBaseTransport | None = None,
) -> RaiffeisenbankReportingFxService:
    source_policy = market_evidence_source_policy_from_settings(settings)
    if source_policy.mode == "local_free":
        registry = create_local_free_exchange_rate_registry(
            settings,
            policy=policy,
            yahoo_finance_transport=yahoo_finance_transport,
            http_transport=yahoo_finance_http_transport,
        )
    else:
        registry = create_production_exchange_rate_registry(
            settings,
            policy=policy,
            twelve_data_fx_transport=twelve_data_fx_transport,
            http_transport=twelve_data_fx_http_transport,
        )
    return RaiffeisenbankReportingFxService(
        session,
        source_policy=source_policy,
        fx_registry=registry,
        policy=policy,
    )


__all__ = ["create_raiffeisenbank_reporting_fx_service"]
