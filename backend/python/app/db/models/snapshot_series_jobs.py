"""Durable orchestration state for renewable snapshot-series publication."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import JSONB, TIMESTAMP
from app.db.models.enums import (
    BACKGROUND_JOB_STATUS_DB,
    SNAPSHOT_SERIES_JOB_KIND_DB,
    BackgroundJobStatus,
    SnapshotSeriesJobKind,
)


class SnapshotSeriesRebuildJobModel(Base):
    __tablename__ = "SnapshotSeriesRebuildJob"
    __table_args__ = (
        ForeignKeyConstraint(
            ("requestedByBackgroundJobId", "userId"),
            ("public.BackgroundJob.id", "public.BackgroundJob.userId"),
            name="SnapshotSeriesRebuildJob_requested_background_job_user_fkey",
            onupdate="CASCADE",
            ondelete='SET NULL ("requestedByBackgroundJobId")',
        ),
        CheckConstraint(
            "jsonb_typeof(\"payload\") = 'object' AND \"payload\" <> '{}'::jsonb",
            name="SnapshotSeriesRebuildJob_payload_object",
        ),
        CheckConstraint(
            "jsonb_typeof(\"checkpoint\") = 'object'",
            name="SnapshotSeriesRebuildJob_checkpoint_object",
        ),
        CheckConstraint(
            "jsonb_typeof(\"progress\") = 'object'", name="SnapshotSeriesRebuildJob_progress_object"
        ),
        CheckConstraint(
            '"result" IS NULL OR jsonb_typeof("result") = \'object\'',
            name="SnapshotSeriesRebuildJob_result_object",
        ),
        CheckConstraint(
            'char_length("idempotencyKey") BETWEEN 1 AND 200',
            name="SnapshotSeriesRebuildJob_idempotencyKey_bounded",
        ),
        CheckConstraint(
            '"attemptCount" >= 0 AND "attemptCount" <= "maxAttempts" AND "maxAttempts" BETWEEN 1 AND 20',
            name="SnapshotSeriesRebuildJob_attempts_valid",
        ),
        CheckConstraint(
            '"leaseVersion" >= 0', name="SnapshotSeriesRebuildJob_leaseVersion_nonnegative"
        ),
        CheckConstraint(
            '(("leaseOwner" IS NULL AND "leaseExpiresAt" IS NULL AND "leaseHeartbeatAt" IS NULL) OR ("leaseOwner" IS NOT NULL AND "leaseExpiresAt" IS NOT NULL AND "leaseHeartbeatAt" IS NOT NULL))',
            name="SnapshotSeriesRebuildJob_lease_complete_or_absent",
        ),
        CheckConstraint(
            '("status" = \'running\'::"BackgroundJobStatus") = ("leaseOwner" IS NOT NULL)',
            name="SnapshotSeriesRebuildJob_running_has_lease",
        ),
        CheckConstraint(
            '(("status" IN (\'completed\'::"BackgroundJobStatus", \'failed\'::"BackgroundJobStatus")) = ("finishedAt" IS NOT NULL))',
            name="SnapshotSeriesRebuildJob_terminal_has_finishedAt",
        ),
        CheckConstraint(
            '("status" = \'completed\'::"BackgroundJobStatus") = ("result" IS NOT NULL)',
            name="SnapshotSeriesRebuildJob_completed_has_result",
        ),
        CheckConstraint(
            '(("errorCode" IS NULL AND "errorMessage" IS NULL) OR ("errorCode" IS NOT NULL AND "errorMessage" IS NOT NULL))',
            name="SnapshotSeriesRebuildJob_error_pair_complete",
        ),
        Index(
            "SnapshotSeriesRebuildJob_user_kind_idempotency_key",
            "userId",
            "kind",
            "idempotencyKey",
            unique=True,
        ),
        Index("SnapshotSeriesRebuildJob_id_user_key", "id", "userId", unique=True),
        Index(
            "SnapshotSeriesRebuildJob_claim_idx",
            "status",
            "runAfter",
            "leaseExpiresAt",
            "createdAt",
            postgresql_where=text(
                '"status" IN (\'queued\'::"BackgroundJobStatus", \'retry_wait\'::"BackgroundJobStatus")'
            ),
        ),
        Index(
            "SnapshotSeriesRebuildJob_one_running_per_user_key",
            "userId",
            unique=True,
            postgresql_where=text('"status" = \'running\'::"BackgroundJobStatus"'),
        ),
        {"schema": "public"},
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("public.User.id", onupdate="CASCADE", ondelete="CASCADE"),
        nullable=False,
    )
    requested_by_background_job_id: Mapped[str | None] = mapped_column(
        "requestedByBackgroundJobId", Text
    )
    kind: Mapped[SnapshotSeriesJobKind] = mapped_column(SNAPSHOT_SERIES_JOB_KIND_DB, nullable=False)
    status: Mapped[BackgroundJobStatus] = mapped_column(
        BACKGROUND_JOB_STATUS_DB,
        nullable=False,
        server_default=text("'queued'::\"BackgroundJobStatus\""),
    )
    idempotency_key: Mapped[str] = mapped_column("idempotencyKey", Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    progress: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
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
        "runAfter", TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
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
        "createdAt", TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class SnapshotSeriesDirtyStateModel(Base):
    __tablename__ = "SnapshotSeriesDirtyState"
    __table_args__ = (
        CheckConstraint(
            '"dirtyEpoch" >= 1 AND "reasonMask" >= 1', name="SnapshotSeriesDirtyState_valid"
        ),
        {"schema": "public"},
    )
    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("public.User.id", onupdate="CASCADE", ondelete="CASCADE"),
        primary_key=True,
    )
    dirty_from: Mapped[datetime] = mapped_column("dirtyFrom", TIMESTAMP, nullable=False)
    dirty_epoch: Mapped[int] = mapped_column("dirtyEpoch", BigInteger, nullable=False)
    scope_dirty: Mapped[bool] = mapped_column(
        "scopeDirty", Boolean, nullable=False, server_default=text("false")
    )
    reason_mask: Mapped[int] = mapped_column("reasonMask", Integer, nullable=False)
    requested_at: Mapped[datetime] = mapped_column("requestedAt", TIMESTAMP, nullable=False)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class SnapshotSeriesCanonicalInvalidationModel(Base):
    __tablename__ = "SnapshotSeriesCanonicalInvalidation"
    __table_args__ = (
        ForeignKeyConstraint(
            ("accountId", "canonicalRevision", "kind", "entityId", "financialTimestamp"),
            (
                "public.AccountCanonicalChange.accountId",
                "public.AccountCanonicalChange.revision",
                "public.AccountCanonicalChange.kind",
                "public.AccountCanonicalChange.entityId",
                "public.AccountCanonicalChange.financialTimestamp",
            ),
            name="SnapshotSeriesCanonicalInvalidation_canonical_change_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("resolvedSnapshotGenerationId",),
            ("public.SnapshotGeneration.id",),
            name="SnapshotSeriesCanonicalInvalidation_resolved_generation_fkey",
            onupdate="CASCADE",
            ondelete='SET NULL ("resolvedSnapshotGenerationId")',
        ),
        CheckConstraint(
            '"firstDirtyEpoch" >= 1',
            name="SnapshotSeriesCanonicalInvalidation_firstDirtyEpoch_positive",
        ),
        Index(
            "SnapshotSeriesCanonicalInvalidation_account_revision_idx",
            "accountId",
            "canonicalRevision",
        ),
        {"schema": "public"},
    )
    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("public.User.id", onupdate="CASCADE", ondelete="CASCADE"),
        primary_key=True,
    )
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", onupdate="CASCADE", ondelete="CASCADE"),
        primary_key=True,
    )
    canonical_revision: Mapped[int] = mapped_column(
        "canonicalRevision", BigInteger, primary_key=True
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column("entityId", Text, nullable=False)
    financial_timestamp: Mapped[datetime] = mapped_column(
        "financialTimestamp", TIMESTAMP, nullable=False
    )
    first_dirty_epoch: Mapped[int] = mapped_column("firstDirtyEpoch", BigInteger, nullable=False)
    invalidated_at: Mapped[datetime] = mapped_column("invalidatedAt", TIMESTAMP, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column("resolvedAt", TIMESTAMP)
    resolved_snapshot_generation_id: Mapped[str | None] = mapped_column(
        "resolvedSnapshotGenerationId", Text
    )


class SnapshotSeriesScheduleStateModel(Base):
    __tablename__ = "SnapshotSeriesScheduleState"
    __table_args__ = (
        CheckConstraint(
            '"timezone" = \'Europe/Prague\' AND "cadenceMinutes" = 30',
            name="SnapshotSeriesScheduleState_capture_policy",
        ),
        CheckConstraint(
            'date_trunc(\'minute\', "nextCaptureAt") = "nextCaptureAt"',
            name="SnapshotSeriesScheduleState_nextCapture_minute_aligned",
        ),
        CheckConstraint(
            '"lastDirtyEpoch" >= 0',
            name="SnapshotSeriesScheduleState_lastDirtyEpoch_nonnegative",
        ),
        Index(
            "SnapshotSeriesScheduleState_due_idx",
            "nextCaptureAt",
            postgresql_where=text('"enabled"'),
        ),
        {"schema": "public"},
    )
    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("public.User.id", onupdate="CASCADE", ondelete="CASCADE"),
        primary_key=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    timezone: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Europe/Prague'::text")
    )
    cadence_minutes: Mapped[int] = mapped_column(
        "cadenceMinutes", SmallInteger, nullable=False, server_default=text("30")
    )
    next_capture_at: Mapped[datetime] = mapped_column("nextCaptureAt", TIMESTAMP, nullable=False)
    last_captured_bucket: Mapped[datetime | None] = mapped_column("lastCapturedBucket", TIMESTAMP)
    last_dirty_epoch: Mapped[int] = mapped_column(
        "lastDirtyEpoch", BigInteger, nullable=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)
