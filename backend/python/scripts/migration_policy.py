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
HEAD_REVISION = "3f0001acctnote"
SCHEMA_REGISTRY = BACKEND_ROOT / "database" / "schema_revisions.toml"
FIRST_SCHEMA_REVISION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3f0001acctnote_add_account_notes.py"
)
PRISMA_SCHEMA = REPOSITORY_ROOT / "prisma" / "schema.prisma"
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
        "schema_version": 7,
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
        "revision_count": 3,
        "head_count": 1,
    }:
        raise RuntimeError("Alembic ownership metadata is invalid.")

    current_schema = manifest.get("current_schema")
    if current_schema != {
        "revision": HEAD_REVISION,
        "schema_source": "database/revisions/3f0001acctnote/schema.sql",
        "checksum_source": "database/revisions/3f0001acctnote/schema.sha256",
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
        "state": "compatibility_mirror",
        "client_enabled": True,
        "schema_is_migration_source": False,
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
    if len(revisions) != 3:
        raise RuntimeError("The first schema migration requires exactly three Alembic revisions.")

    by_revision = {revision.revision: revision for revision in revisions}
    baseline = by_revision.get(BASELINE_REVISION)
    cutover = by_revision.get(CUTOVER_REVISION)
    head = by_revision.get(HEAD_REVISION)
    if baseline is None or baseline.down_revision is not None:
        raise RuntimeError("The inherited Prisma baseline revision is invalid.")
    if cutover is None or cutover.down_revision != BASELINE_REVISION:
        raise RuntimeError("The Alembic ownership marker must follow the inherited baseline.")
    if head is None or head.down_revision != CUTOVER_REVISION:
        raise RuntimeError("The first Alembic schema revision must follow the ownership marker.")

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

    head_module = head.module
    expected_head_metadata = {
        "schema_change": True,
        "schema_change_kind": "add_nullable_column",
        "affected_tables": ("Account",),
        "affected_columns": ("Account.notes",),
        "prisma_schema_impact": "required",
        "data_migration": False,
    }
    for key, value in expected_head_metadata.items():
        if getattr(head_module, key, None) != value:
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
        raise RuntimeError("The first schema revision must own a concrete schema artifact.")
    if "inherits_schema_from" in head_entry:
        raise RuntimeError("A schema-changing revision cannot inherit an older schema artifact.")

    prisma_source = PRISMA_SCHEMA.read_text(encoding="utf-8")
    account_start = prisma_source.index("model Account {")
    account_end = prisma_source.index("\n}", account_start)
    if "notes" not in prisma_source[account_start:account_end]:
        raise RuntimeError("Prisma Account model must expose the notes compatibility field.")


def verify_package_scripts(package_json: Path = PACKAGE_JSON) -> None:
    scripts = json.loads(package_json.read_text(encoding="utf-8")).get("scripts", {})
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
        "db:prisma:archive:verify": "node scripts/prisma-archive-verify.mjs",
    }
    for name, command in expected.items():
        if scripts.get(name) != command:
            raise RuntimeError(f"Invalid post-cutover database script: {name}.")
    if "db:prisma:deploy:legacy" in scripts:
        raise RuntimeError("The unrestricted legacy Prisma deploy script must be removed.")


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
        if "npm run db:prisma:archive:verify" not in source:
            raise RuntimeError("Database CI must use the restricted Prisma archive wrapper.")


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
