from __future__ import annotations

import asyncio
import os
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypedDict
from unittest.mock import patch

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    InvestmentMovementKind,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.accounts.access import AccountAccessDeniedError, AccountNotFoundError
from app.modules.imports.classification import classify_import_row
from app.modules.imports.classification_service import ImportClassificationService
from app.modules.imports.deduplication import ImportDeduplicationService
from app.modules.imports.investment_posting import ImportInvestmentPostingWriter
from app.modules.imports.normalization import ImportNormalizationService
from app.modules.imports.posting_common import ImportPostStateError
from app.modules.imports.posting_service import (
    ImportBatchPostingService,
    ImportBatchPostStateError,
    PostImportBatchCommand,
)
from app.modules.imports.transaction_posting import ImportTransactionPostingWriter

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


class _Snapshot(TypedDict):
    batch: tuple[object, ...]
    rows: tuple[tuple[Any, ...], ...]
    events: tuple[str, ...]
    movements: tuple[str, ...]
    transactions: tuple[str, ...]
    assets: int
    listings: int
    aliases: int


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=6)


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.com",
        name=user_id,
    )


def _manual(external_id: str, amount: str = "10") -> dict[str, str]:
    return {
        "Date": "2026-07-25",
        "Amount": amount,
        "Currency": "EUR",
        "Type": "income" if not amount.startswith("-") else "expense",
        "Description": "Posting integration",
        "External ID": external_id,
    }


def _trading_buy(symbol: str, external_id: str) -> dict[str, str]:
    return {
        "Action": "Market buy",
        "Time": "2026-07-25T10:00:00Z",
        "Ticker": symbol,
        "ISIN": f"ISIN-{symbol}",
        "Name": symbol,
        "Asset type": "ETF",
        "No. of shares": "2",
        "Price / share": "100",
        "Currency (Price / share)": "EUR",
        "Total": "200",
        "Currency (Total)": "EUR",
        "ID": external_id,
    }


def _conversion(external_id: str) -> dict[str, str]:
    row = _trading_buy("", external_id)
    row.update(
        {
            "Action": "Currency conversion",
            "Ticker": "",
            "ISIN": "",
            "Name": "",
            "Asset type": "",
            "No. of shares": "",
            "Price / share": "",
            "Currency (Price / share)": "",
            "Total": "100",
            "Currency (Total)": "EUR",
            "Currency conversion from amount": "100",
            "Currency (Currency conversion from amount)": "EUR",
            "Currency conversion to amount": "110",
            "Currency (Currency conversion to amount)": "USD",
        }
    )
    return row


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    batch_id = f"{prefix}-batch"
    account_id = f"{prefix}-account"
    async with AsyncSession(engine) as session:
        event_ids = set(
            (
                await session.scalars(
                    select(InvestmentEventModel.id).where(
                        InvestmentEventModel.import_batch_id == batch_id
                    )
                )
            ).all()
        )
        event_ids.update(
            value
            for value in (
                await session.scalars(
                    select(ImportRowModel.created_investment_event_id).where(
                        ImportRowModel.import_batch_id == batch_id
                    )
                )
            ).all()
            if value
        )
        if event_ids:
            await session.execute(
                delete(InvestmentMovementModel).where(
                    InvestmentMovementModel.event_id.in_(event_ids)
                )
            )
            await session.execute(
                delete(InvestmentEventModel).where(InvestmentEventModel.id.in_(event_ids))
            )
        await session.execute(
            delete(TransactionModel).where(TransactionModel.import_batch_id == batch_id)
        )
        await session.execute(
            delete(ImportRowModel).where(ImportRowModel.import_batch_id == batch_id)
        )
        await session.execute(delete(ImportBatchModel).where(ImportBatchModel.id == batch_id))
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id == account_id)
        )
        await session.execute(delete(AccountModel).where(AccountModel.id == account_id))
        await session.execute(
            delete(UserModel).where(UserModel.id.in_([f"{prefix}-owner", f"{prefix}-other"]))
        )
        await session.commit()
    await engine.dispose()


async def _seed(
    prefix: str,
    *,
    source: ImportSource,
    rows: list[dict[str, str]],
    other_role: AccountMemberRole | None = None,
) -> None:
    await _cleanup(prefix)
    engine = _engine()
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    account_id, batch_id = f"{prefix}-account", f"{prefix}-batch"
    async with AsyncSession(engine) as session:
        for suffix in ("owner", "other"):
            session.add(
                UserModel(
                    id=f"{prefix}-{suffix}",
                    email=f"{prefix}-{suffix}@example.com",
                    name=suffix,
                    password_hash=None,
                    base_currency="EUR",
                    created_at=now,
                    updated_at=now,
                )
            )
        session.add(
            AccountModel(
                id=account_id,
                name=prefix,
                type=AccountType.bank
                if source in {ImportSource.manual, ImportSource.raiffeisenbank}
                else AccountType.broker,
                currency="EUR",
                color=None,
                notes=None,
                is_archived=False,
                archived_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            AccountMemberModel(
                id=f"{prefix}-owner-member",
                account_id=account_id,
                user_id=f"{prefix}-owner",
                role=AccountMemberRole.owner,
                relation_type=AccountRelationType.owner,
                invited_by_id=None,
                accepted_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        if other_role is not None:
            session.add(
                AccountMemberModel(
                    id=f"{prefix}-other-member",
                    account_id=account_id,
                    user_id=f"{prefix}-other",
                    role=other_role,
                    relation_type=AccountRelationType.collaborator,
                    invited_by_id=f"{prefix}-owner",
                    accepted_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.add(
            ImportBatchModel(
                id=batch_id,
                user_id=f"{prefix}-owner",
                account_id=account_id,
                source=source,
                filename=f"{prefix}.csv",
                file_size=1,
                file_encoding="utf-8",
                checksum=(prefix[0] if prefix else "a") * 64,
                status=ImportStatus.processing,
                rows_total=len(rows),
                rows_imported=0,
                rows_skipped=0,
                created_at=now,
                completed_at=None,
                retain_until=None,
                raw_data_purged_at=None,
            )
        )
        session.add_all(
            [
                ImportRowModel(
                    id=f"{prefix}-row-{index}",
                    import_batch_id=batch_id,
                    row_number=index + 2,
                    raw_data=raw,
                    normalized_data=None,
                    validation_errors=None,
                    deduplication_key=None,
                    status=ImportRowStatus.pending,
                    error_message=None,
                    created_transaction_id=None,
                    created_investment_event_id=None,
                    created_at=now,
                )
                for index, raw in enumerate(rows)
            ]
        )
        await session.commit()
    await engine.dispose()


async def _prepare(prefix: str) -> None:
    engine = _engine()
    principal = _principal(f"{prefix}-owner")
    account_id, batch_id = f"{prefix}-account", f"{prefix}-batch"
    async with AsyncSession(engine) as session:
        await ImportNormalizationService(session).normalize_batch(
            principal=principal, account_id=account_id, batch_id=batch_id
        )
    async with AsyncSession(engine) as session:
        await ImportDeduplicationService(session).deduplicate_batch(
            principal=principal, account_id=account_id, batch_id=batch_id
        )
    async with AsyncSession(engine) as session:
        await ImportClassificationService(session).classify_batch(
            principal=principal, account_id=account_id, batch_id=batch_id
        )
    await engine.dispose()


async def _remove_asset_identities(provider_symbols: set[str]) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        asset_ids = set(
            (
                await session.scalars(
                    select(AssetListingModel.asset_id).where(
                        AssetListingModel.provider_symbol.in_(provider_symbols)
                    )
                )
            ).all()
        )
        await session.execute(
            delete(AssetListingModel).where(AssetListingModel.provider_symbol.in_(provider_symbols))
        )
        if asset_ids:
            await session.execute(delete(AssetModel).where(AssetModel.id.in_(asset_ids)))
        await session.commit()
    await engine.dispose()


async def _configure_non_posting_batch(prefix: str, states: list[str]) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        batch = await session.get(ImportBatchModel, f"{prefix}-batch")
        assert batch is not None
        rows = list(
            (
                await session.scalars(
                    select(ImportRowModel)
                    .where(ImportRowModel.import_batch_id == batch.id)
                    .order_by(ImportRowModel.row_number, ImportRowModel.id)
                )
            ).all()
        )
        assert len(rows) == len(states)
        for row, state in zip(rows, states, strict=True):
            row.created_transaction_id = None
            row.created_investment_event_id = None
            if state == "duplicate":
                row.status = ImportRowStatus.duplicate
                row.normalized_data = {
                    "schema_version": 1,
                    "source": batch.source.value,
                    "deduplication": {"schema_version": 1, "status": "duplicate"},
                }
                row.deduplication_key = f"{prefix}-{row.id}-duplicate"
                row.validation_errors = None
                row.error_message = "Duplicate normalized import row."
            elif state.startswith("skipped:"):
                row.status = ImportRowStatus.skipped
                row.normalized_data = {
                    "schema_version": 2,
                    "source": "anycoin",
                    "kind": state.removeprefix("skipped:"),
                }
                row.deduplication_key = None
                row.validation_errors = None
                row.error_message = None
            elif state == "failed":
                row.status = ImportRowStatus.failed
                row.normalized_data = None
                row.deduplication_key = None
                row.validation_errors = {"code": "blank_row"}
                row.error_message = "The row is blank."
            elif state == "normalization_review":
                row.status = ImportRowStatus.needs_review
                row.normalized_data = None
                row.deduplication_key = None
                row.validation_errors = [
                    {
                        "field": "amount",
                        "code": "invalid",
                        "message": "Amount is invalid.",
                    }
                ]
                row.error_message = "Row requires normalization review."
            elif state == "classification_review":
                canonical: dict[str, Any] = {
                    "schema_version": 1,
                    "source": "manual",
                    "date": "2026-07-25",
                    "amount": "10",
                    "currency": "EUR",
                    "type": "transfer",
                    "external_id": row.id,
                }
                intent = classify_import_row(
                    source=ImportSource.manual,
                    normalized_data=canonical,
                ).model_dump(mode="json")
                assert intent["target"] == "needs_review"
                row.status = ImportRowStatus.needs_review
                row.normalized_data = {
                    **canonical,
                    "deduplication": {"schema_version": 1, "status": "unique"},
                    "posting_intent": intent,
                }
                row.deduplication_key = f"{prefix}-{row.id}-review"
                row.validation_errors = deepcopy(intent["errors"])
                row.error_message = "Row requires classification review."
            else:
                raise AssertionError(f"Unsupported test state: {state}")
        batch.status = ImportStatus.processing
        batch.rows_total = len(rows)
        batch.rows_imported = 0
        batch.rows_skipped = len(rows)
        batch.completed_at = None
        await session.commit()
    await engine.dispose()


async def _post(prefix: str, user: str = "owner"):
    engine = _engine()
    async with AsyncSession(engine) as session:
        result = await ImportBatchPostingService(session).post_batch(
            PostImportBatchCommand(
                principal=_principal(f"{prefix}-{user}"),
                account_id=f"{prefix}-account",
                batch_id=f"{prefix}-batch",
            )
        )
    await engine.dispose()
    return result


async def _snapshot(prefix: str) -> _Snapshot:
    engine = _engine()
    async with AsyncSession(engine) as session:
        batch = await session.get(ImportBatchModel, f"{prefix}-batch")
        assert batch is not None
        rows = tuple(
            (
                await session.scalars(
                    select(ImportRowModel)
                    .where(ImportRowModel.import_batch_id == batch.id)
                    .order_by(ImportRowModel.row_number, ImportRowModel.id)
                )
            ).all()
        )
        event_ids = tuple(
            (
                await session.scalars(
                    select(InvestmentEventModel.id)
                    .where(InvestmentEventModel.import_batch_id == batch.id)
                    .order_by(InvestmentEventModel.id)
                )
            ).all()
        )
        movement_ids = (
            tuple(
                (
                    await session.scalars(
                        select(InvestmentMovementModel.id)
                        .where(InvestmentMovementModel.event_id.in_(event_ids))
                        .order_by(InvestmentMovementModel.id)
                    )
                ).all()
            )
            if event_ids
            else ()
        )
        transaction_ids = tuple(
            (
                await session.scalars(
                    select(TransactionModel.id)
                    .where(TransactionModel.import_batch_id == batch.id)
                    .order_by(TransactionModel.id)
                )
            ).all()
        )
        value: _Snapshot = {
            "batch": (
                batch.status,
                batch.rows_total,
                batch.rows_imported,
                batch.rows_skipped,
                batch.completed_at,
            ),
            "rows": tuple(
                (
                    row.id,
                    row.status,
                    deepcopy(row.normalized_data),
                    row.deduplication_key,
                    row.created_transaction_id,
                    row.created_investment_event_id,
                    deepcopy(row.validation_errors),
                    row.error_message,
                )
                for row in rows
            ),
            "events": event_ids,
            "movements": movement_ids,
            "transactions": transaction_ids,
            "assets": int(await session.scalar(select(func.count()).select_from(AssetModel)) or 0),
            "listings": int(
                await session.scalar(select(func.count()).select_from(AssetListingModel)) or 0
            ),
            "aliases": int(
                await session.scalar(select(func.count()).select_from(AssetAliasModel)) or 0
            ),
        }
    await engine.dispose()
    return value


async def _assert_zero_import_roundtrip(
    prefix: str,
    *,
    expected_status: ImportStatus,
    total: int,
) -> None:
    before = await _snapshot(prefix)
    first = await _post(prefix)
    after_first = await _snapshot(prefix)
    second = await _post(prefix)
    after_second = await _snapshot(prefix)

    assert first.status is expected_status
    assert first.replayed is False
    assert (first.rows_total, first.rows_imported, first.rows_skipped) == (total, 0, total)
    assert first.completed_at is not None
    assert asdict(second) == asdict(replace(first, replayed=True))
    assert after_first == after_second
    assert after_first["batch"] == (
        expected_status,
        total,
        0,
        total,
        first.completed_at,
    )
    assert after_first["rows"] == before["rows"]
    for key in ("events", "movements", "transactions", "assets", "listings", "aliases"):
        assert after_first[key] == before[key]


def test_duplicate_only_batch_finalizes_and_replays_without_canonical_writes() -> None:
    prefix = "g5c-zero-duplicate"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.manual,
            rows=[_manual("duplicate-a"), _manual("duplicate-b")],
        )
        await _configure_non_posting_batch(prefix, ["duplicate", "duplicate"])
        await _assert_zero_import_roundtrip(
            prefix,
            expected_status=ImportStatus.completed,
            total=2,
        )

    asyncio.run(scenario())


def test_skipped_only_batch_finalizes_and_replays_without_canonical_writes() -> None:
    prefix = "g5c-zero-skipped"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.anycoin,
            rows=[{"row": kind} for kind in ("group", "refund", "neutral")],
        )
        await _configure_non_posting_batch(
            prefix,
            [
                "skipped:group_member",
                "skipped:fully_refunded_group",
                "skipped:neutral_row",
            ],
        )
        await _assert_zero_import_roundtrip(
            prefix,
            expected_status=ImportStatus.completed,
            total=3,
        )

    asyncio.run(scenario())


def test_needs_review_only_batch_partially_completes_and_replays() -> None:
    prefix = "g5c-zero-review"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.manual,
            rows=[_manual("review-a"), _manual("review-b")],
        )
        await _configure_non_posting_batch(
            prefix,
            ["classification_review", "classification_review"],
        )
        await _assert_zero_import_roundtrip(
            prefix,
            expected_status=ImportStatus.partially_completed,
            total=2,
        )

    asyncio.run(scenario())


def test_failed_only_batch_partially_completes_and_replays() -> None:
    prefix = "g5c-zero-failed"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.manual,
            rows=[_manual("failed-a"), _manual("failed-b")],
        )
        await _configure_non_posting_batch(prefix, ["failed", "failed"])
        await _assert_zero_import_roundtrip(
            prefix,
            expected_status=ImportStatus.partially_completed,
            total=2,
        )

    asyncio.run(scenario())


def test_mixed_non_posting_batch_partially_completes_and_replays() -> None:
    prefix = "g5c-zero-mixed"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.anycoin,
            rows=[{"row": str(index)} for index in range(4)],
        )
        await _configure_non_posting_batch(
            prefix,
            [
                "duplicate",
                "skipped:neutral_row",
                "normalization_review",
                "failed",
            ],
        )
        await _assert_zero_import_roundtrip(
            prefix,
            expected_status=ImportStatus.partially_completed,
            total=4,
        )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("state", "corruption"),
    [
        ("duplicate", "missing_key"),
        ("duplicate", "posting_intent"),
        ("skipped:group_member", "unsupported_kind"),
        ("skipped:neutral_row", "error_message"),
        ("failed", "created_id"),
        ("failed", "failed_errors_cleared"),
        ("failed", "failed_message_cleared"),
        ("failed", "failed_both_cleared"),
        ("failed", "failed_evidence_tampered"),
        ("normalization_review", "normalization_errors_cleared"),
        ("normalization_review", "normalization_message_cleared"),
        ("normalization_review", "normalization_message_changed"),
        ("normalization_review", "normalization_created_id"),
        ("classification_review", "validation_errors"),
        ("classification_review", "review_message"),
    ],
)
def test_invalid_non_posting_row_fails_closed_without_canonical_writes(
    state: str,
    corruption: str,
) -> None:
    prefix = f"g5c-zero-invalid-{corruption}"

    async def scenario() -> None:
        source = ImportSource.anycoin if state.startswith("skipped:") else ImportSource.manual
        await _seed(prefix, source=source, rows=[{"row": corruption}])
        await _configure_non_posting_batch(prefix, [state])
        engine = _engine()
        async with AsyncSession(engine) as session:
            row = await session.get(ImportRowModel, f"{prefix}-row-0")
            assert row is not None
            if corruption == "missing_key":
                row.deduplication_key = None
            elif corruption == "posting_intent":
                assert isinstance(row.normalized_data, dict)
                row.normalized_data = {**row.normalized_data, "posting_intent": {"target": "x"}}
            elif corruption == "unsupported_kind":
                assert isinstance(row.normalized_data, dict)
                row.normalized_data = {**row.normalized_data, "kind": "unsupported"}
            elif corruption == "error_message":
                row.error_message = "unexpected"
            elif corruption == "created_id":
                row.created_transaction_id = "unexpected"
            elif corruption == "failed_errors_cleared":
                row.validation_errors = None
            elif corruption == "failed_message_cleared":
                row.error_message = None
            elif corruption == "failed_both_cleared":
                row.validation_errors = None
                row.error_message = None
            elif corruption == "failed_evidence_tampered":
                row.validation_errors = {
                    "code": "column_count_mismatch",
                    "expected": 3,
                    "actual": 2,
                }
                row.error_message = "The row contains more values than the header defines."
            elif corruption == "normalization_errors_cleared":
                row.validation_errors = None
            elif corruption == "normalization_message_cleared":
                row.error_message = None
            elif corruption == "normalization_message_changed":
                row.error_message = "Normalization review."
            elif corruption == "normalization_created_id":
                row.created_investment_event_id = "unexpected"
            elif corruption == "validation_errors":
                row.validation_errors = [{"code": "tampered"}]
            else:
                row.error_message = "tampered"
            await session.commit()
        await engine.dispose()

        before = await _snapshot(prefix)
        with pytest.raises(ImportBatchPostStateError):
            await _post(prefix)
        assert await _snapshot(prefix) == before
        assert before["events"] == ()
        assert before["movements"] == ()
        assert before["transactions"] == ()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("state", "corruption"),
    [
        ("failed", "failed_errors_cleared"),
        ("failed", "failed_message_cleared"),
        ("failed", "failed_both_cleared"),
        ("failed", "failed_evidence_tampered"),
        ("normalization_review", "normalization_errors_cleared"),
        ("normalization_review", "normalization_message_cleared"),
        ("normalization_review", "normalization_message_changed"),
        ("normalization_review", "normalization_created_id"),
    ],
)
def test_terminal_failure_evidence_corruption_is_not_repaired_on_replay(
    state: str,
    corruption: str,
) -> None:
    prefix = f"g5c-terminal-evidence-{corruption}"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.manual, rows=[{"row": corruption}])
        await _configure_non_posting_batch(prefix, [state])
        first = await _post(prefix)
        assert first.status is ImportStatus.partially_completed
        assert first.rows_imported == 0

        engine = _engine()
        async with AsyncSession(engine) as session:
            row = await session.get(ImportRowModel, f"{prefix}-row-0")
            assert row is not None
            if corruption == "failed_errors_cleared":
                row.validation_errors = None
            elif corruption == "failed_message_cleared":
                row.error_message = None
            elif corruption == "failed_both_cleared":
                row.validation_errors = None
                row.error_message = None
            elif corruption == "failed_evidence_tampered":
                row.validation_errors = {
                    "code": "column_count_mismatch",
                    "expected": 3,
                    "actual": 2,
                }
                row.error_message = "The row contains more values than the header defines."
            elif corruption == "normalization_errors_cleared":
                row.validation_errors = None
            elif corruption == "normalization_message_cleared":
                row.error_message = None
            elif corruption == "normalization_message_changed":
                row.error_message = "Normalization review."
            else:
                row.created_investment_event_id = "unexpected"
            await session.commit()
        await engine.dispose()

        tampered = await _snapshot(prefix)
        with pytest.raises(ImportBatchPostStateError):
            await _post(prefix)
        assert await _snapshot(prefix) == tampered
        assert tampered["events"] == ()
        assert tampered["movements"] == ()
        assert tampered["transactions"] == ()

    asyncio.run(scenario())


def test_manual_batch_posts_atomically_and_exact_replay_is_stable() -> None:
    prefix = "g5c-manual"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.manual, rows=[_manual("one"), _manual("two", "-5")])
        await _prepare(prefix)
        first = await _post(prefix)
        snapshot = await _snapshot(prefix)
        second = await _post(prefix)
        assert first.replayed is False and second.replayed is True
        assert asdict(first) | {"replayed": True} == asdict(second)
        assert await _snapshot(prefix) == snapshot
        assert first.status is ImportStatus.completed
        assert (first.rows_total, first.rows_imported, first.rows_skipped) == (2, 2, 0)
        assert len(snapshot["transactions"]) == 2
        assert snapshot["events"] == () and snapshot["movements"] == ()

    asyncio.run(scenario())


def test_mixed_trading_batch_posts_unique_rows_and_preserves_duplicate() -> None:
    prefix = "g5c-mixed"

    async def scenario() -> None:
        buy = _trading_buy("G5CMIX", "g5c-buy")
        await _seed(
            prefix,
            source=ImportSource.trading212,
            rows=[buy, deepcopy(buy), _conversion("g5c-fx")],
        )
        await _prepare(prefix)
        result = await _post(prefix)
        snapshot = await _snapshot(prefix)
        replay = await _post(prefix)
        assert result.status is ImportStatus.completed
        assert replay.replayed is True
        assert asdict(result) | {"replayed": True} == asdict(replay)
        assert await _snapshot(prefix) == snapshot
        assert (result.rows_total, result.rows_imported, result.rows_skipped) == (3, 2, 1)
        assert len(snapshot["events"]) == 2
        assert len(snapshot["movements"]) == 4
        duplicate = next(row for row in snapshot["rows"] if row[1] is ImportRowStatus.duplicate)
        assert duplicate[5] is None
        assert snapshot["transactions"] == ()

    asyncio.run(scenario())


def test_partial_batch_finalizes_review_row_without_posting_it() -> None:
    prefix = "g5c-partial"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.manual,
            rows=[_manual("valid"), {"Date": "", "Amount": "bad", "Currency": "EUR"}],
        )
        await _prepare(prefix)
        result = await _post(prefix)
        snapshot = await _snapshot(prefix)
        replay = await _post(prefix)
        assert result.status is ImportStatus.partially_completed
        assert replay.replayed is True
        assert asdict(result) | {"replayed": True} == asdict(replay)
        assert await _snapshot(prefix) == snapshot
        assert (result.rows_total, result.rows_imported, result.rows_skipped) == (2, 1, 1)
        assert len(snapshot["transactions"]) == 1
        assert sum(row[1] is ImportRowStatus.needs_review for row in snapshot["rows"]) == 1

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "corruption",
    ["missing_completed_at", "rows_total", "rows_imported", "rows_skipped"],
)
def test_completed_batch_counter_and_timestamp_corruption_fails_closed(corruption: str) -> None:
    prefix = f"g5c-batch-corrupt-{corruption}"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.manual, rows=[_manual(corruption)])
        await _prepare(prefix)
        await _post(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            batch = await session.get(ImportBatchModel, f"{prefix}-batch")
            assert batch is not None
            if corruption == "missing_completed_at":
                batch.completed_at = None
            elif corruption == "rows_total":
                batch.rows_total = 2
            elif corruption == "rows_imported":
                batch.rows_imported = 0
            else:
                batch.rows_skipped = 1
            await session.commit()
        await engine.dispose()
        before = await _snapshot(prefix)
        with pytest.raises(ImportBatchPostStateError):
            await _post(prefix)
        assert await _snapshot(prefix) == before

    asyncio.run(scenario())


@pytest.mark.parametrize("corruption", ["missing_event", "event_description", "row_membership"])
def test_completed_investment_root_or_membership_corruption_fails_closed(
    corruption: str,
) -> None:
    prefix = f"g5c-root-{corruption}"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.trading212,
            rows=[_trading_buy(f"G5CROOT{corruption.upper()}", f"g5c-root-{corruption}")],
        )
        await _prepare(prefix)
        await _post(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            event = await session.scalar(
                select(InvestmentEventModel).where(
                    InvestmentEventModel.import_batch_id == f"{prefix}-batch"
                )
            )
            assert event is not None
            if corruption == "missing_event":
                await session.delete(event)
            elif corruption == "event_description":
                event.description = "tampered"
            else:
                now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
                session.add(
                    ImportRowModel(
                        id=f"{prefix}-unexpected-row",
                        import_batch_id=f"{prefix}-batch",
                        row_number=99,
                        raw_data={"unexpected": True},
                        normalized_data=None,
                        validation_errors=[{"code": "unexpected"}],
                        deduplication_key=None,
                        status=ImportRowStatus.failed,
                        error_message="unexpected",
                        created_transaction_id=None,
                        created_investment_event_id=None,
                        created_at=now,
                    )
                )
            await session.commit()
        await engine.dispose()
        before = await _snapshot(prefix)
        with pytest.raises((ImportPostStateError, ImportBatchPostStateError)):
            await _post(prefix)
        assert await _snapshot(prefix) == before

    asyncio.run(scenario())


def test_completed_batch_missing_transaction_fails_without_replacement() -> None:
    prefix = "g5c-missing-transaction"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.manual, rows=[_manual("missing")])
        await _prepare(prefix)
        await _post(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            await session.execute(
                delete(TransactionModel).where(
                    TransactionModel.import_batch_id == f"{prefix}-batch"
                )
            )
            await session.commit()
        await engine.dispose()
        before = await _snapshot(prefix)
        with pytest.raises(ImportPostStateError):
            await _post(prefix)
        assert await _snapshot(prefix) == before
        assert before["transactions"] == ()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "corruption",
    ["missing", "extra", "duplicate", "quantity", "currency", "kind", "asset_relation"],
)
def test_completed_investment_movement_corruption_fails_without_repair(
    corruption: str,
) -> None:
    prefix = f"g5c-movement-{corruption}"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.trading212,
            rows=[_trading_buy(f"G5C{corruption.upper()}", f"g5c-{corruption}")],
        )
        await _prepare(prefix)
        await _post(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            event = await session.scalar(
                select(InvestmentEventModel).where(
                    InvestmentEventModel.import_batch_id == f"{prefix}-batch"
                )
            )
            assert event is not None
            movements = list(
                (
                    await session.scalars(
                        select(InvestmentMovementModel).where(
                            InvestmentMovementModel.event_id == event.id
                        )
                    )
                ).all()
            )
            target = movements[0]
            if corruption == "missing":
                await session.delete(target)
            elif corruption in {"extra", "duplicate"}:
                source = target
                session.add(
                    InvestmentMovementModel(
                        id=f"{prefix}-{corruption}",
                        event_id=source.event_id,
                        account_id=source.account_id,
                        asset_id=source.asset_id,
                        listing_id=source.listing_id,
                        kind=source.kind,
                        direction=source.direction,
                        quantity=source.quantity
                        if corruption == "duplicate"
                        else source.quantity + Decimal("1"),
                        currency=source.currency,
                        price_per_unit=source.price_per_unit,
                        value_amount=source.value_amount,
                        value_currency=source.value_currency,
                        source_symbol=source.source_symbol,
                        source_asset_type=source.source_asset_type,
                        note=source.note,
                        updated_at=source.updated_at,
                    )
                )
            elif corruption == "quantity":
                target.quantity += Decimal("1")
            elif corruption == "currency":
                target.currency = "USD"
            elif corruption == "kind":
                target.kind = InvestmentMovementKind.fee
            else:
                target.asset_id = None
            await session.commit()
        await engine.dispose()
        before = await _snapshot(prefix)
        with pytest.raises(ImportPostStateError):
            await _post(prefix)
        assert await _snapshot(prefix) == before

    asyncio.run(scenario())


def test_persisted_authorization_owner_succeeds_and_non_member_is_hidden() -> None:
    prefix = "g5c-auth"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.manual, rows=[_manual("auth")])
        await _prepare(prefix)
        before = await _snapshot(prefix)
        with pytest.raises(AccountNotFoundError):
            await _post(prefix, "other")
        assert await _snapshot(prefix) == before
        result = await _post(prefix, "owner")
        assert result.status is ImportStatus.completed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        (AccountMemberRole.admin, True),
        (AccountMemberRole.editor, True),
        (AccountMemberRole.viewer, False),
    ],
)
def test_persisted_collaborator_authorization_matrix(
    role: AccountMemberRole,
    allowed: bool,
) -> None:
    prefix = f"g5c-auth-{role.value}"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.manual,
            rows=[_manual(role.value)],
            other_role=role,
        )
        await _prepare(prefix)
        before = await _snapshot(prefix)
        if allowed:
            result = await _post(prefix, "other")
            assert result.status is ImportStatus.completed
            assert result.rows_imported == 1
        else:
            with pytest.raises(AccountAccessDeniedError):
                await _post(prefix, "other")
            assert await _snapshot(prefix) == before

    asyncio.run(scenario())


def test_concurrent_role_revocation_blocks_posting_and_is_revalidated() -> None:
    prefix = "g5c-auth-revocation"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.manual,
            rows=[_manual("revocation")],
            other_role=AccountMemberRole.editor,
        )
        await _prepare(prefix)
        before = await _snapshot(prefix)
        engine = _engine()

        async with (
            AsyncSession(engine) as revocation_session,
            AsyncSession(engine) as posting_session,
        ):
            membership = await revocation_session.scalar(
                select(AccountMemberModel)
                .where(AccountMemberModel.id == f"{prefix}-other-member")
                .with_for_update()
            )
            assert membership is not None
            membership.role = AccountMemberRole.viewer
            await revocation_session.flush()

            posting_pid = int(await posting_session.scalar(text("SELECT pg_backend_pid()")))
            posting_task = asyncio.create_task(
                ImportBatchPostingService(posting_session).post_batch(
                    PostImportBatchCommand(
                        principal=_principal(f"{prefix}-other"),
                        account_id=f"{prefix}-account",
                        batch_id=f"{prefix}-batch",
                    )
                )
            )

            blocked = False
            async with AsyncSession(engine) as inspector:
                for _ in range(100):
                    state = (
                        await inspector.execute(
                            text(
                                "SELECT cardinality(pg_blocking_pids(:pid)), wait_event_type "
                                "FROM pg_stat_activity WHERE pid = :pid"
                            ),
                            {"pid": posting_pid},
                        )
                    ).one()
                    if int(state[0] or 0) and state[1] == "Lock":
                        blocked = True
                        break
                    await asyncio.sleep(0.02)
            assert blocked

            await revocation_session.commit()
            result = await asyncio.wait_for(
                asyncio.gather(posting_task, return_exceptions=True),
                timeout=10,
            )

        await engine.dispose()
        assert len(result) == 1
        assert isinstance(result[0], AccountAccessDeniedError)
        assert await _snapshot(prefix) == before

    asyncio.run(scenario())


def test_later_writer_failure_rolls_back_first_row_and_clean_retry_succeeds() -> None:
    prefix = "g5c-rollback"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.manual,
            rows=[_manual("rollback-one"), _manual("rollback-two", "11")],
        )
        await _prepare(prefix)
        before = await _snapshot(prefix)
        original = ImportTransactionPostingWriter.post_row
        calls = 0

        async def controlled(
            self, *, account_id: str, batch: ImportBatchModel, row: ImportRowModel
        ):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("controlled later-row failure")
            return await original(self, account_id=account_id, batch=batch, row=row)

        with patch.object(ImportTransactionPostingWriter, "post_row", controlled):
            with pytest.raises(RuntimeError, match="controlled later-row"):
                await _post(prefix)
        assert await _snapshot(prefix) == before
        retry = await _post(prefix)
        assert retry.status is ImportStatus.completed and retry.rows_imported == 2
        assert len((await _snapshot(prefix))["transactions"]) == 2

    asyncio.run(scenario())


def test_later_investment_failure_rolls_back_resolver_graph_and_retry_succeeds() -> None:
    prefix = "g5c-investment-rollback"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.trading212,
            rows=[
                _trading_buy("G5CROLLBACKA", "g5c-rollback-a"),
                _trading_buy("G5CROLLBACKB", "g5c-rollback-b"),
            ],
        )
        await _remove_asset_identities({"G5CROLLBACKA", "G5CROLLBACKB"})
        await _prepare(prefix)
        before = await _snapshot(prefix)
        original = ImportInvestmentPostingWriter.post_row
        calls = 0

        async def controlled(
            self, *, account_id: str, batch: ImportBatchModel, row: ImportRowModel
        ):
            nonlocal calls
            calls += 1
            result = await original(self, account_id=account_id, batch=batch, row=row)
            if calls == 2:
                raise RuntimeError("controlled investment rollback")
            return result

        with patch.object(ImportInvestmentPostingWriter, "post_row", controlled):
            with pytest.raises(RuntimeError, match="controlled investment"):
                await _post(prefix)
        assert await _snapshot(prefix) == before

        retry = await _post(prefix)
        after = await _snapshot(prefix)
        assert retry.status is ImportStatus.completed and retry.rows_imported == 2
        assert len(after["events"]) == 2
        assert len(after["movements"]) == 4
        assert after["assets"] == before["assets"] + 2
        assert after["listings"] == before["listings"] + 2
        assert after["aliases"] == before["aliases"]
        assert after["transactions"] == before["transactions"]

    asyncio.run(scenario())


def test_same_batch_concurrency_uses_real_batch_lock_and_completed_replay() -> None:
    prefix = "g5c-concurrent"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.manual, rows=[_manual("concurrent")])
        await _prepare(prefix)
        engine = _engine()
        first_locked = asyncio.Event()
        release_first = asyncio.Event()
        original = ImportTransactionPostingWriter.post_row
        first_call = True

        async def held(self, *, account_id: str, batch: ImportBatchModel, row: ImportRowModel):
            nonlocal first_call
            result = await original(self, account_id=account_id, batch=batch, row=row)
            if first_call:
                first_call = False
                first_locked.set()
                await release_first.wait()
            return result

        async def run(session: AsyncSession):
            return await ImportBatchPostingService(session).post_batch(
                PostImportBatchCommand(
                    principal=_principal(f"{prefix}-owner"),
                    account_id=f"{prefix}-account",
                    batch_id=f"{prefix}-batch",
                )
            )

        async with AsyncSession(engine) as first_session, AsyncSession(engine) as second_session:
            second_pid = int(await second_session.scalar(text("SELECT pg_backend_pid()")))
            with patch.object(ImportTransactionPostingWriter, "post_row", held):
                first_task = asyncio.create_task(run(first_session))
                await asyncio.wait_for(first_locked.wait(), timeout=10)
                second_task = asyncio.create_task(run(second_session))
                blocked = False
                async with AsyncSession(engine) as inspector:
                    for _ in range(100):
                        state = (
                            await inspector.execute(
                                text(
                                    "SELECT cardinality(pg_blocking_pids(:pid)), "
                                    "wait_event_type "
                                    "FROM pg_stat_activity WHERE pid = :pid"
                                ),
                                {"pid": second_pid},
                            )
                        ).one()
                        if int(state[0] or 0) and state[1] == "Lock":
                            blocked = True
                            break
                        await asyncio.sleep(0.02)
                assert blocked
                release_first.set()
                first, second = await asyncio.wait_for(
                    asyncio.gather(first_task, second_task), timeout=15
                )
        await engine.dispose()
        assert first.replayed is False and second.replayed is True
        assert first.completed_at == second.completed_at
        snapshot = await _snapshot(prefix)
        assert len(snapshot["transactions"]) == 1
        assert snapshot["batch"] == (
            ImportStatus.completed,
            1,
            1,
            0,
            first.completed_at,
        )

    asyncio.run(scenario())


def test_waiter_posts_after_first_transaction_rolls_back() -> None:
    prefix = "g5c-contention-rollback"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.manual, rows=[_manual("contention")])
        await _prepare(prefix)
        engine = _engine()
        first_wrote = asyncio.Event()
        release_first = asyncio.Event()
        original = ImportTransactionPostingWriter.post_row
        calls = 0

        async def first_fails(
            self, *, account_id: str, batch: ImportBatchModel, row: ImportRowModel
        ):
            nonlocal calls
            calls += 1
            result = await original(self, account_id=account_id, batch=batch, row=row)
            if calls == 1:
                first_wrote.set()
                await release_first.wait()
                raise RuntimeError("controlled transaction rollback")
            return result

        async def run(session: AsyncSession):
            return await ImportBatchPostingService(session).post_batch(
                PostImportBatchCommand(
                    principal=_principal(f"{prefix}-owner"),
                    account_id=f"{prefix}-account",
                    batch_id=f"{prefix}-batch",
                )
            )

        async with AsyncSession(engine) as first_session, AsyncSession(engine) as second_session:
            second_pid = int(await second_session.scalar(text("SELECT pg_backend_pid()")))
            with patch.object(ImportTransactionPostingWriter, "post_row", first_fails):
                first_task = asyncio.create_task(run(first_session))
                await asyncio.wait_for(first_wrote.wait(), timeout=10)
                second_task = asyncio.create_task(run(second_session))
                blocked = False
                async with AsyncSession(engine) as inspector:
                    for _ in range(100):
                        state = (
                            await inspector.execute(
                                text(
                                    "SELECT cardinality(pg_blocking_pids(:pid)), "
                                    "wait_event_type "
                                    "FROM pg_stat_activity WHERE pid = :pid"
                                ),
                                {"pid": second_pid},
                            )
                        ).one()
                        if int(state[0] or 0) and state[1] == "Lock":
                            blocked = True
                            break
                        await asyncio.sleep(0.02)
                assert blocked
                release_first.set()
                first_result, second_result = await asyncio.wait_for(
                    asyncio.gather(first_task, second_task, return_exceptions=True),
                    timeout=15,
                )
        await engine.dispose()
        assert isinstance(first_result, RuntimeError)
        assert not isinstance(second_result, BaseException)
        assert second_result.replayed is False
        snapshot = await _snapshot(prefix)
        assert len(snapshot["transactions"]) == 1
        assert snapshot["batch"][0] is ImportStatus.completed

    asyncio.run(scenario())


def test_different_accounts_for_same_principal_do_not_share_batch_lock() -> None:
    first_prefix, second_prefix = "g5c-independent-a", "g5c-independent-b"

    async def scenario() -> None:
        await _seed(first_prefix, source=ImportSource.manual, rows=[_manual("independent-a")])
        await _seed(second_prefix, source=ImportSource.manual, rows=[_manual("independent-b")])
        await _prepare(first_prefix)
        await _prepare(second_prefix)
        engine = _engine()
        now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
        async with AsyncSession(engine) as session:
            session.add(
                AccountMemberModel(
                    id="g5c-independent-cross-member",
                    account_id=f"{second_prefix}-account",
                    user_id=f"{first_prefix}-owner",
                    role=AccountMemberRole.owner,
                    relation_type=AccountRelationType.owner,
                    invited_by_id=None,
                    accepted_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.commit()

        first_holds = asyncio.Event()
        release_first = asyncio.Event()
        original = ImportTransactionPostingWriter.post_row

        async def hold_first(
            self, *, account_id: str, batch: ImportBatchModel, row: ImportRowModel
        ):
            result = await original(self, account_id=account_id, batch=batch, row=row)
            if batch.id == f"{first_prefix}-batch":
                first_holds.set()
                await release_first.wait()
            return result

        async def run(prefix: str, session: AsyncSession):
            return await ImportBatchPostingService(session).post_batch(
                PostImportBatchCommand(
                    principal=_principal(f"{first_prefix}-owner"),
                    account_id=f"{prefix}-account",
                    batch_id=f"{prefix}-batch",
                )
            )

        async with AsyncSession(engine) as first_session, AsyncSession(engine) as second_session:
            with patch.object(ImportTransactionPostingWriter, "post_row", hold_first):
                first_task = asyncio.create_task(run(first_prefix, first_session))
                await asyncio.wait_for(first_holds.wait(), timeout=10)
                second_result = await asyncio.wait_for(
                    run(second_prefix, second_session), timeout=5
                )
                release_first.set()
                first_result = await asyncio.wait_for(first_task, timeout=10)
        await engine.dispose()
        assert first_result.status is ImportStatus.completed
        assert second_result.status is ImportStatus.completed
        assert len((await _snapshot(first_prefix))["transactions"]) == 1
        assert len((await _snapshot(second_prefix))["transactions"]) == 1

    asyncio.run(scenario())
