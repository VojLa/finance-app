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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.canonical_lineage import (
    AccountSnapshotCanonicalBoundaryModel,
    DailySnapshotBaselineAccountModel,
    DailySnapshotBaselineModel,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.liabilities import LiabilityBalanceModel
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

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
PUBLIC_MONEY = re.compile(r"^-?(?:0|[1-9]\d{0,11})\.\d{6}$")

d2 = cast(Any, importlib.import_module("tests.test_r10d2_current_value_integration"))
investment_support = cast(
    Any,
    importlib.import_module("tests.support.investment_fixture_e2e"),
)

COUNTED_MODELS = (
    AccountSnapshotModel,
    AccountSnapshotItemModel,
    AccountSnapshotCanonicalBoundaryModel,
    NetWorthSnapshotModel,
    DailySnapshotBaselineModel,
    DailySnapshotBaselineAccountModel,
    TransactionModel,
    InvestmentEventModel,
    InvestmentMovementModel,
    LiabilityBalanceModel,
    HoldingModel,
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


async def _finance_counts() -> tuple[int, ...]:
    engine = d2._engine()
    async with AsyncSession(engine) as session:
        counts: list[int] = []
        for model in COUNTED_MODELS:
            counts.append(int(await session.scalar(select(func.count()).select_from(model)) or 0))
        result = tuple(counts)
    await engine.dispose()
    return result


def test_authenticated_current_endpoints_apply_forward_delta_and_leave_finance_unchanged() -> None:
    prefix = "r10e1-current-http"

    async def seed() -> tuple[str, tuple[int, ...]]:
        user_id, account_id = await d2._seed_cash(prefix)
        await d2._transaction(
            account_id,
            transaction_id=f"{prefix}-baseline",
            date=d2.BASELINE_AT - timedelta(days=1),
            amount="100.000000",
        )
        await d2._daily_baseline(user_id)
        await d2._transaction(
            account_id,
            transaction_id=f"{prefix}-forward",
            date=d2.BASELINE_AT + timedelta(hours=2),
            amount="25.000000",
        )
        return user_id, await _finance_counts()

    user_id, before = asyncio.run(seed())
    try:
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
        assert portfolio_json["summary"]["cashValue"] == "125.000000"
        assert portfolio_json["summary"]["totalValue"] == "125.000000"
        assert portfolio_json["accounts"][0]["currency"] == "EUR"
        assert portfolio_json["accounts"][0]["summary"]["cashValue"] == "125.000000"
        assert dashboard_json["summary"]["totalValue"] == "125.000000"
        assert dashboard_json["accounts"][0]["accountCurrency"] == "EUR"
        assert dashboard_json["accounts"][0]["cashValue"] == "125.000000"
        assert dashboard_json["accounts"][0]["netDepositsValue"] == "0.000000"
        assert asyncio.run(_finance_counts()) == before
    finally:
        asyncio.run(d2._cleanup(prefix))


def test_authenticated_mixed_currency_endpoints_keep_primary_and_presentation_authorities() -> None:
    prefix = "r10e1-mixed-http"

    async def seed() -> tuple[str, str, tuple[int, ...]]:
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
        await d2._daily_baseline(user_id)
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
        return user_id, rate_id, await _finance_counts()

    user_id, rate_id, before = asyncio.run(seed())
    observed_idle: list[bool] = []
    try:
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
        # The authenticated composition is fixed and the finance is exact, but
        # this exposes the next release blocker: composed current MONEY keeps
        # its Decimal exponent instead of the public six-decimal representation.
        assert portfolio_json["summary"]["liabilitiesValue"] == "1800.00000000000000"
        assert portfolio_json["summary"]["totalValue"] == "-1800.00000000000000"
        assert PUBLIC_MONEY.fullmatch(portfolio_json["summary"]["liabilitiesValue"]) is None
        account = portfolio_json["accounts"][0]
        assert account["currency"] == "EUR"
        assert account["summary"]["liabilitiesValue"] == "75.000000"
        assert account["summary"]["totalValue"] == "-75.000000"
        card = dashboard_json["accounts"][0]
        assert card["accountCurrency"] == card["outputCurrency"] == "EUR"
        assert card["liabilitiesValue"] == "75.000000"
        assert dashboard_json["summary"]["liabilitiesValue"] == "1800.00000000000000"
        assert asyncio.run(_finance_counts()) == before
    finally:
        asyncio.run(d2._cleanup(prefix))


def test_authenticated_current_failure_contracts_remain_distinct() -> None:
    prefix = "r10e1-current-failures"
    user_id, _ = asyncio.run(d2._seed_cash(prefix))
    try:
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
        asyncio.run(d2._cleanup(prefix))
