from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import JSONB, TIMESTAMP
from app.db.models.enums import (
    BACKGROUND_JOB_KIND_DB,
    BACKGROUND_JOB_STATUS_DB,
    BackgroundJobKind,
    BackgroundJobStatus,
)

_JSON_OBJECT_CHECKS = (
    (
        "jsonb_typeof(\"payload\") = 'object' AND \"payload\" <> '{}'::jsonb",
        "BackgroundJob_payload_object",
    ),
    ("jsonb_typeof(\"checkpoint\") = 'object'", "BackgroundJob_checkpoint_object"),
    ("jsonb_typeof(\"progress\") = 'object'", "BackgroundJob_progress_object"),
    (
        '"result" IS NULL OR jsonb_typeof("result") = \'object\'',
        "BackgroundJob_result_object",
    ),
)


class BackgroundJobModel(Base):
    __tablename__ = "BackgroundJob"
    __table_args__ = (
        UniqueConstraint("userId", "accountId", "kind", "idempotencyKey"),
        Index("BackgroundJob_id_userId_accountId_key", "id", "userId", "accountId", unique=True),
        Index("BackgroundJob_id_userId_key", "id", "userId", unique=True),
        *(CheckConstraint(expression, name=name) for expression, name in _JSON_OBJECT_CHECKS),
        CheckConstraint(
            'octet_length("payload"::text) <= 65536',
            name="BackgroundJob_payload_bounded",
        ),
        CheckConstraint(
            'octet_length("checkpoint"::text) <= 65536',
            name="BackgroundJob_checkpoint_bounded",
        ),
        CheckConstraint(
            'octet_length("progress"::text) <= 16384',
            name="BackgroundJob_progress_bounded",
        ),
        CheckConstraint(
            '"result" IS NULL OR octet_length("result"::text) <= 65536',
            name="BackgroundJob_result_bounded",
        ),
        CheckConstraint(
            'char_length("idempotencyKey") BETWEEN 1 AND 200',
            name="BackgroundJob_idempotencyKey_bounded",
        ),
        CheckConstraint(
            '"attemptCount" >= 0',
            name="BackgroundJob_attemptCount_nonnegative",
        ),
        CheckConstraint(
            '"manualRetryCount" >= 0',
            name="BackgroundJob_manualRetryCount_nonnegative",
        ),
        CheckConstraint(
            '"maxAttempts" BETWEEN 1 AND 20',
            name="BackgroundJob_maxAttempts_bounded",
        ),
        CheckConstraint(
            '"attemptCount" <= "maxAttempts"',
            name="BackgroundJob_attemptCount_within_maximum",
        ),
        CheckConstraint(
            '"leaseVersion" >= 0',
            name="BackgroundJob_leaseVersion_nonnegative",
        ),
        CheckConstraint(
            '(("leaseOwner" IS NULL AND "leaseExpiresAt" IS NULL '
            'AND "leaseHeartbeatAt" IS NULL) OR '
            '("leaseOwner" IS NOT NULL AND "leaseExpiresAt" IS NOT NULL '
            'AND "leaseHeartbeatAt" IS NOT NULL))',
            name="BackgroundJob_lease_complete_or_absent",
        ),
        CheckConstraint(
            '("status" = \'running\'::"BackgroundJobStatus") = ("leaseOwner" IS NOT NULL)',
            name="BackgroundJob_running_has_lease",
        ),
        CheckConstraint(
            '(("status" IN (\'completed\'::"BackgroundJobStatus", '
            '\'failed\'::"BackgroundJobStatus")) = ("finishedAt" IS NOT NULL))',
            name="BackgroundJob_terminal_has_finishedAt",
        ),
        CheckConstraint(
            '(("errorCode" IS NULL AND "errorMessage" IS NULL) OR '
            '("errorCode" IS NOT NULL AND "errorMessage" IS NOT NULL))',
            name="BackgroundJob_error_pair_complete",
        ),
        CheckConstraint(
            '("status" <> \'failed\'::"BackgroundJobStatus") OR '
            '("errorCode" IS NOT NULL AND "errorMessage" IS NOT NULL)',
            name="BackgroundJob_failed_has_safe_error",
        ),
        CheckConstraint(
            '("status" <> \'completed\'::"BackgroundJobStatus") OR '
            '("errorCode" IS NULL AND "errorMessage" IS NULL)',
            name="BackgroundJob_completed_has_no_error",
        ),
        CheckConstraint(
            '("status" = \'completed\'::"BackgroundJobStatus") = ("result" IS NOT NULL)',
            name="BackgroundJob_completed_has_result",
        ),
        CheckConstraint(
            '"leaseOwner" IS NULL OR char_length("leaseOwner") BETWEEN 1 AND 200',
            name="BackgroundJob_leaseOwner_bounded",
        ),
        CheckConstraint(
            '"errorCode" IS NULL OR char_length("errorCode") BETWEEN 1 AND 100',
            name="BackgroundJob_errorCode_bounded",
        ),
        CheckConstraint(
            '"errorMessage" IS NULL OR char_length("errorMessage") BETWEEN 1 AND 1000',
            name="BackgroundJob_errorMessage_bounded",
        ),
        Index(None, "userId", "createdAt"),
        Index(None, "accountId", "createdAt"),
        Index(
            "BackgroundJob_claim_idx",
            "status",
            "runAfter",
            "leaseExpiresAt",
            "createdAt",
            postgresql_where=text(
                '"status" IN (\'queued\'::"BackgroundJobStatus", '
                "'retry_wait'::\"BackgroundJobStatus\")"
            ),
        ),
        Index(
            "BackgroundJob_expiredLease_idx",
            "leaseExpiresAt",
            postgresql_where=text('"status" = \'running\'::"BackgroundJobStatus"'),
        ),
        Index(
            "BackgroundJob_one_running_per_account_key",
            "accountId",
            unique=True,
            postgresql_where=text('"status" = \'running\'::"BackgroundJobStatus"'),
        ),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("public.User.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[BackgroundJobKind] = mapped_column(BACKGROUND_JOB_KIND_DB, nullable=False)
    status: Mapped[BackgroundJobStatus] = mapped_column(
        BACKGROUND_JOB_STATUS_DB,
        nullable=False,
        server_default=text("'queued'::\"BackgroundJobStatus\""),
    )
    idempotency_key: Mapped[str] = mapped_column("idempotencyKey", Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    progress: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column("errorCode", Text)
    error_message: Mapped[str | None] = mapped_column("errorMessage", Text)
    attempt_count: Mapped[int] = mapped_column(
        "attemptCount", Integer, nullable=False, server_default=text("0")
    )
    manual_retry_count: Mapped[int] = mapped_column(
        "manualRetryCount", Integer, nullable=False, server_default=text("0")
    )
    max_attempts: Mapped[int] = mapped_column(
        "maxAttempts", Integer, nullable=False, server_default=text("3")
    )
    run_after: Mapped[datetime] = mapped_column(
        "runAfter",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    lease_owner: Mapped[str | None] = mapped_column("leaseOwner", Text)
    lease_version: Mapped[int] = mapped_column(
        "leaseVersion", Integer, nullable=False, server_default=text("0")
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column("leaseExpiresAt", TIMESTAMP)
    lease_heartbeat_at: Mapped[datetime | None] = mapped_column("leaseHeartbeatAt", TIMESTAMP)
    started_at: Mapped[datetime | None] = mapped_column("startedAt", TIMESTAMP)
    finished_at: Mapped[datetime | None] = mapped_column("finishedAt", TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        "updatedAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class ImportJobBatchModel(Base):
    __tablename__ = "ImportJobBatch"
    __table_args__ = (
        PrimaryKeyConstraint("jobId", "batchId"),
        ForeignKeyConstraint(
            ["jobId", "userId", "accountId"],
            [
                "public.BackgroundJob.id",
                "public.BackgroundJob.userId",
                "public.BackgroundJob.accountId",
            ],
            name="ImportJobBatch_job_scope_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["batchId", "userId", "accountId"],
            [
                "public.ImportBatch.id",
                "public.ImportBatch.userId",
                "public.ImportBatch.accountId",
            ],
            name="ImportJobBatch_batch_scope_fkey",
            ondelete="RESTRICT",
        ),
        Index(None, "batchId"),
        {"schema": "public"},
    )

    job_id: Mapped[str] = mapped_column("jobId", Text, nullable=False)
    batch_id: Mapped[str] = mapped_column("batchId", Text, nullable=False)
    user_id: Mapped[str] = mapped_column("userId", Text, nullable=False)
    account_id: Mapped[str] = mapped_column("accountId", Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class ImportJobAffectedAccountModel(Base):
    __tablename__ = "ImportJobAffectedAccount"
    __table_args__ = (
        PrimaryKeyConstraint("jobId", "accountId"),
        ForeignKeyConstraint(
            ["jobId", "userId"],
            ["public.BackgroundJob.id", "public.BackgroundJob.userId"],
            name="ImportJobAffectedAccount_job_user_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["accountId", "userId"],
            ["public.AccountMember.accountId", "public.AccountMember.userId"],
            name="ImportJobAffectedAccount_member_fkey",
            ondelete="RESTRICT",
        ),
        Index(None, "accountId"),
        {"schema": "public"},
    )

    job_id: Mapped[str] = mapped_column("jobId", Text, nullable=False)
    account_id: Mapped[str] = mapped_column("accountId", Text, nullable=False)
    user_id: Mapped[str] = mapped_column("userId", Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
