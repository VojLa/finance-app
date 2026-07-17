from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.migration_policy import (
    BASELINE_REVISION,
    archive_state,
    render_archive_manifest,
    verify_archive_manifest,
    verify_package_scripts,
    verify_policy,
    verify_runtime_ddl,
    verify_workflow_policy,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_MANIFEST = BACKEND_ROOT / "database" / "prisma_migration_archive.toml"


def create_archive(root: Path) -> Path:
    migrations = root / "prisma" / "migrations"
    (migrations / "20260101000000_init").mkdir(parents=True)
    (migrations / "20260101000000_init" / "migration.sql").write_text(
        "CREATE TABLE test ();\n",
        encoding="utf-8",
    )
    (migrations / "migration_lock.toml").write_text(
        'provider = "postgresql"\n',
        encoding="utf-8",
    )
    return migrations


def test_archive_hash_is_deterministic_and_content_sensitive(tmp_path: Path) -> None:
    migrations = create_archive(tmp_path)
    first = archive_state(tmp_path, migrations)
    second = archive_state(tmp_path, migrations)

    assert first == second
    assert first.file_count == 2
    assert first.migration_count == 1
    assert first.last_migration == "20260101000000_init"
    assert len(first.aggregate_sha256) == 64

    migration = migrations / "20260101000000_init" / "migration.sql"
    migration.write_text("CREATE TABLE changed ();\n", encoding="utf-8")
    changed = archive_state(tmp_path, migrations)

    assert changed.aggregate_sha256 != first.aggregate_sha256


def test_archive_manifest_verifier_detects_drift(tmp_path: Path) -> None:
    migrations = create_archive(tmp_path)
    state = archive_state(tmp_path, migrations)
    manifest = tmp_path / "archive.toml"
    manifest.write_text(render_archive_manifest(state), encoding="utf-8")

    verify_archive_manifest(state, manifest)

    manifest.write_text(
        render_archive_manifest(state).replace(state.aggregate_sha256, "0" * 64),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="aggregate_sha256"):
        verify_archive_manifest(state, manifest)


def test_repository_migration_policy_is_ready() -> None:
    state = verify_policy()

    assert state.last_migration
    assert state.migration_count >= 1
    assert ARCHIVE_MANIFEST.is_file()


def test_package_scripts_freeze_prisma_migration_creation(tmp_path: Path) -> None:
    package = tmp_path / "package.json"
    package.write_text(
        json.dumps(
            {
                "scripts": {
                    "db:migrate": "node scripts/prisma-migrations-frozen.mjs",
                    "db:deploy": "prisma migrate deploy",
                    "db:prisma:deploy:legacy": "prisma migrate deploy",
                    "db:alembic:check": (
                        "cd backend/python && uv run python scripts/database_migrate.py check"
                    ),
                    "db:alembic:upgrade": (
                        "cd backend/python && uv run python scripts/database_migrate.py upgrade"
                    ),
                    "db:alembic:bootstrap": (
                        "cd backend/python && uv run python scripts/database_migrate.py bootstrap"
                    ),
                }
            }
        ),
        encoding="utf-8",
    )

    verify_package_scripts(package)

    data = json.loads(package.read_text(encoding="utf-8"))
    data["scripts"]["db:migrate"] = "prisma migrate dev"
    package.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RuntimeError, match="db:migrate"):
        verify_package_scripts(package)


def test_runtime_ddl_policy_rejects_automatic_migrations(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    (app / "safe.py").write_text("VALUE = 1\n", encoding="utf-8")
    verify_runtime_ddl(app)

    (app / "unsafe.py").write_text("Base.metadata.create_all(engine)\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="metadata.create_all"):
        verify_runtime_ddl(app)


def test_workflow_policy_allows_only_named_legacy_archive_command(tmp_path: Path) -> None:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    workflow = workflows / "database.yml"
    workflow.write_text("run: npm run db:prisma:deploy:legacy\n", encoding="utf-8")
    verify_workflow_policy(workflows)

    workflow.write_text("run: npx prisma migrate deploy\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="raw prisma migrate deploy"):
        verify_workflow_policy(workflows)


def test_policy_baseline_revision_is_stable() -> None:
    assert BASELINE_REVISION == "3d0001base"
