from decimal import Decimal

import pytest

from app.db.models.enums import (
    ImportSource,
    InvestmentEventType,
    TransactionClassification,
    TransactionType,
)
from app.modules.imports.classification import (
    InvestmentEventPostingIntent,
    NeedsReviewPostingIntent,
    TransactionPostingIntent,
    classify_import_row,
)
from app.modules.imports.normalizers import normalize_import_row


def _row(**overrides: str) -> dict[str, str]:
    row = {
        "Action": "Market buy",
        "Time": "2026-07-23T10:00:00Z",
        "ISIN": "IE00B4L5Y983",
        "Ticker": "vwce",
        "Name": "Vanguard FTSE All-World",
        "No. of shares": "2.00",
        "Price / share": "100.50",
        "Currency (Price / share)": "eur",
        "Total": "201.000",
        "Currency (Total)": "EUR",
        "ID": "order-1",
    }
    row.update(overrides)
    return row


def _normalize(**overrides: str):
    return normalize_import_row(
        source=ImportSource.trading212, account_id="account-a", raw_data=_row(**overrides)
    )


def test_trading212_canonical_buy_and_complete_intent() -> None:
    result = _normalize(
        **{"Currency conversion fee": "-0.25", "Currency (Currency conversion fee)": "EUR"}
    )

    assert result.validation_errors is None
    assert result.data == {
        "schema_version": 2,
        "source": "trading212",
        "kind": "investment_event",
        "date": "2026-07-23T10:00:00+00:00",
        "action": "buy",
        "external_id": "order-1",
        "raw_action": "Market buy",
        "asset": {
            "symbol": "VWCE",
            "isin": "IE00B4L5Y983",
            "name": "Vanguard FTSE All-World",
            "asset_type_hint": None,
        },
        "quantity": "2",
        "price": {"amount": "100.5", "currency": "EUR"},
        "total": {"amount": "200.75", "currency": "EUR"},
        "fee": {"amount": "0.25", "currency": "EUR"},
        "conversion": None,
        "realized_pnl": None,
        "is_promotional": False,
        "note": None,
    }
    assert result.data is not None
    intent = classify_import_row(source=ImportSource.trading212, normalized_data=result.data)
    assert isinstance(intent, InvestmentEventPostingIntent)
    assert intent.investment_event_type is InvestmentEventType.trade
    assert intent.quantity == Decimal("2")
    assert intent.model_dump(mode="json")["fee"]["amount"] == "0.25"


def test_cross_currency_buy_derives_trade_principal_without_conversion_legs() -> None:
    result = _normalize(
        **{
            "No. of shares": "0.2066590000",
            "Price / share": "93.9200000000",
            "Currency (Price / share)": "USD",
            "Total": "17.98",
            "Currency (Total)": "EUR",
            "Exchange rate": "1.08130436",
            "Currency conversion fee": "0.03",
            "Currency (Currency conversion fee)": "EUR",
        }
    )

    assert result.validation_errors is None
    assert result.data is not None
    assert result.data["quantity"] == "0.206659"
    assert result.data["price"] == {"amount": "93.92", "currency": "USD"}
    assert result.data["total"] == {"amount": "17.95", "currency": "EUR"}
    assert result.data["fee"] == {"amount": "0.03", "currency": "EUR"}
    assert result.data["conversion"] is None
    intent = classify_import_row(source=ImportSource.trading212, normalized_data=result.data)
    assert isinstance(intent, InvestmentEventPostingIntent)


def test_cross_currency_sell_derives_gross_trade_proceeds_without_conversion_legs() -> None:
    result = _normalize(
        Action="Market sell",
        **{
            "No. of shares": "0.2066590000",
            "Price / share": "126.4200000000",
            "Currency (Price / share)": "USD",
            "Total": "24.61",
            "Currency (Total)": "EUR",
            "Exchange rate": "1.05987143",
            "Currency conversion fee": "0.04",
            "Currency (Currency conversion fee)": "EUR",
        },
    )

    assert result.validation_errors is None
    assert result.data is not None
    assert result.data["total"] == {"amount": "24.65", "currency": "EUR"}
    assert result.data["fee"] == {"amount": "0.04", "currency": "EUR"}
    assert result.data["conversion"] is None


def test_trade_fee_must_share_settlement_currency_for_principal_derivation() -> None:
    result = _normalize(
        **{
            "Currency conversion fee": "0.25",
            "Currency (Currency conversion fee)": "USD",
        }
    )

    assert result.data is None
    assert result.validation_errors is not None
    assert any(error["code"] == "conflicting_currency" for error in result.validation_errors)


def test_buy_fee_cannot_consume_the_complete_settled_total() -> None:
    result = _normalize(
        Total="0.25",
        **{
            "Currency conversion fee": "0.25",
            "Currency (Currency conversion fee)": "EUR",
        },
    )

    assert result.data is None
    assert result.validation_errors is not None
    assert any(error["field"] == "total" for error in result.validation_errors)


def test_zero_provider_fee_column_is_absent_from_canonical_payload() -> None:
    result = _normalize(
        **{
            "Currency conversion fee": "0",
            "Currency (Currency conversion fee)": "EUR",
        }
    )

    assert result.data is not None
    assert result.data["fee"] is None


@pytest.mark.parametrize("action", ["Market buy", "Limit buy"])
def test_buy_ignores_trading212_blank_result_currency_placeholder(action: str) -> None:
    result = _normalize(Action=action, **{"Result": "", "Currency (Result)": "eur"})

    assert result.validation_errors is None
    assert result.data is not None
    assert result.data["realized_pnl"] is None
    assert isinstance(
        classify_import_row(source=ImportSource.trading212, normalized_data=result.data),
        InvestmentEventPostingIntent,
    )


@pytest.mark.parametrize("action", ["Market sell", "Dividend"])
def test_non_buy_blank_result_currency_requires_paired_realized_pnl(action: str) -> None:
    result = _normalize(Action=action, **{"Result": "", "Currency (Result)": "EUR"})

    assert result.data is None
    assert result.validation_errors is not None
    assert {error["code"] for error in result.validation_errors} >= {"paired_required"}


def test_sell_preserves_filled_realized_pnl_and_classifies() -> None:
    result = _normalize(Action="Market sell", **{"Result": "1.25", "Currency (Result)": "EUR"})

    assert result.validation_errors is None
    assert result.data is not None
    assert result.data["realized_pnl"] == {"amount": "1.25", "currency": "EUR"}
    assert isinstance(
        classify_import_row(source=ImportSource.trading212, normalized_data=result.data),
        InvestmentEventPostingIntent,
    )


def test_sell_result_without_currency_requires_paired_realized_pnl() -> None:
    result = _normalize(Action="Market sell", **{"Result": "1.25", "Currency (Result)": ""})

    assert result.data is None
    assert result.validation_errors is not None
    assert {error["code"] for error in result.validation_errors} >= {"paired_required"}


def test_buy_blank_result_with_invalid_currency_requires_review() -> None:
    result = _normalize(**{"Result": "", "Currency (Result)": "EUR!"})

    assert result.data is None
    assert result.validation_errors is not None
    assert any(
        error
        == {"field": "realized_pnl.currency", "code": "invalid", "message": "Currency is invalid."}
        for error in result.validation_errors
    )


def test_buy_preserves_filled_realized_pnl_for_classifier_review() -> None:
    result = _normalize(**{"Result": "1.25", "Currency (Result)": "EUR"})

    assert result.validation_errors is None
    assert result.data is not None
    assert result.data["realized_pnl"] == {"amount": "1.25", "currency": "EUR"}
    classified = classify_import_row(source=ImportSource.trading212, normalized_data=result.data)
    assert isinstance(classified, NeedsReviewPostingIntent)
    assert classified.errors[0].code.value == "incompatible_investment_fields"


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("Dividend (Tax Exempted)", InvestmentEventType.dividend),
        ("Deposit", InvestmentEventType.cash_deposit),
        ("Withdrawal", InvestmentEventType.cash_withdrawal),
        ("Currency conversion", InvestmentEventType.currency_conversion),
        ("Trading fee", InvestmentEventType.fee),
        ("Staking reward", InvestmentEventType.staking_reward),
        ("Airdrop", InvestmentEventType.airdrop),
    ],
)
def test_supported_action_families(action: str, expected: InvestmentEventType) -> None:
    values = {"Action": action}
    if expected is InvestmentEventType.dividend:
        values.update({"No. of shares": "", "Price / share": "", "Currency (Price / share)": ""})
    if expected in {
        InvestmentEventType.interest,
        InvestmentEventType.cash_deposit,
        InvestmentEventType.cash_withdrawal,
        InvestmentEventType.currency_conversion,
        InvestmentEventType.fee,
    }:
        values.update(
            {
                "Ticker": "",
                "ISIN": "",
                "Name": "",
                "No. of shares": "",
                "Price / share": "",
                "Currency (Price / share)": "",
            }
        )
    if expected is InvestmentEventType.currency_conversion:
        values.update(
            {
                "Total": "100",
                "Currency (Total)": "EUR",
                "Currency conversion from amount": "100",
                "Currency (Currency conversion from amount)": "EUR",
                "Currency conversion to amount": "110",
                "Currency (Currency conversion to amount)": "USD",
            }
        )
    result = _normalize(**values)
    assert result.data is not None, result.validation_errors
    intent = classify_import_row(source=ImportSource.trading212, normalized_data=result.data)
    assert isinstance(intent, InvestmentEventPostingIntent)
    assert intent.investment_event_type is expected


def test_directionless_trading212_asset_transfer_requires_review() -> None:
    result = _normalize(
        Action="Portfolio transfer",
        **{
            "Price / share": "",
            "Currency (Price / share)": "",
            "Total": "",
            "Currency (Total)": "",
        },
    )
    assert result.data is not None
    intent = classify_import_row(source=ImportSource.trading212, normalized_data=result.data)
    assert isinstance(intent, NeedsReviewPostingIntent)
    assert intent.errors[0].code.value == "missing_asset_direction"


@pytest.mark.parametrize(
    ("action", "amount"),
    [
        ("Card debit", "-12.5"),
        ("New card cost", "-5"),
        ("Spending cashback", "1.25"),
    ],
)
def test_trading_card_cash_rows_remain_operational_transactions(action: str, amount: str) -> None:
    result = _normalize(
        Action=action,
        Ticker="",
        ISIN="",
        Name="Coffee shop",
        **{
            "No. of shares": "",
            "Price / share": "",
            "Currency (Price / share)": "",
            "Total": amount.removeprefix("-"),
        },
    )

    assert result.validation_errors is None
    assert result.data is not None
    assert result.data["kind"] == "transaction"
    assert result.data["amount"] == amount
    assert result.data["currency"] == "EUR"
    assert result.data["description"] == "Coffee shop"
    assert result.data["counterparty"] == "Coffee shop"
    intent = classify_import_row(source=ImportSource.trading212, normalized_data=result.data)
    assert isinstance(intent, TransactionPostingIntent)
    assert intent.amount == Decimal(amount)
    expected_type = TransactionType.income if Decimal(amount) > 0 else TransactionType.expense
    expected_classification = (
        TransactionClassification.real_income
        if Decimal(amount) > 0
        else TransactionClassification.real_expense
    )
    assert intent.transaction_type is expected_type
    assert intent.transaction_classification is expected_classification


def test_trading_card_fallback_deduplication_distinguishes_merchants_and_actions() -> None:
    common = {
        "ID": "",
        "Ticker": "",
        "ISIN": "",
        "No. of shares": "",
        "Price / share": "",
        "Currency (Price / share)": "",
        "Total": "12.50",
    }
    coffee = _normalize(Action="Card debit", Name="Coffee shop", **common)
    grocer = _normalize(Action="Card debit", Name="Grocer", **common)
    card_cost = _normalize(Action="New card cost", Name="Coffee shop", **common)

    assert coffee.validation_errors is None
    assert grocer.validation_errors is None
    assert card_cost.validation_errors is None
    assert coffee.deduplication_key != grocer.deduplication_key
    assert coffee.deduplication_key != card_cost.deduplication_key


@pytest.mark.parametrize("action", ["Card cost", "Unknown refund"])
def test_unsupported_actions_require_review(action: str) -> None:
    result = _normalize(Action=action)
    assert result.data is None
    assert result.deduplication_key is None
    assert result.validation_errors is not None


@pytest.mark.parametrize("action", ["Transfer", "Account transfer"])
def test_generic_transfer_actions_do_not_create_asset_transfer(action: str) -> None:
    result = _normalize(Action=action)

    assert result.data is None
    assert result.validation_errors is not None
    assert result.validation_errors[0]["code"] == "unsupported_action"


def test_promotional_free_share_requires_asset_and_quantity_and_ignores_fee() -> None:
    result = _normalize(
        Action="Free share",
        **{"Currency conversion fee": "1", "Currency (Currency conversion fee)": "EUR"},
    )
    assert result.data is not None
    assert result.data["action"] == "airdrop"
    assert result.data["is_promotional"] is True
    assert result.data["fee"] is None
    missing_asset = _normalize(Action="Free share", Ticker="", ISIN="")
    assert missing_asset.data is None


def test_fee_currency_conflict_and_paired_fields_require_review() -> None:
    result = _normalize(
        **{
            "Currency conversion fee": "1",
            "Currency (Currency conversion fee)": "EUR",
            "Finra fee": "2",
            "Currency (Finra fee)": "USD",
        }
    )
    assert result.data is None
    assert any(error["code"] == "conflicting_currency" for error in result.validation_errors or [])
    incomplete = _normalize(**{"Price / share": "100", "Currency (Price / share)": ""})
    assert incomplete.data is None


def test_fee_action_with_zero_total_requires_review() -> None:
    result = _normalize(Action="Fee", Total="0")

    assert result.data is None
    assert result.validation_errors is not None
    assert any(error["field"].startswith("total") for error in result.validation_errors)


def test_classifier_rejects_manually_constructed_zero_fee() -> None:
    normalized = _normalize()
    assert normalized.data is not None
    normalized.data["fee"] = {"amount": "0", "currency": "EUR"}

    result = classify_import_row(source=ImportSource.trading212, normalized_data=normalized.data)

    assert isinstance(result, NeedsReviewPostingIntent)
    assert result.errors[0].code.value == "incompatible_investment_fields"


def test_fallback_dedup_is_canonical_and_excludes_provider_presentation() -> None:
    first = _normalize(ID="", **{"No. of shares": "2.00", "Total": "201.000", "Notes": "one"})
    second = _normalize(
        ID="", **{"No. of shares": "2", "Total": "201", "Notes": "two", "Action": " market   BUY "}
    )
    other_account = normalize_import_row(
        source=ImportSource.trading212, account_id="account-b", raw_data=_row(ID="")
    )
    different = _normalize(ID="", Total="202")
    assert first.deduplication_key == second.deduplication_key
    assert first.deduplication_key != other_account.deduplication_key
    assert first.deduplication_key != different.deduplication_key


def test_anycoin_remains_deferred() -> None:
    data = {
        "schema_version": 1,
        "source": "anycoin",
        "date": "2026-07-23",
        "amount": "1",
        "currency": "EUR",
    }
    result = classify_import_row(source=ImportSource.anycoin, normalized_data=data)
    assert isinstance(result, NeedsReviewPostingIntent)
    assert result.errors[0].code.value == "investment_normalization_required"
