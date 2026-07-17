from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import UserModel
from app.db.url import normalize_database_url
from scripts.alembic_baseline import BASELINE_REVISION

DATABASE_URL = os.getenv("DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
TEST_USER_ID = "alembic-baseline-preservation-user"


def run_command(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    assert DATABASE_URL is not None
    environment["DATABASE_URL"] = DATABASE_URL
    result = subprocess.run(
        [sys.executable, *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_alembic_baseline_stamp_preserves_schema_and_data() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime(2026, 7, 17, 12, 0, 0)

    try:
        async with engine.begin() as connection:
            await connection.execute(delete(UserModel).where(UserModel.id == TEST_USER_ID))
            await connection.execute(
                insert(UserModel).values(
                    id=TEST_USER_ID,
                    email="alembic-baseline@example.test",
                    name="Alembic Baseline",
                    password_hash=None,
                    base_currency="CZK",
                    created_at=now,
                    updated_at=now,
                )
            )

        verification = run_command("scripts/alembic_baseline.py", "--verify")
        assert "safe to stamp" in verification.stdout

        run_command(
            "-m",
            "alembic",
            "-c",
            str(ALEMBIC_CONFIG),
            "stamp",
            BASELINE_REVISION,
        )
        run_command(
            "-m",
            "alembic",
            "-c",
            str(ALEMBIC_CONFIG),
            "current",
            "--check-heads",
        )
        check = run_command("-m", "alembic", "-c", str(ALEMBIC_CONFIG), "check")
        assert "No new upgrade operations detected" in check.stdout + check.stderr
        run_command("-m", "alembic", "-c", str(ALEMBIC_CONFIG), "upgrade", "head")

        async with engine.connect() as connection:
            preserved_user = await connection.scalar(
                select(UserModel.email).where(UserModel.id == TEST_USER_ID)
            )
            version = await connection.scalar(
                text('SELECT "version_num" FROM public.alembic_version')
            )
            application_tables = await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' "
                    "AND table_type = 'BASE TABLE' "
                    "AND table_name NOT IN ('_prisma_migrations', 'alembic_version')"
                )
            )

        assert preserved_user == "alembic-baseline@example.test"
        assert version == BASELINE_REVISION
        assert application_tables == 30
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(UserModel).where(UserModel.id == TEST_USER_ID))
        await engine.dispose()
