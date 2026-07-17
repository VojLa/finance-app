from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    source = path.read_text(encoding="utf-8")
    if source.count(old) != 1:
        raise RuntimeError(f"Expected exactly one match in {path}: {old[:80]!r}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8", newline="\n")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


# Prisma remains a runtime compatibility mirror; no Prisma migration is created.
replace_once(
    REPOSITORY_ROOT / "prisma" / "schema.prisma",
    "  color               String?\n  isArchived          Boolean              @default(false)\n",
    "  color               String?\n  notes               String?\n  isArchived          Boolean              @default(false)\n",
)

# Revision-aware schema artifact support.
database_schema = BACKEND_ROOT / "scripts" / "database_schema.py"
replace_once(database_schema, "import sys\n", "import sys\nimport tomllib\n")
replace_once(
    database_schema,
    "DEFAULT_CHECKSUM = PROJECT_ROOT / \"database\" / \"baseline\" / \"schema.sha256\"\n",
    "DEFAULT_CHECKSUM = PROJECT_ROOT / \"database\" / \"baseline\" / \"schema.sha256\"\n"
    "DEFAULT_REGISTRY = PROJECT_ROOT / \"database\" / \"schema_revisions.toml\"\n",
)
replace_once(
    database_schema,
    "def write_baseline(schema: str, baseline_path: Path, checksum_path: Path) -> None:\n",
    "def schema_artifact_paths(\n"
    "    revision: str | None,\n"
    "    registry_path: Path = DEFAULT_REGISTRY,\n"
    ") -> tuple[Path, Path]:\n"
    "    if revision is None:\n"
    "        return DEFAULT_BASELINE, DEFAULT_CHECKSUM\n"
    "    with registry_path.open(\"rb\") as source:\n"
    "        registry = tomllib.load(source)\n"
    "    if registry.get(\"version\") != 1:\n"
    "        raise RuntimeError(\"Schema revision registry version must be 1.\")\n"
    "    revisions = registry.get(\"revisions\")\n"
    "    if not isinstance(revisions, dict):\n"
    "        raise RuntimeError(\"Schema revision registry is missing revisions.\")\n"
    "    current = revision\n"
    "    visited: set[str] = set()\n"
    "    while True:\n"
    "        if current in visited:\n"
    "            raise RuntimeError(\"Schema revision registry contains an inheritance cycle.\")\n"
    "        visited.add(current)\n"
    "        entry = revisions.get(current)\n"
    "        if not isinstance(entry, dict):\n"
    "            raise RuntimeError(f\"Schema artifact is not registered for revision {current}.\")\n"
    "        inherited = entry.get(\"inherits_schema_from\")\n"
    "        if isinstance(inherited, str):\n"
    "            current = inherited\n"
    "            continue\n"
    "        schema_source = entry.get(\"schema_source\")\n"
    "        checksum_source = entry.get(\"checksum_source\")\n"
    "        if not isinstance(schema_source, str) or not isinstance(checksum_source, str):\n"
    "            raise RuntimeError(f\"Revision {current} has no concrete schema artifact.\")\n"
    "        return PROJECT_ROOT / schema_source, PROJECT_ROOT / checksum_source\n"
    "\n"
    "\n"
    "def verify_live_schema(\n"
    "    database_url: str,\n"
    "    pg_dump: str,\n"
    "    revision: str | None,\n"
    "    registry_path: Path = DEFAULT_REGISTRY,\n"
    ") -> None:\n"
    "    schema_path, checksum_path = schema_artifact_paths(revision, registry_path)\n"
    "    schema = dump_schema(database_url, pg_dump)\n"
    "    if check_baseline(schema, schema_path, checksum_path) != 0:\n"
    "        label = revision or \"inherited baseline\"\n"
    "        raise RuntimeError(f\"Live PostgreSQL schema does not match revision {label}.\")\n"
    "\n"
    "\n"
    "def write_baseline(schema: str, baseline_path: Path, checksum_path: Path) -> None:\n",
)
replace_once(
    database_schema,
    "    parser.add_argument(\"--baseline\", type=Path, default=DEFAULT_BASELINE)\n"
    "    parser.add_argument(\"--checksum\", type=Path, default=DEFAULT_CHECKSUM)\n",
    "    parser.add_argument(\"--baseline\", type=Path, default=None)\n"
    "    parser.add_argument(\"--checksum\", type=Path, default=None)\n"
    "    parser.add_argument(\"--revision\", default=None)\n"
    "    parser.add_argument(\"--registry\", type=Path, default=DEFAULT_REGISTRY)\n",
)
replace_once(
    database_schema,
    "    if args.write:\n"
    "        write_baseline(schema, args.baseline, args.checksum)\n"
    "        print(f\"Wrote database baseline to {args.baseline}.\")\n"
    "        return 0\n"
    "\n"
    "    return check_baseline(schema, args.baseline, args.checksum)\n",
    "    registered_schema, registered_checksum = schema_artifact_paths(\n"
    "        args.revision, args.registry\n"
    "    )\n"
    "    baseline_path = args.baseline or registered_schema\n"
    "    checksum_path = args.checksum or registered_checksum\n"
    "    if args.write:\n"
    "        write_baseline(schema, baseline_path, checksum_path)\n"
    "        print(f\"Wrote database schema artifact to {baseline_path}.\")\n"
    "        return 0\n"
    "\n"
    "    return check_baseline(schema, baseline_path, checksum_path)\n",
)

# Baseline verification now understands inherited and current-head schemas.
alembic_baseline = BACKEND_ROOT / "scripts" / "alembic_baseline.py"
replace_once(
    alembic_baseline,
    'CUTOVER_REVISION = "3e0001cutover"\n',
    'CUTOVER_REVISION = "3e0001cutover"\nHEAD_REVISION = "3f0001acctnote"\n',
)
replace_once(
    alembic_baseline,
    "    if len(revisions) != 2:\n"
    "        raise RuntimeError(f\"Expected exactly two Alembic revisions, found {len(revisions)}.\")\n"
    "    if heads != [CUTOVER_REVISION]:\n"
    "        raise RuntimeError(f\"Expected Alembic head {CUTOVER_REVISION}, found {heads}.\")\n",
    "    if len(revisions) != 3:\n"
    "        raise RuntimeError(f\"Expected exactly three Alembic revisions, found {len(revisions)}.\")\n"
    "    if heads != [HEAD_REVISION]:\n"
    "        raise RuntimeError(f\"Expected Alembic head {HEAD_REVISION}, found {heads}.\")\n",
)
replace_once(
    alembic_baseline,
    "    cutover = by_revision.get(CUTOVER_REVISION)\n"
    "    if baseline is None or baseline.down_revision is not None:\n"
    "        raise RuntimeError(\"The Alembic baseline revision graph is invalid.\")\n"
    "    if cutover is None or cutover.down_revision != BASELINE_REVISION:\n"
    "        raise RuntimeError(\"The Alembic ownership cutover revision graph is invalid.\")\n",
    "    cutover = by_revision.get(CUTOVER_REVISION)\n"
    "    head = by_revision.get(HEAD_REVISION)\n"
    "    if baseline is None or baseline.down_revision is not None:\n"
    "        raise RuntimeError(\"The Alembic baseline revision graph is invalid.\")\n"
    "    if cutover is None or cutover.down_revision != BASELINE_REVISION:\n"
    "        raise RuntimeError(\"The Alembic ownership cutover revision graph is invalid.\")\n"
    "    if head is None or head.down_revision != CUTOVER_REVISION:\n"
    "        raise RuntimeError(\"The first Alembic schema revision must follow the cutover marker.\")\n",
)
replace_once(
    alembic_baseline,
    "    if manifest.get(\"schema_version\") != 6:\n"
    "        raise RuntimeError(\"Ownership manifest schema_version must be 6 after cutover.\")\n",
    "    if manifest.get(\"schema_version\") != 7:\n"
    "        raise RuntimeError(\"Ownership manifest schema_version must be 7 after the first schema change.\")\n",
)
replace_once(
    alembic_baseline,
    '        "revision_count": 2,\n        "head_count": 1,\n        "head_revision": CUTOVER_REVISION,\n',
    '        "revision_count": 3,\n        "head_count": 1,\n        "head_revision": HEAD_REVISION,\n',
)
replace_once(
    alembic_baseline,
    "    known = {BASELINE_REVISION, CUTOVER_REVISION}\n",
    "    directory = ScriptDirectory.from_config(alembic_config())\n"
    "    known = {revision.revision for revision in directory.walk_revisions()}\n",
)
replace_once(
    alembic_baseline,
    "def verify_sqlalchemy_parity(database_url: str) -> None:\n",
    "def verify_revision_schema(database_url: str, pg_dump: str, revision: str) -> None:\n"
    "    database_schema.verify_live_schema(database_url, pg_dump, revision)\n"
    "\n"
    "\n"
    "def verify_sqlalchemy_parity(database_url: str) -> None:\n",
)
replace_once(
    alembic_baseline,
    "        verify_canonical_baseline(args.database_url, args.pg_dump)\n"
    "        verify_sqlalchemy_parity(args.database_url)\n",
    "        revision = state.version_revisions[0] if state.version_revisions else BASELINE_REVISION\n"
    "        verify_revision_schema(args.database_url, args.pg_dump, revision)\n"
    "        if revision == HEAD_REVISION:\n"
    "            verify_sqlalchemy_parity(args.database_url)\n",
)
replace_once(
    alembic_baseline,
    '    print("Alembic baseline verification passed across the completed ownership cutover.")\n',
    '    print("Alembic schema verification passed for the database revision state.")\n',
)

# The runner verifies the schema corresponding to the database's current revision before upgrade.
database_migrate = BACKEND_ROOT / "scripts" / "database_migrate.py"
replace_once(
    database_migrate,
    'CUTOVER_REVISION = "3e0001cutover"\n',
    'CUTOVER_REVISION = "3e0001cutover"\nHEAD_REVISION = "3f0001acctnote"\n',
)
replace_once(
    database_migrate,
    "    alembic_baseline.verify_canonical_baseline(database_url, pg_dump)\n"
    "    alembic_baseline.verify_sqlalchemy_parity(database_url)\n",
    "    current_revision = state.version_revisions[0]\n"
    "    alembic_baseline.verify_revision_schema(database_url, pg_dump, current_revision)\n"
    "    if require_head:\n"
    "        alembic_baseline.verify_sqlalchemy_parity(database_url)\n",
)
replace_once(
    database_migrate,
    '        f"target={CUTOVER_REVISION} "\n',
    '        f"target={HEAD_REVISION} "\n',
)
replace_once(
    database_migrate,
    "    alembic_baseline.verify_canonical_baseline(database_url, pg_dump)\n"
    "    alembic_baseline.verify_sqlalchemy_parity(database_url)\n"
    "    run_alembic(database_url, \"stamp\", BASELINE_REVISION)\n",
    "    alembic_baseline.verify_canonical_baseline(database_url, pg_dump)\n"
    "    run_alembic(database_url, \"stamp\", BASELINE_REVISION)\n",
)

# Generalize the post-cutover policy for the first and future Alembic schema revisions.
migration_policy = BACKEND_ROOT / "scripts" / "migration_policy.py"
replace_once(
    migration_policy,
    "from alembic.script import ScriptDirectory\n",
    "from alembic.script import ScriptDirectory\n\nfrom scripts import database_schema\n",
)
replace_once(
    migration_policy,
    'CUTOVER_REVISION = "3e0001cutover"\n',
    'CUTOVER_REVISION = "3e0001cutover"\nHEAD_REVISION = "3f0001acctnote"\n'
    'SCHEMA_REGISTRY = BACKEND_ROOT / "database" / "schema_revisions.toml"\n'
    'FIRST_SCHEMA_REVISION_PATH = (\n'
    '    BACKEND_ROOT / "migrations" / "versions" / "3f0001acctnote_add_account_notes.py"\n'
    ')\n'
    'PRISMA_SCHEMA = REPOSITORY_ROOT / "prisma" / "schema.prisma"\n',
)
replace_once(
    migration_policy,
    '        "schema_version": 6,\n',
    '        "schema_version": 7,\n',
)
replace_once(
    migration_policy,
    '        "revision_count": 2,\n        "head_count": 1,\n',
    '        "head_revision": HEAD_REVISION,\n        "revision_count": 3,\n        "head_count": 1,\n',
)
replace_once(
    migration_policy,
    "    prisma_migrations = manifest.get(\"prisma_migrations\")\n",
    "    current_schema = manifest.get(\"current_schema\")\n"
    "    if current_schema != {\n"
    "        \"revision\": HEAD_REVISION,\n"
    "        \"schema_source\": \"database/revisions/3f0001acctnote/schema.sql\",\n"
    "        \"checksum_source\": \"database/revisions/3f0001acctnote/schema.sha256\",\n"
    "    }:\n"
    "        raise RuntimeError(\"Current schema artifact metadata is invalid.\")\n"
    "\n"
    "    prisma_migrations = manifest.get(\"prisma_migrations\")\n",
)
start = migration_policy.read_text(encoding="utf-8").index("def verify_alembic_graph(")
end = migration_policy.read_text(encoding="utf-8").index("def verify_package_scripts(")
source = migration_policy.read_text(encoding="utf-8")
new_graph = '''def verify_alembic_graph(config_path: Path = ALEMBIC_CONFIG) -> None:
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
    if "WHERE \"notes\" IS NOT NULL" not in head_source:
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
        schema_path, checksum_path = database_schema.schema_artifact_paths(
            revision, registry_path
        )
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


'''
migration_policy.write_text(source[:start] + new_graph + source[end:], encoding="utf-8", newline="\n")
replace_once(
    migration_policy,
    "    verify_alembic_graph()\n    verify_package_scripts()\n",
    "    verify_alembic_graph()\n    verify_schema_registry()\n    verify_package_scripts()\n",
)

# Ownership manifest now points at the first real Alembic schema head.
ownership = BACKEND_ROOT / "database" / "schema_ownership.toml"
replace_once(ownership, "schema_version = 6\n", "schema_version = 7\n")
replace_once(
    ownership,
    'revision_count = 2\nhead_count = 1\nhead_revision = "3e0001cutover"\n',
    'revision_count = 3\nhead_count = 1\nhead_revision = "3f0001acctnote"\n',
)
replace_once(
    ownership,
    '[alembic]\nstate = "sole_migration_owner"\nbaseline_revision = "3d0001base"\ncutover_revision = "3e0001cutover"\nrevision_count = 2\nhead_count = 1\n',
    '[alembic]\nstate = "sole_migration_owner"\nbaseline_revision = "3d0001base"\ncutover_revision = "3e0001cutover"\nhead_revision = "3f0001acctnote"\nrevision_count = 3\nhead_count = 1\n\n[current_schema]\nrevision = "3f0001acctnote"\nschema_source = "database/revisions/3f0001acctnote/schema.sql"\nchecksum_source = "database/revisions/3f0001acctnote/schema.sha256"\n',
)
replace_once(
    ownership,
    'verified_against = "prisma_migrated_postgresql_16"\n',
    'verified_against = "alembic_head_postgresql_16"\n',
)

# Static model and policy tests.
replace_once(
    BACKEND_ROOT / "tests" / "test_database_models.py",
    "from sqlalchemy import Numeric\n",
    "from sqlalchemy import Numeric, Text\n",
)
replace_once(
    BACKEND_ROOT / "tests" / "test_database_models.py",
    "def test_all_foreign_keys_target_mapped_tables() -> None:\n",
    "def test_account_notes_column_is_nullable_text() -> None:\n"
    "    column = Base.metadata.tables[\"public.Account\"].c.notes\n"
    "\n"
    "    assert isinstance(column.type, Text)\n"
    "    assert column.nullable is True\n"
    "    assert column.server_default is None\n"
    "\n"
    "\n"
    "def test_all_foreign_keys_target_mapped_tables() -> None:\n",
)
replace_once(
    BACKEND_ROOT / "tests" / "test_sqlalchemy_persistence.py",
    '                        "color": None,\n                        "is_archived": False,\n',
    '                        "color": None,\n                        "notes": "Primary investing account",\n                        "is_archived": False,\n',
)
replace_once(
    BACKEND_ROOT / "tests" / "test_sqlalchemy_persistence.py",
    '                        "color": None,\n                        "is_archived": True,\n',
    '                        "color": None,\n                        "notes": None,\n                        "is_archived": True,\n',
)

write(
    BACKEND_ROOT / "tests" / "test_alembic_configuration.py",
    '''from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
BASELINE_REVISION = "3d0001base"
CUTOVER_REVISION = "3e0001cutover"
HEAD_REVISION = "3f0001acctnote"


def test_alembic_configuration_uses_local_migration_directory() -> None:
    config = Config(str(ALEMBIC_CONFIG))

    configured_location = config.get_main_option("script_location")
    assert configured_location is not None
    script_location = Path(configured_location)
    assert script_location.resolve() == (BACKEND_ROOT / "migrations").resolve()
    assert not config.get_main_option("sqlalchemy.url")


def test_alembic_revision_graph_contains_first_schema_migration() -> None:
    directory = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG)))
    revisions = list(directory.walk_revisions())
    by_revision = {revision.revision: revision for revision in revisions}

    assert directory.get_heads() == [HEAD_REVISION]
    assert directory.get_bases() == [BASELINE_REVISION]
    assert len(revisions) == 3
    assert by_revision[BASELINE_REVISION].down_revision is None
    assert by_revision[BASELINE_REVISION].branch_labels == {"prisma_baseline"}
    assert by_revision[CUTOVER_REVISION].down_revision == BASELINE_REVISION
    assert by_revision[HEAD_REVISION].down_revision == CUTOVER_REVISION
''',
)

write(
    BACKEND_ROOT / "tests" / "test_alembic_baseline.py",
    '''from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

from scripts.alembic_baseline import (
    BASELINE_REVISION,
    CUTOVER_REVISION,
    HEAD_REVISION,
    DatabaseState,
    verify_database_state,
    verify_manifest,
    verify_revision_graph,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = BACKEND_ROOT / "migrations" / "versions" / "3d0001base_prisma_schema_baseline.py"
CUTOVER_PATH = BACKEND_ROOT / "migrations" / "versions" / "3e0001cutover_alembic_ownership.py"
HEAD_PATH = BACKEND_ROOT / "migrations" / "versions" / "3f0001acctnote_add_account_notes.py"
OWNERSHIP_PATH = BACKEND_ROOT / "database" / "schema_ownership.toml"


def load_revision(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_baseline_upgrade_is_noop_and_downgrade_is_blocked() -> None:
    revision = load_revision(BASELINE_PATH, "prisma_schema_baseline")
    source = BASELINE_PATH.read_text(encoding="utf-8")

    assert revision.revision == BASELINE_REVISION
    assert revision.down_revision is None
    assert revision.upgrade() is None
    assert "op." not in source
    with pytest.raises(RuntimeError, match="cannot be downgraded automatically"):
        revision.downgrade()


def test_cutover_marker_is_noop_and_downgrade_is_blocked() -> None:
    revision = load_revision(CUTOVER_PATH, "alembic_ownership_cutover")
    source = CUTOVER_PATH.read_text(encoding="utf-8")

    assert revision.revision == CUTOVER_REVISION
    assert revision.down_revision == BASELINE_REVISION
    assert revision.ownership_cutover is True
    assert revision.prisma_schema_impact == "none"
    assert revision.upgrade() is None
    assert "op." not in source
    with pytest.raises(RuntimeError, match="cannot be downgraded automatically"):
        revision.downgrade()


def test_first_schema_revision_metadata_and_data_loss_guard() -> None:
    revision = load_revision(HEAD_PATH, "account_notes")
    source = HEAD_PATH.read_text(encoding="utf-8")

    assert revision.revision == HEAD_REVISION
    assert revision.down_revision == CUTOVER_REVISION
    assert revision.schema_change is True
    assert revision.schema_change_kind == "add_nullable_column"
    assert revision.affected_tables == ("Account",)
    assert revision.affected_columns == ("Account.notes",)
    assert revision.prisma_schema_impact == "required"
    assert revision.data_migration is False
    assert "op.add_column" in source
    assert "op.drop_column" in source
    assert 'WHERE "notes" IS NOT NULL' in source


def test_manifest_records_first_alembic_schema_head() -> None:
    manifest = tomllib.loads(OWNERSHIP_PATH.read_text(encoding="utf-8"))
    baseline = manifest["alembic_baseline"]
    alembic = manifest["alembic"]

    assert manifest["schema_version"] == 7
    assert manifest["current_migration_owner"] == "alembic"
    assert manifest["cutover_status"] == "completed"
    assert baseline["revision_count"] == 3
    assert baseline["head_revision"] == HEAD_REVISION
    assert alembic["head_revision"] == HEAD_REVISION
    assert alembic["revision_count"] == 3

    verify_manifest()
    verify_revision_graph()


def test_database_state_accepts_all_known_single_head_states() -> None:
    verify_database_state(DatabaseState(30, 27, ()))
    verify_database_state(DatabaseState(30, 27, (BASELINE_REVISION,)))
    verify_database_state(DatabaseState(30, 27, (CUTOVER_REVISION,)))
    verify_database_state(DatabaseState(30, 27, (HEAD_REVISION,)))


def test_database_state_rejects_schema_or_revision_drift() -> None:
    with pytest.raises(RuntimeError, match="Expected 30 application tables"):
        verify_database_state(DatabaseState(29, 27, ()))
    with pytest.raises(RuntimeError, match="Expected 27 enums"):
        verify_database_state(DatabaseState(30, 26, ()))
    with pytest.raises(RuntimeError, match="unknown Alembic revisions"):
        verify_database_state(DatabaseState(30, 27, ("unknown",)))
''',
)

write(
    BACKEND_ROOT / "tests" / "test_database_migrate.py",
    '''from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.alembic_baseline import DatabaseState
from scripts.database_migrate import (
    BASELINE_REVISION,
    CUTOVER_REVISION,
    HEAD_REVISION,
    DEFAULT_ADVISORY_LOCK_KEY,
    run_alembic,
    verify_revision_state,
)


def test_revision_state_requires_explicit_baseline_stamp() -> None:
    with pytest.raises(RuntimeError, match="not stamped"):
        verify_revision_state(DatabaseState(30, 27, ()), require_head=False)


def test_revision_state_rejects_unknown_revision() -> None:
    with pytest.raises(RuntimeError, match="unknown Alembic revisions"):
        verify_revision_state(DatabaseState(30, 27, ("unknown",)), require_head=False)


def test_revision_state_accepts_known_revision_before_upgrade() -> None:
    verify_revision_state(DatabaseState(30, 27, (BASELINE_REVISION,)), require_head=False)
    verify_revision_state(DatabaseState(30, 27, (CUTOVER_REVISION,)), require_head=False)


def test_revision_state_requires_current_schema_head_for_check() -> None:
    with pytest.raises(RuntimeError, match="not at the Alembic head"):
        verify_revision_state(DatabaseState(30, 27, (CUTOVER_REVISION,)), require_head=True)
    verify_revision_state(DatabaseState(30, 27, (HEAD_REVISION,)), require_head=True)


def test_alembic_runner_uses_python_module_and_local_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run_command(
        command: list[str],
        *,
        database_url: str,
    ) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["database_url"] = database_url
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("scripts.database_migrate.run_command", fake_run_command)
    run_alembic("postgresql://localhost/test", "current", "--check-heads")

    command = captured["command"]
    assert isinstance(command, list)
    assert command[1:4] == ["-m", "alembic", "-c"]
    assert Path(command[4]).name == "alembic.ini"
    assert command[-2:] == ["current", "--check-heads"]
    assert captured["database_url"] == "postgresql://localhost/test"


def test_advisory_lock_key_is_stable_and_signed_bigint_safe() -> None:
    assert DEFAULT_ADVISORY_LOCK_KEY == 731845204311764461
    assert -(2**63) <= DEFAULT_ADVISORY_LOCK_KEY < 2**63
''',
)

# Update schema and migration policy assertions while retaining existing broad coverage.
test_database_schema = BACKEND_ROOT / "tests" / "test_database_schema.py"
replace_once(test_database_schema, "import tomllib\n", "import tomllib\n")
replace_once(test_database_schema, "CHECKSUM_PATH = BACKEND_ROOT / \"database\" / \"baseline\" / \"schema.sha256\"\n", "CHECKSUM_PATH = BACKEND_ROOT / \"database\" / \"baseline\" / \"schema.sha256\"\nSCHEMA_REGISTRY_PATH = BACKEND_ROOT / \"database\" / \"schema_revisions.toml\"\n")
replace_once(test_database_schema, '    assert manifest["schema_version"] == 6\n', '    assert manifest["schema_version"] == 7\n')
replace_once(
    test_database_schema,
    '        "cutover_revision": "3e0001cutover",\n        "revision_count": 2,\n        "head_count": 1,\n',
    '        "cutover_revision": "3e0001cutover",\n        "head_revision": "3f0001acctnote",\n        "revision_count": 3,\n        "head_count": 1,\n',
)
replace_once(
    test_database_schema,
    '        "verified_against": "prisma_migrated_postgresql_16",\n',
    '        "verified_against": "alembic_head_postgresql_16",\n',
)
replace_once(
    test_database_schema,
    "def test_normalize_database_url_removes_prisma_schema_parameter() -> None:\n",
    "def test_schema_revision_registry_preserves_inherited_baseline_and_head_snapshot() -> None:\n"
    "    with SCHEMA_REGISTRY_PATH.open(\"rb\") as source:\n"
    "        registry = tomllib.load(source)\n"
    "\n"
    "    assert registry[\"version\"] == 1\n"
    "    assert registry[\"revisions\"][\"3e0001cutover\"][\"inherits_schema_from\"] == \"3d0001base\"\n"
    "    assert registry[\"revisions\"][\"3f0001acctnote\"][\"schema_change\"] is True\n"
    "\n"
    "\n"
    "def test_normalize_database_url_removes_prisma_schema_parameter() -> None:\n",
)

test_migration_policy = BACKEND_ROOT / "tests" / "test_migration_policy.py"
replace_once(
    test_migration_policy,
    "    CUTOVER_REVISION,\n",
    "    CUTOVER_REVISION,\n    HEAD_REVISION,\n",
)
replace_once(
    test_migration_policy,
    "    verify_runtime_ddl,\n",
    "    verify_runtime_ddl,\n    verify_schema_registry,\n",
)
replace_once(
    test_migration_policy,
    "def test_repository_migration_policy_is_completed() -> None:\n",
    "def test_repository_schema_registry_is_complete() -> None:\n"
    "    verify_schema_registry()\n"
    "\n"
    "\n"
    "def test_repository_migration_policy_is_completed() -> None:\n",
)
replace_once(
    test_migration_policy,
    '    assert CUTOVER_REVISION == "3e0001cutover"\n',
    '    assert CUTOVER_REVISION == "3e0001cutover"\n    assert HEAD_REVISION == "3f0001acctnote"\n',
)

# Full lifecycle integration: upgrade, protected downgrade, clean downgrade, and re-upgrade.
write(
    BACKEND_ROOT / "tests" / "test_alembic_integration.py",
    '''from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import AccountModel, AccountType, UserModel
from app.db.url import normalize_database_url
from scripts.alembic_baseline import BASELINE_REVISION, CUTOVER_REVISION, HEAD_REVISION

DATABASE_URL = os.getenv("DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
TEST_USER_ID = "alembic-first-migration-user"
TEST_ACCOUNT_ID = "alembic-first-migration-account"


def invoke_command(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    assert DATABASE_URL is not None
    environment["DATABASE_URL"] = DATABASE_URL
    return subprocess.run(
        [sys.executable, *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def run_command(*arguments: str) -> subprocess.CompletedProcess[str]:
    result = invoke_command(*arguments)
    assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_first_alembic_schema_migration_lifecycle() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime(2026, 7, 17, 12, 0, 0)

    try:
        async with engine.begin() as connection:
            await connection.execute(delete(AccountModel).where(AccountModel.id == TEST_ACCOUNT_ID))
            await connection.execute(delete(UserModel).where(UserModel.id == TEST_USER_ID))
            await connection.execute(
                insert(UserModel).values(
                    id=TEST_USER_ID,
                    email="alembic-first@example.test",
                    name="Alembic First Migration",
                    password_hash=None,
                    base_currency="CZK",
                    created_at=now,
                    updated_at=now,
                )
            )
            # The inherited database does not have Account.notes yet, so insert only legacy columns.
            await connection.execute(
                text(
                    'INSERT INTO "public"."Account" '
                    '("id", "name", "type", "currency", "color", "isArchived", '
                    '"archivedAt", "createdAt", "updatedAt") '
                    'VALUES (:id, :name, CAST(:type AS "AccountType"), :currency, NULL, false, '
                    'NULL, :created_at, :updated_at)'
                ),
                {
                    "id": TEST_ACCOUNT_ID,
                    "name": "First Alembic Account",
                    "type": AccountType.bank.value,
                    "currency": "CZK",
                    "created_at": now,
                    "updated_at": now,
                },
            )

        verification = run_command("scripts/alembic_baseline.py", "--verify")
        assert "revision state" in verification.stdout

        run_command(
            "-m", "alembic", "-c", str(ALEMBIC_CONFIG), "stamp", BASELINE_REVISION
        )
        run_command("scripts/database_migrate.py", "upgrade")

        async with engine.begin() as connection:
            notes = await connection.scalar(
                text('SELECT "notes" FROM "public"."Account" WHERE "id" = :id'),
                {"id": TEST_ACCOUNT_ID},
            )
            version = await connection.scalar(
                text('SELECT "version_num" FROM public.alembic_version')
            )
            assert notes is None
            assert version == HEAD_REVISION
            await connection.execute(
                text('UPDATE "public"."Account" SET "notes" = :notes WHERE "id" = :id'),
                {"notes": "Preserve this note", "id": TEST_ACCOUNT_ID},
            )

        blocked = invoke_command(
            "-m", "alembic", "-c", str(ALEMBIC_CONFIG), "downgrade", CUTOVER_REVISION
        )
        assert blocked.returncode != 0
        assert "Cannot remove Account.notes" in blocked.stdout + blocked.stderr

        async with engine.begin() as connection:
            preserved = await connection.scalar(
                text('SELECT "notes" FROM "public"."Account" WHERE "id" = :id'),
                {"id": TEST_ACCOUNT_ID},
            )
            assert preserved == "Preserve this note"
            await connection.execute(
                text('UPDATE "public"."Account" SET "notes" = NULL WHERE "id" = :id'),
                {"id": TEST_ACCOUNT_ID},
            )

        run_command(
            "-m", "alembic", "-c", str(ALEMBIC_CONFIG), "downgrade", CUTOVER_REVISION
        )
        async with engine.connect() as connection:
            column_exists = await connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'Account' "
                    "AND column_name = 'notes')"
                )
            )
            assert column_exists is False

        run_command("scripts/database_migrate.py", "upgrade")
        run_command(
            "-m", "alembic", "-c", str(ALEMBIC_CONFIG), "current", "--check-heads"
        )
        check = run_command("-m", "alembic", "-c", str(ALEMBIC_CONFIG), "check")
        assert "No new upgrade operations detected" in check.stdout + check.stderr

        async with engine.connect() as connection:
            account_name = await connection.scalar(
                select(AccountModel.name).where(AccountModel.id == TEST_ACCOUNT_ID)
            )
            notes = await connection.scalar(
                select(AccountModel.notes).where(AccountModel.id == TEST_ACCOUNT_ID)
            )
            assert account_name == "First Alembic Account"
            assert notes is None
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(AccountModel).where(AccountModel.id == TEST_ACCOUNT_ID))
            await connection.execute(delete(UserModel).where(UserModel.id == TEST_USER_ID))
        await engine.dispose()
''',
)

# Database workflow: verify inherited baseline before upgrade, current artifact after upgrade.
write(
    REPOSITORY_ROOT / ".github" / "workflows" / "database-schema.yml",
    '''name: Database Schema

on:
  pull_request:
    paths:
      - "prisma/**"
      - "package.json"
      - "package-lock.json"
      - "scripts/prisma-migrations-frozen.mjs"
      - "scripts/prisma-archive-verify.mjs"
      - "backend/python/alembic.ini"
      - "backend/python/migrations/**"
      - "backend/python/app/db/**"
      - "backend/python/app/lifespan.py"
      - "backend/python/app/modules/portfolio/**"
      - "backend/python/database/**"
      - "backend/python/pyproject.toml"
      - "backend/python/scripts/**"
      - "backend/python/tests/**"
      - "backend/python/uv.lock"
      - ".github/workflows/database-schema.yml"
  push:
    branches:
      - main
    paths:
      - "prisma/**"
      - "package.json"
      - "package-lock.json"
      - "scripts/prisma-migrations-frozen.mjs"
      - "scripts/prisma-archive-verify.mjs"
      - "backend/python/alembic.ini"
      - "backend/python/migrations/**"
      - "backend/python/app/db/**"
      - "backend/python/app/lifespan.py"
      - "backend/python/app/modules/portfolio/**"
      - "backend/python/database/**"
      - "backend/python/pyproject.toml"
      - "backend/python/scripts/**"
      - "backend/python/tests/**"
      - "backend/python/uv.lock"
      - ".github/workflows/database-schema.yml"

permissions:
  contents: read

jobs:
  verify-schema:
    name: Verify first Alembic-owned schema migration
    runs-on: ubuntu-24.04

    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: finance_app
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U postgres -d finance_app"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10

    env:
      DATABASE_URL: postgresql://postgres:postgres@localhost:5432/finance_app
      PGPASSWORD: postgres

    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Node.js
        uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: npm

      - name: Install Node dependencies
        run: npm ci

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version-file: backend/python/.python-version

      - name: Set up uv
        uses: astral-sh/setup-uv@v6
        with:
          enable-cache: true
          cache-dependency-glob: backend/python/uv.lock

      - name: Install backend dependencies
        working-directory: backend/python
        run: uv sync --frozen --extra dev

      - name: Install PostgreSQL 16 client
        run: |
          sudo apt-get update
          sudo apt-get install --yes postgresql-client-16

      - name: Apply frozen Prisma archive for historical verification
        env:
          ALLOW_FROZEN_PRISMA_ARCHIVE_DEPLOY: "1"
        run: npm run db:prisma:archive:verify

      - name: Verify Prisma runtime compatibility tooling
        run: |
          npm run db:prisma:validate
          npm run db:prisma:generate

      - name: Enforce Alembic migration and schema artifact policy
        working-directory: backend/python
        run: uv run python scripts/migration_policy.py --check

      - name: Verify inherited canonical schema before the first real migration
        working-directory: backend/python
        run: |
          uv run python scripts/database_schema.py --check --revision 3d0001base
          uv run python scripts/alembic_baseline.py --verify

      - name: Run static metadata and migration tests
        working-directory: backend/python
        run: >-
          uv run pytest
          tests/test_database_schema.py
          tests/test_database_models.py
          tests/test_database_url.py
          tests/test_sqlalchemy_schema.py
          tests/test_alembic_configuration.py
          tests/test_alembic_baseline.py
          tests/test_migration_policy.py
          tests/test_database_migrate.py

      - name: Verify first migration lifecycle and protected downgrade
        working-directory: backend/python
        run: uv run pytest tests/test_alembic_integration.py -v

      - name: Verify head persistence and live metadata parity
        working-directory: backend/python
        run: >-
          uv run pytest
          tests/test_sqlalchemy_schema_parity.py
          tests/test_sqlalchemy_persistence.py
          -v

      - name: Verify migration runner and advisory lock
        working-directory: backend/python
        run: |
          uv run pytest tests/test_database_migrate_integration.py -v
          uv run python scripts/database_migrate.py check
          uv run python scripts/database_migrate.py upgrade

      - name: Verify current head schema artifact
        working-directory: backend/python
        run: |
          uv run alembic -c alembic.ini current --check-heads
          uv run alembic -c alembic.ini check
          uv run python scripts/database_schema.py --check --revision 3f0001acctnote
          uv run python scripts/sqlalchemy_schema.py --check
          uv run python scripts/alembic_baseline.py --verify

      - name: Verify clean bootstrap through all Alembic revisions
        working-directory: backend/python
        env:
          BOOTSTRAP_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/finance_app_canonical_bootstrap
        run: |
          createdb --host localhost --username postgres finance_app_canonical_bootstrap
          export DATABASE_URL="$BOOTSTRAP_DATABASE_URL"
          uv run python scripts/database_migrate.py bootstrap
          uv run python scripts/database_migrate.py check
          uv run python scripts/database_schema.py --check --revision 3f0001acctnote
          uv run python scripts/sqlalchemy_schema.py --check
''',
)

# Documentation records the actual first migration and immutable inherited baseline.
for relative in (
    Path("database/README.md"),
    Path("migrations/README.md"),
    Path("app/db/README.md"),
):
    path = BACKEND_ROOT / relative
    source = path.read_text(encoding="utf-8")
    if "3f0001acctnote" not in source:
        source += (
            "\n## First Alembic-owned schema change\n\n"
            "Revision `3f0001acctnote` adds nullable `Account.notes` as the first physical "
            "schema change owned by Alembic. The inherited baseline remains immutable; the "
            "current head is verified through `database/schema_revisions.toml` and the "
            "revision-specific schema artifact.\n"
        )
        path.write_text(source, encoding="utf-8", newline="\n")

print("Step 3F source changes staged.")
