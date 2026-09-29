"""Add snapshot-series rebuild orchestration and migrate retained legacy state.

Revision ID: 3y0001snapshotjobs
Revises: 3x0001historyseries
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3y0001snapshotjobs"
down_revision: str | None = "3x0001historyseries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_snapshot_series_rebuild_orchestration"
affected_tables = (
    "SnapshotSeriesRebuildJob",
    "SnapshotSeriesDirtyState",
    "SnapshotSeriesCanonicalInvalidation",
    "SnapshotSeriesScheduleState",
)
data_migration = True

_STATUS = postgresql.ENUM(name="BackgroundJobStatus", schema="public", create_type=False)
_KIND = postgresql.ENUM(name="SnapshotSeriesJobKind", schema="public", create_type=False)
_JSONB = postgresql.JSONB(astext_type=sa.Text())
_TIMESTAMP = postgresql.TIMESTAMP(precision=3)


def upgrade() -> None:
    op.execute("CREATE TYPE \"public\".\"SnapshotSeriesJobKind\" AS ENUM ('rebuild', 'capture')")
    op.create_table(
        "SnapshotSeriesRebuildJob",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("requestedByBackgroundJobId", sa.Text()),
        sa.Column("kind", _KIND, nullable=False),
        sa.Column(
            "status",
            _STATUS,
            nullable=False,
            server_default=sa.text("'queued'::\"BackgroundJobStatus\""),
        ),
        sa.Column("idempotencyKey", sa.Text(), nullable=False),
        sa.Column("payload", _JSONB, nullable=False),
        sa.Column("checkpoint", _JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("progress", _JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", _JSONB),
        sa.Column("errorCode", sa.Text()),
        sa.Column("errorMessage", sa.Text()),
        sa.Column("attemptCount", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("manualRetryCount", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("maxAttempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column(
            "runAfter", _TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column("leaseOwner", sa.Text()),
        sa.Column("leaseVersion", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("leaseExpiresAt", _TIMESTAMP),
        sa.Column("leaseHeartbeatAt", _TIMESTAMP),
        sa.Column("startedAt", _TIMESTAMP),
        sa.Column("finishedAt", _TIMESTAMP),
        sa.Column(
            "createdAt", _TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column("updatedAt", _TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(\"payload\") = 'object' AND \"payload\" <> '{}'::jsonb",
            name="SnapshotSeriesRebuildJob_payload_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(\"checkpoint\") = 'object'",
            name="SnapshotSeriesRebuildJob_checkpoint_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(\"progress\") = 'object'", name="SnapshotSeriesRebuildJob_progress_object"
        ),
        sa.CheckConstraint(
            '"result" IS NULL OR jsonb_typeof("result") = \'object\'',
            name="SnapshotSeriesRebuildJob_result_object",
        ),
        sa.CheckConstraint(
            'char_length("idempotencyKey") BETWEEN 1 AND 200',
            name="SnapshotSeriesRebuildJob_idempotencyKey_bounded",
        ),
        sa.CheckConstraint(
            '"attemptCount" >= 0 AND "attemptCount" <= "maxAttempts" AND "maxAttempts" BETWEEN 1 AND 20',
            name="SnapshotSeriesRebuildJob_attempts_valid",
        ),
        sa.CheckConstraint(
            '"leaseVersion" >= 0', name="SnapshotSeriesRebuildJob_leaseVersion_nonnegative"
        ),
        sa.CheckConstraint(
            '(("leaseOwner" IS NULL AND "leaseExpiresAt" IS NULL AND "leaseHeartbeatAt" IS NULL) OR ("leaseOwner" IS NOT NULL AND "leaseExpiresAt" IS NOT NULL AND "leaseHeartbeatAt" IS NOT NULL))',
            name="SnapshotSeriesRebuildJob_lease_complete_or_absent",
        ),
        sa.CheckConstraint(
            '("status" = \'running\'::"BackgroundJobStatus") = ("leaseOwner" IS NOT NULL)',
            name="SnapshotSeriesRebuildJob_running_has_lease",
        ),
        sa.CheckConstraint(
            '(("status" IN (\'completed\'::"BackgroundJobStatus", \'failed\'::"BackgroundJobStatus")) = ("finishedAt" IS NOT NULL))',
            name="SnapshotSeriesRebuildJob_terminal_has_finishedAt",
        ),
        sa.CheckConstraint(
            '("status" = \'completed\'::"BackgroundJobStatus") = ("result" IS NOT NULL)',
            name="SnapshotSeriesRebuildJob_completed_has_result",
        ),
        sa.CheckConstraint(
            '(("errorCode" IS NULL AND "errorMessage" IS NULL) OR ("errorCode" IS NOT NULL AND "errorMessage" IS NOT NULL))',
            name="SnapshotSeriesRebuildJob_error_pair_complete",
        ),
        sa.ForeignKeyConstraint(
            ["userId"], ["public.User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requestedByBackgroundJobId", "userId"],
            ["public.BackgroundJob.id", "public.BackgroundJob.userId"],
            name="SnapshotSeriesRebuildJob_requested_background_job_user_fkey",
            onupdate="CASCADE",
            ondelete='SET NULL ("requestedByBackgroundJobId")',
        ),
        schema="public",
    )
    op.create_index(
        "SnapshotSeriesRebuildJob_user_kind_idempotency_key",
        "SnapshotSeriesRebuildJob",
        ["userId", "kind", "idempotencyKey"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "SnapshotSeriesRebuildJob_id_user_key",
        "SnapshotSeriesRebuildJob",
        ["id", "userId"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "SnapshotSeriesRebuildJob_claim_idx",
        "SnapshotSeriesRebuildJob",
        ["status", "runAfter", "leaseExpiresAt", "createdAt"],
        postgresql_where=sa.text(
            '"status" IN (\'queued\'::"BackgroundJobStatus", \'retry_wait\'::"BackgroundJobStatus")'
        ),
        schema="public",
    )
    op.create_index(
        "SnapshotSeriesRebuildJob_one_running_per_user_key",
        "SnapshotSeriesRebuildJob",
        ["userId"],
        unique=True,
        postgresql_where=sa.text('"status" = \'running\'::"BackgroundJobStatus"'),
        schema="public",
    )
    op.create_table(
        "SnapshotSeriesDirtyState",
        sa.Column(
            "userId",
            sa.Text(),
            sa.ForeignKey("public.User.id", onupdate="CASCADE", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("dirtyFrom", _TIMESTAMP, nullable=False),
        sa.Column("dirtyEpoch", sa.BigInteger(), nullable=False),
        sa.Column("scopeDirty", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reasonMask", sa.Integer(), nullable=False),
        sa.Column("requestedAt", _TIMESTAMP, nullable=False),
        sa.Column("updatedAt", _TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            '"dirtyEpoch" >= 1 AND "reasonMask" >= 1', name="SnapshotSeriesDirtyState_valid"
        ),
        schema="public",
    )
    op.create_table(
        "SnapshotSeriesCanonicalInvalidation",
        sa.Column(
            "userId",
            sa.Text(),
            sa.ForeignKey("public.User.id", onupdate="CASCADE", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "accountId",
            sa.Text(),
            sa.ForeignKey("public.Account.id", onupdate="CASCADE", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("canonicalRevision", sa.BigInteger(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("entityId", sa.Text(), nullable=False),
        sa.Column("financialTimestamp", _TIMESTAMP, nullable=False),
        sa.Column("firstDirtyEpoch", sa.BigInteger(), nullable=False),
        sa.Column("invalidatedAt", _TIMESTAMP, nullable=False),
        sa.Column("resolvedAt", _TIMESTAMP),
        sa.Column("resolvedSnapshotGenerationId", sa.Text()),
        sa.CheckConstraint(
            '"firstDirtyEpoch" >= 1',
            name="SnapshotSeriesCanonicalInvalidation_firstDirtyEpoch_positive",
        ),
        sa.ForeignKeyConstraint(
            ["accountId", "canonicalRevision", "kind", "entityId", "financialTimestamp"],
            [
                "public.AccountCanonicalChange.accountId",
                "public.AccountCanonicalChange.revision",
                "public.AccountCanonicalChange.kind",
                "public.AccountCanonicalChange.entityId",
                "public.AccountCanonicalChange.financialTimestamp",
            ],
            name="SnapshotSeriesCanonicalInvalidation_canonical_change_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolvedSnapshotGenerationId"],
            ["public.SnapshotGeneration.id"],
            name="SnapshotSeriesCanonicalInvalidation_resolved_generation_fkey",
            onupdate="CASCADE",
            ondelete='SET NULL ("resolvedSnapshotGenerationId")',
        ),
        schema="public",
    )
    op.create_index(
        "SnapshotSeriesCanonicalInvalidation_account_revision_idx",
        "SnapshotSeriesCanonicalInvalidation",
        ["accountId", "canonicalRevision"],
        schema="public",
    )
    op.create_table(
        "SnapshotSeriesScheduleState",
        sa.Column(
            "userId",
            sa.Text(),
            sa.ForeignKey("public.User.id", onupdate="CASCADE", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "timezone", sa.Text(), nullable=False, server_default=sa.text("'Europe/Prague'::text")
        ),
        sa.Column(
            "cadenceMinutes", sa.SmallInteger(), nullable=False, server_default=sa.text("30")
        ),
        sa.Column("nextCaptureAt", _TIMESTAMP, nullable=False),
        sa.Column("lastCapturedBucket", _TIMESTAMP),
        sa.Column("lastDirtyEpoch", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("updatedAt", _TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            '"timezone" = \'Europe/Prague\' AND "cadenceMinutes" = 30',
            name="SnapshotSeriesScheduleState_capture_policy",
        ),
        sa.CheckConstraint(
            'date_trunc(\'minute\', "nextCaptureAt") = "nextCaptureAt"',
            name="SnapshotSeriesScheduleState_nextCapture_minute_aligned",
        ),
        sa.CheckConstraint(
            '"lastDirtyEpoch" >= 0',
            name="SnapshotSeriesScheduleState_lastDirtyEpoch_nonnegative",
        ),
        schema="public",
    )
    op.create_index(
        "SnapshotSeriesScheduleState_due_idx",
        "SnapshotSeriesScheduleState",
        ["nextCaptureAt"],
        postgresql_where=sa.text('"enabled"'),
        schema="public",
    )
    # Only rebuild/capture jobs have a replacement; running leases become claimable retries.
    op.execute(
        """INSERT INTO "public"."SnapshotSeriesRebuildJob" ("id","userId","requestedByBackgroundJobId","kind","status","idempotencyKey","payload","checkpoint","progress","result","errorCode","errorMessage","attemptCount","manualRetryCount","maxAttempts","runAfter","leaseOwner","leaseVersion","leaseExpiresAt","leaseHeartbeatAt","startedAt","finishedAt","createdAt","updatedAt") SELECT "id","userId","requestedByBackgroundJobId", CASE "kind" WHEN 'history_rebuild'::"PortfolioHistoryJobKind" THEN 'rebuild'::"SnapshotSeriesJobKind" ELSE 'capture'::"SnapshotSeriesJobKind" END, CASE WHEN "status" = 'running'::"BackgroundJobStatus" THEN 'retry_wait'::"BackgroundJobStatus" ELSE "status" END, "idempotencyKey","payload","checkpoint","progress","result","errorCode","errorMessage", CASE WHEN "status" = 'running'::"BackgroundJobStatus" THEN GREATEST("attemptCount" - 1, 0) ELSE "attemptCount" END,"manualRetryCount","maxAttempts", CASE WHEN "status" = 'running'::"BackgroundJobStatus" THEN CURRENT_TIMESTAMP ELSE "runAfter" END, NULL, "leaseVersion", NULL, NULL, "startedAt","finishedAt","createdAt","updatedAt" FROM "public"."PortfolioHistoryJob" WHERE "kind" IN ('history_rebuild'::"PortfolioHistoryJobKind", 'snapshot_capture'::"PortfolioHistoryJobKind")"""
    )
    op.execute(
        'INSERT INTO "public"."SnapshotSeriesDirtyState" SELECT * FROM "public"."PortfolioHistoryDirtyState" ON CONFLICT ("userId") DO NOTHING'
    )
    op.execute(
        'INSERT INTO "public"."SnapshotSeriesCanonicalInvalidation" ("userId","accountId","canonicalRevision","kind","entityId","financialTimestamp","firstDirtyEpoch","invalidatedAt") SELECT "userId","accountId","canonicalRevision","kind","entityId","financialTimestamp","firstDirtyEpoch","invalidatedAt" FROM "public"."PortfolioHistoryCanonicalInvalidation" ON CONFLICT ("userId","accountId","canonicalRevision") DO NOTHING'
    )
    op.execute(
        """INSERT INTO "public"."SnapshotSeriesScheduleState" ("userId","enabled","timezone","cadenceMinutes","nextCaptureAt","lastCapturedBucket","lastDirtyEpoch","updatedAt")
        SELECT old."userId",old."enabled",old."timezone",old."cadenceMinutes",old."nextCaptureAt",old."lastCapturedBucket",
          GREATEST(
            COALESCE(dirty."dirtyEpoch", 0),
            COALESCE((SELECT max(receipt."firstDirtyEpoch") FROM "public"."PortfolioHistoryCanonicalInvalidation" receipt WHERE receipt."userId"=old."userId"), 0),
            COALESCE((SELECT max(CASE WHEN job."payload"->>'dirty_epoch' ~ '^[0-9]+$' THEN (job."payload"->>'dirty_epoch')::bigint END) FROM "public"."PortfolioHistoryJob" job WHERE job."userId"=old."userId" AND job."kind"='history_rebuild'::"PortfolioHistoryJobKind"), 0)
          ),old."updatedAt"
        FROM "public"."PortfolioHistoryScheduleState" old
        LEFT JOIN "public"."PortfolioHistoryDirtyState" dirty ON dirty."userId"=old."userId"
        ON CONFLICT ("userId") DO NOTHING"""
    )


def downgrade() -> None:
    op.drop_table("SnapshotSeriesScheduleState", schema="public")
    op.drop_table("SnapshotSeriesCanonicalInvalidation", schema="public")
    op.drop_table("SnapshotSeriesDirtyState", schema="public")
    op.drop_table("SnapshotSeriesRebuildJob", schema="public")
    op.execute('DROP TYPE "public"."SnapshotSeriesJobKind"')
