"""Remove retired PortfolioHistory persistence after the SnapshotSeries cutover.

Revision ID: 3z0001historydrop
Revises: 3y0001snapshotjobs
"""

from collections.abc import Sequence

from alembic import op

revision: str = "3z0001historydrop"
down_revision: str | None = "3y0001snapshotjobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
schema_change = True
schema_change_kind = "drop_legacy_portfolio_history_persistence"
affected_tables = (
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
)
data_migration = True
destructive = True
irreversible = True


def _preflight() -> None:
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM "public"."PortfolioHistoryJob" WHERE "leaseOwner" IS NOT NULL AND ("leaseExpiresAt" IS NULL OR "leaseExpiresAt" > CURRENT_TIMESTAMP)) THEN RAISE EXCEPTION 'legacy PortfolioHistory job lease is still active'; END IF;
      IF EXISTS (SELECT 1 FROM "public"."PortfolioHistoryJob" old WHERE old."kind" IN ('history_rebuild'::"PortfolioHistoryJobKind", 'snapshot_capture'::"PortfolioHistoryJobKind") AND NOT EXISTS (SELECT 1 FROM "public"."SnapshotSeriesRebuildJob" replacement WHERE replacement.id=old.id AND replacement."userId"=old."userId")) THEN RAISE EXCEPTION 'legacy rebuild/capture job lacks SnapshotSeries migration proof'; END IF;
      IF EXISTS (SELECT 1 FROM "public"."PortfolioHistoryDirtyState" old WHERE NOT EXISTS (SELECT 1 FROM "public"."SnapshotSeriesDirtyState" replacement WHERE replacement."userId"=old."userId" AND replacement."dirtyEpoch"=old."dirtyEpoch" AND replacement."dirtyFrom"=old."dirtyFrom")) THEN RAISE EXCEPTION 'legacy dirty state lacks SnapshotSeries migration proof'; END IF;
      IF EXISTS (SELECT 1 FROM "public"."PortfolioHistoryCanonicalInvalidation" old WHERE NOT EXISTS (SELECT 1 FROM "public"."SnapshotSeriesCanonicalInvalidation" replacement WHERE replacement."userId"=old."userId" AND replacement."accountId"=old."accountId" AND replacement."canonicalRevision"=old."canonicalRevision" AND replacement."firstDirtyEpoch"=old."firstDirtyEpoch")) THEN RAISE EXCEPTION 'legacy canonical invalidation lacks SnapshotSeries migration proof'; END IF;
      IF EXISTS (SELECT 1 FROM "public"."PortfolioHistoryScheduleState" old WHERE NOT EXISTS (SELECT 1 FROM "public"."SnapshotSeriesScheduleState" replacement WHERE replacement."userId"=old."userId" AND replacement."nextCaptureAt"=old."nextCaptureAt" AND replacement."lastCapturedBucket" IS NOT DISTINCT FROM old."lastCapturedBucket")) THEN RAISE EXCEPTION 'legacy capture schedule lacks SnapshotSeries migration proof'; END IF;
      IF EXISTS (
        SELECT 1
        FROM "public"."PortfolioHistoryPublication" old
        JOIN "public"."PortfolioHistoryGeneration" old_generation
          ON old_generation."id" = old."generationId"
         AND old_generation."userId" = old."userId"
        WHERE NOT EXISTS (
          SELECT 1 FROM "public"."UserReadModelPublication" current
          WHERE current."userId" = old."userId"
            AND current."publishedAt" >= old."publishedAt"
            AND EXISTS (
              SELECT 1
              FROM "public"."DailySnapshotBaseline" baseline
              WHERE baseline."userId" = current."userId"
                AND baseline."generationId" = current."generationId"
              GROUP BY baseline."userId", baseline."generationId"
              HAVING min(baseline."timestamp") <= old_generation."replayFrom"
                 AND max(baseline."timestamp") >= old_generation."coveredThrough"
            )
        )
        AND NOT EXISTS (
          SELECT 1 FROM "public"."SnapshotSeriesRebuildJob" replacement
          WHERE replacement."userId" = old."userId"
            AND replacement."kind" = 'rebuild'::"SnapshotSeriesJobKind"
            AND replacement."status" IN (
              'queued'::"BackgroundJobStatus",
              'retry_wait'::"BackgroundJobStatus"
            )
            AND replacement."attemptCount" < replacement."maxAttempts"
        )
      ) THEN RAISE EXCEPTION 'legacy publication lacks complete SnapshotSeries coverage or a claimable durable rebuild'; END IF;
      IF EXISTS (SELECT 1 FROM "public"."PortfolioHistoryCoverageSegment" coverage LEFT JOIN "public"."PortfolioHistoryGeneration" generation ON generation.id=coverage."generationId" LEFT JOIN "public"."PortfolioHistoryJob" job ON job.id=generation."requestedByHistoryJobId" AND job."userId"=generation."userId" WHERE generation.id IS NULL OR job.id IS NULL) THEN RAISE EXCEPTION 'legacy coverage lacks an auditable job identity proof'; END IF;
    END $$""")


def upgrade() -> None:
    _preflight()
    op.create_check_constraint(
        "UserReadModelPublication_generation_published",
        "UserReadModelPublication",
        "\"generationState\" = 'published'",
        schema="public",
    )
    for table in (
        "PortfolioHistoryPointPriceEvidence",
        "PortfolioHistoryPointFxEvidence",
        "PortfolioHistoryAccountPoint",
        "PortfolioHistoryCoverageSegment",
        "PortfolioHistoryPoint",
        "PortfolioHistoryReplayCheckpoint",
        "PortfolioHistoryGenerationCleanupReceipt",
        "PortfolioHistoryGenerationAccount",
        "PortfolioHistoryPublication",
        "PortfolioHistoryCanonicalInvalidation",
        "PortfolioHistoryDirtyState",
        "PortfolioHistoryScheduleState",
        "PortfolioHistoryGeneration",
        "PortfolioHistoryJob",
    ):
        op.drop_table(table, schema="public")
    for enum in (
        "PortfolioHistoryJobKind",
        "PortfolioHistoryCoverageStatus",
        "PortfolioHistoryPointKind",
        "HistoryGenerationBuildCause",
        "HistoryGenerationState",
    ):
        op.execute(f'DROP TYPE "public"."{enum}"')


def downgrade() -> None:
    raise RuntimeError(
        "3z cleanup is intentionally irreversible; rebuild snapshots from preserved canonical and market evidence"
    )
