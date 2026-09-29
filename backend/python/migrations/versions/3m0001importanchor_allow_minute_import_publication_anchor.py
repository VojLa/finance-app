"""Allow a minute import publication anchor for strict current-value reads.

Revision ID: 3m0001importanchor
Revises: 3l0001bgjob
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3m0001importanchor"
down_revision: str | None = "3l0001bgjob"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "allow_import_current_value_publication_anchor"
affected_tables = ("DailySnapshotBaseline", "ImportJobPublicationTarget")
affected_columns = (
    "DailySnapshotBaseline.granularity",
    "DailySnapshotBaseline.source",
    "DailySnapshotBaseline.backgroundJobId",
    "ImportJobPublicationTarget.jobId",
    "ImportJobPublicationTarget.userId",
    "ImportJobPublicationTarget.bucket",
    "ImportJobPublicationTarget.publishedAt",
)
prisma_schema_impact = "required"
data_migration = False

_OLD_CHECK = "DailySnapshotBaseline_day_only"
_NEW_CHECK = "DailySnapshotBaseline_day_or_import_anchor"
_NEW_EXPRESSION = (
    '("granularity" = \'day\'::"SnapshotGranularity" OR '
    '("granularity" = \'minute\'::"SnapshotGranularity" '
    'AND "source" = \'import_event\'::"SnapshotSource" '
    'AND "backgroundJobId" IS NOT NULL)) '
    'AND (("granularity" = \'day\'::"SnapshotGranularity") = '
    '("backgroundJobId" IS NULL))'
)


def upgrade() -> None:
    op.create_table(
        "ImportJobPublicationTarget",
        sa.Column("jobId", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("bucket", postgresql.TIMESTAMP(precision=3), nullable=False),
        sa.Column("publishedAt", postgresql.TIMESTAMP(precision=3), nullable=True),
        sa.ForeignKeyConstraint(
            ["jobId"],
            ["public.BackgroundJob.id"],
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["userId"],
            ["public.User.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("jobId", "userId"),
        sa.CheckConstraint(
            'date_trunc(\'minute\', "bucket") = "bucket"',
            name="ImportJobPublicationTarget_bucket_minute_aligned",
        ),
        schema="public",
    )
    op.create_index(
        "ImportJobPublicationTarget_user_bucket_key",
        "ImportJobPublicationTarget",
        ["userId", "bucket"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "ImportJobPublicationTarget_unpublished_idx",
        "ImportJobPublicationTarget",
        ["userId", "bucket"],
        schema="public",
    )
    op.add_column(
        "DailySnapshotBaseline",
        sa.Column("backgroundJobId", sa.Text(), nullable=True),
        schema="public",
    )
    op.create_foreign_key(
        "DailySnapshotBaseline_backgroundJob_user_fkey",
        "DailySnapshotBaseline",
        "ImportJobPublicationTarget",
        ["backgroundJobId", "userId"],
        ["jobId", "userId"],
        source_schema="public",
        referent_schema="public",
        onupdate="CASCADE",
        ondelete="RESTRICT",
    )
    op.create_index(
        "DailySnapshotBaseline_backgroundJob_user_key",
        "DailySnapshotBaseline",
        ["backgroundJobId", "userId"],
        unique=True,
        schema="public",
    )
    op.drop_constraint(_OLD_CHECK, "DailySnapshotBaseline", schema="public", type_="check")
    op.create_check_constraint(
        _NEW_CHECK,
        "DailySnapshotBaseline",
        _NEW_EXPRESSION,
        schema="public",
    )


def downgrade() -> None:
    connection = op.get_bind()
    anchor_exists = connection.execute(
        sa.text(
            'SELECT EXISTS (SELECT 1 FROM "public"."DailySnapshotBaseline" '
            'WHERE "granularity" = \'minute\'::"SnapshotGranularity")'
        )
    ).scalar_one()
    if anchor_exists:
        raise RuntimeError("Cannot remove minute import publication anchors while evidence exists.")
    op.drop_constraint(_NEW_CHECK, "DailySnapshotBaseline", schema="public", type_="check")
    op.drop_index(
        "DailySnapshotBaseline_backgroundJob_user_key",
        table_name="DailySnapshotBaseline",
        schema="public",
    )
    op.drop_constraint(
        "DailySnapshotBaseline_backgroundJob_user_fkey",
        "DailySnapshotBaseline",
        schema="public",
        type_="foreignkey",
    )
    op.drop_column("DailySnapshotBaseline", "backgroundJobId", schema="public")
    target_exists = connection.execute(
        sa.text('SELECT EXISTS (SELECT 1 FROM "public"."ImportJobPublicationTarget")')
    ).scalar_one()
    if target_exists:
        raise RuntimeError("Cannot remove import publication targets while evidence exists.")
    op.drop_index(
        "ImportJobPublicationTarget_unpublished_idx",
        table_name="ImportJobPublicationTarget",
        schema="public",
    )
    op.drop_index(
        "ImportJobPublicationTarget_user_bucket_key",
        table_name="ImportJobPublicationTarget",
        schema="public",
    )
    op.drop_table("ImportJobPublicationTarget", schema="public")
    op.create_check_constraint(
        _OLD_CHECK,
        "DailySnapshotBaseline",
        '"granularity" = \'day\'::"SnapshotGranularity"',
        schema="public",
    )
