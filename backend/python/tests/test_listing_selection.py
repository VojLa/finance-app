from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from app.db.models.enums import AssetType, MarketDataFailureReason, PriceSource
from app.modules.market_data.health import (
    ListingHealthOutcome,
    MarketDataHealthState,
    apply_listing_health_outcome,
)
from app.modules.market_data.listing_selection import (
    FxCompatibilityEvidence,
    ListingSelectionCandidate,
    ListingSelectionError,
    ListingSelectionReason,
    select_listing,
)

NOW = datetime(2026, 9, 30, 12)


def _candidate(
    listing_id: str,
    *,
    asset_id: str = "asset-vuaa",
    currency: str = "EUR",
    priority: int = 100,
    health: MarketDataHealthState = MarketDataHealthState.healthy,
    provider: PriceSource = PriceSource.yahoo_finance,
    symbol: str | None = None,
) -> ListingSelectionCandidate:
    return ListingSelectionCandidate(
        listing_id=listing_id,
        asset_id=asset_id,
        asset_type=AssetType.etf,
        currency=currency,
        provider=provider,
        provider_symbol=symbol or listing_id,
        mic="XETR" if listing_id.endswith(".DE") else "XMIL",
        base_priority=priority,
        health=health,
        price_available=False,
        acquisition_eligible=True,
    )


def _select(
    *candidates: ListingSelectionCandidate,
    requested: str = "VUAA.DE",
    now: datetime = NOW,
):
    return select_listing(
        requested_listing_id=requested,
        asset_id="asset-vuaa",
        asset_type=AssetType.etf,
        valuation_currency="EUR",
        through=NOW,
        now=now,
        candidates=tuple(candidates),
    )


def test_higher_base_priority_wins_between_healthy_listings() -> None:
    result = _select(
        _candidate("VUAA.MI", priority=80),
        _candidate("VUAA.DE", priority=100),
    )
    assert result.selected_listing_id == "VUAA.DE"


def test_degraded_preferred_listing_is_skipped_and_recovers() -> None:
    degraded = _candidate("VUAA.DE", priority=100, health=MarketDataHealthState.degraded)
    alternate = _candidate("VUAA.MI", priority=80)
    fallback = _select(degraded, alternate)
    assert fallback.selected_listing_id == "VUAA.MI"
    assert fallback.fallback_reason is ListingSelectionReason.requested_listing_degraded

    recovered = _select(
        _candidate("VUAA.DE", priority=100, health=MarketDataHealthState.healthy),
        alternate,
    )
    assert recovered.selected_listing_id == "VUAA.DE"


def test_one_suspect_failure_does_not_force_fallback() -> None:
    result = _select(
        _candidate("VUAA.DE", priority=100, health=MarketDataHealthState.suspect),
        _candidate("VUAA.MI", priority=80),
    )
    assert result.selected_listing_id == "VUAA.DE"


def test_equal_priority_uses_explicit_stable_identity_tie_breaker() -> None:
    left = _candidate("listing-b", priority=100, symbol="B")
    right = _candidate("listing-a", priority=100, symbol="A")
    forward = _select(left, right, requested="listing-b")
    reverse = _select(right, left, requested="listing-b")
    assert forward.selected_listing_id == reverse.selected_listing_id == "listing-a"


def test_listing_from_another_asset_is_never_selected() -> None:
    result = _select(
        _candidate("VUAA.DE", priority=10),
        _candidate("foreign", asset_id="other", priority=1000),
    )
    assert result.selected_listing_id == "VUAA.DE"


def test_unresolved_requested_identity_can_fallback_only_to_exact_same_asset() -> None:
    result = _select(
        _candidate("VUAA.MI", priority=80),
        requested="missing-requested-identity",
    )
    assert result.selected_listing_id == "VUAA.MI"
    assert result.fallback_reason is ListingSelectionReason.requested_listing_incompatible


def test_incompatible_currency_fails_closed_without_direct_fx_evidence() -> None:
    with pytest.raises(ListingSelectionError, match="No safe listing"):
        _select(_candidate("VUAA.DE", currency="USD"))


def test_other_currency_requires_fresh_direct_fx_evidence() -> None:
    candidate = _candidate("VUAA.DE", currency="USD")
    result = select_listing(
        requested_listing_id="VUAA.DE",
        asset_id="asset-vuaa",
        asset_type=AssetType.etf,
        valuation_currency="EUR",
        through=NOW,
        now=NOW,
        candidates=(candidate,),
        fx_evidence=(
            FxCompatibilityEvidence(
                from_currency="USD",
                to_currency="EUR",
                observed_at=NOW - timedelta(hours=1),
                valid_through=NOW + timedelta(hours=1),
            ),
        ),
    )
    assert result.selected_listing_id == "VUAA.DE"


def test_cooldown_survives_as_persisted_candidate_state() -> None:
    preferred = _candidate("VUAA.DE", priority=100)
    preferred = ListingSelectionCandidate(
        **{
            name: getattr(preferred, name)
            for name in preferred.__dataclass_fields__
            if name != "retry_after"
        },
        retry_after=NOW + timedelta(minutes=5),
    )
    result = _select(preferred, _candidate("VUAA.MI", priority=80))
    assert result.selected_listing_id == "VUAA.MI"
    assert result.fallback_reason is ListingSelectionReason.requested_listing_cooldown


def test_temporary_unavailable_listing_gets_due_acquisition_probe_only() -> None:
    health = None
    for attempt in range(3):
        attempted_at = NOW - timedelta(minutes=3 - attempt)
        health = apply_listing_health_outcome(
            health,
            ListingHealthOutcome(
                attempt_started_at=attempted_at,
                attempt_token=f"failure-{attempt}",
                observed_at=attempted_at,
                reason=MarketDataFailureReason.timeout,
            ),
        )
    assert health is not None
    assert health.state is MarketDataHealthState.unavailable
    assert health.retry_after is not None and health.retry_after > NOW

    preferred = replace(
        _candidate("VUAA.DE", priority=100),
        health=health.state,
        retry_after=health.retry_after,
        last_failure_reason=health.last_failure_reason,
        acquisition_probe=True,
    )
    fallback = _candidate("VUAA.MI", priority=80)
    assert _select(preferred, fallback).selected_listing_id == "VUAA.MI"

    due_at = health.retry_after
    assert _select(preferred, fallback, now=due_at).selected_listing_id == "VUAA.DE"
    valuation_only = replace(preferred, acquisition_eligible=False)
    assert _select(valuation_only, fallback, now=due_at).selected_listing_id == "VUAA.MI"

    recovered = apply_listing_health_outcome(
        health,
        ListingHealthOutcome(
            attempt_started_at=due_at,
            attempt_token="recovered",
            observed_at=due_at,
        ),
    )
    assert recovered.state is MarketDataHealthState.healthy
    assert (
        _select(
            replace(
                preferred,
                health=recovered.state,
                retry_after=recovered.retry_after,
                last_failure_reason=recovered.last_failure_reason,
                acquisition_probe=False,
            ),
            fallback,
            now=due_at,
        ).selected_listing_id
        == "VUAA.DE"
    )


def test_closed_session_preserves_temporary_recovery_probe_for_next_session() -> None:
    health = None
    for attempt in range(3):
        attempted_at = NOW - timedelta(minutes=3 - attempt)
        health = apply_listing_health_outcome(
            health,
            ListingHealthOutcome(
                attempt_started_at=attempted_at,
                attempt_token=f"failure-{attempt}",
                observed_at=attempted_at,
                reason=MarketDataFailureReason.timeout,
            ),
        )
    assert health is not None and health.retry_after is not None
    next_session = health.retry_after + timedelta(hours=12)
    closed = apply_listing_health_outcome(
        health,
        ListingHealthOutcome(
            attempt_started_at=health.retry_after,
            attempt_token="closed-session",
            observed_at=health.retry_after,
            reason=MarketDataFailureReason.market_closed,
            next_session_at=next_session,
        ),
    )
    preferred = replace(
        _candidate("VUAA.DE", priority=100),
        health=closed.state,
        retry_after=closed.retry_after,
        last_failure_reason=closed.last_failure_reason,
        acquisition_probe=True,
    )
    fallback = _candidate("VUAA.MI", priority=80)

    assert closed.state is MarketDataHealthState.unavailable
    assert closed.last_failure_reason is MarketDataFailureReason.timeout
    assert _select(preferred, fallback, now=next_session).selected_listing_id == "VUAA.DE"
    assert (
        _select(
            replace(preferred, acquisition_eligible=False),
            fallback,
            now=next_session,
        ).selected_listing_id
        == "VUAA.MI"
    )


def test_expired_rate_limit_competes_for_acquisition_probe_only() -> None:
    preferred = replace(
        _candidate("VUAA.DE", priority=100, health=MarketDataHealthState.degraded),
        retry_after=NOW - timedelta(seconds=1),
        last_failure_reason=MarketDataFailureReason.rate_limit,
        acquisition_probe=True,
    )
    fallback = _candidate("VUAA.MI", priority=80)
    assert _select(preferred, fallback).selected_listing_id == "VUAA.DE"
    assert (
        _select(replace(preferred, acquisition_probe=False), fallback).selected_listing_id
        == "VUAA.MI"
    )
    assert (
        _select(
            replace(preferred, retry_after=NOW + timedelta(minutes=1)),
            fallback,
        ).selected_listing_id
        == "VUAA.MI"
    )


def test_degraded_temporary_listing_is_retried_only_by_acquisition() -> None:
    preferred = replace(
        _candidate("VUAA.DE", priority=100, health=MarketDataHealthState.degraded),
        last_failure_reason=MarketDataFailureReason.timeout,
        acquisition_probe=True,
    )
    fallback = _candidate("VUAA.MI", priority=80)
    assert _select(preferred, fallback).selected_listing_id == "VUAA.DE"
    assert (
        _select(replace(preferred, acquisition_probe=False), fallback).selected_listing_id
        == "VUAA.MI"
    )


@pytest.mark.parametrize(
    "reason",
    [
        MarketDataFailureReason.unknown_symbol,
        MarketDataFailureReason.currency_conflict,
        MarketDataFailureReason.provider_identity_conflict,
        MarketDataFailureReason.missing_provider_symbol,
    ],
)
def test_permanent_unavailable_never_gets_acquisition_probe(
    reason: MarketDataFailureReason,
) -> None:
    preferred = replace(
        _candidate("VUAA.DE", priority=100, health=MarketDataHealthState.unavailable),
        retry_after=NOW - timedelta(seconds=1),
        last_failure_reason=reason,
        acquisition_probe=True,
    )
    assert _select(preferred, _candidate("VUAA.MI", priority=80)).selected_listing_id == "VUAA.MI"


def test_missing_requested_price_has_an_explicit_fallback_reason() -> None:
    requested = replace(
        _candidate("VUAA.DE", priority=100),
        price_available=False,
        acquisition_eligible=False,
    )
    alternate = replace(
        _candidate("VUAA.MI", priority=80),
        price_available=True,
        acquisition_eligible=False,
    )

    result = _select(requested, alternate)

    assert result.selected_listing_id == "VUAA.MI"
    assert result.fallback_reason is ListingSelectionReason.requested_price_unavailable
