"""PostgreSQL evidence for implemented version 0.1 backend boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import os
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.imports import ImportBatchModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app

DATABASE_URL = os.getenv("DATABASE_URL")
PREFIX = "version-0-1-acceptance"
USER_ID = f"{PREFIX}-user"
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        log_level="ERROR",
        log_json=False,
        internal_auth_secret="version-0-1-integration-secret-32-characters",
        _env_file=None,
    )


async def _seed_user() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        account_ids = select(AccountModel.id).where(AccountModel.name.startswith(PREFIX))
        await session.execute(
            delete(ImportBatchModel).where(ImportBatchModel.account_id.in_(account_ids))
        )
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
        )
        await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        await session.execute(delete(UserModel).where(UserModel.id == USER_ID))
        now = datetime.now(UTC).replace(tzinfo=None)
        session.add(
            UserModel(
                id=USER_ID,
                email=f"{USER_ID}@example.test",
                name="Version 0.1 acceptance",
                password_hash=None,
                base_currency="EUR",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    await engine.dispose()


async def _persisted_counts() -> tuple[int, int, int]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        accounts = await session.scalar(
            select(func.count())
            .select_from(AccountModel)
            .where(AccountModel.name.startswith(PREFIX))
        )
        memberships = await session.scalar(
            select(func.count())
            .select_from(AccountMemberModel)
            .where(AccountMemberModel.user_id == USER_ID)
        )
        batches = await session.scalar(
            select(func.count())
            .select_from(ImportBatchModel)
            .where(ImportBatchModel.user_id == USER_ID)
        )
    await engine.dispose()
    return int(accounts or 0), int(memberships or 0), int(batches or 0)


def test_real_postgresql_version_and_migration_state() -> None:
    assert DATABASE_URL is not None

    async def inspect_database() -> tuple[str, str, str]:
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            version = str(await session.scalar(text("SELECT version()")))
            database = str(await session.scalar(text("SELECT current_database()")))
            migration = str(await session.scalar(text("SELECT version_num FROM alembic_version")))
        await engine.dispose()
        return version, database, migration

    version, database, migration = _run(inspect_database())
    assert version.startswith("PostgreSQL 16.")
    assert database == "finance_app_version_0_1_acceptance"
    assert migration == "3g0001liabbal"


def test_python_accounts_and_import_batch_registration_use_persisted_membership() -> None:
    _run(_seed_user())
    app = create_app(_settings())
    app.dependency_overrides[get_current_principal] = lambda: AuthenticatedPrincipal(
        user_id=USER_ID,
        email=f"{USER_ID}@example.test",
        name="Version 0.1 acceptance",
    )

    with TestClient(app) as client:
        created_accounts: dict[str, str] = {}
        for suffix, account_type, currency in (
            ("broker", "broker", "EUR"),
            ("bank", "bank", "CZK"),
            ("loan", "loan", "USD"),
        ):
            response = client.post(
                "/api/v1/accounts",
                json={
                    "name": f"{PREFIX}-{suffix}",
                    "type": account_type,
                    "currency": currency,
                },
            )
            assert response.status_code == 201
            assert response.json()["role"] == "owner"
            assert response.json()["currency"] == currency
            created_accounts[suffix] = response.json()["id"]

        for source, suffix in (
            ("trading212", "broker"),
            ("anycoin", "broker"),
            ("raiffeisenbank", "bank"),
        ):
            content = f"{source}-acceptance-placeholder".encode()
            response = client.post(
                f"/api/v1/accounts/{created_accounts[suffix]}/imports",
                json={
                    "source": source,
                    "filename": f"{source}.csv",
                    "file_size": len(content),
                    "file_encoding": "utf-8",
                    "checksum": hashlib.sha256(content).hexdigest(),
                },
            )
            assert response.status_code == 201
            assert response.json()["source"] == source
            assert response.json()["status"] == "pending"

    assert _run(_persisted_counts()) == (3, 3, 3)


def test_account_and_import_authorization_do_not_accept_caller_subject_override() -> None:
    _run(_seed_user())
    app = create_app(_settings())
    app.dependency_overrides[get_current_principal] = lambda: AuthenticatedPrincipal(
        user_id=USER_ID,
        email=f"{USER_ID}@example.test",
        name=None,
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/accounts?user_id=foreign-user")

    assert response.status_code == 200
    assert all(account["role"] == "owner" for account in response.json())
