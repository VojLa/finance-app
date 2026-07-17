from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.url import normalize_database_url  # noqa: E402
from scripts import database_schema, sqlalchemy_schema  # noqa: E402

ALEMBIC_CONFIG = PROJECT_ROOT / "alembic.ini"
OWNERSHIP_MANIFEST = PROJECT_ROOT / "database" / "schema_ownership.toml"
BASELINE_REVISION = "3d0001base"
EXPECTED_TABLE_COUNT = 30
EXPECTED_ENUM_COUNT = 27


@dataclass(frozen=True)
class DatabaseState:
    table_count: int
    enum_count: int
    version_revisions: tuple[str, ...]


def alembic_config() -> Config:
    return Config(str(ALEMBIC_CONFIG))


def verify_revision_graph() -> None:
    directory = ScriptDirectory.from_config(alembic_config())
    revisions = list(directory.walk_revisions())
    heads = directory.get_heads()
    bases = directory.get_bases()

    if len(revisions) != 1:
        raise RuntimeError(f"Expected exactly one Alembic revision, found {len(revisions)}.")
    if heads != [BASELINE_REVISION]:
        raise RuntimeError(f"Expected Alembic head {BASELINE_REVISION}, found {heads}.")
    if bases != [BASELINE_REVISION]:
        raise RuntimeError(f"Expected Alembic base {BASELINE_REVISION}, found {bases}.")

    revision = revisions[0]
    if revision.revision != BASELINE_REVISION or revision.down_revision is not None:
        raise RuntimeError("The Alembic baseline revision graph is invalid.")


def verify_manifest() -> None:
    manifest = tomllib.loads(OWNERSHIP_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 5:
        raise RuntimeError("Ownership manifest schema_version must be 5 for step 3E-A.")
    if manifest.get("current_migration_owner") != "prisma":
        raise RuntimeError("Prisma remains the current migration owner during step 3E-A.")
    if manifest.get("cutover_status") != "ready":
        raise RuntimeError("Migration ownership cutover must be ready but not activated in 3E-A.")

    cutover = manifest.get("cutover")
    if not isinstance(cutover, dict):
        raise RuntimeError("Ownership manifest is missing the cutover preparation section.")
    if cutover.get("phase") != "prepared":
        raise RuntimeError("Cutover phase must be prepared during step 3E-A.")
    if cutover.get("production_activation_allowed") is not False:
        raise RuntimeError("Production activation must remain blocked during step 3E-A.")

    excluded = set(manifest.get("excluded_database_objects", []))
    if excluded != {"_prisma_migrations", "alembic_version"}:
        raise RuntimeError("Migration metadata exclusions are incomplete.")

    baseline = manifest.get("alembic_baseline")
    if not isinstance(baseline, dict):
        raise RuntimeError("Ownership manifest is missing the Alembic baseline section.")

    expected: dict[str, Any] = {
        "state": "verified_not_owner",
        "revision": BASELINE_REVISION,
        "revision_count": 1,
        "head_count": 1,
        "upgrade_is_noop": True,
        "downgrade_supported": False,
        "version_table": "alembic_version",
        "version_table_schema": "public",
        "requires_schema_verification_before_stamp": True,
        "source": "canonical_postgresql_baseline",
    }
    for key, value in expected.items():
        if baseline.get(key) != value:
            raise RuntimeError(f"Invalid Alembic baseline manifest value for {key}.")


async def inspect_database(database_url: str) -> DatabaseState:
    engine = create_async_engine(normalize_database_url(database_url))
    try:
        async with engine.connect() as connection:
            if connection.dialect.name != "postgresql":
                raise RuntimeError("Alembic baseline verification requires PostgreSQL.")

            public_exists = await connection.scalar(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM information_schema.schemata "
                    "WHERE schema_name = 'public'"
                    ")"
                )
            )
            if not public_exists:
                raise RuntimeError("PostgreSQL schema public does not exist.")

            table_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_schema = 'public' "
                    "AND table_type = 'BASE TABLE' "
                    "AND table_name NOT IN ('_prisma_migrations', 'alembic_version')"
                )
            )
            enum_count = await connection.scalar(
                text(
                    "SELECT count(*) FROM pg_type AS type "
                    "JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace "
                    "WHERE namespace.nspname = 'public' AND type.typtype = 'e'"
                )
            )
            version_table = await connection.scalar(
                text("SELECT to_regclass('public.alembic_version')::text")
            )
            version_revisions: tuple[str, ...] = ()
            if version_table is not None:
                result = await connection.execute(
                    text('SELECT "version_num" FROM public.alembic_version ORDER BY "version_num"')
                )
                version_revisions = tuple(result.scalars())

            return DatabaseState(
                table_count=int(table_count or 0),
                enum_count=int(enum_count or 0),
                version_revisions=version_revisions,
            )
    finally:
        await engine.dispose()


def verify_database_state(state: DatabaseState) -> None:
    if state.table_count != EXPECTED_TABLE_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_TABLE_COUNT} application tables, found {state.table_count}."
        )
    if state.enum_count != EXPECTED_ENUM_COUNT:
        raise RuntimeError(f"Expected {EXPECTED_ENUM_COUNT} enums, found {state.enum_count}.")

    unknown_revisions = set(state.version_revisions) - {BASELINE_REVISION}
    if unknown_revisions:
        raise RuntimeError(f"Database contains unknown Alembic revisions: {unknown_revisions}.")
    if len(state.version_revisions) > 1:
        raise RuntimeError("Database contains multiple Alembic revisions for a single-head graph.")


def verify_canonical_baseline(database_url: str, pg_dump: str) -> None:
    schema = database_schema.dump_schema(database_url, pg_dump)
    result = database_schema.check_baseline(
        schema,
        database_schema.DEFAULT_BASELINE,
        database_schema.DEFAULT_CHECKSUM,
    )
    if result != 0:
        raise RuntimeError("Live PostgreSQL schema does not match the canonical baseline.")


def verify_sqlalchemy_parity(database_url: str) -> None:
    reflected = asyncio.run(sqlalchemy_schema.live_snapshot(database_url))
    if sqlalchemy_schema.compare_snapshots(sqlalchemy_schema.local_snapshot(), reflected) != 0:
        raise RuntimeError("SQLAlchemy metadata does not match the live PostgreSQL schema.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify a PostgreSQL database before stamping the Alembic baseline."
    )
    parser.add_argument("--verify", action="store_true", required=True)
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL"),
        help="PostgreSQL connection URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--pg-dump",
        default=os.getenv("PG_DUMP", "pg_dump"),
        help="pg_dump executable. Defaults to PG_DUMP or pg_dump.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database_url:
        print("DATABASE_URL or --database-url is required.", file=sys.stderr)
        return 2

    try:
        verify_revision_graph()
        verify_manifest()
        state = asyncio.run(inspect_database(args.database_url))
        verify_database_state(state)
        verify_canonical_baseline(args.database_url, args.pg_dump)
        verify_sqlalchemy_parity(args.database_url)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"Alembic baseline verification failed: {error}", file=sys.stderr)
        return 1

    print("Alembic baseline verification passed; the database is safe to stamp.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
