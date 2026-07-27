from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.db.models.enums import (
    AssetType,
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    InvestmentMovementKind,
    MovementDirection,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.modules.holdings.projection import (
    ExpectedHoldingPlan,
    HoldingProjection,
    HoldingProjectionMovement,
    HoldingProjectionStateError,
    build_holding_projection,
)
from app.modules.imports.anycoin import AnycoinBatchRow, normalize_anycoin_batch
from app.modules.imports.classification import InvestmentEventPostingIntent, classify_import_row
from app.modules.imports.investment_posting_plan import (
    InvestmentEventPostingPlan,
    build_investment_posting_plan,
)
from app.modules.imports.normalizers import normalize_import_row

_DATE = datetime(2026, 7, 25, 10, 0, 0, 123000)


def _movement(
    movement_id: str,
    *,
    event_id: str | None = None,
    event_date: datetime = _DATE,
    account_id: str = "account",
    kind: InvestmentMovementKind = InvestmentMovementKind.asset,
    direction: MovementDirection = MovementDirection.incoming,
    quantity: Decimal = Decimal("1"),
    currency: str = "VWCE",
    asset_id: str | None = "asset-vwce",
    listing_id: str | None = "listing-vwce",
    listing_asset_id: str | None = "asset-vwce",
    source_symbol: str | None = "VWCE",
    source_asset_type: AssetType | None = AssetType.etf,
    linked_identity: bool = False,
) -> HoldingProjectionMovement:
    if (
        kind is not InvestmentMovementKind.asset
        and not linked_identity
        and asset_id == "asset-vwce"
    ):
        asset_id = listing_id = listing_asset_id = source_symbol = source_asset_type = None
    return HoldingProjectionMovement(
        movement_id=movement_id,
        event_id=event_id if event_id is not None else f"event-{movement_id}",
        account_id=account_id,
        event_date=event_date,
        kind=kind,
        direction=direction,
        quantity=quantity,
        currency=currency,
        asset_id=asset_id,
        listing_id=listing_id,
        listing_asset_id=listing_asset_id,
        source_symbol=source_symbol,
        source_asset_type=source_asset_type,
    )


def _projection(*movements: HoldingProjectionMovement) -> HoldingProjection:
    return build_holding_projection(account_id="account", movements=movements)


def test_one_buy_creates_one_exact_holding() -> None:
    assert _projection(_movement("buy", quantity=Decimal("2.5"))) == HoldingProjection(
        account_id="account",
        holdings=(
            ExpectedHoldingPlan(
                account_id="account",
                asset_id="asset-vwce",
                listing_id="listing-vwce",
                symbol="VWCE",
                asset_type=AssetType.etf,
                quantity=Decimal("2.5"),
            ),
        ),
    )


def test_multiple_buys_aggregate_fractional_quantity_exactly() -> None:
    result = _projection(
        _movement("buy-1", quantity=Decimal("0.1234567890")),
        _movement("buy-2", quantity=Decimal("1.0000000001")),
    )
    assert result.holdings[0].quantity == Decimal("1.1234567891")


def test_exact_maximum_quantity_is_accepted() -> None:
    maximum = Decimal("999999999999999999.9999999999")
    assert _projection(_movement("maximum", quantity=maximum)).holdings[0].quantity == maximum


def test_buy_then_partial_sell_reduces_quantity() -> None:
    result = _projection(
        _movement("buy", event_date=datetime(2026, 7, 24), quantity=Decimal("4")),
        _movement(
            "sell",
            event_date=datetime(2026, 7, 25),
            direction=MovementDirection.outgoing,
            quantity=Decimal("1.25"),
        ),
    )
    assert result.holdings[0].quantity == Decimal("2.75")


def test_exact_full_sell_omits_zero_holding() -> None:
    result = _projection(
        _movement("buy", event_date=datetime(2026, 7, 24), quantity=Decimal("2")),
        _movement(
            "sell",
            event_date=datetime(2026, 7, 25),
            direction=MovementDirection.outgoing,
            quantity=Decimal("2"),
        ),
    )
    assert result.holdings == ()


def test_multiple_assets_and_same_asset_on_different_listings_remain_separate() -> None:
    result = _projection(
        _movement("vwce-xetra"),
        _movement(
            "vwce-lse",
            listing_id="listing-vwce-lse",
            quantity=Decimal("2"),
        ),
        _movement(
            "btc",
            currency="BTC",
            asset_id="asset-btc",
            listing_id="listing-btc",
            listing_asset_id="asset-btc",
            source_symbol="BTC",
            source_asset_type=AssetType.crypto,
            quantity=Decimal("0.5"),
        ),
    )
    assert [(holding.listing_id, holding.quantity) for holding in result.holdings] == [
        ("listing-btc", Decimal("0.5")),
        ("listing-vwce", Decimal("1")),
        ("listing-vwce-lse", Decimal("2")),
    ]


def test_cash_fee_tax_and_asset_linked_dividend_cash_create_no_holding() -> None:
    result = _projection(
        _movement(
            "cash",
            kind=InvestmentMovementKind.cash,
            currency="EUR",
            quantity=Decimal("100"),
        ),
        _movement(
            "fee",
            kind=InvestmentMovementKind.fee,
            direction=MovementDirection.outgoing,
            currency="EUR",
            quantity=Decimal("1"),
        ),
        _movement(
            "tax",
            kind=InvestmentMovementKind.tax,
            direction=MovementDirection.outgoing,
            currency="EUR",
            quantity=Decimal("2"),
        ),
        _movement(
            "dividend",
            kind=InvestmentMovementKind.cash,
            currency="USD",
            quantity=Decimal("5"),
            asset_id="asset-vwce",
            listing_id="listing-vwce",
            listing_asset_id="asset-vwce",
            source_symbol="VWCE",
            source_asset_type=AssetType.etf,
            linked_identity=True,
        ),
    )
    assert result.holdings == ()


def test_repeated_and_reversed_inputs_are_structurally_equal_and_unchanged() -> None:
    movements = (
        _movement("later", event_date=datetime(2026, 7, 26), quantity=Decimal("2")),
        _movement("earlier", event_date=datetime(2026, 7, 25), quantity=Decimal("1")),
    )
    before = deepcopy(movements)
    first = _projection(*movements)
    second = _projection(*tuple(reversed(movements)))
    third = _projection(*movements)
    assert first == second == third
    assert movements == before


def test_equal_timestamps_use_event_then_movement_id_tie_breakers() -> None:
    first = _movement("z", event_id="event-b", quantity=Decimal("2"))
    second = _movement("a", event_id="event-a", quantity=Decimal("3"))
    assert _projection(first, second).holdings[0].quantity == Decimal("5")
    assert _projection(second, first) == _projection(first, second)


def test_projection_contracts_are_frozen() -> None:
    def assign(instance: object, name: str, value: object) -> None:
        setattr(instance, name, value)

    movement = _movement("buy")
    projection = _projection(movement)
    with pytest.raises(FrozenInstanceError):
        assign(movement, "quantity", Decimal("2"))
    with pytest.raises(FrozenInstanceError):
        assign(projection.holdings[0], "quantity", Decimal("2"))
    with pytest.raises(FrozenInstanceError):
        assign(projection, "account_id", "other")
    assert tuple(field.name for field in fields(projection)) == ("account_id", "holdings")


@pytest.mark.parametrize(
    "movement",
    [
        _movement("foreign", account_id="other"),
        _movement(""),
        _movement("blank-event", event_id=""),
        _movement("missing-asset", asset_id=None),
        _movement("missing-listing", listing_id=None),
        _movement("missing-listing-asset", listing_asset_id=None),
        _movement("wrong-listing-asset", listing_asset_id="asset-other"),
        _movement("missing-symbol", source_symbol=None),
        _movement("missing-type", source_asset_type=None),
        _movement("symbol-currency-conflict", currency="EUR"),
        _movement("lowercase-currency", currency="vwce"),
        _movement(
            "invalid-asset-type",
            source_asset_type=cast(AssetType, "unsupported"),
        ),
        _movement(
            "unsupported-kind",
            kind=cast(InvestmentMovementKind, "unsupported"),
        ),
        _movement(
            "unsupported-direction",
            direction=cast(MovementDirection, "sideways"),
        ),
        _movement("zero", quantity=Decimal("0")),
        _movement("negative", quantity=Decimal("-1")),
        _movement("float", quantity=cast(Decimal, 1.5)),
        _movement("non-finite", quantity=Decimal("NaN")),
        _movement("over-scale", quantity=Decimal("0.00000000001")),
        _movement("overflow", quantity=Decimal("1000000000000000000")),
        _movement(
            "sub-millisecond",
            event_date=datetime(2026, 7, 25, 10, 0, 0, 123456),
        ),
        _movement(
            "aware-date",
            event_date=datetime(2026, 7, 25, tzinfo=UTC),
        ),
        _movement(
            "incoming-fee",
            kind=InvestmentMovementKind.fee,
            direction=MovementDirection.incoming,
            currency="EUR",
        ),
        _movement(
            "linked-fee",
            kind=InvestmentMovementKind.fee,
            direction=MovementDirection.outgoing,
            currency="EUR",
            asset_id="asset-vwce",
            listing_id="listing-vwce",
            listing_asset_id="asset-vwce",
            source_symbol="VWCE",
            source_asset_type=AssetType.etf,
            linked_identity=True,
        ),
        _movement(
            "partial-linked-cash",
            kind=InvestmentMovementKind.cash,
            currency="EUR",
            asset_id="asset-vwce",
            listing_id=None,
            linked_identity=True,
        ),
    ],
)
def test_invalid_movement_contract_fails_closed(
    movement: HoldingProjectionMovement,
) -> None:
    with pytest.raises(HoldingProjectionStateError):
        _projection(movement)


def test_duplicate_movement_identity_fails_closed() -> None:
    with pytest.raises(HoldingProjectionStateError):
        _projection(_movement("same"), _movement("same"))


def test_conflicting_asset_identity_for_one_listing_fails_closed() -> None:
    with pytest.raises(HoldingProjectionStateError):
        _projection(
            _movement("first"),
            _movement(
                "second",
                asset_id="asset-other",
                listing_asset_id="asset-other",
            ),
        )


def test_final_or_intermediate_negative_holding_fails_closed() -> None:
    with pytest.raises(HoldingProjectionStateError):
        _projection(
            _movement("buy", event_date=datetime(2026, 7, 24), quantity=Decimal("1")),
            _movement(
                "sell",
                event_date=datetime(2026, 7, 25),
                direction=MovementDirection.outgoing,
                quantity=Decimal("2"),
            ),
        )
    with pytest.raises(HoldingProjectionStateError):
        _projection(
            _movement(
                "sell-first",
                event_date=datetime(2026, 7, 24),
                direction=MovementDirection.outgoing,
            ),
            _movement("buy-later", event_date=datetime(2026, 7, 25)),
        )


def test_aggregate_precision_overflow_fails_closed() -> None:
    maximum = Decimal("999999999999999999.9999999999")
    with pytest.raises(HoldingProjectionStateError):
        _projection(
            _movement("maximum", quantity=maximum),
            _movement("overflow", quantity=Decimal("0.0000000001")),
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


def _posting_plan(
    normalized: dict[str, Any],
    *,
    source: ImportSource,
) -> InvestmentEventPostingPlan:
    canonical = deepcopy(normalized)
    intent = classify_import_row(source=source, normalized_data=canonical)
    assert isinstance(intent, InvestmentEventPostingIntent), intent
    canonical["deduplication"] = {"schema_version": 1, "status": "unique"}
    canonical["posting_intent"] = intent.model_dump(mode="json")
    row = cast(
        ImportRowModel,
        SimpleNamespace(
            id="row",
            import_batch_id="batch",
            status=ImportRowStatus.pending,
            normalized_data=canonical,
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


def _persisted_movements(
    plan: InvestmentEventPostingPlan,
    *,
    event_id: str,
    asset_id: str = "asset-provider",
    listing_id: str = "listing-provider",
) -> tuple[HoldingProjectionMovement, ...]:
    return tuple(
        HoldingProjectionMovement(
            movement_id=f"{event_id}-movement-{index}",
            event_id=event_id,
            account_id=plan.account_id,
            event_date=plan.date,
            kind=movement.kind,
            direction=movement.direction,
            quantity=movement.quantity,
            currency=movement.currency,
            asset_id=asset_id if movement.requires_asset else None,
            listing_id=listing_id if movement.requires_asset else None,
            listing_asset_id=asset_id if movement.requires_asset else None,
            source_symbol=movement.source_symbol,
            source_asset_type=movement.source_asset_type,
        )
        for index, movement in enumerate(plan.movements)
    )


def _trading_row(action: str, *, date: str, external_id: str) -> dict[str, str]:
    values = {
        "Action": action,
        "Time": date,
        "ISIN": "IE00B4L5Y983",
        "Ticker": "vwce",
        "Name": "Vanguard FTSE All-World",
        "No. of shares": "2",
        "Price / share": "100.5",
        "Currency (Price / share)": "EUR",
        "Total": "201",
        "Currency (Total)": "EUR",
        "ID": external_id,
    }
    if action == "Dividend (Tax Exempted)":
        values["No. of shares"] = ""
        values["Price / share"] = ""
        values["Currency (Price / share)"] = ""
    if action in {"Currency conversion", "Spending cashback"}:
        values.update(
            {
                "ISIN": "",
                "Ticker": "",
                "Name": "",
                "No. of shares": "",
                "Price / share": "",
                "Currency (Price / share)": "",
            }
        )
    if action == "Currency conversion":
        values.update(
            {
                "Currency conversion from amount": "201",
                "Currency (Currency conversion from amount)": "EUR",
                "Currency conversion to amount": "220",
                "Currency (Currency conversion to amount)": "USD",
            }
        )
    return values


def _normalized_trading(action: str, *, date: str, external_id: str) -> dict[str, Any]:
    result = normalize_import_row(
        source=ImportSource.trading212,
        account_id="account",
        raw_data=_trading_row(action, date=date, external_id=external_id),
    )
    assert result.data is not None, result.validation_errors
    return result.data


def test_trading212_buy_sell_dividend_conversion_and_cash_only_match_b1_b3_contract() -> None:
    buy = _posting_plan(
        _normalized_trading(
            "Market buy",
            date="2026-07-23T10:00:00Z",
            external_id="buy",
        ),
        source=ImportSource.trading212,
    )
    sell = _posting_plan(
        _normalized_trading(
            "Market sell",
            date="2026-07-24T10:00:00Z",
            external_id="sell",
        ),
        source=ImportSource.trading212,
    )
    dividend = _posting_plan(
        _normalized_trading(
            "Dividend (Tax Exempted)",
            date="2026-07-25T10:00:00Z",
            external_id="dividend",
        ),
        source=ImportSource.trading212,
    )
    conversion = _posting_plan(
        _normalized_trading(
            "Currency conversion",
            date="2026-07-26T10:00:00Z",
            external_id="conversion",
        ),
        source=ImportSource.trading212,
    )
    interest = _posting_plan(
        _normalized_trading(
            "Spending cashback",
            date="2026-07-27T10:00:00Z",
            external_id="interest",
        ),
        source=ImportSource.trading212,
    )
    movements = (
        *_persisted_movements(buy, event_id="buy"),
        *_persisted_movements(sell, event_id="sell"),
        *_persisted_movements(dividend, event_id="dividend"),
        *_persisted_movements(conversion, event_id="conversion"),
        *_persisted_movements(interest, event_id="interest"),
    )
    assert _projection(*movements).holdings == ()


def _anycoin_row(
    row_id: str,
    row_number: int,
    kind: str,
    amount: str,
    currency: str,
    *,
    date: str,
    order_id: str = "order-1",
) -> AnycoinBatchRow:
    return AnycoinBatchRow(
        row_id=row_id,
        row_number=row_number,
        raw_data={
            "Type": kind,
            "Order ID": order_id,
            "Date": date,
            "Amount": amount,
            "Currency": currency,
            "anycoin TX ID": f"external-{row_id}",
        },
    )


def test_anycoin_grouped_trade_and_transfer_directions_match_b1_b3_contract() -> None:
    grouped = normalize_anycoin_batch(
        account_id="account",
        rows=[
            _anycoin_row(
                "payment",
                1,
                "trade payment",
                "-500",
                "EUR",
                date="2026-07-23T10:00:00Z",
            ),
            _anycoin_row(
                "fill",
                2,
                "trade fill",
                "0.01",
                "BTC",
                date="2026-07-23T10:00:00Z",
            ),
        ],
    )
    anchor = next(outcome for outcome in grouped if outcome.status is ImportRowStatus.pending)
    assert anchor.data is not None
    grouped_plan = _posting_plan(anchor.data, source=ImportSource.anycoin)

    incoming = normalize_anycoin_batch(
        account_id="account",
        rows=[
            _anycoin_row(
                "deposit",
                1,
                "deposit",
                "0.5",
                "BTC",
                date="2026-07-24T10:00:00Z",
                order_id="",
            )
        ],
    )[0]
    outgoing = normalize_anycoin_batch(
        account_id="account",
        rows=[
            _anycoin_row(
                "withdrawal",
                1,
                "withdrawal",
                "-0.2",
                "BTC",
                date="2026-07-25T10:00:00Z",
                order_id="",
            )
        ],
    )[0]
    assert incoming.data is not None and outgoing.data is not None
    incoming_plan = _posting_plan(incoming.data, source=ImportSource.anycoin)
    outgoing_plan = _posting_plan(outgoing.data, source=ImportSource.anycoin)
    movements = (
        *_persisted_movements(grouped_plan, event_id="grouped"),
        *_persisted_movements(incoming_plan, event_id="incoming"),
        *_persisted_movements(outgoing_plan, event_id="outgoing"),
    )
    holding = _projection(*movements).holdings[0]
    assert holding.asset_type is AssetType.crypto
    assert holding.symbol == "BTC"
    assert holding.quantity == Decimal("0.31")
