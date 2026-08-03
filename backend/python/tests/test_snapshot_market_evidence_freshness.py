from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountType,
    AssetType,
    ExchangeRateSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.modules.snapshots.evidence_repository import (
    AccountSnapshotEvidenceRepository,
    PersistedHoldingEvidence,
)
from app.modules.snapshots.evidence_service import (
    AccountSnapshotEvidenceService,
    BuildAccountSnapshotEvidenceCommand,
    ExactSnapshotMetric,
)
from app.modules.snapshots.financial_metrics import AccountSnapshotEvidenceStateError

NOW = datetime(2026, 8, 3)
EVENT_AT = NOW - timedelta(days=10)


def _account() -> AccountModel:
    return AccountModel(
        id="account-1",
        name="Broker",
        type=AccountType.broker,
        currency="EUR",
        is_archived=False,
        archived_at=None,
        updated_at=NOW,
    )


def _holding() -> tuple[PersistedHoldingEvidence, ...]:
    asset = AssetModel(
        id="asset-1",
        symbol="EXACT",
        isin=None,
        name="Exact",
        asset_type=AssetType.etf,
        currency="EUR",
        updated_at=NOW,
    )
    listing = AssetListingModel(
        id="listing-1",
        asset_id=asset.id,
        symbol="EXACT",
        exchange="XETR",
        mic=None,
        currency="EUR",
        country=None,
        provider=PriceSource.yahoo_finance,
        provider_symbol="EXACT",
        is_primary=False,
        updated_at=NOW,
    )
    holding = HoldingModel(
        id="holding-1",
        symbol="EXACT",
        name="Exact",
        asset_type=AssetType.etf,
        quantity=Decimal("2"),
        avg_buy_price=Decimal("100"),
        currency="EUR",
        current_price=None,
        current_value=None,
        unrealized_pnl=None,
        realized_pnl=None,
        asset_id=asset.id,
        listing_id=listing.id,
        account_id="account-1",
        calculated_at=NOW,
        updated_at=NOW,
    )
    return (PersistedHoldingEvidence(holding, listing, asset),)


def _price(timestamp: datetime) -> PriceSnapshotModel:
    return PriceSnapshotModel(
        id=f"price-{timestamp.isoformat()}",
        asset_id="asset-1",
        listing_id="listing-1",
        price=Decimal("110"),
        currency="EUR",
        source=PriceSource.yahoo_finance,
        timestamp=timestamp,
    )


def _rate(timestamp: datetime, rate_id: str) -> ExchangeRateModel:
    return ExchangeRateModel(
        id=rate_id,
        from_currency="EUR",
        to_currency="CZK",
        rate=Decimal("25"),
        date=timestamp,
        source=ExchangeRateSource.ecb,
    )


def _event() -> InvestmentEventModel:
    return InvestmentEventModel(
        id="event-1",
        account_id="account-1",
        type=InvestmentEventType.cash_deposit,
        date=EVENT_AT,
        source=None,
        external_id=None,
        order_id=None,
        description=None,
        realized_pnl=None,
        realized_pnl_currency=None,
        import_batch_id=None,
        archived_at=None,
        deleted_at=None,
        updated_at=NOW,
    )


def _movement() -> InvestmentMovementModel:
    return InvestmentMovementModel(
        id="movement-1",
        event_id="event-1",
        account_id="account-1",
        asset_id=None,
        listing_id=None,
        kind=InvestmentMovementKind.cash,
        direction=MovementDirection.incoming,
        quantity=Decimal("100"),
        currency="EUR",
        price_per_unit=None,
        value_amount=Decimal("100"),
        value_currency="EUR",
        source_symbol=None,
        source_asset_type=None,
        note=None,
        updated_at=NOW,
    )


def _repository(
    *,
    prices: tuple[PriceSnapshotModel, ...],
    rates: tuple[ExchangeRateModel, ...] = (),
    historical: bool = False,
) -> AccountSnapshotEvidenceRepository:
    values = {
        "load_account": _account(),
        "load_holdings": _holding(),
        "load_active_transactions": (),
        "load_active_events": (_event(),) if historical else (),
        "load_active_movements": (_movement(),) if historical else (),
        "load_price_candidates": prices,
        "load_exchange_rate_candidates": rates,
    }
    repository = SimpleNamespace()
    for name, value in values.items():
        setattr(repository, name, AsyncMock(return_value=value))
    return cast(AccountSnapshotEvidenceRepository, repository)


def _command() -> BuildAccountSnapshotEvidenceCommand:
    return BuildAccountSnapshotEvidenceCommand(
        account_id="account-1",
        snapshot_timestamp=NOW,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        output_currency="CZK",
    )


@pytest.mark.asyncio
async def test_price_exact_freshness_boundary_is_selected() -> None:
    result = await AccountSnapshotEvidenceService(
        MagicMock(),
        repository=_repository(
            prices=(_price(NOW - timedelta(hours=72)),),
            rates=(_rate(NOW - timedelta(days=7), "snapshot-rate"),),
        ),
    ).build(_command())
    assert result.selected_price_ids == (f"price-{(NOW - timedelta(hours=72)).isoformat()}",)
    assert result.selected_snapshot_exchange_rate_ids == ("snapshot-rate",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "timestamp",
    [
        NOW - timedelta(hours=72, milliseconds=1),
        NOW + timedelta(milliseconds=1),
    ],
)
async def test_stale_or_future_price_fails_closed(timestamp: datetime) -> None:
    with pytest.raises(AccountSnapshotEvidenceStateError):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=_repository(
                prices=(_price(timestamp),),
                rates=(_rate(NOW, "snapshot-rate"),),
            ),
        ).build(_command())


@pytest.mark.asyncio
async def test_stale_snapshot_time_fx_fails_closed() -> None:
    with pytest.raises(AccountSnapshotEvidenceStateError):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=_repository(
                prices=(_price(NOW),),
                rates=(
                    _rate(
                        NOW - timedelta(days=7, milliseconds=1),
                        "stale-rate",
                    ),
                ),
            ),
        ).build(_command())


@pytest.mark.asyncio
async def test_historical_metric_selects_event_date_rate_with_exact_boundary() -> None:
    historical_rate_at = EVENT_AT - timedelta(days=7)
    result = await AccountSnapshotEvidenceService(
        MagicMock(),
        repository=_repository(
            prices=(_price(NOW),),
            rates=(
                _rate(NOW, "snapshot-rate"),
                _rate(historical_rate_at, "historical-rate"),
            ),
            historical=True,
        ),
    ).build(_command())

    assert result.selected_snapshot_exchange_rate_ids == ("snapshot-rate",)
    assert result.selected_historical_exchange_rate_ids == ("historical-rate",)
    assert isinstance(result.net_deposits, ExactSnapshotMetric)
    assert result.net_deposits.value == Decimal("2500")


@pytest.mark.asyncio
async def test_rate_after_event_cannot_replace_event_date_evidence() -> None:
    with pytest.raises(AccountSnapshotEvidenceStateError):
        await AccountSnapshotEvidenceService(
            MagicMock(),
            repository=_repository(
                prices=(_price(NOW),),
                rates=(
                    _rate(NOW, "snapshot-rate"),
                    _rate(EVENT_AT + timedelta(milliseconds=1), "after-event"),
                ),
                historical=True,
            ),
        ).build(_command())
