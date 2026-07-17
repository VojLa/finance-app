from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_CONFIG = BACKEND_ROOT / "alembic.ini"
BASELINE_REVISION = "3d0001base"


def test_alembic_configuration_uses_local_migration_directory() -> None:
    config = Config(str(ALEMBIC_CONFIG))

    script_location = Path(config.get_main_option("script_location"))
    assert script_location.resolve() == (BACKEND_ROOT / "migrations").resolve()
    assert not config.get_main_option("sqlalchemy.url")


def test_alembic_revision_graph_contains_only_the_prisma_baseline() -> None:
    directory = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG)))
    revisions = list(directory.walk_revisions())

    assert directory.get_heads() == [BASELINE_REVISION]
    assert directory.get_bases() == [BASELINE_REVISION]
    assert len(revisions) == 1
    assert revisions[0].revision == BASELINE_REVISION
    assert revisions[0].down_revision is None
    assert revisions[0].branch_labels == {"prisma_baseline"}
