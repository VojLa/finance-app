from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import AccountModel, AccountType, UserModel
from app.db.url import normalize_database_url
from scripts.alembic_baseline import BASELINE_REVISION, CUTOVER_REVISION, HEAD_REVISION

DATABASE_URL = os.getenv("DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
TEST_USER_ID = "alembic-first-migration-user"
TEST_ACCOUNT_ID = "alembic-first-migration-account"


def invoke_command(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    assert DATABASE_URL is not None
    environment["DATABASE_URL"] = DATABASE_URL
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def run_command(*arguments: str) -> subprocess.CompletedProcess[str]:
    result = invoke_command(*arguments)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_first_alembic_schema_migration_lifecycle() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime(2026, 7, 17, 12, 0, 0)

    try:
        async with engine.begin() as connection:
            await connection.execute(delete(AccountModel).where(AccountModel.id == TEST_ACCOUNT_ID))
            await connection.execute(delete(UserModel).where(UserModel.id == TEST_USER_ID))
            await connection.execute(
                insert(UserModel).values(
                    id=TEST_USER_ID,
                    email="alembic-first@example.test",
                    name="Alembic First Migration",
                    password_hash=None,
                    base_currency="CZK",
                    created_at=now,
                    updated_at=now,
                )
            )
            # The inherited database does not have Account.notes yet, so insert only legacy columns.
            await connection.execute(
                text(
                    'INSERT INTO "public"."Account" '
                    '("id", "name", "type", "currency", "color", "isArchived", '
                    '"archivedAt", "createdAt", "updatedAt") '
                    'VALUES (:id, :name, CAST(:type AS "AccountType"), :currency, NULL, false, '
                    "NULL, :created_at, :updated_at)"
                ),
                {
                    "id": TEST_ACCOUNT_ID,
                    "name": "First Alembic Account",
                    "type": AccountType.bank.value,
                    "currency": "CZK",
                    "created_at": now,
                    "updated_at": now,
                },
            )

        verification = run_command("scripts/alembic_baseline.py", "--verify")
        assert "revision state" in verification.stdout

        run_command("-m", "alembic", "-c", str(ALEMBIC_CONFIG), "stamp", BASELINE_REVISION)
        run_command("scripts/database_migrate.py", "upgrade")

        async with engine.begin() as connection:
            notes = await connection.scalar(
                text('SELECT "notes" FROM "public"."Account" WHERE "id" = :id'),
                {"id": TEST_ACCOUNT_ID},
            )
            version = await connection.scalar(
                text('SELECT "version_num" FROM public.alembic_version')
            )
            assert notes is None
            assert version == HEAD_REVISION
            await connection.execute(
                text('UPDATE "public"."Account" SET "notes" = :notes WHERE "id" = :id'),
                {"notes": "Preserve this note", "id": TEST_ACCOUNT_ID},
            )

        blocked = invoke_command(
            "-m", "alembic", "-c", str(ALEMBIC_CONFIG), "downgrade", CUTOVER_REVISION
        )
        assert blocked.returncode != 0
        assert "Cannot remove Account.notes" in blocked.stdout + blocked.stderr

        async with engine.begin() as connection:
            preserved = await connection.scalar(
                text('SELECT "notes" FROM "public"."Account" WHERE "id" = :id'),
                {"id": TEST_ACCOUNT_ID},
            )
            assert preserved == "Preserve this note"
            await connection.execute(
                text('UPDATE "public"."Account" SET "notes" = NULL WHERE "id" = :id'),
                {"id": TEST_ACCOUNT_ID},
            )

        run_command("-m", "alembic", "-c", str(ALEMBIC_CONFIG), "downgrade", CUTOVER_REVISION)
        async with engine.connect() as connection:
            column_exists = await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'Account' "
                    "AND column_name = 'notes')"
                )
            )
            assert column_exists is False

        run_command("scripts/database_migrate.py", "upgrade")
        run_command("-m", "alembic", "-c", str(ALEMBIC_CONFIG), "current", "--check-heads")
        check = run_command("-m", "alembic", "-c", str(ALEMBIC_CONFIG), "check")
        assert "No new upgrade operations detected" in check.stdout + check.stderr

        async with engine.connect() as connection:
            account_name = await connection.scalar(
                select(AccountModel.name).where(AccountModel.id == TEST_ACCOUNT_ID)
            )
            notes = await connection.scalar(
                select(AccountModel.notes).where(AccountModel.id == TEST_ACCOUNT_ID)
            )
            assert account_name == "First Alembic Account"
            assert notes is None
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(AccountModel).where(AccountModel.id == TEST_ACCOUNT_ID))
            await connection.execute(delete(UserModel).where(UserModel.id == TEST_USER_ID))
        await engine.dispose()
