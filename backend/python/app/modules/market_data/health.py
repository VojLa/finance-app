"""Pure, ordered transitions for one exact listing/provider health identity."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from app.db.models.enums import MarketDataFailureReason, MarketDataHealthState

_TEMPORARY = frozenset(
    {
        MarketDataFailureReason.timeout,
        MarketDataFailureReason.server_error,
        MarketDataFailureReason.incomplete_response,
    }
)
_PERMANENT = frozenset(
    {
        MarketDataFailureReason.unknown_symbol,
        MarketDataFailureReason.currency_conflict,
        MarketDataFailureReason.provider_identity_conflict,
        MarketDataFailureReason.missing_provider_symbol,
    }
)
_INVALID_EVIDENCE = frozenset(
    {MarketDataFailureReason.invalid_price, MarketDataFailureReason.stale_timestamp}
)
_RATE_LIMIT_DELAY = timedelta(minutes=15)
_TEMPORARY_COOLDOWN = timedelta(minutes=5)
_MAX_TEMPORARY_COOLDOWN = timedelta(hours=1)


@dataclass(frozen=True, slots=True)
class ListingHealthSnapshot:
    state: MarketDataHealthState
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    consecutive_failures: int
    last_failure_reason: MarketDataFailureReason | None
    retry_after: datetime | None
    state_changed_at: datetime
    last_attempt_token: str | None
    version: int
    total_successes: int = 0
    total_failures: int = 0


@dataclass(frozen=True, slots=True)
class ListingHealthOutcome:
    attempt_started_at: datetime
    attempt_token: str
    observed_at: datetime
    reason: MarketDataFailureReason | None = None  # None means valid evidence was acquired.
    retry_after: datetime | None = None  # Provider Retry-After for rate limits only.
    next_session_at: datetime | None = None  # Supported-calendar boundary for a closed market.


def apply_listing_health_outcome(
    current: ListingHealthSnapshot | None,
    outcome: ListingHealthOutcome,
) -> ListingHealthSnapshot:
    """Return a new state; equal or older attempt identities are no-ops.

    The caller must hold the listing/provider row lock or compare `version` when
    persisting the returned snapshot. Acquisition leases are managed separately.
    """
    if not outcome.attempt_token or not outcome.attempt_token.strip():
        raise ValueError("attempt_token must be nonblank")
    if current is not None and current.last_attempt_at is not None:
        assert current.last_attempt_token is not None
        if (outcome.attempt_started_at, outcome.attempt_token) <= (
            current.last_attempt_at,
            current.last_attempt_token,
        ):
            return current

    if outcome.observed_at < outcome.attempt_started_at:
        raise ValueError("observed_at must follow attempt_started_at")
    if outcome.retry_after is not None and outcome.reason != MarketDataFailureReason.rate_limit:
        raise ValueError("retry_after is only valid for rate limits")
    if (
        outcome.next_session_at is not None
        and outcome.reason != MarketDataFailureReason.market_closed
    ):
        raise ValueError("next_session_at is only valid for market closure")
    if outcome.reason == MarketDataFailureReason.market_closed:
        if outcome.next_session_at is None or outcome.next_session_at <= outcome.observed_at:
            raise ValueError("market closure requires a future supported session boundary")
    if outcome.reason == MarketDataFailureReason.rate_limit:
        if outcome.retry_after is not None and outcome.retry_after <= outcome.observed_at:
            raise ValueError("provider retry_after must be in the future")

    if current is None:
        current = ListingHealthSnapshot(
            state=MarketDataHealthState.unknown,
            last_success_at=None,
            last_attempt_at=None,
            consecutive_failures=0,
            last_failure_reason=None,
            retry_after=None,
            state_changed_at=outcome.observed_at,
            last_attempt_token=None,
            version=0,
        )

    reason = outcome.reason
    failures = current.consecutive_failures + 1
    total_successes = current.total_successes
    total_failures = current.total_failures
    last_success_at: datetime | None
    if reason is None:
        new_state = MarketDataHealthState.healthy
        failures = 0
        last_success_at = outcome.observed_at
        retry_after = None
        total_successes += 1
    elif reason == MarketDataFailureReason.market_closed:
        new_state = current.state
        failures = current.consecutive_failures
        last_success_at = current.last_success_at
        retry_after = max(
            boundary
            for boundary in (current.retry_after, outcome.next_session_at)
            if boundary is not None
        )
    elif reason in _PERMANENT:
        new_state = MarketDataHealthState.unavailable
        last_success_at = current.last_success_at
        retry_after = None
    elif reason == MarketDataFailureReason.rate_limit:
        new_state = MarketDataHealthState.degraded
        last_success_at = current.last_success_at
        retry_after = max(
            boundary
            for boundary in (
                current.retry_after,
                outcome.retry_after or outcome.observed_at + _RATE_LIMIT_DELAY,
            )
            if boundary is not None
        )
    elif reason in _INVALID_EVIDENCE:
        new_state = MarketDataHealthState.degraded
        last_success_at = current.last_success_at
        retry_after = current.retry_after
    elif reason in _TEMPORARY:
        new_state = (
            MarketDataHealthState.suspect
            if failures == 1
            else MarketDataHealthState.degraded
            if failures == 2
            else MarketDataHealthState.unavailable
        )
        last_success_at = current.last_success_at
        if failures >= 3:
            delay = min(
                _TEMPORARY_COOLDOWN * (2 ** min(failures - 3, 8)),
                _MAX_TEMPORARY_COOLDOWN,
            )
            retry_after = max(
                boundary
                for boundary in (current.retry_after, outcome.observed_at + delay)
                if boundary is not None
            )
        else:
            retry_after = current.retry_after
    else:
        raise ValueError(f"unsupported health outcome: {reason!r}")

    if reason is not None and reason != MarketDataFailureReason.market_closed:
        total_failures += 1

    return replace(
        current,
        state=new_state,
        last_success_at=last_success_at,
        last_attempt_at=outcome.attempt_started_at,
        consecutive_failures=failures,
        # Market closure is scheduling evidence, not a provider outcome. Preserve
        # the prior classified failure so an unavailable/degraded listing remains
        # eligible for its recovery probe when the next session opens.
        last_failure_reason=(
            current.last_failure_reason
            if reason == MarketDataFailureReason.market_closed
            else reason
        ),
        retry_after=retry_after,
        state_changed_at=(
            max(current.state_changed_at, outcome.observed_at)
            if new_state != current.state
            else current.state_changed_at
        ),
        last_attempt_token=outcome.attempt_token,
        version=current.version + 1,
        total_successes=total_successes,
        total_failures=total_failures,
    )
