"""Pure deterministic selection of one exact market-data listing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.db.models.enums import AssetType, MarketDataFailureReason, PriceSource
from app.modules.market_data.health import MarketDataHealthState


class ListingSelectionError(ValueError):
    pass


class ListingSelectionReason(StrEnum):
    requested_listing = "requested_listing"
    higher_base_priority = "higher_base_priority"
    requested_listing_degraded = "requested_listing_degraded"
    requested_listing_unavailable = "requested_listing_unavailable"
    requested_listing_cooldown = "requested_listing_cooldown"
    requested_listing_incompatible = "requested_listing_incompatible"
    requested_price_unavailable = "requested_price_unavailable"


@dataclass(frozen=True, slots=True)
class ListingSelectionCandidate:
    listing_id: str
    asset_id: str
    asset_type: AssetType
    currency: str
    provider: PriceSource
    provider_symbol: str
    mic: str | None
    base_priority: int
    health: MarketDataHealthState = MarketDataHealthState.unknown
    price_available: bool = False
    acquisition_eligible: bool = True
    retry_after: datetime | None = None
    provider_retry_after: datetime | None = None
    last_failure_reason: MarketDataFailureReason | None = None
    acquisition_probe: bool = False


@dataclass(frozen=True, slots=True)
class FxCompatibilityEvidence:
    from_currency: str
    to_currency: str
    observed_at: datetime
    valid_through: datetime


@dataclass(frozen=True, slots=True)
class ListingSelectionResult:
    requested_listing_id: str
    selected_listing_id: str
    reason: ListingSelectionReason
    fallback_reason: ListingSelectionReason | None
    base_priority: int
    health: MarketDataHealthState
    provider: PriceSource
    provider_symbol: str


_PREFERRED_STATES = frozenset(
    {
        MarketDataHealthState.healthy,
        MarketDataHealthState.suspect,
        MarketDataHealthState.unknown,
    }
)
_RECOVERABLE_COOLDOWN_REASONS = frozenset(
    {
        MarketDataFailureReason.timeout,
        MarketDataFailureReason.server_error,
        MarketDataFailureReason.incomplete_response,
        MarketDataFailureReason.rate_limit,
        MarketDataFailureReason.invalid_price,
        MarketDataFailureReason.stale_timestamp,
    }
)


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ListingSelectionError("Listing selection input is invalid.")
    return value


def _currency(value: object) -> str:
    result = _nonblank(value)
    if len(result) != 3 or result != result.upper() or not result.isascii() or not result.isalpha():
        raise ListingSelectionError("Listing selection input is invalid.")
    return result


def _timestamp(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise ListingSelectionError("Listing selection input is invalid.")
    return value


def _valid_fx_path(
    *,
    source_currency: str,
    target_currency: str,
    through: datetime,
    evidence: tuple[FxCompatibilityEvidence, ...],
) -> bool:
    if source_currency == target_currency:
        return True
    matches = tuple(
        item
        for item in evidence
        if isinstance(item, FxCompatibilityEvidence)
        and item.from_currency == source_currency
        and item.to_currency == target_currency
        and isinstance(item.observed_at, datetime)
        and item.observed_at.tzinfo is None
        and isinstance(item.valid_through, datetime)
        and item.valid_through.tzinfo is None
        and item.observed_at <= through <= item.valid_through
    )
    return len(matches) == 1


def _candidate_tier(candidate: ListingSelectionCandidate, *, now: datetime) -> int | None:
    if candidate.retry_after is not None and candidate.retry_after > now:
        return None
    if candidate.provider_retry_after is not None and candidate.provider_retry_after > now:
        return None
    due_probe = (
        candidate.acquisition_probe
        and candidate.acquisition_eligible
        and (candidate.retry_after is None or candidate.retry_after <= now)
        and candidate.last_failure_reason in _RECOVERABLE_COOLDOWN_REASONS
    )
    if candidate.health is MarketDataHealthState.unavailable:
        return 0 if due_probe else None
    if due_probe:
        return 0
    return 0 if candidate.health in _PREFERRED_STATES else 1


def select_listing(
    *,
    requested_listing_id: str,
    asset_id: str,
    asset_type: AssetType,
    valuation_currency: str,
    through: datetime,
    now: datetime,
    candidates: tuple[ListingSelectionCandidate, ...],
    fx_evidence: tuple[FxCompatibilityEvidence, ...] = (),
) -> ListingSelectionResult:
    """Select a safe listing without relying on database result order.

    A candidate in another quote currency needs one explicit direct FX evidence
    path into the valuation currency. The selector never invents an indirect path.
    """

    requested_id = _nonblank(requested_listing_id)
    expected_asset_id = _nonblank(asset_id)
    target_currency = _currency(valuation_currency)
    cutoff = _timestamp(through)
    current = _timestamp(now)
    if not isinstance(asset_type, AssetType) or cutoff > current:
        raise ListingSelectionError("Listing selection input is invalid.")
    if not isinstance(candidates, tuple) or not isinstance(fx_evidence, tuple):
        raise ListingSelectionError("Listing selection input is invalid.")

    by_id: dict[str, ListingSelectionCandidate] = {}
    for candidate in candidates:
        if not isinstance(candidate, ListingSelectionCandidate):
            raise ListingSelectionError("Listing selection input is invalid.")
        listing_id = _nonblank(candidate.listing_id)
        if listing_id in by_id:
            raise ListingSelectionError("Listing selection input is invalid.")
        by_id[listing_id] = candidate
    requested = by_id.get(requested_id)
    if requested is not None and (
        requested.asset_id != expected_asset_id or requested.asset_type is not asset_type
    ):
        raise ListingSelectionError("Requested listing does not belong to the asset.")

    eligible: list[tuple[int, ListingSelectionCandidate]] = []
    for candidate in candidates:
        if candidate.asset_id != expected_asset_id or candidate.asset_type is not asset_type:
            continue
        currency = _currency(candidate.currency)
        provider_symbol = _nonblank(candidate.provider_symbol)
        if getattr(candidate.provider, "value", None) not in PriceSource._value2member_map_:
            continue
        if type(candidate.base_priority) is not int or candidate.base_priority < 0:
            raise ListingSelectionError("Listing selection input is invalid.")
        if candidate.mic is not None:
            _nonblank(candidate.mic)
        if not candidate.price_available and not candidate.acquisition_eligible:
            continue
        if not _valid_fx_path(
            source_currency=currency,
            target_currency=target_currency,
            through=cutoff,
            evidence=fx_evidence,
        ):
            continue
        tier = _candidate_tier(candidate, now=current)
        if tier is None:
            continue
        # Validate before placing provider-owned identity into the deterministic key.
        _ = provider_symbol
        eligible.append((tier, candidate))

    if not eligible:
        raise ListingSelectionError("No safe listing is available.")
    if any(tier == 0 for tier, _ in eligible):
        eligible = [(tier, item) for tier, item in eligible if tier == 0]
    _, selected = min(
        eligible,
        key=lambda item: (
            item[0],
            -item[1].base_priority,
            item[1].provider.value,
            item[1].provider_symbol,
            item[1].mic is None,
            item[1].mic or "",
            item[1].listing_id,
        ),
    )

    fallback_reason: ListingSelectionReason | None = None
    if selected.listing_id == requested_id:
        reason = ListingSelectionReason.requested_listing
    else:
        reason = ListingSelectionReason.higher_base_priority
        if requested is None:
            fallback_reason = ListingSelectionReason.requested_listing_incompatible
        elif requested.health is MarketDataHealthState.degraded:
            fallback_reason = ListingSelectionReason.requested_listing_degraded
        elif requested.health is MarketDataHealthState.unavailable:
            fallback_reason = ListingSelectionReason.requested_listing_unavailable
        elif (requested.retry_after is not None and requested.retry_after > current) or (
            requested.provider_retry_after is not None and requested.provider_retry_after > current
        ):
            fallback_reason = ListingSelectionReason.requested_listing_cooldown
        elif not requested.price_available and not requested.acquisition_eligible:
            fallback_reason = ListingSelectionReason.requested_price_unavailable
        elif not _valid_fx_path(
            source_currency=_currency(requested.currency),
            target_currency=target_currency,
            through=cutoff,
            evidence=fx_evidence,
        ):
            fallback_reason = ListingSelectionReason.requested_listing_incompatible
        else:
            fallback_reason = ListingSelectionReason.higher_base_priority
    return ListingSelectionResult(
        requested_listing_id=requested_id,
        selected_listing_id=selected.listing_id,
        reason=reason,
        fallback_reason=fallback_reason,
        base_priority=selected.base_priority,
        health=selected.health,
        provider=selected.provider,
        provider_symbol=selected.provider_symbol,
    )


__all__ = [
    "FxCompatibilityEvidence",
    "ListingSelectionCandidate",
    "ListingSelectionError",
    "ListingSelectionReason",
    "ListingSelectionResult",
    "select_listing",
]
