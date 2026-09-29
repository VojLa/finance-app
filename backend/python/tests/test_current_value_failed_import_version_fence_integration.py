from __future__ import annotations

import importlib
import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.canonical_lineage import DailySnapshotBaselineModel
from app.db.models.enums import (
    AssetAliasProvider,
    AssetType,
    ImportSource,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.prices import PriceSnapshotModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.db.url import normalize_database_url
from app.modules.current_value.service import (
    CurrentValueService,
    CurrentValueUnavailableError,
    ReadCurrentPortfolioCommand,
)
from app.modules.market_data.source_policy import (
    LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
)
from app.modules.snapshot_refresh.executor import (
    ExecuteUserSnapshotRefreshCommand,
    UserSnapshotRefreshExecutor,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required"),
]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
CURRENT_SCHEMA = BACKEND_ROOT / "database" / "revisions" / "410001serieslinks" / "schema.sql"


def _support() -> ModuleType:
    return importlib.import_module("tests.test_r10d2_current_value_integration")


async def _publish_v2(support: Any, *, user_id: str) -> tuple[str, str]:
    engine = support._engine()
    try:
        async with AsyncSession(engine) as session:
            result = await UserSnapshotRefreshExecutor(
                session,
                source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
            ).execute(
                ExecuteUserSnapshotRefreshCommand(
                    user_id=user_id,
                    snapshot_timestamp=support.BASELINE_AT,
                    granularity=SnapshotGranularity.day,
                    source=SnapshotSource.manual_recalculation,
                    calculation_version=2,
                    calculated_at=support.BASELINE_AT,
                    created_at=support.BASELINE_AT,
                    is_recalculated=True,
                )
            )
            assert result.calculation_version == 2
            assert len(result.account_snapshots) == 1
            return result.account_snapshots[0].snapshot_id, result.net_worth_snapshot_id
    finally:
        await engine.dispose()


async def _publish_unsupported_v1(support: Any, *, user_id: str) -> None:
    engine = support._engine()
    try:
        async with AsyncSession(engine) as session:
            result = await UserSnapshotRefreshExecutor(
                session,
            ).execute(
                ExecuteUserSnapshotRefreshCommand(
                    user_id=user_id,
                    snapshot_timestamp=support.BASELINE_AT,
                    granularity=SnapshotGranularity.day,
                    source=SnapshotSource.manual_recalculation,
                    calculation_version=1,
                    calculated_at=support.BASELINE_AT,
                    created_at=support.BASELINE_AT,
                    is_recalculated=True,
                )
            )
            assert result.calculation_version == 1
    finally:
        await engine.dispose()


async def _read_current(
    support: Any,
    *,
    user_id: str,
    price_id: str,
):
    engine = support._engine()
    try:
        async with AsyncSession(engine) as session:
            settings = Settings(
                environment="test",
                market_evidence_source_mode="local_free",
                _env_file=None,
            )
            service = CurrentValueService(
                session,
                settings,
                clock=lambda: support.CURRENT_AT,
                market_service_factory=lambda _session, _settings, _planner: (
                    support._ReplayMarketService(
                        user_id,
                        "EUR",
                        (price_id,),
                        (),
                    )
                ),
            )
            return await service.read_portfolio(
                ReadCurrentPortfolioCommand(
                    principal=AuthenticatedPrincipal(
                        user_id=user_id,
                        email=f"{user_id}@example.test",
                        name="Version-fence integration",
                    )
                )
            )
    finally:
        await engine.dispose()


async def _seed_published_investment(
    support: Any,
    *,
    prefix: str,
    version: int,
) -> tuple[str, str, str]:
    source = ImportSource.trading212 if version == 2 else ImportSource.anycoin
    asset_type = AssetType.stock if version == 2 else AssetType.crypto
    provider = AssetAliasProvider.yahoo_finance if version == 2 else AssetAliasProvider.coingecko
    user_id, account_id, listing_id = await support._seed_investment(
        prefix,
        source=source,
        asset_type=asset_type,
        provider=provider,
        external_id="AAA" if version == 2 else "bitcoin",
    )
    if version == 2:
        engine = support._engine()
        try:
            async with AsyncSession(engine) as session, session.begin():
                prices = tuple(
                    (
                        await session.scalars(
                            select(PriceSnapshotModel).where(
                                PriceSnapshotModel.id.in_(
                                    (
                                        f"{prefix}-baseline-price",
                                        f"{listing_id}-current-price",
                                    )
                                )
                            )
                        )
                    ).all()
                )
                assert len(prices) == 2
                for price in prices:
                    price.source = PriceSource.yahoo_finance
                    price.price = Decimal("10.0000000000")
        finally:
            await engine.dispose()
    await support._investment_cash_deposit(
        prefix,
        account_id=account_id,
        at=support.BASELINE_AT - timedelta(days=2),
        amount="100.0000000000",
        currency="EUR",
    )
    await support._investment_buy(
        prefix,
        account_id=account_id,
        listing_id=listing_id,
        source=source,
        at=support.BASELINE_AT - timedelta(days=1),
        price="10.0000000000",
    )
    await support._rebuild(account_id, at=support.BASELINE_AT - timedelta(hours=1))
    if version == 2:
        await _publish_v2(support, user_id=user_id)
    else:
        assert version == 1
        await _publish_unsupported_v1(support, user_id=user_id)
    return user_id, account_id, listing_id


@pytest.mark.asyncio
async def test_failed_investment_import_retains_exact_coherent_v2_publication_only() -> None:
    assert DATABASE_URL is not None
    support = _support()
    mutable_support = cast(Any, support)
    original_support_url = mutable_support.DATABASE_URL
    source_url = make_url(normalize_database_url(DATABASE_URL))
    database_name = f"finance_app_version_fence_{uuid4().hex}"
    admin_url = source_url.set(drivername="postgresql", database="postgres")
    target_url = source_url.set(database=database_name)
    admin = await asyncpg.connect(admin_url.render_as_string(hide_password=False))
    try:
        await admin.execute(f'CREATE DATABASE "{database_name}"')
        target = await asyncpg.connect(
            target_url.set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            await target.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
            schema = CURRENT_SCHEMA.read_text(encoding="utf-8").replace(
                'CREATE SCHEMA "public";\n', "", 1
            )
            await target.execute(schema)
            await target.execute(
                "CREATE TABLE public.alembic_version ("
                "version_num varchar(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
            await target.execute(
                "INSERT INTO public.alembic_version (version_num) VALUES ('410001serieslinks')"
            )
        finally:
            await target.close()

        mutable_support.DATABASE_URL = target_url.render_as_string(hide_password=False)

        unsupported_prefix = f"fence-v1-{uuid4().hex}"
        (
            unsupported_user,
            unsupported_account,
            unsupported_listing,
        ) = await _seed_published_investment(
            support,
            prefix=unsupported_prefix,
            version=1,
        )
        await support._failed_import_job(
            unsupported_user,
            unsupported_account,
            job_id=f"{unsupported_prefix}-job",
        )
        with pytest.raises(CurrentValueUnavailableError):
            await _read_current(
                support,
                user_id=unsupported_user,
                price_id=f"{unsupported_listing}-baseline-price",
            )

        prefix = f"fence-v2-{uuid4().hex}"
        user_id, account_id, listing_id = await _seed_published_investment(
            support,
            prefix=prefix,
            version=2,
        )

        # A legacy version is never a normal fallback. It becomes eligible only
        # while an active import fence protects its account publication.
        with pytest.raises(CurrentValueUnavailableError):
            await _read_current(
                support,
                user_id=user_id,
                price_id=f"{listing_id}-baseline-price",
            )

        engine = support._engine()
        try:
            async with AsyncSession(engine) as session:
                baseline = await session.scalar(
                    select(DailySnapshotBaselineModel).where(
                        DailySnapshotBaselineModel.user_id == user_id
                    )
                )
                assert baseline is not None and baseline.calculation_version == 2
                net_worth = await session.get(
                    NetWorthSnapshotModel,
                    baseline.net_worth_snapshot_id,
                )
                assert net_worth is not None
                assert net_worth.calculation_version == 2
                assert net_worth.total_net_worth == Decimal("100.000000")
                account_snapshot = await session.scalar(
                    select(AccountSnapshotModel).where(
                        AccountSnapshotModel.account_id == account_id,
                        AccountSnapshotModel.calculation_version == 2,
                    )
                )
                assert account_snapshot is not None
                assert account_snapshot.cash_value == Decimal("90.000000")
                assert account_snapshot.investment_value == Decimal("10.000000")
                assert account_snapshot.total_value == Decimal("100.000000")
        finally:
            await engine.dispose()

        await support._failed_import_job(
            user_id,
            account_id,
            job_id=f"{prefix}-job",
        )
        await support._investment_buy(
            prefix,
            account_id=account_id,
            listing_id=listing_id,
            source=ImportSource.trading212,
            at=support.BASELINE_AT - timedelta(hours=1),
            price="10.0000000000",
        )
        await support._rebuild(account_id, at=support.CURRENT_AT)

        frozen = await _read_current(
            support,
            user_id=user_id,
            price_id=f"{listing_id}-baseline-price",
        )
        account = frozen.portfolio.accounts[0]
        assert account.summary.cash_value == Decimal("90.000000")
        assert account.summary.investment_value == Decimal("10.000000")
        assert account.summary.total_value == Decimal("100.000000")
        assert frozen.portfolio.summary.total_value == Decimal("100.000000")
    finally:
        mutable_support.DATABASE_URL = original_support_url
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
        await admin.close()
