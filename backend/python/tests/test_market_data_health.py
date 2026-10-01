from datetime import datetime, timedelta
from typing import cast

import pytest
from sqlalchemy import Table, UniqueConstraint

from app.db.models import MarketDataListingHealthModel
from app.db.models.enums import MarketDataFailureReason as Reason
from app.db.models.enums import MarketDataHealthState as State
from app.modules.market_data.health import (
    ListingHealthOutcome,
    ListingHealthSnapshot,
    apply_listing_health_outcome,
)

START = datetime(2026, 9, 30, 9, 0)


def outcome(
    minute: int,
    reason: Reason | None = None,
    *,
    token: str | None = None,
    retry_after: datetime | None = None,
    next_session_at: datetime | None = None,
) -> ListingHealthOutcome:
    started = START + timedelta(minutes=minute)
    return ListingHealthOutcome(
        attempt_started_at=started,
        attempt_token=token or f"attempt-{minute}",
        observed_at=started + timedelta(seconds=1),
        reason=reason,
        retry_after=retry_after,
        next_session_at=next_session_at,
    )


@pytest.mark.parametrize(
    "reason",
    [Reason.timeout, Reason.server_error, Reason.incomplete_response],
)
def test_temporary_failures_escalate_and_cap_cooldown(reason: Reason) -> None:
    first = apply_listing_health_outcome(None, outcome(0, reason))
    second = apply_listing_health_outcome(first, outcome(1, reason))
    third = apply_listing_health_outcome(second, outcome(2, reason))

    assert [first.state, second.state, third.state] == [
        State.suspect,
        State.degraded,
        State.unavailable,
    ]
    assert [
        first.consecutive_failures,
        second.consecutive_failures,
        third.consecutive_failures,
    ] == [
        1,
        2,
        3,
    ]
    assert first.retry_after is None and second.retry_after is None
    assert third.retry_after == START + timedelta(minutes=7, seconds=1)

    current = third
    for minute in range(3, 15):
        current = apply_listing_health_outcome(current, outcome(minute, reason))
    assert current.retry_after == START + timedelta(minutes=74, seconds=1)


def test_replay_and_late_older_completion_cannot_replace_newer_outcome() -> None:
    earlier = outcome(0, Reason.timeout)
    later = outcome(1)
    latest = apply_listing_health_outcome(None, later)

    assert apply_listing_health_outcome(latest, later) is latest
    assert apply_listing_health_outcome(latest, earlier) is latest
    assert latest.state == State.healthy
    assert latest.version == 1


def test_token_breaks_same_start_time_ties() -> None:
    first = apply_listing_health_outcome(None, outcome(0, Reason.timeout, token="a"))
    second = apply_listing_health_outcome(first, outcome(0, token="b"))

    assert second.state == State.healthy
    assert second.version == 2
    assert (
        apply_listing_health_outcome(second, outcome(0, Reason.server_error, token="a")) is second
    )


def test_success_recovers_and_resets_failures_without_mutating_prior_snapshot() -> None:
    failure = apply_listing_health_outcome(None, outcome(0, Reason.timeout))
    recovered = apply_listing_health_outcome(failure, outcome(1))

    assert recovered.state == State.healthy
    assert recovered.consecutive_failures == 0
    assert recovered.last_failure_reason is None
    assert recovered.retry_after is None
    assert recovered.last_success_at == START + timedelta(minutes=1, seconds=1)
    assert recovered.state_changed_at == recovered.last_success_at
    assert failure.state == State.suspect and failure.consecutive_failures == 1
    assert failure.total_failures == 1 and failure.total_successes == 0
    assert recovered.total_failures == 1 and recovered.total_successes == 1


def test_rate_limit_uses_provider_retry_after_or_computed_delay() -> None:
    provided = START + timedelta(hours=2)
    default = apply_listing_health_outcome(None, outcome(0, Reason.rate_limit))
    first = apply_listing_health_outcome(None, outcome(0, Reason.rate_limit, retry_after=provided))
    computed = apply_listing_health_outcome(first, outcome(1, Reason.rate_limit))

    assert default.retry_after == START + timedelta(minutes=15, seconds=1)
    assert first.state == State.degraded and first.retry_after == provided
    assert computed.state == State.degraded
    assert computed.retry_after == provided


@pytest.mark.parametrize(
    "reason",
    [
        Reason.unknown_symbol,
        Reason.currency_conflict,
        Reason.provider_identity_conflict,
        Reason.missing_provider_symbol,
    ],
)
def test_permanent_identity_failures_are_unavailable_without_retry(reason: Reason) -> None:
    result = apply_listing_health_outcome(None, outcome(0, reason))

    assert result.state == State.unavailable
    assert result.last_failure_reason == reason
    assert result.retry_after is None


@pytest.mark.parametrize("reason", [Reason.invalid_price, Reason.stale_timestamp])
def test_invalid_evidence_degrades_until_valid_evidence(reason: Reason) -> None:
    degraded = apply_listing_health_outcome(None, outcome(0, reason))
    recovered = apply_listing_health_outcome(degraded, outcome(1))

    assert degraded.state == State.degraded
    assert recovered.state == State.healthy


def test_market_closure_preserves_state_and_failure_count_then_schedules_session() -> None:
    previous = apply_listing_health_outcome(None, outcome(0, Reason.timeout))
    boundary = START + timedelta(days=1)
    closed = apply_listing_health_outcome(
        previous, outcome(1, Reason.market_closed, next_session_at=boundary)
    )

    assert closed.state == previous.state
    assert closed.consecutive_failures == previous.consecutive_failures
    assert closed.state_changed_at == previous.state_changed_at
    assert closed.last_attempt_at == START + timedelta(minutes=1)
    assert closed.last_failure_reason == Reason.timeout
    assert closed.retry_after == boundary
    assert closed.total_failures == previous.total_failures


def test_closed_market_does_not_shorten_persisted_provider_cooldown() -> None:
    provided = START + timedelta(days=2)
    limited = apply_listing_health_outcome(
        None, outcome(0, Reason.rate_limit, retry_after=provided)
    )
    closed = apply_listing_health_outcome(
        limited,
        outcome(1, Reason.market_closed, next_session_at=START + timedelta(days=1)),
    )

    assert closed.state == State.degraded
    assert closed.retry_after == provided
    assert closed.last_failure_reason == Reason.rate_limit


def test_closed_market_requires_supported_future_boundary() -> None:
    with pytest.raises(ValueError, match="future supported session"):
        apply_listing_health_outcome(None, outcome(0, Reason.market_closed))
    with pytest.raises(ValueError, match="future supported session"):
        apply_listing_health_outcome(
            None,
            outcome(0, Reason.market_closed, next_session_at=START),
        )


def test_model_exposes_persisted_ordering_lease_and_version() -> None:
    table = cast(Table, MarketDataListingHealthModel.__table__)

    assert table.name == "MarketDataListingHealth"
    assert {
        "lastAttemptAt",
        "lastAttemptToken",
        "leaseOwner",
        "leaseExpiresAt",
        "version",
        "totalSuccesses",
        "totalFailures",
    } <= {column.name for column in table.columns}
    assert {"listingId", "provider"} == {
        column.name
        for constraint in table.constraints
        if constraint.name == "MarketDataListingHealth_listing_provider_key"
        for column in cast(UniqueConstraint, constraint).columns
    }
    assert "basePriority" not in table.columns


def test_snapshot_is_immutable() -> None:
    snapshot = apply_listing_health_outcome(None, outcome(0))

    assert isinstance(snapshot, ListingHealthSnapshot)
    with pytest.raises(AttributeError):
        snapshot.state = State.degraded  # type: ignore[misc]
