"""Development/test-only Yahoo historical range providers."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

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
    HistoricalProviderRangeCapability,
    HistoricalTimeSeriesInterval,
    validate_historical_exchange_rate_range_requirement,
    validate_historical_price_range_requirement,
)
from app.modules.market_data.history.ranges import (
    HistoricalTimeRange,
    build_historical_window,
    chunk_historical_window,
)
from app.modules.market_data.models import (
    ExchangeRateRequirement,
    MarketEvidenceStateError,
    PriceRequirement,
)
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
    validate_market_evidence_policy,
)
from app.modules.prices.models import PriceObservation
from app.modules.prices.providers.yahoo_finance_identity import (
    YahooFinanceAssetIdentityError,
    parse_yahoo_finance_asset_identity,
)
from app.modules.prices.providers.yahoo_finance_models import (
    YahooFinanceChartPoint,
    YahooFinanceHttpResponse,
)
from app.modules.prices.providers.yahoo_finance_parser import parse_yahoo_finance_chart
from app.modules.prices.providers.yahoo_finance_transport import YahooFinanceChartTransport
from app.modules.prices.validation import (
    PriceObservationValidationError,
    validate_price_observation,
)

_MAX_CHUNK_SPAN = timedelta(days=365)
_YAHOO_SUBDAILY_PROVIDER_RANGE = timedelta(days=59)
_YAHOO_SUBDAILY_CHUNK_SPAN = timedelta(days=7)
_THIRTY_MINUTES = timedelta(minutes=30)


def _fail() -> HistoricalMarketEvidenceStateError:
    return HistoricalMarketEvidenceStateError()


def _fx_symbol(from_currency: str, to_currency: str) -> str:
    if from_currency == "USD":
        return f"{to_currency}=X"
    return f"{from_currency}{to_currency}=X"


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _canonical_now(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise _fail()
    return value


def _subdaily_chunks(
    window: HistoricalTimeRange, *, maximum_span: timedelta
) -> tuple[HistoricalTimeRange, ...]:
    chunks = list(chunk_historical_window(window, maximum_span=maximum_span))
    if len(chunks) > 1 and chunks[-1].end - chunks[-1].start < _THIRTY_MINUTES:
        boundary = chunks[-1].end - _THIRTY_MINUTES
        chunks[-2] = HistoricalTimeRange(chunks[-2].start, boundary)
        chunks[-1] = HistoricalTimeRange(boundary, chunks[-1].end)
    return tuple(chunks)


def _points_in_requested_chunk(
    points: tuple[YahooFinanceChartPoint, ...],
    chunk: HistoricalTimeRange,
    *,
    now: datetime,
) -> tuple[YahooFinanceChartPoint, ...]:
    selected = [point for point in points if chunk.start <= point.observed_at < chunk.end]
    if not selected:
        raise _fail()
    phases = {int(point.observed_at.replace(tzinfo=UTC).timestamp()) % 1_800 for point in selected}
    if len(phases) != 1:
        raise _fail()
    # Yahoo may return the preceding regular-session bar when a request starts
    # outside a listing's trading hours (for example a Friday evening UTC
    # boundary for Milan).  Those observations are outside this chunk and are
    # never used below; rejecting the whole valid chunk would make the history
    # depend on the exchange's session calendar.  Validate the selected bars
    # strictly and discard unrelated boundary observations.  They can include
    # a preceding session close as well as Yahoo's transient latest quote;
    # neither is an observation in this chunk and neither reaches valuation.
    return tuple(selected)


def _subdaily_points(
    points: tuple[YahooFinanceChartPoint, ...],
    *,
    window_start: datetime,
    window_end: datetime,
    now: datetime,
) -> tuple[tuple[datetime, Decimal], ...]:
    """Convert Yahoo 30m bar-start timestamps into completed-bar evidence times."""

    if not points:
        raise _fail()
    ordered = tuple(sorted(points, key=lambda item: item.observed_at))
    phase: int | None = None
    completed: list[tuple[datetime, Decimal]] = []
    newest = ordered[-1].observed_at
    for point in ordered:
        try:
            seconds = int(point.observed_at.replace(tzinfo=UTC).timestamp())
        except (OverflowError, OSError, ValueError) as exc:
            raise _fail() from exc
        point_phase = seconds % 1_800
        if phase is None:
            phase = point_phase
        elif point_phase != phase:
            # Yahoo appends a live, non-bar timestamp. It is safe only as the
            # newest still-open observation; historical phase changes fail closed.
            if point.observed_at == newest and now - point.observed_at < _THIRTY_MINUTES:
                continue
            raise _fail()
        raw_start = window_start - _THIRTY_MINUTES
        raw_end = window_end - _THIRTY_MINUTES
        if point.observed_at < raw_start:
            if raw_start - point.observed_at <= _THIRTY_MINUTES:
                continue
            raise _fail()
        if point.observed_at >= raw_end:
            if point.observed_at - raw_end < _THIRTY_MINUTES:
                continue
            raise _fail()
        effective_at = point.observed_at + _THIRTY_MINUTES
        if effective_at > now:
            if point.observed_at == newest:
                continue
            raise _fail()
        if not window_start <= effective_at < window_end:
            raise _fail()
        completed.append((effective_at, point.close))
    if not completed:
        raise _fail()
    return tuple(completed)


class YahooFinanceHistoricalPriceProvider:
    source = PriceSource.yahoo_finance
    capability = HistoricalPriceProviderCapability(
        source=source,
        native_granularity=HistoricalProviderGranularity.provider_determined,
        supports_subdaily_backfill=True,
        supported_intervals=(
            HistoricalTimeSeriesInterval.thirty_minutes,
            HistoricalTimeSeriesInterval.daily,
            HistoricalTimeSeriesInterval.provider_determined,
        ),
        ranges=(
            HistoricalProviderRangeCapability(
                requested_interval=HistoricalTimeSeriesInterval.thirty_minutes,
                native_observation_interval=_THIRTY_MINUTES,
                maximum_request_span=_YAHOO_SUBDAILY_CHUNK_SPAN,
                maximum_age=timedelta(days=50),
            ),
            HistoricalProviderRangeCapability(
                requested_interval=HistoricalTimeSeriesInterval.provider_determined,
                native_observation_interval=_THIRTY_MINUTES,
                maximum_request_span=_YAHOO_SUBDAILY_CHUNK_SPAN,
                maximum_age=timedelta(days=50),
            ),
        ),
    )

    def __init__(
        self,
        transport: YahooFinanceChartTransport,
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
            symbol = parse_yahoo_finance_asset_identity(canonical.provider_symbol)
        except YahooFinanceAssetIdentityError as exc:
            raise _fail() from exc
        now = _canonical_now(self._clock)
        if canonical.interval in {
            HistoricalTimeSeriesInterval.thirty_minutes,
            HistoricalTimeSeriesInterval.provider_determined,
        }:
            recent_cutoff = now - (
                _YAHOO_SUBDAILY_PROVIDER_RANGE - self._policy.maximum_price_age - _THIRTY_MINUTES
            )
            if canonical.requested_at[0] < recent_cutoff:
                raise _fail()
        window = build_historical_window(
            canonical.requested_at,
            lookback=self._policy.maximum_price_age,
        )
        subdaily = canonical.interval in {
            HistoricalTimeSeriesInterval.thirty_minutes,
            HistoricalTimeSeriesInterval.provider_determined,
        }
        acquisition_window = window
        maximum_chunk_span = self._maximum_chunk_span
        if subdaily:
            acquisition_window = type(window)(
                start=window.start - _THIRTY_MINUTES,
                end=window.end - _THIRTY_MINUTES,
            )
            if (
                acquisition_window.start < now - _YAHOO_SUBDAILY_PROVIDER_RANGE
                or canonical.requested_at[-1] > now
            ):
                raise _fail()
            maximum_chunk_span = min(maximum_chunk_span, _YAHOO_SUBDAILY_CHUNK_SPAN)
        observations: dict[datetime, PriceObservation] = {}
        raw_points: list[YahooFinanceChartPoint] = []
        chunks = (
            _subdaily_chunks(acquisition_window, maximum_span=maximum_chunk_span)
            if subdaily
            else chunk_historical_window(acquisition_window, maximum_span=maximum_chunk_span)
        )
        for chunk in chunks:
            response = await self._transport.fetch_chart(
                symbol,
                start=chunk.start,
                end=chunk.end,
                interval="30m" if subdaily else "1d",
            )
            if (
                not isinstance(response, YahooFinanceHttpResponse)
                or response.status_code != 200
                or response.content_type != "application/json"
            ):
                raise _fail()
            try:
                chart = parse_yahoo_finance_chart(
                    response.body,
                    expected_symbol=symbol,
                    expected_currency=canonical.listing_currency,
                    maximum_price_hint=10,
                    expected_data_granularity="30m" if subdaily else None,
                )
            except MarketEvidenceStateError as exc:
                raise _fail() from exc
            raw_points.extend(
                _points_in_requested_chunk(chart.points, chunk, now=now)
                if subdaily
                else chart.points
            )
        selected_points = (
            _subdaily_points(
                tuple(raw_points),
                window_start=window.start,
                window_end=window.end,
                now=now,
            )
            if subdaily
            else tuple(
                (point.observed_at, point.close)
                for point in raw_points
                if window.start <= point.observed_at < window.end
            )
        )
        for observed_at, close in selected_points:
            if observed_at < window.start or observed_at >= window.end:
                raise _fail()
            observation = PriceObservation(
                asset_id=canonical.asset_id,
                listing_id=canonical.listing_id,
                provider=self.source,
                provider_symbol=symbol,
                price=close,
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
                        provider_symbol=symbol,
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


class YahooFinanceHistoricalExchangeRateProvider:
    source = ExchangeRateSource.yahoo_finance
    capability = HistoricalExchangeRateProviderCapability(
        source=source,
        supported_intervals=(
            HistoricalTimeSeriesInterval.thirty_minutes,
            HistoricalTimeSeriesInterval.daily,
            HistoricalTimeSeriesInterval.provider_determined,
        ),
        ranges=(
            HistoricalProviderRangeCapability(
                requested_interval=HistoricalTimeSeriesInterval.thirty_minutes,
                native_observation_interval=_THIRTY_MINUTES,
                maximum_request_span=_YAHOO_SUBDAILY_CHUNK_SPAN,
                maximum_age=timedelta(days=50),
            ),
            HistoricalProviderRangeCapability(
                requested_interval=HistoricalTimeSeriesInterval.provider_determined,
                native_observation_interval=_THIRTY_MINUTES,
                maximum_request_span=_YAHOO_SUBDAILY_CHUNK_SPAN,
                maximum_age=timedelta(days=50),
            ),
        ),
    )

    def __init__(
        self,
        transport: YahooFinanceChartTransport,
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
        requirement: HistoricalExchangeRateRangeRequirement,
    ) -> tuple[ExchangeRateObservation, ...]:
        canonical = validate_historical_exchange_rate_range_requirement(requirement)
        if (
            canonical.provider is not self.source
            or canonical.interval not in self.capability.supported_intervals
        ):
            raise _fail()
        symbol = _fx_symbol(canonical.from_currency, canonical.to_currency)
        now = _canonical_now(self._clock)
        if canonical.interval in {
            HistoricalTimeSeriesInterval.thirty_minutes,
            HistoricalTimeSeriesInterval.provider_determined,
        }:
            recent_cutoff = now - (
                _YAHOO_SUBDAILY_PROVIDER_RANGE - self._policy.maximum_fx_age - _THIRTY_MINUTES
            )
            if canonical.requested_at[0] < recent_cutoff:
                raise _fail()
        window = build_historical_window(
            canonical.requested_at,
            lookback=self._policy.maximum_fx_age,
        )
        subdaily = canonical.interval in {
            HistoricalTimeSeriesInterval.thirty_minutes,
            HistoricalTimeSeriesInterval.provider_determined,
        }
        acquisition_window = window
        maximum_chunk_span = self._maximum_chunk_span
        if subdaily:
            acquisition_window = type(window)(
                start=window.start - _THIRTY_MINUTES,
                end=window.end - _THIRTY_MINUTES,
            )
            if (
                acquisition_window.start < now - _YAHOO_SUBDAILY_PROVIDER_RANGE
                or canonical.requested_at[-1] > now
            ):
                raise _fail()
            maximum_chunk_span = min(maximum_chunk_span, _YAHOO_SUBDAILY_CHUNK_SPAN)
        observations: dict[datetime, ExchangeRateObservation] = {}
        raw_points: list[YahooFinanceChartPoint] = []
        chunks = (
            _subdaily_chunks(acquisition_window, maximum_span=maximum_chunk_span)
            if subdaily
            else chunk_historical_window(acquisition_window, maximum_span=maximum_chunk_span)
        )
        for chunk in chunks:
            response = await self._transport.fetch_chart(
                symbol,
                start=chunk.start,
                end=chunk.end,
                interval="30m" if subdaily else "1d",
            )
            if (
                not isinstance(response, YahooFinanceHttpResponse)
                or response.status_code != 200
                or response.content_type != "application/json"
            ):
                raise _fail()
            try:
                chart = parse_yahoo_finance_chart(
                    response.body,
                    expected_symbol=symbol,
                    expected_currency=canonical.to_currency,
                    maximum_price_hint=8,
                    expected_data_granularity="30m" if subdaily else None,
                )
            except MarketEvidenceStateError as exc:
                raise _fail() from exc
            raw_points.extend(
                _points_in_requested_chunk(chart.points, chunk, now=now)
                if subdaily
                else chart.points
            )
        selected_points = (
            _subdaily_points(
                tuple(raw_points),
                window_start=window.start,
                window_end=window.end,
                now=now,
            )
            if subdaily
            else tuple(
                (point.observed_at, point.close)
                for point in raw_points
                if window.start <= point.observed_at < window.end
            )
        )
        for effective_at, close in selected_points:
            if effective_at < window.start or effective_at >= window.end:
                raise _fail()
            observation = ExchangeRateObservation(
                from_currency=canonical.from_currency,
                to_currency=canonical.to_currency,
                provider=self.source,
                rate=close,
                effective_at=effective_at,
            )
            try:
                observation = validate_exchange_rate_observation(
                    observation,
                    requirement=ExchangeRateRequirement(
                        from_currency=canonical.from_currency,
                        to_currency=canonical.to_currency,
                        through=effective_at,
                        provider=self.source,
                    ),
                    policy=self._policy,
                )
            except ExchangeRateObservationValidationError as exc:
                raise _fail() from exc
            existing = observations.get(effective_at)
            if existing is not None and existing != observation:
                raise _fail()
            observations[effective_at] = observation
        return tuple(observations[timestamp] for timestamp in sorted(observations))


__all__ = [
    "YahooFinanceHistoricalExchangeRateProvider",
    "YahooFinanceHistoricalPriceProvider",
]
