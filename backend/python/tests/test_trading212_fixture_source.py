from pathlib import Path

import pytest

from app.db.models.enums import ImportSource
from app.modules.imports.normalizers import normalize_import_row
from app.modules.imports.parsers import PARSER_REGISTRY, parse_csv, parse_import_file

FIXTURES = Path(__file__).parent / "fixtures" / "imports" / "trading212"
FORBIDDEN_MARKERS = (
    "BEGIN PRIVATE KEY",
    "Bearer ",
    "api_token",
    "access_token",
)


def _rows(name: str):
    return parse_import_file(
        ImportSource.trading212,
        (FIXTURES / name).read_bytes(),
        encoding=None,
    )


def test_fixture_is_synthetic_and_uses_the_generic_strict_parser() -> None:
    content = (FIXTURES / "activity.csv").read_text(encoding="utf-8")
    assert PARSER_REGISTRY[ImportSource.trading212] is parse_csv
    assert "T212-FAKE-DEPOSIT-001" in content
    assert "T212-FAKE-BUY-001" in content
    assert "T212-FAKE-DIVIDEND-001" in content
    assert "TEST00000001" in content
    assert "TSTETF" in content
    assert not any(marker in content for marker in FORBIDDEN_MARKERS)


def test_main_fixture_normalizes_to_three_exact_schema_v2_events() -> None:
    rows = _rows("activity.csv")
    results = [
        normalize_import_row(
            source=ImportSource.trading212,
            account_id="fixture-account",
            raw_data=row.raw_data,
        )
        for row in rows
    ]

    assert [row.row_number for row in rows] == [2, 3, 4]
    assert all(row.validation_errors is None for row in rows)
    assert all(result.validation_errors is None for result in results)
    assert [result.data["action"] for result in results if result.data] == [
        "cash_deposit",
        "buy",
        "dividend",
    ]
    assert [result.data["external_id"] for result in results if result.data] == [
        "T212-FAKE-DEPOSIT-001",
        "T212-FAKE-BUY-001",
        "T212-FAKE-DIVIDEND-001",
    ]
    buy = results[1].data
    assert buy is not None
    assert buy["schema_version"] == 2
    assert buy["source"] == "trading212"
    assert buy["asset"] == {
        "symbol": "TSTETF",
        "isin": "TEST00000001",
        "name": "Fictitious Test ETF",
        "asset_type_hint": "etf",
    }
    assert buy["quantity"] == "2"
    assert buy["price"] == {"amount": "100", "currency": "EUR"}
    assert buy["total"] == {"amount": "200", "currency": "EUR"}
    assert buy["fee"] is None


def test_bom_and_row_order_do_not_change_provider_identity() -> None:
    content = (FIXTURES / "activity.csv").read_bytes()
    baseline = _rows("activity.csv")
    bom = parse_import_file(ImportSource.trading212, b"\xef\xbb\xbf" + content, encoding=None)
    lines = content.decode("utf-8").splitlines()
    reordered = parse_import_file(
        ImportSource.trading212,
        ("\n".join([lines[0], *reversed(lines[1:])]) + "\n").encode(),
        encoding="utf-8",
    )

    def identities(rows):
        values = []
        for row in rows:
            result = normalize_import_row(
                source=ImportSource.trading212,
                account_id="fixture-account",
                raw_data=row.raw_data,
            )
            assert result.data is not None
            values.append(result.data["external_id"])
        return set(values)

    assert identities(baseline) == identities(bom) == identities(reordered)


def test_issue_fixture_preserves_every_physical_data_row() -> None:
    rows = _rows("activity_issues.csv")
    assert len(rows) == 9
    assert [row.row_number for row in rows] == list(range(2, 11))
    assert rows[-2].validation_errors == {"code": "blank_row"}
    assert rows[-1].validation_errors == {
        "code": "column_count_mismatch",
        "expected": 19,
        "actual": 13,
    }

    normalization_errors = []
    for row in rows[:-2]:
        assert row.validation_errors is None
        result = normalize_import_row(
            source=ImportSource.trading212,
            account_id="fixture-account",
            raw_data=row.raw_data,
        )
        assert result.data is None
        normalization_errors.extend(result.validation_errors or [])
    assert {error["code"] for error in normalization_errors} >= {
        "unsupported_action",
        "unsupported_linked_cash_transaction",
        "required",
        "invalid",
        "paired_required",
    }


@pytest.mark.parametrize(
    "value",
    [
        "0",
        "0.000000",
    ],
)
def test_zero_fee_placeholder_is_not_persisted_as_fee(value: str) -> None:
    row = _rows("activity.csv")[1]
    raw = dict(row.raw_data)
    raw["Currency conversion fee"] = value
    raw["Currency (Currency conversion fee)"] = ""
    result = normalize_import_row(
        source=ImportSource.trading212,
        account_id="fixture-account",
        raw_data=raw,
    )
    assert result.validation_errors is None
    assert result.data is not None
    assert result.data["fee"] is None
