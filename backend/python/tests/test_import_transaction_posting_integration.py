from __future__ import annotations

import asyncio
import os
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    TransactionClassification,
    TransactionType,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.imports.classification_service import ImportClassificationService
from app.modules.imports.deduplication import ImportDeduplicationService
from app.modules.imports.normalization import ImportNormalizationService
from app.modules.imports.transaction_posting import (
    ImportPostStateError,
    ImportTransactionPostingWriter,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _principal(prefix: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=f"{prefix}-user",
        email=f"{prefix}@example.com",
        name=prefix,
    )


async def _seed(prefix: str, source: ImportSource, raw_data: dict[str, str]) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id = f"{prefix}-user"
    account_id = f"{prefix}-account"
    batch_id = f"{prefix}-batch"
    async with AsyncSession(engine) as session:
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
        await session.execute(delete(UserModel).where(UserModel.id == user_id))
        session.add(
            UserModel(
                id=user_id,
                email=f"{prefix}@example.com",
                name=prefix,
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
                type=AccountType.bank,
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
                id=f"{prefix}-member",
                account_id=account_id,
                user_id=user_id,
                role=AccountMemberRole.owner,
                relation_type=AccountRelationType.owner,
                invited_by_id=None,
                accepted_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            ImportBatchModel(
                id=batch_id,
                user_id=user_id,
                account_id=account_id,
                source=source,
                filename="posting.csv",
                file_size=1,
                file_encoding="utf-8",
                checksum=(prefix[0] * 64),
                status=ImportStatus.processing,
                rows_total=1,
                rows_imported=0,
                rows_skipped=0,
                created_at=now,
                completed_at=None,
                retain_until=None,
                raw_data_purged_at=None,
            )
        )
        session.add(
            ImportRowModel(
                id=f"{prefix}-row",
                import_batch_id=batch_id,
                row_number=2,
                raw_data=raw_data,
                normalized_data=None,
                validation_errors=None,
                deduplication_key=None,
                status=ImportRowStatus.pending,
                error_message=None,
                created_transaction_id=None,
                created_investment_event_id=None,
                created_at=now,
            )
        )
        await session.commit()
    await engine.dispose()


async def _prepare(prefix: str) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    principal = _principal(prefix)
    async with AsyncSession(engine) as session:
        await ImportNormalizationService(session).normalize_batch(
            principal=principal,
            account_id=f"{prefix}-account",
            batch_id=f"{prefix}-batch",
        )
    async with AsyncSession(engine) as session:
        await ImportDeduplicationService(session).deduplicate_batch(
            principal=principal,
            account_id=f"{prefix}-account",
            batch_id=f"{prefix}-batch",
        )
    async with AsyncSession(engine) as session:
        await ImportClassificationService(session).classify_batch(
            principal=principal,
            account_id=f"{prefix}-account",
            batch_id=f"{prefix}-batch",
        )
    await engine.dispose()


async def _post(prefix: str, *, commit: bool) -> str:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        batch = await session.scalar(
            select(ImportBatchModel)
            .where(ImportBatchModel.id == f"{prefix}-batch")
            .with_for_update()
        )
        row = await session.scalar(
            select(ImportRowModel).where(ImportRowModel.id == f"{prefix}-row").with_for_update()
        )
        assert batch is not None and row is not None
        transaction = await ImportTransactionPostingWriter(session).post_row(
            account_id=f"{prefix}-account",
            batch=batch,
            row=row,
        )
        transaction_id = transaction.id
        if commit:
            await session.commit()
        else:
            await session.rollback()
    await engine.dispose()
    return transaction_id


async def _reload(
    prefix: str,
) -> tuple[ImportBatchModel, ImportRowModel, list[TransactionModel]]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        batch = await session.get(ImportBatchModel, f"{prefix}-batch")
        row = await session.get(ImportRowModel, f"{prefix}-row")
        transactions = list(
            (
                await session.scalars(
                    select(TransactionModel).where(
                        TransactionModel.import_batch_id == f"{prefix}-batch"
                    )
                )
            ).all()
        )
        assert batch is not None and row is not None
        session.expunge(batch)
        session.expunge(row)
        for transaction in transactions:
            session.expunge(transaction)
    await engine.dispose()
    return batch, row, transactions


async def _assert_no_investment_side_effects() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        counts = [
            int(await session.scalar(select(func.count()).select_from(model)) or 0)
            for model in (InvestmentEventModel, InvestmentMovementModel)
        ]
    await engine.dispose()
    assert counts == [0, 0]


def test_manual_pipeline_persists_exact_transaction_and_row_linkage() -> None:
    prefix = "post-manual"

    async def scenario() -> None:
        await _seed(
            prefix,
            ImportSource.manual,
            {
                "Date": "2026-07-25",
                "Amount": "123.45",
                "Currency": "EUR",
                "Type": "income",
                "Description": "Salary",
                "ID": "manual-1",
            },
        )
        await _prepare(prefix)
        before_batch, before_row, before_transactions = await _reload(prefix)
        assert before_transactions == []
        normalized_snapshot = deepcopy(before_row.normalized_data)
        key_snapshot = before_row.deduplication_key
        transaction_id = await _post(prefix, commit=True)

        batch, row, transactions = await _reload(prefix)
        assert len(transactions) == 1
        transaction = transactions[0]
        assert transaction.id == transaction_id
        assert transaction.account_id == f"{prefix}-account"
        assert transaction.import_batch_id == f"{prefix}-batch"
        assert transaction.date == datetime(2026, 7, 25)
        assert transaction.amount == Decimal("123.450000")
        assert transaction.currency == "EUR"
        assert transaction.type is TransactionType.income
        assert transaction.classification is TransactionClassification.real_income
        assert transaction.description == "Salary"
        assert transaction.external_id == "manual-1"
        assert row.status is ImportRowStatus.imported
        assert row.created_transaction_id == transaction.id
        assert row.created_investment_event_id is None
        assert row.normalized_data == normalized_snapshot
        assert row.deduplication_key == key_snapshot
        assert batch.status is before_batch.status is ImportStatus.processing
        assert batch.rows_total == before_batch.rows_total == 1
        assert batch.rows_imported == before_batch.rows_imported == 0
        assert batch.rows_skipped == before_batch.rows_skipped == 0
        assert batch.completed_at == before_batch.completed_at is None
        await _assert_no_investment_side_effects()

    asyncio.run(scenario())


def test_raiffeisenbank_pipeline_persists_expense_mapping() -> None:
    prefix = "post-rb"

    async def scenario() -> None:
        await _seed(
            prefix,
            ImportSource.raiffeisenbank,
            {
                "Date": "2026-07-25T12:30:00+02:00",
                "Amount": "-42.125",
                "Currency": "EUR",
                "Type": "expense",
                "Description": "Card purchase",
                "ID": "rb-1",
            },
        )
        await _prepare(prefix)
        await _post(prefix, commit=True)
        batch, row, transactions = await _reload(prefix)
        assert len(transactions) == 1
        transaction = transactions[0]
        assert transaction.date == datetime(2026, 7, 25, 10, 30)
        assert transaction.amount == Decimal("-42.125000")
        assert transaction.type is TransactionType.expense
        assert transaction.classification is TransactionClassification.real_expense
        assert transaction.description == "Card purchase"
        assert transaction.external_id == "rb-1"
        assert row.status is ImportRowStatus.imported
        assert row.created_transaction_id == transaction.id
        assert batch.status is ImportStatus.processing
        assert batch.rows_imported == 0
        await _assert_no_investment_side_effects()

    asyncio.run(scenario())


def test_database_replay_returns_same_transaction_without_duplicate() -> None:
    prefix = "post-replay"

    async def scenario() -> None:
        await _seed(
            prefix,
            ImportSource.manual,
            {
                "Date": "2026-07-25",
                "Amount": "10",
                "Currency": "EUR",
                "Type": "income",
            },
        )
        await _prepare(prefix)
        first_id = await _post(prefix, commit=True)
        first_batch, first_row, first_transactions = await _reload(prefix)
        assert len(first_transactions) == 1
        entity_snapshot = {
            field: getattr(first_transactions[0], field)
            for field in (
                "id",
                "account_id",
                "import_batch_id",
                "date",
                "amount",
                "currency",
                "type",
                "classification",
                "description",
                "external_id",
                "booking_date",
                "reporting_amount",
                "reporting_currency",
                "note",
                "counterparty",
                "category_id",
                "archived_at",
                "deleted_at",
            )
        }
        row_snapshot = (
            first_row.status,
            first_row.created_transaction_id,
            deepcopy(first_row.normalized_data),
            first_row.deduplication_key,
        )

        second_id = await _post(prefix, commit=True)
        second_batch, second_row, second_transactions = await _reload(prefix)
        assert second_id == first_id
        assert len(second_transactions) == 1
        assert {
            field: getattr(second_transactions[0], field) for field in entity_snapshot
        } == entity_snapshot
        assert (
            second_row.status,
            second_row.created_transaction_id,
            second_row.normalized_data,
            second_row.deduplication_key,
        ) == row_snapshot
        assert second_batch.status is first_batch.status is ImportStatus.processing
        assert second_batch.rows_imported == first_batch.rows_imported == 0
        await _assert_no_investment_side_effects()

    asyncio.run(scenario())


def test_caller_rollback_leaves_no_partial_state_and_retry_succeeds() -> None:
    prefix = "post-rollback"

    async def scenario() -> None:
        await _seed(
            prefix,
            ImportSource.manual,
            {
                "Date": "2026-07-25",
                "Amount": "-9.99",
                "Currency": "EUR",
                "Type": "expense",
            },
        )
        await _prepare(prefix)
        before_batch, before_row, _ = await _reload(prefix)
        normalized_snapshot = deepcopy(before_row.normalized_data)
        key_snapshot = before_row.deduplication_key

        await _post(prefix, commit=False)
        rolled_batch, rolled_row, rolled_transactions = await _reload(prefix)
        assert rolled_transactions == []
        assert rolled_row.status is ImportRowStatus.pending
        assert rolled_row.created_transaction_id is None
        assert rolled_row.created_investment_event_id is None
        assert rolled_row.normalized_data == normalized_snapshot
        assert rolled_row.deduplication_key == key_snapshot
        assert rolled_batch.status is before_batch.status is ImportStatus.processing
        assert rolled_batch.rows_imported == before_batch.rows_imported == 0
        await _assert_no_investment_side_effects()

        retry_id = await _post(prefix, commit=True)
        retry_batch, retry_row, retry_transactions = await _reload(prefix)
        assert len(retry_transactions) == 1
        assert retry_transactions[0].id == retry_id
        assert retry_row.status is ImportRowStatus.imported
        assert retry_row.created_transaction_id == retry_id
        assert retry_row.normalized_data == normalized_snapshot
        assert retry_row.deduplication_key == key_snapshot
        assert retry_batch.status is ImportStatus.processing
        assert retry_batch.rows_imported == 0
        await _assert_no_investment_side_effects()

    asyncio.run(scenario())


def test_corrupted_transaction_replay_fails_closed_without_repair() -> None:
    prefix = "post-corruption"

    async def scenario() -> None:
        await _seed(
            prefix,
            ImportSource.manual,
            {
                "Date": "2026-07-25",
                "Amount": "75",
                "Currency": "EUR",
                "Type": "income",
            },
        )
        await _prepare(prefix)
        transaction_id = await _post(prefix, commit=True)
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            transaction = await session.get(TransactionModel, transaction_id)
            assert transaction is not None
            transaction.amount = Decimal("999")
            await session.commit()

        async with AsyncSession(engine) as session:
            batch = await session.scalar(
                select(ImportBatchModel)
                .where(ImportBatchModel.id == f"{prefix}-batch")
                .with_for_update()
            )
            row = await session.scalar(
                select(ImportRowModel).where(ImportRowModel.id == f"{prefix}-row").with_for_update()
            )
            assert batch is not None and row is not None
            row_snapshot = (
                row.status,
                row.created_transaction_id,
                deepcopy(row.normalized_data),
                row.deduplication_key,
            )
            with pytest.raises(ImportPostStateError):
                await ImportTransactionPostingWriter(session).post_row(
                    account_id=f"{prefix}-account",
                    batch=batch,
                    row=row,
                )
            await session.rollback()
        await engine.dispose()

        batch, row, transactions = await _reload(prefix)
        assert len(transactions) == 1
        assert transactions[0].amount == Decimal("999.000000")
        assert (
            row.status,
            row.created_transaction_id,
            row.normalized_data,
            row.deduplication_key,
        ) == row_snapshot
        assert batch.status is ImportStatus.processing
        assert batch.rows_imported == 0
        await _assert_no_investment_side_effects()

    asyncio.run(scenario())
