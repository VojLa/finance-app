from pathlib import Path

from sqlalchemy.dialects.postgresql import ExcludeConstraint

from app.db.base import Base
from app.db.models import SnapshotSeriesJobKind

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"

LEGACY_TABLES = {
    "PortfolioHistoryJob",
    "PortfolioHistoryGeneration",
    "PortfolioHistoryGenerationAccount",
    "PortfolioHistoryGenerationCleanupReceipt",
    "PortfolioHistoryPublication",
    "PortfolioHistoryReplayCheckpoint",
    "PortfolioHistoryPoint",
    "PortfolioHistoryAccountPoint",
    "PortfolioHistoryCoverageSegment",
    "PortfolioHistoryPointPriceEvidence",
    "PortfolioHistoryPointFxEvidence",
    "PortfolioHistoryCanonicalInvalidation",
    "PortfolioHistoryDirtyState",
    "PortfolioHistoryScheduleState",
}


def test_snapshot_series_replacement_schema_has_no_legacy_dependency() -> None:
    tables = {table.name: table for table in Base.metadata.tables.values()}
    replacement = {
        "SnapshotSeriesRebuildJob",
        "SnapshotSeriesDirtyState",
        "SnapshotSeriesCanonicalInvalidation",
        "SnapshotSeriesScheduleState",
    }
    assert replacement <= set(tables)
    for name in replacement:
        assert {
            foreign_key.column.table.name for foreign_key in tables[name].foreign_keys
        }.isdisjoint(LEGACY_TABLES)


def test_snapshot_series_job_kind_is_limited_to_rebuild_and_capture() -> None:
    assert [member.value for member in SnapshotSeriesJobKind] == ["rebuild", "capture"]


def test_snapshot_series_invalidation_retains_resolution_identity() -> None:
    table = Base.metadata.tables["public.SnapshotSeriesCanonicalInvalidation"]
    assert {"resolvedAt", "resolvedSnapshotGenerationId"} <= set(table.c.keys())
    assert any(fk.column.table.name == "SnapshotGeneration" for fk in table.foreign_keys)


def test_cutover_preserves_monotonic_epochs_and_requeues_interrupted_attempt() -> None:
    schedule = Base.metadata.tables["public.SnapshotSeriesScheduleState"]
    assert "lastDirtyEpoch" in schedule.c
    source = (
        MIGRATIONS / "3y0001snapshotjobs_add_snapshot_series_rebuild_orchestration.py"
    ).read_text(encoding="utf-8")
    assert 'COALESCE(dirty."dirtyEpoch", 0)' in source
    assert 'max(receipt."firstDirtyEpoch")' in source
    assert "job.\"payload\"->>'dirty_epoch'" in source
    assert 'GREATEST("attemptCount" - 1, 0)' in source


def test_irreversible_drop_requires_complete_series_or_claimable_rebuild() -> None:
    source = (MIGRATIONS / "3z0001historydrop_remove_legacy_portfolio_history.py").read_text(
        encoding="utf-8"
    )
    assert 'min(baseline."timestamp") <= old_generation."replayFrom"' in source
    assert 'max(baseline."timestamp") >= old_generation."coveredThrough"' in source
    assert 'replacement."attemptCount" < replacement."maxAttempts"' in source


def test_temporal_series_metadata_has_exact_snapshot_and_head_boundaries() -> None:
    tables = Base.metadata.tables
    state = tables["public.SnapshotSeriesVersionState"]
    head = tables["public.SnapshotSeriesHead"]
    link = tables["public.SnapshotSeriesPointLink"]
    receipt = tables["public.SnapshotSeriesPublicationReceipt"]
    pointer = tables["public.UserReadModelPublication"]

    assert "lastVersion" in state.c
    assert {"userId", "version", "parentHeadId"} <= set(head.c.keys())
    assert pointer.c.seriesHeadId.nullable is False
    assert any(
        set(foreign_key.column_keys) == {"seriesHeadId", "userId"}
        for foreign_key in pointer.foreign_key_constraints
    )
    assert any(isinstance(constraint, ExcludeConstraint) for constraint in link.constraints)
    assert {"baselineId", "portfolioSnapshotId", "netWorthSnapshotId", "generationId"} <= set(
        link.c.keys()
    )
    targets = {foreign_key.referred_table.name for foreign_key in link.foreign_key_constraints}
    assert {
        "DailySnapshotBaseline",
        "PortfolioSnapshot",
        "NetWorthSnapshot",
        "SnapshotSeriesHead",
    } <= targets
    assert any(
        index.unique and index.dialect_options["postgresql"]["where"] is not None
        for index in link.indexes
    )
    assert {"jobId", "generationId", "headId"} <= set(receipt.c.keys())
    assert "SnapshotSeriesRebuildJob" not in {
        foreign_key.referred_table.name for foreign_key in receipt.foreign_key_constraints
    }
    assert any(
        constraint.name == "SnapshotSeriesPublicationReceipt_job_id_bounded"
        for constraint in receipt.constraints
    )
