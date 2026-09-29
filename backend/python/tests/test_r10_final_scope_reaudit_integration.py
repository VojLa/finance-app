"""Authenticated HTTP acceptance closing the R10 final release blocker."""

from __future__ import annotations

import asyncio
import importlib
import os
import re
from datetime import timedelta
from typing import Annotated, Any, cast

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.canonical_lineage import (
    AccountSnapshotCanonicalBoundaryModel,
    DailySnapshotBaselineAccountModel,
    DailySnapshotBaselineModel,
)
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.snapshot_series_jobs import SnapshotSeriesDirtyStateModel
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.transactions import TransactionModel
from app.main import create_app
from app.modules.current_value.api import (
    get_current_value_clock,
    get_current_value_service,
)
from app.modules.current_value.service import CurrentValueService
from app.modules.snapshot_refresh.executor import (
    ExecuteUserSnapshotRefreshCommand,
    UserSnapshotRefreshExecutor,
)
from app.modules.snapshot_refresh.version import (
    current_coordinated_snapshot_calculation_version,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
PUBLIC_MONEY = re.compile(r"^-?(?:0|[1-9]\d{0,11})\.\d{6}$")

d2 = cast(Any, importlib.import_module("tests.test_r10d2_current_value_integration"))
investment_support = cast(
    Any,
    importlib.import_module("tests.support.investment_fixture_e2e"),
)


def _app():
    assert DATABASE_URL is not None
    app = create_app(
        Settings(
            environment="test",
            database_url=DATABASE_URL,
            docs_enabled=True,
            log_level="ERROR",
            log_json=False,
            internal_auth_secret=investment_support.SECRET,
            _env_file=None,
        )
    )
    app.dependency_overrides[get_current_value_clock] = lambda: lambda: d2.CURRENT_AT
    return app


async def _finance_counts(prefix: str) -> tuple[int, ...]:
    engine = d2._engine()
    user_id = f"{prefix}-user"
    account_id = f"{prefix}-account"
    async with AsyncSession(engine) as session:
        queries = (
            select(func.count())
            .select_from(AccountSnapshotModel)
            .where(AccountSnapshotModel.account_id == account_id),
            select(func.count())
            .select_from(AccountSnapshotItemModel)
            .join(
                AccountSnapshotModel,
                AccountSnapshotItemModel.snapshot_id == AccountSnapshotModel.id,
            )
            .where(AccountSnapshotModel.account_id == account_id),
            select(func.count())
            .select_from(AccountSnapshotCanonicalBoundaryModel)
            .where(AccountSnapshotCanonicalBoundaryModel.account_id == account_id),
            select(func.count())
            .select_from(NetWorthSnapshotModel)
            .where(NetWorthSnapshotModel.user_id == user_id),
            select(func.count())
            .select_from(DailySnapshotBaselineModel)
            .where(DailySnapshotBaselineModel.user_id == user_id),
            select(func.count())
            .select_from(DailySnapshotBaselineAccountModel)
            .where(DailySnapshotBaselineAccountModel.account_id == account_id),
            select(func.count())
            .select_from(TransactionModel)
            .where(TransactionModel.account_id == account_id),
            select(func.count())
            .select_from(InvestmentEventModel)
            .where(InvestmentEventModel.account_id == account_id),
            select(func.count())
            .select_from(InvestmentMovementModel)
            .where(InvestmentMovementModel.account_id == account_id),
            select(func.count())
            .select_from(LiabilityBalanceModel)
            .where(LiabilityBalanceModel.account_id == account_id),
            select(func.count())
            .select_from(HoldingModel)
            .where(HoldingModel.account_id == account_id),
        )
        counts = [int(await session.scalar(query) or 0) for query in queries]
        result = tuple(counts)
    await engine.dispose()
    return result


async def _cleanup(prefix: str) -> None:
    user_id = f"{prefix}-user"
    account_id = f"{prefix}-account"
    engine = d2._engine()
    try:
        async with AsyncSession(engine) as session:
            await investment_support.cleanup_snapshot_publications(
                session,
                user_ids=(user_id,),
                account_ids=(account_id,),
            )
            await session.commit()
    finally:
        await engine.dispose()
    await d2._cleanup(prefix)


async def _daily_baseline(user_id: str) -> None:
    engine = d2._engine()
    try:
        async with AsyncSession(engine) as session:
            # The direct refresh publishes the fixture's complete canonical state.
            # Liability writes also enqueue a separate series rebuild request.
            await session.execute(
                delete(SnapshotSeriesDirtyStateModel).where(
                    SnapshotSeriesDirtyStateModel.user_id == user_id
                )
            )
            await session.commit()
            await UserSnapshotRefreshExecutor(session).execute(
                ExecuteUserSnapshotRefreshCommand(
                    user_id=user_id,
                    snapshot_timestamp=d2.BASELINE_AT,
                    granularity=SnapshotGranularity.day,
                    source=SnapshotSource.manual_recalculation,
                    calculation_version=current_coordinated_snapshot_calculation_version(),
                    calculated_at=d2.BASELINE_AT,
                    created_at=d2.BASELINE_AT,
                    is_recalculated=True,
                )
            )
    finally:
        await engine.dispose()


def test_authenticated_current_endpoints_keep_scope_and_forward_delta_without_writes() -> None:
    prefix = "r10e1-current-http"

    async def seed() -> tuple[str, tuple[int, ...]]:
        await _cleanup(prefix)
        user_id, account_id = await d2._seed_cash(prefix)
        await d2._transaction(
            account_id,
            transaction_id=f"{prefix}-baseline",
            date=d2.BASELINE_AT - timedelta(days=1),
            amount="100.000000",
        )
        await _daily_baseline(user_id)
        await d2._transaction(
            account_id,
            transaction_id=f"{prefix}-forward",
            date=d2.BASELINE_AT + timedelta(hours=2),
            amount="25.000000",
        )
        return user_id, await _finance_counts(prefix)

    try:
        user_id, before = asyncio.run(seed())
        app = _app()
        with TestClient(app) as client:
            portfolio = client.post(
                "/api/v1/portfolio/current",
                headers=investment_support.headers(user_id),
            )
            dashboard = client.post(
                "/api/v1/dashboard/current",
                headers=investment_support.headers(user_id),
            )

        assert portfolio.status_code == dashboard.status_code == 200
        portfolio_json = portfolio.json()
        dashboard_json = dashboard.json()
        assert (
            portfolio_json["asOf"]
            == dashboard_json["asOf"]
            == d2.CURRENT_AT.isoformat(timespec="milliseconds")
        )
        assert (
            portfolio_json["baselineTimestamp"]
            == dashboard_json["baselineTimestamp"]
            == d2.BASELINE_AT.isoformat(timespec="milliseconds")
        )
        assert (
            portfolio_json["historyAnchorSnapshotId"] == dashboard_json["historyAnchorSnapshotId"]
        )
        assert portfolio_json["currency"] == dashboard_json["currency"] == "EUR"
        assert portfolio_json["summary"]["cashValue"] == "0.000000"
        assert portfolio_json["summary"]["totalValue"] == "0.000000"
        assert portfolio_json["accounts"] == []
        assert dashboard_json["summary"]["totalValue"] == "125.000000"
        assert dashboard_json["accounts"][0]["accountCurrency"] == "EUR"
        assert dashboard_json["accounts"][0]["cashValue"] == "125.000000"
        assert dashboard_json["accounts"][0]["netDepositsValue"] == "0.000000"
        assert asyncio.run(_finance_counts(prefix)) == before
    finally:
        asyncio.run(_cleanup(prefix))


def test_authenticated_mixed_currency_endpoints_keep_primary_and_presentation_authorities() -> None:
    prefix = "r10e1-mixed-http"

    async def seed() -> tuple[str, str, tuple[int, ...]]:
        await _cleanup(prefix)
        user_id, account_id = await d2._seed(
            prefix,
            base_currency="CZK",
            account_currency="EUR",
        )
        await d2._liability(
            account_id,
            effective_at=d2.BASELINE_AT - timedelta(days=1),
            external_id="baseline",
            amount="100.000000",
        )
        await d2._rate(prefix, currency="EUR", at=d2.BASELINE_AT, value="25.00000000")
        await _daily_baseline(user_id)
        await d2._liability(
            account_id,
            effective_at=d2.BASELINE_AT + timedelta(hours=2),
            external_id="forward",
            amount="75.000000",
        )
        rate_id = await d2._rate(
            prefix,
            currency="EUR",
            at=d2.CURRENT_AT,
            value="24.00000000",
        )
        return user_id, rate_id, await _finance_counts(prefix)

    observed_idle: list[bool] = []
    try:
        user_id, rate_id, before = asyncio.run(seed())
        app = _app()

        def service_after_authentication(
            session: Annotated[AsyncSession, Depends(get_db_session)],
        ) -> CurrentValueService:
            observed_idle.append(not session.in_transaction())
            return CurrentValueService(
                session,
                app.state.settings,
                clock=lambda: d2.CURRENT_AT,
                market_service_factory=lambda _session, _settings, _planner: (
                    d2._ReplayMarketService(
                        user_id,
                        "CZK",
                        (),
                        (rate_id,),
                    )
                ),
            )

        app.dependency_overrides[get_current_value_service] = service_after_authentication
        with TestClient(app) as client:
            portfolio = client.post(
                "/api/v1/portfolio/current",
                headers=investment_support.headers(user_id),
            )
            dashboard = client.post(
                "/api/v1/dashboard/current",
                headers=investment_support.headers(user_id),
            )

        assert observed_idle == [True, True]
        assert portfolio.status_code == dashboard.status_code == 200
        portfolio_json = portfolio.json()
        dashboard_json = dashboard.json()
        assert portfolio_json["currency"] == dashboard_json["currency"] == "CZK"
        assert portfolio_json["summary"]["liabilitiesValue"] == "0.000000"
        assert portfolio_json["summary"]["totalValue"] == "0.000000"
        assert portfolio_json["accounts"] == []
        card = dashboard_json["accounts"][0]
        assert card["accountCurrency"] == card["outputCurrency"] == "EUR"
        assert card["liabilitiesValue"] == "75.000000"
        assert dashboard_json["summary"]["liabilitiesValue"] == "1800.000000"
        assert dashboard_json["summary"]["totalValue"] == "-1800.000000"
        assert PUBLIC_MONEY.fullmatch(dashboard_json["summary"]["liabilitiesValue"]) is not None
        assert asyncio.run(_finance_counts(prefix)) == before
    finally:
        asyncio.run(_cleanup(prefix))


def test_authenticated_current_failure_contracts_remain_distinct() -> None:
    prefix = "r10e1-current-failures"
    try:
        asyncio.run(_cleanup(prefix))
        user_id, _ = asyncio.run(d2._seed_cash(prefix))
        app = _app()
        with TestClient(app) as client:
            no_baseline = client.post(
                "/api/v1/portfolio/current",
                headers=investment_support.headers(user_id),
            )
            invalid_auth = client.post(
                "/api/v1/portfolio/current",
                headers={"Authorization": "Bearer invalid"},
            )

        assert no_baseline.status_code == 409
        assert no_baseline.json()["error"]["code"] == "current_value_unavailable"
        assert invalid_auth.status_code == 401
        assert invalid_auth.json()["error"]["code"] == "invalid_session_token"
    finally:
        asyncio.run(_cleanup(prefix))
