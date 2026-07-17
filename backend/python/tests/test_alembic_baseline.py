from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

from scripts.alembic_baseline import (
    BASELINE_REVISION,
    DatabaseState,
    verify_database_state,
    verify_manifest,
    verify_revision_graph,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REVISION_PATH = BACKEND_ROOT / "migrations" / "versions" / "3d0001base_prisma_schema_baseline.py"
OWNERSHIP_PATH = BACKEND_ROOT / "database" / "schema_ownership.toml"


def load_revision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prisma_schema_baseline", REVISION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_baseline_upgrade_is_noop_and_downgrade_is_blocked() -> None:
    revision = load_revision()
    source = REVISION_PATH.read_text(encoding="utf-8")

    assert revision.revision == BASELINE_REVISION
    assert revision.down_revision is None
    assert revision.upgrade() is None
    assert "op." not in source
    assert "create_table" not in source
    assert "drop_table" not in source

    with pytest.raises(RuntimeError, match="cannot be downgraded automatically"):
        revision.downgrade()


def test_baseline_manifest_keeps_prisma_as_owner_during_cutover_preparation() -> None:
    manifest = tomllib.loads(OWNERSHIP_PATH.read_text(encoding="utf-8"))
    baseline = manifest["alembic_baseline"]
    cutover = manifest["cutover"]

    assert manifest["schema_version"] == 5
    assert manifest["current_migration_owner"] == "prisma"
    assert manifest["cutover_status"] == "ready"
    assert cutover["phase"] == "prepared"
    assert cutover["production_activation_allowed"] is False
    assert baseline["state"] == "verified_not_owner"
    assert baseline["revision"] == BASELINE_REVISION
    assert baseline["upgrade_is_noop"] is True
    assert baseline["downgrade_supported"] is False
    assert baseline["version_table"] == "alembic_version"
    assert baseline["version_table_schema"] == "public"

    verify_manifest()
    verify_revision_graph()


def test_database_state_accepts_unstamped_or_baseline_stamped_database() -> None:
    verify_database_state(DatabaseState(30, 27, ()))
    verify_database_state(DatabaseState(30, 27, (BASELINE_REVISION,)))


def test_database_state_rejects_schema_or_revision_drift() -> None:
    with pytest.raises(RuntimeError, match="Expected 30 application tables"):
        verify_database_state(DatabaseState(29, 27, ()))
    with pytest.raises(RuntimeError, match="Expected 27 enums"):
        verify_database_state(DatabaseState(30, 26, ()))
    with pytest.raises(RuntimeError, match="unknown Alembic revisions"):
        verify_database_state(DatabaseState(30, 27, ("unknown",)))
