from __future__ import annotations

import asyncio
import importlib
import os
from datetime import datetime, timedelta
from typing import Any, cast
from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.modules.holdings.orchestration import HoldingRebuildApplicationService
from app.modules.imports import posting_service as posting_service_module
from app.modules.imports.multi_file_service import (
    FinalizeImportBatchesCommand,
    ImportMultiFileFinalizationService,
)
from app.modules.imports.posting_service import (
    ImportBatchPostingService,
    PostImportBatchCommand,
)
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
            await post_processing_support._cleanup_holdings(prefix)
            for batch_id in reversed(additional):
                await post_processing_support._remove_additional_batch(batch_id)
            await posting_support._cleanup(prefix)
            await post_processing_support._remove_market_evidence(prefix)
            await posting_support._remove_asset_identities({symbol})

    asyncio.run(scenario())
