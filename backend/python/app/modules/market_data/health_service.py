"""Lease acquisition and ordered outcome recording for market-data health."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.db.models.enums import MarketDataFailureReason, MarketDataHealthState, PriceSource
from app.db.models.market_health import MarketDataListingHealthModel
from app.modules.market_data.health import (
    ListingHealthOutcome,
    ListingHealthSnapshot,
    apply_listing_health_outcome,
)
from app.modules.market_data.health_repository import MarketDataHealthRepository, health_id

_MAX_LEASE = timedelta(minutes=5)
_PERMANENT_REASONS = frozenset(
    {
        MarketDataFailureReason.unknown_symbol,
        MarketDataFailureReason.currency_conflict,
        MarketDataFailureReason.provider_identity_conflict,
        MarketDataFailureReason.missing_provider_symbol,
    }
)


def _snapshot(row: MarketDataListingHealthModel) -> ListingHealthSnapshot:
    return ListingHealthSnapshot(
        state=row.state,
        last_success_at=row.last_success_at,
        last_attempt_at=row.last_attempt_at,
        consecutive_failures=row.consecutive_failures,
        last_failure_reason=row.last_failure_reason,
        retry_after=row.retry_after,
        state_changed_at=row.state_changed_at,
        last_attempt_token=row.last_attempt_token,
        version=row.version,
        total_successes=row.total_successes,
        total_failures=row.total_failures,
    )


def _write_snapshot(row: MarketDataListingHealthModel, snapshot: ListingHealthSnapshot) -> None:
    row.state = snapshot.state
    row.last_success_at = snapshot.last_success_at
    row.last_attempt_at = snapshot.last_attempt_at
    row.consecutive_failures = snapshot.consecutive_failures
    row.last_failure_reason = snapshot.last_failure_reason
    row.retry_after = snapshot.retry_after
    row.state_changed_at = snapshot.state_changed_at
    row.last_attempt_token = snapshot.last_attempt_token
    row.version = snapshot.version
    row.total_successes = snapshot.total_successes
    row.total_failures = snapshot.total_failures


class MarketDataHealthService:
    """Call inside an explicit transaction; commit claim before provider I/O.

    An acquisition lease guards requests across processes and restarts. Its owner
    should be a unique attempt identifier. Recording in a second transaction
    requires that owner while its lease remains on the row.
    """

    def __init__(self, repository: MarketDataHealthRepository) -> None:
        self.repository = repository

    async def claim(
        self,
        *,
        listing_id: str,
        provider: PriceSource,
        provider_symbol: str,
        lease_owner: str,
        now: datetime,
        lease_for: timedelta,
    ) -> bool:
        if not listing_id or not provider_symbol or not provider_symbol.strip():
            return False
        if not lease_owner or not lease_owner.strip():
            raise ValueError("lease_owner must be nonblank")
        if not timedelta(0) < lease_for <= _MAX_LEASE:
            raise ValueError("lease_for must be between zero and five minutes")
        repo = self.repository
        repo.require_transaction()
        await repo.lock_provider_and_listing(listing_id, provider)
        if not await repo.validate_identity(listing_id, provider, provider_symbol):
            return False
        if await repo.provider_retry_after(provider, now) is not None:
            return False
        row = await repo.locked_row(listing_id, provider)
        if row is not None:
            if row.provider_symbol != provider_symbol:
                if (
                    row.provider_symbol is None
                    and row.last_failure_reason is MarketDataFailureReason.missing_provider_symbol
                ):
                    row.provider_symbol = provider_symbol
                    row.state = MarketDataHealthState.unknown
                    row.consecutive_failures = 0
                    row.last_failure_reason = None
                    row.retry_after = None
                    row.state_changed_at = now
                else:
                    return False
            if row.last_failure_reason in _PERMANENT_REASONS:
                return False
            if row.retry_after is not None and row.retry_after > now:
                return False
            if row.lease_expires_at is not None and row.lease_expires_at > now:
                return row.lease_owner == lease_owner
            row.lease_owner = lease_owner
            row.lease_expires_at = now + lease_for
            row.version += 1
        else:
            repo.add(
                MarketDataListingHealthModel(
                    id=health_id(listing_id, provider),
                    listing_id=listing_id,
                    provider=provider,
                    provider_symbol=provider_symbol,
                    state=MarketDataHealthState.unknown,
                    last_success_at=None,
                    last_attempt_at=None,
                    consecutive_failures=0,
                    last_failure_reason=None,
                    retry_after=None,
                    state_changed_at=now,
                    last_attempt_token=None,
                    lease_owner=lease_owner,
                    lease_expires_at=now + lease_for,
                    version=1,
                    total_successes=0,
                    total_failures=0,
                )
            )
        await repo.flush()
        return True

    async def record(
        self,
        *,
        listing_id: str,
        provider: PriceSource,
        provider_symbol: str | None,
        outcome: ListingHealthOutcome,
        lease_owner: str | None = None,
    ) -> ListingHealthSnapshot | None:
        """Persist only a newer attempt; None means identity or lease was rejected.

        An exact replay returns the persisted snapshot unchanged. Any other
        completion must still own the active lease, so an expired worker cannot
        publish evidence after a takeover has completed.
        """
        if not listing_id:
            return None
        if (
            provider_symbol is None
            and outcome.reason != MarketDataFailureReason.missing_provider_symbol
        ):
            return None
        if provider_symbol is not None and not provider_symbol.strip():
            return None
        # Ordinary provider outcomes must match a previously committed claim.
        # An absent symbol cannot be claimed and may be recorded as a permanent
        # configuration failure directly.
        if (
            lease_owner is None
            and outcome.reason != MarketDataFailureReason.missing_provider_symbol
        ):
            return None
        repo = self.repository
        repo.require_transaction()
        await repo.lock_provider_and_listing(listing_id, provider)
        if not await repo.validate_identity(listing_id, provider, provider_symbol):
            return None
        row = await repo.locked_row(listing_id, provider)
        missing_symbol_configuration = (
            provider_symbol is None
            and outcome.reason is MarketDataFailureReason.missing_provider_symbol
            and lease_owner is None
        )
        if (
            row is not None
            and row.provider_symbol != provider_symbol
            and not missing_symbol_configuration
        ):
            return None
        current = _snapshot(row) if row is not None else None
        exact_replay = (
            current is not None
            and current.last_attempt_at == outcome.attempt_started_at
            and current.last_attempt_token == outcome.attempt_token
        )
        if exact_replay:
            return current
        if row is not None and not missing_symbol_configuration and row.lease_owner != lease_owner:
            return None
        updated = apply_listing_health_outcome(current, outcome)
        if updated is current:
            return current if missing_symbol_configuration else None
        if row is not None:
            if missing_symbol_configuration:
                # The locked listing identity was revalidated as explicitly
                # symbol-less. Invalidate any lease for the removed identity;
                # a stale completion cannot pass validate_identity afterwards.
                row.provider_symbol = None
                row.lease_owner = None
                row.lease_expires_at = None
            _write_snapshot(row, updated)
            if lease_owner is not None:
                row.lease_owner = None
                row.lease_expires_at = None
        else:
            if lease_owner is not None:
                return None
            row = MarketDataListingHealthModel(
                id=health_id(listing_id, provider),
                listing_id=listing_id,
                provider=provider,
                provider_symbol=provider_symbol,
                state=updated.state,
                last_success_at=updated.last_success_at,
                last_attempt_at=updated.last_attempt_at,
                consecutive_failures=updated.consecutive_failures,
                last_failure_reason=updated.last_failure_reason,
                retry_after=updated.retry_after,
                state_changed_at=updated.state_changed_at,
                last_attempt_token=updated.last_attempt_token,
                lease_owner=None,
                lease_expires_at=None,
                version=updated.version,
                total_successes=updated.total_successes,
                total_failures=updated.total_failures,
            )
            repo.add(row)
        await repo.flush()
        return updated
