from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest

from app.db.models.enums import MarketDataFailureReason as Reason
from app.db.models.enums import PriceSource
from app.modules.market_data.models import PriceRequirement
from app.modules.market_data.provider_failure import ProviderFailure
from app.modules.prices.providers.coingecko import CoinGeckoPriceProvider
from app.modules.prices.providers.coingecko_models import CoinGeckoHttpResponse
from app.modules.prices.providers.coingecko_transport import HttpxCoinGeckoPriceTransport
from app.modules.prices.providers.twelve_data import TwelveDataPriceProvider
from app.modules.prices.providers.twelve_data_models import TwelveDataHttpResponse
from app.modules.prices.providers.twelve_data_transport import (
    HttpxTwelveDataPriceTransport,
    TwelveDataPriceTransport,
)
from app.modules.prices.providers.yahoo_finance import YahooFinancePriceProvider
from app.modules.prices.providers.yahoo_finance_models import YahooFinanceHttpResponse
from app.modules.prices.providers.yahoo_finance_transport import HttpxYahooFinanceChartTransport


class ResponseTransport:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls = 0

    async def fetch_chart(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        return self.response

    async def fetch_quote(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        return self.response

    async def fetch_simple_price(self, *args: object, **kwargs: object) -> object:
        self.calls += 1
        return self.response


def requirement(source: PriceSource, symbol: str) -> PriceRequirement:
    return PriceRequirement(
        account_id="account",
        asset_id="asset",
        listing_id="listing",
        listing_currency="USD",
        provider=source,
        provider_symbol=symbol,
        through=datetime(2026, 8, 5, 12, 34) + timedelta(hours=1),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,source,symbol,response",
    [
        (
            YahooFinancePriceProvider,
            PriceSource.yahoo_finance,
            "AAPL",
            YahooFinanceHttpResponse(404, "application/json", b""),
        ),
        (
            TwelveDataPriceProvider,
            PriceSource.twelve_data,
            '{"symbol":"AAPL","mic_code":"XNAS"}',
            TwelveDataHttpResponse(404, "application/json", b""),
        ),
        (
            CoinGeckoPriceProvider,
            PriceSource.coingecko,
            "bitcoin",
            CoinGeckoHttpResponse(404, "application/json", b""),
        ),
    ],
)
async def test_adapter_classifies_response_status(provider, source, symbol, response) -> None:
    transport = ResponseTransport(response)
    with pytest.raises(ProviderFailure) as caught:
        await provider(transport).fetch(requirement(source, symbol))
    assert caught.value.reason is Reason.unknown_symbol
    assert transport.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,source,symbol,response",
    [
        (
            YahooFinancePriceProvider,
            PriceSource.yahoo_finance,
            "AAPL",
            YahooFinanceHttpResponse(429, "application/json", b""),
        ),
        (
            TwelveDataPriceProvider,
            PriceSource.twelve_data,
            '{"symbol":"AAPL","mic_code":"XNAS"}',
            TwelveDataHttpResponse(429, "application/json", b""),
        ),
        (
            CoinGeckoPriceProvider,
            PriceSource.coingecko,
            "bitcoin",
            CoinGeckoHttpResponse(429, "application/json", b""),
        ),
    ],
)
async def test_rate_limit_is_one_shot(provider, source, symbol, response) -> None:
    transport = ResponseTransport(response)
    with pytest.raises(ProviderFailure) as caught:
        await provider(transport).fetch(requirement(source, symbol))
    assert caught.value.reason is Reason.rate_limit
    assert transport.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,source,symbol,response",
    [
        (
            YahooFinancePriceProvider,
            PriceSource.yahoo_finance,
            "AAPL",
            YahooFinanceHttpResponse(429, "application/json", b"", "120"),
        ),
        (
            TwelveDataPriceProvider,
            PriceSource.twelve_data,
            '{"symbol":"AAPL","mic_code":"XNAS"}',
            TwelveDataHttpResponse(429, "application/json", b"", "120"),
        ),
        (
            CoinGeckoPriceProvider,
            PriceSource.coingecko,
            "bitcoin",
            CoinGeckoHttpResponse(429, "application/json", b"", "120"),
        ),
    ],
)
async def test_rate_limit_retry_after_reaches_provider_failure(
    provider, source, symbol, response
) -> None:
    transport = ResponseTransport(response)
    before = datetime.now(UTC).replace(tzinfo=None)
    with pytest.raises(ProviderFailure) as caught:
        await provider(transport).fetch(requirement(source, symbol))
    after = datetime.now(UTC).replace(tzinfo=None)
    assert caught.value.reason is Reason.rate_limit
    assert caught.value.retry_after is not None
    assert before < caught.value.retry_after <= after + timedelta(seconds=121)
    assert transport.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,source,symbol,response",
    [
        (
            YahooFinancePriceProvider,
            PriceSource.yahoo_finance,
            "AAPL",
            YahooFinanceHttpResponse(429, "application/json", b"", "not-a-date"),
        ),
        (
            TwelveDataPriceProvider,
            PriceSource.twelve_data,
            '{"symbol":"AAPL","mic_code":"XNAS"}',
            TwelveDataHttpResponse(429, "application/json", b"", "not-a-date"),
        ),
        (
            CoinGeckoPriceProvider,
            PriceSource.coingecko,
            "bitcoin",
            CoinGeckoHttpResponse(429, "application/json", b"", "not-a-date"),
        ),
    ],
)
async def test_malformed_retry_after_uses_default_fallback(
    provider, source, symbol, response
) -> None:
    transport = ResponseTransport(response)
    with pytest.raises(ProviderFailure) as caught:
        await provider(transport).fetch(requirement(source, symbol))
    assert caught.value.reason is Reason.rate_limit
    assert caught.value.retry_after is None
    assert transport.calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_name", ["yahoo", "twelve_data", "coingecko"])
async def test_http_transport_carries_retry_after_into_provider_failure(provider_name: str) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"rEtRy-AfTeR": " 120 "})

    mock_transport = httpx.MockTransport(handler)
    if provider_name == "yahoo":
        yahoo_transport = HttpxYahooFinanceChartTransport(
            base_url="https://yahoo.test/chart",
            timeout_seconds=2,
            max_response_bytes=1024,
            user_agent="finance-app/test",
            transport=mock_transport,
        )
        yahoo_provider = YahooFinancePriceProvider(yahoo_transport)
        req = requirement(PriceSource.yahoo_finance, "AAPL")
    elif provider_name == "twelve_data":
        twelve_data_transport = HttpxTwelveDataPriceTransport(
            base_url="https://twelve.test/quote",
            timeout_seconds=2,
            max_response_bytes=1024,
            user_agent="finance-app/test",
            api_key="test-key",
            transport=mock_transport,
        )
        twelve_data_provider = TwelveDataPriceProvider(twelve_data_transport)
        req = requirement(PriceSource.twelve_data, '{"symbol":"AAPL","mic_code":"XNAS"}')
    else:
        coingecko_transport = HttpxCoinGeckoPriceTransport(
            base_url="https://coingecko.test/simple/price",
            timeout_seconds=2,
            max_response_bytes=1024,
            user_agent="finance-app/test",
            transport=mock_transport,
        )
        coingecko_provider = CoinGeckoPriceProvider(coingecko_transport)
        req = requirement(PriceSource.coingecko, "bitcoin")
    with pytest.raises(ProviderFailure) as caught:
        await (
            yahoo_provider.fetch(req)
            if provider_name == "yahoo"
            else twelve_data_provider.fetch(req)
            if provider_name == "twelve_data"
            else coingecko_provider.fetch(req)
        )
    assert caught.value.reason is Reason.rate_limit
    assert caught.value.retry_after is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider,source,symbol,response",
    [
        (
            YahooFinancePriceProvider,
            PriceSource.yahoo_finance,
            "AAPL",
            YahooFinanceHttpResponse(200, "application/json", b"{}"),
        ),
        (
            TwelveDataPriceProvider,
            PriceSource.twelve_data,
            '{"symbol":"AAPL","mic_code":"XNAS"}',
            TwelveDataHttpResponse(200, "application/json", b"{}"),
        ),
        (
            CoinGeckoPriceProvider,
            PriceSource.coingecko,
            "bitcoin",
            CoinGeckoHttpResponse(200, "application/json", b'{"bitcoin":null}'),
        ),
    ],
)
async def test_incomplete_body_retries_at_most_twice(provider, source, symbol, response) -> None:
    transport = ResponseTransport(response)
    with pytest.raises(ProviderFailure) as caught:
        await provider(transport).fetch(requirement(source, symbol))
    assert caught.value.reason is Reason.incomplete_response
    assert transport.calls == 3


@pytest.mark.asyncio
async def test_parser_preserves_exact_identity_and_currency_reason() -> None:
    symbol = '{"symbol":"AAPL","mic_code":"XNAS"}'
    body = (
        b'{"symbol":"MSFT","mic_code":"XNAS","currency":"USD",'
        b'"datetime":"2026-08-05 12:34:00","timestamp":1785933240,'
        b'"last_quote_at":1785933240,"close":"1"}'
    )
    transport = ResponseTransport(TwelveDataHttpResponse(200, "application/json", body))
    with pytest.raises(ProviderFailure) as caught:
        await TwelveDataPriceProvider(cast(TwelveDataPriceTransport, transport)).fetch(
            requirement(PriceSource.twelve_data, symbol)
        )
    assert caught.value.reason is Reason.provider_identity_conflict
    assert transport.calls == 1
