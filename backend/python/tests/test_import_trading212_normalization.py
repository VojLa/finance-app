from decimal import Decimal

import pytest

from app.db.models.enums import ImportSource, InvestmentEventType
from app.modules.imports.classification import (
    InvestmentEventPostingIntent,
    NeedsReviewPostingIntent,
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
        "total": {"amount": "201", "currency": "EUR"},
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


def test_zero_provider_fee_column_is_absent_from_canonical_payload() -> None:
    result = _normalize(
        **{
            "Currency conversion fee": "0",
            "Currency (Currency conversion fee)": "EUR",
        }
    )

    assert result.data is not None
    assert result.data["fee"] is None


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ("Dividend (Tax Exempted)", InvestmentEventType.dividend),
        ("Spending cashback", InvestmentEventType.interest),
        ("Deposit", InvestmentEventType.cash_deposit),
        ("Withdrawal", InvestmentEventType.cash_withdrawal),
        ("Currency conversion", InvestmentEventType.currency_conversion),
        ("Portfolio transfer", InvestmentEventType.asset_transfer),
        ("Trading fee", InvestmentEventType.fee),
        ("Staking reward", InvestmentEventType.staking_reward),
        ("Airdrop", InvestmentEventType.airdrop),
    ],
)
def test_supported_action_families(action: str, expected: InvestmentEventType) -> None:
    values = {"Action": action}
    if expected is InvestmentEventType.currency_conversion:
        values.update(
            {
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


@pytest.mark.parametrize("action", ["Card debit", "Card cost", "New card cost", "Unknown refund"])
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
    assert result.errors[0].code.value == "invalid_investment_payload"


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
