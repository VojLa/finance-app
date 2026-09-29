from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.engine import make_url

from app.db.url import normalize_database_url

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required"),
]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_SCHEMA = BACKEND_ROOT / "database" / "revisions" / "3n0001emptyhold" / "schema.sql"
NOW = datetime(2026, 8, 19, 12, 0)


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(BACKEND_ROOT / "alembic.ini"), *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


async def _seed_complete_v2_evidence(connection: asyncpg.Connection, prefix: str) -> None:
    await connection.execute(
        'INSERT INTO public."Account" '
        '(id, name, type, currency, color, "isArchived", "archivedAt", '
        '"createdAt", "updatedAt", notes) '
        "VALUES ($1, 'Legacy exchange', 'exchange', 'CZK', NULL, false, NULL, $2, $2, NULL)",
        f"{prefix}-account",
        NOW,
    )
    await connection.execute(
        'INSERT INTO public."Asset" '
        '(id, symbol, isin, name, "assetType", currency, "createdAt", "updatedAt") '
        "VALUES ($1, 'BTC', NULL, 'Bitcoin', 'crypto', 'CZK', $2, $2)",
        f"{prefix}-asset",
        NOW,
    )
    await connection.execute(
        'INSERT INTO public."AssetListing" '
        '(id, "assetId", symbol, exchange, mic, currency, country, provider, '
        '"providerSymbol", "isPrimary", "createdAt", "updatedAt") '
        "VALUES ($1, $2, 'BTC', 'anycoin', NULL, 'CZK', NULL, NULL, NULL, true, $3, $3)",
        f"{prefix}-listing",
        f"{prefix}-asset",
        NOW,
    )
    await connection.execute(
        'INSERT INTO public."Holding" '
        '(id, symbol, name, "assetType", quantity, "avgBuyPrice", currency, '
        '"assetId", "listingId", "accountId", "calculatedAt", "updatedAt", '
        '"costBasisByCurrency") '
        "VALUES ($1, 'BTC', 'Bitcoin', 'crypto', 2, 100, 'CZK', $2, $3, $4, $5, $5, "
        '\'{"CZK": "200.0000000000"}\'::jsonb)',
        f"{prefix}-holding",
        f"{prefix}-asset",
        f"{prefix}-listing",
        f"{prefix}-account",
        NOW,
    )
    await connection.execute(
        'INSERT INTO public."AccountSnapshot" '
        '(id, "accountId", timestamp, granularity, source, currency, "cashValue", '
        '"investmentValue", "investmentCostBasis", "liabilitiesValue", "totalValue", '
        '"isRecalculated", "calculatedAt", "calculationVersion", "createdAt", '
        '"netDepositsValue", "realizedPnlValue", "unrealizedPnlValue", "feesValue", '
        '"taxesValue", "investmentCostBasisByCurrency") '
        "VALUES ($1, $2, $3, 'minute', 'manual_recalculation', 'CZK', 0, 240, 200, 0, 240, "
        "true, $3, 2, $3, 200, 0, 40, 0, 0, "
        '\'{"CZK": "200.0000000000"}\'::jsonb)',
        f"{prefix}-snapshot-complete",
        f"{prefix}-account",
        NOW,
    )
    await connection.execute(
        'INSERT INTO public."AccountSnapshotItem" '
        '(id, "snapshotId", "assetId", "listingId", symbol, quantity, "pricePerUnit", '
        '"priceCurrency", "priceSource", "priceTimestamp", value, "costBasis", '
        '"costCurrency", "allocationPct", "createdAt", "nativeValue", "valueCurrency", '
        '"nativeCostBasis", "nativeCostCurrency", "nativeCostBasisByCurrency", '
        '"averageBuyPrice", "averageBuyPriceCurrency") '
        "VALUES ($1, $2, $3, $4, 'BTC', 2, 120, 'CZK', 'coingecko', $5, 240, 200, "
        "'CZK', 100, $5, 240, 'CZK', 200, 'CZK', "
        "'{\"CZK\": \"200.0000000000\"}'::jsonb, 100, 'CZK')",
        f"{prefix}-item-complete",
        f"{prefix}-snapshot-complete",
        f"{prefix}-asset",
        f"{prefix}-listing",
        NOW,
    )


@pytest.mark.asyncio
async def test_3o_upgrade_preserves_complete_v2_and_guards_unknown_evidence_downgrade() -> None:
    assert DATABASE_URL is not None
    source_url = make_url(normalize_database_url(DATABASE_URL))
    database_name = f"finance_app_3o_unknown_basis_{uuid4().hex}"
    admin_url = source_url.set(drivername="postgresql", database="postgres")
    target_url = source_url.set(database=database_name)
    admin_dsn = admin_url.render_as_string(hide_password=False)
    target_dsn = target_url.set(drivername="postgresql").render_as_string(hide_password=False)
    target_database_url = target_url.render_as_string(hide_password=False)
    prefix = f"unknown-basis-{uuid4().hex}"
    admin = await asyncpg.connect(admin_dsn)
    try:
        await admin.execute(f'CREATE DATABASE "{database_name}"')
        target = await asyncpg.connect(target_dsn)
        try:
            previous_schema = PREVIOUS_SCHEMA.read_text(encoding="utf-8").replace(
                'CREATE SCHEMA "public";\n', "", 1
            )
            await target.execute(previous_schema)
            await target.execute(
                "CREATE TABLE public.alembic_version ("
                "version_num varchar(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
            await target.execute(
                "INSERT INTO public.alembic_version (version_num) VALUES ('3n0001emptyhold')"
            )
            await _seed_complete_v2_evidence(target, prefix)
        finally:
            await target.close()

        upgraded = _run_alembic(target_database_url, "upgrade", "3o0001unkbasis")
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr

        target = await asyncpg.connect(target_dsn)
        try:
            assert await target.fetchval("SELECT version_num FROM public.alembic_version") == (
                "3o0001unkbasis"
            )
            complete = await target.fetchrow(
                'SELECT "avgBuyPrice", "costBasisByCurrency" FROM public."Holding" WHERE id = $1',
                f"{prefix}-holding",
            )
            assert complete is not None
            assert complete["avgBuyPrice"] == Decimal("100.0000000000")
            assert json.loads(complete["costBasisByCurrency"]) == {"CZK": "200.0000000000"}
            assert (
                await target.fetchval(
                    'SELECT "calculationVersion" FROM public."AccountSnapshot" WHERE id = $1',
                    f"{prefix}-snapshot-complete",
                )
                == 2
            )

            await target.execute(
                'UPDATE public."Holding" SET "avgBuyPrice" = NULL, '
                '"costBasisByCurrency" = NULL WHERE id = $1',
                f"{prefix}-holding",
            )
            with pytest.raises(asyncpg.CheckViolationError):
                await target.execute(
                    'UPDATE public."Holding" SET "avgBuyPrice" = 1 WHERE id = $1',
                    f"{prefix}-holding",
                )
        finally:
            await target.close()

        downgrade = _run_alembic(target_database_url, "downgrade", "3n0001emptyhold")
        assert downgrade.returncode != 0
        assert (
            "Cannot remove unknown investment cost-basis support while incomplete evidence exists."
            in downgrade.stdout + downgrade.stderr
        )
    finally:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin.close()
