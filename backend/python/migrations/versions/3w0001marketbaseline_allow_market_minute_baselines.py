"""Allow atomic minute publication for background market refresh snapshots.

Revision ID: 3w0001marketbaseline
Revises: 3v0001portfoliosnapshot
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3w0001marketbaseline"
down_revision: str | None = "3v0001portfoliosnapshot"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "allow_market_minute_snapshot_baseline"
affected_tables = ("DailySnapshotBaseline",)
prisma_schema_impact = "required"
data_migration = False

_CONSTRAINT = "DailySnapshotBaseline_day_or_import_anchor"


def upgrade() -> None:
    op.drop_constraint(
        _CONSTRAINT,
        "DailySnapshotBaseline",
        schema="public",
        type_="check",
    )
    op.create_check_constraint(
        _CONSTRAINT,
        "DailySnapshotBaseline",
        '("granularity" = \'day\'::"SnapshotGranularity" AND "backgroundJobId" IS NULL) OR '
        '("granularity" = \'minute\'::"SnapshotGranularity" AND '
        '(("source" = \'import_event\'::"SnapshotSource" AND "backgroundJobId" IS NOT NULL) OR '
        '("source" IN (\'manual_recalculation\'::"SnapshotSource", '
        "'price_refresh'::\"SnapshotSource\", 'scheduled'::\"SnapshotSource\") "
        'AND "backgroundJobId" IS NULL)))',
        schema="public",
    )


def downgrade() -> None:
    op.drop_constraint(
        _CONSTRAINT,
        "DailySnapshotBaseline",
        schema="public",
        type_="check",
    )
    op.create_check_constraint(
        _CONSTRAINT,
        "DailySnapshotBaseline",
        '("granularity" = \'day\'::"SnapshotGranularity" AND "backgroundJobId" IS NULL) OR '
        '("granularity" = \'minute\'::"SnapshotGranularity" AND '
        '(("source" = \'import_event\'::"SnapshotSource" AND "backgroundJobId" IS NOT NULL) OR '
        '("source" = \'manual_recalculation\'::"SnapshotSource" '
        'AND "backgroundJobId" IS NULL)))',
        schema="public",
    )
