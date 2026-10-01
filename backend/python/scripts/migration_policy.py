from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import database_schema

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
PRISMA_MIGRATIONS = REPOSITORY_ROOT / "prisma" / "migrations"
ARCHIVE_MANIFEST = BACKEND_ROOT / "database" / "prisma_migration_archive.toml"
OWNERSHIP_MANIFEST = BACKEND_ROOT / "database" / "schema_ownership.toml"
ENVIRONMENT_INVENTORY = BACKEND_ROOT / "database" / "cutover" / "environments.toml"
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
CUTOVER_REVISION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3e0001cutover_alembic_ownership.py"
)
PACKAGE_JSON = REPOSITORY_ROOT / "package.json"
BASELINE_REVISION = "3d0001base"
CUTOVER_REVISION = "3e0001cutover"
FIRST_SCHEMA_REVISION = "3f0001acctnote"
LIABILITY_REVISION = "3g0001liabbal"
TWELVE_DATA_PRICE_REVISION = "3h0001twdata"
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
LISTING_IDENTITY_REVISION = "420001yahooidentity"
LISTING_PROVIDER_HEALTH_REVISION = "430001markethealth"
ASSET_ALIAS_AUDIT_REVISION = "440001assetaudit"
HEAD_REVISION = ASSET_ALIAS_AUDIT_REVISION
SCHEMA_REGISTRY = BACKEND_ROOT / "database" / "schema_revisions.toml"
FIRST_SCHEMA_REVISION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3f0001acctnote_add_account_notes.py"
)
LIABILITY_REVISION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3g0001liabbal_add_liability_balances.py"
)
TWELVE_DATA_REVISION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3h0001twdata_add_twelve_data_provider_identity.py"
)
D1_LINEAGE_REVISION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3i0001d1base_add_daily_baseline_lineage.py"
)
TWELVE_DATA_FX_REVISION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3j0001twfx_add_twelve_data_fx_source.py"
)
MULTI_CURRENCY_COST_BASIS_REVISION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3k0001mcost_add_multicurrency_holding_cost_basis.py"
)
BACKGROUND_JOB_REVISION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3l0001bgjob_add_persisted_background_jobs.py"
)
IMPORT_PUBLICATION_ANCHOR_REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3m0001importanchor_allow_minute_import_publication_anchor.py"
)
EMPTY_INVESTMENT_HOLDING_REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3n0001emptyhold_initialize_empty_investment_holdings.py"
)
UNKNOWN_INVESTMENT_COST_BASIS_REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3o0001unkbasis_allow_unknown_investment_cost_basis.py"
)
RB_SCHEMA_FOUNDATION_REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3p0001rbfoundation_add_reconciliation_schema_foundation.py"
)
HISTORY_GENERATION_REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3q0001historygen_add_immutable_portfolio_history_generations.py"
)
HISTORY_CLEANUP_REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3r0001historycleanup_add_portfolio_history_cleanup.py"
)
CREDIT_LIMIT_REVISION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3o0001creditlimit_add_account_credit_limit.py"
)
MANUAL_MINUTE_BASELINE_REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3s0001manualbaseline_allow_manual_minute_baselines.py"
)
READ_MODEL_PUBLICATION_REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3t0001readmodelversion_add_user_read_model_publication.py"
)
SNAPSHOT_GENERATION_REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3u0001snapshotgeneration_add_staged_snapshot_generations.py"
)
PORTFOLIO_SNAPSHOT_REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3v0001portfoliosnapshot_add_investment_portfolio_snapshots.py"
)
MARKET_BASELINE_REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3w0001marketbaseline_allow_market_minute_baselines.py"
)
HISTORY_SERIES_REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3x0001historyseries_allow_history_series_baselines.py"
)
SNAPSHOT_SERIES_JOBS_REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3y0001snapshotjobs_add_snapshot_series_rebuild_orchestration.py"
)
HISTORY_DROP_REVISION_PATH = (
    BACKEND_ROOT
    / "migrations"
    / "versions"
    / "3z0001historydrop_remove_legacy_portfolio_history.py"
)
LISTING_PROVIDER_HEALTH_REVISION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "430001markethealth_add_listing_provider_health.py"
)
ASSET_ALIAS_AUDIT_REVISION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "440001assetaudit_add_operator_decision_audit.py"
)
ARCHIVE_HASH_PATTERN = re.compile(r'(?m)^archive_sha256 = "[^"]*"$')
FORBIDDEN_RUNTIME_PATTERNS = (
    "metadata.create_all",
    "metadata.drop_all",
    "alembic.command.upgrade",
    "alembic.command.stamp",
)


@dataclass(frozen=True)
class PrismaArchiveState:
    file_count: int
    migration_count: int
    last_migration: str
    aggregate_sha256: str
    files: tuple[str, ...]


def migration_files(migrations_root: Path = PRISMA_MIGRATIONS) -> list[Path]:
    if not migrations_root.is_dir():
        raise RuntimeError(f"Prisma migration directory does not exist: {migrations_root}")
    files = sorted(path for path in migrations_root.rglob("*") if path.is_file())
    if not files:
        raise RuntimeError("Prisma migration archive is empty.")
    return files


def archive_state(
    repository_root: Path = REPOSITORY_ROOT,
    migrations_root: Path = PRISMA_MIGRATIONS,
) -> PrismaArchiveState:
    files = migration_files(migrations_root)
    digest = hashlib.sha256()
    relative_paths: list[str] = []
    migration_names: set[str] = set()

    for path in files:
        relative_path = path.relative_to(repository_root).as_posix()
        content_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_digest.encode("ascii"))
        digest.update(b"\0")
        relative_paths.append(relative_path)
        if path.name == "migration.sql":
            migration_names.add(path.parent.name)

    if not migration_names:
        raise RuntimeError("Prisma migration archive contains no migration.sql files.")

    ordered_migrations = sorted(migration_names)
    return PrismaArchiveState(
        file_count=len(files),
        migration_count=len(ordered_migrations),
        last_migration=ordered_migrations[-1],
        aggregate_sha256=digest.hexdigest(),
        files=tuple(relative_paths),
    )


def render_archive_manifest(state: PrismaArchiveState) -> str:
    return (
        "version = 1\n"
        'state = "frozen"\n'
        "migration_creation_enabled = false\n"
        "migration_deployment_enabled = false\n"
        "legacy_archive_verification_enabled = true\n"
        f'last_migration = "{state.last_migration}"\n'
        f"file_count = {state.file_count}\n"
        f"migration_count = {state.migration_count}\n"
        f'aggregate_sha256 = "{state.aggregate_sha256}"\n'
        'hash_algorithm = "sha256(relative_path NUL content_sha256 NUL)"\n'
        f'cutover_baseline_revision = "{BASELINE_REVISION}"\n'
    )


def write_archive_manifest(
    state: PrismaArchiveState,
    archive_manifest: Path = ARCHIVE_MANIFEST,
    ownership_manifest: Path = OWNERSHIP_MANIFEST,
) -> None:
    archive_manifest.parent.mkdir(parents=True, exist_ok=True)
    archive_manifest.write_text(
        render_archive_manifest(state),
        encoding="utf-8",
        newline="\n",
    )

    ownership_text = ownership_manifest.read_text(encoding="utf-8")
    replacement = f'archive_sha256 = "{state.aggregate_sha256}"'
    updated, replacements = ARCHIVE_HASH_PATTERN.subn(replacement, ownership_text, count=1)
    if replacements != 1:
        raise RuntimeError("Ownership manifest must contain exactly one archive_sha256 field.")
    ownership_manifest.write_text(updated, encoding="utf-8", newline="\n")


def load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as source:
        return tomllib.load(source)


def display_path(path: Path) -> str:
    try:
        return path.relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def verify_archive_manifest(
    state: PrismaArchiveState,
    archive_manifest: Path = ARCHIVE_MANIFEST,
) -> None:
    manifest = load_toml(archive_manifest)
    expected: dict[str, Any] = {
        "version": 1,
        "state": "frozen",
        "migration_creation_enabled": False,
        "migration_deployment_enabled": False,
        "legacy_archive_verification_enabled": True,
        "last_migration": state.last_migration,
        "file_count": state.file_count,
        "migration_count": state.migration_count,
        "aggregate_sha256": state.aggregate_sha256,
        "hash_algorithm": "sha256(relative_path NUL content_sha256 NUL)",
        "cutover_baseline_revision": BASELINE_REVISION,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise RuntimeError(f"Frozen Prisma migration archive mismatch for {key}.")


def verify_environment_inventory(path: Path = ENVIRONMENT_INVENTORY) -> None:
    inventory = load_toml(path)
    if inventory.get("version") != 1:
        raise RuntimeError("Cutover environment inventory version must be 1.")
    if inventory.get("remote_databases_exist") is not False:
        raise RuntimeError("This direct cutover requires remote_databases_exist = false.")
    if inventory.get("required_environment_count") != 0:
        raise RuntimeError(
            "No persistent remote databases means required_environment_count must be 0."
        )
    reason = inventory.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise RuntimeError("The no-remote-database inventory requires an explicit reason.")
    if inventory.get("environments"):
        raise RuntimeError(
            "No environment entries are allowed when remote_databases_exist is false."
        )


def verify_ownership_manifest(
    archive: PrismaArchiveState,
    ownership_manifest: Path = OWNERSHIP_MANIFEST,
) -> None:
    manifest = load_toml(ownership_manifest)
    expected_top_level = {
        "schema_version": 27,
        "current_migration_owner": "alembic",
        "target_migration_owner": "alembic",
        "cutover_status": "completed",
    }
    for key, value in expected_top_level.items():
        if manifest.get(key) != value:
            raise RuntimeError(f"Invalid completed ownership manifest value for {key}.")

    if manifest.get("defaults") != {
        "current_owner": "alembic",
        "target_owner": "alembic",
        "cutover_status": "alembic_owned",
    }:
        raise RuntimeError("Application objects must inherit Alembic ownership after cutover.")

    cutover = manifest.get("cutover")
    expected_cutover = {
        "phase": "completed",
        "baseline_revision": BASELINE_REVISION,
        "cutover_revision": CUTOVER_REVISION,
        "previous_owner": "prisma",
        "current_owner": "alembic",
        "all_target_databases_stamped": True,
        "all_target_databases_activated": True,
        "deployment_command_switched": True,
        "remote_databases_exist": False,
        "production_activation_allowed": True,
        "completion_receipts_required": False,
    }
    if cutover != expected_cutover:
        raise RuntimeError("Completed cutover manifest is invalid.")

    alembic = manifest.get("alembic")
    if alembic != {
        "state": "sole_migration_owner",
        "baseline_revision": BASELINE_REVISION,
        "cutover_revision": CUTOVER_REVISION,
        "head_revision": HEAD_REVISION,
        "revision_count": 29,
        "head_count": 1,
    }:
        raise RuntimeError("Alembic ownership metadata is invalid.")

    current_schema = manifest.get("current_schema")
    if current_schema != {
        "revision": HEAD_REVISION,
        "schema_source": "database/revisions/440001assetaudit/schema.sql",
        "checksum_source": "database/revisions/440001assetaudit/schema.sha256",
    }:
        raise RuntimeError("Current schema artifact metadata is invalid.")

    prisma_migrations = manifest.get("prisma_migrations")
    expected_prisma = {
        "state": "frozen_archive",
        "creation_enabled": False,
        "deployment_enabled": False,
        "legacy_archive_verification_enabled": True,
        "archive_manifest": "database/prisma_migration_archive.toml",
        "archive_sha256": archive.aggregate_sha256,
    }
    if prisma_migrations != expected_prisma:
        raise RuntimeError("Frozen Prisma migration ownership policy is invalid.")

    if manifest.get("prisma_runtime") != {
        "state": "removed",
        "client_enabled": False,
        "schema_present": False,
    }:
        raise RuntimeError("Prisma runtime compatibility policy is invalid.")

    if manifest.get("cutover_evidence") != {
        "environment_inventory": "database/cutover/environments.toml",
        "remote_databases_exist": False,
        "preparation_receipts_required": False,
        "activation_receipts_required": False,
        "secrets_allowed": False,
    }:
        raise RuntimeError("No-remote-database cutover evidence is invalid.")


def verify_alembic_graph(config_path: Path = ALEMBIC_CONFIG) -> None:
    directory = ScriptDirectory.from_config(Config(str(config_path)))
    revisions = list(directory.walk_revisions())
    if directory.get_heads() != [HEAD_REVISION]:
        raise RuntimeError(f"Alembic head must be {HEAD_REVISION}.")
    if directory.get_bases() != [BASELINE_REVISION]:
        raise RuntimeError(f"Alembic base must remain {BASELINE_REVISION}.")
    if len(revisions) != 29:
        raise RuntimeError("The current schema requires exactly twenty-nine Alembic revisions.")

    by_revision = {revision.revision: revision for revision in revisions}
    baseline = by_revision.get(BASELINE_REVISION)
    cutover = by_revision.get(CUTOVER_REVISION)
    first_head = by_revision.get(FIRST_SCHEMA_REVISION)
    liability = by_revision.get(LIABILITY_REVISION)
    provider_identity = by_revision.get(TWELVE_DATA_PRICE_REVISION)
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
    listing_identity = by_revision.get(LISTING_IDENTITY_REVISION)
    listing_provider_health = by_revision.get(LISTING_PROVIDER_HEALTH_REVISION)
    asset_alias_audit = by_revision.get(ASSET_ALIAS_AUDIT_REVISION)
    if baseline is None or baseline.down_revision is not None:
        raise RuntimeError("The inherited Prisma baseline revision is invalid.")
    if cutover is None or cutover.down_revision != BASELINE_REVISION:
        raise RuntimeError("The Alembic ownership marker must follow the inherited baseline.")
    if first_head is None or first_head.down_revision != CUTOVER_REVISION:
        raise RuntimeError("The first Alembic schema revision must follow the ownership marker.")
    if liability is None or liability.down_revision != FIRST_SCHEMA_REVISION:
        raise RuntimeError("The liability balance revision must follow the previous head.")
    if provider_identity is None or provider_identity.down_revision != LIABILITY_REVISION:
        raise RuntimeError("The Twelve Data identity revision must follow the liability head.")
    if daily_baseline is None or daily_baseline.down_revision != TWELVE_DATA_PRICE_REVISION:
        raise RuntimeError("The D1 lineage revision must follow the provider identity head.")
    if direct_fx is None or direct_fx.down_revision != DAILY_BASELINE_REVISION:
        raise RuntimeError("The Twelve Data FX revision must follow the D1 lineage head.")
    if multi_currency_cost is None or multi_currency_cost.down_revision != DIRECT_FX_REVISION:
        raise RuntimeError("The multi-currency cost basis revision must follow the FX head.")
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
        raise RuntimeError("The history-generation schema must follow reconciliation foundation.")
    if history_cleanup is None or history_cleanup.down_revision != HISTORY_GENERATION_REVISION:
        raise RuntimeError("The history-cleanup schema must follow history generation.")
    if credit_limit is None or credit_limit.down_revision != HISTORY_CLEANUP_REVISION:
        raise RuntimeError("The credit-limit schema must follow the history-cleanup head.")
    if (
        manual_minute_baseline is None
        or manual_minute_baseline.down_revision != CREDIT_LIMIT_REVISION
    ):
        raise RuntimeError("The manual-minute baseline schema must follow the credit-limit head.")
    if (
        read_model_publication is None
        or read_model_publication.down_revision != MANUAL_MINUTE_BASELINE_REVISION
    ):
        raise RuntimeError("The read-model publication schema must follow manual-minute baseline.")
    if (
        snapshot_generation is None
        or snapshot_generation.down_revision != READ_MODEL_PUBLICATION_REVISION
    ):
        raise RuntimeError("The snapshot-generation schema must follow read-model publication.")
    if (
        portfolio_snapshot is None
        or portfolio_snapshot.down_revision != SNAPSHOT_GENERATION_REVISION
    ):
        raise RuntimeError("The portfolio-snapshot schema must follow snapshot generation.")
    if market_baseline is None or market_baseline.down_revision != PORTFOLIO_SNAPSHOT_REVISION:
        raise RuntimeError("The market-baseline schema must follow portfolio snapshot.")
    if history_series is None or history_series.down_revision != MARKET_BASELINE_REVISION:
        raise RuntimeError("The history-series schema must follow market baseline.")
    if (
        snapshot_series_jobs is None
        or snapshot_series_jobs.down_revision != HISTORY_SERIES_REVISION
    ):
        raise RuntimeError("Snapshot-series jobs must follow the history-series schema.")
    if history_drop is None or history_drop.down_revision != SNAPSHOT_SERIES_JOBS_REVISION:
        raise RuntimeError("History cleanup must follow Snapshot-series jobs.")
    if valuation_evidence is None or valuation_evidence.down_revision != HISTORY_DROP_REVISION:
        raise RuntimeError("Investment-movement valuation evidence must follow history cleanup.")
    if temporal_series is None or temporal_series.down_revision != VALUATION_EVIDENCE_REVISION:
        raise RuntimeError("Temporal snapshot-series links must follow valuation evidence.")
    if listing_identity is None or listing_identity.down_revision != TEMPORAL_SERIES_REVISION:
        raise RuntimeError("Listing market identity must follow temporal snapshot-series links.")
    if (
        listing_provider_health is None
        or listing_provider_health.down_revision != LISTING_IDENTITY_REVISION
    ):
        raise RuntimeError("Listing provider health must follow listing market identity.")
    if (
        asset_alias_audit is None
        or asset_alias_audit.down_revision != LISTING_PROVIDER_HEALTH_REVISION
    ):
        raise RuntimeError("Asset alias audit must follow listing provider health.")

    cutover_module = cutover.module
    expected_cutover_metadata = {
        "ownership_cutover": True,
        "previous_migration_owner": "prisma",
        "new_migration_owner": "alembic",
        "baseline_revision": BASELINE_REVISION,
        "prisma_schema_impact": "none",
    }
    for key, value in expected_cutover_metadata.items():
        if getattr(cutover_module, key, None) != value:
            raise RuntimeError(f"Cutover revision metadata is invalid for {key}.")

    first_head_module = first_head.module
    expected_first_head_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_nullable_column",
        "affected_tables": ("Account",),
        "affected_columns": ("Account.notes",),
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_first_head_metadata.items():
        if getattr(first_head_module, key, None) != value:
            raise RuntimeError(f"First schema revision metadata is invalid for {key}.")

    cutover_source = CUTOVER_REVISION_PATH.read_text(encoding="utf-8")
    if any(token in cutover_source for token in ("op.", "create_table", "add_column")):
        raise RuntimeError("The ownership cutover revision must not contain application DDL.")

    head_source = FIRST_SCHEMA_REVISION_PATH.read_text(encoding="utf-8")
    for token in ("op.add_column", '"Account"', '"notes"', "op.drop_column"):
        if token not in head_source:
            raise RuntimeError(f"First schema revision is missing required token {token}.")
    if 'WHERE "notes" IS NOT NULL' not in head_source:
        raise RuntimeError("Account notes downgrade must guard against data loss.")

    liability_module = liability.module
    expected_liability_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_liability_balance_contract",
        "affected_tables": ("LiabilityBalance",),
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_liability_metadata.items():
        if getattr(liability_module, key, None) != value:
            raise RuntimeError(f"Liability schema revision metadata is invalid for {key}.")
    liability_source = LIABILITY_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        "op.create_table(",
        '"LiabilityBalance"',
        '"LiabilityBalanceSource"',
        "op.drop_table",
        "source_enum.drop",
    ):
        if token not in liability_source:
            raise RuntimeError(f"Liability revision is missing required token {token}.")
    if 'SELECT EXISTS (SELECT 1 FROM "public"."LiabilityBalance")' not in liability_source:
        raise RuntimeError("Liability downgrade must guard canonical evidence against data loss.")

    expected_provider_metadata = {
        "schema_change": True,
        "schema_change_kind": "extend_market_provider_identity_enums",
        "affected_tables": ("AssetAlias", "AssetListing", "PriceSnapshot"),
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_provider_metadata.items():
        if getattr(provider_identity.module, key, None) != value:
            raise RuntimeError(f"Twelve Data identity revision metadata is invalid for {key}.")
    twelve_data_source = TWELVE_DATA_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        'ALTER TYPE "public"."AssetAliasProvider"',
        'ALTER TYPE "public"."PriceSource"',
        "ADD VALUE IF NOT EXISTS 'twelve_data'",
        "cannot be downgraded automatically",
    ):
        if token not in twelve_data_source:
            raise RuntimeError(f"Twelve Data identity revision is missing required token {token}.")

    expected_head_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_daily_baseline_lineage",
        "prisma_schema_impact": "required",
        "data_migration": True,
    }
    for key, value in expected_head_metadata.items():
        if getattr(daily_baseline.module, key, None) != value:
            raise RuntimeError(f"D1 lineage revision metadata is invalid for {key}.")
    lineage_source = D1_LINEAGE_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        '"AccountCanonicalState"',
        '"AccountCanonicalChange"',
        '"AccountSnapshotCanonicalBoundary"',
        '"DailySnapshotBaseline"',
        '"DailySnapshotBaselineAccount"',
        "row_number() OVER",
    ):
        if token not in lineage_source:
            raise RuntimeError(f"D1 lineage revision is missing required token {token}.")

    expected_fx_metadata = {
        "schema_change": True,
        "schema_change_kind": "extend_exchange_rate_source_identity",
        "affected_tables": ("ExchangeRate",),
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_fx_metadata.items():
        if getattr(direct_fx.module, key, None) != value:
            raise RuntimeError(f"Twelve Data FX revision metadata is invalid for {key}.")
    fx_source = TWELVE_DATA_FX_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        'ALTER TYPE "public"."ExchangeRateSource"',
        "ADD VALUE IF NOT EXISTS 'twelve_data'",
        "cannot be downgraded automatically",
    ):
        if token not in fx_source:
            raise RuntimeError(f"Twelve Data FX revision is missing required token {token}.")

    expected_cost_basis_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_multicurrency_holding_cost_basis",
        "affected_tables": ("Holding", "AccountSnapshotItem"),
        "affected_columns": (
            "Holding.costBasisByCurrency",
            "AccountSnapshotItem.nativeCostBasisByCurrency",
            "AccountSnapshotItem.averageBuyPrice",
            "AccountSnapshotItem.averageBuyPriceCurrency",
        ),
        "prisma_schema_impact": "required",
        "data_migration": True,
    }
    for key, value in expected_cost_basis_metadata.items():
        if getattr(multi_currency_cost.module, key, None) != value:
            raise RuntimeError(f"Multi-currency cost basis revision metadata is invalid for {key}.")
    cost_basis_source = MULTI_CURRENCY_COST_BASIS_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        '"costBasisByCurrency"',
        '"nativeCostBasisByCurrency"',
        '"averageBuyPrice"',
        '"averageBuyPriceCurrency"',
        "jsonb_typeof",
        "mod(floor({scaled_expression}), 2)",
        "complete native cost pair",
        "Cannot remove multi-currency",
    ):
        if token not in cost_basis_source:
            raise RuntimeError(
                f"Multi-currency cost basis revision is missing required token {token}."
            )

    expected_background_job_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_persisted_background_job_lifecycle",
        "affected_tables": ("BackgroundJob",),
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_background_job_metadata.items():
        if getattr(background_job.module, key, None) != value:
            raise RuntimeError(f"Background-job revision metadata is invalid for {key}.")
    background_job_source = BACKGROUND_JOB_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        '"BackgroundJob"',
        '"BackgroundJobStatus"',
        '"BackgroundJobKind"',
        '"BackgroundJob_one_running_per_account_key"',
        '"BackgroundJob_claim_idx"',
        '"BackgroundJob_expiredLease_idx"',
        '"BackgroundJob_running_has_lease"',
        '"BackgroundJob_completed_has_result"',
        '"maxAttempts" BETWEEN 1 AND 20',
        '"attemptCount" <= "maxAttempts"',
        "BackgroundJob_userId_accountId_kind_idempotencyKey_key",
        "Cannot remove BackgroundJob while durable job evidence exists.",
    ):
        if token not in background_job_source:
            raise RuntimeError(f"Background-job revision is missing required token {token}.")

    expected_anchor_metadata = {
        "schema_change": True,
        "schema_change_kind": "allow_import_current_value_publication_anchor",
        "affected_tables": ("DailySnapshotBaseline", "ImportJobPublicationTarget"),
        "affected_columns": (
            "DailySnapshotBaseline.granularity",
            "DailySnapshotBaseline.source",
            "DailySnapshotBaseline.backgroundJobId",
            "ImportJobPublicationTarget.jobId",
            "ImportJobPublicationTarget.userId",
            "ImportJobPublicationTarget.bucket",
            "ImportJobPublicationTarget.publishedAt",
        ),
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_anchor_metadata.items():
        if getattr(import_publication_anchor.module, key, None) != value:
            raise RuntimeError(f"Import publication-anchor revision metadata is invalid for {key}.")
    anchor_source = IMPORT_PUBLICATION_ANCHOR_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        "DailySnapshotBaseline_day_only",
        "DailySnapshotBaseline_day_or_import_anchor",
        "\\'minute\\'::\"SnapshotGranularity\"",
        "\\'import_event\\'::\"SnapshotSource\"",
        '"backgroundJobId"',
        "ImportJobPublicationTarget",
        "DailySnapshotBaseline_backgroundJob_user_fkey",
        "Cannot remove minute import publication anchors while evidence exists.",
    ):
        if token not in anchor_source:
            raise RuntimeError(
                f"Import publication-anchor revision is missing required token {token}."
            )

    expected_empty_holding_metadata = {
        "schema_change": True,
        "schema_change_kind": "initialize_empty_investment_holding_revision",
        "affected_tables": ("Account", "AccountCanonicalState", "Holding"),
        "affected_columns": (
            "Account.type",
            "AccountCanonicalState.lastInvestmentRevision",
            "AccountCanonicalState.holdingRevision",
            "Holding.accountId",
        ),
        "prisma_schema_impact": "required",
        "data_migration": True,
    }
    for key, value in expected_empty_holding_metadata.items():
        if getattr(empty_investment_holding.module, key, None) != value:
            raise RuntimeError(f"Empty investment Holding revision metadata is invalid for {key}.")
    empty_holding_source = EMPTY_INVESTMENT_HOLDING_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        'CREATE OR REPLACE FUNCTION "public"."initializeAccountCanonicalState"()',
        "'broker', 'exchange', 'crypto_wallet'",
        'state."lastInvestmentRevision" = 0',
        'state."holdingRevision" IS NULL',
        'FROM "public"."Holding" AS holding',
        'FROM "public"."AccountCanonicalChange" AS change',
        "change.\"kind\" = 'investment_event'",
        "Cannot remove initialized empty investment Holding revisions automatically.",
    ):
        if token not in empty_holding_source:
            raise RuntimeError(
                f"Empty investment Holding revision is missing required token {token}."
            )

    expected_unknown_basis_metadata = {
        "schema_change": True,
        "schema_change_kind": "allow_unknown_investment_cost_basis",
        "affected_tables": ("Holding", "AccountSnapshot", "AccountSnapshotItem"),
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_unknown_basis_metadata.items():
        if getattr(unknown_cost_basis.module, key, None) != value:
            raise RuntimeError(f"Unknown cost-basis revision metadata is invalid for {key}.")
    unknown_basis_source = UNKNOWN_INVESTMENT_COST_BASIS_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        "Holding_cost_basis_completeness_pair",
        "AccountSnapshotItem_cost_basis_completeness",
        "Cannot remove unknown investment cost-basis support while incomplete evidence exists.",
    ):
        if token not in unknown_basis_source:
            raise RuntimeError(f"Unknown cost-basis revision is missing required token {token}.")

    expected_reconciliation_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_import_reconciliation_evidence_foundation",
        "affected_tables": (
            "ImportBatch",
            "ImportRow",
            "Transaction",
            "ExchangeRate",
            "BackgroundJob",
            "ImportSourceOccurrence",
            "TransactionReportingEvidence",
            "ImportJobBatch",
            "ImportJobAffectedAccount",
            "TransactionPair",
        ),
        "prisma_schema_impact": "required",
        "data_migration": True,
    }
    for key, value in expected_reconciliation_metadata.items():
        if getattr(reconciliation.module, key, None) != value:
            raise RuntimeError(f"Reconciliation foundation metadata is invalid for {key}.")
    reconciliation_source = RB_SCHEMA_FOUNDATION_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        '"ImportSourceOccurrence"',
        '"TransactionReportingEvidence"',
        '"ImportJobBatch"',
        '"ImportJobAffectedAccount"',
        '"TransactionPair"',
        "ImportSourceOccurrence_fp_identity_key",
        "TransactionReportingEvidence_fx_direction_fkey",
        "ImportJobBatch_job_scope_fkey",
        "ImportJobAffectedAccount_member_fkey",
        "TransactionPair_reconciliation_evidence_complete_or_legacy",
        "Cannot remove import reconciliation evidence while durable evidence exists.",
    ):
        if token not in reconciliation_source:
            raise RuntimeError(
                f"Reconciliation foundation revision is missing required token {token}."
            )

    expected_history_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_immutable_portfolio_history_generations",
        "prisma_schema_impact": "required",
        "data_migration": True,
    }
    for key, value in expected_history_metadata.items():
        if getattr(history_generation.module, key, None) != value:
            raise RuntimeError(f"History-generation revision metadata is invalid for {key}.")
    history_source = HISTORY_GENERATION_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        '"PortfolioHistoryGeneration"',
        '"PortfolioHistoryReplayCheckpoint"',
        '"PortfolioHistoryPoint"',
        '"netWorthOpen"',
        '"netWorthClose"',
        '"PortfolioHistoryAccountPoint"',
        '"requestedByBackgroundJobId"',
        '"requestedByHistoryJobId"',
        "_eligible_history_change_select",
        '"PortfolioHistoryCanonicalInvalidation"',
        '"PortfolioHistoryDirtyState"',
        '"PortfolioHistoryScheduleState"',
        "1048576",
        "PortfolioHistoryPoint_id_generation_key",
        "cannot be downgraded automatically",
    ):
        if token not in history_source:
            raise RuntimeError(f"History-generation revision is missing required token {token}.")

    expected_cleanup_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_portfolio_history_cleanup_receipts",
        "affected_tables": (
            "PortfolioHistoryGeneration",
            "PortfolioHistoryGenerationCleanupReceipt",
            "PortfolioHistoryScheduleState",
        ),
        "prisma_schema_impact": "required",
    }
    for key, value in expected_cleanup_metadata.items():
        if getattr(history_cleanup.module, key, None) != value:
            raise RuntimeError(f"History-cleanup revision metadata is invalid for {key}.")
    cleanup_source = HISTORY_CLEANUP_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        "history_cleanup",
        '"supersededAt"',
        '"lastCleanedAt"',
        '"PortfolioHistoryGenerationCleanupReceipt"',
        "PortfolioHistoryCleanupReceipt_generation_user_fkey",
        "PortfolioHistoryCleanupReceipt_audit_job_user_fkey",
        '"payloadManifestHash"',
        "cannot be downgraded automatically",
    ):
        if token not in cleanup_source:
            raise RuntimeError(f"History-cleanup revision is missing required token {token}.")

    expected_credit_limit_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_account_credit_limit",
        "affected_tables": ("Account",),
        "affected_columns": ("Account.creditLimit",),
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_credit_limit_metadata.items():
        if getattr(credit_limit.module, key, None) != value:
            raise RuntimeError(f"Credit-limit revision metadata is invalid for {key}.")

    expected_manual_baseline_metadata = {
        "schema_change": True,
        "schema_change_kind": "allow_manual_minute_snapshot_baseline",
        "affected_tables": ("DailySnapshotBaseline",),
        "affected_columns": (
            "DailySnapshotBaseline.granularity",
            "DailySnapshotBaseline.source",
            "DailySnapshotBaseline.backgroundJobId",
        ),
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_manual_baseline_metadata.items():
        if getattr(manual_minute_baseline.module, key, None) != value:
            raise RuntimeError(f"Manual baseline revision metadata is invalid for {key}.")
    manual_baseline_source = MANUAL_MINUTE_BASELINE_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        "DailySnapshotBaseline_day_or_import_anchor",
        "manual_recalculation",
        "Cannot remove manual minute baselines while evidence exists.",
    ):
        if token not in manual_baseline_source:
            raise RuntimeError(f"Manual baseline revision is missing required token {token}.")

    expected_read_model_publication_metadata = {
        "schema_change": True,
        "schema_change_kind": "user_read_model_publication",
        "affected_tables": ("UserReadModelPublication",),
        "affected_columns": (
            "UserReadModelPublication.userId",
            "UserReadModelPublication.version",
            "UserReadModelPublication.baselineId",
            "UserReadModelPublication.scopes",
            "UserReadModelPublication.publishedAt",
        ),
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_read_model_publication_metadata.items():
        if getattr(read_model_publication.module, key, None) != value:
            raise RuntimeError(f"Read-model publication revision metadata is invalid for {key}.")
    read_model_publication_source = READ_MODEL_PUBLICATION_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        '"UserReadModelPublication"',
        '"baselineId"',
        '"publishedAt"',
        'INSERT INTO "public"."UserReadModelPublication"',
        "op.drop_table",
    ):
        if token not in read_model_publication_source:
            raise RuntimeError(
                f"Read-model publication revision is missing required token {token}."
            )

    expected_snapshot_generation_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_staged_snapshot_generations",
        "affected_tables": (
            "SnapshotGeneration",
            "SnapshotGenerationTarget",
            "AccountSnapshot",
            "NetWorthSnapshot",
            "DailySnapshotBaseline",
            "DailySnapshotBaselineAccount",
            "UserReadModelPublication",
        ),
        "prisma_schema_impact": "required",
        "data_migration": True,
    }
    for key, value in expected_snapshot_generation_metadata.items():
        if getattr(snapshot_generation.module, key, None) != value:
            raise RuntimeError(f"Snapshot-generation revision metadata is invalid for {key}.")
    snapshot_generation_source = SNAPSHOT_GENERATION_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        '"SnapshotGeneration"',
        '"SnapshotGenerationTarget"',
        '"generationId"',
        '"generationState"',
        "legacy-snapshot-generation:",
        "UserReadModelPublication_generation_published_fkey",
        "cannot be downgraded automatically",
    ):
        if token not in snapshot_generation_source:
            raise RuntimeError(f"Snapshot-generation revision is missing required token {token}.")
    portfolio_snapshot_tables = (
        "InvestmentAccountSnapshot",
        "InvestmentAccountSnapshotItem",
        "PortfolioSnapshot",
        "PortfolioSnapshotInput",
        "PortfolioSnapshotItem",
        "PortfolioSnapshotItemAccount",
    )
    expected_portfolio_snapshot_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_investment_portfolio_snapshot_projections",
        "affected_tables": portfolio_snapshot_tables,
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_portfolio_snapshot_metadata.items():
        if getattr(portfolio_snapshot.module, key, None) != value:
            raise RuntimeError(f"Portfolio-snapshot revision metadata is invalid for {key}.")
    portfolio_snapshot_source = PORTFOLIO_SNAPSHOT_REVISION_PATH.read_text(encoding="utf-8")
    for token in portfolio_snapshot_tables:
        if f'"{token}"' not in portfolio_snapshot_source:
            raise RuntimeError(f"Portfolio-snapshot revision is missing required token {token}.")

    expected_market_baseline_metadata = {
        "schema_change": True,
        "schema_change_kind": "allow_market_minute_snapshot_baseline",
        "affected_tables": ("DailySnapshotBaseline",),
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_market_baseline_metadata.items():
        if getattr(market_baseline.module, key, None) != value:
            raise RuntimeError(f"Market-baseline revision metadata is invalid for {key}.")
    market_baseline_source = MARKET_BASELINE_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        "DailySnapshotBaseline_day_or_import_anchor",
        "manual_recalculation",
        "price_refresh",
        "scheduled",
    ):
        if token not in market_baseline_source:
            raise RuntimeError(f"Market-baseline revision is missing required token {token}.")

    expected_history_series_metadata = {
        "schema_change": True,
        "schema_change_kind": "finalize_history_series_storage",
        "affected_tables": (
            "AccountSnapshot",
            "DailySnapshotBaseline",
            "PortfolioSnapshotInput",
            "UserReadModelPublicationWatermark",
        ),
        "prisma_schema_impact": "required",
        "data_migration": True,
    }
    for key, value in expected_history_series_metadata.items():
        if getattr(history_series.module, key, None) != value:
            raise RuntimeError(f"History-series revision metadata is invalid for {key}.")
    history_series_source = HISTORY_SERIES_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        "DailySnapshotBaseline_day_or_import_anchor",
        "holdings_recalculation",
        "liabilitiesValueByCurrency",
        "UserReadModelPublicationWatermark",
        'INSERT INTO "public"."UserReadModelPublicationWatermark"',
        'FROM "public"."UserReadModelPublication"',
        "PortfolioSnapshotInput_authorized_account_user_fkey",
    ):
        if token not in history_series_source:
            raise RuntimeError(f"History-series revision is missing required token {token}.")
    expected_snapshot_jobs_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_snapshot_series_rebuild_orchestration",
        "affected_tables": (
            "SnapshotSeriesRebuildJob",
            "SnapshotSeriesDirtyState",
            "SnapshotSeriesCanonicalInvalidation",
            "SnapshotSeriesScheduleState",
        ),
        "data_migration": True,
    }
    for key, value in expected_snapshot_jobs_metadata.items():
        if getattr(snapshot_series_jobs.module, key, None) != value:
            raise RuntimeError(f"Snapshot-series jobs revision metadata is invalid for {key}.")
    history_drop_metadata = {
        "schema_change": True,
        "schema_change_kind": "drop_legacy_portfolio_history_persistence",
        "data_migration": True,
        "destructive": True,
        "irreversible": True,
    }
    for key, value in history_drop_metadata.items():
        if getattr(history_drop.module, key, None) != value:
            raise RuntimeError(f"History-drop revision metadata is invalid for {key}.")
    history_drop_source = HISTORY_DROP_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        "legacy PortfolioHistory job lease is still active",
        "SnapshotSeries migration proof",
        "DROP TYPE",
    ):
        if token not in history_drop_source:
            raise RuntimeError(f"History-drop revision is missing required safety token {token}.")

    expected_listing_provider_health_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_listing_provider_health",
        "affected_tables": ("MarketDataListingHealth",),
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_listing_provider_health_metadata.items():
        if getattr(listing_provider_health.module, key, None) != value:
            raise RuntimeError(f"Listing-provider-health metadata is invalid for {key}.")
    listing_provider_health_source = LISTING_PROVIDER_HEALTH_REVISION_PATH.read_text(
        encoding="utf-8"
    )
    for token in (
        'CREATE TYPE "public"."MarketDataHealthState" AS ENUM',
        'CREATE TYPE "public"."MarketDataFailureReason" AS ENUM',
        '"MarketDataListingHealth"',
        '"MarketDataHealthState"',
        '"MarketDataFailureReason"',
    ):
        if token not in listing_provider_health_source:
            raise RuntimeError(
                f"Listing-provider-health revision is missing required token {token}."
            )

    expected_asset_alias_audit_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_asset_alias_audit",
        "affected_tables": ("AssetAliasAudit",),
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_asset_alias_audit_metadata.items():
        if getattr(asset_alias_audit.module, key, None) != value:
            raise RuntimeError(f"Asset-alias-audit metadata is invalid for {key}.")
    asset_alias_audit_source = ASSET_ALIAS_AUDIT_REVISION_PATH.read_text(encoding="utf-8")
    for token in (
        '"AssetAliasAudit"',
        "AssetAliasAudit_action_allowed",
        "prevent_asset_alias_audit_mutation",
        "AssetAliasAudit_append_only",
    ):
        if token not in asset_alias_audit_source:
            raise RuntimeError(f"Asset-alias-audit revision is missing required token {token}.")


def verify_schema_registry(
    registry_path: Path = SCHEMA_REGISTRY,
    config_path: Path = ALEMBIC_CONFIG,
) -> None:
    registry = load_toml(registry_path)
    if registry.get("version") != 1:
        raise RuntimeError("Schema revision registry version must be 1.")
    entries = registry.get("revisions")
    if not isinstance(entries, dict):
        raise RuntimeError("Schema revision registry is missing revisions.")

    directory = ScriptDirectory.from_config(Config(str(config_path)))
    graph_revisions = {revision.revision for revision in directory.walk_revisions()}
    if set(entries) != graph_revisions:
        raise RuntimeError("Schema revision registry must cover the complete Alembic graph.")

    for revision in graph_revisions:
        schema_path, checksum_path = database_schema.schema_artifact_paths(revision, registry_path)
        if not schema_path.is_file() or not checksum_path.is_file():
            raise RuntimeError(f"Schema artifact is missing for revision {revision}.")
        expected = schema_path.read_text(encoding="utf-8")
        digest_parts = checksum_path.read_text(encoding="utf-8").strip().split()
        if not digest_parts or digest_parts[0] != database_schema.schema_digest(expected):
            raise RuntimeError(f"Schema artifact checksum is invalid for revision {revision}.")

    head_entry = entries.get(HEAD_REVISION)
    if not isinstance(head_entry, dict) or head_entry.get("schema_change") is not True:
        raise RuntimeError("The current schema head must own a concrete schema artifact.")
    if "inherits_schema_from" in head_entry:
        raise RuntimeError("A schema-changing revision cannot inherit an older schema artifact.")


def verify_package_scripts(package_json: Path = PACKAGE_JSON) -> None:
    package = json.loads(package_json.read_text(encoding="utf-8"))
    scripts = package.get("scripts", {})
    upgrade = "cd backend/python && uv run python scripts/database_migrate.py upgrade"
    check = "cd backend/python && uv run python scripts/database_migrate.py check"
    bootstrap = "cd backend/python && uv run python scripts/database_migrate.py bootstrap"
    expected = {
        "db:migrate": upgrade,
        "db:deploy": upgrade,
        "db:check": check,
        "db:bootstrap": bootstrap,
        "db:alembic:check": check,
        "db:alembic:upgrade": upgrade,
        "db:alembic:bootstrap": bootstrap,
        "db:archive:verify": (
            "cd backend/python && uv run python scripts/migration_policy.py --check"
        ),
        "seed": "cd backend/python && uv run python scripts/seed_defaults.py",
    }
    for name, command in expected.items():
        if scripts.get(name) != command:
            raise RuntimeError(f"Invalid post-cutover database script: {name}.")
    forbidden_scripts = {name for name in scripts if "prisma" in name.lower()}
    if forbidden_scripts:
        raise RuntimeError(f"Prisma package scripts must be removed: {sorted(forbidden_scripts)}")
    dependencies = {
        **package.get("dependencies", {}),
        **package.get("devDependencies", {}),
    }
    forbidden_dependencies = {
        "@prisma/client",
        "prisma",
        "bcryptjs",
        "@types/bcryptjs",
    }
    present = sorted(forbidden_dependencies.intersection(dependencies))
    if present:
        raise RuntimeError(f"Removed runtime dependencies are still declared: {present}")


def verify_runtime_ddl(app_root: Path | None = None) -> None:
    root = app_root or BACKEND_ROOT / "app"
    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_RUNTIME_PATTERNS:
            if pattern in source:
                raise RuntimeError(
                    f"Forbidden runtime migration operation {pattern} in {display_path(path)}."
                )


def verify_workflow_policy(workflows_root: Path | None = None) -> None:
    root = workflows_root or REPOSITORY_ROOT / ".github" / "workflows"
    forbidden = (
        "prisma migrate dev",
        "prisma migrate deploy",
        "prisma migrate reset",
        "prisma db push",
    )
    for path in sorted(root.glob("*.y*ml")):
        source = path.read_text(encoding="utf-8")
        for command in forbidden:
            if command in source:
                raise RuntimeError(
                    f"Forbidden Prisma migration command {command} in {display_path(path)}."
                )
    database_workflow = root / "database-schema.yml"
    if database_workflow.is_file():
        source = database_workflow.read_text(encoding="utf-8")
        for forbidden_command in ("prisma generate", "prisma validate", "npm run db:prisma"):
            if forbidden_command in source:
                raise RuntimeError(
                    f"Database CI contains removed Prisma tooling: {forbidden_command}."
                )
        head_schema_check = f"python scripts/database_schema.py --check --revision {HEAD_REVISION}"
        if source.count(head_schema_check) < 2:
            raise RuntimeError(
                "Database CI must verify the current head artifact after upgrade and bootstrap."
            )


def verify_policy() -> PrismaArchiveState:
    state = archive_state()
    verify_archive_manifest(state)
    verify_environment_inventory()
    verify_ownership_manifest(state)
    verify_alembic_graph()
    verify_schema_registry()
    verify_package_scripts()
    verify_runtime_ddl()
    verify_workflow_policy()
    return state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enforce the Prisma-to-Alembic migration policy.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write-archive-manifest", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        state = archive_state()
        if args.write_archive_manifest:
            write_archive_manifest(state)
            print(
                "Wrote frozen Prisma migration archive manifest "
                f"for {state.migration_count} migrations ({state.aggregate_sha256})."
            )
            return 0
        verify_policy()
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"Migration policy verification failed: {error}", file=sys.stderr)
        return 1

    print(
        "Migration policy verification passed; Alembic is the sole migration owner and the "
        "Prisma migration history remains frozen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
