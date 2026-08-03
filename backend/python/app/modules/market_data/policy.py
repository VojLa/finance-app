"""Explicit freshness policy shared by refresh and snapshot selection."""

from dataclasses import dataclass
from datetime import timedelta


class MarketEvidencePolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MarketEvidencePolicy:
    maximum_price_age: timedelta
    maximum_fx_age: timedelta


DEFAULT_MARKET_EVIDENCE_POLICY = MarketEvidencePolicy(
    maximum_price_age=timedelta(hours=72),
    maximum_fx_age=timedelta(days=7),
)


def validate_market_evidence_policy(value: object) -> MarketEvidencePolicy:
    if (
        not isinstance(value, MarketEvidencePolicy)
        or not isinstance(value.maximum_price_age, timedelta)
        or not isinstance(value.maximum_fx_age, timedelta)
        or value.maximum_price_age <= timedelta(0)
        or value.maximum_fx_age <= timedelta(0)
    ):
        raise MarketEvidencePolicyError("Market evidence policy is invalid.")
    return value
