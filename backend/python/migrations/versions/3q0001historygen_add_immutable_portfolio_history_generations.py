"""Add immutable versioned portfolio-history persistence.

Revision ID: 3q0001historygen
Revises: 3p0001rbfoundation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3q0001historygen"
down_revision: str | None = "3p0001rbfoundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_immutable_portfolio_history_generations"
affected_tables = (
    "AccountCanonicalChange",
    "PriceSnapshot",
    "PortfolioHistoryJob",
    "PortfolioHistoryGeneration",
    "PortfolioHistoryGenerationAccount",
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
prisma_schema_impact = "required"
data_migration = True

_STATUS = postgresql.ENUM(name="BackgroundJobStatus", schema="public", create_type=False)
_ACCOUNT_TYPE = postgresql.ENUM(name="AccountType", schema="public", create_type=False)
_GENERATION_STATE = postgresql.ENUM(
    name="HistoryGenerationState", schema="public", create_type=False
)
_GENERATION_BUILD_CAUSE = postgresql.ENUM(
    name="HistoryGenerationBuildCause", schema="public", create_type=False
)
_POINT_KIND = postgresql.ENUM(name="PortfolioHistoryPointKind", schema="public", create_type=False)
_COVERAGE_STATUS = postgresql.ENUM(
    name="PortfolioHistoryCoverageStatus", schema="public", create_type=False
)
_JOB_KIND = postgresql.ENUM(name="PortfolioHistoryJobKind", schema="public", create_type=False)
_JSONB = postgresql.JSONB(astext_type=sa.Text())
_TIMESTAMP = postgresql.TIMESTAMP(precision=3)
PORTFOLIO_HISTORY_LATTICE_LEVEL_RESOLUTIONS: tuple[tuple[int, int], ...] = (
    (0, 30),
    (1, 120),
    (2, 360),
    (3, 720),
    (4, 1_440),
    (5, 2_880),
    (6, 5_760),
    (7, 11_520),
    (8, 23_040),
    (9, 46_080),
    (10, 92_160),
    (11, 184_320),
    (12, 368_640),
    (13, 737_280),
    (14, 1_474_560),
    (15, 2_949_120),
    (16, 5_898_240),
    (17, 11_796_480),
)
_LATTICE_IDENTITY_CHECK = " OR ".join(
    f'("level" = {level} AND "resolutionMinutes" = {minutes})'
    for level, minutes in PORTFOLIO_HISTORY_LATTICE_LEVEL_RESOLUTIONS
)


def _published_import_predicate(root_alias: str) -> str:
    """Return the H5 fail-closed, per-member imported-root visibility predicate."""
    return (
        f'((SELECT count(*) FROM "public"."ImportJobBatch" AS provenance_count '
        f'WHERE provenance_count."batchId"={root_alias}."importBatchId") = 1 '
        'AND EXISTS (SELECT 1 FROM "public"."ImportBatch" AS batch '
        'JOIN "public"."ImportJobBatch" AS provenance '
        'ON provenance."batchId"=batch.id AND provenance."userId"=batch."userId" '
        'AND provenance."accountId"=batch."accountId" '
        'JOIN "public"."BackgroundJob" AS job ON job.id=provenance."jobId" '
        'AND job."userId"=provenance."userId" '
        'AND job."accountId"=provenance."accountId" '
        'JOIN "public"."ImportJobPublicationTarget" AS target '
        'ON target."jobId"=job.id AND target."userId"=member."userId" '
        f'WHERE batch.id={root_alias}."importBatchId" '
        f'AND batch."accountId"={root_alias}."accountId" '
        "AND batch.status IN ('completed'::\"ImportStatus\","
        '\'partially_completed\'::"ImportStatus") AND batch."completedAt" IS NOT NULL '
        "AND job.kind='import_workflow'::\"BackgroundJobKind\" "
        "AND job.status='completed'::\"BackgroundJobStatus\" "
        'AND target."publishedAt" IS NOT NULL))'
    )


def _eligible_history_change_select() -> str:
    """Select exactly the canonical roots visible to H5 for each current member."""
    columns = (
        'member."userId" AS "userId",change."accountId" AS "accountId",'
        'change.revision,change.kind,change."entityId",change."financialTimestamp"'
    )
    common = (
        'FROM "public"."AccountMember" AS member '
        'JOIN "public"."Account" AS account ON account.id=member."accountId" '
        'JOIN "public"."AccountCanonicalChange" AS change '
        'ON change."accountId"=member."accountId" '
    )
    active = 'member."acceptedAt" IS NOT NULL AND NOT account."isArchived"'
    transaction = (
        f"SELECT {columns} {common}"
        'JOIN "public"."Transaction" AS root ON root.id=change."entityId" '
        'AND root."accountId"=change."accountId" '
        'AND root.date=change."financialTimestamp" '
        f"WHERE {active} AND change.kind='transaction' "
        'AND root."archivedAt" IS NULL AND root."deletedAt" IS NULL '
        'AND root.classification IS NOT NULL AND (root."importBatchId" IS NULL OR '
        f"{_published_import_predicate('root')})"
    )
    investment = (
        f"SELECT {columns} {common}"
        'JOIN "public"."InvestmentEvent" AS root ON root.id=change."entityId" '
        'AND root."accountId"=change."accountId" '
        'AND root.date=change."financialTimestamp" '
        f"WHERE {active} AND change.kind='investment_event' "
        'AND root."archivedAt" IS NULL AND root."deletedAt" IS NULL '
        'AND (root."importBatchId" IS NULL OR '
        f"{_published_import_predicate('root')})"
    )
    liability = (
        f"SELECT {columns} {common}"
        'JOIN "public"."LiabilityBalance" AS root ON root.id=change."entityId" '
        'AND root."accountId"=change."accountId" '
        'AND root."effectiveAt"=change."financialTimestamp" '
        f"WHERE {active} AND change.kind='liability_balance'"
    )
    return f"{transaction} UNION ALL {investment} UNION ALL {liability}"


def _create_types() -> None:
    for name, values in (
        ("HistoryGenerationState", ("building", "verified", "failed", "superseded")),
        ("HistoryGenerationBuildCause", ("rebuild", "capture", "compaction")),
        ("PortfolioHistoryPointKind", ("replayed_close", "rollup_close")),
        ("PortfolioHistoryCoverageStatus", ("complete", "missing_evidence")),
        (
            "PortfolioHistoryJobKind",
            ("history_rebuild", "snapshot_capture", "history_compaction", "history_audit"),
        ),
    ):
        quoted = ", ".join(f"'{value}'" for value in values)
        op.execute(f'CREATE TYPE "public"."{name}" AS ENUM ({quoted})')


def upgrade() -> None:
    _create_types()
    op.create_index(
        "AccountCanonicalChange_exact_identity_key",
        "AccountCanonicalChange",
        ["accountId", "revision", "kind", "entityId", "financialTimestamp"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "PriceSnapshot_id_listingId_key",
        "PriceSnapshot",
        ["id", "listingId"],
        unique=True,
        schema="public",
    )
    op.create_table(
        "PortfolioHistoryJob",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("requestedByBackgroundJobId", sa.Text()),
        sa.Column("kind", _JOB_KIND, nullable=False),
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
        sa.Column("result", _JSONB, nullable=True),
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
            name="PortfolioHistoryJob_payload_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(\"checkpoint\") = 'object'", name="PortfolioHistoryJob_checkpoint_object"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(\"progress\") = 'object'", name="PortfolioHistoryJob_progress_object"
        ),
        sa.CheckConstraint(
            '"result" IS NULL OR jsonb_typeof("result") = \'object\'',
            name="PortfolioHistoryJob_result_object",
        ),
        sa.CheckConstraint(
            'octet_length("payload"::text) <= 65536', name="PortfolioHistoryJob_payload_bounded"
        ),
        sa.CheckConstraint(
            'octet_length("checkpoint"::text) <= 65536',
            name="PortfolioHistoryJob_checkpoint_bounded",
        ),
        sa.CheckConstraint(
            'octet_length("progress"::text) <= 16384', name="PortfolioHistoryJob_progress_bounded"
        ),
        sa.CheckConstraint(
            '"result" IS NULL OR octet_length("result"::text) <= 65536',
            name="PortfolioHistoryJob_result_bounded",
        ),
        sa.CheckConstraint(
            'char_length("idempotencyKey") BETWEEN 1 AND 200',
            name="PortfolioHistoryJob_idempotencyKey_bounded",
        ),
        sa.CheckConstraint(
            '"attemptCount" >= 0 AND "attemptCount" <= "maxAttempts"',
            name="PortfolioHistoryJob_attemptCount_valid",
        ),
        sa.CheckConstraint(
            '"manualRetryCount" >= 0', name="PortfolioHistoryJob_manualRetryCount_nonnegative"
        ),
        sa.CheckConstraint(
            '"maxAttempts" BETWEEN 1 AND 20', name="PortfolioHistoryJob_maxAttempts_bounded"
        ),
        sa.CheckConstraint(
            '"leaseVersion" >= 0', name="PortfolioHistoryJob_leaseVersion_nonnegative"
        ),
        sa.CheckConstraint(
            '(("leaseOwner" IS NULL AND "leaseExpiresAt" IS NULL AND "leaseHeartbeatAt" IS NULL) OR ("leaseOwner" IS NOT NULL AND "leaseExpiresAt" IS NOT NULL AND "leaseHeartbeatAt" IS NOT NULL))',
            name="PortfolioHistoryJob_lease_complete_or_absent",
        ),
        sa.CheckConstraint(
            '("status" = \'running\'::"BackgroundJobStatus") = ("leaseOwner" IS NOT NULL)',
            name="PortfolioHistoryJob_running_has_lease",
        ),
        sa.CheckConstraint(
            '(("status" IN (\'completed\'::"BackgroundJobStatus", \'failed\'::"BackgroundJobStatus")) = ("finishedAt" IS NOT NULL))',
            name="PortfolioHistoryJob_terminal_has_finishedAt",
        ),
        sa.CheckConstraint(
            '("status" = \'completed\'::"BackgroundJobStatus") = ("result" IS NOT NULL)',
            name="PortfolioHistoryJob_completed_has_result",
        ),
        sa.CheckConstraint(
            '(("errorCode" IS NULL AND "errorMessage" IS NULL) OR ("errorCode" IS NOT NULL AND "errorMessage" IS NOT NULL))',
            name="PortfolioHistoryJob_error_pair_complete",
        ),
        sa.ForeignKeyConstraint(
            ["userId"], ["public.User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["requestedByBackgroundJobId", "userId"],
            ["public.BackgroundJob.id", "public.BackgroundJob.userId"],
            name="PortfolioHistoryJob_requested_background_job_user_fkey",
            onupdate="CASCADE",
            ondelete='SET NULL ("requestedByBackgroundJobId")',
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="public",
    )
    for name, cols, where, unique in (
        ("PortfolioHistoryJob_user_created_idx", ["userId", "createdAt"], None, False),
        (
            "PortfolioHistoryJob_claim_idx",
            ["status", "runAfter", "leaseExpiresAt", "createdAt"],
            '"status" IN (\'queued\'::"BackgroundJobStatus", \'retry_wait\'::"BackgroundJobStatus")',
            False,
        ),
        (
            "PortfolioHistoryJob_expiredLease_idx",
            ["leaseExpiresAt"],
            '"status" = \'running\'::"BackgroundJobStatus"',
            False,
        ),
        (
            "PortfolioHistoryJob_one_running_per_user_key",
            ["userId"],
            '"status" = \'running\'::"BackgroundJobStatus"',
            True,
        ),
        (
            "PortfolioHistoryJob_userId_kind_idempotencyKey_key",
            ["userId", "kind", "idempotencyKey"],
            None,
            True,
        ),
        ("PortfolioHistoryJob_id_user_key", ["id", "userId"], None, True),
    ):
        op.create_index(
            name,
            "PortfolioHistoryJob",
            cols,
            unique=unique,
            schema="public",
            postgresql_where=sa.text(where) if where else None,
        )
    op.create_table(
        "PortfolioHistoryGeneration",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("parentGenerationId", sa.Text()),
        sa.Column("parentGenerationHash", sa.Text()),
        sa.Column("parentPublicationVersion", sa.BigInteger()),
        sa.Column("inputGenerationId", sa.Text()),
        sa.Column("inputGenerationHash", sa.Text()),
        sa.Column("requestedByHistoryJobId", sa.Text(), nullable=False),
        sa.Column(
            "state",
            _GENERATION_STATE,
            nullable=False,
            server_default=sa.text("'building'::\"HistoryGenerationState\""),
        ),
        sa.Column("policyVersion", sa.Integer(), nullable=False),
        sa.Column("calculationVersion", sa.Integer(), nullable=False),
        sa.Column("baseCurrency", sa.Text(), nullable=False),
        sa.Column("buildCause", _GENERATION_BUILD_CAUSE, nullable=False),
        sa.Column("buildDirtyEpoch", sa.BigInteger()),
        sa.Column(
            "timezone", sa.Text(), nullable=False, server_default=sa.text("'Europe/Prague'::text")
        ),
        sa.Column("buildFrom", _TIMESTAMP, nullable=False),
        sa.Column("replayFrom", _TIMESTAMP, nullable=False),
        sa.Column("coveredThrough", _TIMESTAMP),
        sa.Column("canonicalInputHash", sa.Text(), nullable=False),
        sa.Column("scopeHash", sa.Text(), nullable=False),
        sa.Column("failureCode", sa.Text()),
        sa.Column("failureMessage", sa.Text()),
        sa.Column("createdAt", _TIMESTAMP, nullable=False),
        sa.Column("verifiedAt", _TIMESTAMP),
        sa.Column("finishedAt", _TIMESTAMP),
        sa.CheckConstraint(
            '"policyVersion" >= 1 AND "calculationVersion" >= 1 AND ("buildDirtyEpoch" IS NULL OR "buildDirtyEpoch" >= 1)',
            name="PortfolioHistoryGeneration_versions_positive",
        ),
        sa.CheckConstraint(
            "\"baseCurrency\" ~ '^[A-Z]{3}$'",
            name="PortfolioHistoryGeneration_baseCurrency_iso4217",
        ),
        sa.CheckConstraint(
            "\"timezone\" = 'Europe/Prague'", name="PortfolioHistoryGeneration_timezone_prague"
        ),
        sa.CheckConstraint(
            "\"scopeHash\" ~ '^[0-9a-f]{64}$'", name="PortfolioHistoryGeneration_scopeHash_sha256"
        ),
        sa.CheckConstraint(
            "\"canonicalInputHash\" ~ '^[0-9a-f]{64}$'",
            name="PortfolioHistoryGeneration_canonicalInputHash_sha256",
        ),
        sa.CheckConstraint(
            '"replayFrom" <= "buildFrom"', name="PortfolioHistoryGeneration_replay_before_build"
        ),
        sa.CheckConstraint(
            '"coveredThrough" IS NULL OR "coveredThrough" >= "replayFrom"',
            name="PortfolioHistoryGeneration_coverage_after_replay",
        ),
        sa.CheckConstraint(
            '("parentGenerationId" IS NULL) = ("parentGenerationHash" IS NULL) AND ("parentGenerationId" IS NULL) = ("parentPublicationVersion" IS NULL) AND ("inputGenerationId" IS NULL) = ("inputGenerationHash" IS NULL)',
            name="PortfolioHistoryGeneration_parent_input_hash_pair",
        ),
        sa.CheckConstraint(
            '"parentPublicationVersion" IS NULL OR "parentPublicationVersion" > 0',
            name="PortfolioHistoryGeneration_parent_publication_positive",
        ),
        sa.CheckConstraint(
            '("buildCause" = \'rebuild\'::"HistoryGenerationBuildCause" AND "buildDirtyEpoch" IS NOT NULL AND "inputGenerationId" IS NULL) OR '
            '("buildCause" = \'capture\'::"HistoryGenerationBuildCause" AND "buildDirtyEpoch" IS NULL AND "parentGenerationId" IS NOT NULL AND "inputGenerationId" IS NULL) OR '
            '("buildCause" = \'compaction\'::"HistoryGenerationBuildCause" AND "buildDirtyEpoch" IS NULL AND "parentGenerationId" IS NOT NULL AND "inputGenerationId" = "parentGenerationId" AND "inputGenerationHash" = "parentGenerationHash")',
            name="PortfolioHistoryGeneration_build_cause_shape",
        ),
        sa.CheckConstraint(
            '("parentGenerationHash" IS NULL OR "parentGenerationHash" ~ \'^[0-9a-f]{64}$\') AND ("inputGenerationHash" IS NULL OR "inputGenerationHash" ~ \'^[0-9a-f]{64}$\')',
            name="PortfolioHistoryGeneration_parent_input_hash_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["userId"], ["public.User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parentGenerationId"],
            ["public.PortfolioHistoryGeneration.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["inputGenerationId"],
            ["public.PortfolioHistoryGeneration.id"],
            onupdate="CASCADE",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requestedByHistoryJobId", "userId"],
            ["public.PortfolioHistoryJob.id", "public.PortfolioHistoryJob.userId"],
            name="PortfolioHistoryGeneration_requested_history_job_user_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="public",
    )
    for name, cols, where, unique in (
        ("PortfolioHistoryGeneration_id_user_key", ["id", "userId"], None, True),
        ("PortfolioHistoryGeneration_user_created_idx", ["userId", "createdAt"], None, False),
        (
            "PortfolioHistoryGeneration_active_idx",
            ["userId", "state"],
            '"state" IN (\'building\'::"HistoryGenerationState", \'verified\'::"HistoryGenerationState")',
            False,
        ),
        ("PortfolioHistoryGeneration_parent_idx", ["parentGenerationId"], None, False),
        (
            "PortfolioHistoryGeneration_one_building_per_user_key",
            ["userId"],
            '"state" = \'building\'::"HistoryGenerationState"',
            True,
        ),
    ):
        op.create_index(
            name,
            "PortfolioHistoryGeneration",
            cols,
            unique=unique,
            schema="public",
            postgresql_where=sa.text(where) if where else None,
        )
    op.create_table(
        "PortfolioHistoryCanonicalInvalidation",
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("canonicalRevision", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("entityId", sa.Text(), nullable=False),
        sa.Column("financialTimestamp", _TIMESTAMP, nullable=False),
        sa.Column("firstDirtyEpoch", sa.BigInteger(), nullable=False),
        sa.Column("invalidatedAt", _TIMESTAMP, nullable=False),
        sa.Column("replayedGenerationId", sa.Text()),
        sa.CheckConstraint(
            '"firstDirtyEpoch" >= 1',
            name="PortfolioHistoryCanonicalInvalidation_firstDirtyEpoch_positive",
        ),
        sa.CheckConstraint(
            "\"kind\" IN ('transaction', 'investment_event', 'liability_balance')",
            name="PortfolioHistoryCanonicalInvalidation_kind_supported",
        ),
        sa.CheckConstraint(
            "btrim(\"entityId\") <> ''",
            name="PortfolioHistoryCanonicalInvalidation_entityId_nonblank",
        ),
        sa.ForeignKeyConstraint(
            ["userId"],
            ["public.User.id"],
            name="PortfolioHistoryCanonicalInvalidation_user_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["accountId"],
            ["public.Account.id"],
            name="PortfolioHistoryCanonicalInvalidation_account_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [
                "accountId",
                "canonicalRevision",
                "kind",
                "entityId",
                "financialTimestamp",
            ],
            [
                "public.AccountCanonicalChange.accountId",
                "public.AccountCanonicalChange.revision",
                "public.AccountCanonicalChange.kind",
                "public.AccountCanonicalChange.entityId",
                "public.AccountCanonicalChange.financialTimestamp",
            ],
            name="PortfolioHistoryCanonicalInvalidation_canonical_change_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["replayedGenerationId", "userId"],
            ["public.PortfolioHistoryGeneration.id", "public.PortfolioHistoryGeneration.userId"],
            name="PHCanonicalInvalidation_replayed_gen_user_fkey",
            onupdate="CASCADE",
            ondelete='SET NULL ("replayedGenerationId")',
        ),
        sa.PrimaryKeyConstraint("userId", "accountId", "canonicalRevision"),
        schema="public",
    )
    op.create_index(
        "PortfolioHistoryCanonicalInvalidation_account_revision_idx",
        "PortfolioHistoryCanonicalInvalidation",
        ["accountId", "canonicalRevision"],
        schema="public",
    )
    op.create_index(
        "PortfolioHistoryCanonicalInvalidation_replayed_generation_idx",
        "PortfolioHistoryCanonicalInvalidation",
        ["replayedGenerationId"],
        schema="public",
    )
    op.create_table(
        "PortfolioHistoryDirtyState",
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("dirtyFrom", _TIMESTAMP, nullable=False),
        sa.Column("dirtyEpoch", sa.BigInteger(), nullable=False),
        sa.Column("scopeDirty", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reasonMask", sa.Integer(), nullable=False),
        sa.Column("requestedAt", _TIMESTAMP, nullable=False),
        sa.Column("updatedAt", _TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            '"dirtyEpoch" >= 1 AND "reasonMask" >= 1', name="PortfolioHistoryDirtyState_valid"
        ),
        sa.ForeignKeyConstraint(
            ["userId"], ["public.User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("userId"),
        schema="public",
    )
    op.create_table(
        "PortfolioHistoryScheduleState",
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "timezone", sa.Text(), nullable=False, server_default=sa.text("'Europe/Prague'::text")
        ),
        sa.Column(
            "cadenceMinutes", sa.SmallInteger(), nullable=False, server_default=sa.text("30")
        ),
        sa.Column("nextCaptureAt", _TIMESTAMP, nullable=False),
        sa.Column("lastCapturedBucket", _TIMESTAMP),
        sa.Column("lastCompactedAt", _TIMESTAMP),
        sa.Column("lastAuditedAt", _TIMESTAMP),
        sa.Column("policyVersion", sa.Integer(), nullable=False),
        sa.Column("updatedAt", _TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            '"timezone" = \'Europe/Prague\' AND "cadenceMinutes" = 30 AND "policyVersion" >= 1',
            name="PortfolioHistoryScheduleState_policy",
        ),
        sa.CheckConstraint(
            'date_trunc(\'minute\', "nextCaptureAt") = "nextCaptureAt"',
            name="PortfolioHistoryScheduleState_nextCapture_minute_aligned",
        ),
        sa.ForeignKeyConstraint(
            ["userId"], ["public.User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("userId"),
        schema="public",
    )
    op.create_index(
        "PortfolioHistoryScheduleState_due_idx",
        "PortfolioHistoryScheduleState",
        ["nextCaptureAt"],
        schema="public",
        postgresql_where=sa.text('"enabled"'),
    )
    # Roll existing canonical history into the durable invalidation protocol.
    # Receipts use only current accepted memberships; a membership deleted
    # before this migration deliberately receives no historical evidence.
    op.execute(
        sa.text(
            'INSERT INTO "public"."PortfolioHistoryCanonicalInvalidation" '
            '("userId","accountId","canonicalRevision",kind,"entityId",'
            '"financialTimestamp","firstDirtyEpoch","invalidatedAt",'
            '"replayedGenerationId") '
            'SELECT eligible."userId",eligible."accountId",eligible.revision,eligible.kind,'
            'eligible."entityId",eligible."financialTimestamp",1,'
            "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),NULL "
            f"FROM ({_eligible_history_change_select()}) AS eligible "
            'ON CONFLICT ("userId","accountId","canonicalRevision") DO NOTHING'
        )
    )
    # Dirty replay starts at the earliest currently eligible active-account
    # root. Archived accounts keep receipts but cannot widen the active scope.
    op.execute(
        sa.text(
            'INSERT INTO "public"."PortfolioHistoryDirtyState" '
            '("userId","dirtyFrom","dirtyEpoch","scopeDirty","reasonMask",'
            '"requestedAt","updatedAt") '
            'SELECT eligible."userId",MIN(eligible."financialTimestamp"),1,false,1,'
            "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),"
            "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC') "
            f"FROM ({_eligible_history_change_select()}) AS eligible "
            'GROUP BY eligible."userId"'
        )
    )
    # Only users with seeded canonical dirty work enter the scheduler lattice.
    # Users whose last membership was removed have no current financial scope;
    # seeding them would create a permanent boundary_required scheduler loop.
    # The last closed UTC half-hour is also an exact Europe/Prague half-hour
    # boundary, including both DST transitions, and is immediately due.
    op.execute(
        sa.text(
            'INSERT INTO "public"."PortfolioHistoryScheduleState" '
            '("userId",enabled,timezone,"cadenceMinutes","nextCaptureAt",'
            '"lastCapturedBucket","lastCompactedAt","lastAuditedAt",'
            '"policyVersion","updatedAt") '
            "SELECT dirty.\"userId\",true,'Europe/Prague',30,"
            "date_bin(INTERVAL '30 minutes',"
            "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC'),TIMESTAMP '1970-01-01'),"
            "NULL,NULL,NULL,1,(CURRENT_TIMESTAMP AT TIME ZONE 'UTC') "
            'FROM "public"."PortfolioHistoryDirtyState" AS dirty'
        )
    )
    op.create_table(
        "PortfolioHistoryGenerationAccount",
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("accountType", _ACCOUNT_TYPE, nullable=False),
        sa.Column("accountCurrency", sa.Text(), nullable=False),
        sa.Column("targetCanonicalRevision", sa.BigInteger(), nullable=False),
        sa.Column("targetInvestmentRevision", sa.BigInteger()),
        sa.Column("targetHoldingRevision", sa.BigInteger()),
        sa.Column("earliestAffectedAt", _TIMESTAMP, nullable=False),
        sa.Column("createdAt", _TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            '"targetCanonicalRevision" >= 0 AND ("targetInvestmentRevision" IS NULL OR "targetInvestmentRevision" >= 0) AND ("targetHoldingRevision" IS NULL OR "targetHoldingRevision" >= 0)',
            name="PortfolioHistoryGenerationAccount_revisions_nonnegative",
        ),
        sa.CheckConstraint(
            '("targetInvestmentRevision" IS NULL) = ("targetHoldingRevision" IS NULL) AND ("targetInvestmentRevision" IS NULL OR "targetInvestmentRevision" = "targetHoldingRevision") AND ("targetInvestmentRevision" IS NULL OR "targetInvestmentRevision" <= "targetCanonicalRevision")',
            name="PortfolioHistoryGenerationAccount_holding_fresh",
        ),
        sa.CheckConstraint(
            "\"accountCurrency\" ~ '^[A-Z]{3}$'",
            name="PortfolioHistoryGenerationAccount_currency_iso4217",
        ),
        sa.ForeignKeyConstraint(
            ["generationId", "userId"],
            ["public.PortfolioHistoryGeneration.id", "public.PortfolioHistoryGeneration.userId"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["accountId"], ["public.Account.id"], onupdate="CASCADE", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("generationId", "accountId"),
        schema="public",
    )
    op.create_index(
        "PortfolioHistoryGenerationAccount_account_idx",
        "PortfolioHistoryGenerationAccount",
        ["accountId", "generationId"],
        schema="public",
    )
    op.create_table(
        "PortfolioHistoryPublication",
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("publicationVersion", sa.BigInteger(), nullable=False),
        sa.Column("publishedAt", _TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            '"publicationVersion" > 0', name="PortfolioHistoryPublication_version_positive"
        ),
        sa.ForeignKeyConstraint(
            ["userId"], ["public.User.id"], onupdate="CASCADE", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["generationId", "userId"],
            ["public.PortfolioHistoryGeneration.id", "public.PortfolioHistoryGeneration.userId"],
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("userId"),
        schema="public",
    )
    op.create_index(
        "PortfolioHistoryPublication_generation_key",
        "PortfolioHistoryPublication",
        ["generationId"],
        unique=True,
        schema="public",
    )
    op.create_table(
        "PortfolioHistoryReplayCheckpoint",
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("lastCanonicalRevision", sa.BigInteger(), nullable=False),
        sa.Column("eventTimestamp", _TIMESTAMP),
        sa.Column("eventRevision", sa.BigInteger()),
        sa.Column("throughTimestamp", _TIMESTAMP),
        sa.Column("state", _JSONB, nullable=False),
        sa.Column("stateHash", sa.Text(), nullable=False),
        sa.Column("updatedAt", _TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            '"lastCanonicalRevision" >= 0',
            name="PortfolioHistoryReplayCheckpoint_revision_nonnegative",
        ),
        sa.CheckConstraint(
            '("eventTimestamp" IS NULL) = ("eventRevision" IS NULL)',
            name="PortfolioHistoryReplayCheckpoint_cursor_pair",
        ),
        sa.CheckConstraint(
            '"eventRevision" IS NULL OR "eventRevision" >= 0',
            name="PortfolioHistoryReplayCheckpoint_eventRevision_nonnegative",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(\"state\") = 'object' AND \"state\" <> '{}'::jsonb",
            name="PortfolioHistoryReplayCheckpoint_state_object",
        ),
        sa.CheckConstraint(
            'octet_length("state"::text) <= 1048576',
            name="PortfolioHistoryReplayCheckpoint_state_bounded",
        ),
        sa.CheckConstraint(
            "\"stateHash\" ~ '^[0-9a-f]{64}$'",
            name="PortfolioHistoryReplayCheckpoint_stateHash_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["generationId", "accountId"],
            [
                "public.PortfolioHistoryGenerationAccount.generationId",
                "public.PortfolioHistoryGenerationAccount.accountId",
            ],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("generationId", "accountId"),
        schema="public",
    )
    op.create_table(
        "PortfolioHistoryPoint",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("resolutionMinutes", sa.Integer(), nullable=False),
        sa.Column("bucketStart", _TIMESTAMP, nullable=False),
        sa.Column("bucketEnd", _TIMESTAMP, nullable=False),
        sa.Column("representativeAt", _TIMESTAMP, nullable=False),
        sa.Column("cashValue", sa.Numeric(18, 6), nullable=False),
        sa.Column("portfolioValue", sa.Numeric(18, 6), nullable=False),
        sa.Column("liabilitiesValue", sa.Numeric(18, 6), nullable=False),
        sa.Column("netWorthOpen", sa.Numeric(18, 6), nullable=False),
        sa.Column("netWorthHigh", sa.Numeric(18, 6), nullable=False),
        sa.Column("netWorthLow", sa.Numeric(18, 6), nullable=False),
        sa.Column("netWorthClose", sa.Numeric(18, 6), nullable=False),
        sa.Column("sampleCount", sa.Integer(), nullable=False),
        sa.Column("pointKind", _POINT_KIND, nullable=False),
        sa.Column("inputManifestHash", sa.Text(), nullable=False),
        sa.Column("createdAt", _TIMESTAMP, nullable=False),
        sa.CheckConstraint('"sampleCount" >= 1', name="PortfolioHistoryPoint_shape_valid"),
        sa.CheckConstraint(_LATTICE_IDENTITY_CHECK, name="PortfolioHistoryPoint_lattice_identity"),
        sa.CheckConstraint(
            '"bucketStart" < "bucketEnd" AND "representativeAt" >= "bucketStart" AND "representativeAt" < "bucketEnd"',
            name="PortfolioHistoryPoint_bucket_valid",
        ),
        sa.CheckConstraint(
            '"cashValue" + "portfolioValue" - "liabilitiesValue" = "netWorthClose"',
            name="PortfolioHistoryPoint_netWorthClose_exact",
        ),
        sa.CheckConstraint(
            '"netWorthLow" <= "netWorthOpen" AND "netWorthOpen" <= "netWorthHigh" AND "netWorthLow" <= "netWorthClose" AND "netWorthClose" <= "netWorthHigh"',
            name="PortfolioHistoryPoint_netWorth_ohlc_ordered",
        ),
        sa.CheckConstraint(
            "\"inputManifestHash\" ~ '^[0-9a-f]{64}$'",
            name="PortfolioHistoryPoint_manifestHash_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["generationId"],
            ["public.PortfolioHistoryGeneration.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="public",
    )
    op.create_index(
        "PortfolioHistoryPoint_generation_resolution_bucket_idx",
        "PortfolioHistoryPoint",
        ["generationId", "resolutionMinutes", "bucketStart"],
        schema="public",
    )
    op.create_index(
        "PortfolioHistoryPoint_generation_resolution_bucket_key",
        "PortfolioHistoryPoint",
        ["generationId", "resolutionMinutes", "bucketStart"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "PortfolioHistoryPoint_id_generation_key",
        "PortfolioHistoryPoint",
        ["id", "generationId"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "PortfolioHistoryPoint_generation_representative_idx",
        "PortfolioHistoryPoint",
        ["generationId", "representativeAt"],
        schema="public",
    )
    op.create_table(
        "PortfolioHistoryAccountPoint",
        sa.Column("pointId", sa.Text(), nullable=False),
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("cashValue", sa.Numeric(18, 6), nullable=False),
        sa.Column("portfolioValue", sa.Numeric(18, 6), nullable=False),
        sa.Column("liabilitiesValue", sa.Numeric(18, 6), nullable=False),
        sa.Column("totalValue", sa.Numeric(18, 6), nullable=False),
        sa.CheckConstraint(
            "\"currency\" ~ '^[A-Z]{3}$'", name="PortfolioHistoryAccountPoint_currency_iso4217"
        ),
        sa.CheckConstraint(
            '"cashValue" + "portfolioValue" - "liabilitiesValue" = "totalValue"',
            name="PortfolioHistoryAccountPoint_total_exact",
        ),
        sa.ForeignKeyConstraint(
            ["pointId", "generationId"],
            ["public.PortfolioHistoryPoint.id", "public.PortfolioHistoryPoint.generationId"],
            name="PortfolioHistoryAccountPoint_point_generation_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["generationId", "accountId"],
            [
                "public.PortfolioHistoryGenerationAccount.generationId",
                "public.PortfolioHistoryGenerationAccount.accountId",
            ],
            name="PortfolioHistoryAccountPoint_generation_account_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("pointId", "generationId", "accountId"),
        schema="public",
    )
    op.create_index(
        "PortfolioHistoryAccountPoint_account_point_idx",
        "PortfolioHistoryAccountPoint",
        ["accountId", "pointId"],
        schema="public",
    )
    op.create_table(
        "PortfolioHistoryCoverageSegment",
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("resolutionMinutes", sa.Integer(), nullable=False),
        sa.Column("segmentStart", _TIMESTAMP, nullable=False),
        sa.Column("segmentEnd", _TIMESTAMP, nullable=False),
        sa.Column("pointCount", sa.Integer(), nullable=False),
        sa.Column("status", _COVERAGE_STATUS, nullable=False),
        sa.Column("reasonCode", sa.Text()),
        sa.Column("coverageHash", sa.Text(), nullable=False),
        sa.Column("createdAt", _TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            '"segmentStart" < "segmentEnd" AND "pointCount" >= 0',
            name="PortfolioHistoryCoverageSegment_shape_valid",
        ),
        sa.CheckConstraint(
            _LATTICE_IDENTITY_CHECK, name="PortfolioHistoryCoverageSegment_lattice_identity"
        ),
        sa.CheckConstraint(
            '("status" = \'complete\'::"PortfolioHistoryCoverageStatus" AND "pointCount" >= 1 AND "reasonCode" IS NULL) OR ("status" = \'missing_evidence\'::"PortfolioHistoryCoverageStatus" AND "pointCount" = 0 AND "reasonCode" IS NOT NULL)',
            name="PortfolioHistoryCoverageSegment_status_complete_or_gap",
        ),
        sa.CheckConstraint(
            "\"coverageHash\" ~ '^[0-9a-f]{64}$'",
            name="PortfolioHistoryCoverageSegment_hash_sha256",
        ),
        sa.ForeignKeyConstraint(
            ["generationId"],
            ["public.PortfolioHistoryGeneration.id"],
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("generationId", "level", "segmentStart"),
        schema="public",
    )
    op.create_index(
        "PortfolioHistoryCoverageSegment_generation_level_start_idx",
        "PortfolioHistoryCoverageSegment",
        ["generationId", "level", "segmentStart"],
        schema="public",
    )
    op.create_table(
        "PortfolioHistoryPointPriceEvidence",
        sa.Column("pointId", sa.Text(), nullable=False),
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("priceSnapshotId", sa.Text(), nullable=False),
        sa.Column("listingId", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["pointId", "generationId", "accountId"],
            [
                "public.PortfolioHistoryAccountPoint.pointId",
                "public.PortfolioHistoryAccountPoint.generationId",
                "public.PortfolioHistoryAccountPoint.accountId",
            ],
            name="PortfolioHistoryPointPriceEvidence_account_point_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["priceSnapshotId", "listingId"],
            ["public.PriceSnapshot.id", "public.PriceSnapshot.listingId"],
            name="PortfolioHistoryPointPriceEvidence_price_listing_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("pointId", "generationId", "accountId", "priceSnapshotId"),
        schema="public",
    )
    op.create_table(
        "PortfolioHistoryPointFxEvidence",
        sa.Column("pointId", sa.Text(), nullable=False),
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("exchangeRateId", sa.Text(), nullable=False),
        sa.Column("fromCurrency", sa.Text(), nullable=False),
        sa.Column("toCurrency", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["pointId", "generationId", "accountId"],
            [
                "public.PortfolioHistoryAccountPoint.pointId",
                "public.PortfolioHistoryAccountPoint.generationId",
                "public.PortfolioHistoryAccountPoint.accountId",
            ],
            name="PortfolioHistoryPointFxEvidence_account_point_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exchangeRateId", "fromCurrency", "toCurrency"],
            [
                "public.ExchangeRate.id",
                "public.ExchangeRate.fromCurrency",
                "public.ExchangeRate.toCurrency",
            ],
            name="PortfolioHistoryPointFxEvidence_rate_direction_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("pointId", "generationId", "accountId", "exchangeRateId"),
        schema="public",
    )


def downgrade() -> None:
    raise RuntimeError("Immutable portfolio history schema cannot be downgraded automatically.")
