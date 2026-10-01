"""Exact-source composition for canonical and local historical providers."""

from __future__ import annotations

import httpx

from app.config.settings import Settings
from app.modules.market_data.history.coingecko import (
    CoinGeckoHistoricalPriceProvider,
    CoinGeckoHistoricalPriceTransport,
    HttpxCoinGeckoHistoricalPriceTransport,
)
from app.modules.market_data.history.local_free import (
    YahooFinanceHistoricalExchangeRateProvider,
    YahooFinanceHistoricalPriceProvider,
)
from app.modules.market_data.history.models import HistoricalMarketEvidenceStateError
from app.modules.market_data.history.twelve_data import (
    HttpxTwelveDataHistoricalTimeSeriesTransport,
    TwelveDataHistoricalExchangeRateProvider,
    TwelveDataHistoricalPriceProvider,
    TwelveDataHistoricalTimeSeriesTransport,
)
from app.modules.market_data.source_policy import market_evidence_source_policy_from_settings
from app.modules.prices.providers.yahoo_finance_transport import (
    HttpxYahooFinanceChartTransport,
    YahooFinanceChartTransport,
)

COINGECKO_PRO_HISTORY_BASE_URL = "https://pro-api.coingecko.com/api/v3/coins"


def _create_coingecko_historical_transport(
    settings: Settings,
    *,
    http_transport: httpx.AsyncBaseTransport | None,
) -> HttpxCoinGeckoHistoricalPriceTransport:
    """Resolve exactly one public/demo or Pro CoinGecko historical transport."""

    demo_api_key = (
        settings.coingecko_demo_api_key.get_secret_value()
        if settings.coingecko_demo_api_key is not None
        else None
    )
    pro_api_key = (
        settings.coingecko_pro_api_key.get_secret_value()
        if settings.coingecko_pro_api_key is not None
        else None
    )
    if demo_api_key is not None and pro_api_key is not None:
        raise HistoricalMarketEvidenceStateError()
    return HttpxCoinGeckoHistoricalPriceTransport(
        base_url=(
            COINGECKO_PRO_HISTORY_BASE_URL
            if pro_api_key is not None
            else settings.coingecko_history_base_url
        ),
        timeout_seconds=settings.coingecko_price_timeout_seconds,
        max_response_bytes=settings.coingecko_price_max_response_bytes,
        user_agent=settings.coingecko_price_user_agent,
        demo_api_key=demo_api_key,
        pro_api_key=pro_api_key,
        transport=http_transport,
    )


def create_local_free_historical_yahoo_providers(
    settings: Settings,
    *,
    transport: YahooFinanceChartTransport | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[
    YahooFinanceHistoricalPriceProvider,
    YahooFinanceHistoricalExchangeRateProvider,
]:
    """Create Yahoo history providers only under the non-production local policy."""

    if not isinstance(settings, Settings) or settings.environment == "production":
        raise HistoricalMarketEvidenceStateError()
    source_policy = market_evidence_source_policy_from_settings(settings)
    if source_policy.mode != "local_free":
        raise HistoricalMarketEvidenceStateError()
    chart_transport = transport or HttpxYahooFinanceChartTransport(
        base_url=settings.yahoo_finance_chart_base_url,
        timeout_seconds=settings.yahoo_finance_timeout_seconds,
        max_response_bytes=settings.yahoo_finance_max_response_bytes,
        user_agent=settings.yahoo_finance_user_agent,
        transport=http_transport,
    )
    return (
        YahooFinanceHistoricalPriceProvider(chart_transport),
        YahooFinanceHistoricalExchangeRateProvider(chart_transport),
    )


def create_canonical_historical_twelve_data_providers(
    settings: Settings,
    *,
    transport: TwelveDataHistoricalTimeSeriesTransport | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[TwelveDataHistoricalPriceProvider, TwelveDataHistoricalExchangeRateProvider]:
    """Create canonical history providers only under the production source policy."""

    if not isinstance(settings, Settings):
        raise HistoricalMarketEvidenceStateError()
    source_policy = market_evidence_source_policy_from_settings(settings)
    if source_policy.mode != "canonical" or settings.twelve_data_api_key is None:
        raise HistoricalMarketEvidenceStateError()
    time_series_transport = transport or HttpxTwelveDataHistoricalTimeSeriesTransport(
        base_url=settings.twelve_data_fx_base_url,
        api_key=settings.twelve_data_api_key.get_secret_value(),
        timeout_seconds=settings.twelve_data_timeout_seconds,
        max_response_bytes=settings.twelve_data_max_response_bytes,
        user_agent=settings.twelve_data_user_agent,
        transport=http_transport,
    )
    return (
        TwelveDataHistoricalPriceProvider(time_series_transport),
        TwelveDataHistoricalExchangeRateProvider(time_series_transport),
    )


def create_canonical_historical_providers(
    settings: Settings,
    *,
    twelve_data_transport: TwelveDataHistoricalTimeSeriesTransport | None = None,
    coingecko_transport: CoinGeckoHistoricalPriceTransport | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[
    TwelveDataHistoricalPriceProvider,
    CoinGeckoHistoricalPriceProvider,
    TwelveDataHistoricalExchangeRateProvider,
]:
    """Create exact canonical listed, crypto and direct-FX history adapters."""

    listed_price, direct_fx = create_canonical_historical_twelve_data_providers(
        settings,
        transport=twelve_data_transport,
        http_transport=http_transport,
    )
    crypto_transport = coingecko_transport or _create_coingecko_historical_transport(
        settings,
        http_transport=http_transport,
    )
    return listed_price, CoinGeckoHistoricalPriceProvider(crypto_transport), direct_fx


def create_local_free_historical_providers(
    settings: Settings,
    *,
    yahoo_transport: YahooFinanceChartTransport | None = None,
    coingecko_transport: CoinGeckoHistoricalPriceTransport | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[
    YahooFinanceHistoricalPriceProvider,
    CoinGeckoHistoricalPriceProvider,
    YahooFinanceHistoricalExchangeRateProvider,
]:
    """Create exact local-free listed, crypto and direct-FX history adapters."""

    listed_price, direct_fx = create_local_free_historical_yahoo_providers(
        settings,
        transport=yahoo_transport,
        http_transport=http_transport,
    )
    crypto_transport = coingecko_transport or _create_coingecko_historical_transport(
        settings,
        http_transport=http_transport,
    )
    return listed_price, CoinGeckoHistoricalPriceProvider(crypto_transport), direct_fx


__all__ = [
    "create_canonical_historical_providers",
    "create_canonical_historical_twelve_data_providers",
    "create_local_free_historical_providers",
    "create_local_free_historical_yahoo_providers",
]
