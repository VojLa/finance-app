"""Add the durable PostgreSQL background-job lifecycle.

Revision ID: 3l0001bgjob
Revises: 3k0001mcost
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3l0001bgjob"
down_revision: str | None = "3k0001mcost"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_persisted_background_job_lifecycle"
affected_tables = ("BackgroundJob",)
affected_columns = (
    "BackgroundJob.id",
    "BackgroundJob.userId",
    "BackgroundJob.accountId",
    "BackgroundJob.kind",
    "BackgroundJob.status",
    "BackgroundJob.idempotencyKey",
    "BackgroundJob.payload",
    "BackgroundJob.checkpoint",
    "BackgroundJob.progress",
    "BackgroundJob.result",
    "BackgroundJob.errorCode",
    "BackgroundJob.errorMessage",
    "BackgroundJob.attemptCount",
    "BackgroundJob.manualRetryCount",
    "BackgroundJob.maxAttempts",
    "BackgroundJob.runAfter",
    "BackgroundJob.leaseOwner",
    "BackgroundJob.leaseVersion",
    "BackgroundJob.leaseExpiresAt",
    "BackgroundJob.leaseHeartbeatAt",
    "BackgroundJob.startedAt",
    "BackgroundJob.finishedAt",
    "BackgroundJob.createdAt",
    "BackgroundJob.updatedAt",
)
prisma_schema_impact = "required"
data_migration = False

STATUS_VALUES = ("queued", "running", "retry_wait", "completed", "failed")
KIND_VALUES = ("import_workflow",)
status_enum = postgresql.ENUM(*STATUS_VALUES, name="BackgroundJobStatus", schema="public")
kind_enum = postgresql.ENUM(*KIND_VALUES, name="BackgroundJobKind", schema="public")


def upgrade() -> None:
    status_enum.create(op.get_bind(), checkfirst=False)
    kind_enum.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "BackgroundJob",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(
                *KIND_VALUES,
                name="BackgroundJobKind",
                schema="public",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            postgresql.ENUM(
                *STATUS_VALUES,
                name="BackgroundJobStatus",
                schema="public",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'queued'::\"BackgroundJobStatus\""),
        ),
        sa.Column("idempotencyKey", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "checkpoint",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "progress",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "result", postgresql.JSONB(astext_type=sa.Text(), none_as_null=True), nullable=True
        ),
        sa.Column("errorCode", sa.Text(), nullable=True),
        sa.Column("errorMessage", sa.Text(), nullable=True),
        sa.Column("attemptCount", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("manualRetryCount", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("maxAttempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column(
            "runAfter",
            postgresql.TIMESTAMP(precision=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("leaseOwner", sa.Text(), nullable=True),
        sa.Column("leaseVersion", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("leaseExpiresAt", postgresql.TIMESTAMP(precision=3), nullable=True),
        sa.Column("leaseHeartbeatAt", postgresql.TIMESTAMP(precision=3), nullable=True),
        sa.Column("startedAt", postgresql.TIMESTAMP(precision=3), nullable=True),
        sa.Column("finishedAt", postgresql.TIMESTAMP(precision=3), nullable=True),
        sa.Column(
            "createdAt",
            postgresql.TIMESTAMP(precision=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updatedAt",
            postgresql.TIMESTAMP(precision=3),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(\"payload\") = 'object' AND \"payload\" <> '{}'::jsonb",
            name="BackgroundJob_payload_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(\"checkpoint\") = 'object'",
            name="BackgroundJob_checkpoint_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(\"progress\") = 'object'",
            name="BackgroundJob_progress_object",
        ),
        sa.CheckConstraint(
            '"result" IS NULL OR jsonb_typeof("result") = \'object\'',
            name="BackgroundJob_result_object",
        ),
        sa.CheckConstraint(
            'octet_length("payload"::text) <= 65536',
            name="BackgroundJob_payload_bounded",
        ),
        sa.CheckConstraint(
            'octet_length("checkpoint"::text) <= 65536',
            name="BackgroundJob_checkpoint_bounded",
        ),
        sa.CheckConstraint(
            'octet_length("progress"::text) <= 16384',
            name="BackgroundJob_progress_bounded",
        ),
        sa.CheckConstraint(
            '"result" IS NULL OR octet_length("result"::text) <= 65536',
            name="BackgroundJob_result_bounded",
        ),
        sa.CheckConstraint(
            'char_length("idempotencyKey") BETWEEN 1 AND 200',
            name="BackgroundJob_idempotencyKey_bounded",
        ),
        sa.CheckConstraint('"attemptCount" >= 0', name="BackgroundJob_attemptCount_nonnegative"),
        sa.CheckConstraint(
            '"manualRetryCount" >= 0',
            name="BackgroundJob_manualRetryCount_nonnegative",
        ),
        sa.CheckConstraint(
            '"maxAttempts" BETWEEN 1 AND 20',
            name="BackgroundJob_maxAttempts_bounded",
        ),
        sa.CheckConstraint(
            '"attemptCount" <= "maxAttempts"',
            name="BackgroundJob_attemptCount_within_maximum",
        ),
        sa.CheckConstraint('"leaseVersion" >= 0', name="BackgroundJob_leaseVersion_nonnegative"),
        sa.CheckConstraint(
            '(("leaseOwner" IS NULL AND "leaseExpiresAt" IS NULL '
            'AND "leaseHeartbeatAt" IS NULL) OR '
            '("leaseOwner" IS NOT NULL AND "leaseExpiresAt" IS NOT NULL '
            'AND "leaseHeartbeatAt" IS NOT NULL))',
            name="BackgroundJob_lease_complete_or_absent",
        ),
        sa.CheckConstraint(
            '("status" = \'running\'::"BackgroundJobStatus") = ("leaseOwner" IS NOT NULL)',
            name="BackgroundJob_running_has_lease",
        ),
        sa.CheckConstraint(
            '(("status" IN (\'completed\'::"BackgroundJobStatus", '
            '\'failed\'::"BackgroundJobStatus")) = ("finishedAt" IS NOT NULL))',
            name="BackgroundJob_terminal_has_finishedAt",
        ),
        sa.CheckConstraint(
            '(("errorCode" IS NULL AND "errorMessage" IS NULL) OR '
            '("errorCode" IS NOT NULL AND "errorMessage" IS NOT NULL))',
            name="BackgroundJob_error_pair_complete",
        ),
        sa.CheckConstraint(
            '("status" <> \'failed\'::"BackgroundJobStatus") OR '
            '("errorCode" IS NOT NULL AND "errorMessage" IS NOT NULL)',
            name="BackgroundJob_failed_has_safe_error",
        ),
        sa.CheckConstraint(
            '("status" <> \'completed\'::"BackgroundJobStatus") OR '
            '("errorCode" IS NULL AND "errorMessage" IS NULL)',
            name="BackgroundJob_completed_has_no_error",
        ),
        sa.CheckConstraint(
            '("status" = \'completed\'::"BackgroundJobStatus") = ("result" IS NOT NULL)',
            name="BackgroundJob_completed_has_result",
        ),
        sa.CheckConstraint(
            '"leaseOwner" IS NULL OR char_length("leaseOwner") BETWEEN 1 AND 200',
            name="BackgroundJob_leaseOwner_bounded",
        ),
        sa.CheckConstraint(
            '"errorCode" IS NULL OR char_length("errorCode") BETWEEN 1 AND 100',
            name="BackgroundJob_errorCode_bounded",
        ),
        sa.CheckConstraint(
            '"errorMessage" IS NULL OR char_length("errorMessage") BETWEEN 1 AND 1000',
            name="BackgroundJob_errorMessage_bounded",
        ),
        sa.ForeignKeyConstraint(
            ["userId"],
            ["public.User.id"],
            name="BackgroundJob_userId_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["accountId"],
            ["public.Account.id"],
            name="BackgroundJob_accountId_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="BackgroundJob_pkey"),
        schema="public",
    )
    op.create_index(
        "BackgroundJob_userId_createdAt_idx",
        "BackgroundJob",
        ["userId", "createdAt"],
        schema="public",
    )
    op.create_index(
        "BackgroundJob_accountId_createdAt_idx",
        "BackgroundJob",
        ["accountId", "createdAt"],
        schema="public",
    )
    op.create_index(
        "BackgroundJob_userId_accountId_kind_idempotencyKey_key",
        "BackgroundJob",
        ["userId", "accountId", "kind", "idempotencyKey"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "BackgroundJob_claim_idx",
        "BackgroundJob",
        ["status", "runAfter", "leaseExpiresAt", "createdAt"],
        postgresql_where=sa.text(
            '"status" IN (\'queued\'::"BackgroundJobStatus", \'retry_wait\'::"BackgroundJobStatus")'
        ),
        schema="public",
    )
    op.create_index(
        "BackgroundJob_expiredLease_idx",
        "BackgroundJob",
        ["leaseExpiresAt"],
        unique=False,
        postgresql_where=sa.text('"status" = \'running\'::"BackgroundJobStatus"'),
        schema="public",
    )
    op.create_index(
        "BackgroundJob_one_running_per_account_key",
        "BackgroundJob",
        ["accountId"],
        unique=True,
        postgresql_where=sa.text('"status" = \'running\'::"BackgroundJobStatus"'),
        schema="public",
    )


def downgrade() -> None:
    connection = op.get_bind()
    rows_exist = connection.execute(
        sa.text('SELECT EXISTS (SELECT 1 FROM "public"."BackgroundJob")')
    ).scalar_one()
    if rows_exist:
        raise RuntimeError("Cannot remove BackgroundJob while durable job evidence exists.")
    op.drop_index(
        "BackgroundJob_one_running_per_account_key",
        table_name="BackgroundJob",
        schema="public",
    )
    op.drop_index(
        "BackgroundJob_userId_accountId_kind_idempotencyKey_key",
        table_name="BackgroundJob",
        schema="public",
    )
    op.drop_index("BackgroundJob_expiredLease_idx", table_name="BackgroundJob", schema="public")
    op.drop_index("BackgroundJob_claim_idx", table_name="BackgroundJob", schema="public")
    op.drop_index(
        "BackgroundJob_accountId_createdAt_idx", table_name="BackgroundJob", schema="public"
    )
    op.drop_index("BackgroundJob_userId_createdAt_idx", table_name="BackgroundJob", schema="public")
    op.drop_table("BackgroundJob", schema="public")
    kind_enum.drop(connection, checkfirst=False)
    status_enum.drop(connection, checkfirst=False)
