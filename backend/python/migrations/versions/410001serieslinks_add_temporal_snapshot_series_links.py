"""Add versioned snapshot-series heads, temporal links and publication receipts.

Revision ID: 410001serieslinks
Revises: 400001anycoinvaluation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "410001serieslinks"
down_revision: str | None = "400001anycoinvaluation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_temporal_snapshot_series_links"
affected_tables = (
    "SnapshotSeriesVersionState",
    "SnapshotSeriesHead",
    "SnapshotSeriesPointLink",
    "SnapshotSeriesPublicationReceipt",
    "DailySnapshotBaseline",
    "SnapshotGenerationTarget",
    "UserReadModelPublication",
)
prisma_schema_impact = "required"
data_migration = True

_TIMESTAMP = postgresql.TIMESTAMP(precision=3)
_GRANULARITY = postgresql.ENUM(name="SnapshotGranularity", schema="public", create_type=False)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.add_column(
        "SnapshotGenerationTarget", sa.Column("stagedByJobId", sa.Text()), schema="public"
    )
    op.add_column(
        "SnapshotGenerationTarget",
        sa.Column("stagedLeaseVersion", sa.BigInteger()),
        schema="public",
    )
    op.add_column(
        "SnapshotGenerationTarget", sa.Column("stagedLeaseOwner", sa.Text()), schema="public"
    )
    op.create_foreign_key(
        "SnapshotGenerationTarget_staging_job_user_fkey",
        "SnapshotGenerationTarget",
        "SnapshotSeriesRebuildJob",
        ["stagedByJobId", "userId"],
        ["id", "userId"],
        source_schema="public",
        referent_schema="public",
        onupdate="CASCADE",
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "SnapshotGenerationTarget_staging_provenance_complete",
        "SnapshotGenerationTarget",
        '("stagedByJobId" IS NULL AND "stagedLeaseVersion" IS NULL AND "stagedLeaseOwner" IS NULL) OR ("stagedByJobId" IS NOT NULL AND "stagedLeaseVersion" IS NOT NULL AND "stagedLeaseVersion" >= 0 AND "stagedLeaseOwner" IS NOT NULL)',
        schema="public",
    )
    op.create_index(
        "DailySnapshotBaseline_exact_point_key",
        "DailySnapshotBaseline",
        ["id", "generationId", "userId", "netWorthSnapshotId"],
        unique=True,
        schema="public",
    )
    op.create_table(
        "SnapshotSeriesVersionState",
        sa.Column(
            "userId",
            sa.Text(),
            sa.ForeignKey("public.User.id", onupdate="CASCADE", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("lastVersion", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("updatedAt", _TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            '"lastVersion" >= 0', name="SnapshotSeriesVersionState_lastVersion_nonnegative"
        ),
        schema="public",
    )
    op.create_table(
        "SnapshotSeriesHead",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "userId",
            sa.Text(),
            sa.ForeignKey("public.User.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.BigInteger(), nullable=False),
        sa.Column("parentHeadId", sa.Text()),
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("createdAt", _TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["generationId", "userId"],
            [
                "public.SnapshotGenerationTarget.generationId",
                "public.SnapshotGenerationTarget.userId",
            ],
            name="SnapshotSeriesHead_generation_target_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint('"version" >= 1', name="SnapshotSeriesHead_version_positive"),
        sa.CheckConstraint(
            '"parentHeadId" IS NULL OR "parentHeadId" <> "id"',
            name="SnapshotSeriesHead_parent_distinct",
        ),
        schema="public",
    )
    op.create_index(
        "SnapshotSeriesHead_user_version_key",
        "SnapshotSeriesHead",
        ["userId", "version"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "SnapshotSeriesHead_id_user_key",
        "SnapshotSeriesHead",
        ["id", "userId"],
        unique=True,
        schema="public",
    )
    op.create_foreign_key(
        "SnapshotSeriesHead_parent_user_fkey",
        "SnapshotSeriesHead",
        "SnapshotSeriesHead",
        ["parentHeadId", "userId"],
        ["id", "userId"],
        source_schema="public",
        referent_schema="public",
        onupdate="CASCADE",
        ondelete="RESTRICT",
    )
    op.create_table(
        "SnapshotSeriesPointLink",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "userId",
            sa.Text(),
            sa.ForeignKey("public.User.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("timestamp", _TIMESTAMP, nullable=False),
        sa.Column("granularity", _GRANULARITY, nullable=False),
        sa.Column("validFromVersion", sa.BigInteger(), nullable=False),
        sa.Column("validToVersion", sa.BigInteger()),
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("baselineId", sa.Text(), nullable=False),
        sa.Column("portfolioSnapshotId", sa.Text(), nullable=False),
        sa.Column("netWorthSnapshotId", sa.Text(), nullable=False),
        sa.Column("createdAt", _TIMESTAMP, nullable=False),
        sa.ForeignKeyConstraint(
            ["userId", "validFromVersion"],
            ["public.SnapshotSeriesHead.userId", "public.SnapshotSeriesHead.version"],
            name="SnapshotSeriesPointLink_from_head_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["baselineId", "generationId", "userId", "netWorthSnapshotId"],
            [
                "public.DailySnapshotBaseline.id",
                "public.DailySnapshotBaseline.generationId",
                "public.DailySnapshotBaseline.userId",
                "public.DailySnapshotBaseline.netWorthSnapshotId",
            ],
            name="SnapshotSeriesPointLink_baseline_exact_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["portfolioSnapshotId", "generationId", "userId"],
            [
                "public.PortfolioSnapshot.id",
                "public.PortfolioSnapshot.generationId",
                "public.PortfolioSnapshot.userId",
            ],
            name="SnapshotSeriesPointLink_portfolio_exact_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["netWorthSnapshotId", "generationId", "userId"],
            [
                "public.NetWorthSnapshot.id",
                "public.NetWorthSnapshot.generationId",
                "public.NetWorthSnapshot.userId",
            ],
            name="SnapshotSeriesPointLink_net_worth_exact_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint('"validFromVersion" >= 1', name="SnapshotSeriesPointLink_from_positive"),
        sa.CheckConstraint(
            '"validToVersion" IS NULL OR "validToVersion" > "validFromVersion"',
            name="SnapshotSeriesPointLink_to_after_from",
        ),
        schema="public",
    )
    op.create_index(
        "SnapshotSeriesPointLink_coordinate_from_key",
        "SnapshotSeriesPointLink",
        ["userId", "timestamp", "granularity", "validFromVersion"],
        unique=True,
        schema="public",
    )
    op.execute(
        'ALTER TABLE "public"."SnapshotSeriesPointLink" ADD CONSTRAINT "SnapshotSeriesPointLink_no_overlap" EXCLUDE USING gist ("userId" WITH =, "timestamp" WITH =, "granularity" WITH =, int8range("validFromVersion", "validToVersion", \'[)\') WITH &&)'
    )
    op.create_index(
        "SnapshotSeriesPointLink_one_current_coordinate_key",
        "SnapshotSeriesPointLink",
        ["userId", "timestamp", "granularity"],
        unique=True,
        postgresql_where=sa.text('"validToVersion" IS NULL'),
        schema="public",
    )
    op.create_index(
        "SnapshotSeriesPointLink_user_visible_idx",
        "SnapshotSeriesPointLink",
        ["userId", "granularity", "timestamp", "validFromVersion", "validToVersion"],
        schema="public",
    )
    op.create_table(
        "SnapshotSeriesPublicationReceipt",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "userId",
            sa.Text(),
            sa.ForeignKey("public.User.id", onupdate="CASCADE", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("jobId", sa.Text(), nullable=False),
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("headId", sa.Text(), nullable=False),
        sa.Column("committedAt", _TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            'char_length("jobId") BETWEEN 1 AND 200',
            name="SnapshotSeriesPublicationReceipt_job_id_bounded",
        ),
        sa.ForeignKeyConstraint(
            ["generationId", "userId"],
            [
                "public.SnapshotGenerationTarget.generationId",
                "public.SnapshotGenerationTarget.userId",
            ],
            name="SnapshotSeriesPublicationReceipt_generation_target_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["headId", "userId"],
            ["public.SnapshotSeriesHead.id", "public.SnapshotSeriesHead.userId"],
            name="SnapshotSeriesPublicationReceipt_head_user_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        schema="public",
    )
    op.create_index(
        "SnapshotSeriesPublicationReceipt_user_job_key",
        "SnapshotSeriesPublicationReceipt",
        ["userId", "jobId"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "SnapshotSeriesPublicationReceipt_user_generation_key",
        "SnapshotSeriesPublicationReceipt",
        ["userId", "generationId"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "SnapshotSeriesPublicationReceipt_user_head_key",
        "SnapshotSeriesPublicationReceipt",
        ["userId", "headId"],
        unique=True,
        schema="public",
    )
    op.add_column("UserReadModelPublication", sa.Column("seriesHeadId", sa.Text()), schema="public")
    op.create_foreign_key(
        "UserReadModelPublication_series_head_user_fkey",
        "UserReadModelPublication",
        "SnapshotSeriesHead",
        ["seriesHeadId", "userId"],
        ["id", "userId"],
        source_schema="public",
        referent_schema="public",
        onupdate="CASCADE",
        ondelete="RESTRICT",
    )

    connection = op.get_bind()
    invalid = connection.execute(
        sa.text("""
        SELECT p."userId" FROM "public"."UserReadModelPublication" p
        JOIN "public"."DailySnapshotBaseline" b
          ON b."userId" = p."userId" AND b."generationId" = p."generationId"
        LEFT JOIN "public"."PortfolioSnapshot" ps
          ON ps."userId" = b."userId" AND ps."generationId" = b."generationId"
         AND ps."timestamp" = b."timestamp" AND ps."granularity" = b."granularity"
         AND ps."currency" = b."currency"
        JOIN "public"."NetWorthSnapshot" n ON n."id" = b."netWorthSnapshotId"
        GROUP BY p."userId", b."timestamp", b."granularity"
        HAVING count(*) <> 1 OR count(ps."id") <> 1
           OR bool_or(n."timestamp" <> b."timestamp" OR n."granularity" <> b."granularity")
        LIMIT 1
    """)
    ).first()
    if invalid is not None:
        raise RuntimeError(
            f"Cannot backfill inconsistent published snapshot coordinate for user {invalid[0]}"
        )
    missing = connection.execute(
        sa.text("""
        SELECT p."userId" FROM "public"."UserReadModelPublication" p
        WHERE NOT EXISTS (
            SELECT 1 FROM "public"."DailySnapshotBaseline" b
            WHERE b."userId" = p."userId" AND b."generationId" = p."generationId"
              AND b."id" = p."baselineId"
        ) LIMIT 1
    """)
    ).first()
    if missing is not None:
        raise RuntimeError(
            f"Cannot backfill publication without its baseline for user {missing[0]}"
        )

    op.execute("""
        INSERT INTO "public"."SnapshotSeriesVersionState" ("userId", "lastVersion", "updatedAt")
        SELECT "userId", 1, "publishedAt" FROM "public"."UserReadModelPublication"
    """)
    op.execute("""
        INSERT INTO "public"."SnapshotSeriesHead" ("id", "userId", "version", "generationId", "createdAt")
        SELECT 'series-head-migration-' || md5("userId"), "userId", 1, "generationId", "publishedAt"
        FROM "public"."UserReadModelPublication"
    """)
    op.execute("""
        INSERT INTO "public"."SnapshotSeriesPointLink"
          ("id", "userId", "timestamp", "granularity", "validFromVersion", "generationId",
           "baselineId", "portfolioSnapshotId", "netWorthSnapshotId", "createdAt")
        SELECT 'series-link-migration-' || md5(b."id"), b."userId", b."timestamp", b."granularity", 1,
               b."generationId", b."id", ps."id", b."netWorthSnapshotId", p."publishedAt"
        FROM "public"."UserReadModelPublication" p
        JOIN "public"."DailySnapshotBaseline" b
          ON b."userId" = p."userId" AND b."generationId" = p."generationId"
        JOIN "public"."PortfolioSnapshot" ps
          ON ps."userId" = b."userId" AND ps."generationId" = b."generationId"
         AND ps."timestamp" = b."timestamp" AND ps."granularity" = b."granularity"
         AND ps."currency" = b."currency"
    """)
    op.execute("""
        UPDATE "public"."UserReadModelPublication"
        SET "seriesHeadId" = 'series-head-migration-' || md5("userId")
    """)
    op.alter_column("UserReadModelPublication", "seriesHeadId", nullable=False, schema="public")
    op.execute("""
        CREATE FUNCTION "public"."guard_snapshot_series_version_state"() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'UPDATE' AND NEW."lastVersion" < OLD."lastVersion" THEN
                RAISE EXCEPTION 'snapshot series version cannot decrease';
            END IF;
            IF TG_OP = 'DELETE' AND EXISTS (SELECT 1 FROM "public"."User" WHERE "id" = OLD."userId") THEN
                RAISE EXCEPTION 'snapshot series version state survives retirement';
            END IF;
            RETURN COALESCE(NEW, OLD);
        END $$
    """)
    op.execute("""
        CREATE TRIGGER "SnapshotSeriesVersionState_guard" BEFORE UPDATE OR DELETE
        ON "public"."SnapshotSeriesVersionState" FOR EACH ROW
        EXECUTE FUNCTION "public"."guard_snapshot_series_version_state"()
    """)
    op.execute("""
        CREATE FUNCTION "public"."guard_snapshot_series_immutable"() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND NOT EXISTS (SELECT 1 FROM "public"."User" WHERE "id" = OLD."userId") THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'snapshot series publication metadata is immutable';
        END $$
    """)
    for table in ("SnapshotSeriesHead", "SnapshotSeriesPublicationReceipt"):
        op.execute(f'''
            CREATE TRIGGER "{table}_immutable" BEFORE UPDATE OR DELETE
            ON "public"."{table}" FOR EACH ROW
            EXECUTE FUNCTION "public"."guard_snapshot_series_immutable"()
        ''')
    op.execute("""
        CREATE FUNCTION "public"."guard_snapshot_series_point_link"() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' AND NOT EXISTS (SELECT 1 FROM "public"."User" WHERE "id" = OLD."userId") THEN
                RETURN OLD;
            END IF;
            IF TG_OP = 'UPDATE' AND OLD."validToVersion" IS NULL
                AND NEW."validToVersion" IS NOT NULL
                AND (to_jsonb(NEW) - 'validToVersion') = (to_jsonb(OLD) - 'validToVersion') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'snapshot series point links may only close once';
        END $$
    """)
    op.execute("""
        CREATE TRIGGER "SnapshotSeriesPointLink_guard" BEFORE UPDATE OR DELETE
        ON "public"."SnapshotSeriesPointLink" FOR EACH ROW
        EXECUTE FUNCTION "public"."guard_snapshot_series_point_link"()
    """)


def downgrade() -> None:
    raise RuntimeError("Temporal snapshot-series metadata is irreversible after publication.")
