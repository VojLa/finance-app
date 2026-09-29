"""Fail-closed as-of selection for historical provider ranges."""

from __future__ import annotations

from datetime import datetime

from app.modules.fx.models import ExchangeRateObservation
from app.modules.fx.validation import (
    ExchangeRateObservationValidationError,
    validate_exchange_rate_observation,
)
from app.modules.market_data.history.models import (
    HistoricalExchangeRateRangeRequirement,
    HistoricalExchangeRateSelection,
    HistoricalMarketEvidenceStateError,
    HistoricalPriceRangeRequirement,
    HistoricalPriceSelection,
    validate_historical_exchange_rate_range_requirement,
    validate_historical_price_range_requirement,
)
from app.modules.market_data.models import ExchangeRateRequirement, PriceRequirement
from app.modules.market_data.policy import MarketEvidencePolicy, validate_market_evidence_policy
from app.modules.prices.models import PriceObservation
from app.modules.prices.validation import (
    PriceObservationValidationError,
    validate_price_observation,
)


def _fail() -> HistoricalMarketEvidenceStateError:
    return HistoricalMarketEvidenceStateError()


def _timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or value.microsecond % 1_000 != 0
    ):
        raise _fail()
    return value


def _canonical_price_candidates(
    requirement: HistoricalPriceRangeRequirement,
    candidates: object,
) -> tuple[PriceObservation, ...]:
    if not isinstance(candidates, tuple):
        raise _fail()
    values: list[PriceObservation] = []
    seen: set[datetime] = set()
    for candidate in candidates:
        if (
            not isinstance(candidate, PriceObservation)
            or candidate.asset_id != requirement.asset_id
            or candidate.listing_id != requirement.listing_id
            or candidate.provider is not requirement.provider
            or candidate.provider_symbol != requirement.provider_symbol
            or candidate.currency != requirement.listing_currency
        ):
            raise _fail()
        timestamp = _timestamp(candidate.observed_at)
        if timestamp in seen:
            raise _fail()
        seen.add(timestamp)
        values.append(candidate)
    canonical = tuple(sorted(values, key=lambda item: item.observed_at))
    if tuple(values) != canonical:
        raise _fail()
    return canonical


def _canonical_rate_candidates(
    requirement: HistoricalExchangeRateRangeRequirement,
    candidates: object,
) -> tuple[ExchangeRateObservation, ...]:
    if not isinstance(candidates, tuple):
        raise _fail()
    values: list[ExchangeRateObservation] = []
    seen: set[datetime] = set()
    for candidate in candidates:
        if (
            not isinstance(candidate, ExchangeRateObservation)
            or candidate.from_currency != requirement.from_currency
            or candidate.to_currency != requirement.to_currency
            or candidate.provider is not requirement.provider
        ):
            raise _fail()
        timestamp = _timestamp(candidate.effective_at)
        if timestamp in seen:
            raise _fail()
        seen.add(timestamp)
        values.append(candidate)
    canonical = tuple(sorted(values, key=lambda item: item.effective_at))
    if tuple(values) != canonical:
        raise _fail()
    return canonical


def select_historical_prices(
    requirement: object,
    candidates: object,
    *,
    policy: MarketEvidencePolicy,
) -> tuple[HistoricalPriceSelection, ...]:
    canonical_requirement = validate_historical_price_range_requirement(requirement)
    canonical_policy = validate_market_evidence_policy(policy)
    canonical_candidates = _canonical_price_candidates(canonical_requirement, candidates)
    selections: list[HistoricalPriceSelection] = []
    for through in canonical_requirement.requested_at:
        candidate = next(
            (item for item in reversed(canonical_candidates) if item.observed_at <= through),
            None,
        )
        if candidate is None:
            raise _fail()
        try:
            observation = validate_price_observation(
                candidate,
                requirement=PriceRequirement(
                    account_id="historical",
                    asset_id=canonical_requirement.asset_id,
                    listing_id=canonical_requirement.listing_id,
                    listing_currency=canonical_requirement.listing_currency,
                    provider=canonical_requirement.provider,
                    provider_symbol=canonical_requirement.provider_symbol,
                    through=through,
                ),
                policy=canonical_policy,
            )
        except PriceObservationValidationError as exc:
            raise _fail() from exc
        selections.append(HistoricalPriceSelection(through=through, observation=observation))
    return tuple(selections)


def select_historical_exchange_rates(
    requirement: object,
    candidates: object,
    *,
    policy: MarketEvidencePolicy,
) -> tuple[HistoricalExchangeRateSelection, ...]:
    canonical_requirement = validate_historical_exchange_rate_range_requirement(requirement)
    canonical_policy = validate_market_evidence_policy(policy)
    canonical_candidates = _canonical_rate_candidates(canonical_requirement, candidates)
    selections: list[HistoricalExchangeRateSelection] = []
    for through in canonical_requirement.requested_at:
        candidate = next(
            (item for item in reversed(canonical_candidates) if item.effective_at <= through),
            None,
        )
        if candidate is None:
            raise _fail()
        try:
            observation = validate_exchange_rate_observation(
                candidate,
                requirement=ExchangeRateRequirement(
                    from_currency=canonical_requirement.from_currency,
                    to_currency=canonical_requirement.to_currency,
                    through=through,
                    provider=canonical_requirement.provider,
                ),
                policy=canonical_policy,
            )
        except ExchangeRateObservationValidationError as exc:
            raise _fail() from exc
        selections.append(HistoricalExchangeRateSelection(through=through, observation=observation))
    return tuple(selections)


__all__ = ["select_historical_exchange_rates", "select_historical_prices"]
