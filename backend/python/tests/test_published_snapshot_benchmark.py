"""Opt-in local measurement of exact published projection reads."""

from __future__ import annotations

import os
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from statistics import median, quantiles
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.canonical_lineage import (
    AccountCanonicalStateModel,
    DailySnapshotBaselineAccountModel,
    DailySnapshotBaselineModel,
    SnapshotGenerationModel,
    SnapshotGenerationTargetModel,
    UserReadModelPublicationModel,
)
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    SnapshotSource,
)
from app.db.models.enums import (
    SnapshotGranularity as DbSnapshotGranularity,
)
from app.db.models.investment_snapshots import PortfolioSnapshotModel
from app.db.models.snapshot_series_publication import (
    SnapshotSeriesHeadModel,
    SnapshotSeriesPointLinkModel,
)
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.accounts.access import AccountNotFoundError
from app.modules.portfolio_snapshot.authorized_reader import PortfolioSnapshotUnavailableError
from app.modules.portfolio_snapshot.models import SnapshotGranularity
from app.modules.portfolio_snapshot.multi_account_service import (
    AuthorizedMultiAccountPortfolioSnapshotService,
    ExactAccountSnapshotSelection,
    ReadAuthorizedMultiAccountPortfolioSnapshotCommand,
)
from app.modules.published_snapshot import api as published_api

DATABASE_URL = os.getenv("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not (
        os.getenv("RUN_PUBLISHED_BENCHMARK") == "1"
        and "finance_app_stabilization_test" in DATABASE_URL
    ),
    reason="opt-in; disposable finance_app_stabilization_test only",
)
AT = datetime(2026, 9, 28)
AMOUNT = Decimal("10.000000")
ZERO = Decimal("0.000000")


@pytest.mark.asyncio
@pytest.mark.parametrize("count", (1, 5, 20))
async def test_published_read_latency(count: int) -> None:
    prefix = f"bench-{uuid4().hex[:12]}"
    user_id = f"{prefix}-user"
    generation_id = f"{prefix}-generation"
    net_worth_id = f"{prefix}-net-worth"
    portfolio_id = f"{prefix}-portfolio"
    baseline_id = f"{prefix}-baseline"
    head_id = f"{prefix}-head"
    clone_name = f"finance_app_bench_{uuid4().hex[:16]}"
    base_url = make_url(normalize_database_url(DATABASE_URL))
    admin_engine = create_async_engine(base_url.set(database="postgres"))
    async with admin_engine.connect() as connection:
        await connection.execution_options(isolation_level="AUTOCOMMIT")
        await connection.execute(
            text(f'CREATE DATABASE "{clone_name}" TEMPLATE "finance_app_stabilization_test"')
        )
    engine = create_async_engine(base_url.set(database=clone_name), pool_size=3)
    account_ids = tuple(f"{prefix}-account-{index}" for index in range(count))
    try:
        async with AsyncSession(engine) as session:
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{user_id}@example.invalid",
                    name="Benchmark",
                    base_currency="EUR",
                    created_at=AT,
                    updated_at=AT,
                )
            )
            session.add(
                SnapshotGenerationModel(
                    id=generation_id,
                    state="staged",
                    created_at=AT,
                    published_at=None,
                )
            )
            await session.flush()
            session.add(
                SnapshotGenerationTargetModel(
                    generation_id=generation_id,
                    user_id=user_id,
                    created_at=AT,
                )
            )
            for account_id in account_ids:
                session.add(
                    AccountModel(
                        id=account_id,
                        name=account_id,
                        type=AccountType.broker,
                        currency="EUR",
                        is_archived=False,
                        created_at=AT,
                        updated_at=AT,
                    )
                )
            await session.flush()
            for account_id in account_ids:
                session.add(
                    AccountMemberModel(
                        id=f"{account_id}-member",
                        account_id=account_id,
                        user_id=user_id,
                        role=AccountMemberRole.owner,
                        relation_type=AccountRelationType.owner,
                        accepted_at=AT,
                        created_at=AT,
                        updated_at=AT,
                    )
                )
                session.add(
                    AccountSnapshotModel(
                        id=f"{account_id}-snapshot",
                        account_id=account_id,
                        generation_id=generation_id,
                        timestamp=AT,
                        granularity=DbSnapshotGranularity.day,
                        source=SnapshotSource.manual_recalculation,
                        currency="EUR",
                        cash_value=AMOUNT,
                        investment_value=ZERO,
                        investment_cost_basis=ZERO,
                        liabilities_value=ZERO,
                        total_value=AMOUNT,
                        is_recalculated=True,
                        calculated_at=AT,
                        calculation_version=1,
                        created_at=AT,
                        net_deposits_value=ZERO,
                        realized_pnl_value=ZERO,
                        unrealized_pnl_value=ZERO,
                        fees_value=ZERO,
                        taxes_value=ZERO,
                        cash_value_by_currency={"EUR": "10.000000"},
                        net_deposits_by_currency={},
                        exchange_rates={"version": 1, "snapshotRates": [], "historicalRateIds": []},
                    )
                )
            await session.flush()
            await session.execute(
                update(AccountCanonicalStateModel)
                .where(AccountCanonicalStateModel.account_id.in_(account_ids))
                .values(last_revision=1, updated_at=AT)
            )
            total = AMOUNT * count
            session.add(
                NetWorthSnapshotModel(
                    id=net_worth_id,
                    user_id=user_id,
                    generation_id=generation_id,
                    timestamp=AT,
                    granularity=DbSnapshotGranularity.day,
                    source=SnapshotSource.manual_recalculation,
                    currency="EUR",
                    cash_value=total,
                    portfolio_value=ZERO,
                    liabilities_value=ZERO,
                    total_net_worth=total,
                    is_recalculated=True,
                    calculated_at=AT,
                    calculation_version=1,
                    created_at=AT,
                )
            )
            session.add(
                PortfolioSnapshotModel(
                    id=portfolio_id,
                    user_id=user_id,
                    generation_id=generation_id,
                    timestamp=AT,
                    valuation_timestamp=AT,
                    granularity=DbSnapshotGranularity.day,
                    source=SnapshotSource.manual_recalculation,
                    currency="EUR",
                    cash_value=total,
                    investment_value=ZERO,
                    investment_cost_basis=ZERO,
                    net_deposits_value=ZERO,
                    realized_pnl_value=ZERO,
                    unrealized_pnl_value=ZERO,
                    fees_value=ZERO,
                    taxes_value=ZERO,
                    calculated_at=AT,
                    calculation_version=1,
                    created_at=AT,
                )
            )
            await session.flush()
            session.add(
                DailySnapshotBaselineModel(
                    id=baseline_id,
                    user_id=user_id,
                    net_worth_snapshot_id=net_worth_id,
                    generation_id=generation_id,
                    timestamp=AT,
                    granularity=DbSnapshotGranularity.day,
                    source=SnapshotSource.manual_recalculation,
                    currency="EUR",
                    calculation_version=1,
                    created_at=AT,
                )
            )
            session.add(
                SnapshotSeriesHeadModel(
                    id=head_id,
                    user_id=user_id,
                    version=1,
                    generation_id=generation_id,
                    created_at=AT,
                )
            )
            await session.flush()
            for account_id in account_ids:
                session.add(
                    DailySnapshotBaselineAccountModel(
                        baseline_id=baseline_id,
                        account_id=account_id,
                        account_type=AccountType.broker,
                        account_currency="EUR",
                        primary_snapshot_id=f"{account_id}-snapshot",
                        presentation_snapshot_id=f"{account_id}-snapshot",
                        canonical_revision=1,
                        generation_id=generation_id,
                    )
                )
            session.add(
                SnapshotSeriesPointLinkModel(
                    id=f"{prefix}-link",
                    user_id=user_id,
                    timestamp=AT,
                    granularity=DbSnapshotGranularity.day,
                    valid_from_version=1,
                    generation_id=generation_id,
                    baseline_id=baseline_id,
                    portfolio_snapshot_id=portfolio_id,
                    net_worth_snapshot_id=net_worth_id,
                    created_at=AT,
                )
            )
            generation = await session.get(SnapshotGenerationModel, generation_id)
            assert generation is not None
            generation.state = "published"
            generation.published_at = AT
            await session.flush()
            session.add(
                UserReadModelPublicationModel(
                    user_id=user_id,
                    version=f"{prefix}-publication",
                    baseline_id=baseline_id,
                    generation_id=generation_id,
                    generation_state="published",
                    series_head_id=head_id,
                    scopes=["portfolio", "dashboard"],
                    published_at=AT,
                )
            )
            await session.commit()

        command = ReadAuthorizedMultiAccountPortfolioSnapshotCommand(
            principal=AuthenticatedPrincipal(
                user_id=user_id, email=f"{user_id}@example.invalid", name="Benchmark"
            ),
            timestamp=AT,
            granularity=SnapshotGranularity.day,
            currency="EUR",
            calculation_version=1,
            accounts=tuple(
                ExactAccountSnapshotSelection(account_id, f"{account_id}-snapshot")
                for account_id in account_ids
            ),
        )
        cold: list[float] = []
        warm: list[float] = []
        cold_queries: list[int] = []
        warm_queries: list[int] = []
        query_count = [0]

        def count_query(*_args: object) -> None:
            query_count[0] += 1

        event.listen(engine.sync_engine, "before_cursor_execute", count_query)
        for index in range(50):
            published_api._read_cache.clear()
            async with AsyncSession(engine) as session:
                before = query_count[0]
                started = perf_counter()
                baseline, result = await published_api._read_latest(
                    principal=command.principal,
                    session=session,
                    account_types=frozenset({AccountType.broker}),
                )
                cold.append((perf_counter() - started) * 1000)
                cold_queries.append(query_count[0] - before)
                assert baseline.baseline_id == baseline_id
                assert result.portfolio.summary.account_count == count
                before = query_count[0]
                started = perf_counter()
                baseline, result = await published_api._read_latest(
                    principal=command.principal,
                    session=session,
                    account_types=frozenset({AccountType.broker}),
                )
                warm.append((perf_counter() - started) * 1000)
                warm_queries.append(query_count[0] - before)
                assert baseline.baseline_id == baseline_id
                assert result.portfolio.summary.account_count == count
            if index == 0:
                cold.clear()  # exclude engine/statement warmup
                warm.clear()
                cold_queries.clear()
                warm_queries.clear()
        for label, samples in (("cold", cold), ("warm", warm)):
            p50 = median(samples)
            p95 = quantiles(samples, n=100)[94]
            print(f"PUBLISHED_READ_BENCH count={count} {label} p50={p50:.2f}ms p95={p95:.2f}ms")
            assert p95 < 100
        print(
            f"PUBLISHED_READ_QUERIES count={count} cold={set(cold_queries)} warm={set(warm_queries)}"
        )
        assert len(set(cold_queries)) == len(set(warm_queries)) == 1
        assert cold_queries[0] > warm_queries[0]
        event.remove(engine.sync_engine, "before_cursor_execute", count_query)
        # A canonical import transaction may be open while a published read
        # takes its own repeatable-read view of the last complete publication.
        async with AsyncSession(engine) as writer_session:
            async with writer_session.begin():
                await writer_session.execute(
                    update(AccountCanonicalStateModel)
                    .where(AccountCanonicalStateModel.account_id == account_ids[0])
                    .values(last_revision=2)
                )
                published_api._read_cache.clear()
                async with AsyncSession(engine) as reader_session:
                    baseline, concurrent_result = await published_api._read_latest(
                        principal=command.principal,
                        session=reader_session,
                        account_types=frozenset({AccountType.broker}),
                    )
                    assert baseline.baseline_id == baseline_id
                    assert concurrent_result.portfolio.summary.account_count == count
        wrong = replace(
            command,
            accounts=(
                ExactAccountSnapshotSelection(account_ids[0], "wrong-snapshot"),
                *command.accounts[1:],
            ),
        )
        async with AsyncSession(engine) as session:
            with pytest.raises(PortfolioSnapshotUnavailableError):
                await AuthorizedMultiAccountPortfolioSnapshotService(session).read(wrong)
        async with AsyncSession(engine) as session:
            await session.execute(
                delete(AccountMemberModel).where(
                    AccountMemberModel.account_id == account_ids[0],
                    AccountMemberModel.user_id == user_id,
                )
            )
            await session.commit()
        async with AsyncSession(engine) as session:
            with pytest.raises(AccountNotFoundError):
                await AuthorizedMultiAccountPortfolioSnapshotService(session).read(command)
    finally:
        published_api._read_cache.clear()
        await engine.dispose()
        async with admin_engine.connect() as connection:
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.execute(text(f'DROP DATABASE "{clone_name}" WITH (FORCE)'))
        await admin_engine.dispose()
