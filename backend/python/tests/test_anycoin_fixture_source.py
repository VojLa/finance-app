from pathlib import Path

from app.db.models.enums import ImportRowStatus, ImportSource
from app.modules.imports.anycoin import AnycoinBatchRow, normalize_anycoin_batch
from app.modules.imports.parsers import PARSER_REGISTRY, parse_csv, parse_import_file

FIXTURES = Path(__file__).parent / "fixtures" / "imports" / "anycoin"
FORBIDDEN_MARKERS = (
    "BEGIN PRIVATE KEY",
    "Bearer ",
    "api_token",
    "access_token",
)


def _rows(name: str):
    return parse_import_file(
        ImportSource.anycoin,
        (FIXTURES / name).read_bytes(),
        encoding=None,
    )


def _outcomes(rows, *, account_id: str = "fixture-account"):
    return normalize_anycoin_batch(
        account_id=account_id,
        rows=[
            AnycoinBatchRow(
                row_id=f"row-{row.row_number}",
                row_number=row.row_number,
                raw_data=row.raw_data,
            )
            for row in rows
            if row.validation_errors is None
        ],
    )


def test_fixture_is_synthetic_and_uses_generic_parser_plus_batch_grouping() -> None:
    content = (FIXTURES / "history.csv").read_text(encoding="utf-8")
    assert PARSER_REGISTRY[ImportSource.anycoin] is parse_csv
    assert "AC-FAKE-ORDER-001" in content
    assert "AC-FAKE-PAY-001" in content
    assert "AC-FAKE-FILL-001" in content
    assert "AC-FAKE-REFUND-001" in content
    assert not any(marker in content for marker in FORBIDDEN_MARKERS)


def test_main_fixture_builds_one_exact_grouped_buy_with_anchor_members() -> None:
    rows = _rows("history.csv")
    outcomes = _outcomes(rows)
    by_row = {outcome.row_id: outcome for outcome in outcomes}
    anchor = by_row["row-3"]

    assert [row.row_number for row in rows] == [2, 3, 4]
    assert anchor.status is ImportRowStatus.pending
    assert anchor.validation_errors is None
    assert anchor.data == {
        "schema_version": 2,
        "source": "anycoin",
        "kind": "investment_event",
        "date": "2026-07-20T09:00:01+00:00",
        "action": "buy",
        "external_id": "AC-FAKE-FILL-001",
        "order_id": "AC-FAKE-ORDER-001",
        "raw_action": "grouped_trade",
        "asset": {
            "symbol": "BTC",
            "isin": None,
            "name": None,
            "asset_type_hint": "crypto",
        },
        "quantity": "0.01",
        "price": {"amount": "49000", "currency": "EUR"},
        "total": {"amount": "490", "currency": "EUR"},
        "fee": None,
        "conversion": None,
        "realized_pnl": None,
        "is_promotional": False,
        "note": None,
        "asset_direction": None,
    }
    assert by_row["row-2"].status is ImportRowStatus.skipped
    assert by_row["row-2"].data == {
        "schema_version": 2,
        "source": "anycoin",
        "kind": "group_member",
        "order_id": "AC-FAKE-ORDER-001",
        "anchor_row_id": "row-3",
        "member_role": "payment",
    }
    assert by_row["row-4"].status is ImportRowStatus.skipped
    assert by_row["row-4"].data["anchor_row_id"] == "row-3"
    assert by_row["row-4"].data["member_role"] == "refund"


def test_group_anchor_and_identity_are_order_independent() -> None:
    content = (FIXTURES / "history.csv").read_bytes()
    baseline = _outcomes(_rows("history.csv"))
    lines = content.decode("utf-8").splitlines()
    reordered_rows = parse_import_file(
        ImportSource.anycoin,
        ("\n".join([lines[0], *reversed(lines[1:])]) + "\n").encode(),
        encoding="utf-8",
    )
    reordered = _outcomes(reordered_rows)

    def canonical(outcomes):
        return next(
            outcome
            for outcome in outcomes
            if outcome.data and outcome.data.get("kind") == "investment_event"
        ).data

    assert canonical(baseline) == canonical(reordered)


def test_bom_preserves_group_contract() -> None:
    content = (FIXTURES / "history.csv").read_bytes()
    rows = parse_import_file(ImportSource.anycoin, b"\xef\xbb\xbf" + content, encoding=None)
    canonical = next(
        outcome
        for outcome in _outcomes(rows)
        if outcome.data and outcome.data.get("kind") == "investment_event"
    )
    assert canonical.data["external_id"] == "AC-FAKE-FILL-001"
    assert canonical.data["quantity"] == "0.01"
    assert canonical.data["total"] == {"amount": "490", "currency": "EUR"}


def test_issue_fixture_preserves_rows_and_fails_closed() -> None:
    rows = _rows("history_issues.csv")
    assert len(rows) == 23
    assert [row.row_number for row in rows] == list(range(2, 25))
    assert rows[-2].validation_errors == {"code": "blank_row"}
    assert rows[-1].validation_errors == {
        "code": "column_count_mismatch",
        "expected": 6,
        "actual": 5,
    }
    outcomes = _outcomes(rows)
    assert len(outcomes) == 21
    assert all(outcome.status is ImportRowStatus.needs_review for outcome in outcomes)
    codes = {error["code"] for outcome in outcomes for error in outcome.validation_errors or []}
    assert codes >= {
        "missing_order_id",
        "incomplete_order",
        "multiple_asset_currencies",
        "multiple_fiat_currencies",
        "contradictory_trade_direction",
        "conflicting_external_id",
        "unsupported_anycoin_row",
    }
    assert all(
        not outcome.data or outcome.data.get("kind") != "investment_event" for outcome in outcomes
    )


def test_group_identity_is_account_scoped() -> None:
    rows = _rows("history.csv")
    first = next(
        outcome for outcome in _outcomes(rows, account_id="account-a") if outcome.deduplication_key
    )
    second = next(
        outcome for outcome in _outcomes(rows, account_id="account-b") if outcome.deduplication_key
    )
    assert first.deduplication_key != second.deduplication_key
