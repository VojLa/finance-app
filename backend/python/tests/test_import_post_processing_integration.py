from __future__ import annotations

import asyncio
import importlib
import os
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AssetType,
    ImportLogEvent,
    ImportSource,
    ImportStatus,
    PriceSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.imports import ImportBatchModel, ImportLogModel
from app.db.models.ledger import InvestmentEventModel
from app.db.models.prices import PriceSnapshotModel
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.transactions import TransactionModel
from app.modules.imports.models import ImportSnapshotRefreshStatus
from app.modules.imports.post_processing_service import ImportBatchPostProcessingService
from app.modules.imports.posting_service import PostImportBatchCommand

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
posting_support = cast(
    Any,
    importlib.import_module("tests.test_import_posting_integration"),
)


async def _post(prefix: str):
    engine = posting_support._engine()
    async with AsyncSession(engine) as session:
        result = await ImportBatchPostProcessingService(session).post_batch(
            PostImportBatchCommand(
                principal=posting_support._principal(f"{prefix}-owner"),
                account_id=f"{prefix}-account",
                batch_id=f"{prefix}-batch",
            )
        )
        assert session.in_transaction() is False
    await engine.dispose()
    return result


async def _cleanup_holdings(prefix: str) -> None:
    engine = posting_support._engine()
    async with AsyncSession(engine) as session:
        snapshot_ids = tuple(
            (
                await session.scalars(
                    select(AccountSnapshotModel.id).where(
                        AccountSnapshotModel.account_id == f"{prefix}-account"
                    )
                )
            ).all()
        )
        if snapshot_ids:
            await session.execute(
                delete(AccountSnapshotItemModel).where(
                    AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids)
                )
            )
            await session.execute(
                delete(AccountSnapshotModel).where(AccountSnapshotModel.id.in_(snapshot_ids))
            )
        await session.execute(
            delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id == f"{prefix}-owner")
        )
        await session.execute(
            delete(HoldingModel).where(HoldingModel.account_id == f"{prefix}-account")
        )
        await session.commit()
    await engine.dispose()


async def _seed_price_identity(prefix: str, symbol: str) -> None:
    engine = posting_support._engine()
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    price_at = datetime(2026, 7, 25, 12)
    async with AsyncSession(engine) as session:
        session.add(
            AssetModel(
                id=f"{prefix}-asset",
                symbol=symbol,
                isin=f"ISIN-{symbol}",
                name=symbol,
                asset_type=AssetType.etf,
                currency="EUR",
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            AssetListingModel(
                id=f"{prefix}-listing",
                asset_id=f"{prefix}-asset",
                symbol=symbol,
                exchange="trading212",
                mic=None,
                currency="EUR",
                country=None,
                provider=PriceSource.broker,
                provider_symbol=symbol,
                is_primary=False,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            PriceSnapshotModel(
                id=f"{prefix}-price",
                asset_id=f"{prefix}-asset",
                listing_id=f"{prefix}-listing",
                price=Decimal("100"),
                currency="EUR",
                source=PriceSource.broker,
                timestamp=price_at,
                created_at=now,
            )
        )
        await session.commit()
    await engine.dispose()


def test_transaction_only_unsupported_account_preserves_committed_import() -> None:
    async def scenario() -> None:
        prefix = "e2-transaction"
        await posting_support._seed(
            prefix,
            source=ImportSource.manual,
            rows=[posting_support._manual("e2-transaction-row")],
        )
        try:
            await posting_support._prepare(prefix)
            first = await _post(prefix)
            second = await _post(prefix)
            assert first.snapshot_refresh_status is ImportSnapshotRefreshStatus.unavailable
            assert second.snapshot_refresh_status is ImportSnapshotRefreshStatus.unavailable
            assert first.replayed is False
            assert second.replayed is True

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                batch = await session.get(ImportBatchModel, f"{prefix}-batch")
                assert batch is not None
                assert batch.status is ImportStatus.completed
                assert batch.rows_imported == 1
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(TransactionModel)
                        .where(TransactionModel.import_batch_id == batch.id)
                    )
                    == 1
                )
                logs = tuple(
                    (
                        await session.scalars(
                            select(ImportLogModel).where(ImportLogModel.import_batch_id == batch.id)
                        )
                    ).all()
                )
                assert len(logs) == 1
                assert logs[0].event is ImportLogEvent.snapshot_validation_failed
                assert "account" not in (logs[0].message or "").lower()
            await engine.dispose()
        finally:
            await posting_support._cleanup(prefix)

    asyncio.run(scenario())


def test_investment_import_rebuilds_holdings_and_creates_then_replays_snapshots() -> None:
    async def scenario() -> None:
        prefix = "e2-investment"
        symbol = "E2INV"
        await posting_support._seed(
            prefix,
            source=ImportSource.trading212,
            rows=[posting_support._trading_buy(symbol, "e2-investment-row")],
        )
        try:
            await _seed_price_identity(prefix, symbol)
            await posting_support._prepare(prefix)
            first = await _post(prefix)
            second = await _post(prefix)
            assert first.snapshot_refresh_status is ImportSnapshotRefreshStatus.created
            assert second.snapshot_refresh_status is ImportSnapshotRefreshStatus.replayed
            assert second.replayed is True

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                batch = await session.get(ImportBatchModel, f"{prefix}-batch")
                assert batch is not None
                assert batch.status is ImportStatus.completed
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(InvestmentEventModel)
                        .where(InvestmentEventModel.import_batch_id == batch.id)
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AccountSnapshotModel)
                        .where(AccountSnapshotModel.account_id == f"{prefix}-account")
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(NetWorthSnapshotModel)
                        .where(NetWorthSnapshotModel.user_id == f"{prefix}-owner")
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(HoldingModel)
                        .where(HoldingModel.account_id == f"{prefix}-account")
                    )
                    == 1
                )
                events = set(
                    (
                        await session.scalars(
                            select(ImportLogModel.event).where(
                                ImportLogModel.import_batch_id == batch.id
                            )
                        )
                    ).all()
                )
                assert events == {
                    ImportLogEvent.holdings_recalculated,
                    ImportLogEvent.snapshots_recalculated,
                }
            await engine.dispose()
        finally:
            await _cleanup_holdings(prefix)
            await posting_support._cleanup(prefix)
            await posting_support._remove_asset_identities({symbol})

    asyncio.run(scenario())


def test_concurrent_investment_post_processing_is_exact_and_deduplicated() -> None:
    async def scenario() -> None:
        prefix = "e2-concurrent"
        symbol = "E2CON"
        await posting_support._seed(
            prefix,
            source=ImportSource.trading212,
            rows=[posting_support._trading_buy(symbol, "e2-concurrent-row")],
        )
        try:
            await _seed_price_identity(prefix, symbol)
            await posting_support._prepare(prefix)
            results = await asyncio.gather(_post(prefix), _post(prefix))

            assert {result.snapshot_refresh_status for result in results} == {
                ImportSnapshotRefreshStatus.created,
                ImportSnapshotRefreshStatus.replayed,
            }
            assert {result.replayed for result in results} == {False, True}

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(InvestmentEventModel)
                        .where(InvestmentEventModel.import_batch_id == f"{prefix}-batch")
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(HoldingModel)
                        .where(HoldingModel.account_id == f"{prefix}-account")
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AccountSnapshotModel)
                        .where(AccountSnapshotModel.account_id == f"{prefix}-account")
                    )
                    == 1
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(NetWorthSnapshotModel)
                        .where(NetWorthSnapshotModel.user_id == f"{prefix}-owner")
                    )
                    == 1
                )
                log_events = tuple(
                    (
                        await session.scalars(
                            select(ImportLogModel.event).where(
                                ImportLogModel.import_batch_id == f"{prefix}-batch"
                            )
                        )
                    ).all()
                )
                assert log_events.count(ImportLogEvent.holdings_recalculated) == 2
                assert log_events.count(ImportLogEvent.snapshots_recalculated) == 2
            await engine.dispose()
        finally:
            await _cleanup_holdings(prefix)
            await posting_support._cleanup(prefix)
            await posting_support._remove_asset_identities({symbol})

    asyncio.run(scenario())


def test_zero_import_batch_is_post_processing_noop() -> None:
    async def scenario() -> None:
        prefix = "e2-zero"
        await posting_support._seed(
            prefix,
            source=ImportSource.manual,
            rows=[posting_support._manual("e2-zero-row")],
        )
        try:
            await posting_support._configure_non_posting_batch(prefix, ["duplicate"])
            result = await _post(prefix)
            assert result.snapshot_refresh_status is ImportSnapshotRefreshStatus.not_required

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                batch = await session.get(ImportBatchModel, f"{prefix}-batch")
                assert batch is not None
                assert batch.status is ImportStatus.completed
                assert batch.rows_imported == 0
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(ImportLogModel)
                        .where(ImportLogModel.import_batch_id == batch.id)
                    )
                    == 0
                )
            await engine.dispose()
        finally:
            await posting_support._cleanup(prefix)

    asyncio.run(scenario())
