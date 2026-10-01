from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest

from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import AssetType, ExchangeRateSource, MarketDataHealthState, PriceSource
from app.db.models.market_health import MarketDataListingHealthModel
from app.db.models.prices import ExchangeRateModel
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.modules.current_value.repository import (
    CurrentListingSelectionContext,
    CurrentValueRepository,
)
from app.modules.current_value.service import (
    CurrentValueUnavailableError,
    _deduplicate_selected_requirements,
    _same_market_plan_identity,
    _select_current_price_requirement,
    _validate_baseline_market_evidence,
)
from app.modules.market_data.models import MarketEvidenceRefreshPlan
from app.modules.market_data.source_policy import (
    CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
)
from app.modules.portfolio_snapshot.models import PortfolioSnapshotView


class _Repository:
    def __init__(
        self,
        *,
        items: tuple[tuple[AccountSnapshotItemModel, AssetModel], ...] = (),
        rates: tuple[ExchangeRateModel, ...] = (),
    ) -> None:
        self.items = items
        self.rates = rates

    async def load_snapshot_items_with_assets(
        self,
        snapshot_ids: tuple[str, ...],
    ) -> tuple[tuple[AccountSnapshotItemModel, AssetModel], ...]:
        assert snapshot_ids
        return self.items

    async def load_exchange_rates_by_ids(
        self,
        rate_ids: tuple[str, ...],
    ) -> tuple[ExchangeRateModel, ...]:
        assert tuple(sorted(rate.id for rate in self.rates)) == rate_ids
        return self.rates


def _view(snapshot_id: str, *, positions: int) -> PortfolioSnapshotView:
    return cast(
        PortfolioSnapshotView,
        SimpleNamespace(snapshot_id=snapshot_id, positions=tuple(range(positions))),
    )


def _empty_audit() -> dict[str, object]:
    return {"version": 1, "snapshotRates": [], "historicalRateIds": []}


NOW = datetime(2026, 9, 30, 12)


def _listing(
    listing_id: str, *, asset_id: str = "asset", currency: str = "EUR", priority: int = 1
) -> AssetListingModel:
    return AssetListingModel(
        id=listing_id,
        asset_id=asset_id,
        symbol="AAA",
        currency=currency,
        provider=PriceSource.twelve_data,
        provider_symbol=f"AAA:{listing_id}",
        base_priority=priority,
    )


def _selection_context(
    *, requested_state: MarketDataHealthState, retry_after: datetime | None = None
) -> CurrentListingSelectionContext:
    return CurrentListingSelectionContext(
        requested_listing=_listing("preferred", priority=10),
        asset=AssetModel(id="asset", symbol="AAA", asset_type=AssetType.stock, currency="EUR"),
        candidate_listings=(
            _listing("preferred", priority=10),
            _listing("fallback", priority=5),
            _listing("other-asset", asset_id="other", priority=100),
            _listing("other-currency", currency="USD", priority=100),
        ),
        aliases=(),
        health=(
            cast(
                MarketDataListingHealthModel,
                SimpleNamespace(
                    listing_id="preferred",
                    provider=PriceSource.twelve_data,
                    provider_symbol="AAA:preferred",
                    state=requested_state,
                    retry_after=retry_after,
                    lease_expires_at=None,
                ),
            ),
        ),
        provider_retry_after=(),
    )


@pytest.mark.parametrize(
    ("state", "retry_after", "selected", "reason"),
    (
        (MarketDataHealthState.degraded, None, "fallback", "requested_listing_degraded"),
        (
            MarketDataHealthState.healthy,
            NOW + timedelta(minutes=5),
            "fallback",
            "requested_listing_cooldown",
        ),
        (MarketDataHealthState.healthy, None, "preferred", None),
    ),
)
def test_current_price_requirement_uses_safe_listing_fallback(
    state: MarketDataHealthState,
    retry_after: datetime | None,
    selected: str,
    reason: str | None,
) -> None:
    requirement = _select_current_price_requirement(
        context=_selection_context(requested_state=state, retry_after=retry_after),
        account_id="account",
        existing_prices=(),
        as_of=NOW,
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    )
    assert requirement.requested_listing_id == "preferred"
    assert requirement.listing_id == selected
    assert requirement.fallback_reason == reason
    assert requirement.provider_symbol == f"AAA:{selected}"
    assert requirement.listing_currency == "EUR"


def test_current_plan_pins_selected_listing_across_health_refresh() -> None:
    requirement = _select_current_price_requirement(
        context=_selection_context(requested_state=MarketDataHealthState.degraded),
        account_id="account",
        existing_prices=(),
        as_of=NOW,
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    )
    plan = MarketEvidenceRefreshPlan(
        user_id="user",
        output_currency="EUR",
        snapshot_timestamp=NOW,
        price_requirements=(requirement,),
        fx_requirements=(),
    )
    updated = replace(
        plan,
        price_requirements=(replace(requirement, selected_health="healthy"),),
    )
    changed_listing = replace(
        plan,
        price_requirements=(replace(requirement, listing_id="preferred"),),
    )
    assert _same_market_plan_identity(plan, updated)
    assert not _same_market_plan_identity(plan, changed_listing)


def test_current_plan_acquires_one_price_for_two_requested_listings() -> None:
    first = _select_current_price_requirement(
        context=_selection_context(requested_state=MarketDataHealthState.degraded),
        account_id="account-a",
        existing_prices=(),
        as_of=NOW,
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    )
    second = replace(first, account_id="account-b", requested_listing_id="other-requested")
    assert _deduplicate_selected_requirements((first, second)) == (first,)
    with pytest.raises(CurrentValueUnavailableError):
        _deduplicate_selected_requirements(
            (first, replace(second, provider_symbol="different-provider-identity"))
        )


@pytest.mark.asyncio
async def test_canonical_price_baseline_cannot_be_reused_under_local_free_policy() -> None:
    snapshot = AccountSnapshotModel(id="canonical-price", exchange_rates=_empty_audit())
    item = AccountSnapshotItemModel(
        id="canonical-price-item",
        snapshot_id=snapshot.id,
        asset_id="listed-asset",
        price_source=PriceSource.twelve_data,
    )
    asset = AssetModel(id="listed-asset", asset_type=AssetType.etf)

    with pytest.raises(CurrentValueUnavailableError):
        await _validate_baseline_market_evidence(
            cast(CurrentValueRepository, _Repository(items=((item, asset),))),
            primary=_view(snapshot.id, positions=1),
            presentation=_view(snapshot.id, positions=1),
            primary_snapshot=snapshot,
            presentation_snapshot=snapshot,
            source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
        )


@pytest.mark.asyncio
async def test_local_free_mixed_currency_fx_baseline_cannot_be_reused_under_canonical_policy() -> (
    None
):
    primary = AccountSnapshotModel(
        id="local-free-czk",
        exchange_rates={
            "version": 1,
            "snapshotRates": [
                {
                    "rateId": "yahoo-eur-czk",
                    "from": "EUR",
                    "to": "CZK",
                    "source": "yahoo_finance",
                }
            ],
            "historicalRateIds": [],
        },
    )
    presentation = AccountSnapshotModel(id="local-free-eur", exchange_rates=_empty_audit())
    rate = ExchangeRateModel(
        id="yahoo-eur-czk",
        source=ExchangeRateSource.yahoo_finance,
    )

    with pytest.raises(CurrentValueUnavailableError):
        await _validate_baseline_market_evidence(
            cast(CurrentValueRepository, _Repository(rates=(rate,))),
            primary=_view(primary.id, positions=0),
            presentation=_view(presentation.id, positions=0),
            primary_snapshot=primary,
            presentation_snapshot=presentation,
            source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        )


@pytest.mark.asyncio
async def test_historical_fx_provenance_must_match_the_active_policy() -> None:
    snapshot = AccountSnapshotModel(
        id="canonical-historical",
        exchange_rates={
            "version": 1,
            "snapshotRates": [],
            "historicalRateIds": ["yahoo-historical-rate"],
        },
    )
    rate = ExchangeRateModel(
        id="yahoo-historical-rate",
        source=ExchangeRateSource.yahoo_finance,
    )

    with pytest.raises(CurrentValueUnavailableError):
        await _validate_baseline_market_evidence(
            cast(CurrentValueRepository, _Repository(rates=(rate,))),
            primary=_view(snapshot.id, positions=0),
            presentation=_view(snapshot.id, positions=0),
            primary_snapshot=snapshot,
            presentation_snapshot=snapshot,
            source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        )
