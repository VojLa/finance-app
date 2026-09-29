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
ANYCOIN_TRANSFER_VALUATION_REVISION = "400001anycoinvaluation"
TEMPORAL_SERIES_REVISION = "410001serieslinks"


def test_alembic_configuration_uses_local_migration_directory() -> None:
    config = Config(str(ALEMBIC_CONFIG))

    configured_location = config.get_main_option("script_location")
    assert configured_location is not None
    script_location = Path(configured_location)
    assert script_location.resolve() == (BACKEND_ROOT / "migrations").resolve()
    assert not config.get_main_option("sqlalchemy.url")


def test_alembic_revision_graph_contains_current_snapshot_generation_head() -> None:
    directory = ScriptDirectory.from_config(Config(str(ALEMBIC_CONFIG)))
    revisions = list(directory.walk_revisions())
    by_revision = {revision.revision: revision for revision in revisions}

    assert directory.get_heads() == [TEMPORAL_SERIES_REVISION]
    assert directory.get_bases() == [BASELINE_REVISION]
    assert len(revisions) == 26
    assert by_revision[BASELINE_REVISION].down_revision is None
    assert by_revision[BASELINE_REVISION].branch_labels == {"prisma_baseline"}
    assert by_revision[CUTOVER_REVISION].down_revision == BASELINE_REVISION
    assert by_revision[FIRST_SCHEMA_REVISION].down_revision == CUTOVER_REVISION
    assert by_revision[LIABILITY_REVISION].down_revision == FIRST_SCHEMA_REVISION
    assert by_revision[TWELVE_DATA_REVISION].down_revision == LIABILITY_REVISION
    assert by_revision[DAILY_BASELINE_REVISION].down_revision == TWELVE_DATA_REVISION
    assert by_revision[DIRECT_FX_REVISION].down_revision == DAILY_BASELINE_REVISION
    assert by_revision[MULTI_CURRENCY_COST_BASIS_REVISION].down_revision == DIRECT_FX_REVISION
    assert by_revision[BACKGROUND_JOB_REVISION].down_revision == MULTI_CURRENCY_COST_BASIS_REVISION
    assert by_revision[IMPORT_PUBLICATION_ANCHOR_REVISION].down_revision == BACKGROUND_JOB_REVISION
    assert (
        by_revision[EMPTY_INVESTMENT_HOLDING_REVISION].down_revision
        == IMPORT_PUBLICATION_ANCHOR_REVISION
    )
    assert (
        by_revision[UNKNOWN_INVESTMENT_COST_BASIS_REVISION].down_revision
        == EMPTY_INVESTMENT_HOLDING_REVISION
    )
    assert (
        by_revision[RB_SCHEMA_FOUNDATION_REVISION].down_revision
        == UNKNOWN_INVESTMENT_COST_BASIS_REVISION
    )
    assert by_revision[HISTORY_GENERATION_REVISION].down_revision == RB_SCHEMA_FOUNDATION_REVISION
    assert by_revision[HISTORY_CLEANUP_REVISION].down_revision == HISTORY_GENERATION_REVISION
    assert by_revision[CREDIT_LIMIT_REVISION].down_revision == HISTORY_CLEANUP_REVISION
    assert by_revision[MANUAL_MINUTE_BASELINE_REVISION].down_revision == CREDIT_LIMIT_REVISION
    assert (
        by_revision[READ_MODEL_PUBLICATION_REVISION].down_revision
        == MANUAL_MINUTE_BASELINE_REVISION
    )
    assert (
        by_revision[SNAPSHOT_GENERATION_REVISION].down_revision == READ_MODEL_PUBLICATION_REVISION
    )
    assert by_revision[PORTFOLIO_SNAPSHOT_REVISION].down_revision == SNAPSHOT_GENERATION_REVISION
    assert by_revision[MARKET_BASELINE_REVISION].down_revision == PORTFOLIO_SNAPSHOT_REVISION
    assert by_revision[HISTORY_SERIES_REVISION].down_revision == MARKET_BASELINE_REVISION
    assert by_revision[SNAPSHOT_SERIES_JOBS_REVISION].down_revision == HISTORY_SERIES_REVISION
    assert by_revision[HISTORY_DROP_REVISION].down_revision == SNAPSHOT_SERIES_JOBS_REVISION
    assert by_revision[ANYCOIN_TRANSFER_VALUATION_REVISION].down_revision == HISTORY_DROP_REVISION
    assert (
        by_revision[TEMPORAL_SERIES_REVISION].down_revision == ANYCOIN_TRANSFER_VALUATION_REVISION
    )
