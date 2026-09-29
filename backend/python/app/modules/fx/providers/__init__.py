"""Production foreign-exchange providers and registry composition."""

from __future__ import annotations

import httpx

from app.config.settings import Settings
from app.modules.fx.providers.twelve_data import TwelveDataExchangeRateProvider
from app.modules.fx.providers.twelve_data_transport import (
    HttpxTwelveDataFxTransport,
    TwelveDataFxTransport,
)
from app.modules.fx.providers.yahoo_finance import YahooFinanceExchangeRateProvider
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
)
from app.modules.market_data.providers import ExchangeRateProviderRegistry
from app.modules.market_data.source_policy import (
    MarketEvidenceSourcePolicyError,
    market_evidence_source_policy_from_settings,
)
from app.modules.prices.providers.yahoo_finance_transport import (
    HttpxYahooFinanceChartTransport,
    YahooFinanceChartTransport,
)


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


def create_local_free_exchange_rate_registry(
    settings: Settings,
    *,
    policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
    yahoo_finance_transport: YahooFinanceChartTransport | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> ExchangeRateProviderRegistry:
    source_policy = market_evidence_source_policy_from_settings(settings)
    if source_policy.mode != "local_free":
        raise MarketEvidenceSourcePolicyError()
    transport = yahoo_finance_transport or HttpxYahooFinanceChartTransport(
        base_url=settings.yahoo_finance_chart_base_url,
        timeout_seconds=settings.yahoo_finance_timeout_seconds,
        max_response_bytes=settings.yahoo_finance_max_response_bytes,
        user_agent=settings.yahoo_finance_user_agent,
        transport=http_transport,
    )
    return ExchangeRateProviderRegistry(
        (YahooFinanceExchangeRateProvider(transport, policy=policy),)
    )


__all__ = [
    "HttpxTwelveDataFxTransport",
    "HttpxYahooFinanceChartTransport",
    "TwelveDataExchangeRateProvider",
    "TwelveDataFxTransport",
    "YahooFinanceChartTransport",
    "YahooFinanceExchangeRateProvider",
    "create_local_free_exchange_rate_registry",
    "create_production_exchange_rate_registry",
]
