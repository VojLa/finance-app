"""Add the atomically published user read-model version.

Revision ID: 3t0001readmodelversion
Revises: 3s0001manualbaseline
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3t0001readmodelversion"
down_revision: str | None = "3s0001manualbaseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "user_read_model_publication"
affected_tables = ("UserReadModelPublication",)
affected_columns = (
    "UserReadModelPublication.userId",
    "UserReadModelPublication.version",
    "UserReadModelPublication.baselineId",
    "UserReadModelPublication.scopes",
    "UserReadModelPublication.publishedAt",
)
prisma_schema_impact = "required"
data_migration = False


def upgrade() -> None:
    op.create_table(
        "UserReadModelPublication",
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("version", sa.Text(), nullable=False),
        sa.Column("baselineId", sa.Text(), nullable=False),
        sa.Column("scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("publishedAt", postgresql.TIMESTAMP(precision=3), nullable=False),
        sa.CheckConstraint("\"version\" <> ''", name="UserReadModelPublication_version_nonempty"),
        sa.ForeignKeyConstraint(
            ["baselineId"],
            ["public.DailySnapshotBaseline.id"],
            name="UserReadModelPublication_baselineId_fkey",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["userId"], ["public.User.id"], ondelete="CASCADE", onupdate="CASCADE"
        ),
        sa.PrimaryKeyConstraint("userId"),
        schema="public",
    )
    op.execute(
        """
        INSERT INTO "public"."UserReadModelPublication"
            ("userId", "version", "baselineId", "scopes", "publishedAt")
        SELECT DISTINCT ON (baseline."userId")
            baseline."userId",
            baseline."id",
            baseline."id",
            '["portfolio", "dashboard"]'::jsonb,
            baseline."createdAt"
        FROM "public"."DailySnapshotBaseline" AS baseline
        LEFT JOIN "public"."ImportJobPublicationTarget" AS target
          ON baseline."backgroundJobId" = target."jobId"
         AND baseline."userId" = target."userId"
        LEFT JOIN "public"."BackgroundJob" AS job
          ON baseline."backgroundJobId" = job."id"
        WHERE baseline."backgroundJobId" IS NULL
           OR (job."status" = 'completed'::"public"."BackgroundJobStatus"
               AND target."publishedAt" IS NOT NULL)
        ORDER BY baseline."userId", baseline."timestamp" DESC, baseline."id" DESC
        """
    )


def downgrade() -> None:
    op.drop_table("UserReadModelPublication", schema="public")
