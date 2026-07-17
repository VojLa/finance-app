from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.url import normalize_database_url  # noqa: E402
from scripts import alembic_baseline, migration_policy  # noqa: E402
from scripts.database_schema import normalize_database_url as normalize_libpq_url  # noqa: E402

ALEMBIC_CONFIG = PROJECT_ROOT / "alembic.ini"
CANONICAL_BASELINE = PROJECT_ROOT / "database" / "baseline" / "schema.sql"
BASELINE_REVISION = "3d0001base"
DEFAULT_ADVISORY_LOCK_KEY = 731845204311764461


def run_command(command: list[str], *, database_url: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip() or "command failed without output"
        raise RuntimeError(f"Command failed ({' '.join(command)}): {detail}")
    return result


def run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return run_command(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_CONFIG), *arguments],
        database_url=database_url,
    )


def known_revisions() -> tuple[set[str], tuple[str, ...]]:
    directory = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG)))
    revisions = {revision.revision for revision in directory.walk_revisions()}
    return revisions, tuple(directory.get_heads())


def verify_revision_state(state: alembic_baseline.DatabaseState, *, require_head: bool) -> None:
    revisions, heads = known_revisions()
    if not state.version_revisions:
        raise RuntimeError(
            "Database is not stamped. Run the guarded baseline verification and explicit "
            f"alembic stamp {BASELINE_REVISION} before using the prepared migration runner."
        )
    unknown = set(state.version_revisions) - revisions
    if unknown:
        raise RuntimeError(f"Database contains unknown Alembic revisions: {sorted(unknown)}.")
    if len(state.version_revisions) != 1:
        raise RuntimeError("A single-head migration graph requires exactly one current revision.")
    if require_head and set(state.version_revisions) != set(heads):
        raise RuntimeError(
            f"Database is not at the Alembic head. Current={state.version_revisions}, heads={heads}."
        )


def verify_prepared_database(database_url: str, pg_dump: str, *, require_head: bool) -> None:
    migration_policy.verify_policy()
    alembic_baseline.verify_revision_graph()
    alembic_baseline.verify_manifest()
    state = asyncio.run(alembic_baseline.inspect_database(database_url))
    alembic_baseline.verify_database_state(state)
    verify_revision_state(state, require_head=require_head)
    alembic_baseline.verify_canonical_baseline(database_url, pg_dump)
    alembic_baseline.verify_sqlalchemy_parity(database_url)


def run_check(database_url: str, pg_dump: str) -> None:
    verify_prepared_database(database_url, pg_dump, require_head=True)
    run_alembic(database_url, "current", "--check-heads")
    run_alembic(database_url, "check")


async def upgrade_with_lock(database_url: str, lock_key: int) -> None:
    engine = create_async_engine(normalize_database_url(database_url))
    try:
        async with engine.connect() as connection:
            acquired = await connection.scalar(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
            if acquired is not True:
                raise RuntimeError(
                    "Database migration advisory lock is already held by another process."
                )
            try:
                await asyncio.to_thread(run_alembic, database_url, "upgrade", "head")
            finally:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )
    finally:
        await engine.dispose()


def run_upgrade(database_url: str, pg_dump: str, lock_key: int) -> None:
    verify_prepared_database(database_url, pg_dump, require_head=False)
    asyncio.run(upgrade_with_lock(database_url, lock_key))
    run_check(database_url, pg_dump)


async def public_schema_is_empty(database_url: str) -> bool:
    engine = create_async_engine(normalize_database_url(database_url))
    try:
        async with engine.connect() as connection:
            if connection.dialect.name != "postgresql":
                raise RuntimeError("Database bootstrap requires PostgreSQL.")
            object_count = await connection.scalar(
                text(
                    "SELECT ("
                    "  SELECT count(*) FROM information_schema.tables "
                    "  WHERE table_schema = 'public'"
                    ") + ("
                    "  SELECT count(*) FROM information_schema.views "
                    "  WHERE table_schema = 'public'"
                    ") + ("
                    "  SELECT count(*) FROM information_schema.sequences "
                    "  WHERE sequence_schema = 'public'"
                    ") + ("
                    "  SELECT count(*) FROM pg_type AS type "
                    "  JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace "
                    "  WHERE namespace.nspname = 'public' AND type.typtype = 'e'"
                    ")"
                )
            )
            return int(object_count or 0) == 0
    finally:
        await engine.dispose()


def load_canonical_baseline(database_url: str, psql: str) -> None:
    normalized_url = normalize_libpq_url(database_url)
    source = CANONICAL_BASELINE.read_text(encoding="utf-8")
    bootstrap_source = source.replace('CREATE SCHEMA "public";\n', "", 1)
    temporary_baseline = PROJECT_ROOT / ".canonical-bootstrap.sql"
    temporary_baseline.write_text(bootstrap_source, encoding="utf-8", newline="\n")
    try:
        result = subprocess.run(
            [
                psql,
                "--set=ON_ERROR_STOP=1",
                f"--dbname={normalized_url}",
                f"--file={temporary_baseline}",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        temporary_baseline.unlink(missing_ok=True)
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip() or "psql failed without output"
        raise RuntimeError(f"Unable to load canonical database baseline: {detail}")


def run_bootstrap(database_url: str, pg_dump: str, psql: str, lock_key: int) -> None:
    migration_policy.verify_policy()
    if not asyncio.run(public_schema_is_empty(database_url)):
        raise RuntimeError("Bootstrap refuses to modify a non-empty public schema.")
    load_canonical_baseline(database_url, psql)
    alembic_baseline.verify_canonical_baseline(database_url, pg_dump)
    alembic_baseline.verify_sqlalchemy_parity(database_url)
    run_alembic(database_url, "stamp", BASELINE_REVISION)
    asyncio.run(upgrade_with_lock(database_url, lock_key))
    run_check(database_url, pg_dump)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepared Alembic migration runner for the Prisma-to-Alembic cutover."
    )
    parser.add_argument("command", choices=("check", "upgrade", "bootstrap"))
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
    parser.add_argument(
        "--psql",
        default=os.getenv("PSQL", "psql"),
        help="psql executable used by bootstrap.",
    )
    parser.add_argument(
        "--lock-key",
        type=int,
        default=DEFAULT_ADVISORY_LOCK_KEY,
        help="PostgreSQL advisory lock key used for migration serialization.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database_url:
        print("DATABASE_URL or --database-url is required.", file=sys.stderr)
        return 2

    try:
        if args.command == "check":
            run_check(args.database_url, args.pg_dump)
        elif args.command == "upgrade":
            run_upgrade(args.database_url, args.pg_dump, args.lock_key)
        else:
            run_bootstrap(args.database_url, args.pg_dump, args.psql, args.lock_key)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"Database migration {args.command} failed: {error}", file=sys.stderr)
        return 1

    print(f"Database migration {args.command} completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
