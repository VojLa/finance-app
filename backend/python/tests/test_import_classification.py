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
    InvestmentAction,
    InvestmentEventPostingIntent,
    NeedsReviewPostingIntent,
    PostingIntentIssueCode,
    PostingIntentTarget,
    TransactionPostingIntent,
    classify_import_row,
)


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
        (
            "income",
            "10",
            TransactionType.income,
            TransactionClassification.real_income,
        ),
        (
            "  PŘÍCHOZÍ \t PLATBA ",
            "10",
            TransactionType.income,
            TransactionClassification.real_income,
        ),
        (
            "expense",
            "-10",
            TransactionType.expense,
            TransactionClassification.real_expense,
        ),
        (
            " Odchozí   platba ",
            "-10",
            TransactionType.expense,
            TransactionClassification.real_expense,
        ),
        (
            "transfer",
            "10",
            TransactionType.transfer,
            TransactionClassification.internal_transfer,
        ),
        (
            "INTERNAL TRANSFER",
            "-10",
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


@pytest.mark.parametrize(
    ("source_type", "amount"),
    [("income", "-1"), ("expense", "1")],
)
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


@pytest.mark.parametrize("source", list(ImportSource))
def test_zero_amount_needs_review(source: ImportSource) -> None:
    source_type = (
        "income"
        if source
        in {
            ImportSource.raiffeisenbank,
            ImportSource.manual,
        }
        else "deposit"
    )
    result = classify_import_row(
        source=source,
        normalized_data=_normalized(source, amount="0.000", source_type=source_type),
    )

    assert isinstance(result, NeedsReviewPostingIntent)
    assert _review_code(result) is PostingIntentIssueCode.zero_amount


def test_description_and_counterparty_do_not_influence_transaction_classification() -> None:
    first_data = _normalized(
        ImportSource.manual,
        amount="-5",
        source_type="unknown",
        description="refund internal transfer loan income",
        counterparty="Loan provider",
    )
    second_data = _normalized(
        ImportSource.manual,
        amount="-5",
        source_type="unknown",
        description="ordinary purchase",
        counterparty="Merchant",
    )

    first = classify_import_row(
        source=ImportSource.manual,
        normalized_data=first_data,
    )
    second = classify_import_row(
        source=ImportSource.manual,
        normalized_data=second_data,
    )

    assert isinstance(first, TransactionPostingIntent)
    assert isinstance(second, TransactionPostingIntent)
    assert first == second
    assert first.transaction_classification is TransactionClassification.real_expense


@pytest.mark.parametrize("source", [ImportSource.trading212, ImportSource.anycoin])
@pytest.mark.parametrize(
    ("source_type", "event_type", "action"),
    [
        ("  MARKET   BUY ", InvestmentEventType.trade, InvestmentAction.buy),
        ("PRODEJ", InvestmentEventType.trade, InvestmentAction.sell),
        ("deposit", InvestmentEventType.cash_deposit, None),
        ("withdrawal", InvestmentEventType.cash_withdrawal, None),
        ("Dividend (Dividend)", InvestmentEventType.dividend, None),
        ("interest on cash", InvestmentEventType.interest, None),
        ("FX conversion", InvestmentEventType.currency_conversion, None),
        ("asset transfer", InvestmentEventType.asset_transfer, None),
        ("commission", InvestmentEventType.fee, None),
        ("staking reward", InvestmentEventType.staking_reward, None),
        ("free shares", InvestmentEventType.airdrop, None),
    ],
)
def test_investment_action_families_map_to_canonical_events(
    source: ImportSource,
    source_type: str,
    event_type: InvestmentEventType,
    action: InvestmentAction | None,
) -> None:
    result = classify_import_row(
        source=source,
        normalized_data=_normalized(source, amount="-12.5", source_type=source_type),
    )

    assert isinstance(result, InvestmentEventPostingIntent)
    assert result.investment_event_type is event_type
    assert result.action is action
    assert result.amount == Decimal("-12.5")


@pytest.mark.parametrize(
    ("source_type", "expected_event", "expected_action"),
    [
        ("purchase", InvestmentEventType.trade, InvestmentAction.buy),
        ("nákup", InvestmentEventType.trade, InvestmentAction.buy),
        ("take profit", InvestmentEventType.trade, InvestmentAction.sell),
        ("crypto sale", InvestmentEventType.trade, InvestmentAction.sell),
        ("fiat deposit", InvestmentEventType.cash_deposit, None),
        ("vklad", InvestmentEventType.cash_deposit, None),
        ("crypto withdrawal", InvestmentEventType.cash_withdrawal, None),
        ("výběr", InvestmentEventType.cash_withdrawal, None),
        ("dividend (tax exempted)", InvestmentEventType.dividend, None),
        ("cash interest", InvestmentEventType.interest, None),
        ("swap", InvestmentEventType.currency_conversion, None),
        ("portfolio transfer", InvestmentEventType.asset_transfer, None),
        ("currency conversion fee", InvestmentEventType.fee, None),
        ("eth2 staking reward", InvestmentEventType.staking_reward, None),
        ("token distribution", InvestmentEventType.airdrop, None),
    ],
)
def test_investment_allowlist_variants_are_exact(
    source_type: str,
    expected_event: InvestmentEventType,
    expected_action: InvestmentAction | None,
) -> None:
    result = classify_import_row(
        source=ImportSource.anycoin,
        normalized_data=_normalized(
            ImportSource.anycoin,
            source_type=source_type,
        ),
    )

    assert isinstance(result, InvestmentEventPostingIntent)
    assert result.investment_event_type is expected_event
    assert result.action is expected_action


@pytest.mark.parametrize(
    "source_type",
    [None, "", [], "market buy with bonus", "refund", "loan", "trade"],
)
def test_missing_unknown_or_non_exact_investment_action_needs_review(
    source_type: object | None,
) -> None:
    result = classify_import_row(
        source=ImportSource.anycoin,
        normalized_data=_normalized(
            ImportSource.anycoin,
            source_type=source_type,
            description="free share refund transfer",
        ),
    )

    assert isinstance(result, NeedsReviewPostingIntent)
    expected = (
        PostingIntentIssueCode.missing_investment_type
        if source_type is None or source_type == ""
        else PostingIntentIssueCode.unsupported_investment_type
    )
    assert _review_code(result) is expected


@pytest.mark.parametrize("source_type", ["card debit", "card cost", "new card cost"])
def test_trading212_card_cost_requires_linked_cash_contract(source_type: str) -> None:
    result = classify_import_row(
        source=ImportSource.trading212,
        normalized_data=_normalized(
            ImportSource.trading212,
            amount="-19.70",
            source_type=source_type,
        ),
    )

    assert isinstance(result, NeedsReviewPostingIntent)
    assert _review_code(result) is PostingIntentIssueCode.unsupported_linked_cash_transaction


def test_description_cannot_turn_investment_deposit_into_airdrop() -> None:
    result = classify_import_row(
        source=ImportSource.trading212,
        normalized_data=_normalized(
            ImportSource.trading212,
            source_type="deposit",
            description="Free share bonus",
            counterparty="Promotion",
        ),
    )

    assert isinstance(result, InvestmentEventPostingIntent)
    assert result.investment_event_type is InvestmentEventType.cash_deposit


@pytest.mark.parametrize("schema_version", [None, 0, 2, True, "1"])
def test_unsupported_normalized_schema_version_is_deterministic(
    schema_version: object,
) -> None:
    data = _normalized(ImportSource.manual)
    data["schema_version"] = schema_version

    result = classify_import_row(
        source=ImportSource.manual,
        normalized_data=data,
    )

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

    result = classify_import_row(
        source=ImportSource.manual,
        normalized_data=data,
    )

    assert isinstance(result, NeedsReviewPostingIntent)
    assert _review_code(result) is expected_code


def test_invalid_normalized_payload_needs_review() -> None:
    result = classify_import_row(
        source=ImportSource.manual,
        normalized_data=[],
    )

    assert isinstance(result, NeedsReviewPostingIntent)
    assert _review_code(result) is PostingIntentIssueCode.invalid_payload


def test_posting_intent_is_immutable_versioned_and_json_serializable() -> None:
    normalized_data = _normalized(
        ImportSource.manual,
        amount="-123.4500",
        source_type="expense",
    )
    original = normalized_data.copy()

    result = classify_import_row(
        source=ImportSource.manual,
        normalized_data=normalized_data,
    )

    assert isinstance(result, TransactionPostingIntent)
    assert normalized_data == original
    assert isinstance(result.amount, Decimal)
    assert result.model_dump(mode="json") == {
        "schema_version": 1,
        "target": PostingIntentTarget.transaction.value,
        "source": ImportSource.manual.value,
        "date": "2026-07-23",
        "amount": "-123.4500",
        "currency": "EUR",
        "transaction_type": TransactionType.expense.value,
        "transaction_classification": TransactionClassification.real_expense.value,
    }
    with pytest.raises(ValidationError):
        result.amount = Decimal("1")  # type: ignore[misc]


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
                "field": "type",
                "code": PostingIntentIssueCode.unsupported_investment_type.value,
                "message": "The investment action is not supported by the explicit allowlist.",
            }
        ],
    }
