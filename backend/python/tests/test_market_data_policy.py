from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
    MarketEvidencePolicyError,
    validate_market_evidence_policy,
)


def test_default_policy_is_explicit_and_immutable() -> None:
    assert DEFAULT_MARKET_EVIDENCE_POLICY == MarketEvidencePolicy(
        maximum_price_age=timedelta(hours=72),
        maximum_fx_age=timedelta(days=7),
    )
    with pytest.raises(FrozenInstanceError):
        DEFAULT_MARKET_EVIDENCE_POLICY.maximum_fx_age = timedelta(days=8)  # type: ignore[misc]


@pytest.mark.parametrize(
    "value",
    [
        object(),
        MarketEvidencePolicy(timedelta(0), timedelta(days=7)),
        MarketEvidencePolicy(timedelta(hours=-1), timedelta(days=7)),
        MarketEvidencePolicy(timedelta(hours=72), timedelta(0)),
        MarketEvidencePolicy(timedelta(hours=72), timedelta(days=-1)),
    ],
)
def test_policy_rejects_nonpositive_or_malformed_values(value: object) -> None:
    with pytest.raises(MarketEvidencePolicyError):
        validate_market_evidence_policy(value)


def test_policy_validator_preserves_exact_value() -> None:
    policy = MarketEvidencePolicy(timedelta(hours=1), timedelta(days=2))
    assert validate_market_evidence_policy(policy) is policy
