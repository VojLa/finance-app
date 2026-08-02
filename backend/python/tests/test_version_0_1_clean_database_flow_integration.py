"""Clean-database acceptance probe for the incomplete version 0.1 main flow."""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Coroutine
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.holdings import HoldingModel
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app

DATABASE_URL = os.getenv("DATABASE_URL")
EXPECTED_DATABASE = "finance_app_version_0_1_acceptance"
USER_ID = "version-0-1-clean-user"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


async def _truncate_dedicated_database() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        database = await session.scalar(text("SELECT current_database()"))
        assert database == EXPECTED_DATABASE
        tables = (
            await session.execute(
                text(
                    """
                    SELECT tablename
                    FROM pg_tables
                    WHERE schemaname = 'public'
                      AND tablename <> 'alembic_version'
                    ORDER BY tablename
                    """
                )
            )
        ).scalars()
        quoted = ", ".join(f'"public"."{table.replace(chr(34), chr(34) * 2)}"' for table in tables)
        assert quoted
        await session.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
        await session.commit()
    await engine.dispose()


async def _core_counts() -> dict[str, int]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    models = {
        "users": UserModel,
        "accounts": AccountModel,
        "memberships": AccountMemberModel,
        "batches": ImportBatchModel,
        "rows": ImportRowModel,
        "transactions": TransactionModel,
        "events": InvestmentEventModel,
        "holdings": HoldingModel,
        "account_snapshots": AccountSnapshotModel,
        "net_worth_snapshots": NetWorthSnapshotModel,
    }
    async with AsyncSession(engine) as session:
        counts = {
            name: int(await session.scalar(select(func.count()).select_from(model)) or 0)
            for name, model in models.items()
        }
    await engine.dispose()
    return counts


async def _seed_user() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        session.add(
            UserModel(
                id=USER_ID,
                email=f"{USER_ID}@example.test",
                name="Clean database user",
                password_hash=None,
                base_currency="EUR",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    await engine.dispose()


def test_clean_database_probe_reaches_python_accounts_and_registered_imports_only() -> None:
    _run(_truncate_dedicated_database())
    assert _run(_core_counts()) == {
        "users": 0,
        "accounts": 0,
        "memberships": 0,
        "batches": 0,
        "rows": 0,
        "transactions": 0,
        "events": 0,
        "holdings": 0,
        "account_snapshots": 0,
        "net_worth_snapshots": 0,
    }
    _run(_seed_user())

    app = create_app(
        Settings(
            environment="test",
            database_url=DATABASE_URL,
            docs_enabled=True,
            log_level="ERROR",
            log_json=False,
            internal_auth_secret="version-0-1-clean-database-secret-32-characters",
            _env_file=None,
        )
    )
    app.dependency_overrides[get_current_principal] = lambda: AuthenticatedPrincipal(
        user_id=USER_ID,
        email=f"{USER_ID}@example.test",
        name=None,
    )

    with TestClient(app) as client:
        accounts: dict[str, str] = {}
        for source, account_type, currency in (
            ("trading212", "broker", "EUR"),
            ("anycoin", "exchange", "EUR"),
            ("raiffeisenbank", "bank", "CZK"),
        ):
            account = client.post(
                "/api/v1/accounts",
                json={
                    "name": f"clean-{source}",
                    "type": account_type,
                    "currency": currency,
                },
            )
            assert account.status_code == 201
            accounts[source] = account.json()["id"]
            placeholder = f"no-real-python-fixture-{source}".encode()
            batch = client.post(
                f"/api/v1/accounts/{accounts[source]}/imports",
                json={
                    "source": source,
                    "filename": f"{source}.csv",
                    "file_size": len(placeholder),
                    "file_encoding": "utf-8",
                    "checksum": hashlib.sha256(placeholder).hexdigest(),
                },
            )
            assert batch.status_code == 201

    counts = _run(_core_counts())
    assert counts == {
        "users": 1,
        "accounts": 3,
        "memberships": 3,
        "batches": 3,
        "rows": 0,
        "transactions": 0,
        "events": 0,
        "holdings": 0,
        "account_snapshots": 0,
        "net_worth_snapshots": 0,
    }

    # This passing probe records the exact NOT READY boundary. The clean
    # database can reach Python account and batch registration, but the browser
    # still invokes TypeScript account/import business routes and the Python
    # source registry has no real-export fixtures for an upload-to-read-model
    # acceptance run.
    account_route = (REPOSITORY_ROOT / "src/app/api/accounts/route.ts").read_text(encoding="utf-8")
    import_route = (REPOSITORY_ROOT / "src/app/api/import/raiffeisenbank/route.ts").read_text(
        encoding="utf-8"
    )
    supported_sources = (REPOSITORY_ROOT / "!docs/02-imports/03-supported-sources.md").read_text(
        encoding="utf-8"
    )
    assert 'from "@/lib/prisma"' in account_route
    assert "importCsvFilesAsync" in import_route
    assert "broker- or bank-specific CSV mappings" in supported_sources
