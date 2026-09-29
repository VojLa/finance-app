"""Bounded, provider-neutral contracts for historical market evidence.

These contracts deliberately do not know about holdings, replay, persistence,
or a background job.  A caller supplies exact persisted provider identities and
the bucket times for which it needs as-of evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.db.models.enums import ExchangeRateSource, PriceSource
from app.modules.fx.models import ExchangeRateObservation
from app.modules.prices.models import PriceObservation

_MAX_REQUESTED_TIMESTAMPS = 4_096


class HistoricalMarketEvidenceStateError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Historical market evidence is unavailable.")


class HistoricalProviderGranularity(StrEnum):
    daily = "daily"
    provider_determined = "provider_determined"


class HistoricalTimeSeriesInterval(StrEnum):
    thirty_minutes = "30min"
    provider_determined = "provider_determined"
    daily = "1day"


@dataclass(frozen=True, slots=True)
class HistoricalProviderRangeCapability:
    """One bounded request shape and the truthful observations it can return."""

    requested_interval: HistoricalTimeSeriesInterval
    native_observation_interval: timedelta
    maximum_request_span: timedelta
    maximum_age: timedelta | None = None
    requires_current_end: bool = False


@dataclass(frozen=True, slots=True)
class HistoricalPriceProviderCapability:
    source: PriceSource
    native_granularity: HistoricalProviderGranularity
    supports_subdaily_backfill: bool
    supported_intervals: tuple[HistoricalTimeSeriesInterval, ...] = ()
    ranges: tuple[HistoricalProviderRangeCapability, ...] = ()


@dataclass(frozen=True, slots=True)
class HistoricalExchangeRateProviderCapability:
    source: ExchangeRateSource
    supported_intervals: tuple[HistoricalTimeSeriesInterval, ...]
    ranges: tuple[HistoricalProviderRangeCapability, ...] = ()


def _fail() -> HistoricalMarketEvidenceStateError:
    return HistoricalMarketEvidenceStateError()


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    currency = _nonblank(value)
    if (
        len(currency) != 3
        or currency != currency.upper()
        or not currency.isascii()
        or not currency.isalpha()
    ):
        raise _fail()
    return currency


def _timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or value.microsecond % 1_000 != 0
    ):
        raise _fail()
    return value


def _requested_timestamps(value: object) -> tuple[datetime, ...]:
    if not isinstance(value, tuple) or not value or len(value) > _MAX_REQUESTED_TIMESTAMPS:
        raise _fail()
    timestamps = tuple(_timestamp(item) for item in value)
    if timestamps != tuple(sorted(timestamps)) or len(set(timestamps)) != len(timestamps):
        raise _fail()
    return timestamps


@dataclass(frozen=True, slots=True)
class HistoricalPriceRangeRequirement:
    asset_id: str
    listing_id: str
    listing_currency: str
    provider: PriceSource
    provider_symbol: str
    requested_at: tuple[datetime, ...]
    interval: HistoricalTimeSeriesInterval = HistoricalTimeSeriesInterval.daily


@dataclass(frozen=True, slots=True)
class HistoricalExchangeRateRangeRequirement:
    from_currency: str
    to_currency: str
    provider: ExchangeRateSource
    requested_at: tuple[datetime, ...]
    interval: HistoricalTimeSeriesInterval = HistoricalTimeSeriesInterval.daily


@dataclass(frozen=True, slots=True)
class HistoricalPriceSelection:
    through: datetime
    observation: PriceObservation


@dataclass(frozen=True, slots=True)
class HistoricalExchangeRateSelection:
    through: datetime
    observation: ExchangeRateObservation


def validate_historical_price_range_requirement(
    value: object,
) -> HistoricalPriceRangeRequirement:
    if (
        not isinstance(value, HistoricalPriceRangeRequirement)
        or not isinstance(value.provider, PriceSource)
        or not isinstance(value.interval, HistoricalTimeSeriesInterval)
    ):
        raise _fail()
    return HistoricalPriceRangeRequirement(
        asset_id=_nonblank(value.asset_id),
        listing_id=_nonblank(value.listing_id),
        listing_currency=_currency(value.listing_currency),
        provider=value.provider,
        provider_symbol=_nonblank(value.provider_symbol),
        requested_at=_requested_timestamps(value.requested_at),
        interval=value.interval,
    )


def validate_historical_exchange_rate_range_requirement(
    value: object,
) -> HistoricalExchangeRateRangeRequirement:
    if (
        not isinstance(value, HistoricalExchangeRateRangeRequirement)
        or not isinstance(value.provider, ExchangeRateSource)
        or not isinstance(value.interval, HistoricalTimeSeriesInterval)
    ):
        raise _fail()
    from_currency = _currency(value.from_currency)
    to_currency = _currency(value.to_currency)
    if from_currency == to_currency:
        raise _fail()
    return HistoricalExchangeRateRangeRequirement(
        from_currency=from_currency,
        to_currency=to_currency,
        provider=value.provider,
        requested_at=_requested_timestamps(value.requested_at),
        interval=value.interval,
    )


__all__ = [
    "HistoricalExchangeRateProviderCapability",
    "HistoricalExchangeRateRangeRequirement",
    "HistoricalExchangeRateSelection",
    "HistoricalMarketEvidenceStateError",
    "HistoricalPriceProviderCapability",
    "HistoricalPriceRangeRequirement",
    "HistoricalPriceSelection",
    "HistoricalProviderGranularity",
    "HistoricalProviderRangeCapability",
    "HistoricalTimeSeriesInterval",
    "validate_historical_exchange_rate_range_requirement",
    "validate_historical_price_range_requirement",
]
