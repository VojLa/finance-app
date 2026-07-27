from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.db.models.enums import (
    AssetType,
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.modules.holdings.persistence_projection import (
    ExpectedPersistedHoldingPlan,
    HoldingPersistenceEvent,
    HoldingPersistenceMovement,
    HoldingPersistenceProjection,
    build_holding_persistence_projection,
)
from app.modules.holdings.projection import HoldingProjectionStateError
from app.modules.imports.anycoin import AnycoinBatchRow, normalize_anycoin_batch
from app.modules.imports.classification import InvestmentEventPostingIntent, classify_import_row
from app.modules.imports.investment_posting_plan import (
    InvestmentEventPostingPlan,
    build_investment_posting_plan,
)
from app.modules.imports.normalizers import normalize_import_row


def _asset(
    event_id: str,
    *,
    direction: MovementDirection,
    quantity: Decimal,
    price: Decimal | None,
    value: Decimal | None,
    value_currency: str | None = "EUR",
    listing_id: str = "listing",
    asset_id: str = "asset",
    symbol: str = "VWCE",
    asset_type: AssetType = AssetType.etf,
) -> HoldingPersistenceMovement:
    return HoldingPersistenceMovement(
        movement_id=f"{event_id}-asset",
        event_id=event_id,
        account_id="account",
        kind=InvestmentMovementKind.asset,
        direction=direction,
        quantity=quantity,
        currency=symbol,
        asset_id=asset_id,
        listing_id=listing_id,
        listing_asset_id=asset_id,
        source_symbol=symbol,
        source_asset_type=asset_type,
        price_per_unit=price,
        value_amount=value,
        value_currency=value_currency,
    )


def _cash(
    event_id: str,
    *,
    direction: MovementDirection,
    amount: Decimal,
    currency: str = "EUR",
    linked: bool = False,
) -> HoldingPersistenceMovement:
    return HoldingPersistenceMovement(
        movement_id=f"{event_id}-cash-{direction.value}",
        event_id=event_id,
        account_id="account",
        kind=InvestmentMovementKind.cash,
        direction=direction,
        quantity=amount,
        currency=currency,
        asset_id="asset" if linked else None,
        listing_id="listing" if linked else None,
        listing_asset_id="asset" if linked else None,
        source_symbol="VWCE" if linked else None,
        source_asset_type=AssetType.etf if linked else None,
        price_per_unit=None,
        value_amount=amount,
        value_currency=currency,
    )


def _fee(event_id: str, amount: Decimal = Decimal("1")) -> HoldingPersistenceMovement:
    return HoldingPersistenceMovement(
        movement_id=f"{event_id}-fee",
        event_id=event_id,
        account_id="account",
        kind=InvestmentMovementKind.fee,
        direction=MovementDirection.outgoing,
        quantity=amount,
        currency="EUR",
        asset_id=None,
        listing_id=None,
        listing_asset_id=None,
        source_symbol=None,
        source_asset_type=None,
        price_per_unit=None,
        value_amount=amount,
        value_currency="EUR",
    )


def _event(
    event_id: str,
    event_type: InvestmentEventType,
    movements: tuple[HoldingPersistenceMovement, ...],
    *,
    date: datetime,
) -> HoldingPersistenceEvent:
    return HoldingPersistenceEvent(
        event_id=event_id,
        account_id="account",
        event_type=event_type,
        event_date=date,
        external_id=f"external-{event_id}",
        movements=movements,
    )


def _buy(
    event_id: str,
    quantity: str,
    price: str,
    *,
    date: datetime,
    currency: str = "EUR",
    listing_id: str = "listing",
    asset_id: str = "asset",
    symbol: str = "VWCE",
) -> HoldingPersistenceEvent:
    qty, unit = Decimal(quantity), Decimal(price)
    value = qty * unit
    asset = _asset(
        event_id,
        direction=MovementDirection.incoming,
        quantity=qty,
        price=unit,
        value=value,
        value_currency=currency,
        listing_id=listing_id,
        asset_id=asset_id,
        symbol=symbol,
        asset_type=AssetType.crypto if symbol == "BTC" else AssetType.etf,
    )
    return _event(
        event_id,
        InvestmentEventType.trade,
        (
            asset,
            _cash(
                event_id,
                direction=MovementDirection.outgoing,
                amount=value,
                currency=currency,
            ),
        ),
        date=date,
    )


def _sell(
    event_id: str,
    quantity: str,
    price: str,
    *,
    date: datetime,
) -> HoldingPersistenceEvent:
    qty, unit = Decimal(quantity), Decimal(price)
    value = qty * unit
    return _event(
        event_id,
        InvestmentEventType.trade,
        (
            _asset(
                event_id,
                direction=MovementDirection.outgoing,
                quantity=qty,
                price=unit,
                value=value,
            ),
            _cash(
                event_id,
                direction=MovementDirection.incoming,
                amount=value,
            ),
        ),
        date=date,
    )


def _project(*events: HoldingPersistenceEvent) -> HoldingPersistenceProjection:
    return build_holding_persistence_projection(account_id="account", events=events)


def test_one_buy_produces_every_non_temporal_holding_field() -> None:
    assert _project(_buy("buy", "2", "100.5", date=datetime(2026, 7, 20))) == (
        HoldingPersistenceProjection(
            account_id="account",
            holdings=(
                ExpectedPersistedHoldingPlan(
                    account_id="account",
                    asset_id="asset",
                    listing_id="listing",
                    symbol="VWCE",
                    name=None,
                    asset_type=AssetType.etf,
                    quantity=Decimal("2"),
                    avg_buy_price=Decimal("100.5"),
                    currency="EUR",
                    current_price=None,
                    current_value=None,
                    unrealized_pnl=None,
                    realized_pnl=None,
                ),
            ),
        )
    )


def test_multiple_equal_and_different_buys_use_exact_weighted_average() -> None:
    equal = _project(
        _buy("a", "1", "100", date=datetime(2026, 7, 20)),
        _buy("b", "2", "100", date=datetime(2026, 7, 21)),
    )
    weighted = _project(
        _buy("a", "1", "100", date=datetime(2026, 7, 20)),
        _buy("b", "3", "200", date=datetime(2026, 7, 21)),
    )
    assert equal.holdings[0].avg_buy_price == Decimal("100")
    assert weighted.holdings[0].quantity == Decimal("4")
    assert weighted.holdings[0].avg_buy_price == Decimal("175")


def test_fractional_acquisition_and_multiple_listings_remain_exact_and_separate() -> None:
    result = _project(
        _buy("a", "0.125", "80", date=datetime(2026, 7, 20)),
        _buy(
            "b",
            "0.5",
            "50",
            date=datetime(2026, 7, 21),
            listing_id="listing-b",
            asset_id="asset-b",
            symbol="BTC",
        ),
    )
    assert [(item.listing_id, item.quantity, item.avg_buy_price) for item in result.holdings] == [
        ("listing", Decimal("0.125"), Decimal("80")),
        ("listing-b", Decimal("0.5"), Decimal("50")),
    ]


def test_same_asset_on_different_listings_is_not_merged() -> None:
    result = _project(
        _buy("a", "1", "100", date=datetime(2026, 7, 20)),
        _buy(
            "b",
            "2",
            "110",
            date=datetime(2026, 7, 21),
            listing_id="listing-b",
        ),
    )
    assert [(item.asset_id, item.listing_id, item.quantity) for item in result.holdings] == [
        ("asset", "listing", Decimal("1")),
        ("asset", "listing-b", Decimal("2")),
    ]


def test_partial_sale_preserves_average_and_sale_price_is_irrelevant() -> None:
    result = _project(
        _buy("a", "1", "100", date=datetime(2026, 7, 20)),
        _buy("b", "3", "200", date=datetime(2026, 7, 21)),
        _sell("c", "2", "999", date=datetime(2026, 7, 22)),
    )
    assert result.holdings[0].quantity == Decimal("2")
    assert result.holdings[0].avg_buy_price == Decimal("175")


def test_full_sale_removes_holding() -> None:
    assert (
        _project(
            _buy("buy", "2", "100", date=datetime(2026, 7, 20)),
            _sell("sell", "2", "120", date=datetime(2026, 7, 21)),
        ).holdings
        == ()
    )


@pytest.mark.parametrize(
    "events",
    [
        (
            _sell("sell", "1", "100", date=datetime(2026, 7, 20)),
            _buy("buy", "1", "100", date=datetime(2026, 7, 21)),
        ),
        (
            _buy("buy", "1", "100", date=datetime(2026, 7, 20)),
            _sell("sell", "2", "100", date=datetime(2026, 7, 21)),
        ),
    ],
)
def test_sale_before_buy_and_oversell_fail_closed(
    events: tuple[HoldingPersistenceEvent, ...],
) -> None:
    with pytest.raises(HoldingProjectionStateError):
        _project(*events)


def test_outgoing_transfer_reduces_quantity_without_changing_average() -> None:
    transfer = _event(
        "transfer",
        InvestmentEventType.asset_transfer,
        (
            _asset(
                "transfer",
                direction=MovementDirection.outgoing,
                quantity=Decimal("0.4"),
                price=None,
                value=None,
                value_currency=None,
            ),
        ),
        date=datetime(2026, 7, 21),
    )
    result = _project(_buy("buy", "1", "100", date=datetime(2026, 7, 20)), transfer)
    assert result.holdings[0].quantity == Decimal("0.6")
    assert result.holdings[0].avg_buy_price == Decimal("100")


def test_exact_full_outgoing_transfer_removes_holding() -> None:
    transfer = _event(
        "transfer",
        InvestmentEventType.asset_transfer,
        (
            _asset(
                "transfer",
                direction=MovementDirection.outgoing,
                quantity=Decimal("1"),
                price=None,
                value=None,
                value_currency=None,
            ),
        ),
        date=datetime(2026, 7, 21),
    )
    assert _project(_buy("buy", "1", "100", date=datetime(2026, 7, 20)), transfer).holdings == ()


def test_incoming_transfer_requires_exact_persisted_basis() -> None:
    missing = _event(
        "missing",
        InvestmentEventType.asset_transfer,
        (
            _asset(
                "missing",
                direction=MovementDirection.incoming,
                quantity=Decimal("1"),
                price=None,
                value=None,
                value_currency=None,
            ),
        ),
        date=datetime(2026, 7, 20),
    )
    exact = _event(
        "exact",
        InvestmentEventType.asset_transfer,
        (
            _asset(
                "exact",
                direction=MovementDirection.incoming,
                quantity=Decimal("2"),
                price=Decimal("50"),
                value=Decimal("100"),
            ),
        ),
        date=datetime(2026, 7, 20),
    )
    with pytest.raises(HoldingProjectionStateError):
        _project(missing)
    assert _project(exact).holdings[0].avg_buy_price == Decimal("50")


@pytest.mark.parametrize(
    "event_type",
    [
        InvestmentEventType.staking_reward,
        InvestmentEventType.airdrop,
        InvestmentEventType.adjustment,
    ],
)
def test_rewards_airdrops_and_adjustments_are_unsupported_basis(
    event_type: InvestmentEventType,
) -> None:
    event = _event(
        event_type.value,
        event_type,
        (
            _asset(
                event_type.value,
                direction=MovementDirection.incoming,
                quantity=Decimal("1"),
                price=Decimal("10"),
                value=Decimal("10"),
            ),
        ),
        date=datetime(2026, 7, 20),
    )
    with pytest.raises(HoldingProjectionStateError):
        _project(event)


def test_dividend_fee_and_cash_events_do_not_change_basis() -> None:
    dividend = _event(
        "dividend",
        InvestmentEventType.dividend,
        (
            _cash(
                "dividend",
                direction=MovementDirection.incoming,
                amount=Decimal("5"),
                currency="USD",
                linked=True,
            ),
            _fee("dividend"),
        ),
        date=datetime(2026, 7, 21),
    )
    fee = _event(
        "fee",
        InvestmentEventType.fee,
        (_fee("fee"),),
        date=datetime(2026, 7, 22),
    )
    result = _project(_buy("buy", "1", "100", date=datetime(2026, 7, 20)), dividend, fee)
    assert result.holdings[0].avg_buy_price == Decimal("100")
    assert result.holdings[0].currency == "EUR"


def test_supported_cash_only_events_create_no_holding() -> None:
    events = (
        _event(
            "interest",
            InvestmentEventType.interest,
            (_cash("interest", direction=MovementDirection.incoming, amount=Decimal("2")),),
            date=datetime(2026, 7, 20),
        ),
        _event(
            "deposit",
            InvestmentEventType.cash_deposit,
            (_cash("deposit", direction=MovementDirection.incoming, amount=Decimal("20")),),
            date=datetime(2026, 7, 21),
        ),
        _event(
            "withdrawal",
            InvestmentEventType.cash_withdrawal,
            (_cash("withdrawal", direction=MovementDirection.outgoing, amount=Decimal("5")),),
            date=datetime(2026, 7, 22),
        ),
        _event(
            "conversion",
            InvestmentEventType.currency_conversion,
            (
                _cash(
                    "conversion",
                    direction=MovementDirection.outgoing,
                    amount=Decimal("10"),
                    currency="EUR",
                ),
                _cash(
                    "conversion",
                    direction=MovementDirection.incoming,
                    amount=Decimal("11"),
                    currency="USD",
                ),
            ),
            date=datetime(2026, 7, 23),
        ),
    )
    assert _project(*events).holdings == ()


def test_exact_numeric_boundary_is_accepted() -> None:
    maximum = Decimal("999999999999999999.9999999999")
    result = _project(_buy("maximum", "1", str(maximum), date=datetime(2026, 7, 20)))
    assert result.holdings[0].avg_buy_price == maximum


def test_cost_currency_is_value_currency_and_mixed_acquisitions_fail() -> None:
    first = _buy("eur", "1", "100", date=datetime(2026, 7, 20))
    second = _buy(
        "usd",
        "1",
        "110",
        date=datetime(2026, 7, 21),
        currency="USD",
    )
    assert _project(first).holdings[0].currency == "EUR"
    assert _project(first).holdings[0].currency != "VWCE"
    with pytest.raises(HoldingProjectionStateError):
        _project(first, second)


def test_input_order_does_not_change_output_and_inputs_are_immutable() -> None:
    events = (
        _buy("later", "1", "200", date=datetime(2026, 7, 21)),
        _buy("earlier", "1", "100", date=datetime(2026, 7, 20)),
    )
    before = deepcopy(events)
    assert _project(*events) == _project(*tuple(reversed(events)))
    assert events == before
    assert cast(Any, events[0]).__dataclass_params__.frozen


def test_equal_timestamps_use_event_id_order() -> None:
    first = _buy("event-b", "1", "200", date=datetime(2026, 7, 20))
    second = _buy("event-a", "1", "100", date=datetime(2026, 7, 20))
    assert _project(first, second).holdings[0].avg_buy_price == Decimal("150")
    assert _project(first, second) == _project(second, first)


def test_repeating_weighted_average_fails_without_rounding() -> None:
    with pytest.raises(HoldingProjectionStateError):
        _project(
            _buy("a", "1", "1", date=datetime(2026, 7, 20)),
            _buy("b", "2", "2", date=datetime(2026, 7, 21)),
        )


@pytest.mark.parametrize(
    "corruption",
    [
        "foreign_event",
        "foreign_movement",
        "duplicate_event",
        "duplicate_movement",
        "incomplete_trade",
        "wrong_cash_direction",
        "missing_listing",
        "listing_asset_mismatch",
        "price_float",
        "price_nan",
        "price_over_scale",
        "value_float",
        "value_overflow",
        "cash_value_mismatch",
        "fee_value_mismatch",
        "price_value_mismatch",
        "multiplication_overflow",
    ],
)
def test_corrupt_event_evidence_fails_complete_projection(corruption: str) -> None:
    event = _buy("buy", "2", "100", date=datetime(2026, 7, 20))
    asset, cash = event.movements
    events: tuple[HoldingPersistenceEvent, ...] = (event,)
    if corruption == "foreign_event":
        event = replace(event, account_id="other")
    elif corruption == "foreign_movement":
        event = replace(event, movements=(replace(asset, account_id="other"), cash))
    elif corruption == "duplicate_event":
        events = (event, event)
    elif corruption == "duplicate_movement":
        event = replace(event, movements=(asset, replace(cash, movement_id=asset.movement_id)))
    elif corruption == "incomplete_trade":
        event = replace(event, movements=(asset,))
    elif corruption == "wrong_cash_direction":
        event = replace(
            event, movements=(asset, replace(cash, direction=MovementDirection.incoming))
        )
    elif corruption == "missing_listing":
        event = replace(event, movements=(replace(asset, listing_id=None), cash))
    elif corruption == "listing_asset_mismatch":
        event = replace(event, movements=(replace(asset, listing_asset_id="other"), cash))
    elif corruption == "price_float":
        event = replace(event, movements=(replace(asset, price_per_unit=cast(Decimal, 1.5)), cash))
    elif corruption == "price_nan":
        event = replace(event, movements=(replace(asset, price_per_unit=Decimal("NaN")), cash))
    elif corruption == "price_over_scale":
        event = replace(
            event,
            movements=(replace(asset, price_per_unit=Decimal("100.00000000001")), cash),
        )
    elif corruption == "value_float":
        event = replace(
            event,
            movements=(replace(asset, value_amount=cast(Decimal, 200.0)), cash),
        )
    elif corruption == "value_overflow":
        event = replace(
            event,
            movements=(replace(asset, value_amount=Decimal("1000000000000000000")), cash),
        )
    elif corruption == "cash_value_mismatch":
        event = replace(
            event,
            movements=(asset, replace(cash, value_amount=Decimal("199"))),
        )
    elif corruption == "fee_value_mismatch":
        event = replace(
            event,
            movements=(
                asset,
                cash,
                replace(_fee(event.event_id), value_amount=Decimal("2")),
            ),
        )
    elif corruption == "price_value_mismatch":
        event = replace(event, movements=(replace(asset, value_amount=Decimal("201")), cash))
    else:
        huge = Decimal("999999999999999999.9999999999")
        event = replace(
            event,
            movements=(
                replace(asset, quantity=Decimal("2"), price_per_unit=huge, value_amount=huge),
                replace(cash, quantity=huge),
            ),
        )
    if corruption != "duplicate_event":
        events = (event,)
    with pytest.raises(HoldingProjectionStateError):
        _project(*events)


def test_aggregate_cost_overflow_fails_without_partial_projection() -> None:
    maximum = Decimal("999999999999999999.9999999999")
    with pytest.raises(HoldingProjectionStateError):
        _project(
            _buy("maximum", "1", str(maximum), date=datetime(2026, 7, 20)),
            _buy("overflow", "1", "1", date=datetime(2026, 7, 21)),
        )


def test_tax_evidence_is_unsupported_without_an_allocation_contract() -> None:
    tax = replace(_fee("tax", Decimal("1")), kind=InvestmentMovementKind.tax)
    with pytest.raises(HoldingProjectionStateError):
        _project(
            _buy("buy", "1", "100", date=datetime(2026, 7, 20)),
            _event(
                "tax",
                InvestmentEventType.fee,
                (tax,),
                date=datetime(2026, 7, 21),
            ),
        )


def _batch(source: ImportSource) -> ImportBatchModel:
    return cast(
        ImportBatchModel,
        SimpleNamespace(
            id="batch",
            account_id="account",
            source=source,
            status=ImportStatus.processing,
        ),
    )


def _plan(normalized: dict[str, Any], source: ImportSource) -> InvestmentEventPostingPlan:
    data = deepcopy(normalized)
    intent = classify_import_row(source=source, normalized_data=data)
    assert isinstance(intent, InvestmentEventPostingIntent), intent
    data["deduplication"] = {"schema_version": 1, "status": "unique"}
    data["posting_intent"] = intent.model_dump(mode="json")
    row = cast(
        ImportRowModel,
        SimpleNamespace(
            id="row",
            import_batch_id="batch",
            status=ImportRowStatus.pending,
            normalized_data=data,
            deduplication_key="key",
            validation_errors=None,
            error_message=None,
            created_transaction_id=None,
            created_investment_event_id=None,
        ),
    )
    return build_investment_posting_plan(
        account_id="account",
        batch=_batch(source),
        row=row,
    )


def _from_plan(
    plan: InvestmentEventPostingPlan,
    event_id: str,
) -> HoldingPersistenceEvent:
    movements = tuple(
        HoldingPersistenceMovement(
            movement_id=f"{event_id}-{index}",
            event_id=event_id,
            account_id="account",
            kind=movement.kind,
            direction=movement.direction,
            quantity=movement.quantity,
            currency=movement.currency,
            asset_id="provider-asset" if movement.requires_asset else None,
            listing_id="provider-listing" if movement.requires_asset else None,
            listing_asset_id="provider-asset" if movement.requires_asset else None,
            source_symbol=movement.source_symbol,
            source_asset_type=movement.source_asset_type,
            price_per_unit=movement.price_per_unit,
            value_amount=movement.value_amount,
            value_currency=movement.value_currency,
        )
        for index, movement in enumerate(plan.movements)
    )
    return HoldingPersistenceEvent(
        event_id=event_id,
        account_id="account",
        event_type=plan.event_type,
        event_date=plan.date,
        external_id=plan.external_id,
        movements=movements,
    )


def _trading(action: str, date: str, external_id: str) -> InvestmentEventPostingPlan:
    row = {
        "Action": action,
        "Time": date,
        "ISIN": "IE00B4L5Y983",
        "Ticker": "vwce",
        "Name": "Vanguard",
        "No. of shares": "2",
        "Price / share": "100",
        "Currency (Price / share)": "EUR",
        "Total": "200",
        "Currency (Total)": "EUR",
        "ID": external_id,
    }
    normalized = normalize_import_row(
        source=ImportSource.trading212,
        account_id="account",
        raw_data=row,
    )
    assert normalized.data is not None, normalized.validation_errors
    return _plan(normalized.data, ImportSource.trading212)


def _anycoin_row(
    row_id: str,
    number: int,
    kind: str,
    amount: str,
    currency: str,
    date: str,
    *,
    order_id: str = "order",
) -> AnycoinBatchRow:
    return AnycoinBatchRow(
        row_id=row_id,
        row_number=number,
        raw_data={
            "Type": kind,
            "Order ID": order_id,
            "Date": date,
            "Amount": amount,
            "Currency": currency,
            "anycoin TX ID": f"external-{row_id}",
        },
    )


def test_actual_trading212_buy_and_sell_plans_project_exactly() -> None:
    buy = _from_plan(_trading("Market buy", "2026-07-20T10:00:00Z", "buy"), "buy")
    sell = _from_plan(_trading("Market sell", "2026-07-21T10:00:00Z", "sell"), "sell")
    assert _project(buy, sell).holdings == ()


def test_actual_anycoin_grouped_trade_and_outgoing_transfer_project_exactly() -> None:
    outcomes = normalize_anycoin_batch(
        account_id="account",
        rows=[
            _anycoin_row("payment", 1, "trade payment", "-500", "EUR", "2026-07-20T10:00:00Z"),
            _anycoin_row("fill", 2, "trade fill", "0.01", "BTC", "2026-07-20T10:00:00Z"),
        ],
    )
    anchor = next(item for item in outcomes if item.status is ImportRowStatus.pending)
    assert anchor.data is not None
    buy = _from_plan(_plan(anchor.data, ImportSource.anycoin), "grouped")
    withdrawal = normalize_anycoin_batch(
        account_id="account",
        rows=[
            _anycoin_row(
                "withdrawal",
                1,
                "withdrawal",
                "-0.005",
                "BTC",
                "2026-07-21T10:00:00Z",
                order_id="",
            )
        ],
    )[0]
    assert withdrawal.data is not None
    outgoing = _from_plan(_plan(withdrawal.data, ImportSource.anycoin), "outgoing")
    result = _project(buy, outgoing)
    assert result.holdings[0].quantity == Decimal("0.005")
    assert result.holdings[0].avg_buy_price == Decimal("50000")
    assert result.holdings[0].currency == "EUR"


def test_actual_anycoin_incoming_transfer_fails_without_basis() -> None:
    outcome = normalize_anycoin_batch(
        account_id="account",
        rows=[
            _anycoin_row(
                "deposit",
                1,
                "deposit",
                "0.5",
                "BTC",
                "2026-07-20T10:00:00Z",
                order_id="",
            )
        ],
    )[0]
    assert outcome.data is not None
    with pytest.raises(HoldingProjectionStateError):
        _project(_from_plan(_plan(outcome.data, ImportSource.anycoin), "incoming"))
