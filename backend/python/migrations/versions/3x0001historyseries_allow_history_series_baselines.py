"""Finalize historical snapshot-series storage semantics.

Revision ID: 3x0001historyseries
Revises: 3w0001marketbaseline
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import CheckConstraint, Column, ForeignKeyConstraint, Text
from sqlalchemy.dialects import postgresql

revision: str = "3x0001historyseries"
down_revision: str | None = "3w0001marketbaseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "finalize_history_series_storage"
affected_tables = (
    "AccountSnapshot",
    "DailySnapshotBaseline",
    "PortfolioSnapshotInput",
    "UserReadModelPublicationWatermark",
)
prisma_schema_impact = "required"
data_migration = True

_CONSTRAINT = "DailySnapshotBaseline_day_or_import_anchor"
_MEMBERSHIP_CONSTRAINT = "PortfolioSnapshotInput_authorized_account_user_fkey"


def upgrade() -> None:
    op.add_column(
        "AccountSnapshot",
        Column(
            "liabilitiesValueByCurrency",
            postgresql.JSONB(none_as_null=True),
            nullable=True,
        ),
        schema="public",
    )
    op.create_table(
        "UserReadModelPublicationWatermark",
        Column("userId", Text, primary_key=True),
        Column("causalAt", postgresql.TIMESTAMP(precision=3, timezone=False), nullable=False),
        Column("kind", Text, nullable=False),
        Column("generationId", Text, nullable=True),
        Column("updatedAt", postgresql.TIMESTAMP(precision=3, timezone=False), nullable=False),
        CheckConstraint(
            "\"kind\" IN ('published', 'retired')",
            name="UserReadModelPublicationWatermark_kind_known",
        ),
        CheckConstraint(
            '("kind" = \'published\' AND "generationId" IS NOT NULL) OR '
            '("kind" = \'retired\' AND "generationId" IS NULL)',
            name="UserReadModelPublicationWatermark_generation_matches_kind",
        ),
        ForeignKeyConstraint(
            ("userId",),
            ("public.User.id",),
            name="UserReadModelPublicationWatermark_userId_fkey",
            ondelete="CASCADE",
        ),
        schema="public",
    )
    op.execute(
        'INSERT INTO "public"."UserReadModelPublicationWatermark" '
        '("userId", "causalAt", "kind", "generationId", "updatedAt") '
        'SELECT "userId", "publishedAt", \'published\', "generationId", "publishedAt" '
        'FROM "public"."UserReadModelPublication"'
    )
    # Authorization is checked while staging and again before every public read.
    # Keeping a historical input tied to the *current* membership row would make
    # membership revocation impossible and would mutate history semantics.
    op.execute(
        'ALTER TABLE "public"."PortfolioSnapshotInput" '
        f'DROP CONSTRAINT IF EXISTS "{_MEMBERSHIP_CONSTRAINT}"'
    )
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
        "'price_refresh'::\"SnapshotSource\", 'scheduled'::\"SnapshotSource\", "
        "'holdings_recalculation'::\"SnapshotSource\") "
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
        '("source" IN (\'manual_recalculation\'::"SnapshotSource", '
        "'price_refresh'::\"SnapshotSource\", 'scheduled'::\"SnapshotSource\") "
        'AND "backgroundJobId" IS NULL)))',
        schema="public",
    )
    op.create_foreign_key(
        _MEMBERSHIP_CONSTRAINT,
        "PortfolioSnapshotInput",
        "AccountMember",
        ("accountId", "userId"),
        ("accountId", "userId"),
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
    )
    op.drop_column(
        "AccountSnapshot",
        "liabilitiesValueByCurrency",
        schema="public",
    )
    op.drop_table("UserReadModelPublicationWatermark", schema="public")
