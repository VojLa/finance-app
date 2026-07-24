from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete, func, select
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
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.imports.classification_service import ImportClassificationService
from app.modules.imports.deduplication import ImportDeduplicationService
from app.modules.imports.investment_posting import ImportInvestmentPostingWriter
from app.modules.imports.normalization import ImportNormalizationService
from app.modules.imports.posting_common import ImportPostStateError

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=4)


def _principal(prefix: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=f"{prefix}-user", email=f"{prefix}@example.com", name=prefix
    )


async def _seed(prefix: str, *, source: ImportSource, rows: list[dict[str, str]]) -> None:
    engine = _engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    account_id, batch_id, user_id = f"{prefix}-account", f"{prefix}-batch", f"{prefix}-user"
    async with AsyncSession(engine) as session:
        previous_event_ids = list(
            (
                await session.scalars(
                    select(InvestmentEventModel.id).where(
                        InvestmentEventModel.import_batch_id == batch_id
                    )
                )
            ).all()
        )
        if previous_event_ids:
            await session.execute(
                delete(InvestmentMovementModel).where(
                    InvestmentMovementModel.event_id.in_(previous_event_ids)
                )
            )
        await session.execute(
            delete(InvestmentEventModel).where(InvestmentEventModel.import_batch_id == batch_id)
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
                type=AccountType.broker
                if source is ImportSource.trading212
                else AccountType.exchange,
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
                filename=f"{prefix}.csv",
                file_size=1,
                file_encoding="utf-8",
                checksum=(prefix[:1] or "a") * 64,
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
    principal = _principal(prefix)
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


async def _post(prefix: str, *, commit: bool = True):
    engine = _engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        batch = await session.scalar(
            select(ImportBatchModel).where(ImportBatchModel.id == f"{prefix}-batch")
        )
        row = await session.scalar(
            select(ImportRowModel).where(ImportRowModel.id == f"{prefix}-row-0")
        )
        assert batch is not None and row is not None
        result = await ImportInvestmentPostingWriter(session).post_row(
            account_id=batch.account_id, batch=batch, row=row
        )
        if commit:
            await session.commit()
        else:
            await session.rollback()
    await engine.dispose()
    return result


async def _counts() -> dict[str, int]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        result = {
            model.__tablename__: int(
                await session.scalar(select(func.count()).select_from(model)) or 0
            )
            for model in (
                AssetModel,
                AssetListingModel,
                AssetAliasModel,
                InvestmentEventModel,
                InvestmentMovementModel,
                TransactionModel,
            )
        }
    await engine.dispose()
    return result


async def _batch_history_counts(prefix: str) -> tuple[int, int]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        event_ids = list(
            (
                await session.scalars(
                    select(InvestmentEventModel.id).where(
                        InvestmentEventModel.import_batch_id == f"{prefix}-batch"
                    )
                )
            ).all()
        )
        movements = (
            0
            if not event_ids
            else int(
                await session.scalar(
                    select(func.count())
                    .select_from(InvestmentMovementModel)
                    .where(InvestmentMovementModel.event_id.in_(event_ids))
                )
                or 0
            )
        )
    await engine.dispose()
    return len(event_ids), movements


def _trading_buy(symbol: str, isin: str) -> dict[str, str]:
    return {
        "Action": "Market buy",
        "Time": "2026-07-26T10:00:00Z",
        "Ticker": symbol,
        "ISIN": isin,
        "Name": "Writer fixture",
        "Asset type": "ETF",
        "No. of shares": "2",
        "Price / share": "100",
        "Currency (Price / share)": "EUR",
        "Total": "200",
        "Currency (Total)": "EUR",
        "ID": f"trade-{symbol}",
    }


def test_trading212_buy_persists_event_movements_and_exact_replay() -> None:
    prefix, symbol, isin = "b3-buy", "B3BUY", "ISINB3BUY"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)])
        await _prepare(prefix)
        first = await _post(prefix)
        original_event_timestamp = first.event.updated_at
        original_movement_ids = tuple(movement.id for movement in first.movements)
        second = await _post(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            row = await session.get(ImportRowModel, f"{prefix}-row-0")
            batch = await session.get(ImportBatchModel, f"{prefix}-batch")
            assert row is not None and batch is not None
            assert row.status is ImportRowStatus.imported
            assert (
                row.created_transaction_id is None
                and row.created_investment_event_id == first.event.id
            )
            assert batch.status is ImportStatus.processing and batch.rows_imported == 0
            event = await session.get(InvestmentEventModel, first.event.id)
            assert event is not None and event.updated_at == original_event_timestamp
        await engine.dispose()
        assert first.created is True and second.created is False
        assert first.event.id == second.event.id
        assert tuple(movement.id for movement in second.movements) == original_movement_ids
        assert len(first.movements) == 2
        assert await _batch_history_counts(prefix) == (1, 2)
        counts = await _counts()
        assert counts["AssetAlias"] == 0 and counts["Transaction"] == 0

    asyncio.run(scenario())


def test_anycoin_transfer_and_caller_rollback_retry() -> None:
    prefix = "b3-transfer"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.anycoin,
            rows=[
                {
                    "Type": "deposit",
                    "Order ID": "",
                    "Date": "2026-07-26T10:00:00Z",
                    "Amount": "0.01",
                    "Currency": "BTC",
                    "anycoin TX ID": "b3-deposit",
                }
            ],
        )
        await _prepare(prefix)
        first = await _post(prefix, commit=False)
        assert first.created is True
        assert await _batch_history_counts(prefix) == (0, 0)
        engine = _engine()
        async with AsyncSession(engine) as session:
            row = await session.get(ImportRowModel, f"{prefix}-row-0")
            assert row is not None
            assert row.status is ImportRowStatus.pending
            assert row.created_investment_event_id is None
        await engine.dispose()
        retry = await _post(prefix)
        assert retry.movements[0].direction.value == "in"
        assert retry.movements[0].asset_id is not None and retry.movements[0].listing_id is not None
        assert await _batch_history_counts(prefix) == (1, 1)

    asyncio.run(scenario())


def test_corrupt_event_fails_closed_without_repair() -> None:
    prefix, symbol, isin = "b3-corrupt", "B3CORRUPT", "ISINB3CORRUPT"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)])
        await _prepare(prefix)
        posted = await _post(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            event = await session.get(InvestmentEventModel, posted.event.id)
            assert event is not None
            event.description = "tampered"
            await session.commit()
        async with AsyncSession(engine) as session:
            batch = await session.get(ImportBatchModel, f"{prefix}-batch")
            row = await session.get(ImportRowModel, f"{prefix}-row-0")
            assert batch is not None and row is not None
            with pytest.raises(ImportPostStateError):
                await ImportInvestmentPostingWriter(session).post_row(
                    account_id=batch.account_id, batch=batch, row=row
                )
            assert row.created_investment_event_id == posted.event.id
        await engine.dispose()
        assert await _batch_history_counts(prefix) == (1, 2)

    asyncio.run(scenario())
