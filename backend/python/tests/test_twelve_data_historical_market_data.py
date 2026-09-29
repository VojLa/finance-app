from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Any

import httpx
import pytest

from app.config.settings import Settings
from app.db.models.enums import ExchangeRateSource, PriceSource
from app.modules.market_data.history.factory import (
    create_canonical_historical_twelve_data_providers,
)
from app.modules.market_data.history.models import (
    HistoricalExchangeRateRangeRequirement,
    HistoricalMarketEvidenceStateError,
    HistoricalPriceRangeRequirement,
    HistoricalTimeSeriesInterval,
)
from app.modules.market_data.history.selection import (
    select_historical_exchange_rates,
    select_historical_prices,
)
from app.modules.market_data.history.twelve_data import (
    HttpxTwelveDataHistoricalTimeSeriesTransport,
    TwelveDataHistoricalExchangeRateProvider,
    TwelveDataHistoricalPriceProvider,
    parse_twelve_data_historical_time_series,
)
from app.modules.market_data.policy import DEFAULT_MARKET_EVIDENCE_POLICY

BASE_URL = "https://api.twelvedata.test/time_series"
IDENTITY = '{"symbol":"AAPL","mic_code":"XNAS"}'
T0 = datetime(2024, 8, 5, 12)


def _price_requirement(
    requested_at: tuple[datetime, ...] = (T0,),
) -> HistoricalPriceRangeRequirement:
    return HistoricalPriceRangeRequirement(
        asset_id="asset-a",
        listing_id="listing-a",
        listing_currency="USD",
        provider=PriceSource.twelve_data,
        provider_symbol=IDENTITY,
        requested_at=requested_at,
        interval=HistoricalTimeSeriesInterval.thirty_minutes,
    )


def _fx_requirement(
    requested_at: tuple[datetime, ...] = (datetime(2024, 8, 5, 12),),
) -> HistoricalExchangeRateRangeRequirement:
    return HistoricalExchangeRateRangeRequirement(
        from_currency="EUR",
        to_currency="USD",
        provider=ExchangeRateSource.twelve_data,
        requested_at=requested_at,
        interval=HistoricalTimeSeriesInterval.thirty_minutes,
    )


def _body(
    *,
    symbol: str,
    interval: HistoricalTimeSeriesInterval,
    values: list[dict[str, str]],
    currency: str | None = None,
    mic_code: str | None = None,
    fx: tuple[str, str] | None = None,
) -> bytes:
    meta: dict[str, str] = {"symbol": symbol, "interval": interval.value}
    if currency is not None:
        meta["currency"] = currency
    if mic_code is not None:
        meta["mic_code"] = mic_code
    if fx is not None:
        meta["currency_base"], meta["currency_quote"] = fx
    return json.dumps({"meta": meta, "values": values, "status": "ok"}).encode()


def _price_body(close: str = "100.1234567890", at: str = "2024-08-05 11:30:00") -> bytes:
    return _body(
        symbol="AAPL",
        interval=HistoricalTimeSeriesInterval.thirty_minutes,
        currency="USD",
        mic_code="XNAS",
        values=[{"datetime": at, "close": close}],
    )


def _fx_body(close: str = "1.08123456", at: str = "2024-08-05 11:30:00") -> bytes:
    return _body(
        symbol="EUR/USD",
        interval=HistoricalTimeSeriesInterval.thirty_minutes,
        fx=("EUR", "USD"),
        values=[{"datetime": at, "close": close}],
    )


def _transport(handler: Any, *, max_response_bytes: int = 1_048_576):
    return HttpxTwelveDataHistoricalTimeSeriesTransport(
        base_url=BASE_URL,
        api_key="server-secret",
        timeout_seconds=10,
        max_response_bytes=max_response_bytes,
        user_agent="finance-app/0.1",
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_transport_sends_bounded_exact_price_range_with_header_key_only() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "application/json"}, content=b"{}")

    await _transport(handler).fetch_time_series(
        symbol="AAPL",
        mic_code="XNAS",
        interval=HistoricalTimeSeriesInterval.thirty_minutes,
        start=datetime(2024, 8, 1),
        end=datetime(2024, 8, 2),
    )

    assert requests[0].url.params.multi_items() == [
        ("symbol", "AAPL"),
        ("interval", "30min"),
        ("start_date", "2024-08-01T00:00:00"),
        ("end_date", "2024-08-02T00:00:00"),
        ("outputsize", "5000"),
        ("order", "ASC"),
        ("timezone", "UTC"),
        ("format", "JSON"),
        ("dp", "10"),
        ("prepost", "false"),
        ("mic_code", "XNAS"),
    ]
    assert requests[0].headers["authorization"] == "apikey server-secret"
    assert "server-secret" not in str(requests[0].url)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [302, 429, 500])
async def test_transport_rejects_quota_server_and_oversized_response(status: int) -> None:
    with pytest.raises(HistoricalMarketEvidenceStateError):
        await _transport(
            lambda _: httpx.Response(
                status, headers={"content-type": "application/json"}, content=b"{}"
            )
        ).fetch_time_series(
            symbol="EUR/USD",
            mic_code=None,
            interval=HistoricalTimeSeriesInterval.daily,
            start=datetime(2024, 8, 1),
            end=datetime(2024, 8, 2),
        )
    with pytest.raises(HistoricalMarketEvidenceStateError):
        await _transport(
            lambda _: httpx.Response(
                200, headers={"content-type": "application/json"}, content=b"12345"
            ),
            max_response_bytes=4,
        ).fetch_time_series(
            symbol="EUR/USD",
            mic_code=None,
            interval=HistoricalTimeSeriesInterval.daily,
            start=datetime(2024, 8, 1),
            end=datetime(2024, 8, 2),
        )


@pytest.mark.asyncio
async def test_transport_rejects_redirect_without_forwarding_authorization() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://evil.test/time_series"})

    with pytest.raises(HistoricalMarketEvidenceStateError):
        await _transport(handler).fetch_time_series(
            symbol="AAPL",
            mic_code="XNAS",
            interval=HistoricalTimeSeriesInterval.thirty_minutes,
            start=datetime(2024, 8, 1),
            end=datetime(2024, 8, 2),
        )

    assert len(requests) == 1
    assert requests[0].headers["authorization"] == "apikey server-secret"


def test_parser_enforces_twelve_data_five_thousand_value_limit() -> None:
    values = [
        {
            "datetime": f"2024-01-{(index // 48) + 1:02d} {((index // 2) % 24):02d}:{(index % 2) * 30:02d}:00",
            "close": "1",
        }
        for index in range(5_001)
    ]
    body = _body(
        symbol="AAPL",
        interval=HistoricalTimeSeriesInterval.thirty_minutes,
        currency="USD",
        mic_code="XNAS",
        values=values,
    )

    with pytest.raises(HistoricalMarketEvidenceStateError):
        parse_twelve_data_historical_time_series(
            body,
            expected_symbol="AAPL",
            expected_interval=HistoricalTimeSeriesInterval.thirty_minutes,
            expected_currency="USD",
            expected_mic_code="XNAS",
            expected_fx_pair=None,
        )


def test_parser_strictly_validates_exact_identity_and_bar_close_time() -> None:
    result = parse_twelve_data_historical_time_series(
        _price_body(),
        expected_symbol="AAPL",
        expected_interval=HistoricalTimeSeriesInterval.thirty_minutes,
        expected_currency="USD",
        expected_mic_code="XNAS",
        expected_fx_pair=None,
    )

    assert result == ((datetime(2024, 8, 5, 12), Decimal("100.1234567890")),)
    with pytest.raises(HistoricalMarketEvidenceStateError):
        parse_twelve_data_historical_time_series(
            _price_body(),
            expected_symbol="AAPL",
            expected_interval=HistoricalTimeSeriesInterval.thirty_minutes,
            expected_currency="EUR",
            expected_mic_code="XNAS",
            expected_fx_pair=None,
        )
    with pytest.raises(HistoricalMarketEvidenceStateError):
        parse_twelve_data_historical_time_series(
            _fx_body(),
            expected_symbol="USD/EUR",
            expected_interval=HistoricalTimeSeriesInterval.daily,
            expected_currency=None,
            expected_mic_code=None,
            expected_fx_pair=("USD", "EUR"),
        )


class _FakeTransport:
    def __init__(self, bodies: list[bytes]) -> None:
        self.bodies = bodies
        self.calls: list[tuple[str, HistoricalTimeSeriesInterval, str | None]] = []

    async def fetch_time_series(
        self,
        *,
        symbol: str,
        interval: HistoricalTimeSeriesInterval,
        start: datetime,
        end: datetime,
        mic_code: str | None,
    ) -> bytes:
        assert start < end
        self.calls.append((symbol, interval, mic_code))
        return self.bodies.pop(0)


@pytest.mark.asyncio
async def test_price_provider_preserves_current_quote_separation_and_as_of_selection() -> None:
    transport = _FakeTransport([_price_body()])
    provider = TwelveDataHistoricalPriceProvider(transport)

    observations = await provider.fetch_range(_price_requirement())
    selected = select_historical_prices(
        _price_requirement(), observations, policy=DEFAULT_MARKET_EVIDENCE_POLICY
    )

    assert selected[0].observation.price == Decimal("100.1234567890")
    assert transport.calls == [("AAPL", HistoricalTimeSeriesInterval.thirty_minutes, "XNAS")]
    assert provider.capability.supported_intervals == (HistoricalTimeSeriesInterval.thirty_minutes,)


@pytest.mark.asyncio
async def test_fx_intraday_close_is_available_at_its_utc_bar_close() -> None:
    transport = _FakeTransport([_fx_body()])
    provider = TwelveDataHistoricalExchangeRateProvider(transport)
    requirement = _fx_requirement((T0,))

    observations = await provider.fetch_range(requirement)
    selected = select_historical_exchange_rates(
        requirement, observations, policy=DEFAULT_MARKET_EVIDENCE_POLICY
    )

    assert observations[0].effective_at == T0
    assert selected[0].observation.rate == Decimal("1.08123456")


@pytest.mark.asyncio
async def test_provider_queries_only_bar_opens_that_can_close_by_valuation_time() -> None:
    class WindowTransport:
        def __init__(self) -> None:
            self.bounds: list[tuple[datetime, datetime]] = []

        async def fetch_time_series(
            self,
            *,
            symbol: str,
            interval: HistoricalTimeSeriesInterval,
            start: datetime,
            end: datetime,
            mic_code: str | None,
        ) -> bytes:
            assert (symbol, interval, mic_code) == (
                "AAPL",
                HistoricalTimeSeriesInterval.thirty_minutes,
                "XNAS",
            )
            self.bounds.append((start, end))
            return _price_body(at="2024-08-05 11:30:00")

    transport = WindowTransport()
    observations = await TwelveDataHistoricalPriceProvider(transport).fetch_range(
        _price_requirement((T0,))
    )

    assert observations[0].observed_at == T0
    assert transport.bounds[0][1] == T0 - timedelta(minutes=30) + timedelta(seconds=1)
    assert transport.bounds[0][1] < T0


@pytest.mark.asyncio
async def test_provider_reconciles_exact_overlap_and_rejects_conflict() -> None:
    requested = (datetime(2024, 1, 1, 12), datetime(2024, 5, 1, 12))
    exact = _price_body("100", at="2024-05-01 11:30:00")
    provider = TwelveDataHistoricalPriceProvider(_FakeTransport([exact, exact]))

    result = await provider.fetch_range(_price_requirement(requested))

    assert len(result) == 1
    with pytest.raises(HistoricalMarketEvidenceStateError):
        await TwelveDataHistoricalPriceProvider(
            _FakeTransport([exact, _price_body("101", at="2024-05-01 11:30:00")])
        ).fetch_range(_price_requirement(requested))


class _MultiYearTransport:
    def __init__(self, first: datetime, last: datetime) -> None:
        self.first = first
        self.last = last
        self.calls: list[tuple[datetime, datetime]] = []

    async def fetch_time_series(
        self,
        *,
        symbol: str,
        interval: HistoricalTimeSeriesInterval,
        start: datetime,
        end: datetime,
        mic_code: str | None,
    ) -> bytes:
        assert (symbol, interval, mic_code) == (
            "AAPL",
            HistoricalTimeSeriesInterval.thirty_minutes,
            "XNAS",
        )
        self.calls.append((start, end))
        close_at = (
            self.first
            if len(self.calls) == 1
            else min(self.last, end + timedelta(minutes=30) - timedelta(seconds=1))
        )
        return _price_body(at=(close_at - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"))


@pytest.mark.asyncio
async def test_multiyear_thirty_minute_requests_are_bounded_and_select_sparse_as_of_points() -> (
    None
):
    requested = (datetime(2020, 1, 1, 12), datetime(2025, 1, 1, 12))
    transport = _MultiYearTransport(*requested)
    requirement = _price_requirement(requested)

    observations = await TwelveDataHistoricalPriceProvider(transport).fetch_range(requirement)
    selections = select_historical_prices(
        requirement, observations, policy=DEFAULT_MARKET_EVIDENCE_POLICY
    )

    assert [selection.observation.observed_at for selection in selections] == list(requested)
    assert len(transport.calls) > 1
    assert all(end - start <= timedelta(days=100) for start, end in transport.calls)
    assert all(left[1] == right[0] for left, right in pairwise(transport.calls))


@pytest.mark.asyncio
async def test_provider_rejects_daily_listed_price_and_missing_evidence() -> None:
    provider = TwelveDataHistoricalPriceProvider(_FakeTransport([_price_body()]))
    daily = replace(_price_requirement(), interval=HistoricalTimeSeriesInterval.daily)

    with pytest.raises(HistoricalMarketEvidenceStateError):
        await provider.fetch_range(daily)
    with pytest.raises(HistoricalMarketEvidenceStateError):
        select_historical_prices(
            _price_requirement((T0 + timedelta(days=4),)),
            (),
            policy=DEFAULT_MARKET_EVIDENCE_POLICY,
        )


@pytest.mark.asyncio
async def test_provider_rejects_future_or_out_of_lookback_response_evidence() -> None:
    future = _price_body()
    with pytest.raises(HistoricalMarketEvidenceStateError):
        await TwelveDataHistoricalPriceProvider(_FakeTransport([future])).fetch_range(
            _price_requirement((T0 - timedelta(minutes=30),))
        )
    stale = _price_body()
    with pytest.raises(HistoricalMarketEvidenceStateError):
        await TwelveDataHistoricalPriceProvider(_FakeTransport([stale])).fetch_range(
            _price_requirement((T0 + timedelta(days=4),))
        )


def test_canonical_factory_requires_canonical_policy_and_server_key() -> None:
    transport = _FakeTransport([_price_body()])
    settings = Settings(
        environment="test",
        market_evidence_source_mode="canonical",
        twelve_data_api_key="server-secret",
    )

    price, fx = create_canonical_historical_twelve_data_providers(settings, transport=transport)

    assert isinstance(price, TwelveDataHistoricalPriceProvider)
    assert isinstance(fx, TwelveDataHistoricalExchangeRateProvider)
    with pytest.raises(HistoricalMarketEvidenceStateError):
        create_canonical_historical_twelve_data_providers(
            Settings(environment="test", market_evidence_source_mode="local_free"),
            transport=transport,
        )
