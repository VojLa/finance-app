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
CUTOVER_REVISION = "3e0001cutover"
FIRST_SCHEMA_REVISION = "3f0001acctnote"
LIABILITY_REVISION = "3g0001liabbal"
PREVIOUS_HEAD_REVISION = "3h0001twdata"
DAILY_BASELINE_REVISION = "3i0001d1base"
DIRECT_FX_REVISION = "3j0001twfx"
MULTI_CURRENCY_COST_BASIS_REVISION = "3k0001mcost"
BACKGROUND_JOB_REVISION = "3l0001bgjob"
IMPORT_PUBLICATION_ANCHOR_REVISION = "3m0001importanchor"
EMPTY_INVESTMENT_HOLDING_REVISION = "3n0001emptyhold"
UNKNOWN_INVESTMENT_COST_BASIS_REVISION = "3o0001unkbasis"
RB_SCHEMA_FOUNDATION_REVISION = "3p0001rbfoundation"
HISTORY_GENERATION_REVISION = "3q0001historygen"
HISTORY_CLEANUP_REVISION = "3r0001historycleanup"
CREDIT_LIMIT_REVISION = "3o0001creditlimit"
MANUAL_MINUTE_BASELINE_REVISION = "3s0001manualbaseline"
READ_MODEL_PUBLICATION_REVISION = "3t0001readmodelversion"
SNAPSHOT_GENERATION_REVISION = "3u0001snapshotgeneration"
PORTFOLIO_SNAPSHOT_REVISION = "3v0001portfoliosnapshot"
MARKET_BASELINE_REVISION = "3w0001marketbaseline"
HISTORY_SERIES_REVISION = "3x0001historyseries"
SNAPSHOT_SERIES_JOBS_REVISION = "3y0001snapshotjobs"
HISTORY_DROP_REVISION = "3z0001historydrop"
VALUATION_EVIDENCE_REVISION = "400001anycoinvaluation"
TEMPORAL_SERIES_REVISION = "410001serieslinks"
LISTING_MARKET_IDENTITY_REVISION = "420001yahooidentity"
LISTING_PROVIDER_HEALTH_REVISION = "430001markethealth"
ASSET_ALIAS_AUDIT_REVISION = "440001assetaudit"
HEAD_REVISION = ASSET_ALIAS_AUDIT_REVISION
EXPECTED_TABLE_COUNT = 63
EXPECTED_ENUM_COUNT = 33
HISTORY_GENERATION_TABLE_COUNT = 54
HISTORY_GENERATION_ENUM_COUNT = 34
PREVIOUS_HEAD_TABLE_COUNT = 36
PREVIOUS_HEAD_ENUM_COUNT = 28
PREVIOUS_TABLE_COUNT = 31
PREVIOUS_ENUM_COUNT = 28
INHERITED_TABLE_COUNT = 30
INHERITED_ENUM_COUNT = 27


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

    if len(revisions) != 29:
        raise RuntimeError(
            f"Expected exactly twenty-nine Alembic revisions, found {len(revisions)}."
        )
    if heads != [HEAD_REVISION]:
        raise RuntimeError(f"Expected Alembic head {HEAD_REVISION}, found {heads}.")
    if bases != [BASELINE_REVISION]:
        raise RuntimeError(f"Expected Alembic base {BASELINE_REVISION}, found {bases}.")

    by_revision = {revision.revision: revision for revision in revisions}
    baseline = by_revision.get(BASELINE_REVISION)
    cutover = by_revision.get(CUTOVER_REVISION)
    first_schema = by_revision.get(FIRST_SCHEMA_REVISION)
    liability = by_revision.get(LIABILITY_REVISION)
    previous_head = by_revision.get(PREVIOUS_HEAD_REVISION)
    daily_baseline = by_revision.get(DAILY_BASELINE_REVISION)
    direct_fx = by_revision.get(DIRECT_FX_REVISION)
    multi_currency_cost = by_revision.get(MULTI_CURRENCY_COST_BASIS_REVISION)
    background_job = by_revision.get(BACKGROUND_JOB_REVISION)
    import_publication_anchor = by_revision.get(IMPORT_PUBLICATION_ANCHOR_REVISION)
    empty_investment_holding = by_revision.get(EMPTY_INVESTMENT_HOLDING_REVISION)
    unknown_cost_basis = by_revision.get(UNKNOWN_INVESTMENT_COST_BASIS_REVISION)
    reconciliation = by_revision.get(RB_SCHEMA_FOUNDATION_REVISION)
    history_generation = by_revision.get(HISTORY_GENERATION_REVISION)
    history_cleanup = by_revision.get(HISTORY_CLEANUP_REVISION)
    credit_limit = by_revision.get(CREDIT_LIMIT_REVISION)
    manual_minute_baseline = by_revision.get(MANUAL_MINUTE_BASELINE_REVISION)
    read_model_publication = by_revision.get(READ_MODEL_PUBLICATION_REVISION)
    snapshot_generation = by_revision.get(SNAPSHOT_GENERATION_REVISION)
    portfolio_snapshot = by_revision.get(PORTFOLIO_SNAPSHOT_REVISION)
    market_baseline = by_revision.get(MARKET_BASELINE_REVISION)
    history_series = by_revision.get(HISTORY_SERIES_REVISION)
    snapshot_series_jobs = by_revision.get(SNAPSHOT_SERIES_JOBS_REVISION)
    history_drop = by_revision.get(HISTORY_DROP_REVISION)
    valuation_evidence = by_revision.get(VALUATION_EVIDENCE_REVISION)
    temporal_series = by_revision.get(TEMPORAL_SERIES_REVISION)
    listing_market_identity = by_revision.get(LISTING_MARKET_IDENTITY_REVISION)
    listing_provider_health = by_revision.get(LISTING_PROVIDER_HEALTH_REVISION)
    asset_alias_audit = by_revision.get(ASSET_ALIAS_AUDIT_REVISION)
    if baseline is None or baseline.down_revision is not None:
        raise RuntimeError("The Alembic baseline revision graph is invalid.")
    if cutover is None or cutover.down_revision != BASELINE_REVISION:
        raise RuntimeError("The Alembic ownership cutover revision graph is invalid.")
    if first_schema is None or first_schema.down_revision != CUTOVER_REVISION:
        raise RuntimeError("The first Alembic schema revision must follow the cutover marker.")
    if liability is None or liability.down_revision != FIRST_SCHEMA_REVISION:
        raise RuntimeError("The liability schema revision must follow the previous head.")
    if previous_head is None or previous_head.down_revision != LIABILITY_REVISION:
        raise RuntimeError("The Twelve Data identity revision must follow the liability head.")
    if daily_baseline is None or daily_baseline.down_revision != PREVIOUS_HEAD_REVISION:
        raise RuntimeError("The D1 lineage revision must follow the provider identity head.")
    if direct_fx is None or direct_fx.down_revision != DAILY_BASELINE_REVISION:
        raise RuntimeError("The direct FX revision must follow the D1 lineage head.")
    if multi_currency_cost is None or multi_currency_cost.down_revision != DIRECT_FX_REVISION:
        raise RuntimeError("The multi-currency cost basis revision must follow the direct FX head.")
    if background_job is None or background_job.down_revision != MULTI_CURRENCY_COST_BASIS_REVISION:
        raise RuntimeError(
            "The background-job revision must follow the multi-currency cost basis head."
        )
    if (
        import_publication_anchor is None
        or import_publication_anchor.down_revision != BACKGROUND_JOB_REVISION
    ):
        raise RuntimeError(
            "The import publication-anchor revision must follow the background-job head."
        )
    if (
        empty_investment_holding is None
        or empty_investment_holding.down_revision != IMPORT_PUBLICATION_ANCHOR_REVISION
    ):
        raise RuntimeError(
            "The empty investment Holding revision must follow the import publication-anchor head."
        )
    if (
        unknown_cost_basis is None
        or unknown_cost_basis.down_revision != EMPTY_INVESTMENT_HOLDING_REVISION
    ):
        raise RuntimeError(
            "The unknown investment cost-basis revision must follow the empty-Holding head."
        )
    if (
        reconciliation is None
        or reconciliation.down_revision != UNKNOWN_INVESTMENT_COST_BASIS_REVISION
    ):
        raise RuntimeError(
            "The reconciliation schema foundation must follow the unknown cost-basis head."
        )
    if (
        history_generation is None
        or history_generation.down_revision != RB_SCHEMA_FOUNDATION_REVISION
    ):
        raise RuntimeError("The history-generation revision must follow reconciliation foundation.")
    if history_cleanup is None or history_cleanup.down_revision != HISTORY_GENERATION_REVISION:
        raise RuntimeError("The history-cleanup revision must follow history generation.")
    if credit_limit is None or credit_limit.down_revision != HISTORY_CLEANUP_REVISION:
        raise RuntimeError("The credit-limit revision must follow history cleanup.")
    if (
        manual_minute_baseline is None
        or manual_minute_baseline.down_revision != CREDIT_LIMIT_REVISION
    ):
        raise RuntimeError("The manual-minute baseline revision must follow credit limit.")
    if (
        read_model_publication is None
        or read_model_publication.down_revision != MANUAL_MINUTE_BASELINE_REVISION
    ):
        raise RuntimeError(
            "The read-model publication revision must follow manual-minute baseline."
        )
    if (
        snapshot_generation is None
        or snapshot_generation.down_revision != READ_MODEL_PUBLICATION_REVISION
    ):
        raise RuntimeError("The snapshot-generation revision must follow read-model publication.")
    if (
        portfolio_snapshot is None
        or portfolio_snapshot.down_revision != SNAPSHOT_GENERATION_REVISION
    ):
        raise RuntimeError("The portfolio-snapshot revision must follow snapshot generation.")
    if market_baseline is None or market_baseline.down_revision != PORTFOLIO_SNAPSHOT_REVISION:
        raise RuntimeError("The market-baseline revision must follow portfolio snapshot.")
    if history_series is None or history_series.down_revision != MARKET_BASELINE_REVISION:
        raise RuntimeError("The history-series revision must follow market baseline.")
    if (
        snapshot_series_jobs is None
        or snapshot_series_jobs.down_revision != HISTORY_SERIES_REVISION
    ):
        raise RuntimeError("The snapshot-series jobs revision must follow history series.")
    if history_drop is None or history_drop.down_revision != SNAPSHOT_SERIES_JOBS_REVISION:
        raise RuntimeError("The legacy-history drop must follow snapshot-series jobs.")
    if valuation_evidence is None or valuation_evidence.down_revision != HISTORY_DROP_REVISION:
        raise RuntimeError(
            "Investment-movement valuation evidence must follow legacy-history drop."
        )
    if temporal_series is None or temporal_series.down_revision != VALUATION_EVIDENCE_REVISION:
        raise RuntimeError("Temporal snapshot-series links must follow valuation evidence.")
    if (
        listing_market_identity is None
        or listing_market_identity.down_revision != TEMPORAL_SERIES_REVISION
    ):
        raise RuntimeError("Listing market identity must follow temporal series links.")
    if (
        listing_provider_health is None
        or listing_provider_health.down_revision != LISTING_MARKET_IDENTITY_REVISION
    ):
        raise RuntimeError("Listing provider health must follow listing market identity.")
    if (
        asset_alias_audit is None
        or asset_alias_audit.down_revision != LISTING_PROVIDER_HEALTH_REVISION
    ):
        raise RuntimeError("Asset alias audit must follow listing provider health.")


def verify_manifest() -> None:
    manifest = tomllib.loads(OWNERSHIP_MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 27:
        raise RuntimeError(
            "Ownership manifest schema_version must be 27 after audit schema addition."
        )
    if manifest.get("current_migration_owner") != "alembic":
        raise RuntimeError("Alembic must be the current migration owner after cutover.")
    if manifest.get("target_migration_owner") != "alembic":
        raise RuntimeError("Alembic must remain the target migration owner.")
    if manifest.get("cutover_status") != "completed":
        raise RuntimeError("Migration ownership cutover must be completed.")

    cutover = manifest.get("cutover")
    if not isinstance(cutover, dict):
        raise RuntimeError("Ownership manifest is missing the cutover section.")
    if cutover.get("phase") != "completed":
        raise RuntimeError("Cutover phase must be completed.")
    if cutover.get("cutover_revision") != CUTOVER_REVISION:
        raise RuntimeError("Ownership manifest has the wrong cutover revision.")
    if cutover.get("remote_databases_exist") is not False:
        raise RuntimeError("This direct cutover requires no persistent remote databases.")

    excluded = set(manifest.get("excluded_database_objects", []))
    if excluded != {"_prisma_migrations", "alembic_version"}:
        raise RuntimeError("Migration metadata exclusions are incomplete.")

    baseline = manifest.get("alembic_baseline")
    if not isinstance(baseline, dict):
        raise RuntimeError("Ownership manifest is missing the Alembic baseline section.")

    expected: dict[str, Any] = {
        "state": "inherited_by_alembic_owner",
        "revision": BASELINE_REVISION,
        "revision_count": 29,
        "head_count": 1,
        "head_revision": HEAD_REVISION,
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
    revision = state.version_revisions[0] if state.version_revisions else BASELINE_REVISION
    if revision == RB_SCHEMA_FOUNDATION_REVISION:
        expected_tables = 42
        expected_enums = 30
    elif revision in {
        BACKGROUND_JOB_REVISION,
        IMPORT_PUBLICATION_ANCHOR_REVISION,
        EMPTY_INVESTMENT_HOLDING_REVISION,
        UNKNOWN_INVESTMENT_COST_BASIS_REVISION,
    }:
        expected_tables = 38
        expected_enums = 30
    elif revision == HISTORY_GENERATION_REVISION:
        expected_tables = HISTORY_GENERATION_TABLE_COUNT
        expected_enums = HISTORY_GENERATION_ENUM_COUNT
    elif revision in {
        HISTORY_CLEANUP_REVISION,
        CREDIT_LIMIT_REVISION,
        MANUAL_MINUTE_BASELINE_REVISION,
    }:
        expected_tables = 56
        expected_enums = 35
    elif revision == READ_MODEL_PUBLICATION_REVISION:
        expected_tables = 57
        expected_enums = 35
    elif revision == SNAPSHOT_GENERATION_REVISION:
        expected_tables = 59
        expected_enums = 35
    elif revision in {PORTFOLIO_SNAPSHOT_REVISION, MARKET_BASELINE_REVISION}:
        expected_tables = 65
        expected_enums = 35
    elif revision == HISTORY_SERIES_REVISION:
        expected_tables = 66
        expected_enums = 35
    elif revision == SNAPSHOT_SERIES_JOBS_REVISION:
        expected_tables = 70
        expected_enums = 36
    elif revision == VALUATION_EVIDENCE_REVISION:
        expected_tables = 57
        expected_enums = EXPECTED_ENUM_COUNT
    elif revision == HEAD_REVISION:
        expected_tables = EXPECTED_TABLE_COUNT
        expected_enums = EXPECTED_ENUM_COUNT
    elif revision == LISTING_PROVIDER_HEALTH_REVISION:
        expected_tables = 62
        expected_enums = 33
    elif revision in {TEMPORAL_SERIES_REVISION, LISTING_MARKET_IDENTITY_REVISION}:
        expected_tables = 61
        expected_enums = 31
    elif revision in {
        DAILY_BASELINE_REVISION,
        DIRECT_FX_REVISION,
        MULTI_CURRENCY_COST_BASIS_REVISION,
    }:
        expected_tables = PREVIOUS_HEAD_TABLE_COUNT
        expected_enums = PREVIOUS_HEAD_ENUM_COUNT
    elif revision in {LIABILITY_REVISION, PREVIOUS_HEAD_REVISION}:
        expected_tables = PREVIOUS_TABLE_COUNT
        expected_enums = PREVIOUS_ENUM_COUNT
    else:
        expected_tables = INHERITED_TABLE_COUNT
        expected_enums = INHERITED_ENUM_COUNT
    if state.table_count != expected_tables:
        raise RuntimeError(
            f"Expected {expected_tables} application tables, found {state.table_count}."
        )
    if state.enum_count != expected_enums:
        raise RuntimeError(f"Expected {expected_enums} enums, found {state.enum_count}.")

    directory = ScriptDirectory.from_config(alembic_config())
    known = {revision.revision for revision in directory.walk_revisions()}
    unknown_revisions = set(state.version_revisions) - known
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


def verify_revision_schema(database_url: str, pg_dump: str, revision: str) -> None:
    database_schema.verify_live_schema(database_url, pg_dump, revision)


def verify_sqlalchemy_parity(database_url: str) -> None:
    reflected = asyncio.run(sqlalchemy_schema.live_snapshot(database_url))
    if sqlalchemy_schema.compare_snapshots(sqlalchemy_schema.local_snapshot(), reflected) != 0:
        raise RuntimeError("SQLAlchemy metadata does not match the live PostgreSQL schema.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify an inherited PostgreSQL schema across the Alembic ownership boundary."
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
        revision = state.version_revisions[0] if state.version_revisions else BASELINE_REVISION
        verify_revision_schema(args.database_url, args.pg_dump, revision)
        if revision == HEAD_REVISION:
            verify_sqlalchemy_parity(args.database_url)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"Alembic baseline verification failed: {error}", file=sys.stderr)
        return 1

    print("Alembic schema verification passed for the database revision state.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
