from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.config.settings import Settings
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.db.models.snapshots import NetWorthSnapshotModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.portfolio_history.api import get_portfolio_history_clock

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
SECRET = "r7a-history-integration-secret-32-characters"
END = datetime(2026, 8, 1, 12, 0, 0, 123000)


def _encode(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _token(user_id: str) -> str:
    now = int(time.time())
    header = _encode({"alg": "HS256", "typ": "JWT"})
    payload = _encode(
        {
            "sub": user_id,
            "iss": "finance-app-next",
            "aud": "finance-app-python",
            "iat": now,
            "exp": now + 300,
        }
    )
    signature = hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


async def _cleanup(prefix: str) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        user_ids = tuple(
            await session.scalars(select(UserModel.id).where(UserModel.id.startswith(f"{prefix}-")))
        )
        if user_ids:
            await session.execute(
                delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id.in_(user_ids))
            )
            await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        await session.commit()
    await engine.dispose()


async def _seed(prefix: str) -> dict[str, str]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    users = {
        "a": f"{prefix}-a",
        "b": f"{prefix}-b",
        "empty": f"{prefix}-empty",
        "corrupt": f"{prefix}-corrupt",
    }
    async with AsyncSession(engine) as session:
        for suffix, user_id in users.items():
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    name=suffix,
                    password_hash=None,
                    base_currency="EUR",
                    created_at=END,
                    updated_at=END,
                )
            )
        await session.flush()
        for suffix, user_id, cash, portfolio, liabilities, total in (
            ("a-point", users["a"], "-50.000000", "10000.000000", "1000.000000", "8950.000000"),
            ("b-point", users["b"], "2.000000", "3.000000", "0.000000", "5.000000"),
            ("corrupt-point", users["corrupt"], "1.000000", "1.000000", "0.000000", "9.000000"),
        ):
            session.add(
                NetWorthSnapshotModel(
                    id=f"{prefix}-{suffix}",
                    user_id=user_id,
                    timestamp=END,
                    granularity=SnapshotGranularity.minute,
                    source=SnapshotSource.scheduled,
                    currency="EUR",
                    cash_value=Decimal(cash),
                    portfolio_value=Decimal(portfolio),
                    liabilities_value=Decimal(liabilities),
                    total_net_worth=Decimal(total),
                    is_recalculated=False,
                    calculated_at=END,
                    calculation_version=1,
                    created_at=END,
                    cash_value_by_currency=None,
                    portfolio_value_by_currency=None,
                    liabilities_value_by_currency=None,
                    total_net_worth_by_currency=None,
                    exchange_rates=None,
                )
            )
        await session.commit()
    await engine.dispose()
    return users


@pytest.mark.integration
def test_real_endpoint_enforces_bearer_isolation_exact_json_and_no_writes() -> None:
    assert DATABASE_URL is not None
    prefix = f"r7a-api-{uuid4().hex}"
    asyncio.run(_cleanup(prefix))
    users = asyncio.run(_seed(prefix))
    settings = Settings(
        environment="test",
        database_url=DATABASE_URL,
        log_level="ERROR",
        log_json=False,
        docs_enabled=True,
        internal_auth_secret=SECRET,
        _env_file=None,
    )
    app = create_app(settings)
    app.dependency_overrides[get_portfolio_history_clock] = lambda: lambda: END

    async def count_rows() -> int:
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            version = await session.scalar(text("SHOW server_version"))
            assert isinstance(version, str) and version.startswith("16.")
            result = await session.scalar(select(func.count()).select_from(NetWorthSnapshotModel))
        await engine.dispose()
        assert result is not None
        return result

    try:
        before = asyncio.run(count_rows())
        with TestClient(app) as client:
            unauthorized = client.get("/api/v1/portfolio/history")
            response_a = client.get(
                "/api/v1/portfolio/history?range=1Y",
                headers=_headers(users["a"]),
            )
            response_b = client.get(
                "/api/v1/portfolio/history?range=ALL",
                headers=_headers(users["b"]),
            )
            empty = client.get(
                "/api/v1/portfolio/history",
                headers=_headers(users["empty"]),
            )
            corrupt = client.get(
                "/api/v1/portfolio/history",
                headers=_headers(users["corrupt"]),
            )

        assert unauthorized.status_code == 401
        assert response_a.status_code == 200
        assert response_a.json() == {
            "range": "1Y",
            "currency": "EUR",
            "points": [
                {
                    "timestamp": "2026-08-01T12:00:00.123",
                    "cashValue": "-50.000000",
                    "investmentValue": "10000.000000",
                    "liabilitiesValue": "1000.000000",
                    "netWorthValue": "8950.000000",
                }
            ],
        }
        assert response_b.json()["points"][0]["netWorthValue"] == "5.000000"
        assert empty.json() == {"range": "1Y", "currency": "EUR", "points": []}
        assert corrupt.status_code == 409
        assert corrupt.json()["error"]["code"] == "portfolio_history_unavailable"
        assert "snapshot" not in response_a.text.lower()
        assert "provider" not in response_a.text.lower()
        assert asyncio.run(count_rows()) == before
    finally:
        asyncio.run(_cleanup(prefix))
