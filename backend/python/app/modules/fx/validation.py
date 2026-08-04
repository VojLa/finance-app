"""Pure validation for canonical direct exchange-rate observations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.db.models.enums import ExchangeRateSource
from app.modules.fx.models import ExchangeRateObservation
from app.modules.market_data.models import ExchangeRateRequirement
from app.modules.market_data.policy import MarketEvidencePolicy, validate_market_evidence_policy

_RATE_PRECISION = 18
_RATE_SCALE = 8


class ExchangeRateObservationValidationError(ValueError):
    pass


def _fail() -> ExchangeRateObservationValidationError:
    return ExchangeRateObservationValidationError(
        "Exchange-rate provider returned incompatible evidence."
    )


def _currency(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) != 3
        or value != value.upper()
        or not value.isascii()
        or not value.isalpha()
    ):
        raise _fail()
    return value


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
    if not isinstance(exponent, int) or exponent < -_RATE_SCALE:
        raise _fail()
    integer_digits = max(value.adjusted() + 1, 0)
    if integer_digits > _RATE_PRECISION - _RATE_SCALE:
        raise _fail()
    return value


def validate_exchange_rate_observation(
    value: object,
    *,
    requirement: ExchangeRateRequirement,
    policy: MarketEvidencePolicy,
) -> ExchangeRateObservation:
    if (
        not isinstance(value, ExchangeRateObservation)
        or not isinstance(requirement, ExchangeRateRequirement)
        or not isinstance(value.provider, ExchangeRateSource)
    ):
        raise _fail()
    canonical_policy = validate_market_evidence_policy(policy)
    from_currency = _currency(value.from_currency)
    to_currency = _currency(value.to_currency)
    effective_at = _timestamp(value.effective_at)
    through = _timestamp(requirement.through)
    age = through - effective_at
    if (
        from_currency == to_currency
        or from_currency != requirement.from_currency
        or to_currency != requirement.to_currency
        or value.provider is not requirement.provider
        or age.total_seconds() < 0
        or age > canonical_policy.maximum_fx_age
    ):
        raise _fail()
    return ExchangeRateObservation(
        from_currency=from_currency,
        to_currency=to_currency,
        provider=value.provider,
        rate=_positive_decimal(value.rate),
        effective_at=effective_at,
    )
