"""Pure validation for canonical price observations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.db.models.enums import PriceSource
from app.modules.market_data.models import PriceRequirement
from app.modules.market_data.policy import MarketEvidencePolicy, validate_market_evidence_policy
from app.modules.prices.models import PriceObservation

_PRICE_PRECISION = 28
_PRICE_SCALE = 10


class PriceObservationValidationError(ValueError):
    pass


def _fail() -> PriceObservationValidationError:
    return PriceObservationValidationError("Price provider returned incompatible evidence.")


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    result = _nonblank(value)
    if len(result) != 3 or result != result.upper() or not result.isascii() or not result.isalpha():
        raise _fail()
    return result


def _timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or value.microsecond % 1_000 != 0
    ):
        raise _fail()
    return value


def _positive_decimal(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise _fail()
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -_PRICE_SCALE:
        raise _fail()
    integer_digits = max(value.adjusted() + 1, 0)
    if integer_digits > _PRICE_PRECISION - _PRICE_SCALE:
        raise _fail()
    return value


def validate_price_observation(
    value: object,
    *,
    requirement: PriceRequirement,
    policy: MarketEvidencePolicy,
) -> PriceObservation:
    if (
        not isinstance(value, PriceObservation)
        or not isinstance(requirement, PriceRequirement)
        or not isinstance(value.provider, PriceSource)
    ):
        raise _fail()
    canonical_policy = validate_market_evidence_policy(policy)
    asset_id = _nonblank(value.asset_id)
    listing_id = _nonblank(value.listing_id)
    provider_symbol = _nonblank(value.provider_symbol)
    currency = _currency(value.currency)
    observed_at = _timestamp(value.observed_at)
    through = _timestamp(requirement.through)
    age = through - observed_at
    if (
        asset_id != requirement.asset_id
        or listing_id != requirement.listing_id
        or value.provider is not requirement.provider
        or provider_symbol != requirement.provider_symbol
        or currency != requirement.listing_currency
        or age.total_seconds() < 0
        or age > canonical_policy.maximum_price_age
    ):
        raise _fail()
    return PriceObservation(
        asset_id=asset_id,
        listing_id=listing_id,
        provider=value.provider,
        provider_symbol=provider_symbol,
        price=_positive_decimal(value.price),
        currency=currency,
        observed_at=observed_at,
    )
