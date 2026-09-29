"""Canonical Twelve Data historical time-series adapters.

Twelve Data documents ``datetime`` as the opening time of a bar.  This module
therefore makes a close usable only at the end of its interval.  It never
relies on provider ordering, inverse pairs, symbol discovery, or a fallback.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from app.db.models.enums import ExchangeRateSource, PriceSource
from app.modules.fx.models import ExchangeRateObservation
from app.modules.fx.validation import (
    ExchangeRateObservationValidationError,
    validate_exchange_rate_observation,
)
from app.modules.market_data.history.models import (
    HistoricalExchangeRateProviderCapability,
    HistoricalExchangeRateRangeRequirement,
    HistoricalMarketEvidenceStateError,
    HistoricalPriceProviderCapability,
    HistoricalPriceRangeRequirement,
    HistoricalProviderGranularity,
    HistoricalTimeSeriesInterval,
    validate_historical_exchange_rate_range_requirement,
    validate_historical_price_range_requirement,
)
from app.modules.market_data.history.ranges import (
    HistoricalTimeRange,
    build_historical_window,
    chunk_historical_window,
)
from app.modules.market_data.models import ExchangeRateRequirement, PriceRequirement
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
    validate_market_evidence_policy,
)
from app.modules.prices.models import PriceObservation
from app.modules.prices.providers.twelve_data_identity import (
    parse_twelve_data_quote_identity,
)
from app.modules.prices.validation import (
    PriceObservationValidationError,
    validate_price_observation,
)

_MAX_RESPONSE_ITEMS = 40_000
_MAX_VALUES = 5_000
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_DATETIME = "%Y-%m-%d %H:%M:%S"
_DATE = "%Y-%m-%d"
# The request timezone is honoured only for intraday series.  Do not add a
# daily interval here until persisted listing identity includes an exchange
# timezone plus an exchange-close calendar; a bare local date is not a UTC
# as-of timestamp (and TD ignores `timezone` for daily bars).
_INTERVAL_SPANS = {
    HistoricalTimeSeriesInterval.thirty_minutes: timedelta(days=100),
    HistoricalTimeSeriesInterval.daily: timedelta(days=4_000),
}
_INTERVAL_DURATIONS = {
    HistoricalTimeSeriesInterval.thirty_minutes: timedelta(minutes=30),
    HistoricalTimeSeriesInterval.daily: timedelta(days=1),
}


def _fail() -> HistoricalMarketEvidenceStateError:
    return HistoricalMarketEvidenceStateError()


class TwelveDataHistoricalTimeSeriesTransport(Protocol):
    async def fetch_time_series(
        self,
        *,
        symbol: str,
        interval: HistoricalTimeSeriesInterval,
        start: datetime,
        end: datetime,
        mic_code: str | None,
    ) -> bytes: ...


class HttpxTwelveDataHistoricalTimeSeriesTransport:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        timeout_seconds: float,
        max_response_bytes: int,
        user_agent: str,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    ) -> None:
        parsed = urlsplit(base_url) if isinstance(base_url, str) else None
        if (
            parsed is None
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or bool(parsed.query)
            or bool(parsed.fragment)
            or not isinstance(api_key, str)
            or not api_key
            or api_key != api_key.strip()
            or not 0 < timeout_seconds <= 120
            or not 0 < max_response_bytes <= 10_485_760
            or not isinstance(user_agent, str)
            or not user_agent
            or user_agent != user_agent.strip()
            or "\r" in user_agent
            or "\n" in user_agent
            or len(user_agent) > 256
        ):
            raise _fail()
        self._base_url = base_url
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_response_bytes = max_response_bytes
        self._user_agent = user_agent
        self._transport = transport
        self._client_factory = client_factory

    async def fetch_time_series(
        self,
        *,
        symbol: str,
        interval: HistoricalTimeSeriesInterval,
        start: datetime,
        end: datetime,
        mic_code: str | None,
    ) -> bytes:
        if (
            not isinstance(symbol, str)
            or not symbol
            or not isinstance(interval, HistoricalTimeSeriesInterval)
            or not isinstance(start, datetime)
            or not isinstance(end, datetime)
            or start.tzinfo is not None
            or end.tzinfo is not None
            or start.microsecond != 0
            or end.microsecond != 0
            or start >= end
            or (mic_code is not None and (not isinstance(mic_code, str) or not mic_code))
        ):
            raise _fail()
        params = {
            "symbol": symbol,
            "interval": interval.value,
            "start_date": start.isoformat(timespec="seconds"),
            "end_date": end.isoformat(timespec="seconds"),
            "outputsize": str(_MAX_VALUES),
            "order": "ASC",
            "timezone": "UTC",
            "format": "JSON",
            "dp": "10",
            "prepost": "false",
        }
        if mic_code is not None:
            params["mic_code"] = mic_code
        try:
            async with self._client_factory(
                timeout=httpx.Timeout(self._timeout_seconds),
                follow_redirects=False,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"apikey {self._api_key}",
                    "User-Agent": self._user_agent,
                },
                transport=self._transport,
            ) as client:
                async with client.stream("GET", self._base_url, params=params) as response:
                    content_type = (
                        response.headers.get("content-type", "").partition(";")[0].strip().lower()
                    )
                    if response.status_code != 200 or content_type != "application/json":
                        raise _fail()
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self._max_response_bytes:
                            raise _fail()
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    if not body:
                        raise _fail()
                    return body
        except HistoricalMarketEvidenceStateError:
            raise
        except httpx.HTTPError as exc:
            raise _fail() from exc


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len(pairs) > _MAX_RESPONSE_ITEMS:
        raise _fail()
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _fail()
        result[key] = value
    return result


def _reject_constant(_: str) -> None:
    raise _fail()


def _decimal(value: object) -> Decimal:
    if not isinstance(value, str) or not _DECIMAL.fullmatch(value):
        raise _fail()
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise _fail() from exc
    if not result.is_finite() or result <= 0:
        raise _fail()
    return result


def _bar_close_timestamp(value: object, interval: HistoricalTimeSeriesInterval) -> datetime:
    if not isinstance(value, str):
        raise _fail()
    try:
        opened = datetime.strptime(
            value, _DATETIME if interval is HistoricalTimeSeriesInterval.thirty_minutes else _DATE
        )
    except ValueError as exc:
        raise _fail() from exc
    if (
        opened.strftime(
            _DATETIME if interval is HistoricalTimeSeriesInterval.thirty_minutes else _DATE
        )
        != value
    ):
        raise _fail()
    return opened + _INTERVAL_DURATIONS[interval]


def parse_twelve_data_historical_time_series(
    body: bytes,
    *,
    expected_symbol: str,
    expected_interval: HistoricalTimeSeriesInterval,
    expected_currency: str | None,
    expected_mic_code: str | None,
    expected_fx_pair: tuple[str, str] | None,
) -> tuple[tuple[datetime, Decimal], ...]:
    if not isinstance(body, bytes) or not body:
        raise _fail()
    try:
        document = json.loads(
            body,
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=_reject_constant,
            object_pairs_hook=_strict_object,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
        raise _fail() from exc
    if (
        not isinstance(document, dict)
        or set(document) != {"meta", "values", "status"}
        or document["status"] != "ok"
        or not isinstance(document["meta"], dict)
        or not isinstance(document["values"], list)
        or not document["values"]
        or len(document["values"]) > _MAX_VALUES
    ):
        raise _fail()
    meta = document["meta"]
    if meta.get("symbol") != expected_symbol or meta.get("interval") != expected_interval.value:
        raise _fail()
    if expected_currency is not None and meta.get("currency") != expected_currency:
        raise _fail()
    if expected_mic_code is not None and meta.get("mic_code") != expected_mic_code:
        raise _fail()
    if expected_fx_pair is not None and (
        meta.get("currency_base") != expected_fx_pair[0]
        or meta.get("currency_quote") != expected_fx_pair[1]
    ):
        raise _fail()
    points: list[tuple[datetime, Decimal]] = []
    seen: set[datetime] = set()
    for row in document["values"]:
        if not isinstance(row, dict) or set(row) - {
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
        }:
            raise _fail()
        timestamp = _bar_close_timestamp(row.get("datetime"), expected_interval)
        if timestamp in seen:
            raise _fail()
        seen.add(timestamp)
        points.append((timestamp, _decimal(row.get("close"))))
    if points != sorted(points, key=lambda item: item[0]):
        raise _fail()
    return tuple(points)


def _history_chunks(
    requested_at: tuple[datetime, ...],
    *,
    lookback: timedelta,
    interval: HistoricalTimeSeriesInterval,
) -> tuple[HistoricalTimeRange, ...]:
    window = build_historical_window(requested_at, lookback=lookback)
    duration = _INTERVAL_DURATIONS[interval]
    open_time_end = window.end - duration
    query_window = HistoricalTimeRange(
        # Twelve Data request bounds and response datetimes are bar-open times,
        # while the common window is expressed in usable bar-close times.
        start=window.start - duration,
        # Keep the one-millisecond exclusive fence after translating to open
        # time, then round outward to the transport's second precision. This
        # includes the last completed bar without requesting the bar that opens
        # at the valuation timestamp.
        end=(
            open_time_end.replace(microsecond=0)
            if open_time_end.microsecond == 0
            else open_time_end.replace(microsecond=0) + timedelta(seconds=1)
        ),
    )
    return chunk_historical_window(query_window, maximum_span=_INTERVAL_SPANS[interval])


def _reconcile[T](target: dict[datetime, T], timestamp: datetime, value: T) -> None:
    existing = target.get(timestamp)
    if existing is not None and existing != value:
        raise _fail()
    target[timestamp] = value


def _validate_observed_window(
    timestamp: datetime,
    *,
    requested_at: tuple[datetime, ...],
    lookback: timedelta,
) -> None:
    """Reject a provider response outside the exact as-of evidence window."""

    if timestamp < requested_at[0] - lookback or timestamp > requested_at[-1]:
        raise _fail()


class TwelveDataHistoricalPriceProvider:
    source = PriceSource.twelve_data
    capability = HistoricalPriceProviderCapability(
        source=source,
        native_granularity=HistoricalProviderGranularity.provider_determined,
        supports_subdaily_backfill=True,
        supported_intervals=(HistoricalTimeSeriesInterval.thirty_minutes,),
    )

    def __init__(
        self,
        transport: TwelveDataHistoricalTimeSeriesTransport,
        *,
        policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
    ) -> None:
        self._transport = transport
        self._policy = validate_market_evidence_policy(policy)

    async def fetch_range(
        self, requirement: HistoricalPriceRangeRequirement
    ) -> tuple[PriceObservation, ...]:
        canonical = validate_historical_price_range_requirement(requirement)
        if (
            canonical.provider is not self.source
            or canonical.interval is not HistoricalTimeSeriesInterval.thirty_minutes
        ):
            raise _fail()
        identity = parse_twelve_data_quote_identity(canonical.provider_symbol)
        observations: dict[datetime, PriceObservation] = {}
        for chunk in _history_chunks(
            canonical.requested_at,
            lookback=self._policy.maximum_price_age,
            interval=canonical.interval,
        ):
            body = await self._transport.fetch_time_series(
                symbol=identity.symbol,
                mic_code=identity.mic_code,
                interval=canonical.interval,
                start=chunk.start,
                end=chunk.end,
            )
            for observed_at, price in parse_twelve_data_historical_time_series(
                body,
                expected_symbol=identity.symbol,
                expected_interval=canonical.interval,
                expected_currency=canonical.listing_currency,
                expected_mic_code=identity.mic_code,
                expected_fx_pair=None,
            ):
                _validate_observed_window(
                    observed_at,
                    requested_at=canonical.requested_at,
                    lookback=self._policy.maximum_price_age,
                )
                observation = PriceObservation(
                    asset_id=canonical.asset_id,
                    listing_id=canonical.listing_id,
                    provider=self.source,
                    provider_symbol=canonical.provider_symbol,
                    price=price,
                    currency=canonical.listing_currency,
                    observed_at=observed_at,
                )
                try:
                    observation = validate_price_observation(
                        observation,
                        requirement=PriceRequirement(
                            account_id="historical",
                            asset_id=canonical.asset_id,
                            listing_id=canonical.listing_id,
                            listing_currency=canonical.listing_currency,
                            provider=self.source,
                            provider_symbol=canonical.provider_symbol,
                            through=observed_at,
                        ),
                        policy=self._policy,
                    )
                except PriceObservationValidationError as exc:
                    raise _fail() from exc
                _reconcile(observations, observed_at, observation)
        return tuple(observations[timestamp] for timestamp in sorted(observations))


class TwelveDataHistoricalExchangeRateProvider:
    source = ExchangeRateSource.twelve_data
    capability = HistoricalExchangeRateProviderCapability(
        source=source,
        supported_intervals=(HistoricalTimeSeriesInterval.thirty_minutes,),
    )

    def __init__(
        self,
        transport: TwelveDataHistoricalTimeSeriesTransport,
        *,
        policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
    ) -> None:
        self._transport = transport
        self._policy = validate_market_evidence_policy(policy)

    async def fetch_range(
        self, requirement: HistoricalExchangeRateRangeRequirement
    ) -> tuple[ExchangeRateObservation, ...]:
        canonical = validate_historical_exchange_rate_range_requirement(requirement)
        if (
            canonical.provider is not self.source
            or canonical.interval not in self.capability.supported_intervals
        ):
            raise _fail()
        symbol = f"{canonical.from_currency}/{canonical.to_currency}"
        observations: dict[datetime, ExchangeRateObservation] = {}
        for chunk in _history_chunks(
            canonical.requested_at,
            lookback=self._policy.maximum_fx_age,
            interval=canonical.interval,
        ):
            body = await self._transport.fetch_time_series(
                symbol=symbol,
                mic_code=None,
                interval=canonical.interval,
                start=chunk.start,
                end=chunk.end,
            )
            for effective_at, rate in parse_twelve_data_historical_time_series(
                body,
                expected_symbol=symbol,
                expected_interval=canonical.interval,
                expected_currency=None,
                expected_mic_code=None,
                expected_fx_pair=(canonical.from_currency, canonical.to_currency),
            ):
                _validate_observed_window(
                    effective_at,
                    requested_at=canonical.requested_at,
                    lookback=self._policy.maximum_fx_age,
                )
                observation = ExchangeRateObservation(
                    from_currency=canonical.from_currency,
                    to_currency=canonical.to_currency,
                    provider=self.source,
                    rate=rate,
                    effective_at=effective_at,
                )
                try:
                    observation = validate_exchange_rate_observation(
                        observation,
                        requirement=ExchangeRateRequirement(
                            from_currency=canonical.from_currency,
                            to_currency=canonical.to_currency,
                            provider=self.source,
                            through=effective_at,
                        ),
                        policy=self._policy,
                    )
                except ExchangeRateObservationValidationError as exc:
                    raise _fail() from exc
                _reconcile(observations, effective_at, observation)
        return tuple(observations[timestamp] for timestamp in sorted(observations))


__all__ = [
    "HttpxTwelveDataHistoricalTimeSeriesTransport",
    "TwelveDataHistoricalExchangeRateProvider",
    "TwelveDataHistoricalPriceProvider",
    "TwelveDataHistoricalTimeSeriesTransport",
    "parse_twelve_data_historical_time_series",
]
