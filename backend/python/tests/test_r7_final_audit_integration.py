from __future__ import annotations

import ast
import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.common import MONEY, TIMESTAMP
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.db.models.snapshots import NetWorthSnapshotModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.portfolio_history.api import get_portfolio_history_clock
from app.modules.portfolio_history.models import PortfolioHistoryRange
from app.modules.portfolio_history.service import (
    ReadPortfolioHistoryCommand,
    SnapshotBackedPortfolioHistoryService,
)

ROOT = Path(__file__).parents[1]
MODULE_DIR = ROOT / "app" / "modules" / "portfolio_history"
DATABASE_URL = os.getenv("DATABASE_URL")
END = datetime(2026, 8, 1, 12, 0, 0, 123000)
SECRET = "r7-final-audit-secret-with-32-characters"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }


def test_r7_python_source_inventory_is_read_only_and_checkout_portable() -> None:
    forbidden_imports = {
        "account_snapshot",
        "fx",
        "holdings",
        "imports",
        "investment",
        "market_data",
        "prices",
        "provider",
        "snapshot_refresh",
        "transactions",
    }
    forbidden_operations = (
        "create_task",
        "background",
        "httpx",
        "requests",
        "for update",
        "advisory",
        "insert(",
        "update(",
        "delete(",
    )
    module_paths = tuple(sorted(MODULE_DIR.glob("*.py")))
    assert tuple(path.name for path in module_paths) == (
        "__init__.py",
        "api.py",
        "api_models.py",
        "models.py",
        "repository.py",
        "selection.py",
        "service.py",
    )

    for path in module_paths:
        modules = _imports(path)
        assert not any(fragment in module for fragment in forbidden_imports for module in modules)
        lowered = path.read_text(encoding="utf-8").lower()
        for operation in forbidden_operations:
            assert operation not in lowered

    repository = (MODULE_DIR / "repository.py").read_text(encoding="utf-8")
    repository_imports = _imports(MODULE_DIR / "repository.py")
    model_imports = {module for module in repository_imports if module.startswith("app.db.models.")}
    assert model_imports == {
        "app.db.models.snapshots",
        "app.db.models.users",
    }
    assert repository.count("select(") == 2
    assert "UserModel.id == user_id" in repository
    assert "NetWorthSnapshotModel.user_id == user_id" in repository
    assert "NetWorthSnapshotModel.currency == currency" in repository

    service = (MODULE_DIR / "service.py").read_text(encoding="utf-8")
    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY" in service
    assert "self.clock()" in service
    assert service.count("self.clock()") == 1


def test_r7_model_and_openapi_contract_are_exact() -> None:
    assert MONEY.precision == 18
    assert MONEY.scale == 6
    assert TIMESTAMP.precision == 3
    assert tuple(item.value for item in PortfolioHistoryRange) == (
        "1W",
        "1M",
        "3M",
        "6M",
        "1Y",
        "ALL",
    )

    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://audit:audit@127.0.0.1:1/audit",
        log_level="ERROR",
        log_json=False,
        docs_enabled=True,
        internal_auth_secret=SECRET,
        _env_file=None,
    )
    schema = create_app(settings).openapi()
    operation = schema["paths"]["/api/v1/portfolio/history"]["get"]
    assert operation["security"] == [{"InternalSessionToken": []}]
    assert operation["parameters"] == [
        {
            "name": "range",
            "in": "query",
            "required": False,
            "schema": {
                "$ref": "#/components/schemas/PortfolioHistoryRange",
                "default": "1Y",
            },
        }
    ]
    components = schema["components"]["schemas"]
    assert components["PortfolioHistoryRange"]["enum"] == [
        "1W",
        "1M",
        "3M",
        "6M",
        "1Y",
        "ALL",
    ]
    point = components["PortfolioHistoryPointResponse"]
    assert point["required"] == [
        "timestamp",
        "cashValue",
        "investmentValue",
        "liabilitiesValue",
        "netWorthValue",
    ]
    assert point["additionalProperties"] is False
    assert all(
        point["properties"][field]["type"] == "string"
        for field in (
            "cashValue",
            "investmentValue",
            "liabilitiesValue",
            "netWorthValue",
        )
    )
    response = components["PortfolioHistoryResponse"]
    assert response["required"] == ["range", "currency", "points"]
    assert response["additionalProperties"] is False


def _encode(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _token(user_id: str) -> str:
    now = int(time.time())
    header = _encode({"alg": "HS256", "typ": "JWT"})
    payload = _encode(
        {
            "sub": user_id,
            "email": f"{user_id}@example.test",
            "iss": "finance-app-next",
            "aud": "finance-app-python",
            "iat": now,
            "exp": now + 300,
        }
    )
    signature = hmac.new(
        SECRET.encode(),
        f"{header}.{payload}".encode(),
        hashlib.sha256,
    ).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _snapshot(
    user_id: str,
    suffix: str,
    timestamp: datetime,
    *,
    granularity: SnapshotGranularity = SnapshotGranularity.day,
    currency: str = "EUR",
    cash: str = "10.000000",
    portfolio: str = "100.000000",
    liabilities: str = "20.000000",
    total: str = "90.000000",
) -> NetWorthSnapshotModel:
    return NetWorthSnapshotModel(
        id=f"{user_id}-{suffix}",
        user_id=user_id,
        timestamp=timestamp,
        granularity=granularity,
        source=SnapshotSource.scheduled,
        currency=currency,
        cash_value=Decimal(cash),
        portfolio_value=Decimal(portfolio),
        liabilities_value=Decimal(liabilities),
        total_net_worth=Decimal(total),
        is_recalculated=False,
        calculated_at=timestamp,
        calculation_version=1,
        created_at=timestamp,
        cash_value_by_currency=None,
        portfolio_value_by_currency=None,
        liabilities_value_by_currency=None,
        total_net_worth_by_currency=None,
        exchange_rates=None,
    )


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
    users = {
        "a": f"{prefix}-a",
        "b": f"{prefix}-b",
        "empty": f"{prefix}-empty",
        "corrupt": f"{prefix}-corrupt",
    }
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
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
        duplicate_at = END - timedelta(days=2)
        session.add_all(
            (
                _snapshot(users["a"], "outside", END - timedelta(days=400)),
                _snapshot(
                    users["a"],
                    "inside-negative",
                    END - timedelta(days=10),
                    cash="-200.000000",
                    portfolio="100.000000",
                    liabilities="50.000000",
                    total="-150.000000",
                ),
                _snapshot(users["a"], "duplicate-day", duplicate_at),
                _snapshot(
                    users["a"],
                    "duplicate-minute",
                    duplicate_at,
                    granularity=SnapshotGranularity.minute,
                ),
                _snapshot(users["a"], "latest", END),
                _snapshot(users["a"], "future", END + timedelta(milliseconds=1)),
                _snapshot(
                    users["a"],
                    "wrong-currency",
                    END - timedelta(days=1),
                    currency="CZK",
                ),
                _snapshot(
                    users["b"],
                    "foreign",
                    duplicate_at,
                    cash="1.000000",
                    portfolio="2.000000",
                    liabilities="0.000000",
                    total="3.000000",
                ),
                _snapshot(users["corrupt"], "bad-formula", END, total="91.000000"),
            )
        )
        await session.commit()
    await engine.dispose()
    return users


async def _physical_service_proof(users: dict[str, str]) -> tuple[int, int]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine, expire_on_commit=False) as session:
        version = await session.scalar(text("SHOW server_version"))
        assert isinstance(version, str) and version.startswith("16.")
        await session.rollback()
        before = await session.scalar(select(func.count()).select_from(NetWorthSnapshotModel))
        await session.rollback()
        service = SnapshotBackedPortfolioHistoryService(session, clock=lambda: END)
        result = await service.read(
            ReadPortfolioHistoryCommand(
                principal=AuthenticatedPrincipal(
                    user_id=users["a"],
                    email=f"{users['a']}@example.test",
                    name="A",
                ),
                range=PortfolioHistoryRange.one_year,
            )
        )
        assert not session.in_transaction()
        assert result.selected_snapshot_ids == (
            f"{users['a']}-inside-negative",
            f"{users['a']}-duplicate-minute",
            f"{users['a']}-latest",
        )
        after = await session.scalar(select(func.count()).select_from(NetWorthSnapshotModel))
        await session.rollback()
    await engine.dispose()
    assert before is not None and after is not None
    return before, after


def test_r7_postgresql_physical_to_api_when_configured() -> None:
    if DATABASE_URL is None:
        for name in (
            "test_portfolio_history_integration.py",
            "test_portfolio_history_api_integration.py",
        ):
            source = (Path(__file__).parent / name).read_text(encoding="utf-8")
            assert "SHOW server_version" in source
            assert "pytest.mark.xfail" not in source
            assert "pytest.skip(" not in source
        return

    prefix = f"r7-final-{uuid4().hex}"
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

    try:
        before, after_service = asyncio.run(_physical_service_proof(users))
        assert before == after_service
        with TestClient(app) as client:
            unauthorized = client.get("/api/v1/portfolio/history?range=1Y")
            invalid = client.get(
                "/api/v1/portfolio/history?range=YEAR",
                headers={"Authorization": f"Bearer {_token(users['a'])}"},
            )
            response_a = client.get(
                "/api/v1/portfolio/history?range=1Y",
                headers={"Authorization": f"Bearer {_token(users['a'])}"},
            )
            response_b = client.get(
                "/api/v1/portfolio/history?range=1Y",
                headers={"Authorization": f"Bearer {_token(users['b'])}"},
            )
            empty = client.get(
                "/api/v1/portfolio/history?range=ALL",
                headers={"Authorization": f"Bearer {_token(users['empty'])}"},
            )
            corrupt = client.get(
                "/api/v1/portfolio/history?range=ALL",
                headers={"Authorization": f"Bearer {_token(users['corrupt'])}"},
            )

        assert unauthorized.status_code == 401
        assert invalid.status_code == 422
        assert response_a.status_code == 200
        assert response_a.json() == {
            "range": "1Y",
            "currency": "EUR",
            "points": [
                {
                    "timestamp": "2026-07-22T12:00:00.123",
                    "cashValue": "-200.000000",
                    "investmentValue": "100.000000",
                    "liabilitiesValue": "50.000000",
                    "netWorthValue": "-150.000000",
                },
                {
                    "timestamp": "2026-07-30T12:00:00.123",
                    "cashValue": "10.000000",
                    "investmentValue": "100.000000",
                    "liabilitiesValue": "20.000000",
                    "netWorthValue": "90.000000",
                },
                {
                    "timestamp": "2026-08-01T12:00:00.123",
                    "cashValue": "10.000000",
                    "investmentValue": "100.000000",
                    "liabilitiesValue": "20.000000",
                    "netWorthValue": "90.000000",
                },
            ],
        }
        assert response_b.json()["points"] == [
            {
                "timestamp": "2026-07-30T12:00:00.123",
                "cashValue": "1.000000",
                "investmentValue": "2.000000",
                "liabilitiesValue": "0.000000",
                "netWorthValue": "3.000000",
            }
        ]
        assert empty.status_code == 200
        assert empty.json() == {"range": "ALL", "currency": "EUR", "points": []}
        assert corrupt.status_code == 409
        assert corrupt.json()["error"]["code"] == "portfolio_history_unavailable"
        assert corrupt.json()["error"]["message"] == "Portfolio history is unavailable."
        serialized = response_a.text
        for forbidden in (
            "userId",
            "snapshotId",
            "accountId",
            "selectedAccountSnapshotIds",
            "provider",
            "exchangeRates",
            "request_id",
        ):
            assert forbidden not in serialized
        after_api = asyncio.run(_physical_service_proof(users))[1]
        assert after_api == before
    finally:
        asyncio.run(_cleanup(prefix))
