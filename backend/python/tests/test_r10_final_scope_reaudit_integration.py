"""Executable release-blocker evidence for the R10 final scope re-audit."""

from __future__ import annotations

import asyncio
import importlib
import os
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.main import create_app
from app.modules.current_value.api import get_current_value_clock

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")

d2 = cast(Any, importlib.import_module("tests.test_r10d2_current_value_integration"))
investment_support = cast(
    Any,
    importlib.import_module("tests.support.investment_fixture_e2e"),
)


async def _snapshot_counts() -> tuple[int, int]:
    engine = d2._engine()
    async with AsyncSession(engine) as session:
        result = (
            int(await session.scalar(select(func.count()).select_from(AccountSnapshotModel)) or 0),
            int(await session.scalar(select(func.count()).select_from(NetWorthSnapshotModel)) or 0),
        )
    await engine.dispose()
    return result


def test_authenticated_current_endpoints_are_blocked_by_principal_session_transaction() -> None:
    """Prove that valid D1/D2 evidence is unavailable through the active HTTP boundary."""

    prefix = "r10-final-current-http"

    async def seed() -> tuple[str, tuple[int, int]]:
        user_id, account_id = await d2._seed_cash(prefix)
        await d2._transaction(
            account_id,
            transaction_id=f"{prefix}-baseline",
            date=d2.BASELINE_AT - timedelta(days=1),
            amount="100.000000",
        )
        await d2._daily_baseline(user_id)

        # The same production service succeeds while it owns an idle session.
        direct = await d2._current(user_id)
        assert direct.portfolio.summary.cash_value == Decimal("100.000000")
        return user_id, await _snapshot_counts()

    user_id, before = asyncio.run(seed())
    try:
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

        with TestClient(app) as client:
            responses = (
                client.post(
                    "/api/v1/portfolio/current",
                    headers=investment_support.headers(user_id),
                ),
                client.post(
                    "/api/v1/dashboard/current",
                    headers=investment_support.headers(user_id),
                ),
            )

        for response in responses:
            assert response.status_code == 409
            payload = response.json()
            assert payload["error"]["code"] == "current_value_unavailable"
            assert payload["error"]["message"] == (
                "Current portfolio value cannot be produced from the available evidence."
            )
            assert isinstance(payload["error"]["request_id"], str)

        assert asyncio.run(_snapshot_counts()) == before
    finally:
        asyncio.run(d2._cleanup(prefix))
