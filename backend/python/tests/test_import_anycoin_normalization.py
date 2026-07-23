from decimal import Decimal

import pytest

from app.db.models.enums import ImportRowStatus, ImportSource, InvestmentEventType
from app.modules.imports.anycoin import AnycoinBatchRow, normalize_anycoin_batch
from app.modules.imports.classification import (
    InvestmentEventPostingIntent,
    NeedsReviewPostingIntent,
    classify_import_row,
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
    return normalize_anycoin_batch(account_id="account-a", rows=list(rows))


def test_grouped_buy_uses_anchor_marker_decimal_and_intent() -> None:
    outcomes = _outcomes(
        _row("payment", 3, "trade payment", amount="-600", currency="EUR"),
        _row("fill", 2, "trade fill", amount="0.01", currency="BTC", external="fill-id"),
    )
    event = next(outcome for outcome in outcomes if outcome.status is ImportRowStatus.pending)
    member = next(outcome for outcome in outcomes if outcome.status is ImportRowStatus.skipped)
    assert event.row_id == "fill" and event.data is not None
    assert event.data["action"] == "buy" and event.data["price"] == {
        "amount": "60000",
        "currency": "EUR",
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


def test_standalone_crypto_direction_fiat_and_schema_v1_deferred() -> None:
    deposit = _outcomes(_row("deposit", 1, "deposit", order="", amount="2", currency="BTC"))[0]
    withdrawal = _outcomes(
        _row("withdrawal", 1, "withdrawal", order="", amount="-2", currency="BTC")
    )[0]
    assert deposit.data and deposit.data["asset_direction"] == "in"
    assert withdrawal.data and withdrawal.data["asset_direction"] == "out"
    fiat = _outcomes(_row("fiat", 1, "deposit", order="", amount="2", currency="EUR"))[0]
    assert (
        fiat.validation_errors
        and fiat.validation_errors[0]["code"] == "unsupported_anycoin_fiat_transfer"
    )
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
