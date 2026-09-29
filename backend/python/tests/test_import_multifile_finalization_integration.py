from __future__ import annotations

import asyncio
import importlib
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from unittest.mock import patch

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import AuthenticatedPrincipal
from app.db.models.background_jobs import BackgroundJobModel, ImportJobBatchModel
from app.db.models.enums import (
    BackgroundJobKind,
    BackgroundJobStatus,
    ExchangeRateSource,
    ImportSource,
    PriceSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.investment_snapshots import PortfolioSnapshotInputModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.prices import ExchangeRateModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.db.models.transactions import TransactionModel, TransactionReportingEvidenceModel
from app.db.models.users import UserModel
from app.modules.holdings.orchestration import HoldingRebuildApplicationService
from app.modules.imports import posting_service as posting_service_module
from app.modules.imports.job_executor import (
    ImportExecutionPayload,
    ImportExecutionStage,
    ImportJobExecutionRetryableError,
    ImportJobExecutor,
    ImportJobWideStageResult,
)
from app.modules.imports.multi_file_service import (
    FinalizeImportBatchesCommand,
    ImportMultiFileFinalizationService,
)
from app.modules.imports.posting_common import ImportPostStateError
from app.modules.imports.posting_service import (
    ImportBatchPostingService,
    PostImportBatchCommand,
)
from app.modules.market_data.source_policy import CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY
from app.modules.snapshot_refresh.market_backed_models import (
    MarketBackedSnapshotRefreshUnavailableError,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
posting_support = cast(
    Any,
    importlib.import_module("tests.test_import_posting_integration"),
)
post_processing_support = cast(
    Any,
    importlib.import_module("tests.test_import_post_processing_integration"),
)


async def _physical_counts(prefix: str) -> tuple[int, int, int]:
    engine = posting_support._engine()
    async with AsyncSession(engine) as session:
        counts = (
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


async def _canonical_counts(prefix: str) -> tuple[int, int]:
    engine = posting_support._engine()
    async with AsyncSession(engine) as session:
        counts = (
            int(
                await session.scalar(
                    select(func.count())
                    .select_from(InvestmentEventModel)
                    .where(InvestmentEventModel.account_id == f"{prefix}-account")
                )
                or 0
            ),
            int(
                await session.scalar(
                    select(func.count())
                    .select_from(InvestmentMovementModel)
                    .where(InvestmentMovementModel.account_id == f"{prefix}-account")
                )
                or 0
            ),
        )
    await engine.dispose()
    return counts


def test_postgresql_finalization_replays_complete_reporting_fx_lineage() -> None:
    """A reporting-FX stage runs before the durable finalization replay."""

    prefix = "r1d-finalize-reporting"
    job_id = f"{prefix}-job"
    rate_id = f"{prefix}-rate"

    async def scenario() -> None:
        await posting_support._seed(
            prefix,
            source=ImportSource.raiffeisenbank,
            rows=[
                {
                    "__raiffeisenbank_statement_kind": "account_statement",
                    "Datum provedení": "25.07.2026",
                    "Zaúčtovaná částka": "+10,00",
                    "Měna účtu": "EUR",
                    "Typ transakce": "Příchozí platba",
                    "Zpráva": "Reporting FX replay",
                    "Název protiúčtu": "Fixture counterparty",
                    "Id transakce": f"{prefix}-external",
                }
            ],
        )
        try:
            await posting_support._prepare(prefix)
            principal = posting_support._principal(f"{prefix}-owner")
            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                posted = await ImportBatchPostingService(session).post_batch(
                    PostImportBatchCommand(
                        principal=principal,
                        account_id=f"{prefix}-account",
                        batch_id=f"{prefix}-batch",
                    )
                )
                assert posted.status.value == "completed"
            await engine.dispose()

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                transaction = await session.scalar(
                    select(TransactionModel).where(
                        TransactionModel.import_batch_id == f"{prefix}-batch"
                    )
                )
                assert transaction is not None
                created_at = transaction.created_at
                session.add(
                    BackgroundJobModel(
                        id=job_id,
                        user_id=f"{prefix}-owner",
                        account_id=f"{prefix}-account",
                        kind=BackgroundJobKind.import_workflow,
                        status=BackgroundJobStatus.running,
                        idempotency_key=f"{prefix}-key",
                        payload={"batch_ids": [f"{prefix}-batch"]},
                        checkpoint={},
                        progress={},
                        result=None,
                        error_code=None,
                        error_message=None,
                        attempt_count=1,
                        manual_retry_count=0,
                        max_attempts=3,
                        run_after=created_at,
                        lease_owner=f"{prefix}-worker",
                        lease_version=1,
                        lease_expires_at=created_at + timedelta(minutes=5),
                        lease_heartbeat_at=created_at,
                        started_at=created_at,
                        finished_at=None,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
                session.add(
                    ImportJobBatchModel(
                        job_id=job_id,
                        batch_id=f"{prefix}-batch",
                        user_id=f"{prefix}-owner",
                        account_id=f"{prefix}-account",
                        created_at=created_at,
                    )
                )
                session.add(
                    ExchangeRateModel(
                        id=rate_id,
                        from_currency="EUR",
                        to_currency="CZK",
                        rate=Decimal("24.57500000"),
                        source=ExchangeRateSource.yahoo_finance,
                        date=transaction.date,
                        created_at=created_at,
                    )
                )
                transaction.reporting_amount = Decimal("245.750000")
                transaction.reporting_currency = "CZK"
                session.add(
                    TransactionReportingEvidenceModel(
                        transaction_id=transaction.id,
                        source_amount=transaction.amount,
                        source_currency=transaction.currency,
                        source_event_time=transaction.date,
                        reporting_amount=transaction.reporting_amount,
                        reporting_currency=transaction.reporting_currency,
                        exchange_rate_id=rate_id,
                        calculation_version=1,
                        background_job_id=job_id,
                        published_at=None,
                        created_at=created_at,
                    )
                )
                await session.commit()
            await engine.dispose()

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:

                class _UnavailableMarketService:
                    async def execute(self, _: object) -> object:
                        raise MarketBackedSnapshotRefreshUnavailableError

                result = await ImportMultiFileFinalizationService(
                    session,
                    market_backed_service=cast(Any, _UnavailableMarketService()),
                    source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
                ).finalize(
                    FinalizeImportBatchesCommand(
                        principal=principal,
                        account_id=f"{prefix}-account",
                        batch_ids=(f"{prefix}-batch",),
                    )
                )
                assert result.snapshot_refresh_status.value == "unavailable"
                assert session.in_transaction() is False
            await engine.dispose()

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                await session.execute(
                    delete(ImportJobBatchModel).where(ImportJobBatchModel.job_id == job_id)
                )
                await session.commit()
            await engine.dispose()

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:

                class _ForbiddenMarketService:
                    async def execute(self, _: object) -> object:
                        raise AssertionError("Corrupt reporting FX must fail before refresh.")

                with pytest.raises(ImportPostStateError):
                    await ImportMultiFileFinalizationService(
                        session,
                        market_backed_service=cast(Any, _ForbiddenMarketService()),
                        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
                    ).finalize(
                        FinalizeImportBatchesCommand(
                            principal=principal,
                            account_id=f"{prefix}-account",
                            batch_ids=(f"{prefix}-batch",),
                        )
                    )
                assert session.in_transaction() is False
            await engine.dispose()
        finally:
            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                transaction_ids = select(TransactionModel.id).where(
                    TransactionModel.import_batch_id == f"{prefix}-batch"
                )
                await session.execute(
                    delete(TransactionReportingEvidenceModel).where(
                        TransactionReportingEvidenceModel.transaction_id.in_(transaction_ids)
                    )
                )
                await session.execute(
                    delete(ImportJobBatchModel).where(ImportJobBatchModel.job_id == job_id)
                )
                await session.execute(
                    delete(BackgroundJobModel).where(BackgroundJobModel.id == job_id)
                )
                await session.execute(
                    delete(ExchangeRateModel).where(ExchangeRateModel.id == rate_id)
                )
                await session.commit()
            await engine.dispose()
            await posting_support._cleanup(prefix)

    asyncio.run(scenario())


def test_three_canonical_batches_have_one_logical_post_processing_phase() -> None:
    async def scenario() -> None:
        prefix = "r10a-three-file"
        symbol = "R10ATHREE"
        batch_ids = (
            f"{prefix}-batch",
            f"{prefix}-batch-b",
            f"{prefix}-batch-c",
        )
        completed_at = (
            datetime(2036, 8, 7, 10, 1, 1, 123000),
            datetime(2036, 8, 7, 10, 2, 2, 456000),
            datetime(2036, 8, 7, 10, 4, 59, 999000),
        )

        async def remove_snapshot_inputs() -> None:
            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                await session.execute(
                    delete(PortfolioSnapshotInputModel).where(
                        PortfolioSnapshotInputModel.account_id == f"{prefix}-account"
                    )
                )
                await session.commit()
            await engine.dispose()

        await remove_snapshot_inputs()
        await post_processing_support._cleanup_holdings(prefix)
        for batch_id in reversed(batch_ids[1:]):
            await post_processing_support._remove_additional_batch(batch_id)
        await posting_support._cleanup(prefix)
        await post_processing_support._remove_market_evidence(prefix)
        await posting_support._remove_asset_identities({symbol})
        await posting_support._seed(
            prefix,
            source=posting_support.ImportSource.trading212,
            rows=[posting_support._trading_buy(symbol, f"{prefix}-deposit")],
        )
        additional: list[str] = []
        try:
            await post_processing_support._seed_investment_identity(
                prefix,
                symbol,
                price_at=completed_at[0] - timedelta(hours=1),
                price_source=PriceSource.twelve_data,
            )
            await posting_support._prepare(prefix)
            additional.append(
                await post_processing_support._seed_additional_batch(
                    prefix,
                    suffix="b",
                    symbol=symbol,
                    external_id=f"{prefix}-buy",
                )
            )
            additional.append(
                await post_processing_support._seed_additional_batch(
                    prefix,
                    suffix="c",
                    symbol=symbol,
                    external_id=f"{prefix}-dividend-fee",
                )
            )

            engine = posting_support._engine()
            principal = posting_support._principal(f"{prefix}-owner")
            async with AsyncSession(engine) as session:
                for batch_id, timestamp in zip(batch_ids, completed_at, strict=True):
                    with patch.object(
                        posting_service_module,
                        "_current_timestamp",
                        return_value=timestamp,
                    ):
                        await ImportBatchPostingService(session).post_batch(
                            PostImportBatchCommand(
                                principal=principal,
                                account_id=f"{prefix}-account",
                                batch_id=batch_id,
                            )
                        )
                    assert session.in_transaction() is False
            await engine.dispose()

            assert await _physical_counts(prefix) == (0, 0, 0)
            canonical_counts = await _canonical_counts(prefix)
            assert canonical_counts[0] > 0
            assert canonical_counts[1] > 0

            unavailable_holding_calls = 0
            unavailable_market_calls = 0
            engine = posting_support._engine()
            async with AsyncSession(engine) as session:

                class _UnavailableMarketService:
                    async def execute(self, _: object) -> object:
                        nonlocal unavailable_market_calls
                        unavailable_market_calls += 1
                        raise MarketBackedSnapshotRefreshUnavailableError

                def unavailable_holding_factory(
                    factory_session: AsyncSession,
                    clock: Any,
                ) -> HoldingRebuildApplicationService:
                    nonlocal unavailable_holding_calls
                    unavailable_holding_calls += 1
                    return HoldingRebuildApplicationService(factory_session, clock=clock)

                unavailable = await ImportMultiFileFinalizationService(
                    session,
                    market_backed_service=cast(Any, _UnavailableMarketService()),
                    source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
                    holding_service_factory=unavailable_holding_factory,
                ).finalize(
                    FinalizeImportBatchesCommand(
                        principal=principal,
                        account_id=f"{prefix}-account",
                        batch_ids=batch_ids,
                    )
                )
                assert session.in_transaction() is False
            await engine.dispose()

            assert unavailable.snapshot_refresh_status.value == "unavailable"
            assert unavailable_holding_calls == 1
            assert unavailable_market_calls == 1
            assert await _physical_counts(prefix) == (1, 0, 0)
            assert await _canonical_counts(prefix) == canonical_counts

            holding_calls = 0
            market_calls = 0
            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                market_delegate = post_processing_support._SnapshotOnlyMarketBackedService(session)

                class _CountingMarketService:
                    async def execute(self, command: object) -> object:
                        nonlocal market_calls
                        market_calls += 1
                        return await market_delegate.execute(command)

                def holding_factory(
                    factory_session: AsyncSession,
                    clock: Any,
                ) -> HoldingRebuildApplicationService:
                    nonlocal holding_calls
                    holding_calls += 1
                    return HoldingRebuildApplicationService(factory_session, clock=clock)

                service = ImportMultiFileFinalizationService(
                    session,
                    market_backed_service=cast(Any, _CountingMarketService()),
                    source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
                    holding_service_factory=holding_factory,
                )
                result = await service.finalize(
                    FinalizeImportBatchesCommand(
                        principal=principal,
                        account_id=f"{prefix}-account",
                        batch_ids=batch_ids,
                    )
                )
                assert session.in_transaction() is False
            await engine.dispose()

            assert result.snapshot_refresh_status.value == "created"
            assert holding_calls == 1
            assert market_calls == 1
            assert await _physical_counts(prefix) == (1, 1, 1)
            assert await _canonical_counts(prefix) == canonical_counts

            engine = posting_support._engine()
            async with AsyncSession(engine) as session:
                account_snapshot = await session.scalar(
                    select(AccountSnapshotModel).where(
                        AccountSnapshotModel.account_id == f"{prefix}-account"
                    )
                )
                net_worth_snapshot = await session.scalar(
                    select(NetWorthSnapshotModel).where(
                        NetWorthSnapshotModel.user_id == f"{prefix}-owner"
                    )
                )
                assert account_snapshot is not None
                assert net_worth_snapshot is not None
                assert account_snapshot.timestamp == datetime(2036, 8, 7, 10, 4)
                assert net_worth_snapshot.timestamp == account_snapshot.timestamp
            await engine.dispose()

            async def concurrent_replay() -> str:
                replay_engine = posting_support._engine()
                async with AsyncSession(replay_engine) as replay_session:
                    replay = await ImportMultiFileFinalizationService(
                        replay_session,
                        market_backed_service=(
                            post_processing_support._SnapshotOnlyMarketBackedService(replay_session)
                        ),
                        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
                    ).finalize(
                        FinalizeImportBatchesCommand(
                            principal=principal,
                            account_id=f"{prefix}-account",
                            batch_ids=batch_ids,
                        )
                    )
                    assert replay_session.in_transaction() is False
                await replay_engine.dispose()
                return replay.snapshot_refresh_status.value

            replay_statuses = await asyncio.gather(
                concurrent_replay(),
                concurrent_replay(),
            )
            assert tuple(replay_statuses) == ("replayed", "replayed")
            assert await _physical_counts(prefix) == (1, 1, 1)
            assert await _canonical_counts(prefix) == canonical_counts
        finally:
            await remove_snapshot_inputs()
            await post_processing_support._cleanup_holdings(prefix)
            for batch_id in reversed(additional):
                await post_processing_support._remove_additional_batch(batch_id)
            await posting_support._cleanup(prefix)
            await post_processing_support._remove_market_evidence(prefix)
            await posting_support._remove_asset_identities({symbol})

    asyncio.run(scenario())


def test_durable_executor_starts_real_finalizer_with_idle_session() -> None:
    async def scenario() -> None:
        prefix = "r12c-idle-finalizer"
        symbol = "R12CIDLE"
        batch_id = f"{prefix}-batch"
        await posting_support._seed(
            prefix,
            source=posting_support.ImportSource.trading212,
            rows=[posting_support._trading_buy(symbol, f"{prefix}-deposit")],
        )
        try:
            await post_processing_support._seed_investment_identity(
                prefix,
                symbol,
                price_at=datetime(2036, 8, 7, 9, 0),
                price_source=PriceSource.twelve_data,
            )
            await posting_support._prepare(prefix)
            engine = posting_support._engine()
            principal = posting_support._principal(f"{prefix}-owner")
            async with AsyncSession(engine) as session:
                await ImportBatchPostingService(session).post_batch(
                    PostImportBatchCommand(
                        principal=principal,
                        account_id=f"{prefix}-account",
                        batch_id=batch_id,
                    )
                )
                assert session.in_transaction() is False

            session_factory = async_sessionmaker(engine, expire_on_commit=False)

            async def resolve_principal(
                session: AsyncSession,
                user_id: str,
            ) -> AuthenticatedPrincipal:
                persisted = await session.scalar(select(UserModel).where(UserModel.id == user_id))
                assert persisted is not None
                assert session.in_transaction() is True
                return AuthenticatedPrincipal(
                    user_id=persisted.id,
                    email=persisted.email,
                    name=persisted.name,
                )

            job_wide_stages: list[ImportExecutionStage] = []

            async def non_raiffeisenbank_job_wide_stage(
                stage: ImportExecutionStage,
                actual_job_id: str,
                actual_user_id: str,
                actual_account_id: str,
                actual_batch_ids: tuple[str, ...],
            ) -> ImportJobWideStageResult:
                assert actual_job_id == "r12c-idle-job"
                assert actual_user_id == principal.user_id
                assert actual_account_id == f"{prefix}-account"
                assert actual_batch_ids == (batch_id,)
                job_wide_stages.append(stage)
                return ImportJobWideStageResult(
                    job_id=actual_job_id,
                    stage=stage,
                    applied=False,
                )

            executor = ImportJobExecutor(
                session_factory,
                principal_resolver=resolve_principal,
                finalization_factory=lambda session: ImportMultiFileFinalizationService(
                    session,
                    market_backed_service=cast(Any, _UnavailableMarketService()),
                    source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
                ),
                job_wide_stage_hook=non_raiffeisenbank_job_wide_stage,
            )

            class _UnavailableMarketService:
                async def execute(self, _: object) -> object:
                    raise MarketBackedSnapshotRefreshUnavailableError

            with pytest.raises(ImportJobExecutionRetryableError) as raised:
                await executor.execute(
                    "r12c-idle-job",
                    principal.user_id,
                    f"{prefix}-account",
                    ImportExecutionPayload((batch_id,)),
                    ImportExecutionStage.canonical_post,
                    lambda _checkpoint: asyncio.sleep(0),
                )

            assert raised.value.status.value == "unavailable"
            assert job_wide_stages == [
                ImportExecutionStage.reconcile,
                ImportExecutionStage.acquire_reporting_fx,
                ImportExecutionStage.validate_liability_readiness,
            ]
            assert (await _physical_counts(prefix))[0] == 1
            await engine.dispose()
        finally:
            await post_processing_support._cleanup_holdings(prefix)
            await posting_support._cleanup(prefix)
            await post_processing_support._remove_market_evidence(prefix)
            await posting_support._remove_asset_identities({symbol})

    asyncio.run(scenario())
