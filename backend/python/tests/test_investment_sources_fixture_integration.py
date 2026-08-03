from __future__ import annotations

import asyncio
import hashlib
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from support import investment_fixture_e2e as support

from app.db.models.enums import (
    ImportRowStatus,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
)
from app.db.models.holdings import HoldingModel
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.transactions import TransactionModel
from app.main import create_app

pytestmark = pytest.mark.skipif(
    not support.DATABASE_URL,
    reason="DATABASE_URL is required",
)


async def _evidence(account_id: str) -> dict[str, Any]:
    db = support.engine()
    async with AsyncSession(db) as session:
        rows = tuple(
            (
                await session.scalars(
                    select(ImportRowModel)
                    .join(ImportBatchModel)
                    .where(ImportBatchModel.account_id == account_id)
                    .order_by(ImportRowModel.row_number, ImportRowModel.id)
                )
            ).all()
        )
        events = tuple(
            (
                await session.scalars(
                    select(InvestmentEventModel)
                    .where(InvestmentEventModel.account_id == account_id)
                    .order_by(InvestmentEventModel.date, InvestmentEventModel.external_id)
                )
            ).all()
        )
        movements = tuple(
            (
                await session.scalars(
                    select(InvestmentMovementModel)
                    .where(InvestmentMovementModel.account_id == account_id)
                    .order_by(
                        InvestmentMovementModel.event_id,
                        InvestmentMovementModel.kind,
                        InvestmentMovementModel.id,
                    )
                )
            ).all()
        )
        holdings = tuple(
            (
                await session.scalars(
                    select(HoldingModel).where(HoldingModel.account_id == account_id)
                )
            ).all()
        )
        transactions = int(
            await session.scalar(
                select(func.count())
                .select_from(TransactionModel)
                .where(TransactionModel.account_id == account_id)
            )
            or 0
        )
        version = str(await session.scalar(text("SHOW server_version")))
        for collection in (rows, events, movements, holdings):
            for value in collection:
                session.expunge(value)
    await db.dispose()
    return {
        "rows": rows,
        "events": events,
        "movements": movements,
        "holdings": holdings,
        "transactions": transactions,
        "postgres_version": version,
    }


@pytest.mark.parametrize(
    ("source", "filename"),
    [
        (ImportSource.trading212, "activity.csv"),
        (ImportSource.anycoin, "history.csv"),
    ],
)
def test_public_staged_fixture_api_creates_exact_canonical_investment_evidence(
    source: ImportSource,
    filename: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = f"r3-stage-{source.value}"
    user_id, account_id = asyncio.run(support.seed_identity(prefix, source=source))
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path / source.value))
    try:
        with TestClient(create_app(support.settings())) as client:
            result = support.run_stages(
                client,
                source=source,
                user_id=user_id,
                account_id=account_id,
                content=support.fixture(source, filename),
                filename=filename,
                post=False,
            )
            asyncio.run(support.seed_asset_listing(prefix, source=source))
            posted = support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=result["batch_id"],
            )
            replayed = support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=result["batch_id"],
            )

        expected_imported = 3 if source is ImportSource.trading212 else 1
        expected_skipped = 0 if source is ImportSource.trading212 else 2
        assert result["parse"] == {
            "batch_id": result["batch_id"],
            "status": "processing",
            "rows_total": 3,
            "rows_pending": 3,
            "rows_failed": 0,
        }
        assert result["normalize"]["rows_normalized"] == expected_imported
        assert result["normalize"]["rows_failed"] == 0
        assert result["normalize"]["rows_needs_review"] == 0
        assert result["deduplicate"]["rows_duplicate"] == 0
        assert result["classify"]["rows_classified"] == expected_imported
        assert result["classify"]["rows_skipped"] == expected_skipped
        assert posted["rows_imported"] == expected_imported
        assert posted["rows_skipped"] == expected_skipped
        assert posted["snapshot_refresh_status"] == "unavailable"
        assert replayed["replayed"] is True
        assert replayed["rows_imported"] == expected_imported

        evidence = asyncio.run(_evidence(account_id))
        assert evidence["postgres_version"].startswith("16.")
        assert evidence["transactions"] == 0
        if source is ImportSource.trading212:
            _assert_trading212_evidence(result["batch_id"], evidence)
        else:
            _assert_anycoin_evidence(result["batch_id"], evidence)
    finally:
        asyncio.run(support.cleanup(prefix))


def _assert_trading212_evidence(batch_id: str, evidence: dict[str, Any]) -> None:
    rows = evidence["rows"]
    events = evidence["events"]
    movements = evidence["movements"]
    holdings = evidence["holdings"]
    assert [row.status for row in rows] == [ImportRowStatus.imported] * 3
    assert all(row.created_investment_event_id for row in rows)
    assert [event.import_batch_id for event in events] == [batch_id] * 3
    assert [event.type for event in events] == [
        InvestmentEventType.cash_deposit,
        InvestmentEventType.trade,
        InvestmentEventType.dividend,
    ]
    assert [event.external_id for event in events] == [
        "T212-FAKE-DEPOSIT-001",
        "T212-FAKE-BUY-001",
        "T212-FAKE-DIVIDEND-001",
    ]
    assert [event.source for event in events] == [ImportSource.trading212] * 3
    assert {
        (movement.kind, movement.direction, movement.quantity, movement.currency)
        for movement in movements
    } == {
        (
            InvestmentMovementKind.cash,
            MovementDirection.incoming,
            Decimal("1000"),
            "EUR",
        ),
        (
            InvestmentMovementKind.asset,
            MovementDirection.incoming,
            Decimal("2"),
            "TSTETF",
        ),
        (
            InvestmentMovementKind.cash,
            MovementDirection.outgoing,
            Decimal("200"),
            "EUR",
        ),
        (
            InvestmentMovementKind.cash,
            MovementDirection.incoming,
            Decimal("5.25"),
            "EUR",
        ),
    }
    asset_movement = next(
        movement for movement in movements if movement.kind is InvestmentMovementKind.asset
    )
    assert asset_movement.price_per_unit == Decimal("100")
    assert asset_movement.value_amount == Decimal("200")
    assert asset_movement.value_currency == "EUR"
    assert asset_movement.source_symbol == "TSTETF"
    assert len(holdings) == 1
    assert holdings[0].symbol == "TSTETF"
    assert holdings[0].quantity == Decimal("2")
    assert holdings[0].avg_buy_price == Decimal("100")


def _assert_anycoin_evidence(batch_id: str, evidence: dict[str, Any]) -> None:
    rows = evidence["rows"]
    events = evidence["events"]
    movements = evidence["movements"]
    holdings = evidence["holdings"]
    anchor = rows[1]
    assert [row.status for row in rows] == [
        ImportRowStatus.skipped,
        ImportRowStatus.imported,
        ImportRowStatus.skipped,
    ]
    assert anchor.created_investment_event_id is not None
    assert rows[0].created_investment_event_id is None
    assert rows[2].created_investment_event_id is None
    assert rows[0].normalized_data["anchor_row_id"] == anchor.id
    assert rows[2].normalized_data["anchor_row_id"] == anchor.id
    assert rows[0].normalized_data["member_role"] == "payment"
    assert rows[2].normalized_data["member_role"] == "refund"
    assert len(events) == 1
    assert events[0].import_batch_id == batch_id
    assert events[0].type is InvestmentEventType.trade
    assert events[0].source is ImportSource.anycoin
    assert events[0].external_id == "AC-FAKE-FILL-001"
    assert events[0].order_id == "AC-FAKE-ORDER-001"
    assert {
        (movement.kind, movement.direction, movement.quantity, movement.currency)
        for movement in movements
    } == {
        (
            InvestmentMovementKind.asset,
            MovementDirection.incoming,
            Decimal("0.01"),
            "BTC",
        ),
        (
            InvestmentMovementKind.cash,
            MovementDirection.outgoing,
            Decimal("490"),
            "EUR",
        ),
    }
    asset_movement = next(
        movement for movement in movements if movement.kind is InvestmentMovementKind.asset
    )
    assert asset_movement.price_per_unit == Decimal("49000")
    assert asset_movement.value_amount == Decimal("490")
    assert asset_movement.value_currency == "EUR"
    assert len(holdings) == 1
    assert holdings[0].symbol == "BTC"
    assert holdings[0].quantity == Decimal("0.01")
    assert holdings[0].avg_buy_price == Decimal("49000")


@pytest.mark.parametrize(
    ("source", "main_fixture", "issue_fixture"),
    [
        (ImportSource.trading212, "activity.csv", "activity_issues.csv"),
        (ImportSource.anycoin, "history.csv", "history_issues.csv"),
    ],
)
def test_issue_fixtures_remain_persisted_review_evidence_without_canonical_rows(
    source: ImportSource,
    main_fixture: str,
    issue_fixture: str,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del main_fixture
    prefix = f"r3-issues-{source.value}"
    user_id, account_id = asyncio.run(support.seed_identity(prefix, source=source))
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path / source.value))
    try:
        with TestClient(create_app(support.settings())) as client:
            result = support.run_stages(
                client,
                source=source,
                user_id=user_id,
                account_id=account_id,
                content=support.fixture(source, issue_fixture),
                filename=issue_fixture,
                post=True,
            )
        evidence = asyncio.run(_evidence(account_id))
        assert result["parse"]["rows_total"] == len(evidence["rows"])
        assert result["parse"]["rows_failed"] >= 2
        assert result["normalize"]["rows_needs_review"] > 0
        assert result["post"]["rows_imported"] == 0
        assert evidence["events"] == ()
        assert evidence["movements"] == ()
        assert evidence["holdings"] == ()
        assert evidence["transactions"] == 0
        assert all(
            row.status
            in {
                ImportRowStatus.failed,
                ImportRowStatus.needs_review,
                ImportRowStatus.skipped,
            }
            for row in evidence["rows"]
        )
    finally:
        asyncio.run(support.cleanup(prefix))


@pytest.mark.parametrize(
    ("source", "filename", "expected_events", "expected_holdings"),
    [
        (ImportSource.trading212, "activity.csv", 3, 1),
        (ImportSource.anycoin, "history.csv", 1, 1),
    ],
)
def test_fixture_replay_variants_are_deterministic_and_account_scoped(
    source: ImportSource,
    filename: str,
    expected_events: int,
    expected_holdings: int,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = f"r3-replay-{source.value}"
    user_id, account_id = asyncio.run(
        support.seed_identity(prefix, source=source, second_account=True)
    )
    other_account = f"{prefix}-account-two"
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path / source.value))
    content = support.fixture(source, filename)
    try:
        with TestClient(create_app(support.settings())) as client:
            first = support.run_stages(
                client,
                source=source,
                user_id=user_id,
                account_id=account_id,
                content=content,
                filename=filename,
                post=False,
            )
            asyncio.run(support.seed_asset_listing(prefix, source=source))
            support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=first["batch_id"],
            )

            for repeated_filename in (filename, f"renamed-{filename}"):
                repeated = client.post(
                    f"/api/v1/accounts/{account_id}/imports",
                    headers=support.headers(user_id),
                    json={
                        "source": source.value,
                        "filename": repeated_filename,
                        "file_size": len(content),
                        "file_encoding": None,
                        "checksum": hashlib.sha256(content).hexdigest(),
                    },
                )
                assert repeated.status_code == 409
                assert repeated.json()["error"]["code"] == "import_batch_exists"

            for variant_name in ("bom", "reordered"):
                duplicate = support.run_stages(
                    client,
                    source=source,
                    user_id=user_id,
                    account_id=account_id,
                    content=support.variant(content, variant_name),
                    filename=f"{variant_name}-{filename}",
                    post=True,
                )
                assert duplicate["deduplicate"]["rows_duplicate"] == expected_events
                assert duplicate["post"]["rows_imported"] == 0
                assert duplicate["post"]["rows_skipped"] == 3

            independent = support.run_stages(
                client,
                source=source,
                user_id=user_id,
                account_id=other_account,
                content=content,
                filename=f"other-account-{filename}",
                post=True,
            )
            assert independent["deduplicate"]["rows_duplicate"] == 0
            assert independent["post"]["rows_imported"] == expected_events

        first_evidence = asyncio.run(_evidence(account_id))
        other_evidence = asyncio.run(_evidence(other_account))
        assert len(first_evidence["events"]) == expected_events
        assert len(first_evidence["holdings"]) == expected_holdings
        assert len(other_evidence["events"]) == expected_events
        assert len(other_evidence["holdings"]) == expected_holdings
        assert {event.external_id for event in first_evidence["events"]} == {
            event.external_id for event in other_evidence["events"]
        }
        assert {event.id for event in first_evidence["events"]}.isdisjoint(
            {event.id for event in other_evidence["events"]}
        )
    finally:
        asyncio.run(support.cleanup(prefix))
