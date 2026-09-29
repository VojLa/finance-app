"""CoinGecko historical crypto range adapter.

The adapter is deliberately separate from the current ``/simple/price`` path.
It receives an already persisted CoinGecko asset ID and never discovers a
ticker or falls back to another provider.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from typing import Protocol
from urllib.parse import quote, urlsplit

import httpx

from app.db.models.enums import PriceSource
from app.modules.market_data.history.models import (
    HistoricalMarketEvidenceStateError,
    HistoricalPriceProviderCapability,
    HistoricalPriceRangeRequirement,
    HistoricalProviderGranularity,
    HistoricalProviderRangeCapability,
    HistoricalTimeSeriesInterval,
    validate_historical_price_range_requirement,
)
from app.modules.market_data.history.ranges import build_historical_window, chunk_historical_window
from app.modules.market_data.models import PriceRequirement
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
    validate_market_evidence_policy,
)
from app.modules.prices.models import PriceObservation
from app.modules.prices.providers.coingecko_identity import (
    CoinGeckoAssetIdentityError,
    parse_coingecko_asset_identity,
)
from app.modules.prices.validation import (
    PriceObservationValidationError,
    validate_price_observation,
)

_MAX_DEPTH = 5
_MAX_ITEMS = 32_768
_MAX_CHUNK_SPAN = timedelta(days=365)
_MAX_TIMEOUT_SECONDS = 120
_MAX_RESPONSE_BYTES = 10_485_760
_MAX_USER_AGENT_LENGTH = 256
_MAX_API_KEY_LENGTH = 512
_FIVE_MINUTES = timedelta(minutes=5)
_ONE_HOUR = timedelta(hours=1)
_RECENT_AUTO_WINDOW = timedelta(hours=23, minutes=55)
_HOURLY_AUTO_WINDOW = timedelta(days=90)


def _fail() -> HistoricalMarketEvidenceStateError:
    return HistoricalMarketEvidenceStateError()


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _canonical_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise _fail()
    return value


def _validate_subdaily_points(
    points: tuple[tuple[datetime, Decimal], ...],
    *,
    requested_at: tuple[datetime, ...],
    interval: timedelta,
    start: datetime,
    end: datetime,
    now: datetime,
) -> None:
    if not points or any(
        not start <= timestamp <= end or timestamp > now for timestamp, _ in points
    ):
        raise _fail()
    tolerance = interval / 5
    for previous, current in pairwise(points):
        gap = current[0] - previous[0]
        if not interval - tolerance <= gap <= interval + tolerance:
            raise _fail()
    timestamps = tuple(timestamp for timestamp, _ in points)
    for through in requested_at:
        eligible = tuple(timestamp for timestamp in timestamps if timestamp <= through)
        if not eligible or through - eligible[-1] > interval + tolerance:
            raise _fail()


def _validate_transport_configuration(
    *,
    base_url: object,
    timeout_seconds: object,
    max_response_bytes: object,
    user_agent: object,
    demo_api_key: object,
    pro_api_key: object,
) -> tuple[str, float, int, str, str | None, str | None]:
    if not isinstance(base_url, str):
        raise _fail()
    parsed_url = urlsplit(base_url)
    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or bool(parsed_url.query)
        or bool(parsed_url.fragment)
        or base_url.endswith("/")
        or any(character.isspace() for character in base_url)
    ):
        raise _fail()
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0 < timeout_seconds <= _MAX_TIMEOUT_SECONDS
    ):
        raise _fail()
    if (
        isinstance(max_response_bytes, bool)
        or not isinstance(max_response_bytes, int)
        or not 0 < max_response_bytes <= _MAX_RESPONSE_BYTES
    ):
        raise _fail()
    if (
        not isinstance(user_agent, str)
        or not user_agent
        or user_agent != user_agent.strip()
        or "\r" in user_agent
        or "\n" in user_agent
        or len(user_agent) > _MAX_USER_AGENT_LENGTH
    ):
        raise _fail()
    if demo_api_key is not None and (
        not isinstance(demo_api_key, str)
        or not demo_api_key
        or demo_api_key != demo_api_key.strip()
        or "\r" in demo_api_key
        or "\n" in demo_api_key
        or len(demo_api_key) > _MAX_API_KEY_LENGTH
    ):
        raise _fail()
    if pro_api_key is not None and (
        not isinstance(pro_api_key, str)
        or not pro_api_key
        or pro_api_key != pro_api_key.strip()
        or "\r" in pro_api_key
        or "\n" in pro_api_key
        or len(pro_api_key) > _MAX_API_KEY_LENGTH
    ):
        raise _fail()
    if demo_api_key is not None and pro_api_key is not None:
        raise _fail()
    return (
        base_url,
        float(timeout_seconds),
        max_response_bytes,
        user_agent,
        demo_api_key,
        pro_api_key,
    )


class CoinGeckoHistoricalPriceTransport(Protocol):
    async def fetch_market_chart_range(
        self,
        provider_symbol: str,
        quote_currency: str,
        *,
        start: datetime,
        end: datetime,
    ) -> bytes: ...


class HttpxCoinGeckoHistoricalPriceTransport:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float,
        max_response_bytes: int,
        user_agent: str,
        demo_api_key: str | None = None,
        pro_api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    ) -> None:
        (
            self._base_url,
            self._timeout_seconds,
            self._max_response_bytes,
            self._user_agent,
            self._demo_api_key,
            self._pro_api_key,
        ) = _validate_transport_configuration(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_response_bytes=max_response_bytes,
            user_agent=user_agent,
            demo_api_key=demo_api_key,
            pro_api_key=pro_api_key,
        )
        self._transport = transport
        self._client_factory = client_factory

    async def fetch_market_chart_range(
        self,
        provider_symbol: str,
        quote_currency: str,
        *,
        start: datetime,
        end: datetime,
    ) -> bytes:
        if (
            not isinstance(provider_symbol, str)
            or not provider_symbol
            or not isinstance(quote_currency, str)
            or not quote_currency
            or not isinstance(start, datetime)
            or not isinstance(end, datetime)
            or start.tzinfo is not None
            or end.tzinfo is not None
            or start >= end
        ):
            raise _fail()
        try:
            from_epoch = int(start.replace(tzinfo=UTC).timestamp())
            to_epoch = int(end.replace(tzinfo=UTC).timestamp())
        except (OverflowError, OSError, ValueError) as exc:
            raise _fail() from exc
        headers = {"Accept": "application/json", "User-Agent": self._user_agent}
        if self._demo_api_key is not None:
            headers["x-cg-demo-api-key"] = self._demo_api_key
        if self._pro_api_key is not None:
            headers["x-cg-pro-api-key"] = self._pro_api_key
        try:
            async with self._client_factory(
                timeout=httpx.Timeout(self._timeout_seconds),
                follow_redirects=False,
                headers=headers,
                transport=self._transport,
            ) as client:
                async with client.stream(
                    "GET",
                    f"{self._base_url}/{quote(provider_symbol, safe='')}/market_chart/range",
                    params={
                        "vs_currency": quote_currency,
                        "from": str(from_epoch),
                        "to": str(to_epoch),
                    },
                ) as response:
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


def _reject_constant(_: str) -> None:
    raise _fail()


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len(pairs) > _MAX_ITEMS:
        raise _fail()
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _fail()
        result[key] = value
    return result


def _validate_shape(value: object, *, depth: int = 0) -> int:
    if depth > _MAX_DEPTH:
        raise _fail()
    if isinstance(value, dict):
        total = len(value)
        for key, item in value.items():
            if not isinstance(key, str):
                raise _fail()
            total += _validate_shape(item, depth=depth + 1)
    elif isinstance(value, list):
        total = len(value)
        for item in value:
            total += _validate_shape(item, depth=depth + 1)
    else:
        total = 1
    if total > _MAX_ITEMS:
        raise _fail()
    return total


def _timestamp_milliseconds(value: object) -> datetime:
    if (
        isinstance(value, bool)
        or not isinstance(value, Decimal)
        or not value.is_finite()
        or value.as_tuple().exponent != 0
        or value < 0
    ):
        raise _fail()
    try:
        milliseconds = int(value)
        return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=milliseconds)).replace(
            tzinfo=None
        )
    except (OverflowError, OSError, ValueError) as exc:
        raise _fail() from exc


def parse_coingecko_market_chart_range(body: bytes) -> tuple[tuple[datetime, Decimal], ...]:
    """Parse only the exact timestamp/close pairs needed for valuation."""

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
    except HistoricalMarketEvidenceStateError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
        raise _fail() from exc
    _validate_shape(document)
    if not isinstance(document, dict) or set(document) != {
        "prices",
        "market_caps",
        "total_volumes",
    }:
        raise _fail()
    prices = document["prices"]
    market_caps = document["market_caps"]
    total_volumes = document["total_volumes"]
    if (
        not isinstance(prices, list)
        or not prices
        or not isinstance(market_caps, list)
        or not isinstance(total_volumes, list)
    ):
        raise _fail()
    points: list[tuple[datetime, Decimal]] = []
    seen: set[datetime] = set()
    for row in prices:
        if not isinstance(row, list) or len(row) != 2:
            raise _fail()
        timestamp = _timestamp_milliseconds(row[0])
        price = row[1]
        if (
            not isinstance(price, Decimal)
            or not price.is_finite()
            or price <= 0
            or timestamp in seen
        ):
            raise _fail()
        seen.add(timestamp)
        points.append((timestamp, price))
    if points != sorted(points, key=lambda item: item[0]):
        raise _fail()
    return tuple(points)


class CoinGeckoHistoricalPriceProvider:
    source = PriceSource.coingecko
    capability = HistoricalPriceProviderCapability(
        source=source,
        native_granularity=HistoricalProviderGranularity.provider_determined,
        supports_subdaily_backfill=True,
        supported_intervals=(
            HistoricalTimeSeriesInterval.daily,
            HistoricalTimeSeriesInterval.provider_determined,
        ),
        ranges=(
            HistoricalProviderRangeCapability(
                requested_interval=HistoricalTimeSeriesInterval.provider_determined,
                native_observation_interval=_FIVE_MINUTES,
                maximum_request_span=_RECENT_AUTO_WINDOW,
                maximum_age=_RECENT_AUTO_WINDOW,
                requires_current_end=True,
            ),
            HistoricalProviderRangeCapability(
                requested_interval=HistoricalTimeSeriesInterval.provider_determined,
                native_observation_interval=_ONE_HOUR,
                maximum_request_span=_HOURLY_AUTO_WINDOW,
                maximum_age=_HOURLY_AUTO_WINDOW,
            ),
        ),
    )

    def __init__(
        self,
        transport: CoinGeckoHistoricalPriceTransport,
        *,
        policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
        maximum_chunk_span: timedelta = _MAX_CHUNK_SPAN,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._transport = transport
        self._policy = validate_market_evidence_policy(policy)
        if not isinstance(maximum_chunk_span, timedelta) or maximum_chunk_span <= timedelta(0):
            raise _fail()
        self._maximum_chunk_span = maximum_chunk_span
        self._clock = clock

    async def fetch_range(
        self,
        requirement: HistoricalPriceRangeRequirement,
    ) -> tuple[PriceObservation, ...]:
        canonical = validate_historical_price_range_requirement(requirement)
        if (
            canonical.provider is not self.source
            or canonical.interval not in self.capability.supported_intervals
        ):
            raise _fail()
        try:
            provider_identity = parse_coingecko_asset_identity(canonical.provider_symbol)
        except CoinGeckoAssetIdentityError as exc:
            raise _fail() from exc
        now = _canonical_now(self._clock)
        subdaily_batches: list[tuple[tuple[datetime, ...], timedelta, datetime, datetime]] = []
        if canonical.interval is HistoricalTimeSeriesInterval.provider_determined:
            if canonical.requested_at[-1] > now:
                raise _fail()
            recent_cutoff = now - timedelta(hours=23, minutes=30)
            hourly_cutoff = now - timedelta(days=89)
            older = tuple(item for item in canonical.requested_at if item < hourly_cutoff)
            hourly = tuple(
                item for item in canonical.requested_at if hourly_cutoff <= item < recent_cutoff
            )
            recent = tuple(item for item in canonical.requested_at if item >= recent_cutoff)
            if older:
                raise _fail()
            if hourly:
                hourly_start = hourly[0] - _ONE_HOUR
                hourly_end = hourly[-1] + timedelta(milliseconds=1)
                if not hourly_end - hourly_start <= _HOURLY_AUTO_WINDOW:
                    raise _fail()
                subdaily_batches.append((hourly, _ONE_HOUR, hourly_start, hourly_end))
            if recent:
                recent_start = recent[0] - _FIVE_MINUTES
                if not now - recent_start < timedelta(days=1):
                    raise _fail()
                subdaily_batches.append((recent, _FIVE_MINUTES, recent_start, now))
        window = build_historical_window(
            canonical.requested_at,
            lookback=self._policy.maximum_price_age,
        )
        observations: dict[datetime, PriceObservation] = {}
        chunks = (
            tuple((times, cadence, start, end) for times, cadence, start, end in subdaily_batches)
            if subdaily_batches
            else tuple(
                (canonical.requested_at, None, chunk.start, chunk.end)
                for chunk in chunk_historical_window(window, maximum_span=self._maximum_chunk_span)
            )
        )
        for requested, cadence, start, end in chunks:
            body = await self._transport.fetch_market_chart_range(
                provider_identity.coin_id,
                canonical.listing_currency.lower(),
                start=start,
                end=end,
            )
            points = parse_coingecko_market_chart_range(body)
            if cadence is not None:
                _validate_subdaily_points(
                    points,
                    requested_at=requested,
                    interval=cadence,
                    start=start,
                    end=end,
                    now=now,
                )
            for observed_at, price in points:
                if cadence is None and (observed_at < window.start or observed_at >= window.end):
                    raise _fail()
                observation = PriceObservation(
                    asset_id=canonical.asset_id,
                    listing_id=canonical.listing_id,
                    provider=self.source,
                    provider_symbol=provider_identity.coin_id,
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
                            provider_symbol=provider_identity.coin_id,
                            through=observed_at,
                        ),
                        policy=self._policy,
                    )
                except PriceObservationValidationError as exc:
                    raise _fail() from exc
                existing = observations.get(observed_at)
                if existing is not None and existing != observation:
                    raise _fail()
                observations[observed_at] = observation
        return tuple(observations[timestamp] for timestamp in sorted(observations))


__all__ = [
    "CoinGeckoHistoricalPriceProvider",
    "CoinGeckoHistoricalPriceTransport",
    "HttpxCoinGeckoHistoricalPriceTransport",
    "parse_coingecko_market_chart_range",
]
