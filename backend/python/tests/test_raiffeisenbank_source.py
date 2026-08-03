from __future__ import annotations

from pathlib import Path

import pytest

from app.db.models.enums import (
    ImportSource,
    TransactionClassification,
    TransactionType,
)
from app.modules.imports.classification import (
    NeedsReviewPostingIntent,
    PostingIntentIssueCode,
    TransactionPostingIntent,
    classify_import_row,
)
from app.modules.imports.normalizers import normalize_import_row
from app.modules.imports.parsers import (
    PARSER_REGISTRY,
    ImportParseError,
    parse_csv,
    parse_import_file,
    parse_raiffeisenbank,
)
from app.modules.imports.raiffeisenbank import STATEMENT_KIND_FIELD

FIXTURES = Path(__file__).parent / "fixtures" / "imports" / "raiffeisenbank"


def _parse_fixture(name: str, *, encoding: str | None = "utf-8"):
    return parse_import_file(
        ImportSource.raiffeisenbank,
        (FIXTURES / name).read_bytes(),
        encoding=encoding,
    )


def _account_raw(**overrides: str | None) -> dict[str, str | None]:
    raw: dict[str, str | None] = {
        STATEMENT_KIND_FIELD: "account_statement",
        "Datum provedení": "14. 6. 2026 12:05",
        "Zaúčtovaná částka": "-1 234,50",
        "Měna účtu": "czk",
        "Typ transakce": "Odchozí platba",
        "Zpráva": "První",
        "Poznámka": "Druhá",
        "Vlastní poznámka": "První",
        "Název protiúčtu": "Fiktivní protistrana",
        "Id transakce": " RB-FAKE-001 ",
    }
    raw.update(overrides)
    return raw


def _card_raw(**overrides: str | None) -> dict[str, str | None]:
    raw: dict[str, str | None] = {
        STATEMENT_KIND_FIELD: "card_statement",
        "Číslo kreditní karty": "FAKE-CARD-0000",
        "Datum transakce": "14.06.2026 12:05:30",
        "Zaúčtovaná částka": "-50.00",
        "Měna zaúčtování": "CZK",
        "Typ transakce": "Platba kartou",
        "Název Obchodníka": "Fiktivní obchod",
        "Popis/Místo transakce": "Fiktivní provozovna",
        "Město": "Testov",
        "Vlastní poznámka": "Testovací poznámka",
    }
    raw.update(overrides)
    return raw


def test_parser_registry_uses_only_raiffeisenbank_specific_parser() -> None:
    assert PARSER_REGISTRY == {
        ImportSource.raiffeisenbank: parse_raiffeisenbank,
        ImportSource.trading212: parse_csv,
        ImportSource.anycoin: parse_csv,
        ImportSource.manual: parse_csv,
    }


@pytest.mark.parametrize(
    ("fixture", "kind", "row_count"),
    [
        ("account_statement.csv", "account_statement", 3),
        ("card_statement.csv", "card_statement", 3),
    ],
)
def test_parser_detects_supported_header_once_and_preserves_rows(
    fixture: str,
    kind: str,
    row_count: int,
) -> None:
    rows = _parse_fixture(fixture)

    assert len(rows) == row_count
    assert [row.row_number for row in rows] == list(range(2, row_count + 2))
    assert all(row.raw_data[STATEMENT_KIND_FIELD] == kind for row in rows)


def test_parser_supports_utf8_bom_and_trimmed_headers() -> None:
    content = (
        "\ufeff Datum provedení ; Zaúčtovaná částka ; Měna účtu \n14.06.2026;1,00;CZK\n"
    ).encode()

    rows = parse_import_file(ImportSource.raiffeisenbank, content, encoding=None)

    assert rows[0].raw_data["Datum provedení"] == "14.06.2026"
    assert rows[0].raw_data[STATEMENT_KIND_FIELD] == "account_statement"


def test_parser_honors_explicit_encoding() -> None:
    content = ("Datum provedení;Zaúčtovaná částka;Měna účtu\n14.06.2026;1,00;CZK\n").encode(
        "cp1250"
    )

    rows = parse_import_file(ImportSource.raiffeisenbank, content, encoding="cp1250")

    assert rows[0].raw_data["Měna účtu"] == "CZK"


@pytest.mark.parametrize(
    "content",
    [
        b"date;amount;currency\n2026-06-14;1;CZK\n",
        (
            "Datum provedení;Zaúčtovaná částka;Měna účtu;"
            "Datum transakce;Měna zaúčtování;Číslo kreditní karty\n"
            "14.06.2026;1;CZK;14.06.2026;CZK;FAKE-0000\n"
        ).encode(),
        b"",
        "Datum provedení;Zaúčtovaná částka;Měna účtu\n".encode(),
        ('Datum provedení;Zaúčtovaná částka;Měna účtu\n"14.06.2026;1;CZK\n').encode(),
    ],
    ids=["unknown-header", "mixed-header", "empty", "header-only", "malformed"],
)
def test_parser_rejects_fatal_file_errors_without_echoing_content(content: bytes) -> None:
    with pytest.raises(ImportParseError) as exc_info:
        parse_import_file(ImportSource.raiffeisenbank, content, encoding="utf-8")

    message = str(exc_info.value)
    assert "FAKE-0000" not in message
    assert "Zaúčtovaná částka" not in message


def test_parser_preserves_blank_and_column_mismatch_rows_as_issues() -> None:
    rows = _parse_fixture("account_statement_issues.csv")

    assert len(rows) == 6
    assert rows[4].validation_errors == {"code": "blank_row"}
    assert rows[5].validation_errors == {
        "code": "column_count_mismatch",
        "expected": 9,
        "actual": 4,
    }
    assert rows[4].row_number == 6
    assert rows[5].row_number == 7


def test_account_normalizer_preserves_signed_decimal_and_provider_identity() -> None:
    result = normalize_import_row(
        source=ImportSource.raiffeisenbank,
        account_id="account-a",
        raw_data=_account_raw(),
    )

    assert result.validation_errors is None
    assert result.data == {
        "schema_version": 1,
        "source": "raiffeisenbank",
        "date": "2026-06-14T12:05:00",
        "amount": "-1234.5",
        "currency": "CZK",
        "external_id": "RB-FAKE-001",
        "description": "První | Druhá",
        "counterparty": "Fiktivní protistrana",
        "type": "Odchozí platba",
    }


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("+10000", "10000"),
        ("-123.45", "-123.45"),
        ("-1 234,50", "-1234.5"),
        ("1\u00a0234,50", "1234.5"),
        ("1.234,50", "1234.5"),
        ("1,234.50", "1234.5"),
    ],
)
def test_normalizer_uses_exact_decimal_without_losing_sign(value: str, expected: str) -> None:
    result = normalize_import_row(
        source=ImportSource.raiffeisenbank,
        account_id="account-a",
        raw_data=_account_raw(**{"Zaúčtovaná částka": value}),
    )
    assert result.data is not None
    assert result.data["amount"] == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("14. 6. 2026", "2026-06-14"),
        ("14.06.2026", "2026-06-14"),
        ("14. 6. 2026 12:05", "2026-06-14T12:05:00"),
        ("14.06.2026 12:05:30", "2026-06-14T12:05:30"),
    ],
)
def test_normalizer_supports_exact_raiffeisenbank_dates(value: str, expected: str) -> None:
    result = normalize_import_row(
        source=ImportSource.raiffeisenbank,
        account_id="account-a",
        raw_data=_account_raw(**{"Datum provedení": value}),
    )
    assert result.data is not None
    assert result.data["date"] == expected


def test_card_normalizer_uses_deterministic_fallback_identity() -> None:
    first = normalize_import_row(
        source=ImportSource.raiffeisenbank,
        account_id="account-a",
        raw_data=_card_raw(),
    )
    reordered = normalize_import_row(
        source=ImportSource.raiffeisenbank,
        account_id="account-a",
        raw_data=dict(reversed(list(_card_raw().items()))),
    )
    other_account = normalize_import_row(
        source=ImportSource.raiffeisenbank,
        account_id="account-b",
        raw_data=_card_raw(),
    )

    assert first.data is not None
    assert first.data["external_id"].startswith("rb-sha256-")
    assert first.data["counterparty"] == "Fiktivní obchod"
    assert first.data["description"] == (
        "Fiktivní provozovna | Fiktivní obchod | Testov | Testovací poznámka | Platba kartou"
    )
    assert first.data == reordered.data
    assert first.deduplication_key == reordered.deduplication_key
    assert other_account.data is not None
    assert first.data["external_id"] != other_account.data["external_id"]
    assert first.deduplication_key != other_account.deduplication_key


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"Datum provedení": None}, "date"),
        ({"Zaúčtovaná částka": None}, "amount"),
        ({"Měna účtu": None}, "currency"),
        ({"Zaúčtovaná částka": "not-decimal"}, "amount"),
        ({"Datum provedení": "not-date"}, "date"),
        ({"Měna účtu": "EU"}, "currency"),
    ],
)
def test_normalizer_persists_structured_issues(
    overrides: dict[str, str | None],
    field: str,
) -> None:
    result = normalize_import_row(
        source=ImportSource.raiffeisenbank,
        account_id="account-a",
        raw_data=_account_raw(**overrides),
    )
    assert result.data is None
    assert result.deduplication_key is None
    assert any(issue["field"] == field for issue in result.validation_errors or [])


@pytest.mark.parametrize(
    ("amount", "source_type", "expected_type", "expected_classification"),
    [
        ("100", "Příchozí platba", TransactionType.income, TransactionClassification.real_income),
        ("-100", "Odchozí platba", TransactionType.expense, TransactionClassification.real_expense),
        ("-100", "Platba kartou", TransactionType.expense, TransactionClassification.real_expense),
        ("100", "", TransactionType.income, TransactionClassification.real_income),
        ("-100", "Neznámý typ", TransactionType.expense, TransactionClassification.real_expense),
        (
            "-100",
            "Interní převod",
            TransactionType.transfer,
            TransactionClassification.internal_transfer,
        ),
    ],
)
def test_classifier_maps_supported_source_type_and_sign(
    amount: str,
    source_type: str,
    expected_type: TransactionType,
    expected_classification: TransactionClassification,
) -> None:
    normalized = normalize_import_row(
        source=ImportSource.raiffeisenbank,
        account_id="account-a",
        raw_data=_account_raw(
            **{
                "Zaúčtovaná částka": amount,
                "Typ transakce": source_type,
            }
        ),
    )
    assert normalized.data is not None
    intent = classify_import_row(
        source=ImportSource.raiffeisenbank,
        normalized_data=normalized.data,
    )
    assert isinstance(intent, TransactionPostingIntent)
    assert str(intent.amount) == amount
    assert intent.transaction_type is expected_type
    assert intent.transaction_classification is expected_classification


@pytest.mark.parametrize(
    ("amount", "source_type", "issue_code"),
    [
        ("-1", "Příchozí platba", PostingIntentIssueCode.conflicting_transaction_type),
        ("1", "Odchozí platba", PostingIntentIssueCode.conflicting_transaction_type),
        ("-1", "Převod", PostingIntentIssueCode.ambiguous_transfer_type),
        ("0", "", PostingIntentIssueCode.zero_amount),
    ],
)
def test_classifier_routes_unsafe_rows_to_review(
    amount: str,
    source_type: str,
    issue_code: PostingIntentIssueCode,
) -> None:
    normalized = normalize_import_row(
        source=ImportSource.raiffeisenbank,
        account_id="account-a",
        raw_data=_account_raw(
            **{
                "Zaúčtovaná částka": amount,
                "Typ transakce": source_type,
            }
        ),
    )
    assert normalized.data is not None
    intent = classify_import_row(
        source=ImportSource.raiffeisenbank,
        normalized_data=normalized.data,
    )
    assert isinstance(intent, NeedsReviewPostingIntent)
    assert [issue.code for issue in intent.errors] == [issue_code]
