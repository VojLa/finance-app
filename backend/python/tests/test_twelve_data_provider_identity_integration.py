from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, async_sessionmaker, create_async_engine

from app.db.models import (
    AssetAliasModel,
    AssetAliasProvider,
    AssetListingModel,
    AssetModel,
    AssetType,
    PriceSnapshotModel,
    PriceSource,
)
from app.db.url import normalize_database_url

DATABASE_URL = os.getenv("DATABASE_URL")
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
PRISMA_SCHEMA = REPOSITORY_ROOT / "prisma" / "schema.prisma"
PREVIOUS_SCHEMA = BACKEND_ROOT / "database" / "revisions" / "3g0001liabbal" / "schema.sql"
ASSET_ID = "twelve-data-identity-asset"
LISTING_ID = "twelve-data-identity-listing"
ALIAS_ID = "twelve-data-identity-alias"
PRICE_ID = "twelve-data-identity-price"
NOW = datetime(2026, 8, 5, 12, 0, 0)


def _prisma_enum_values(name: str) -> tuple[str, ...]:
    source = PRISMA_SCHEMA.read_text(encoding="utf-8")
    match = re.search(rf"enum {re.escape(name)} \{{(?P<body>.*?)\n\}}", source, re.DOTALL)
    assert match is not None
    return tuple(line.strip() for line in match.group("body").splitlines() if line.strip())


async def _postgres_enum_values(connection: AsyncConnection, name: str) -> tuple[str, ...]:
    result = await connection.execute(
        text(
            "SELECT enum_value.enumlabel "
            "FROM pg_type AS enum_type "
            "JOIN pg_namespace AS namespace ON namespace.oid = enum_type.typnamespace "
            "JOIN pg_enum AS enum_value ON enum_value.enumtypid = enum_type.oid "
            "WHERE namespace.nspname = 'public' AND enum_type.typname = :name "
            "ORDER BY enum_value.enumsortorder"
        ),
        {"name": name},
    )
    return tuple(result.scalars())


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_clean_previous_head_database_upgrades_to_twelve_data_head() -> None:
    assert DATABASE_URL is not None
    source_url = make_url(normalize_database_url(DATABASE_URL))
    admin_url = source_url.set(database="postgres")
    database_name = f"finance_app_r5b2b0_{uuid4().hex}"
    target_url = source_url.set(database=database_name)
    admin_dsn = admin_url.set(drivername="postgresql").render_as_string(hide_password=False)
    target_dsn = target_url.set(drivername="postgresql").render_as_string(hide_password=False)
    target_database_url = target_url.render_as_string(hide_password=False)
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
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)"
                ")"
            )
            await target.execute(
                "INSERT INTO public.alembic_version (version_num) VALUES ('3g0001liabbal')"
            )
        finally:
            await target.close()

        environment = os.environ.copy()
        environment["DATABASE_URL"] = target_database_url
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(BACKEND_ROOT / "alembic.ini"),
                "upgrade",
                "head",
            ],
            cwd=BACKEND_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

        target = await asyncpg.connect(target_dsn)
        try:
            version = await target.fetchval("SELECT version_num FROM public.alembic_version")
            alias_values = tuple(
                await target.fetch(
                    "SELECT enum_value.enumlabel "
                    "FROM pg_type AS enum_type "
                    "JOIN pg_namespace AS namespace "
                    "ON namespace.oid = enum_type.typnamespace "
                    "JOIN pg_enum AS enum_value "
                    "ON enum_value.enumtypid = enum_type.oid "
                    "WHERE namespace.nspname = 'public' "
                    "AND enum_type.typname = 'AssetAliasProvider' "
                    "ORDER BY enum_value.enumsortorder"
                )
            )
            price_values = tuple(
                await target.fetch(
                    "SELECT enum_value.enumlabel "
                    "FROM pg_type AS enum_type "
                    "JOIN pg_namespace AS namespace "
                    "ON namespace.oid = enum_type.typnamespace "
                    "JOIN pg_enum AS enum_value "
                    "ON enum_value.enumtypid = enum_type.oid "
                    "WHERE namespace.nspname = 'public' "
                    "AND enum_type.typname = 'PriceSource' "
                    "ORDER BY enum_value.enumsortorder"
                )
            )
            assert version == "3h0001twdata"
            assert tuple(row["enumlabel"] for row in alias_values) == tuple(
                item.value for item in AssetAliasProvider
            )
            assert tuple(row["enumlabel"] for row in price_values) == tuple(
                item.value for item in PriceSource
            )
        finally:
            await target.close()
    finally:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin.close()


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_twelve_data_enum_migration_and_sqlalchemy_round_trip() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with engine.connect() as connection:
            version = str(await connection.scalar(text("SHOW server_version")))
            assert version.startswith("16.")
            migration = await connection.scalar(
                text('SELECT "version_num" FROM public.alembic_version')
            )
            assert migration == "3h0001twdata"

            postgres_alias_values = await _postgres_enum_values(connection, "AssetAliasProvider")
            postgres_price_values = await _postgres_enum_values(connection, "PriceSource")

        assert postgres_alias_values == tuple(item.value for item in AssetAliasProvider)
        assert postgres_price_values == tuple(item.value for item in PriceSource)
        assert postgres_alias_values == _prisma_enum_values("AssetAliasProvider")
        assert postgres_price_values == _prisma_enum_values("PriceSource")

        async with sessions.begin() as session:
            await session.execute(delete(AssetModel).where(AssetModel.id == ASSET_ID))
            asset = AssetModel(
                id=ASSET_ID,
                symbol="TST",
                isin=None,
                name="Twelve Data identity test",
                asset_type=AssetType.stock,
                currency="USD",
                created_at=NOW,
                updated_at=NOW,
            )
            session.add(asset)
            await session.flush()
            session.add(
                AssetListingModel(
                    id=LISTING_ID,
                    asset_id=ASSET_ID,
                    symbol="TST",
                    exchange="TEST",
                    mic="XTST",
                    currency="USD",
                    country=None,
                    provider=PriceSource.twelve_data,
                    provider_symbol="opaque-listing-identity",
                    is_primary=True,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.add(
                AssetAliasModel(
                    id=ALIAS_ID,
                    asset_id=ASSET_ID,
                    provider=AssetAliasProvider.twelve_data,
                    external_id="opaque-exact-identity",
                    created_at=NOW,
                )
            )
            await session.flush()
            session.add(
                PriceSnapshotModel(
                    id=PRICE_ID,
                    asset_id=ASSET_ID,
                    listing_id=LISTING_ID,
                    price=Decimal("123.456789"),
                    currency="USD",
                    source=PriceSource.twelve_data,
                    timestamp=NOW,
                    created_at=NOW,
                )
            )

        async with sessions() as session:
            alias = await session.scalar(
                select(AssetAliasModel).where(AssetAliasModel.id == ALIAS_ID)
            )
            listing = await session.scalar(
                select(AssetListingModel).where(AssetListingModel.id == LISTING_ID)
            )
            price = await session.scalar(
                select(PriceSnapshotModel).where(PriceSnapshotModel.id == PRICE_ID)
            )
            assert alias is not None
            assert listing is not None
            assert price is not None
            assert alias.provider is AssetAliasProvider.twelve_data
            assert alias.external_id == "opaque-exact-identity"
            assert listing.provider is PriceSource.twelve_data
            assert price.source is PriceSource.twelve_data

        async with sessions.begin() as session:
            await session.execute(delete(AssetModel).where(AssetModel.id == ASSET_ID))
    finally:
        await engine.dispose()
