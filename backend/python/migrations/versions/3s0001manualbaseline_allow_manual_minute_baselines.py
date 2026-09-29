"""Allow manual minute baselines without an import-publication job.

Revision ID: 3s0001manualbaseline
Revises: 3o0001creditlimit
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3s0001manualbaseline"
down_revision: str | None = "3o0001creditlimit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "allow_manual_minute_snapshot_baseline"
affected_tables = ("DailySnapshotBaseline",)
affected_columns = (
    "DailySnapshotBaseline.granularity",
    "DailySnapshotBaseline.source",
    "DailySnapshotBaseline.backgroundJobId",
)
prisma_schema_impact = "required"
data_migration = False

_CHECK = "DailySnapshotBaseline_day_or_import_anchor"
_PREVIOUS_EXPRESSION = (
    '("granularity" = \'day\'::"SnapshotGranularity" OR '
    '("granularity" = \'minute\'::"SnapshotGranularity" '
    'AND "source" = \'import_event\'::"SnapshotSource" '
    'AND "backgroundJobId" IS NOT NULL)) '
    'AND (("granularity" = \'day\'::"SnapshotGranularity") = '
    '("backgroundJobId" IS NULL))'
)
_CURRENT_EXPRESSION = (
    '(("granularity" = \'day\'::"SnapshotGranularity" '
    'AND "backgroundJobId" IS NULL) OR '
    '("granularity" = \'minute\'::"SnapshotGranularity" AND '
    '(("source" = \'import_event\'::"SnapshotSource" '
    'AND "backgroundJobId" IS NOT NULL) OR '
    '("source" = \'manual_recalculation\'::"SnapshotSource" '
    'AND "backgroundJobId" IS NULL))))'
)


def upgrade() -> None:
    op.drop_constraint(_CHECK, "DailySnapshotBaseline", schema="public", type_="check")
    op.create_check_constraint(
        _CHECK,
        "DailySnapshotBaseline",
        _CURRENT_EXPRESSION,
        schema="public",
    )


def downgrade() -> None:
    connection = op.get_bind()
    manual_baseline_exists = connection.execute(
        sa.text(
            """
        SELECT EXISTS (
            SELECT 1
            FROM "public"."DailySnapshotBaseline"
            WHERE "granularity" = 'minute'::"SnapshotGranularity"
              AND "source" = 'manual_recalculation'::"SnapshotSource"
        )
        """
        )
    ).scalar_one()
    if manual_baseline_exists:
        raise RuntimeError("Cannot remove manual minute baselines while evidence exists.")
    op.drop_constraint(_CHECK, "DailySnapshotBaseline", schema="public", type_="check")
    op.create_check_constraint(
        _CHECK,
        "DailySnapshotBaseline",
        _PREVIOUS_EXPRESSION,
        schema="public",
    )
