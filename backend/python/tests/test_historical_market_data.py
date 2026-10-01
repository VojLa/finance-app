from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any, cast

import httpx
import pytest

from app.config.settings import Settings
from app.db.models.enums import ExchangeRateSource, PriceSource
from app.modules.fx.models import ExchangeRateObservation
from app.modules.market_data.history.coingecko import (
    CoinGeckoHistoricalPriceProvider,
    HttpxCoinGeckoHistoricalPriceTransport,
    parse_coingecko_market_chart_range,
)
from app.modules.market_data.history.factory import (
    create_canonical_historical_providers,
    create_local_free_historical_providers,
    create_local_free_historical_yahoo_providers,
)
from app.modules.market_data.history.local_free import (
    YahooFinanceHistoricalExchangeRateProvider,
    YahooFinanceHistoricalPriceProvider,
)
from app.modules.market_data.history.models import (
    HistoricalExchangeRateRangeRequirement,
    HistoricalMarketEvidenceStateError,
    HistoricalPriceRangeRequirement,
    HistoricalTimeSeriesInterval,
)
from app.modules.market_data.history.ranges import (
    HistoricalTimeRange,
    build_historical_window,
    chunk_historical_window,
)
from app.modules.market_data.history.selection import (
    select_historical_exchange_rates,
    select_historical_prices,
)
from app.modules.market_data.history.twelve_data import (
    TwelveDataHistoricalTimeSeriesTransport,
)
from app.modules.market_data.policy import DEFAULT_MARKET_EVIDENCE_POLICY
from app.modules.prices.models import PriceObservation
from app.modules.prices.providers.yahoo_finance_models import YahooFinanceHttpResponse
from app.modules.prices.providers.yahoo_finance_transport import YahooFinanceChartTransport

T0 = datetime(2024, 8, 5, 12)
T1 = datetime(2024, 8, 6, 12)


def _price_requirement(
    requested_at: tuple[datetime, ...] = (T0, T1),
    *,
    source: PriceSource = PriceSource.yahoo_finance,
    symbol: str = "VUAA.MI",
) -> HistoricalPriceRangeRequirement:
    return HistoricalPriceRangeRequirement(
        asset_id="asset-a",
        listing_id="listing-a",
        listing_currency="EUR",
        provider=source,
        provider_symbol=symbol,
        requested_at=requested_at,
    )


def _fx_requirement(
    requested_at: tuple[datetime, ...] = (T0, T1),
) -> HistoricalExchangeRateRangeRequirement:
    return HistoricalExchangeRateRangeRequirement(
        from_currency="EUR",
        to_currency="CZK",
        provider=ExchangeRateSource.yahoo_finance,
        requested_at=requested_at,
    )


def _yahoo_body(
    *,
    symbol: str,
    currency: str,
    points: tuple[tuple[datetime, str], ...],
    data_granularity: str | None = None,
) -> bytes:
    meta: dict[str, object] = {"symbol": symbol, "currency": currency, "priceHint": 2}
    if data_granularity is not None:
        meta["dataGranularity"] = data_granularity
    document = {
        "chart": {
            "result": [
                {
                    "meta": meta,
                    "timestamp": [int(item[0].replace(tzinfo=UTC).timestamp()) for item in points],
                    "indicators": {"quote": [{"close": [item[1] for item in points]}]},
                }
            ],
            "error": None,
        }
    }
    return json.dumps(document, separators=(",", ":")).encode()


class _YahooTransport(YahooFinanceChartTransport):
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[tuple[str, datetime, datetime, str]] = []

    async def fetch_chart(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> YahooFinanceHttpResponse:
        self.calls.append((symbol, start, end, interval))
        return YahooFinanceHttpResponse(200, "application/json", self.body)


class _WindowedYahooTransport(YahooFinanceChartTransport):
    def __init__(
        self,
        *,
        symbol: str,
        currency: str,
        points: tuple[tuple[datetime, str], ...],
    ) -> None:
        self.symbol = symbol
        self.currency = currency
        self.points = points
        self.calls: list[tuple[str, datetime, datetime, str]] = []

    async def fetch_chart(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> YahooFinanceHttpResponse:
        self.calls.append((symbol, start, end, interval))
        selected = tuple(
            point
            for point in self.points
            if start - timedelta(minutes=30) <= point[0] < end + timedelta(minutes=30)
        )
        return YahooFinanceHttpResponse(
            200,
            "application/json",
            _yahoo_body(
                symbol=self.symbol,
                currency=self.currency,
                points=selected,
                data_granularity="30m",
            ),
        )


class _SequenceYahooTransport(YahooFinanceChartTransport):
    def __init__(self, bodies: list[bytes]) -> None:
        self.bodies = bodies
        self.calls = 0

    async def fetch_chart(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> YahooFinanceHttpResponse:
        self.calls += 1
        return YahooFinanceHttpResponse(200, "application/json", self.bodies.pop(0))


def _price(timestamp: datetime, value: str) -> PriceObservation:
    return PriceObservation(
        asset_id="asset-a",
        listing_id="listing-a",
        provider=PriceSource.yahoo_finance,
        provider_symbol="VUAA.MI",
        price=Decimal(value),
        currency="EUR",
        observed_at=timestamp,
    )


def _rate(timestamp: datetime, value: str) -> ExchangeRateObservation:
    return ExchangeRateObservation(
        from_currency="EUR",
        to_currency="CZK",
        provider=ExchangeRateSource.yahoo_finance,
        rate=Decimal(value),
        effective_at=timestamp,
    )


def test_range_chunks_are_contiguous_ordered_and_bounded() -> None:
    window = HistoricalTimeRange(datetime(2020, 1, 1), datetime(2022, 7, 1))

    chunks = chunk_historical_window(window, maximum_span=timedelta(days=365))

    assert chunks[0].start == window.start
    assert chunks[-1].end == window.end
    assert all(chunk.end - chunk.start <= timedelta(days=365) for chunk in chunks)
    assert all(left.end == right.start for left, right in pairwise(chunks))


def test_window_adds_only_required_lookback_and_one_millisecond_end() -> None:
    result = build_historical_window((T0, T1), lookback=timedelta(hours=72))

    assert result == HistoricalTimeRange(T0 - timedelta(hours=72), T1 + timedelta(milliseconds=1))


def test_selection_is_as_of_ordered_and_deduplicates_reused_evidence() -> None:
    selections = select_historical_prices(
        _price_requirement((T0, T0 + timedelta(hours=1))),
        (_price(T0 - timedelta(hours=1), "100"),),
        policy=DEFAULT_MARKET_EVIDENCE_POLICY,
    )

    assert tuple(item.through for item in selections) == (T0, T0 + timedelta(hours=1))
    assert selections[0].observation == selections[1].observation


@pytest.mark.parametrize(
    "candidates",
    [
        (_price(T0, "100"), _price(T0 - timedelta(hours=1), "99")),
        (_price(T0, "100"), _price(T0, "100")),
        (
            PriceObservation(
                asset_id="asset-a",
                listing_id="listing-a",
                provider=PriceSource.coingecko,
                provider_symbol="VUAA.MI",
                price=Decimal("100"),
                currency="EUR",
                observed_at=T0,
            ),
        ),
    ],
)
def test_price_selection_rejects_unsorted_duplicate_or_wrong_source(
    candidates: tuple[PriceObservation, ...],
) -> None:
    with pytest.raises(HistoricalMarketEvidenceStateError):
        select_historical_prices(
            _price_requirement((T0,)), candidates, policy=DEFAULT_MARKET_EVIDENCE_POLICY
        )


@pytest.mark.parametrize(
    "candidate",
    [
        PriceObservation(
            asset_id="other-asset",
            listing_id="listing-a",
            provider=PriceSource.yahoo_finance,
            provider_symbol="VUAA.MI",
            price=Decimal("100"),
            currency="EUR",
            observed_at=T0,
        ),
        PriceObservation(
            asset_id="asset-a",
            listing_id="other-listing",
            provider=PriceSource.yahoo_finance,
            provider_symbol="VUAA.MI",
            price=Decimal("100"),
            currency="EUR",
            observed_at=T0,
        ),
        PriceObservation(
            asset_id="asset-a",
            listing_id="listing-a",
            provider=PriceSource.yahoo_finance,
            provider_symbol="OTHER",
            price=Decimal("100"),
            currency="EUR",
            observed_at=T0,
        ),
        PriceObservation(
            asset_id="asset-a",
            listing_id="listing-a",
            provider=PriceSource.yahoo_finance,
            provider_symbol="VUAA.MI",
            price=Decimal("100"),
            currency="USD",
            observed_at=T0,
        ),
    ],
)
def test_price_selection_rejects_cross_identity_or_currency_evidence(
    candidate: PriceObservation,
) -> None:
    with pytest.raises(HistoricalMarketEvidenceStateError):
        select_historical_prices(
            _price_requirement((T0,)), (candidate,), policy=DEFAULT_MARKET_EVIDENCE_POLICY
        )


@pytest.mark.parametrize(
    "candidates",
    [
        (_price(T0 + timedelta(minutes=1), "100"),),
        (_price(T0 - timedelta(hours=72, milliseconds=1), "100"),),
        (),
    ],
)
def test_price_selection_rejects_future_stale_or_missing_evidence(
    candidates: tuple[PriceObservation, ...],
) -> None:
    with pytest.raises(HistoricalMarketEvidenceStateError):
        select_historical_prices(
            _price_requirement((T0,)), candidates, policy=DEFAULT_MARKET_EVIDENCE_POLICY
        )


@pytest.mark.parametrize(
    "candidates",
    [
        (_rate(T0 + timedelta(days=1), "25"),),
        (_rate(T0 - timedelta(days=7, milliseconds=1), "25"),),
        (),
    ],
)
def test_rate_selection_rejects_future_stale_or_missing_evidence(
    candidates: tuple[ExchangeRateObservation, ...],
) -> None:
    with pytest.raises(HistoricalMarketEvidenceStateError):
        select_historical_exchange_rates(
            _fx_requirement((T0,)), candidates, policy=DEFAULT_MARKET_EVIDENCE_POLICY
        )


@pytest.mark.parametrize(
    "candidate",
    [
        ExchangeRateObservation(
            from_currency="USD",
            to_currency="CZK",
            provider=ExchangeRateSource.yahoo_finance,
            rate=Decimal("25"),
            effective_at=T0,
        ),
        ExchangeRateObservation(
            from_currency="EUR",
            to_currency="USD",
            provider=ExchangeRateSource.yahoo_finance,
            rate=Decimal("25"),
            effective_at=T0,
        ),
        ExchangeRateObservation(
            from_currency="EUR",
            to_currency="CZK",
            provider=ExchangeRateSource.twelve_data,
            rate=Decimal("25"),
            effective_at=T0,
        ),
    ],
)
def test_rate_selection_rejects_cross_pair_or_source_evidence(
    candidate: ExchangeRateObservation,
) -> None:
    with pytest.raises(HistoricalMarketEvidenceStateError):
        select_historical_exchange_rates(
            _fx_requirement((T0,)), (candidate,), policy=DEFAULT_MARKET_EVIDENCE_POLICY
        )


@pytest.mark.asyncio
async def test_yahoo_historical_price_and_fx_use_daily_ranges_without_inversion() -> None:
    price_transport = _YahooTransport(
        _yahoo_body(
            symbol="VUAA.MI",
            currency="EUR",
            points=((datetime(2024, 8, 5), "100"), (datetime(2024, 8, 6), "101")),
        )
    )
    fx_transport = _YahooTransport(
        _yahoo_body(
            symbol="EURCZK=X",
            currency="CZK",
            points=((datetime(2024, 8, 5), "25"), (datetime(2024, 8, 6), "26")),
        )
    )

    prices = await YahooFinanceHistoricalPriceProvider(price_transport).fetch_range(
        _price_requirement()
    )
    rates = await YahooFinanceHistoricalExchangeRateProvider(fx_transport).fetch_range(
        _fx_requirement()
    )

    assert [item.price for item in prices] == [Decimal("100.00"), Decimal("101.00")]
    assert [item.rate for item in rates] == [Decimal("25.00"), Decimal("26.00")]
    assert price_transport.calls[0][0] == "VUAA.MI"
    assert fx_transport.calls[0][0] == "EURCZK=X"
    assert all(call[3] == "1d" for call in (*price_transport.calls, *fx_transport.calls))
    assert YahooFinanceHistoricalPriceProvider.capability.native_granularity.value == (
        "provider_determined"
    )
    assert YahooFinanceHistoricalPriceProvider.capability.supports_subdaily_backfill


@pytest.mark.asyncio
async def test_yahoo_historical_daily_ranges_ignore_the_exclusive_end_point() -> None:
    price_transport = _YahooTransport(
        _yahoo_body(
            symbol="VUAA.MI",
            currency="EUR",
            points=(
                (datetime(2024, 8, 5), "100"),
                (datetime(2024, 8, 6), "101"),
                (datetime(2024, 8, 7), "102"),
            ),
        )
    )
    fx_transport = _YahooTransport(
        _yahoo_body(
            symbol="EURCZK=X",
            currency="CZK",
            points=(
                (datetime(2024, 8, 5), "25"),
                (datetime(2024, 8, 6), "26"),
                (datetime(2024, 8, 7), "27"),
            ),
        )
    )
    requirement = _price_requirement((datetime(2024, 8, 5), datetime(2024, 8, 6)))
    fx_requirement = _fx_requirement((datetime(2024, 8, 5), datetime(2024, 8, 6)))

    prices = await YahooFinanceHistoricalPriceProvider(price_transport).fetch_range(requirement)
    rates = await YahooFinanceHistoricalExchangeRateProvider(fx_transport).fetch_range(
        fx_requirement
    )

    assert [item.price for item in prices] == [Decimal("100.00"), Decimal("101.00")]
    assert [item.rate for item in rates] == [Decimal("25.00"), Decimal("26.00")]


@pytest.mark.asyncio
async def test_yahoo_historical_btc_usd_and_usd_czk_use_physical_direct_evidence() -> None:
    price_transport = _YahooTransport(
        _yahoo_body(
            symbol="BTC-USD",
            currency="USD",
            points=((datetime(2024, 8, 5), "55000"),),
        )
    )
    fx_transport = _YahooTransport(
        _yahoo_body(
            # Yahoo accepts the short USD-base request ticker but reports the
            # canonical explicit base in response metadata.
            symbol="USDCZK=X",
            currency="CZK",
            points=((datetime(2024, 8, 5), "23"),),
        )
    )
    price_requirement = _price_requirement((T0,), symbol="BTC-USD")
    price_requirement = replace(price_requirement, listing_currency="USD")
    fx_requirement = HistoricalExchangeRateRangeRequirement(
        from_currency="USD",
        to_currency="CZK",
        provider=ExchangeRateSource.yahoo_finance,
        requested_at=(T0,),
    )

    prices = await YahooFinanceHistoricalPriceProvider(price_transport).fetch_range(
        price_requirement
    )
    rates = await YahooFinanceHistoricalExchangeRateProvider(fx_transport).fetch_range(
        fx_requirement
    )

    assert prices[0].provider_symbol == "BTC-USD"
    assert prices[0].currency == "USD"
    assert rates[0].from_currency == "USD"
    assert rates[0].to_currency == "CZK"
    assert [call[0] for call in price_transport.calls] == ["BTC-USD"]
    assert [call[0] for call in fx_transport.calls] == ["CZK=X"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "symbol,currency",
    [("VUAA.DE", "EUR"), ("VUAA.MI", "USD")],
)
async def test_yahoo_historical_price_rejects_wrong_response_identity(
    symbol: str,
    currency: str,
) -> None:
    transport = _YahooTransport(
        _yahoo_body(symbol=symbol, currency=currency, points=((datetime(2024, 8, 5), "100"),))
    )

    with pytest.raises(HistoricalMarketEvidenceStateError):
        await YahooFinanceHistoricalPriceProvider(transport).fetch_range(_price_requirement((T0,)))


def _coingecko_transport(
    handler: Any,
    *,
    max_response_bytes: int = 1_048_576,
    demo_api_key: str | None = None,
    pro_api_key: str | None = None,
) -> HttpxCoinGeckoHistoricalPriceTransport:
    return HttpxCoinGeckoHistoricalPriceTransport(
        base_url="https://api.coingecko.test/api/v3/coins",
        timeout_seconds=10,
        max_response_bytes=max_response_bytes,
        user_agent="finance-app/0.1",
        demo_api_key=demo_api_key,
        pro_api_key=pro_api_key,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_coingecko_range_transport_is_bounded_and_keeps_key_out_of_url() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json; charset=utf-8"},
            content=b'{"prices":[[1722859200000,61234.123456789]],"market_caps":[],"total_volumes":[]}',
        )

    body = await _coingecko_transport(handler, demo_api_key="demo-secret").fetch_market_chart_range(
        "bitcoin", "eur", start=T0, end=T1
    )

    assert body.startswith(b'{"prices"')
    assert str(seen[0].url).startswith(
        "https://api.coingecko.test/api/v3/coins/bitcoin/market_chart/range?"
    )
    assert seen[0].url.params["vs_currency"] == "eur"
    assert seen[0].headers["x-cg-demo-api-key"] == "demo-secret"
    assert "demo-secret" not in str(seen[0].url)


@pytest.mark.asyncio
async def test_coingecko_range_transport_uses_exact_pro_header_without_url_leak() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b'{"prices":[[1722859200000,61234]],"market_caps":[],"total_volumes":[]}',
        )

    await _coingecko_transport(handler, pro_api_key="pro-secret").fetch_market_chart_range(
        "bitcoin", "eur", start=T0, end=T1
    )

    assert seen[0].headers["x-cg-pro-api-key"] == "pro-secret"
    assert "x-cg-demo-api-key" not in seen[0].headers
    assert "pro-secret" not in str(seen[0].url)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500])
async def test_coingecko_range_transport_rejects_quota_and_body_limit(status: int) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"content-type": "application/json"}, content=b"{}")

    with pytest.raises(HistoricalMarketEvidenceStateError):
        await _coingecko_transport(handler).fetch_market_chart_range(
            "bitcoin", "eur", start=T0, end=T1
        )

    with pytest.raises(HistoricalMarketEvidenceStateError):
        await _coingecko_transport(
            lambda _: httpx.Response(
                200, headers={"content-type": "application/json"}, content=b"12345"
            ),
            max_response_bytes=4,
        ).fetch_market_chart_range("bitcoin", "eur", start=T0, end=T1)


@pytest.mark.parametrize(
    "overrides",
    [
        {"base_url": "http://api.coingecko.test/api/v3/coins"},
        {"base_url": "https://user:secret@api.coingecko.test/api/v3/coins"},
        {"base_url": "https://api.coingecko.test/api/v3/coins?key=secret"},
        {"base_url": "https://api.coingecko.test/api/v3/coins/"},
        {"timeout_seconds": 0},
        {"max_response_bytes": 10_485_761},
        {"user_agent": "unsafe\r\nagent"},
        {"demo_api_key": "unsafe\r\nkey"},
        {"pro_api_key": "unsafe\r\nkey"},
        {"pro_api_key": "x" * 513},
        {"demo_api_key": "demo-secret", "pro_api_key": "pro-secret"},
    ],
)
def test_coingecko_range_transport_rejects_unbounded_or_credentialed_configuration(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "base_url": "https://api.coingecko.test/api/v3/coins",
        "timeout_seconds": 10,
        "max_response_bytes": 1_048_576,
        "user_agent": "finance-app/0.1",
        "demo_api_key": None,
        "pro_api_key": None,
        "transport": httpx.MockTransport(lambda _: httpx.Response(200)),
    }
    values.update(overrides)

    with pytest.raises(HistoricalMarketEvidenceStateError):
        HttpxCoinGeckoHistoricalPriceTransport(**cast(Any, values))


@pytest.mark.asyncio
async def test_coingecko_range_transport_rejects_redirect_without_forwarding_demo_key() -> None:
    secret = "demo-secret"
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            302,
            headers={"location": "https://evil.test/redirect", "content-type": "application/json"},
        )

    with pytest.raises(HistoricalMarketEvidenceStateError):
        await _coingecko_transport(handler, demo_api_key=secret).fetch_market_chart_range(
            "bitcoin", "eur", start=T0, end=T1
        )
    assert len(seen) == 1
    assert seen[0].headers["x-cg-demo-api-key"] == secret


def test_coingecko_range_parser_uses_decimal_and_rejects_future_shape_tricks() -> None:
    points = parse_coingecko_market_chart_range(
        b'{"prices":[[1722859200000,61234.123456789]],"market_caps":[],"total_volumes":[]}'
    )

    assert points == ((datetime(2024, 8, 5, 12), Decimal("61234.123456789")),)
    with pytest.raises(HistoricalMarketEvidenceStateError):
        parse_coingecko_market_chart_range(
            b'{"prices":[[1,1],[1,2]],"market_caps":[],"total_volumes":[]}'
        )
    with pytest.raises(HistoricalMarketEvidenceStateError):
        parse_coingecko_market_chart_range(
            b'{"prices":[[1722859200000,1]],"market_caps":{},"total_volumes":true}'
        )


@pytest.mark.parametrize("span", [timedelta(microseconds=1), timedelta(milliseconds=1)])
def test_history_ranges_reject_non_millisecond_or_unbounded_chunking(span: timedelta) -> None:
    window = HistoricalTimeRange(datetime(2020, 1, 1), datetime(2024, 1, 1))

    with pytest.raises(HistoricalMarketEvidenceStateError):
        chunk_historical_window(window, maximum_span=span)


def test_history_window_rejects_non_millisecond_lookback() -> None:
    with pytest.raises(HistoricalMarketEvidenceStateError):
        build_historical_window((T0,), lookback=timedelta(microseconds=1))


class _CoinTransport:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[tuple[datetime, datetime]] = []

    async def fetch_market_chart_range(
        self,
        provider_symbol: str,
        quote_currency: str,
        *,
        start: datetime,
        end: datetime,
    ) -> bytes:
        assert provider_symbol == "bitcoin"
        assert quote_currency == "eur"
        self.calls.append((start, end))
        return self.body


@pytest.mark.asyncio
async def test_coingecko_provider_keeps_history_path_separate_and_selection_blocks_future() -> None:
    transport = _CoinTransport(
        b'{"prices":[[1722859200000,100.123456789]],"market_caps":[],"total_volumes":[]}'
    )
    requirement = _price_requirement(
        (datetime(2024, 8, 5, 12),), source=PriceSource.coingecko, symbol="bitcoin"
    )

    result = await CoinGeckoHistoricalPriceProvider(transport).fetch_range(requirement)

    assert result[0].price == Decimal("100.123456789")
    assert len(transport.calls) == 1
    assert (
        CoinGeckoHistoricalPriceProvider.capability.native_granularity.value
        == "provider_determined"
    )
    assert CoinGeckoHistoricalPriceProvider.capability.supports_subdaily_backfill
    with pytest.raises(HistoricalMarketEvidenceStateError):
        select_historical_prices(
            _price_requirement(
                (datetime(2024, 8, 5, 11),), source=PriceSource.coingecko, symbol="bitcoin"
            ),
            result,
            policy=DEFAULT_MARKET_EVIDENCE_POLICY,
        )


class _ChunkCoinTransport:
    def __init__(self, bodies: list[bytes]) -> None:
        self._bodies = bodies

    async def fetch_market_chart_range(
        self,
        provider_symbol: str,
        quote_currency: str,
        *,
        start: datetime,
        end: datetime,
    ) -> bytes:
        assert provider_symbol == "bitcoin"
        assert quote_currency == "eur"
        return self._bodies.pop(0)


@pytest.mark.asyncio
async def test_coingecko_reconciles_exact_chunk_boundary_duplicate_but_rejects_conflict() -> None:
    point = b'{"prices":[[1722859200000,100]],"market_caps":[],"total_volumes":[]}'
    requirement = _price_requirement((T0,), source=PriceSource.coingecko, symbol="bitcoin")

    result = await CoinGeckoHistoricalPriceProvider(
        _ChunkCoinTransport([point, point, point, point]), maximum_chunk_span=timedelta(days=1)
    ).fetch_range(requirement)

    assert len(result) == 1
    with pytest.raises(HistoricalMarketEvidenceStateError):
        await CoinGeckoHistoricalPriceProvider(
            _ChunkCoinTransport(
                [
                    point,
                    b'{"prices":[[1722859200000,101]],"market_caps":[],"total_volumes":[]}',
                    point,
                    point,
                ]
            ),
            maximum_chunk_span=timedelta(days=1),
        ).fetch_range(requirement)


def test_local_free_factory_rejects_production_even_if_settings_were_mutated() -> None:
    settings = Settings(environment="test", market_evidence_source_mode="local_free")
    settings.environment = "production"

    with pytest.raises(HistoricalMarketEvidenceStateError):
        create_local_free_historical_yahoo_providers(settings)


def test_local_free_factory_exposes_listed_crypto_and_direct_fx_capabilities() -> None:
    settings = Settings(environment="test", market_evidence_source_mode="local_free")
    yahoo = _YahooTransport(b"unused")

    price, crypto, fx = create_local_free_historical_providers(
        settings,
        yahoo_transport=yahoo,
    )

    assert price.source is PriceSource.yahoo_finance
    assert crypto.source is PriceSource.coingecko
    assert fx.source is ExchangeRateSource.yahoo_finance
    assert HistoricalTimeSeriesInterval.provider_determined in price.capability.supported_intervals
    assert HistoricalTimeSeriesInterval.provider_determined in fx.capability.supported_intervals
    assert price.capability.ranges[0].maximum_age == timedelta(days=50)
    assert price.capability.ranges[0].maximum_request_span == timedelta(days=7)
    assert price.capability.ranges[0].native_observation_interval == timedelta(minutes=30)
    assert fx.capability.ranges[0].maximum_age == timedelta(days=50)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "credentials,expected_base_url,expected_header",
    [
        ({}, "https://public.test/api/v3/coins", None),
        (
            {"coingecko_demo_api_key": "demo-secret"},
            "https://public.test/api/v3/coins",
            ("x-cg-demo-api-key", "demo-secret"),
        ),
        (
            {"coingecko_pro_api_key": "pro-secret"},
            "https://pro-api.coingecko.com/api/v3/coins",
            ("x-cg-pro-api-key", "pro-secret"),
        ),
    ],
)
async def test_history_factory_selects_public_demo_or_pro_transport_without_fallback(
    credentials: dict[str, object],
    expected_base_url: str,
    expected_header: tuple[str, str] | None,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b'{"prices":[[1722859200000,100]],"market_caps":[],"total_volumes":[]}',
        )

    settings = Settings(
        environment="test",
        market_evidence_source_mode="canonical",
        twelve_data_api_key="test-key",
        coingecko_history_base_url="https://public.test/api/v3/coins",
        **cast(Any, credentials),
    )
    _, crypto, _ = create_canonical_historical_providers(
        settings,
        twelve_data_transport=cast(TwelveDataHistoricalTimeSeriesTransport, object()),
        http_transport=httpx.MockTransport(handler),
    )

    await crypto.fetch_range(
        _price_requirement((T0,), source=PriceSource.coingecko, symbol="bitcoin")
    )

    assert str(seen[0].url).startswith(f"{expected_base_url}/bitcoin/market_chart/range?")
    if expected_header is None:
        assert "x-cg-demo-api-key" not in seen[0].headers
        assert "x-cg-pro-api-key" not in seen[0].headers
    else:
        header_name, secret = expected_header
        assert seen[0].headers[header_name] == secret
        other_header = (
            "x-cg-pro-api-key" if header_name == "x-cg-demo-api-key" else "x-cg-demo-api-key"
        )
        assert other_header not in seen[0].headers
        assert secret not in str(seen[0].url)


@pytest.mark.asyncio
async def test_yahoo_provider_determined_uses_completed_30m_listed_and_direct_fx_bars() -> None:
    now = datetime(2026, 8, 20, 12)
    through = now - timedelta(minutes=30)
    price_transport = _YahooTransport(
        _yahoo_body(
            symbol="VUAA.MI",
            currency="EUR",
            points=((through - timedelta(minutes=30), "101.25"),),
            data_granularity="30m",
        )
    )
    fx_transport = _WindowedYahooTransport(
        symbol="EURCZK=X",
        currency="CZK",
        points=(
            (through - timedelta(days=7), "24.80"),
            (through - timedelta(minutes=30), "24.91"),
        ),
    )
    price_requirement = replace(
        _price_requirement((through,)),
        interval=HistoricalTimeSeriesInterval.provider_determined,
    )
    fx_requirement = replace(
        _fx_requirement((through,)),
        interval=HistoricalTimeSeriesInterval.provider_determined,
    )

    prices = await YahooFinanceHistoricalPriceProvider(
        price_transport, clock=lambda: now
    ).fetch_range(price_requirement)
    rates = await YahooFinanceHistoricalExchangeRateProvider(
        fx_transport, clock=lambda: now
    ).fetch_range(fx_requirement)

    assert prices[0].observed_at == through
    assert rates[-1].effective_at == through
    assert all(call[3] == "30m" for call in (*price_transport.calls, *fx_transport.calls))
    assert {call[0] for call in fx_transport.calls} == {"EURCZK=X"}


@pytest.mark.asyncio
async def test_yahoo_chunk_boundary_has_one_owner_when_live_close_is_revised() -> None:
    now = datetime(2026, 8, 20, 12)
    through = now - timedelta(minutes=30)
    old_raw = through - timedelta(days=7)
    owned_raw = through - timedelta(minutes=30)
    transport = _SequenceYahooTransport(
        [
            _yahoo_body(
                symbol="EURCZK=X",
                currency="CZK",
                points=((old_raw, "24.80"), (owned_raw, "24.81")),
                data_granularity="30m",
            ),
            _yahoo_body(
                symbol="EURCZK=X",
                currency="CZK",
                points=((owned_raw, "24.91"),),
                data_granularity="30m",
            ),
        ]
    )
    requirement = replace(
        _fx_requirement((through,)),
        interval=HistoricalTimeSeriesInterval.provider_determined,
    )

    result = await YahooFinanceHistoricalExchangeRateProvider(
        transport, clock=lambda: now
    ).fetch_range(requirement)

    assert transport.calls == 2
    assert result[-1].effective_at == through
    assert result[-1].rate == Decimal("24.91")


@pytest.mark.asyncio
async def test_yahoo_subdaily_rejects_wrong_granularity_and_historical_off_phase() -> None:
    now = datetime(2026, 8, 20, 12)
    through = now - timedelta(hours=1)
    requirement = replace(
        _price_requirement((through,)),
        interval=HistoricalTimeSeriesInterval.provider_determined,
    )
    wrong_meta = _YahooTransport(
        _yahoo_body(
            symbol="VUAA.MI",
            currency="EUR",
            points=((through - timedelta(minutes=30), "100"),),
            data_granularity="1d",
        )
    )
    off_phase = _YahooTransport(
        _yahoo_body(
            symbol="VUAA.MI",
            currency="EUR",
            points=(
                (through - timedelta(minutes=30), "100"),
                (through - timedelta(minutes=44), "101"),
            ),
            data_granularity="30m",
        )
    )

    with pytest.raises(HistoricalMarketEvidenceStateError):
        await YahooFinanceHistoricalPriceProvider(wrong_meta, clock=lambda: now).fetch_range(
            requirement
        )
    with pytest.raises(HistoricalMarketEvidenceStateError):
        await YahooFinanceHistoricalPriceProvider(off_phase, clock=lambda: now).fetch_range(
            requirement
        )

    too_old = replace(requirement, requested_at=(now - timedelta(days=56),))
    never_called = _YahooTransport(b"unused")
    with pytest.raises(HistoricalMarketEvidenceStateError):
        await YahooFinanceHistoricalPriceProvider(never_called, clock=lambda: now).fetch_range(
            too_old
        )
    assert never_called.calls == []


@pytest.mark.asyncio
async def test_yahoo_subdaily_ignores_only_incomplete_live_tail_and_bounds_calls() -> None:
    now = datetime(2026, 8, 20, 12, 17)
    through = now.replace(minute=0) - timedelta(minutes=30)
    transport = _YahooTransport(
        _yahoo_body(
            symbol="VUAA.MI",
            currency="EUR",
            points=(
                (through - timedelta(minutes=30), "100"),
                (now - timedelta(minutes=2), "999"),
            ),
            data_granularity="30m",
        )
    )
    requirement = replace(
        _price_requirement((through,)),
        interval=HistoricalTimeSeriesInterval.provider_determined,
    )

    result = await YahooFinanceHistoricalPriceProvider(transport, clock=lambda: now).fetch_range(
        requirement
    )

    assert [item.price for item in result] == [Decimal("100.00")]
    assert len(transport.calls) == 1

    first = through - timedelta(days=14)
    earliest = first - DEFAULT_MARKET_EVIDENCE_POLICY.maximum_price_age - timedelta(minutes=30)
    chunk_points: list[tuple[datetime, str]] = []
    cursor = earliest.replace(minute=0)
    while cursor <= through:
        chunk_points.append((cursor, "100"))
        cursor += timedelta(hours=6)
    bounded = _WindowedYahooTransport(symbol="VUAA.MI", currency="EUR", points=tuple(chunk_points))
    await YahooFinanceHistoricalPriceProvider(bounded, clock=lambda: now).fetch_range(
        replace(requirement, requested_at=(first, through))
    )
    assert len(bounded.calls) == 3
    assert all(call[2] - call[1] <= timedelta(days=7) for call in bounded.calls)


@pytest.mark.asyncio
async def test_yahoo_subdaily_ignores_unrequested_regular_session_boundary_bar() -> None:
    now = datetime(2026, 8, 20, 12)
    through = now - timedelta(hours=1)
    requirement = replace(
        _price_requirement((through,)),
        interval=HistoricalTimeSeriesInterval.provider_determined,
    )
    window_start = through - DEFAULT_MARKET_EVIDENCE_POLICY.maximum_price_age
    transport = _YahooTransport(
        _yahoo_body(
            symbol="VUAA.MI",
            currency="EUR",
            points=(
                (window_start - timedelta(hours=6), "99"),
                (through - timedelta(minutes=30), "100"),
            ),
            data_granularity="30m",
        )
    )

    result = await YahooFinanceHistoricalPriceProvider(transport, clock=lambda: now).fetch_range(
        requirement
    )

    assert [item.price for item in result] == [Decimal("100.00")]


def _coin_body(points: tuple[tuple[datetime, str], ...]) -> bytes:
    return json.dumps(
        {
            "prices": [
                [int(timestamp.replace(tzinfo=UTC).timestamp() * 1000), float(value)]
                for timestamp, value in points
            ],
            "market_caps": [],
            "total_volumes": [],
        },
        separators=(",", ":"),
    ).encode()


def _series(start: datetime, end: datetime, step: timedelta) -> tuple[tuple[datetime, str], ...]:
    points: list[tuple[datetime, str]] = []
    cursor = start
    while cursor <= end:
        points.append((cursor, "100.123456789"))
        cursor += step
    return tuple(points)


@pytest.mark.asyncio
async def test_coingecko_provider_determined_uses_5m_for_rolling_day_and_one_call() -> None:
    now = datetime(2026, 8, 20, 12)
    requested = (now - timedelta(hours=23, minutes=30), now - timedelta(minutes=30))
    query_start = requested[0] - timedelta(minutes=5)
    transport = _CoinTransport(_coin_body(_series(query_start, now, timedelta(minutes=5))))
    requirement = replace(
        _price_requirement(requested, source=PriceSource.coingecko, symbol="bitcoin"),
        listing_currency="EUR",
        interval=HistoricalTimeSeriesInterval.provider_determined,
    )

    result = await CoinGeckoHistoricalPriceProvider(transport, clock=lambda: now).fetch_range(
        requirement
    )

    assert len(transport.calls) == 1
    assert transport.calls == [(query_start, now)]
    assert result[0].provider is PriceSource.coingecko
    assert all(item.observed_at <= now for item in result)


@pytest.mark.asyncio
async def test_coingecko_provider_determined_uses_truthful_hourly_history() -> None:
    now = datetime(2026, 8, 20, 12)
    requested = (now - timedelta(days=8), now - timedelta(days=2))
    query_start = requested[0] - timedelta(hours=1)
    query_end = requested[-1] + timedelta(milliseconds=1)
    transport = _CoinTransport(_coin_body(_series(query_start, requested[-1], timedelta(hours=1))))
    requirement = replace(
        _price_requirement(requested, source=PriceSource.coingecko, symbol="bitcoin"),
        interval=HistoricalTimeSeriesInterval.provider_determined,
    )

    result = await CoinGeckoHistoricalPriceProvider(transport, clock=lambda: now).fetch_range(
        requirement
    )

    assert transport.calls == [(query_start, query_end)]
    assert len(result) > 100
    assert all(
        right.observed_at - left.observed_at == timedelta(hours=1)
        for left, right in pairwise(result)
    )


@pytest.mark.asyncio
async def test_coingecko_subdaily_rejects_daily_gap_future_and_overlong_recent_window() -> None:
    now = datetime(2026, 8, 20, 12)
    requested = (now - timedelta(hours=3), now - timedelta(hours=1))
    requirement = replace(
        _price_requirement(requested, source=PriceSource.coingecko, symbol="bitcoin"),
        interval=HistoricalTimeSeriesInterval.provider_determined,
    )
    daily = _CoinTransport(
        _coin_body(
            (
                (requested[0] - timedelta(minutes=5), "100"),
                (requested[0] + timedelta(days=1) - timedelta(minutes=5), "101"),
            )
        )
    )
    future = _CoinTransport(
        _coin_body(
            (
                (requested[0] - timedelta(minutes=5), "100"),
                (now + timedelta(minutes=5), "101"),
            )
        )
    )

    with pytest.raises(HistoricalMarketEvidenceStateError):
        await CoinGeckoHistoricalPriceProvider(daily, clock=lambda: now).fetch_range(requirement)
    with pytest.raises(HistoricalMarketEvidenceStateError):
        await CoinGeckoHistoricalPriceProvider(future, clock=lambda: now).fetch_range(requirement)

    too_long = replace(requirement, requested_at=(now - timedelta(hours=24), now))
    empty_transport = _CoinTransport(_coin_body(((now, "100"),)))
    with pytest.raises(HistoricalMarketEvidenceStateError):
        await CoinGeckoHistoricalPriceProvider(empty_transport, clock=lambda: now).fetch_range(
            too_long
        )
    assert len(empty_transport.calls) <= 1

    too_old = replace(requirement, requested_at=(now - timedelta(days=90),))
    old_transport = _CoinTransport(_coin_body(((now - timedelta(days=90), "100"),)))
    with pytest.raises(HistoricalMarketEvidenceStateError):
        await CoinGeckoHistoricalPriceProvider(old_transport, clock=lambda: now).fetch_range(
            too_old
        )
    assert old_transport.calls == []
