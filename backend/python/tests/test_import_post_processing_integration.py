from __future__ import annotations

import asyncio
import importlib
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetType,
    ExchangeRateSource,
    ImportLogEvent,
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    PriceSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.imports import (
    ImportBatchModel,
    ImportLogModel,
    ImportRowModel,
)
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.transactions import TransactionModel
from app.main import create_app
from app.modules.holdings.orchestration import HoldingRebuildUnavailableError
from app.modules.imports import posting_service as posting_service_module
from app.modules.imports.classification_service import ImportClassificationService
from app.modules.imports.deduplication import ImportDeduplicationService
from app.modules.imports.models import ImportSnapshotRefreshStatus
from app.modules.imports.normalization import ImportNormalizationService
from app.modules.imports.post_processing_service import ImportBatchPostProcessingService
from app.modules.imports.posting_service import PostImportBatchCommand

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
posting_support = cast(
    Any,
    importlib.import_module("tests.test_import_posting_integration"),
)


async def _post(
    prefix: str,
    *,
    batch_id: str | None = None,
    principal_user_id: str | None = None,
    **service_kwargs: Any,
):
    engine = posting_support._engine()
    async with AsyncSession(engine) as session:
        result = await ImportBatchPostProcessingService(
            session,
            **service_kwargs,
        ).post_batch(
            PostImportBatchCommand(
                principal=posting_support._principal(principal_user_id or f"{prefix}-owner"),
                account_id=f"{prefix}-account",
                batch_id=batch_id or f"{prefix}-batch",
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


async def _seed_investment_identity(
    prefix: str,
    symbol: str,
    *,
    price_currency: str = "EUR",
    with_price: bool = True,
) -> None:
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
        if with_price:
            await session.flush()
            session.add(
                PriceSnapshotModel(
                    id=f"{prefix}-price",
                    asset_id=f"{prefix}-asset",
                    listing_id=f"{prefix}-listing",
                    price=Decimal("100"),
                    currency=price_currency,
                    source=PriceSource.broker,
                    timestamp=price_at,
                    created_at=now,
                )
            )
        await session.commit()
    await engine.dispose()


async def _add_price(prefix: str, *, currency: str = "EUR") -> None:
    engine = posting_support._engine()
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    async with AsyncSession(engine) as session:
        session.add(
            PriceSnapshotModel(
                id=f"{prefix}-price",
                asset_id=f"{prefix}-asset",
                listing_id=f"{prefix}-listing",
                price=Decimal("100"),
                currency=currency,
                source=PriceSource.broker,
                timestamp=datetime(2026, 7, 25, 12),
                created_at=now,
            )
        )
        await session.commit()
    await engine.dispose()


async def _add_rate(prefix: str, *, from_currency: str = "USD") -> None:
    engine = posting_support._engine()
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    async with AsyncSession(engine) as session:
        session.add(
            ExchangeRateModel(
                id=f"{prefix}-rate-{from_currency.lower()}-eur",
                from_currency=from_currency,
                to_currency="EUR",
                rate=Decimal("0.90000000"),
                date=datetime(2026, 7, 25, 12),
                source=ExchangeRateSource.ecb,
                created_at=now,
            )
        )
        await session.commit()
    await engine.dispose()


async def _row_counts(prefix: str) -> tuple[int, int, int, int, int]:
    engine = posting_support._engine()
    async with AsyncSession(engine) as session:
        batch_ids = select(ImportBatchModel.id).where(ImportBatchModel.id.startswith(f"{prefix}-"))
        event_ids = select(InvestmentEventModel.id).where(
            InvestmentEventModel.import_batch_id.in_(batch_ids)
        )
        counts = (
            int(
                await session.scalar(
                    select(func.count())
                    .select_from(InvestmentEventModel)
                    .where(InvestmentEventModel.id.in_(event_ids))
                )
                or 0
            ),
            int(
                await session.scalar(
                    select(func.count())
                    .select_from(InvestmentMovementModel)
                    .where(InvestmentMovementModel.event_id.in_(event_ids))
                )
                or 0
            ),
            int(
                await session.scalar(
                    select(func.count())
                    .select_from(HoldingModel)
                    .where(HoldingModel.account_id == f"{prefix}-account")
                )
                or 0
            ),
            int(
                await session.scalar(
                    select(func.count())
                    .select_from(AccountSnapshotModel)
                    .where(AccountSnapshotModel.account_id == f"{prefix}-account")
                )
                or 0
            ),
            int(
                await session.scalar(
                    select(func.count())
                    .select_from(NetWorthSnapshotModel)
                    .where(NetWorthSnapshotModel.user_id == f"{prefix}-owner")
                )
                or 0
            ),
        )
    await engine.dispose()
    return counts


async def _physical_snapshot_state(
    prefix: str,
) -> tuple[tuple[object, ...], tuple[tuple[object, ...], ...]]:
    engine = posting_support._engine()
    async with AsyncSession(engine) as session:
        account_row = (
            await session.execute(
                select(*AccountSnapshotModel.__table__.columns)
                .where(AccountSnapshotModel.account_id == f"{prefix}-account")
                .order_by(AccountSnapshotModel.id)
            )
        ).first()
        net_worth_rows = tuple(
            tuple(deepcopy(value) for value in row)
            for row in (
                await session.execute(
                    select(*NetWorthSnapshotModel.__table__.columns)
                    .where(NetWorthSnapshotModel.user_id == f"{prefix}-owner")
                    .order_by(NetWorthSnapshotModel.id)
                )
            ).all()
        )
        assert account_row is not None
        account_state = tuple(deepcopy(value) for value in account_row)
    await engine.dispose()
    return account_state, net_worth_rows


def _endpoint_call(prefix: str, *, principal_user_id: str | None = None):
    assert DATABASE_URL is not None
    app = create_app(
        Settings(
            environment="test",
            database_url=DATABASE_URL,
            docs_enabled=True,
            log_level="ERROR",
            log_json=False,
            internal_auth_secret="e2-acceptance-secret-with-32-characters",
            _env_file=None,
        )
    )
    app.dependency_overrides[get_current_principal] = lambda: posting_support._principal(
        principal_user_id or f"{prefix}-owner"
    )
    with TestClient(app) as client:
        return client.post(f"/api/v1/accounts/{prefix}-account/imports/{prefix}-batch/post")


async def _prepare_batch(prefix: str, batch_id: str) -> None:
    engine = posting_support._engine()
    principal = posting_support._principal(f"{prefix}-owner")
    account_id = f"{prefix}-account"
    async with AsyncSession(engine) as session:
        await ImportNormalizationService(session).normalize_batch(
            principal=principal,
            account_id=account_id,
            batch_id=batch_id,
        )
    async with AsyncSession(engine) as session:
        await ImportDeduplicationService(session).deduplicate_batch(
            principal=principal,
            account_id=account_id,
            batch_id=batch_id,
        )
    async with AsyncSession(engine) as session:
        await ImportClassificationService(session).classify_batch(
            principal=principal,
            account_id=account_id,
            batch_id=batch_id,
        )
    await engine.dispose()


async def _seed_additional_batch(
    prefix: str,
    *,
    suffix: str,
    symbol: str,
    external_id: str,
) -> str:
    batch_id = f"{prefix}-batch-{suffix}"
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    engine = posting_support._engine()
    async with AsyncSession(engine) as session:
        session.add(
            ImportBatchModel(
                id=batch_id,
                user_id=f"{prefix}-owner",
                account_id=f"{prefix}-account",
                source=ImportSource.trading212,
                filename=f"{batch_id}.csv",
                file_size=1,
                file_encoding="utf-8",
                checksum=(suffix[0] * 64),
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
                id=f"{batch_id}-row",
                import_batch_id=batch_id,
                row_number=2,
                raw_data=posting_support._trading_buy(symbol, external_id),
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
    await _prepare_batch(prefix, batch_id)
    return batch_id


async def _add_unsupported_account(prefix: str) -> str:
    account_id = f"{prefix}-unsupported-bank"
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    engine = posting_support._engine()
    async with AsyncSession(engine) as session:
        session.add(
            AccountModel(
                id=account_id,
                name="Unsupported bank",
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
                id=f"{account_id}-member",
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
        await session.commit()
    await engine.dispose()
    return account_id


async def _remove_unsupported_account(account_id: str) -> None:
    engine = posting_support._engine()
    async with AsyncSession(engine) as session:
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id == account_id)
        )
        await session.execute(delete(AccountModel).where(AccountModel.id == account_id))
        await session.commit()
    await engine.dispose()


async def _remove_additional_batch(batch_id: str) -> None:
    engine = posting_support._engine()
    async with AsyncSession(engine) as session:
        event_ids = tuple(
            (
                await session.scalars(
                    select(InvestmentEventModel.id).where(
                        InvestmentEventModel.import_batch_id == batch_id
                    )
                )
            ).all()
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
            delete(ImportLogModel).where(ImportLogModel.import_batch_id == batch_id)
        )
        await session.execute(
            delete(ImportRowModel).where(ImportRowModel.import_batch_id == batch_id)
        )
        await session.execute(delete(ImportBatchModel).where(ImportBatchModel.id == batch_id))
        await session.commit()
    await engine.dispose()


async def _remove_market_evidence(prefix: str) -> None:
    engine = posting_support._engine()
    async with AsyncSession(engine) as session:
        await session.execute(
            delete(PriceSnapshotModel).where(PriceSnapshotModel.id.startswith(f"{prefix}-"))
        )
        await session.execute(
            delete(ExchangeRateModel).where(ExchangeRateModel.id.startswith(f"{prefix}-"))
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
            await _seed_investment_identity(prefix, symbol)
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
            await _remove_market_evidence(prefix)
            await posting_support._remove_asset_identities({symbol})

    asyncio.run(scenario())


def test_holding_failure_preserves_committed_import_and_replay_recovers() -> None:
    async def scenario() -> None:
        prefix = "e2-r1-holding-recovery"
        symbol = "E2R1HOLD"
        verified_committed = False

        class FailingHoldingService:
            async def rebuild(self, command: object) -> object:
                nonlocal verified_committed
                engine = posting_support._engine()
                async with AsyncSession(engine) as session:
                    batch = await session.get(ImportBatchModel, f"{prefix}-batch")
                    assert batch is not None
                    assert batch.status in {
                        ImportStatus.completed,
                        ImportStatus.partially_completed,
                    }
                    event_ids = tuple(
                        (
                            await session.scalars(
                                select(InvestmentEventModel.id).where(
                                    InvestmentEventModel.import_batch_id == batch.id
                                )
                            )
                        ).all()
                    )
                    assert len(event_ids) == 1
                    assert (
                        await session.scalar(
                            select(func.count())
                            .select_from(InvestmentMovementModel)
                            .where(InvestmentMovementModel.event_id.in_(event_ids))
                        )
                        == 2
                    )
                    verified_committed = True
                await engine.dispose()
                raise HoldingRebuildUnavailableError()

        await posting_support._seed(
            prefix,
            source=ImportSource.trading212,
            rows=[posting_support._trading_buy(symbol, f"{prefix}-external")],
        )
        try:
            await _seed_investment_identity(prefix, symbol)
            await posting_support._prepare(prefix)
            failing = FailingHoldingService()
            first = await _post(
                prefix,
                holding_service_factory=lambda _session, _clock: failing,
            )
            assert verified_committed is True
            assert first.snapshot_refresh_status is ImportSnapshotRefreshStatus.unavailable
            assert await _row_counts(prefix) == (1, 2, 0, 0, 0)

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                batch = await session.get(ImportBatchModel, f"{prefix}-batch")
                assert batch is not None
                assert batch.status is ImportStatus.completed
                logs = tuple(
                    (
                        await session.scalars(
                            select(ImportLogModel).where(ImportLogModel.import_batch_id == batch.id)
                        )
                    ).all()
                )
                assert len(logs) == 1
                assert logs[0].event is ImportLogEvent.snapshot_validation_failed
                message = logs[0].message or ""
                for secret in (
                    prefix,
                    f"{prefix}-owner",
                    f"{prefix}-account",
                    f"{prefix}-external",
                    "holding_rebuild_unavailable",
                ):
                    assert secret not in message
            await engine.dispose()

            recovered = await _post(prefix)
            assert recovered.replayed is True
            assert recovered.snapshot_refresh_status in {
                ImportSnapshotRefreshStatus.created,
                ImportSnapshotRefreshStatus.replayed,
            }
            assert await _row_counts(prefix) == (1, 2, 1, 1, 1)
        finally:
            await _cleanup_holdings(prefix)
            await posting_support._cleanup(prefix)
            await _remove_market_evidence(prefix)
            await posting_support._remove_asset_identities({symbol})

    asyncio.run(scenario())


def test_missing_price_preserves_import_and_holdings_then_replay_completes() -> None:
    async def scenario() -> None:
        prefix = "e2-r1-price-recovery"
        symbol = "E2R1PRICE"
        await posting_support._seed(
            prefix,
            source=ImportSource.trading212,
            rows=[posting_support._trading_buy(symbol, f"{prefix}-external")],
        )
        try:
            await _seed_investment_identity(prefix, symbol, with_price=False)
            await posting_support._prepare(prefix)
            first = await _post(prefix)
            assert first.snapshot_refresh_status is ImportSnapshotRefreshStatus.unavailable
            assert await _row_counts(prefix) == (1, 2, 1, 0, 0)
            completed_at = first.completed_at
            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                holding_before = await session.scalar(
                    select(HoldingModel).where(HoldingModel.account_id == f"{prefix}-account")
                )
                assert holding_before is not None
                holding_identity = (
                    holding_before.id,
                    holding_before.quantity,
                    holding_before.calculated_at,
                )
            await engine.dispose()

            await _add_price(prefix)
            recovered = await _post(prefix)
            assert recovered.replayed is True
            assert recovered.completed_at == completed_at
            assert recovered.snapshot_refresh_status is ImportSnapshotRefreshStatus.created
            assert await _row_counts(prefix) == (1, 2, 1, 1, 1)
            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                holding_after = await session.scalar(
                    select(HoldingModel).where(HoldingModel.account_id == f"{prefix}-account")
                )
                assert holding_after is not None
                assert (
                    holding_after.id,
                    holding_after.quantity,
                    holding_after.calculated_at,
                ) == holding_identity
            await engine.dispose()
        finally:
            await _cleanup_holdings(prefix)
            await posting_support._cleanup(prefix)
            await _remove_market_evidence(prefix)
            await posting_support._remove_asset_identities({symbol})

    asyncio.run(scenario())


def test_missing_fx_preserves_committed_stages_then_replay_completes() -> None:
    async def scenario() -> None:
        prefix = "e2-r1-fx-recovery"
        symbol = "E2R1FX"
        await posting_support._seed(
            prefix,
            source=ImportSource.trading212,
            rows=[posting_support._trading_buy(symbol, f"{prefix}-external")],
        )
        try:
            await _seed_investment_identity(prefix, symbol, price_currency="USD")
            await posting_support._prepare(prefix)
            first = await _post(prefix)
            assert first.snapshot_refresh_status is ImportSnapshotRefreshStatus.unavailable
            assert await _row_counts(prefix) == (1, 2, 1, 0, 0)
            completed_at = first.completed_at

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                holding_before = await session.scalar(
                    select(HoldingModel).where(HoldingModel.account_id == f"{prefix}-account")
                )
                assert holding_before is not None
                holding_identity = (
                    holding_before.id,
                    holding_before.quantity,
                    holding_before.calculated_at,
                )
            await engine.dispose()

            await _add_rate(prefix)
            recovered = await _post(prefix)
            assert recovered.replayed is True
            assert recovered.completed_at == completed_at
            assert recovered.snapshot_refresh_status is ImportSnapshotRefreshStatus.created
            assert await _row_counts(prefix) == (1, 2, 1, 1, 1)

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                holding_after = await session.scalar(
                    select(HoldingModel).where(HoldingModel.account_id == f"{prefix}-account")
                )
                snapshot = await session.scalar(
                    select(AccountSnapshotModel).where(
                        AccountSnapshotModel.account_id == f"{prefix}-account"
                    )
                )
                assert holding_after is not None
                assert (
                    holding_after.id,
                    holding_after.quantity,
                    holding_after.calculated_at,
                ) == holding_identity
                assert snapshot is not None
                assert snapshot.timestamp == completed_at.replace(second=0, microsecond=0)
                assert snapshot.currency == "EUR"
            await engine.dispose()
        finally:
            await _cleanup_holdings(prefix)
            await posting_support._cleanup(prefix)
            await _remove_market_evidence(prefix)
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
            await _seed_investment_identity(prefix, symbol)
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
            await _remove_market_evidence(prefix)
            await posting_support._remove_asset_identities({symbol})

    asyncio.run(scenario())


def test_partially_completed_batch_refreshes_only_imported_targets() -> None:
    async def scenario() -> None:
        prefix = "e2-r1-partial"
        symbol = "E2R1PART"
        await posting_support._seed(
            prefix,
            source=ImportSource.trading212,
            rows=[
                posting_support._trading_buy(symbol, f"{prefix}-valid"),
                posting_support._trading_buy(symbol, f"{prefix}-failed"),
            ],
        )
        try:
            await _seed_investment_identity(prefix, symbol)
            await posting_support._prepare(prefix)
            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                batch = await session.get(ImportBatchModel, f"{prefix}-batch")
                rows = list(
                    (
                        await session.scalars(
                            select(ImportRowModel)
                            .where(ImportRowModel.import_batch_id == f"{prefix}-batch")
                            .order_by(ImportRowModel.row_number)
                        )
                    ).all()
                )
                assert batch is not None
                assert len(rows) == 2
                failed = rows[1]
                failed.status = ImportRowStatus.failed
                failed.normalized_data = None
                failed.validation_errors = {"code": "blank_row"}
                failed.deduplication_key = None
                failed.error_message = "The row is blank."
                failed.created_transaction_id = None
                failed.created_investment_event_id = None
                batch.rows_skipped = 1
                await session.commit()
            await engine.dispose()

            first = await _post(prefix)
            assert first.status is ImportStatus.partially_completed
            assert first.rows_imported == 1
            assert first.rows_skipped == 1
            assert first.snapshot_refresh_status is ImportSnapshotRefreshStatus.created
            assert await _row_counts(prefix) == (1, 2, 1, 1, 1)

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                persisted_rows = tuple(
                    (
                        await session.scalars(
                            select(ImportRowModel)
                            .where(ImportRowModel.import_batch_id == f"{prefix}-batch")
                            .order_by(ImportRowModel.row_number)
                        )
                    ).all()
                )
                assert persisted_rows[0].status is ImportRowStatus.imported
                assert persisted_rows[0].created_investment_event_id is not None
                assert persisted_rows[0].created_transaction_id is None
                assert persisted_rows[1].status is ImportRowStatus.failed
                assert persisted_rows[1].created_investment_event_id is None
                assert persisted_rows[1].created_transaction_id is None
            await engine.dispose()

            replay = await _post(prefix)
            assert replay.replayed is True
            assert replay.status is ImportStatus.partially_completed
            assert replay.snapshot_refresh_status is ImportSnapshotRefreshStatus.replayed
            assert await _row_counts(prefix) == (1, 2, 1, 1, 1)
        finally:
            await _cleanup_holdings(prefix)
            await posting_support._cleanup(prefix)
            await _remove_market_evidence(prefix)
            await posting_support._remove_asset_identities({symbol})

    asyncio.run(scenario())


def test_supported_investment_import_with_other_unsupported_account_is_unavailable() -> None:
    async def scenario() -> None:
        prefix = "e2-r1-whole-user-unsupported"
        symbol = "E2R1UNSUP"
        unsupported_id: str | None = None
        await posting_support._seed(
            prefix,
            source=ImportSource.trading212,
            rows=[posting_support._trading_buy(symbol, f"{prefix}-external")],
        )
        try:
            await _seed_investment_identity(prefix, symbol)
            unsupported_id = await _add_unsupported_account(prefix)
            await posting_support._prepare(prefix)
            first = await _post(prefix)
            assert first.snapshot_refresh_status is ImportSnapshotRefreshStatus.unavailable
            assert await _row_counts(prefix) == (1, 2, 1, 0, 0)
            assert unsupported_id not in str(first.model_dump(mode="json"))

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AccountSnapshotModel)
                        .where(
                            AccountSnapshotModel.account_id.in_(
                                (f"{prefix}-account", unsupported_id)
                            )
                        )
                    )
                    == 0
                )
                logs = tuple(
                    (
                        await session.scalars(
                            select(ImportLogModel).where(
                                ImportLogModel.import_batch_id == f"{prefix}-batch"
                            )
                        )
                    ).all()
                )
                assert {log.event for log in logs} == {
                    ImportLogEvent.holdings_recalculated,
                    ImportLogEvent.snapshot_validation_failed,
                }
                for log in logs:
                    assert unsupported_id not in (log.message or "")
                    assert "bank" not in (log.message or "").lower()
            await engine.dispose()

            replay = await _post(prefix)
            assert replay.replayed is True
            assert replay.snapshot_refresh_status is ImportSnapshotRefreshStatus.unavailable
            assert await _row_counts(prefix) == (1, 2, 1, 0, 0)
        finally:
            await _cleanup_holdings(prefix)
            if unsupported_id is not None:
                await _remove_unsupported_account(unsupported_id)
            await posting_support._cleanup(prefix)
            await _remove_market_evidence(prefix)
            await posting_support._remove_asset_identities({symbol})

    asyncio.run(scenario())


def test_immutable_snapshot_conflict_preserves_existing_snapshot_without_repair() -> None:
    async def scenario() -> None:
        prefix = "e2-r1-immutable-conflict"
        symbol = "E2R1CONFLICT"
        await posting_support._seed(
            prefix,
            source=ImportSource.trading212,
            rows=[posting_support._trading_buy(symbol, f"{prefix}-external")],
        )
        try:
            await _seed_investment_identity(prefix, symbol)
            await posting_support._prepare(prefix)
            created = await _post(prefix)
            assert created.snapshot_refresh_status is ImportSnapshotRefreshStatus.created
            assert await _row_counts(prefix) == (1, 2, 1, 1, 1)

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                snapshot = await session.scalar(
                    select(AccountSnapshotModel).where(
                        AccountSnapshotModel.account_id == f"{prefix}-account"
                    )
                )
                assert snapshot is not None
                snapshot.fees_value = Decimal("1.000000")
                await session.commit()
            await engine.dispose()
            corrupted_state = await _physical_snapshot_state(prefix)

            conflict = await _post(prefix)
            assert conflict.replayed is True
            assert conflict.snapshot_refresh_status is ImportSnapshotRefreshStatus.conflict
            assert await _physical_snapshot_state(prefix) == corrupted_state
            assert await _row_counts(prefix) == (1, 2, 1, 1, 1)

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                failure_logs = tuple(
                    (
                        await session.scalars(
                            select(ImportLogModel).where(
                                ImportLogModel.import_batch_id == f"{prefix}-batch",
                                ImportLogModel.event == ImportLogEvent.snapshot_validation_failed,
                            )
                        )
                    ).all()
                )
                assert len(failure_logs) == 1
                assert prefix not in (failure_logs[0].message or "")
            await engine.dispose()
        finally:
            await _cleanup_holdings(prefix)
            await posting_support._cleanup(prefix)
            await _remove_market_evidence(prefix)
            await posting_support._remove_asset_identities({symbol})

    asyncio.run(scenario())


def test_two_financially_different_batches_in_same_minute_conflict_without_time_shift() -> None:
    async def scenario() -> None:
        prefix = "e2-r1-same-minute"
        symbol = "E2R1MINUTE"
        first_completed = datetime(2036, 7, 29, 14, 35, 10)
        second_completed = datetime(2036, 7, 29, 14, 35, 40)
        second_batch_id: str | None = None
        await posting_support._seed(
            prefix,
            source=ImportSource.trading212,
            rows=[posting_support._trading_buy(symbol, f"{prefix}-first")],
        )
        try:
            await _seed_investment_identity(prefix, symbol)
            await posting_support._prepare(prefix)
            with patch.object(
                posting_service_module,
                "_current_timestamp",
                return_value=first_completed,
            ):
                first = await _post(prefix)
            assert first.completed_at == first_completed
            assert first.snapshot_refresh_status is ImportSnapshotRefreshStatus.created
            original_state = await _physical_snapshot_state(prefix)

            second_batch_id = await _seed_additional_batch(
                prefix,
                suffix="second",
                symbol=symbol,
                external_id=f"{prefix}-second",
            )
            with patch.object(
                posting_service_module,
                "_current_timestamp",
                return_value=second_completed,
            ):
                second = await _post(prefix, batch_id=second_batch_id)
            assert second.completed_at == second_completed
            assert second.snapshot_refresh_status is ImportSnapshotRefreshStatus.conflict
            assert await _physical_snapshot_state(prefix) == original_state

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                snapshots = tuple(
                    (
                        await session.scalars(
                            select(AccountSnapshotModel).where(
                                AccountSnapshotModel.account_id == f"{prefix}-account"
                            )
                        )
                    ).all()
                )
                assert len(snapshots) == 1
                assert snapshots[0].timestamp == datetime(2036, 7, 29, 14, 35)
                assert snapshots[0].timestamp <= first_completed
                holding = await session.scalar(
                    select(HoldingModel).where(HoldingModel.account_id == f"{prefix}-account")
                )
                assert holding is not None
                assert holding.quantity == Decimal("4.0000000000")
            await engine.dispose()
            assert await _row_counts(prefix) == (2, 4, 1, 1, 1)
        finally:
            await _cleanup_holdings(prefix)
            if second_batch_id is not None:
                await _remove_additional_batch(second_batch_id)
            await posting_support._cleanup(prefix)
            await _remove_market_evidence(prefix)
            await posting_support._remove_asset_identities({symbol})

    asyncio.run(scenario())


def test_concurrent_import_post_endpoint_requests_converge() -> None:
    async def seed() -> None:
        prefix = "e2-r1-endpoint-concurrent"
        symbol = "E2R1HTTP"
        await posting_support._seed(
            prefix,
            source=ImportSource.trading212,
            rows=[posting_support._trading_buy(symbol, f"{prefix}-external")],
        )
        await _seed_investment_identity(prefix, symbol)
        await posting_support._prepare(prefix)

    prefix = "e2-r1-endpoint-concurrent"
    symbol = "E2R1HTTP"
    asyncio.run(seed())
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(_endpoint_call, prefix)
            second_future = pool.submit(_endpoint_call, prefix)
            first = first_future.result(timeout=30)
            second = second_future.result(timeout=30)
        assert first.status_code == second.status_code == 200
        assert {first.json()["replayed"], second.json()["replayed"]} == {False, True}
        assert {
            first.json()["snapshot_refresh_status"],
            second.json()["snapshot_refresh_status"],
        } == {"created", "replayed"}
        assert asyncio.run(_row_counts(prefix)) == (1, 2, 1, 1, 1)

        async def verify_audits() -> None:
            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                logs = tuple(
                    (
                        await session.scalars(
                            select(ImportLogModel).where(
                                ImportLogModel.import_batch_id == f"{prefix}-batch"
                            )
                        )
                    ).all()
                )
                assert len({log.id for log in logs}) == len(logs)
                assert len(logs) == 4
            await engine.dispose()

        asyncio.run(verify_audits())
    finally:
        asyncio.run(_cleanup_holdings(prefix))
        asyncio.run(posting_support._cleanup(prefix))
        asyncio.run(_remove_market_evidence(prefix))
        asyncio.run(posting_support._remove_asset_identities({symbol}))


def test_import_post_endpoint_principal_isolation_prevents_post_processing() -> None:
    async def scenario() -> None:
        prefix = "e2-r1-principal-isolation"
        symbol = "E2R1ISOLATE"
        await posting_support._seed(
            prefix,
            source=ImportSource.trading212,
            rows=[posting_support._trading_buy(symbol, f"{prefix}-external")],
        )
        await _seed_investment_identity(prefix, symbol)
        await posting_support._prepare(prefix)

    prefix = "e2-r1-principal-isolation"
    symbol = "E2R1ISOLATE"
    asyncio.run(scenario())
    try:
        response = _endpoint_call(
            prefix,
            principal_user_id=f"{prefix}-other",
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "account_not_found"
        assert asyncio.run(_row_counts(prefix)) == (0, 0, 0, 0, 0)

        async def verify_unchanged() -> None:
            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                batch = await session.get(ImportBatchModel, f"{prefix}-batch")
                assert batch is not None
                assert batch.status is ImportStatus.processing
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(ImportLogModel)
                        .where(ImportLogModel.import_batch_id == batch.id)
                    )
                    == 0
                )
            await engine.dispose()

        asyncio.run(verify_unchanged())
    finally:
        asyncio.run(_cleanup_holdings(prefix))
        asyncio.run(posting_support._cleanup(prefix))
        asyncio.run(_remove_market_evidence(prefix))
        asyncio.run(posting_support._remove_asset_identities({symbol}))


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
