from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.db.models.common import QUANTITY
from app.db.models.enums import (
    AssetType,
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.modules.imports.anycoin import AnycoinBatchRow, normalize_anycoin_batch
from app.modules.imports.classification import (
    InvestmentEventPostingIntent,
    NeedsReviewPostingIntent,
    PostingIntentIssueCode,
    classify_import_row,
)
from app.modules.imports.investment_posting_plan import (
    InvestmentEventPostingPlan,
    build_investment_posting_plan,
)
from app.modules.imports.normalizers import normalize_import_row
from app.modules.imports.posting_common import ImportPostStateError, exact_numeric


def _batch(
    source: ImportSource = ImportSource.trading212,
    *,
    status: ImportStatus = ImportStatus.processing,
    account_id: str = "account",
) -> ImportBatchModel:
    return cast(
        ImportBatchModel,
        SimpleNamespace(
            id="batch",
            account_id=account_id,
            source=source,
            status=status,
            rows_total=1,
            rows_imported=0,
            rows_skipped=0,
            completed_at=None,
        ),
    )


def _canonical(
    action: str = "buy",
    *,
    source: ImportSource = ImportSource.trading212,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 2,
        "source": source.value,
        "kind": "investment_event",
        "date": "2026-07-25T10:00:00.123000+00:00",
        "action": action,
        "external_id": "external-1",
        "raw_action": action.replace("_", " "),
        "asset": {
            "symbol": None,
            "isin": None,
            "name": None,
            "asset_type_hint": None,
        },
        "quantity": None,
        "price": None,
        "total": None,
        "fee": None,
        "conversion": None,
        "realized_pnl": None,
        "is_promotional": False,
        "note": "provider note",
        "order_id": None,
        "asset_direction": None,
    }
    if action in {"buy", "sell"}:
        payload["asset"] = {
            "symbol": "vwce",
            "isin": "ie00b4l5y983",
            "name": "Vanguard FTSE All-World",
            "asset_type_hint": "ETF",
        }
        payload["quantity"] = "2"
        payload["price"] = {"amount": "100.5", "currency": "EUR"}
        payload["total"] = {"amount": "201", "currency": "EUR"}
        if source is ImportSource.anycoin:
            payload["asset"]["symbol"] = "btc"
            payload["asset"]["isin"] = None
            payload["asset"]["name"] = None
            payload["asset"]["asset_type_hint"] = "crypto"
            payload["order_id"] = "order-1"
    elif action == "dividend":
        payload["asset"] = {
            "symbol": "aapl",
            "isin": "us0378331005",
            "name": "Apple",
            "asset_type_hint": "stock",
        }
        payload["total"] = {"amount": "4.5", "currency": "USD"}
    elif action in {"interest", "cash_deposit", "cash_withdrawal"}:
        payload["total"] = {"amount": "50", "currency": "EUR"}
    elif action == "currency_conversion":
        payload["conversion"] = {
            "from": {"amount": "100", "currency": "EUR"},
            "to": {"amount": "110", "currency": "USD"},
            "exchange_rate": "1.1",
        }
        payload["total"] = {"amount": "100", "currency": "EUR"}
    elif action == "asset_transfer":
        payload["asset"] = {
            "symbol": "btc",
            "isin": None,
            "name": "Bitcoin",
            "asset_type_hint": "crypto",
        }
        payload["quantity"] = "0.5"
        payload["asset_direction"] = "in"
    elif action == "fee":
        payload["total"] = {"amount": "2.5", "currency": "EUR"}
    elif action in {"staking_reward", "airdrop"}:
        payload["asset"] = {
            "symbol": "eth",
            "isin": None,
            "name": "Ethereum",
            "asset_type_hint": "crypto",
        }
        payload["quantity"] = "0.25"
        payload["price"] = {"amount": "2000", "currency": "EUR"}
        payload["total"] = {"amount": "500", "currency": "EUR"}
        payload["is_promotional"] = action == "airdrop"
    return payload


def _row(
    canonical: dict[str, Any] | None = None,
    *,
    source: ImportSource = ImportSource.trading212,
    status: ImportRowStatus = ImportRowStatus.pending,
) -> ImportRowModel:
    data = deepcopy(canonical or _canonical(source=source))
    intent = classify_import_row(source=source, normalized_data=data)
    assert isinstance(intent, InvestmentEventPostingIntent), intent
    data["deduplication"] = {"schema_version": 1, "status": "unique"}
    data["posting_intent"] = intent.model_dump(mode="json")
    return cast(
        ImportRowModel,
        SimpleNamespace(
            id="row",
            import_batch_id="batch",
            status=status,
            raw_data={"provider": "unchanged"},
            normalized_data=data,
            deduplication_key="dedup-key",
            validation_errors=None,
            error_message=None,
            created_transaction_id=None,
            created_investment_event_id=(
                "event-existing" if status is ImportRowStatus.imported else None
            ),
        ),
    )


def _plan(
    canonical: dict[str, Any] | None = None,
    *,
    source: ImportSource = ImportSource.trading212,
) -> InvestmentEventPostingPlan:
    return build_investment_posting_plan(
        account_id="account",
        batch=_batch(source),
        row=_row(canonical, source=source),
    )


def test_valid_pending_and_imported_replay_boundaries_build_equal_plans() -> None:
    canonical = _canonical()
    pending = _row(canonical)
    imported = _row(canonical, status=ImportRowStatus.imported)
    assert build_investment_posting_plan(
        account_id="account", batch=_batch(), row=pending
    ) == build_investment_posting_plan(account_id="account", batch=_batch(), row=imported)


@pytest.mark.parametrize(
    "change",
    [
        "wrong_account",
        "batch_status",
        "wrong_batch",
        "normalized_none",
        "marker_missing",
        "marker_malformed",
        "intent_missing",
        "intent_malformed",
        "key_missing",
        "key_blank",
        "validation_errors",
        "error_message",
        "transaction_id",
        "event_id_pending",
        "event_id_imported_missing",
        "imported_transaction_id",
    ],
)
def test_posting_boundary_rejects_invalid_state(change: str) -> None:
    batch = _batch()
    row = _row()
    assert row.normalized_data is not None
    if change == "wrong_account":
        account_id = "foreign"
    else:
        account_id = "account"
    if change == "batch_status":
        batch.status = ImportStatus.completed
    elif change == "wrong_batch":
        row.import_batch_id = "other"
    elif change == "normalized_none":
        row.normalized_data = None
    elif change == "marker_missing":
        row.normalized_data.pop("deduplication")
    elif change == "marker_malformed":
        row.normalized_data["deduplication"] = {"schema_version": 2, "status": "unique"}
    elif change == "intent_missing":
        row.normalized_data.pop("posting_intent")
    elif change == "intent_malformed":
        row.normalized_data["posting_intent"] = []
    elif change == "key_missing":
        row.deduplication_key = None
    elif change == "key_blank":
        row.deduplication_key = ""
    elif change == "validation_errors":
        row.validation_errors = [{"code": "bad"}]
    elif change == "error_message":
        row.error_message = "bad"
    elif change == "transaction_id":
        row.created_transaction_id = "transaction"
    elif change == "event_id_pending":
        row.created_investment_event_id = "event"
    elif change == "event_id_imported_missing":
        row.status = ImportRowStatus.imported
        row.created_investment_event_id = None
    elif change == "imported_transaction_id":
        row.status = ImportRowStatus.imported
        row.created_investment_event_id = "event"
        row.created_transaction_id = "transaction"
    with pytest.raises(ImportPostStateError):
        build_investment_posting_plan(account_id=account_id, batch=batch, row=row)


@pytest.mark.parametrize(
    "status",
    [
        ImportRowStatus.duplicate,
        ImportRowStatus.skipped,
        ImportRowStatus.failed,
        ImportRowStatus.needs_review,
    ],
)
def test_non_postable_row_statuses_are_rejected(status: ImportRowStatus) -> None:
    row = _row()
    row.status = status
    with pytest.raises(ImportPostStateError):
        build_investment_posting_plan(account_id="account", batch=_batch(), row=row)


def test_stored_intent_is_rederived_and_mismatch_or_wrong_target_is_rejected() -> None:
    row = _row()
    assert row.normalized_data is not None
    row.normalized_data["posting_intent"]["quantity"] = "3"
    snapshot = deepcopy(row.normalized_data)
    with pytest.raises(ImportPostStateError):
        build_investment_posting_plan(account_id="account", batch=_batch(), row=row)
    assert row.normalized_data == snapshot

    row = _row()
    assert row.normalized_data is not None
    row.normalized_data["posting_intent"] = {"schema_version": 1, "target": "needs_review"}
    with pytest.raises(ImportPostStateError):
        build_investment_posting_plan(account_id="account", batch=_batch(), row=row)


def _review_code(payload: dict[str, Any], source: ImportSource = ImportSource.trading212):
    result = classify_import_row(source=source, normalized_data=payload)
    assert isinstance(result, NeedsReviewPostingIntent)
    return result.errors[0].code


def test_classifier_requires_symbol_not_only_isin() -> None:
    payload = _canonical()
    payload["asset"]["symbol"] = None
    assert _review_code(payload) is PostingIntentIssueCode.missing_asset_symbol


def test_classifier_requires_explicit_asset_transfer_direction() -> None:
    payload = _canonical("asset_transfer")
    payload["asset_direction"] = None
    assert _review_code(payload) is PostingIntentIssueCode.missing_asset_direction


def test_classifier_keeps_anycoin_transfer_direction_successful() -> None:
    payload = _canonical("asset_transfer", source=ImportSource.anycoin)
    result = classify_import_row(source=ImportSource.anycoin, normalized_data=payload)
    assert isinstance(result, InvestmentEventPostingIntent)
    assert result.asset_direction == "in"


def test_classifier_rejects_embedded_trade_conversion() -> None:
    payload = _canonical()
    payload["conversion"] = {
        "from": {"amount": "100", "currency": "EUR"},
        "to": {"amount": "110", "currency": "USD"},
        "exchange_rate": "1.1",
    }
    assert _review_code(payload) is PostingIntentIssueCode.unsupported_embedded_conversion


@pytest.mark.parametrize(
    ("action", "mutation"),
    [
        ("buy", ("realized_pnl", {"amount": "1", "currency": "EUR"})),
        ("buy", ("is_promotional", True)),
        ("fee", ("fee", {"amount": "1", "currency": "EUR"})),
        ("dividend", ("quantity", "1")),
        ("staking_reward", ("total", None)),
    ],
)
def test_classifier_rejects_incompatible_action_fields(
    action: str, mutation: tuple[str, Any]
) -> None:
    payload = _canonical(action)
    field, value = mutation
    payload[field] = value
    if action == "staking_reward":
        payload["price"] = {"amount": "2", "currency": "EUR"}
    assert _review_code(payload) is PostingIntentIssueCode.incompatible_investment_fields


@pytest.mark.parametrize(
    ("hint", "expected"),
    [
        ("stocks", AssetType.stock),
        ("exchange traded fund", AssetType.etf),
        ("cryptocurrency", AssetType.crypto),
        ("commodity", AssetType.commodity),
        ("bond", AssetType.bond),
        ("cash", AssetType.cash),
        ("unknown", AssetType.other),
        (None, AssetType.other),
    ],
)
def test_asset_type_mapping_uses_explicit_hint_only(hint: str | None, expected: AssetType) -> None:
    payload = _canonical()
    payload["asset"]["asset_type_hint"] = hint
    assert _plan(payload).asset_resolution.asset_type is expected  # type: ignore[union-attr]


def test_asset_resolution_maps_provider_identity_and_uppercase_fields() -> None:
    plan = _plan()
    asset = plan.asset_resolution
    assert asset is not None
    assert (
        asset.symbol,
        asset.isin,
        asset.provider,
        asset.provider_symbol,
        asset.exchange,
        asset.listing_currency_hint,
        asset.asset_currency_hint,
    ) == (
        "VWCE",
        "IE00B4L5Y983",
        PriceSource.broker,
        "VWCE",
        "trading212",
        "EUR",
        "EUR",
    )


def test_event_metadata_description_and_date_are_canonical() -> None:
    plan = _plan()
    assert (
        plan.account_id,
        plan.import_batch_id,
        plan.source_row_id,
        plan.event_type,
        plan.source,
        plan.external_id,
        plan.order_id,
        plan.description,
        plan.date,
    ) == (
        "account",
        "batch",
        "row",
        InvestmentEventType.trade,
        ImportSource.trading212,
        "external-1",
        None,
        "Vanguard FTSE All-World",
        datetime(2026, 7, 25, 10, 0, 0, 123000),
    )


def test_buy_listing_currency_falls_back_from_price_to_total() -> None:
    payload = _canonical()
    payload["price"] = None
    asset = _plan(payload).asset_resolution
    assert asset is not None
    assert asset.listing_currency_hint == "EUR"


def test_anycoin_asset_resolution_is_crypto_exchange_with_symbol_currency() -> None:
    payload = _canonical("asset_transfer", source=ImportSource.anycoin)
    plan = _plan(payload, source=ImportSource.anycoin)
    asset = plan.asset_resolution
    assert asset is not None
    assert (
        asset.asset_type,
        asset.provider,
        asset.listing_currency_hint,
        asset.asset_currency_hint,
    ) == (AssetType.crypto, PriceSource.exchange, "BTC", "BTC")


def test_anycoin_conflicting_asset_hint_fails_closed() -> None:
    payload = _canonical("asset_transfer", source=ImportSource.anycoin)
    payload["asset"]["asset_type_hint"] = "stock"
    with pytest.raises(ImportPostStateError):
        _plan(payload, source=ImportSource.anycoin)


def test_dividend_does_not_infer_listing_currency_from_payout() -> None:
    asset = _plan(_canonical("dividend")).asset_resolution
    assert asset is not None
    assert asset.listing_currency_hint is None
    assert asset.asset_currency_hint is None


def test_buy_plan_has_asset_cash_fee_in_binding_order() -> None:
    payload = _canonical()
    payload["fee"] = {"amount": "0.5", "currency": "EUR"}
    plan = _plan(payload)
    assert [movement.kind for movement in plan.movements] == [
        InvestmentMovementKind.asset,
        InvestmentMovementKind.cash,
        InvestmentMovementKind.fee,
    ]
    asset, cash, fee = plan.movements
    assert (
        asset.direction,
        asset.quantity,
        asset.price_per_unit,
        asset.value_amount,
        asset.requires_asset,
    ) == (
        MovementDirection.incoming,
        Decimal("2"),
        Decimal("100.5"),
        Decimal("201"),
        True,
    )
    assert cash.direction is MovementDirection.outgoing
    assert fee.direction is MovementDirection.outgoing and fee.quantity == Decimal("0.5")
    assert all(movement.note == "provider note" for movement in plan.movements)


def test_sell_plan_has_asset_cash_fee_and_realized_pnl_metadata() -> None:
    payload = _canonical("sell")
    payload["fee"] = {"amount": "0.25", "currency": "EUR"}
    payload["realized_pnl"] = {"amount": "-3.5", "currency": "EUR"}
    plan = _plan(payload)
    assert [movement.direction for movement in plan.movements] == [
        MovementDirection.outgoing,
        MovementDirection.incoming,
        MovementDirection.outgoing,
    ]
    assert plan.realized_pnl == Decimal("-3.5")
    assert plan.realized_pnl_currency == "EUR"


def test_dividend_plan_links_cash_to_source_asset() -> None:
    movement = _plan(_canonical("dividend")).movements[0]
    assert movement.kind is InvestmentMovementKind.cash
    assert movement.requires_asset is True
    assert movement.source_symbol == "AAPL"


def test_interest_plan_is_cash_in() -> None:
    movement = _plan(_canonical("interest")).movements[0]
    assert (movement.kind, movement.direction, movement.requires_asset) == (
        InvestmentMovementKind.cash,
        MovementDirection.incoming,
        False,
    )


def test_cash_deposit_plan_is_cash_in() -> None:
    movement = _plan(_canonical("cash_deposit")).movements[0]
    assert movement.direction is MovementDirection.incoming


def test_cash_withdrawal_plan_is_cash_out() -> None:
    movement = _plan(_canonical("cash_withdrawal")).movements[0]
    assert movement.direction is MovementDirection.outgoing


def test_currency_conversion_has_exactly_two_cash_legs_and_optional_fee() -> None:
    payload = _canonical("currency_conversion")
    payload["fee"] = {"amount": "1", "currency": "EUR"}
    plan = _plan(payload)
    assert [(m.currency, m.direction) for m in plan.movements] == [
        ("EUR", MovementDirection.outgoing),
        ("USD", MovementDirection.incoming),
        ("EUR", MovementDirection.outgoing),
    ]


@pytest.mark.parametrize(
    ("direction", "expected"),
    [("in", MovementDirection.incoming), ("out", MovementDirection.outgoing)],
)
def test_anycoin_asset_transfer_has_one_explicit_asset_movement(
    direction: str, expected: MovementDirection
) -> None:
    payload = _canonical("asset_transfer", source=ImportSource.anycoin)
    payload["asset_direction"] = direction
    plan = _plan(payload, source=ImportSource.anycoin)
    assert len(plan.movements) == 1
    assert plan.movements[0].direction is expected


def test_fee_plan_uses_total_as_single_fee_movement() -> None:
    movement = _plan(_canonical("fee")).movements[0]
    assert (
        movement.kind,
        movement.direction,
        movement.quantity,
        movement.value_amount,
    ) == (
        InvestmentMovementKind.fee,
        MovementDirection.outgoing,
        Decimal("2.5"),
        Decimal("2.5"),
    )


def test_staking_reward_and_promotional_airdrop_are_asset_in_movements() -> None:
    staking = _plan(_canonical("staking_reward"))
    airdrop = _plan(_canonical("airdrop"))
    assert staking.movements[0].direction is MovementDirection.incoming
    assert airdrop.movements[0].direction is MovementDirection.incoming
    assert airdrop.movements[0].value_amount == Decimal("500")


def test_exact_quantity_and_timestamp_boundaries_are_accepted() -> None:
    payload = _canonical()
    payload["quantity"] = "999999999999999999.9999999999"
    payload["date"] = "2026-07-25T12:00:00.123000+02:00"
    plan = _plan(payload)
    assert plan.movements[0].quantity == Decimal("999999999999999999.9999999999")
    assert plan.date == datetime(2026, 7, 25, 10, 0, 0, 123000)


@pytest.mark.parametrize("quantity", ["0.00000000001", "1000000000000000000"])
def test_unrepresentable_quantity_is_rejected(quantity: str) -> None:
    payload = _canonical()
    payload["quantity"] = quantity
    row = _row(payload)
    snapshot = deepcopy(row.normalized_data)
    with pytest.raises(ImportPostStateError):
        build_investment_posting_plan(account_id="account", batch=_batch(), row=row)
    assert row.status is ImportRowStatus.pending
    assert row.normalized_data == snapshot


def test_non_finite_quantity_helper_rejects_without_rounding() -> None:
    with pytest.raises(ImportPostStateError):
        exact_numeric(Decimal("NaN"), QUANTITY)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("price", {"amount": "0.00000000001", "currency": "EUR"}),
        ("total", {"amount": "1000000000000000000", "currency": "EUR"}),
        ("fee", {"amount": "0.00000000001", "currency": "EUR"}),
        ("realized_pnl", {"amount": "0.00000000001", "currency": "EUR"}),
        ("realized_pnl", {"amount": "-1000000000000000000", "currency": "EUR"}),
    ],
)
def test_unrepresentable_price_value_fee_and_realized_pnl_are_rejected(
    field: str, value: dict[str, str]
) -> None:
    payload = _canonical("sell")
    payload[field] = value
    with pytest.raises(ImportPostStateError):
        _plan(payload)


def test_sub_millisecond_timestamp_is_rejected() -> None:
    payload = _canonical()
    payload["date"] = "2026-07-25T10:00:00.123456+00:00"
    with pytest.raises(ImportPostStateError):
        _plan(payload)


def test_plans_are_frozen_deterministic_and_do_not_mutate_nested_input() -> None:
    canonical = _canonical()
    row = _row(canonical)
    before_row = deepcopy(row.normalized_data)
    before_batch = deepcopy(vars(_batch()))
    first = build_investment_posting_plan(account_id="account", batch=_batch(), row=row)
    second = build_investment_posting_plan(account_id="account", batch=_batch(), row=row)
    assert first == second
    assert row.normalized_data == before_row
    assert vars(_batch()) == before_batch
    with pytest.raises(FrozenInstanceError):
        first.description = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        first.movements[0].quantity = Decimal("9")  # type: ignore[misc]


def test_trading212_normalize_classify_plan_composition() -> None:
    normalized = normalize_import_row(
        source=ImportSource.trading212,
        account_id="account",
        raw_data={
            "Action": "Market buy",
            "Time": "2026-07-25T10:00:00Z",
            "Ticker": "vwce",
            "ISIN": "IE00B4L5Y983",
            "Name": "Vanguard",
            "Asset type": "ETF",
            "No. of shares": "2",
            "Price / share": "100",
            "Currency (Price / share)": "EUR",
            "Total": "200",
            "Currency (Total)": "EUR",
            "ID": "trade-1",
        },
    )
    assert normalized.data is not None
    plan = _plan(normalized.data)
    assert plan.event_type is InvestmentEventType.trade
    assert [movement.kind for movement in plan.movements] == [
        InvestmentMovementKind.asset,
        InvestmentMovementKind.cash,
    ]


def _anycoin_row(
    row_id: str,
    number: int,
    kind: str,
    amount: str,
    currency: str,
    *,
    order_id: str = "order-1",
) -> AnycoinBatchRow:
    return AnycoinBatchRow(
        row_id=row_id,
        row_number=number,
        raw_data={
            "Type": kind,
            "Order ID": order_id,
            "Date": "2026-07-25T10:00:00Z",
            "Amount": amount,
            "Currency": currency,
            "anycoin TX ID": f"external-{row_id}",
        },
    )


def test_anycoin_grouped_normalize_classify_plan_composition() -> None:
    outcomes = normalize_anycoin_batch(
        account_id="account",
        rows=[
            _anycoin_row("payment", 1, "trade payment", "-500", "EUR"),
            _anycoin_row("fill", 2, "trade fill", "0.01", "BTC"),
        ],
    )
    anchor = next(item for item in outcomes if item.status is ImportRowStatus.pending)
    assert anchor.data is not None
    plan = _plan(anchor.data, source=ImportSource.anycoin)
    assert plan.order_id == "order-1"
    assert plan.asset_resolution is not None
    assert plan.asset_resolution.asset_type is AssetType.crypto


def test_anycoin_standalone_normalize_classify_plan_composition() -> None:
    outcome = normalize_anycoin_batch(
        account_id="account",
        rows=[_anycoin_row("deposit", 1, "deposit", "0.5", "BTC", order_id="")],
    )[0]
    assert outcome.data is not None
    plan = _plan(outcome.data, source=ImportSource.anycoin)
    assert len(plan.movements) == 1
    assert plan.movements[0].direction is MovementDirection.incoming
