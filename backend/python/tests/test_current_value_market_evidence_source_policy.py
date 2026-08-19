from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.db.models.assets import AssetModel
from app.db.models.enums import AssetType, ExchangeRateSource, PriceSource
from app.db.models.prices import ExchangeRateModel
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.modules.current_value.repository import CurrentValueRepository
from app.modules.current_value.service import (
    CurrentValueUnavailableError,
    _validate_baseline_market_evidence,
)
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
