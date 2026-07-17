from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.url import normalize_database_url
from scripts.database_migrate import DEFAULT_ADVISORY_LOCK_KEY

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("DATABASE_URL")


def run_script(*arguments: str) -> subprocess.CompletedProcess[str]:
    assert DATABASE_URL is not None
    environment = os.environ.copy()
    environment["DATABASE_URL"] = DATABASE_URL
    return subprocess.run(
        [sys.executable, "scripts/database_migrate.py", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
def test_prepared_migration_runner_checks_and_upgrades_baseline() -> None:
    check = run_script("check")
    assert check.returncode == 0, check.stdout + check.stderr

    upgrade = run_script("upgrade")
    assert upgrade.returncode == 0, upgrade.stdout + upgrade.stderr


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_prepared_migration_runner_refuses_concurrent_upgrade() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    try:
        async with engine.connect() as connection:
            locked = await connection.scalar(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": DEFAULT_ADVISORY_LOCK_KEY},
            )
            assert locked is True
            try:
                result = run_script("upgrade")
            finally:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": DEFAULT_ADVISORY_LOCK_KEY},
                )
    finally:
        await engine.dispose()

    assert result.returncode == 1
    assert "advisory lock is already held" in result.stderr
