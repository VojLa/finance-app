import csv
from collections import Counter
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from app.db.models.common import QUANTITY
from app.db.models.enums import (
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    InvestmentEventType,
    InvestmentMovementKind,
    PriceSource,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.modules.imports.anycoin import AnycoinBatchRow, normalize_anycoin_batch
from app.modules.imports.classification import (
    InvestmentEventPostingIntent,
    NeedsReviewPostingIntent,
    classify_import_row,
)
from app.modules.imports.investment_posting_plan import build_investment_posting_plan
from app.shared.canonical_arithmetic import canonical_ratio

REAL_ANYCOIN_FIXTURE = (
    Path(__file__).parents[3] / "test_imports" / "AnyCoin" / "transactions (2).csv"
)


def _row(
    row_id: str,
    number: int,
    kind: str,
    order: str = "order-1",
    amount: str = "0",
    currency: str = "EUR",
    date: str = "2026-07-23T10:00:00Z",
    external: str = "",
) -> AnycoinBatchRow:
    return AnycoinBatchRow(
        row_id,
        number,
        {
            "Type": kind,
            "Order ID": order,
            "Date": date,
            "Amount": amount,
            "Currency": currency,
            "anycoin TX ID": external,
        },
    )


def _outcomes(*rows: AnycoinBatchRow):
    return normalize_anycoin_batch(
        account_id="account-a",
        account_currency="EUR",
        rows=list(rows),
    )


def test_grouped_buy_uses_anchor_marker_decimal_and_intent() -> None:
    outcomes = _outcomes(
        _row("payment", 3, "trade payment", amount="-600", currency="EUR"),
        _row("fill", 2, "trade fill", amount="0.01", currency="BTC", external="fill-id"),
    )
    event = next(outcome for outcome in outcomes if outcome.status is ImportRowStatus.pending)
    member = next(outcome for outcome in outcomes if outcome.status is ImportRowStatus.skipped)
    assert event.row_id == "fill" and event.data is not None
    assert event.data["action"] == "buy" and event.data["price"] is None
    assert event.data["quote_currency"] == "EUR"
    assert event.data["asset"] == {
        "symbol": "BTC",
        "isin": None,
        "name": "Bitcoin",
        "asset_type_hint": "crypto",
    }
    assert member.data == {
        "schema_version": 2,
        "source": "anycoin",
        "kind": "group_member",
        "order_id": "order-1",
        "anchor_row_id": "fill",
        "member_role": "payment",
    }
    intent = classify_import_row(source=ImportSource.anycoin, normalized_data=event.data)
    assert isinstance(intent, InvestmentEventPostingIntent)
    assert (
        intent.investment_event_type is InvestmentEventType.trade and intent.order_id == "order-1"
    )
    assert intent.quantity == Decimal("0.01")


def test_sell_refund_and_latest_fill_date_are_deterministic() -> None:
    outcomes = _outcomes(
        _row("payment", 1, "trade payment", amount="100", currency="EUR"),
        _row("fill-old", 4, "trade fill", amount="-1", currency="BTC", date="2026-07-20T10:00:00Z"),
        _row("fill-new", 2, "trade fill", amount="-1", currency="BTC", date="2026-07-22T10:00:00Z"),
        _row("refund", 3, "trade refund", amount="-20", currency="EUR"),
    )
    event = next(outcome for outcome in outcomes if outcome.status is ImportRowStatus.pending)
    assert event.row_id == "fill-new" and event.data is not None
    assert (
        event.data["action"] == "sell"
        and event.data["total"]["amount"] == "80"
        and event.data["date"] == "2026-07-22T10:00:00+00:00"
    )


def test_fully_refunded_and_neutral_rows_are_skipped() -> None:
    refunded = _outcomes(
        _row("payment", 1, "trade payment", amount="-10"),
        _row("refund", 2, "trade refund", amount="10"),
    )
    assert all(
        outcome.status is ImportRowStatus.skipped and outcome.deduplication_key is None
        for outcome in refunded
    )
    neutral = _outcomes(_row("block", 1, "payment block", amount="1"))[0]
    assert neutral.status is ImportRowStatus.skipped and neutral.data == {
        "schema_version": 2,
        "source": "anycoin",
        "kind": "neutral_row",
    }


@pytest.mark.parametrize(
    "rows,code",
    [
        ([_row("payment", 1, "trade payment", amount="-1")], "incomplete_order"),
        ([_row("payment", 1, "trade payment", order="", amount="-1")], "missing_order_id"),
        (
            [
                _row("payment", 1, "trade payment", amount="-1"),
                _row("fill-btc", 2, "trade fill", amount="1", currency="BTC"),
                _row("fill-eth", 3, "trade fill", amount="1", currency="ETH"),
            ],
            "multiple_asset_currencies",
        ),
    ],
)
def test_invalid_groups_are_structured_review(rows: list[AnycoinBatchRow], code: str) -> None:
    outcomes = _outcomes(*rows)
    assert all(
        outcome.status is ImportRowStatus.needs_review and outcome.data is None
        for outcome in outcomes
    )
    assert outcomes[0].validation_errors and outcomes[0].validation_errors[0]["code"] == code


def test_standalone_crypto_and_signed_fiat_directions_are_explicit() -> None:
    deposit = _outcomes(_row("deposit", 1, "deposit", order="", amount="2", currency="BTC"))[0]
    withdrawal = _outcomes(
        _row("withdrawal", 1, "withdrawal", order="", amount="-2", currency="BTC")
    )[0]
    assert deposit.data and deposit.data["asset_direction"] == "in"
    assert deposit.data["asset"]["name"] == "Bitcoin"
    assert withdrawal.data and withdrawal.data["asset_direction"] == "out"
    fiat = _outcomes(_row("fiat", 1, "deposit", order="", amount="2", currency="EUR"))[0]
    assert fiat.data and fiat.data["action"] == "cash_deposit"
    assert fiat.data["total"] == {"amount": "2", "currency": "EUR"}
    fiat_out = _outcomes(_row("fiat-out", 1, "withdrawal", order="", amount="-2", currency="EUR"))[
        0
    ]
    assert fiat_out.data and fiat_out.data["action"] == "cash_withdrawal"
    assert fiat_out.data["total"] == {"amount": "2", "currency": "EUR"}


def test_distinct_overlong_transaction_ids_are_reviewed_without_heuristic_identity() -> None:
    outcomes = _outcomes(
        _row("first", 1, "deposit", order="", amount="2", currency="EUR", external="a" * 10_001),
        _row("second", 2, "deposit", order="", amount="2", currency="EUR", external="b" * 10_001),
    )

    assert [outcome.status for outcome in outcomes] == [
        ImportRowStatus.needs_review,
        ImportRowStatus.needs_review,
    ]
    assert all(outcome.data is None for outcome in outcomes)
    assert all(outcome.deduplication_key is None for outcome in outcomes)
    assert all(
        outcome.validation_errors and outcome.validation_errors[0]["code"] == "invalid_anycoin_row"
        for outcome in outcomes
    )


def test_non_btc_crypto_does_not_receive_a_guessed_display_name() -> None:
    transfer = _outcomes(_row("eth", 1, "deposit", order="", amount="2", currency="ETH"))[0]
    assert transfer.data is not None
    assert transfer.data["asset"]["name"] is None


def test_standalone_transfer_rejects_contradictory_sign_and_quote_currency() -> None:
    contradictory = _outcomes(_row("bad", 1, "withdrawal", order="", amount="2", currency="BTC"))[0]
    assert contradictory.validation_errors
    assert contradictory.validation_errors[0]["code"] == "contradictory_transfer_direction"
    conflicting = _outcomes(_row("usd", 1, "deposit", order="", amount="2", currency="USD"))[0]
    assert conflicting.validation_errors
    assert conflicting.validation_errors[0]["code"] == "conflicting_anycoin_quote_currency"


def test_schema_v1_remains_deferred() -> None:
    result = classify_import_row(
        source=ImportSource.anycoin,
        normalized_data={
            "schema_version": 1,
            "source": "anycoin",
            "date": "2026-07-23",
            "amount": "1",
            "currency": "EUR",
        },
    )
    assert isinstance(result, NeedsReviewPostingIntent)


@pytest.mark.skipif(not REAL_ANYCOIN_FIXTURE.exists(), reason="Local Anycoin fixture is absent")
def test_real_fixture_is_fully_postable_with_one_quote_identity_and_exact_arithmetic() -> None:
    with REAL_ANYCOIN_FIXTURE.open(encoding="utf-8-sig", newline="") as handle:
        raw_rows = list(csv.DictReader(handle))
    rows = [
        AnycoinBatchRow(f"fixture-row-{index}", index, raw)
        for index, raw in enumerate(raw_rows, start=2)
    ]
    outcomes = normalize_anycoin_batch(
        account_id="fixture-account",
        account_currency="CZK",
        rows=rows,
    )
    reversed_outcomes = normalize_anycoin_batch(
        account_id="fixture-account",
        account_currency="CZK",
        rows=list(reversed(rows)),
    )

    assert len(outcomes) == 450
    assert Counter(outcome.status for outcome in outcomes) == {
        ImportRowStatus.pending: 194,
        ImportRowStatus.skipped: 256,
    }
    assert outcomes == reversed_outcomes

    batch = cast(
        ImportBatchModel,
        SimpleNamespace(
            id="fixture-batch",
            account_id="fixture-account",
            source=ImportSource.anycoin,
            status=ImportStatus.processing,
        ),
    )
    plans = []
    raw_overprecision = 0
    for outcome in outcomes:
        if outcome.status is not ImportRowStatus.pending:
            continue
        assert outcome.data is not None and outcome.deduplication_key is not None
        canonical = dict(outcome.data)
        intent = classify_import_row(
            source=ImportSource.anycoin,
            normalized_data=canonical,
        )
        assert isinstance(intent, InvestmentEventPostingIntent)
        assert intent.quote_currency == "CZK"
        if intent.action.value in {"buy", "sell"}:
            assert intent.price is None and intent.total is not None and intent.quantity is not None
            exponent = (intent.total.amount / intent.quantity).as_tuple().exponent
            assert isinstance(exponent, int)
            if exponent < -10:
                raw_overprecision += 1
        canonical["deduplication"] = {"schema_version": 1, "status": "unique"}
        canonical["posting_intent"] = intent.model_dump(mode="json")
        row = cast(
            ImportRowModel,
            SimpleNamespace(
                id=outcome.row_id,
                import_batch_id="fixture-batch",
                status=ImportRowStatus.pending,
                normalized_data=canonical,
                deduplication_key=outcome.deduplication_key,
                validation_errors=None,
                error_message=None,
                created_transaction_id=None,
                created_investment_event_id=None,
            ),
        )
        first = build_investment_posting_plan(
            account_id="fixture-account",
            batch=batch,
            row=row,
        )
        replayed = build_investment_posting_plan(
            account_id="fixture-account",
            batch=batch,
            row=row,
        )
        assert replayed == first
        if intent.action.value in {"buy", "sell"}:
            assert intent.total is not None and intent.quantity is not None
            asset_movement = next(
                movement
                for movement in first.movements
                if movement.kind is InvestmentMovementKind.asset
            )
            cash_movement = next(
                movement
                for movement in first.movements
                if movement.kind is InvestmentMovementKind.cash
            )
            assert asset_movement.quantity == intent.quantity
            assert asset_movement.value_amount == intent.total.amount
            assert cash_movement.quantity == intent.total.amount
            assert asset_movement.price_per_unit == canonical_ratio(
                intent.total.amount,
                intent.quantity,
                QUANTITY,
            )
        plans.append(first)

    assert raw_overprecision == 112
    assert Counter(plan.event_type for plan in plans) == {
        InvestmentEventType.trade: 115,
        InvestmentEventType.asset_transfer: 16,
        InvestmentEventType.cash_deposit: 60,
        InvestmentEventType.cash_withdrawal: 3,
    }
    assert sum(len(plan.movements) for plan in plans) == 309
    assert {
        (
            plan.asset_resolution.symbol,
            plan.asset_resolution.provider,
            plan.asset_resolution.listing_currency_hint,
            plan.asset_resolution.asset_currency_hint,
        )
        for plan in plans
        if plan.asset_resolution is not None
    } == {("BTC", PriceSource.exchange, "CZK", "BTC")}
    for plan in plans:
        for movement in plan.movements:
            if (
                plan.event_type is InvestmentEventType.trade
                and movement.kind is InvestmentMovementKind.asset
            ):
                assert movement.price_per_unit is not None
                exponent = movement.price_per_unit.as_tuple().exponent
                assert isinstance(exponent, int)
                assert exponent >= -10
                assert movement.value_amount is not None
                assert movement.value_currency == "CZK"
