from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
BASELINE_REVISION = "3d0001base"
CUTOVER_REVISION = "3e0001cutover"
FIRST_SCHEMA_REVISION = "3f0001acctnote"
LIABILITY_REVISION = "3g0001liabbal"
TWELVE_DATA_REVISION = "3h0001twdata"
DAILY_BASELINE_REVISION = "3i0001d1base"
HEAD_REVISION = "3j0001twfx"
MULTI_CURRENCY_COST_BASIS_REVISION = "3k0001mcost"


def test_alembic_configuration_uses_local_migration_directory() -> None:
    config = Config(str(ALEMBIC_CONFIG))

    configured_location = config.get_main_option("script_location")
    assert configured_location is not None
    script_location = Path(configured_location)
    assert script_location.resolve() == (BACKEND_ROOT / "migrations").resolve()
    assert not config.get_main_option("sqlalchemy.url")


def test_alembic_revision_graph_contains_direct_fx_migration() -> None:
    directory = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG)))
    revisions = list(directory.walk_revisions())
    by_revision = {revision.revision: revision for revision in revisions}

    assert directory.get_heads() == [MULTI_CURRENCY_COST_BASIS_REVISION]
    assert directory.get_bases() == [BASELINE_REVISION]
    assert len(revisions) == 8
    assert by_revision[BASELINE_REVISION].down_revision is None
    assert by_revision[BASELINE_REVISION].branch_labels == {"prisma_baseline"}
    assert by_revision[CUTOVER_REVISION].down_revision == BASELINE_REVISION
    assert by_revision[FIRST_SCHEMA_REVISION].down_revision == CUTOVER_REVISION
    assert by_revision[LIABILITY_REVISION].down_revision == FIRST_SCHEMA_REVISION
    assert by_revision[TWELVE_DATA_REVISION].down_revision == LIABILITY_REVISION
    assert by_revision[DAILY_BASELINE_REVISION].down_revision == TWELVE_DATA_REVISION
    assert by_revision[HEAD_REVISION].down_revision == DAILY_BASELINE_REVISION
    assert by_revision[MULTI_CURRENCY_COST_BASIS_REVISION].down_revision == HEAD_REVISION
