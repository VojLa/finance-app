from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.db.models.enums import (
    ImportSource,
    InvestmentEventType,
    TransactionClassification,
    TransactionType,
)
from app.modules.imports.classification import (
    InvestmentEventPostingIntent,
    NeedsReviewPostingIntent,
    PostingIntentIssueCode,
    PostingIntentTarget,
    TransactionPostingIntent,
    classify_import_row,
)
from app.modules.imports.normalizers import normalize_import_row


def _normalized(
    source: ImportSource,
    *,
    amount: object = "10",
    source_type: object | None = None,
    **extra: object,
) -> dict[str, object]:
    data: dict[str, object] = {
        "schema_version": 1,
        "source": source.value,
        "date": "2026-07-23",
        "amount": amount,
        "currency": "EUR",
        **extra,
    }
    if source_type is not None:
        data["type"] = source_type
    return data


def _review_code(result: NeedsReviewPostingIntent) -> PostingIntentIssueCode:
    assert len(result.errors) == 1
    return result.errors[0].code


@pytest.mark.parametrize("source", [ImportSource.raiffeisenbank, ImportSource.manual])
@pytest.mark.parametrize(
    ("amount", "expected_type", "expected_classification"),
    [
        ("10.25", TransactionType.income, TransactionClassification.real_income),
        ("-10.25", TransactionType.expense, TransactionClassification.real_expense),
    ],
)
def test_transaction_sources_fall_back_to_signed_decimal_amount(
    source: ImportSource,
    amount: str,
    expected_type: TransactionType,
    expected_classification: TransactionClassification,
) -> None:
    result = classify_import_row(
        source=source,
        normalized_data=_normalized(
            source,
            amount=amount,
            source_type="unmapped provider token",
        ),
    )

    assert isinstance(result, TransactionPostingIntent)
    assert result.transaction_type is expected_type
    assert result.transaction_classification is expected_classification
    assert result.amount == Decimal(amount)


@pytest.mark.parametrize("source", [ImportSource.raiffeisenbank, ImportSource.manual])
@pytest.mark.parametrize(
    ("source_type", "amount", "expected_type", "expected_classification"),
    [
        ("income", "10", TransactionType.income, TransactionClassification.real_income),
        ("expense", "-10", TransactionType.expense, TransactionClassification.real_expense),
        (
            "INTERNAL TRANSFER",
            "-10",
            TransactionType.transfer,
            TransactionClassification.internal_transfer,
        ),
        (
            "interní převod",
            "10",
            TransactionType.transfer,
            TransactionClassification.internal_transfer,
        ),
    ],
)
def test_transaction_explicit_allowlist_uses_normalized_type(
    source: ImportSource,
    source_type: str,
    amount: str,
    expected_type: TransactionType,
    expected_classification: TransactionClassification,
) -> None:
    result = classify_import_row(
        source=source,
        normalized_data=_normalized(source, amount=amount, source_type=source_type),
    )

    assert isinstance(result, TransactionPostingIntent)
    assert result.transaction_type is expected_type
    assert result.transaction_classification is expected_classification


@pytest.mark.parametrize("source", [ImportSource.raiffeisenbank, ImportSource.manual])
@pytest.mark.parametrize("source_type", ["transfer", "account transfer", "převod"])
def test_generic_transfer_tokens_need_review_without_description_inference(
    source: ImportSource,
    source_type: str,
) -> None:
    first = classify_import_row(
        source=source,
        normalized_data=_normalized(
            source,
            source_type=source_type,
            description="internal transfer refund loan",
            counterparty="My other account",
        ),
    )
    second = classify_import_row(
        source=source,
        normalized_data=_normalized(
            source,
            source_type=source_type,
            description="ordinary payment",
            counterparty="External recipient",
        ),
    )

    assert isinstance(first, NeedsReviewPostingIntent)
    assert isinstance(second, NeedsReviewPostingIntent)
    assert _review_code(first) is PostingIntentIssueCode.ambiguous_transfer_type
    assert first == second


@pytest.mark.parametrize(("source_type", "amount"), [("income", "-1"), ("expense", "1")])
def test_explicit_transaction_type_conflicting_with_sign_needs_review(
    source_type: str,
    amount: str,
) -> None:
    result = classify_import_row(
        source=ImportSource.manual,
        normalized_data=_normalized(
            ImportSource.manual,
            amount=amount,
            source_type=source_type,
        ),
    )

    assert isinstance(result, NeedsReviewPostingIntent)
    assert _review_code(result) is PostingIntentIssueCode.conflicting_transaction_type


@pytest.mark.parametrize("source", [ImportSource.raiffeisenbank, ImportSource.manual])
def test_zero_transaction_amount_needs_review(source: ImportSource) -> None:
    result = classify_import_row(
        source=source,
        normalized_data=_normalized(source, amount="0.000", source_type="income"),
    )

    assert isinstance(result, NeedsReviewPostingIntent)
    assert _review_code(result) is PostingIntentIssueCode.zero_amount


@pytest.mark.parametrize("source", [ImportSource.trading212, ImportSource.anycoin])
@pytest.mark.parametrize("source_type", ["market buy", "deposit", "unknown action"])
def test_investment_sources_always_require_source_specific_normalization(
    source: ImportSource,
    source_type: str,
) -> None:
    result = classify_import_row(
        source=source,
        normalized_data=_normalized(source, amount="-12.5", source_type=source_type),
    )

    assert isinstance(result, NeedsReviewPostingIntent)
    assert _review_code(result) is PostingIntentIssueCode.investment_normalization_required


@pytest.mark.parametrize(
    "schema_version",
    [None, 0, 2, True, "1"],
)
def test_unsupported_normalized_schema_version_is_deterministic(schema_version: object) -> None:
    data = _normalized(ImportSource.manual)
    data["schema_version"] = schema_version

    result = classify_import_row(source=ImportSource.manual, normalized_data=data)

    assert isinstance(result, NeedsReviewPostingIntent)
    assert _review_code(result) is PostingIntentIssueCode.unsupported_schema_version


def test_source_argument_must_match_normalized_source() -> None:
    result = classify_import_row(
        source=ImportSource.manual,
        normalized_data=_normalized(ImportSource.raiffeisenbank),
    )

    assert isinstance(result, NeedsReviewPostingIntent)
    assert _review_code(result) is PostingIntentIssueCode.source_mismatch


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("date", None, PostingIntentIssueCode.invalid_date),
        ("date", "not-a-date", PostingIntentIssueCode.invalid_date),
        ("amount", None, PostingIntentIssueCode.invalid_amount),
        ("amount", 1.5, PostingIntentIssueCode.invalid_amount),
        ("amount", "NaN", PostingIntentIssueCode.invalid_amount),
        ("amount", "Infinity", PostingIntentIssueCode.invalid_amount),
        ("currency", "eur", PostingIntentIssueCode.invalid_currency),
        ("currency", "../EUR", PostingIntentIssueCode.invalid_currency),
    ],
)
def test_untrusted_financial_fields_need_review(
    field: str,
    value: object,
    expected_code: PostingIntentIssueCode,
) -> None:
    data = _normalized(ImportSource.manual)
    data[field] = value

    result = classify_import_row(source=ImportSource.manual, normalized_data=data)

    assert isinstance(result, NeedsReviewPostingIntent)
    assert _review_code(result) is expected_code


def test_invalid_normalized_payload_needs_review() -> None:
    result = classify_import_row(source=ImportSource.manual, normalized_data=[])

    assert isinstance(result, NeedsReviewPostingIntent)
    assert _review_code(result) is PostingIntentIssueCode.invalid_payload


def test_posting_intent_contracts_are_immutable_versioned_and_json_serializable() -> None:
    transaction = classify_import_row(
        source=ImportSource.manual,
        normalized_data=_normalized(
            ImportSource.manual,
            amount="-123.4500",
            source_type="expense",
        ),
    )
    normalized = normalize_import_row(
        source=ImportSource.trading212,
        account_id="account-a",
        raw_data={
            "Action": "Market buy",
            "Time": "2026-07-23T10:00:00Z",
            "Ticker": "VWCE",
            "No. of shares": "2",
            "Total": "12.50",
            "Currency (Total)": "EUR",
        },
    )
    assert normalized.data is not None
    investment = classify_import_row(
        source=ImportSource.trading212, normalized_data=normalized.data
    )

    assert isinstance(transaction, TransactionPostingIntent)
    assert transaction.model_dump(mode="json") == {
        "schema_version": 1,
        "target": PostingIntentTarget.transaction.value,
        "source": ImportSource.manual.value,
        "date": "2026-07-23",
        "amount": "-123.4500",
        "currency": "EUR",
        "transaction_type": TransactionType.expense.value,
        "transaction_classification": TransactionClassification.real_expense.value,
    }
    assert isinstance(investment, InvestmentEventPostingIntent)
    assert investment.model_dump(mode="json")["target"] == PostingIntentTarget.investment_event
    assert investment.model_dump(mode="json")["total"]["amount"] == "12.5"
    with pytest.raises(ValidationError):
        transaction.amount = Decimal("1")  # type: ignore[misc]
    with pytest.raises(ValidationError):
        investment.quantity = Decimal("1")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("source_type", "amount", "expected_type", "expected_classification"),
    [
        ("Příchozí platba", "100", TransactionType.income, TransactionClassification.real_income),
        ("Odchozí platba", "-100", TransactionType.expense, TransactionClassification.real_expense),
        ("Platba kartou", "-50", TransactionType.expense, TransactionClassification.real_expense),
        ("Běžný typ", "100", TransactionType.income, TransactionClassification.real_income),
        ("Běžný typ", "-100", TransactionType.expense, TransactionClassification.real_expense),
    ],
)
def test_raiffeisenbank_normalization_and_classification_composition(
    source_type: str,
    amount: str,
    expected_type: TransactionType,
    expected_classification: TransactionClassification,
) -> None:
    normalized = normalize_import_row(
        source=ImportSource.raiffeisenbank,
        account_id="account-a",
        raw_data={
            "Datum": "23.07.2026",
            "Částka": amount,
            "Měna": "czk",
            "Typ": source_type,
        },
    )
    assert normalized.data is not None

    result = classify_import_row(
        source=ImportSource.raiffeisenbank,
        normalized_data=normalized.data,
    )

    assert isinstance(result, TransactionPostingIntent)
    assert result.transaction_type is expected_type
    assert result.transaction_classification is expected_classification


def test_raiffeisenbank_generic_transfer_composition_needs_review() -> None:
    normalized = normalize_import_row(
        source=ImportSource.raiffeisenbank,
        account_id="account-a",
        raw_data={
            "Datum": "23.07.2026",
            "Částka": "100",
            "Měna": "CZK",
            "Typ": "Převod",
        },
    )
    assert normalized.data is not None

    result = classify_import_row(
        source=ImportSource.raiffeisenbank,
        normalized_data=normalized.data,
    )

    assert isinstance(result, NeedsReviewPostingIntent)
    assert _review_code(result) is PostingIntentIssueCode.ambiguous_transfer_type


@pytest.mark.parametrize(
    ("source_type", "amount", "expected_type", "expected_classification"),
    [
        ("income", "10", TransactionType.income, TransactionClassification.real_income),
        ("expense", "-10", TransactionType.expense, TransactionClassification.real_expense),
        (
            "internal transfer",
            "10",
            TransactionType.transfer,
            TransactionClassification.internal_transfer,
        ),
        ("unknown", "10", TransactionType.income, TransactionClassification.real_income),
        ("unknown", "-10", TransactionType.expense, TransactionClassification.real_expense),
    ],
)
def test_manual_normalization_and_classification_composition(
    source_type: str,
    amount: str,
    expected_type: TransactionType,
    expected_classification: TransactionClassification,
) -> None:
    normalized = normalize_import_row(
        source=ImportSource.manual,
        account_id="account-a",
        raw_data={
            "Date": "2026-07-23",
            "Amount": amount,
            "Currency": "EUR",
            "Type": source_type,
        },
    )
    assert normalized.data is not None

    result = classify_import_row(source=ImportSource.manual, normalized_data=normalized.data)

    assert isinstance(result, TransactionPostingIntent)
    assert result.transaction_type is expected_type
    assert result.transaction_classification is expected_classification


def test_trading212_normalization_and_classification_composition() -> None:
    normalized = normalize_import_row(
        source=ImportSource.trading212,
        account_id="account-a",
        raw_data={
            "Action": "Market buy",
            "Time": "2026-07-23T10:00:00Z",
            "Ticker": "VWCE",
            "No. of shares": "2",
            "Price / share": "100.50",
            "Currency (Price / share)": "EUR",
            "Total": "201",
            "Currency (Total)": "EUR",
            "ID": "trade-1",
        },
    )
    assert normalized.data is not None
    assert normalized.data["schema_version"] == 2
    assert normalized.data["action"] == "buy"

    result = classify_import_row(source=ImportSource.trading212, normalized_data=normalized.data)

    assert isinstance(result, InvestmentEventPostingIntent)
    assert result.investment_event_type is InvestmentEventType.trade


@pytest.mark.parametrize("source_type", ["trade payment", "trade fill", "trade refund"])
def test_anycoin_individual_trade_rows_need_grouping_before_classification(
    source_type: str,
) -> None:
    normalized = normalize_import_row(
        source=ImportSource.anycoin,
        account_id="account-a",
        raw_data={
            "Type": source_type,
            "Order ID": "order-1",
            "Date": "2026-07-23T10:00:00Z",
            "Amount": "1.25",
            "Currency": "EUR",
            "anycoin TX ID": "anycoin-1",
        },
    )
    assert normalized.data is not None
    assert normalized.data["type"] == source_type

    result = classify_import_row(source=ImportSource.anycoin, normalized_data=normalized.data)

    assert isinstance(result, NeedsReviewPostingIntent)
    assert _review_code(result) is PostingIntentIssueCode.investment_normalization_required


def test_review_intent_serialization_does_not_echo_untrusted_values() -> None:
    result = classify_import_row(
        source=ImportSource.trading212,
        normalized_data=_normalized(
            ImportSource.trading212,
            source_type="secret unsupported action",
            description="sensitive description",
            external_id="sensitive-id",
        ),
    )

    assert isinstance(result, NeedsReviewPostingIntent)
    assert result.model_dump(mode="json") == {
        "schema_version": 1,
        "target": PostingIntentTarget.needs_review.value,
        "errors": [
            {
                "field": "normalized_data",
                "code": PostingIntentIssueCode.investment_normalization_required.value,
                "message": "Source-specific investment normalization is required before classification.",
            }
        ],
    }


def _anycoin_event(*, action: str = "buy") -> dict[str, object]:
    transfer = action == "asset_transfer"
    return {
        "schema_version": 2,
        "source": "anycoin",
        "kind": "investment_event",
        "date": "2026-07-23T10:00:00+00:00",
        "action": action,
        "external_id": "provider-id",
        "order_id": None if transfer else "order-1",
        "raw_action": "grouped_trade",
        "asset": {"symbol": "BTC", "isin": None, "name": None, "asset_type_hint": "crypto"},
        "quantity": "1",
        "price": None if transfer else {"amount": "100", "currency": "EUR"},
        "total": None if transfer else {"amount": "100", "currency": "EUR"},
        "fee": None,
        "conversion": None,
        "realized_pnl": None,
        "is_promotional": False,
        "note": None,
        "asset_direction": "in" if transfer else None,
    }


@pytest.mark.parametrize(
    ("changes", "expected_intent"),
    [
        ({}, True),
        ({"order_id": None}, False),
        ({"order_id": "  "}, False),
        ({"asset_direction": "in"}, False),
    ],
)
def test_anycoin_grouped_trade_requires_canonical_order_contract(
    changes: dict[str, object], expected_intent: bool
) -> None:
    payload = _anycoin_event()
    payload.update(changes)
    result = classify_import_row(source=ImportSource.anycoin, normalized_data=payload)
    assert isinstance(result, InvestmentEventPostingIntent) is expected_intent


@pytest.mark.parametrize(
    ("changes", "expected_intent"),
    [
        ({}, True),
        ({"asset_direction": "out"}, True),
        ({"asset_direction": None}, False),
        ({"order_id": "x"}, False),
    ],
)
def test_anycoin_asset_transfer_requires_direction_without_order_id(
    changes: dict[str, object], expected_intent: bool
) -> None:
    payload = _anycoin_event(action="asset_transfer")
    payload.update(changes)
    result = classify_import_row(source=ImportSource.anycoin, normalized_data=payload)
    assert isinstance(result, InvestmentEventPostingIntent) is expected_intent


def test_trading212_schema_v2_rejects_anycoin_only_fields() -> None:
    normalized = normalize_import_row(
        source=ImportSource.trading212,
        account_id="account-a",
        raw_data={
            "Action": "Market buy",
            "Time": "2026-07-23T10:00:00Z",
            "Ticker": "VWCE",
            "No. of shares": "2",
            "Total": "12",
            "Currency (Total)": "EUR",
        },
    )
    assert normalized.data is not None
    valid = classify_import_row(source=ImportSource.trading212, normalized_data=normalized.data)
    payload = dict(normalized.data)
    payload["order_id"] = "not-allowed"
    with_order = classify_import_row(source=ImportSource.trading212, normalized_data=payload)
    payload["order_id"] = None
    payload["asset_direction"] = "in"
    with_direction = classify_import_row(source=ImportSource.trading212, normalized_data=payload)
    assert isinstance(valid, InvestmentEventPostingIntent)
    assert isinstance(with_order, NeedsReviewPostingIntent)
    assert isinstance(with_direction, NeedsReviewPostingIntent)
