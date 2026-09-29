"""Add shared staged snapshot generations and their per-user targets.

Revision ID: 3u0001snapshotgeneration
Revises: 3t0001readmodelversion
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3u0001snapshotgeneration"
down_revision: str | None = "3t0001readmodelversion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_staged_snapshot_generations"
affected_tables = (
    "SnapshotGeneration",
    "SnapshotGenerationTarget",
    "AccountSnapshot",
    "NetWorthSnapshot",
    "DailySnapshotBaseline",
    "DailySnapshotBaselineAccount",
    "UserReadModelPublication",
)
prisma_schema_impact = "required"
data_migration = True

_LEGACY_GENERATION_ID = "legacy-snapshot-generation:3u0001"


def upgrade() -> None:
    op.create_table(
        "SnapshotGeneration",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("createdAt", postgresql.TIMESTAMP(precision=3), nullable=False),
        sa.Column("publishedAt", postgresql.TIMESTAMP(precision=3), nullable=True),
        sa.CheckConstraint(
            "\"state\" IN ('staged', 'published')",
            name="SnapshotGeneration_state_known",
        ),
        sa.CheckConstraint(
            '(("state" = \'staged\' AND "publishedAt" IS NULL) OR '
            '("state" = \'published\' AND "publishedAt" IS NOT NULL))',
            name="SnapshotGeneration_publication_lifecycle",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "state", name="SnapshotGeneration_id_state_key"),
        schema="public",
    )
    op.create_index(
        "SnapshotGeneration_state_createdAt_idx",
        "SnapshotGeneration",
        ["state", "createdAt"],
        schema="public",
    )
    op.create_table(
        "SnapshotGenerationTarget",
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("createdAt", postgresql.TIMESTAMP(precision=3), nullable=False),
        sa.ForeignKeyConstraint(
            ["generationId"],
            ["public.SnapshotGeneration.id"],
            name="SnapshotGenerationTarget_generationId_fkey",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["userId"],
            ["public.User.id"],
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("generationId", "userId"),
        schema="public",
    )
    op.create_index(
        "SnapshotGenerationTarget_userId_generationId_idx",
        "SnapshotGenerationTarget",
        ["userId", "generationId"],
        schema="public",
    )

    for table in ("AccountSnapshot", "NetWorthSnapshot", "DailySnapshotBaseline"):
        op.add_column(table, sa.Column("generationId", sa.Text(), nullable=True), schema="public")
    op.add_column(
        "DailySnapshotBaselineAccount",
        sa.Column("generationId", sa.Text(), nullable=True),
        schema="public",
    )
    op.add_column(
        "UserReadModelPublication",
        sa.Column("generationId", sa.Text(), nullable=True),
        schema="public",
    )
    op.add_column(
        "UserReadModelPublication",
        sa.Column("generationState", sa.Text(), nullable=True),
        schema="public",
    )

    op.execute(
        sa.text(
            """
            INSERT INTO "public"."SnapshotGeneration" ("id", "state", "createdAt", "publishedAt")
            VALUES (:generation_id, 'published', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        ).bindparams(generation_id=_LEGACY_GENERATION_ID)
    )
    op.execute(
        sa.text(
            """
            UPDATE "public"."AccountSnapshot"
            SET "generationId" = :generation_id
            WHERE "generationId" IS NULL
            """
        ).bindparams(generation_id=_LEGACY_GENERATION_ID)
    )
    op.execute(
        sa.text(
            """
            UPDATE "public"."NetWorthSnapshot"
            SET "generationId" = :generation_id
            WHERE "generationId" IS NULL
            """
        ).bindparams(generation_id=_LEGACY_GENERATION_ID)
    )
    op.execute(
        sa.text(
            """
            UPDATE "public"."DailySnapshotBaseline"
            SET "generationId" = :generation_id
            WHERE "generationId" IS NULL
            """
        ).bindparams(generation_id=_LEGACY_GENERATION_ID)
    )
    op.execute(
        sa.text(
            """
            UPDATE "public"."DailySnapshotBaselineAccount" AS baseline_account
            SET "generationId" = baseline."generationId"
            FROM "public"."DailySnapshotBaseline" AS baseline
            WHERE baseline."id" = baseline_account."baselineId"
              AND baseline_account."generationId" IS NULL
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE "public"."UserReadModelPublication"
            SET "generationId" = :generation_id,
                "generationState" = 'published'
            WHERE "generationId" IS NULL OR "generationState" IS NULL
            """
        ).bindparams(generation_id=_LEGACY_GENERATION_ID)
    )
    op.execute(
        sa.text(
            """
            INSERT INTO "public"."SnapshotGenerationTarget" ("generationId", "userId", "createdAt")
            SELECT :generation_id, targets."userId", CURRENT_TIMESTAMP
            FROM (
                SELECT "userId" FROM "public"."NetWorthSnapshot"
                UNION
                SELECT "userId" FROM "public"."DailySnapshotBaseline"
                UNION
                SELECT "userId" FROM "public"."UserReadModelPublication"
            ) AS targets
            """
        ).bindparams(generation_id=_LEGACY_GENERATION_ID)
    )

    for table in ("AccountSnapshot", "NetWorthSnapshot", "DailySnapshotBaseline"):
        op.alter_column(table, "generationId", nullable=False, schema="public")
    op.alter_column("DailySnapshotBaselineAccount", "generationId", nullable=False, schema="public")
    op.alter_column("UserReadModelPublication", "generationId", nullable=False, schema="public")
    op.alter_column(
        "UserReadModelPublication",
        "generationState",
        nullable=False,
        server_default=sa.text("'published'::text"),
        schema="public",
    )

    op.drop_index(
        "AccountSnapshot_accountId_timestamp_currency_granularity_key",
        table_name="AccountSnapshot",
        schema="public",
    )
    op.create_index(
        "AccountSnapshot_coordinate_generation_key",
        "AccountSnapshot",
        ["accountId", "timestamp", "currency", "granularity", "generationId"],
        unique=True,
        schema="public",
    )
    op.create_unique_constraint(
        "AccountSnapshot_id_generation_key",
        "AccountSnapshot",
        ["id", "generationId"],
        schema="public",
    )
    op.create_unique_constraint(
        "AccountSnapshot_id_generation_account_key",
        "AccountSnapshot",
        ["id", "generationId", "accountId"],
        schema="public",
    )
    op.create_index(
        "AccountSnapshot_generation_coordinate_idx",
        "AccountSnapshot",
        ["generationId", "accountId", "granularity", "timestamp"],
        schema="public",
    )
    op.create_foreign_key(
        "AccountSnapshot_generationId_fkey",
        "AccountSnapshot",
        "SnapshotGeneration",
        ["generationId"],
        ["id"],
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
        onupdate="CASCADE",
    )

    op.drop_index(
        "NetWorthSnapshot_userId_timestamp_currency_granularity_key",
        table_name="NetWorthSnapshot",
        schema="public",
    )
    op.create_index(
        "NetWorthSnapshot_coordinate_generation_key",
        "NetWorthSnapshot",
        ["userId", "timestamp", "currency", "granularity", "generationId"],
        unique=True,
        schema="public",
    )
    op.create_unique_constraint(
        "NetWorthSnapshot_id_generation_user_key",
        "NetWorthSnapshot",
        ["id", "generationId", "userId"],
        schema="public",
    )
    op.create_index(
        "NetWorthSnapshot_generation_coordinate_idx",
        "NetWorthSnapshot",
        ["generationId", "userId", "granularity", "timestamp"],
        schema="public",
    )
    op.create_foreign_key(
        "NetWorthSnapshot_generation_target_fkey",
        "NetWorthSnapshot",
        "SnapshotGenerationTarget",
        ["generationId", "userId"],
        ["generationId", "userId"],
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
        onupdate="CASCADE",
    )

    op.drop_index(
        "DailyBaseline_user_timestamp_currency_version_key",
        table_name="DailySnapshotBaseline",
        schema="public",
    )
    op.create_index(
        "DailyBaseline_user_timestamp_currency_generation_version_key",
        "DailySnapshotBaseline",
        ["userId", "timestamp", "currency", "calculationVersion", "generationId"],
        unique=True,
        schema="public",
    )
    op.create_unique_constraint(
        "DailySnapshotBaseline_id_generation_user_key",
        "DailySnapshotBaseline",
        ["id", "generationId", "userId"],
        schema="public",
    )
    op.create_unique_constraint(
        "DailySnapshotBaseline_id_generation_key",
        "DailySnapshotBaseline",
        ["id", "generationId"],
        schema="public",
    )
    op.create_index(
        "DailySnapshotBaseline_generationId_userId_timestamp_idx",
        "DailySnapshotBaseline",
        ["generationId", "userId", "timestamp"],
        schema="public",
    )
    op.create_foreign_key(
        "DailySnapshotBaseline_generationId_fkey",
        "DailySnapshotBaseline",
        "SnapshotGeneration",
        ["generationId"],
        ["id"],
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
        onupdate="CASCADE",
    )
    op.create_foreign_key(
        "DailySnapshotBaseline_generation_target_fkey",
        "DailySnapshotBaseline",
        "SnapshotGenerationTarget",
        ["generationId", "userId"],
        ["generationId", "userId"],
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
        onupdate="CASCADE",
    )
    op.create_foreign_key(
        "DailySnapshotBaseline_netWorthSnapshot_generation_fkey",
        "DailySnapshotBaseline",
        "NetWorthSnapshot",
        ["netWorthSnapshotId", "generationId", "userId"],
        ["id", "generationId", "userId"],
        source_schema="public",
        referent_schema="public",
        ondelete="CASCADE",
        onupdate="CASCADE",
    )

    op.create_foreign_key(
        "DailyBaselineAccount_baseline_generation_fkey",
        "DailySnapshotBaselineAccount",
        "DailySnapshotBaseline",
        ["baselineId", "generationId"],
        ["id", "generationId"],
        source_schema="public",
        referent_schema="public",
        ondelete="CASCADE",
        onupdate="CASCADE",
    )
    op.create_foreign_key(
        "DailyBaselineAccount_primarySnapshot_generation_fkey",
        "DailySnapshotBaselineAccount",
        "AccountSnapshot",
        ["primarySnapshotId", "generationId", "accountId"],
        ["id", "generationId", "accountId"],
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
        onupdate="CASCADE",
    )
    op.create_foreign_key(
        "DailyBaselineAccount_presentationSnapshot_generation_fkey",
        "DailySnapshotBaselineAccount",
        "AccountSnapshot",
        ["presentationSnapshotId", "generationId", "accountId"],
        ["id", "generationId", "accountId"],
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
        onupdate="CASCADE",
    )

    op.create_foreign_key(
        "UserReadModelPublication_generationId_fkey",
        "UserReadModelPublication",
        "SnapshotGeneration",
        ["generationId"],
        ["id"],
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
        onupdate="CASCADE",
    )
    op.create_foreign_key(
        "UserReadModelPublication_generation_published_fkey",
        "UserReadModelPublication",
        "SnapshotGeneration",
        ["generationId", "generationState"],
        ["id", "state"],
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
        onupdate="CASCADE",
    )
    op.create_foreign_key(
        "UserReadModelPublication_baseline_generation_fkey",
        "UserReadModelPublication",
        "DailySnapshotBaseline",
        ["baselineId", "generationId", "userId"],
        ["id", "generationId", "userId"],
        source_schema="public",
        referent_schema="public",
        ondelete="RESTRICT",
        onupdate="CASCADE",
    )


def downgrade() -> None:
    raise RuntimeError("Snapshot-generation migration cannot be downgraded automatically.")
