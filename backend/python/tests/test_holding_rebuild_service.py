from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AssetType,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.modules.holdings.persistence_projection import ExpectedPersistedHoldingPlan
from app.modules.holdings.rebuild_service import (
    CurrentHoldingState,
    HoldingCreatePlan,
    HoldingRebuildPlan,
    HoldingRebuildService,
    HoldingRebuildStateError,
    adapt_persisted_history,
    build_holding_rebuild_plan,
    stable_holding_id,
    validate_current_holdings,
)
from app.modules.holdings.repository import (
    advisory_lock_id,
    canonical_history_lock_scopes,
    holdings_rebuild_lock_scope,
)

NOW = datetime(2026, 7, 27, 10, 0, 0, 123000)


def _expected(
    *,
    listing_id: str = "listing",
    asset_id: str = "asset",
    quantity: str = "2",
    average: str = "100",
    currency: str = "EUR",
) -> ExpectedPersistedHoldingPlan:
    return ExpectedPersistedHoldingPlan(
        account_id="account",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        name=None,
        asset_type=AssetType.etf,
        quantity=Decimal(quantity),
        avg_buy_price=Decimal(average),
        currency=currency,
        current_price=None,
        current_value=None,
        unrealized_pnl=None,
        realized_pnl=None,
    )


def _current(
    *,
    holding_id: str = "holding",
    listing_id: str = "listing",
    asset_id: str = "asset",
    quantity: str = "2",
    average: str = "100",
    current_price: Decimal | None = None,
) -> CurrentHoldingState:
    return CurrentHoldingState(
        holding_id=holding_id,
        account_id="account",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        name=None,
        asset_type=AssetType.etf,
        quantity=Decimal(quantity),
        avg_buy_price=Decimal(average),
        currency="EUR",
        current_price=current_price,
        current_value=None,
        unrealized_pnl=None,
        realized_pnl=None,
        calculated_at=NOW,
        updated_at=NOW,
    )


def _asset_models() -> tuple[AssetModel, AssetListingModel]:
    asset = cast(
        AssetModel,
        SimpleNamespace(id="asset", symbol="VWCE", asset_type=AssetType.etf),
    )
    listing = cast(
        AssetListingModel,
        SimpleNamespace(id="listing", asset_id="asset", symbol="VWCE"),
    )
    return asset, listing


def _event_models() -> tuple[
    InvestmentEventModel, InvestmentMovementModel, InvestmentMovementModel
]:
    event = cast(
        InvestmentEventModel,
        SimpleNamespace(
            id="event",
            account_id="account",
            type=InvestmentEventType.trade,
            date=NOW,
            external_id="external",
            archived_at=None,
            deleted_at=None,
        ),
    )
    asset = cast(
        InvestmentMovementModel,
        SimpleNamespace(
            id="movement-asset",
            event_id="event",
            account_id="account",
            kind=InvestmentMovementKind.asset,
            direction=MovementDirection.incoming,
            quantity=Decimal("2"),
            currency="VWCE",
            asset_id="asset",
            listing_id="listing",
            source_symbol="VWCE",
            source_asset_type=AssetType.etf,
            price_per_unit=Decimal("100"),
            value_amount=Decimal("200"),
            value_currency="EUR",
        ),
    )
    cash = cast(
        InvestmentMovementModel,
        SimpleNamespace(
            id="movement-cash",
            event_id="event",
            account_id="account",
            kind=InvestmentMovementKind.cash,
            direction=MovementDirection.outgoing,
            quantity=Decimal("200"),
            currency="EUR",
            asset_id=None,
            listing_id=None,
            source_symbol=None,
            source_asset_type=None,
            price_per_unit=None,
            value_amount=Decimal("200"),
            value_currency="EUR",
        ),
    )
    return event, asset, cash


def test_lock_namespaces_are_stable_account_scoped_and_source_compatible() -> None:
    assert holdings_rebuild_lock_scope("account") == "holdings:rebuild:account"
    scopes = canonical_history_lock_scopes("account")
    assert scopes == tuple(sorted(scopes))
    assert len(scopes) == 4
    assert "imports:deduplication:account:trading212" in scopes
    assert advisory_lock_id(scopes[0]) == advisory_lock_id(scopes[0])
    assert advisory_lock_id(holdings_rebuild_lock_scope("a")) != advisory_lock_id(
        holdings_rebuild_lock_scope("b")
    )


def test_stable_holding_id_is_deterministic_and_listing_scoped() -> None:
    first = stable_holding_id("account", "listing")
    assert first == stable_holding_id("account", "listing")
    assert first != stable_holding_id("account", "other")
    assert first != stable_holding_id("other", "listing")


@pytest.mark.parametrize(
    "account_id,listing_id", [("", "listing"), (" account", "listing"), ("a", "")]
)
def test_stable_holding_id_rejects_blank_identity(account_id: str, listing_id: str) -> None:
    with pytest.raises(HoldingRebuildStateError):
        stable_holding_id(account_id, listing_id)


def test_adapter_uses_persisted_join_evidence_and_is_deterministic() -> None:
    asset_model, listing_model = _asset_models()
    event, asset, cash = _event_models()
    result = adapt_persisted_history(
        account_id="account",
        events=[event],
        movements=[cash, asset],
        listings={"listing": listing_model},
        assets={"asset": asset_model},
    )
    assert [movement.movement_id for movement in result[0].movements] == [
        "movement-asset",
        "movement-cash",
    ]
    linked = next(item for item in result[0].movements if item.asset_id)
    assert linked.listing_asset_id == "asset"


@pytest.mark.parametrize(
    "corruption",
    [
        "foreign_account",
        "missing_listing",
        "missing_asset",
        "listing_asset",
        "asset_type",
        "symbol",
    ],
)
def test_adapter_rejects_persisted_relation_corruption(corruption: str) -> None:
    asset_model, listing_model = _asset_models()
    event, asset, cash = _event_models()
    if corruption == "foreign_account":
        asset.account_id = "other"
    elif corruption == "missing_listing":
        listing_model = cast(AssetListingModel, None)
    elif corruption == "missing_asset":
        asset_model = cast(AssetModel, None)
    elif corruption == "listing_asset":
        listing_model.asset_id = "other"
    elif corruption == "asset_type":
        asset_model.asset_type = AssetType.stock
    else:
        listing_model.symbol = "OTHER"
    with pytest.raises(HoldingRebuildStateError):
        adapt_persisted_history(
            account_id="account",
            events=[event],
            movements=[asset, cash],
            listings={} if listing_model is None else {"listing": listing_model},
            assets={} if asset_model is None else {"asset": asset_model},
        )


def test_diff_plan_classifies_create_update_delete_and_orders_by_listing() -> None:
    expected = (
        _expected(listing_id="c", asset_id="asset-c"),
        _expected(listing_id="a", asset_id="asset-a"),
    )
    current = (
        _current(holding_id="delete", listing_id="z", asset_id="asset-z"),
        _current(holding_id="update", listing_id="c", asset_id="asset-c", quantity="1"),
    )
    plan = build_holding_rebuild_plan(
        account_id="account",
        expected=expected,
        current=current,
        rebuilt_at=NOW,
    )
    assert [item.expected.listing_id for item in plan.creates] == ["a"]
    assert [item.expected.listing_id for item in plan.updates] == ["c"]
    assert [item.listing_id for item in plan.deletes] == ["z"]
    assert plan.updates[0].holding_id == "update"


def test_exact_current_projection_is_read_only_replay_plan() -> None:
    plan = build_holding_rebuild_plan(
        account_id="account",
        expected=(_expected(),),
        current=(_current(),),
        rebuilt_at=NOW,
    )
    assert plan == HoldingRebuildPlan("account", (), (), ())


def test_stale_nullable_valuation_requires_exact_update_and_preserves_id() -> None:
    plan = build_holding_rebuild_plan(
        account_id="account",
        expected=(_expected(),),
        current=(_current(current_price=Decimal("123")),),
        rebuilt_at=NOW,
    )
    assert plan.updates[0].holding_id == "holding"
    assert plan.updates[0].expected.current_price is None


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 7, 27, 10, 0, 0, 1),
        datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
    ],
)
def test_diff_plan_rejects_nonrepresentable_timestamp(timestamp: datetime) -> None:
    with pytest.raises(HoldingRebuildStateError):
        build_holding_rebuild_plan(
            account_id="account",
            expected=(),
            current=(),
            rebuilt_at=timestamp,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("quantity", Decimal("NaN")),
        ("quantity", Decimal("0")),
        ("avg_buy_price", Decimal("0.00000000001")),
        ("currency", "eur"),
        ("asset_id", ""),
        ("calculated_at", datetime(2026, 7, 27, 10, 0, 0, 1)),
    ],
)
def test_current_holding_corruption_fails_closed(field: str, value: object) -> None:
    asset, listing = _asset_models()
    values: dict[str, Any] = {
        "id": "holding",
        "account_id": "account",
        "asset_id": "asset",
        "listing_id": "listing",
        "symbol": "VWCE",
        "name": None,
        "asset_type": AssetType.etf,
        "quantity": Decimal("2"),
        "avg_buy_price": Decimal("100"),
        "currency": "EUR",
        "current_price": None,
        "current_value": None,
        "unrealized_pnl": None,
        "realized_pnl": None,
        "calculated_at": NOW,
        "updated_at": NOW,
    }
    values[field] = value
    holding = cast(HoldingModel, SimpleNamespace(**values))
    with pytest.raises(HoldingRebuildStateError):
        validate_current_holdings(
            account_id="account",
            holdings=[holding],
            listings={"listing": listing},
            assets={"asset": asset},
        )


async def test_empty_exact_rebuild_is_replay_and_service_owns_no_transaction() -> None:
    commit = Mock()
    rollback = Mock()
    begin = Mock()
    session = cast(
        AsyncSession,
        SimpleNamespace(commit=commit, rollback=rollback, begin=begin),
    )
    service = HoldingRebuildService(session)
    repository = SimpleNamespace(
        lock_rebuild_scope=AsyncMock(),
        lock_canonical_history_scopes=AsyncMock(),
        load_active_events_for_update=AsyncMock(return_value=[]),
        load_active_account_movements_for_update=AsyncMock(return_value=[]),
        lock_account_holdings=AsyncMock(return_value=[]),
        load_listings_for_update=AsyncMock(return_value=[]),
        load_assets_for_update=AsyncMock(return_value=[]),
        load_holdings_by_ids_for_update=AsyncMock(return_value=[]),
        flush=AsyncMock(),
    )
    service.repository = cast(Any, repository)
    result = await service.rebuild(account_id="account", rebuilt_at=NOW)
    assert result.replayed is True
    assert result.rebuilt_at is None
    repository.flush.assert_not_awaited()
    commit.assert_not_called()
    rollback.assert_not_called()
    begin.assert_not_called()


def test_plans_and_result_contracts_are_frozen() -> None:
    plan = HoldingCreatePlan(stable_holding_id("account", "listing"), _expected(), NOW)
    with pytest.raises(FrozenInstanceError):
        cast(Any, plan).holding_id = "other"
