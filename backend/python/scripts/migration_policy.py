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

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
PRISMA_MIGRATIONS = REPOSITORY_ROOT / "prisma" / "migrations"
ARCHIVE_MANIFEST = BACKEND_ROOT / "database" / "prisma_migration_archive.toml"
OWNERSHIP_MANIFEST = BACKEND_ROOT / "database" / "schema_ownership.toml"
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
PACKAGE_JSON = REPOSITORY_ROOT / "package.json"
BASELINE_REVISION = "3d0001base"
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


def verify_ownership_manifest(
    archive: PrismaArchiveState,
    ownership_manifest: Path = OWNERSHIP_MANIFEST,
) -> None:
    manifest = load_toml(ownership_manifest)
    if manifest.get("schema_version") != 5:
        raise RuntimeError("Ownership manifest schema_version must be 5 for step 3E-A.")
    if manifest.get("current_migration_owner") != "prisma":
        raise RuntimeError("Prisma remains the migration owner until activation in step 3E-B.")
    if manifest.get("target_migration_owner") != "alembic":
        raise RuntimeError("Alembic must remain the target migration owner.")
    if manifest.get("cutover_status") != "ready":
        raise RuntimeError("Step 3E-A requires cutover_status ready.")

    cutover = manifest.get("cutover")
    if not isinstance(cutover, dict):
        raise RuntimeError("Ownership manifest is missing the cutover section.")
    cutover_expected = {
        "phase": "prepared",
        "baseline_revision": BASELINE_REVISION,
        "all_target_databases_must_be_stamped": True,
        "production_activation_allowed": False,
        "receipts_required_before_activation": True,
    }
    for key, value in cutover_expected.items():
        if cutover.get(key) != value:
            raise RuntimeError(f"Invalid cutover manifest value for {key}.")

    prisma_migrations = manifest.get("prisma_migrations")
    if not isinstance(prisma_migrations, dict):
        raise RuntimeError("Ownership manifest is missing prisma_migrations.")
    prisma_expected = {
        "state": "frozen_archive",
        "creation_enabled": False,
        "deployment_enabled": False,
        "legacy_archive_verification_enabled": True,
        "archive_manifest": "database/prisma_migration_archive.toml",
        "archive_sha256": archive.aggregate_sha256,
    }
    for key, value in prisma_expected.items():
        if prisma_migrations.get(key) != value:
            raise RuntimeError(f"Invalid Prisma migration policy value for {key}.")

    prisma_runtime = manifest.get("prisma_runtime")
    if prisma_runtime != {
        "state": "compatibility_mirror",
        "client_enabled": True,
        "schema_is_migration_source": False,
    }:
        raise RuntimeError("Prisma runtime compatibility policy is invalid.")


def verify_alembic_graph(config_path: Path = ALEMBIC_CONFIG) -> None:
    directory = ScriptDirectory.from_config(Config(str(config_path)))
    revisions = list(directory.walk_revisions())
    if directory.get_heads() != [BASELINE_REVISION]:
        raise RuntimeError("Step 3E-A requires the baseline to remain the only Alembic head.")
    if directory.get_bases() != [BASELINE_REVISION]:
        raise RuntimeError("The inherited Prisma baseline must remain the Alembic base.")
    if len(revisions) != 1 or revisions[0].revision != BASELINE_REVISION:
        raise RuntimeError("Step 3E-A must not introduce a schema-changing Alembic revision.")


def verify_package_scripts(package_json: Path = PACKAGE_JSON) -> None:
    package = json.loads(package_json.read_text(encoding="utf-8"))
    scripts = package.get("scripts", {})
    if scripts.get("db:migrate") != "node scripts/prisma-migrations-frozen.mjs":
        raise RuntimeError("db:migrate must fail closed after the Prisma migration freeze.")
    if scripts.get("db:deploy") != "prisma migrate deploy":
        raise RuntimeError("Step 3E-A must preserve the existing deployment alias until activation.")
    if scripts.get("db:prisma:deploy:legacy") != "prisma migrate deploy":
        raise RuntimeError("Frozen Prisma archive verification command is missing.")

    expected_alembic = {
        "db:alembic:check": "cd backend/python && uv run python scripts/database_migrate.py check",
        "db:alembic:upgrade": "cd backend/python && uv run python scripts/database_migrate.py upgrade",
        "db:alembic:bootstrap": "cd backend/python && uv run python scripts/database_migrate.py bootstrap",
    }
    for name, command in expected_alembic.items():
        if scripts.get(name) != command:
            raise RuntimeError(f"Missing prepared Alembic script: {name}.")


def verify_runtime_ddl(app_root: Path | None = None) -> None:
    root = app_root or BACKEND_ROOT / "app"
    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_RUNTIME_PATTERNS:
            if pattern in source:
                relative = path.relative_to(REPOSITORY_ROOT)
                raise RuntimeError(f"Forbidden runtime migration operation {pattern} in {relative}.")


def verify_workflow_policy(workflows_root: Path | None = None) -> None:
    root = workflows_root or REPOSITORY_ROOT / ".github" / "workflows"
    forbidden = (
        "prisma migrate dev",
        "prisma migrate reset",
        "prisma db push",
    )
    for path in sorted(root.glob("*.y*ml")):
        source = path.read_text(encoding="utf-8")
        for command in forbidden:
            if command in source:
                relative = path.relative_to(REPOSITORY_ROOT)
                raise RuntimeError(f"Forbidden Prisma migration command {command} in {relative}.")
        if "prisma migrate deploy" in source:
            relative = path.relative_to(REPOSITORY_ROOT)
            raise RuntimeError(
                "Workflows must invoke the named frozen archive verification script instead of "
                f"raw prisma migrate deploy: {relative}."
            )


def verify_policy() -> PrismaArchiveState:
    state = archive_state()
    verify_archive_manifest(state)
    verify_ownership_manifest(state)
    verify_alembic_graph()
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
        "Migration policy verification passed; Prisma history is frozen and Alembic cutover "
        "preparation is ready."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
