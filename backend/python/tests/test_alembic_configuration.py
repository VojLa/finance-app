from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
BASELINE_REVISION = "3d0001base"
CUTOVER_REVISION = "3e0001cutover"


def test_alembic_configuration_uses_local_migration_directory() -> None:
    config = Config(str(ALEMBIC_CONFIG))

    configured_location = config.get_main_option("script_location")
    assert configured_location is not None
    script_location = Path(configured_location)
    assert script_location.resolve() == (BACKEND_ROOT / "migrations").resolve()
    assert not config.get_main_option("sqlalchemy.url")


def test_alembic_revision_graph_contains_baseline_and_cutover_marker() -> None:
    directory = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG)))
    revisions = list(directory.walk_revisions())
    by_revision = {revision.revision: revision for revision in revisions}

    assert directory.get_heads() == [CUTOVER_REVISION]
    assert directory.get_bases() == [BASELINE_REVISION]
    assert len(revisions) == 2
    assert by_revision[BASELINE_REVISION].down_revision is None
    assert by_revision[BASELINE_REVISION].branch_labels == {"prisma_baseline"}
    assert by_revision[CUTOVER_REVISION].down_revision == BASELINE_REVISION
