from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import JSONB, TIMESTAMP
from app.db.models.enums import (
    IMPORT_LOG_EVENT_DB,
    IMPORT_LOG_LEVEL_DB,
    IMPORT_ROW_STATUS_DB,
    IMPORT_SOURCE_DB,
    IMPORT_STATUS_DB,
    ImportLogEvent,
    ImportLogLevel,
    ImportRowStatus,
    ImportSource,
    ImportStatus,
)


class ImportBatchModel(Base):
    __tablename__ = "ImportBatch"
    __table_args__ = (
        UniqueConstraint("userId", "accountId", "checksum"),
        Index("ImportBatch_id_userId_accountId_key", "id", "userId", "accountId", unique=True),
        Index("ImportBatch_id_accountId_source_key", "id", "accountId", "source", unique=True),
        Index(None, "userId", "createdAt"),
        Index(None, "accountId", "createdAt"),
        Index(None, "source", "status"),
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
    source: Mapped[ImportSource] = mapped_column(IMPORT_SOURCE_DB, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int | None] = mapped_column("fileSize", Integer)
    file_encoding: Mapped[str | None] = mapped_column("fileEncoding", Text)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ImportStatus] = mapped_column(
        IMPORT_STATUS_DB,
        nullable=False,
        server_default=text("'completed'::\"ImportStatus\""),
    )
    rows_total: Mapped[int | None] = mapped_column("rowsTotal", Integer)
    rows_imported: Mapped[int | None] = mapped_column("rowsImported", Integer)
    rows_skipped: Mapped[int | None] = mapped_column("rowsSkipped", Integer)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    completed_at: Mapped[datetime | None] = mapped_column("completedAt", TIMESTAMP)
    retain_until: Mapped[datetime | None] = mapped_column("retainUntil", TIMESTAMP)
    raw_data_purged_at: Mapped[datetime | None] = mapped_column("rawDataPurgedAt", TIMESTAMP)


class ImportRowModel(Base):
    __tablename__ = "ImportRow"
    __table_args__ = (
        UniqueConstraint("importBatchId", "rowNumber"),
        Index("ImportRow_id_importBatchId_key", "id", "importBatchId", unique=True),
        Index(None, "importBatchId", "status"),
        Index(None, "deduplicationKey"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    import_batch_id: Mapped[str] = mapped_column(
        "importBatchId",
        ForeignKey("public.ImportBatch.id", ondelete="CASCADE"),
        nullable=False,
    )
    row_number: Mapped[int] = mapped_column("rowNumber", Integer, nullable=False)
    raw_data: Mapped[dict[str, Any]] = mapped_column("rawData", JSONB, nullable=False)
    normalized_data: Mapped[dict[str, Any] | None] = mapped_column("normalizedData", JSONB)
    validation_errors: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        "validationErrors",
        JSONB,
    )
    deduplication_key: Mapped[str | None] = mapped_column("deduplicationKey", Text)
    status: Mapped[ImportRowStatus] = mapped_column(
        IMPORT_ROW_STATUS_DB,
        nullable=False,
        server_default=text("'pending'::\"ImportRowStatus\""),
    )
    error_message: Mapped[str | None] = mapped_column("errorMessage", Text)
    created_transaction_id: Mapped[str | None] = mapped_column("createdTransactionId", Text)
    created_investment_event_id: Mapped[str | None] = mapped_column(
        "createdInvestmentEventId",
        Text,
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class ImportLogModel(Base):
    __tablename__ = "ImportLog"
    __table_args__ = (
        Index(None, "importBatchId", "createdAt"),
        Index(None, "level", "createdAt"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    import_batch_id: Mapped[str] = mapped_column(
        "importBatchId",
        ForeignKey("public.ImportBatch.id", ondelete="CASCADE"),
        nullable=False,
    )
    level: Mapped[ImportLogLevel] = mapped_column(IMPORT_LOG_LEVEL_DB, nullable=False)
    event: Mapped[ImportLogEvent] = mapped_column(IMPORT_LOG_EVENT_DB, nullable=False)
    message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class ImportSourceOccurrenceModel(Base):
    """Durable source identity; reconciliation services are intentionally separate."""

    __tablename__ = "ImportSourceOccurrence"
    __table_args__ = (
        Index(
            "ImportSourceOccurrence_fp_identity_key",
            "accountId",
            "source",
            "fingerprintHash",
            "ordinal",
            unique=True,
        ),
        Index(
            "ImportSourceOccurrence_rep_row_key",
            "representativeImportRowId",
            unique=True,
        ),
        CheckConstraint(
            "\"fingerprintHash\" ~ '^[0-9a-f]{64}$'",
            name="ImportSourceOccurrence_fingerprintHash_sha256",
        ),
        CheckConstraint('"ordinal" >= 1', name="ImportSourceOccurrence_ordinal_positive"),
        CheckConstraint('"version" >= 1', name="ImportSourceOccurrence_version_positive"),
        CheckConstraint(
            "jsonb_typeof(\"flags\") = 'object'",
            name="ImportSourceOccurrence_flags_object",
        ),
        CheckConstraint(
            'octet_length("flags"::text) <= 16384',
            name="ImportSourceOccurrence_flags_bounded",
        ),
        ForeignKeyConstraint(
            ["representativeImportRowId", "representativeImportBatchId"],
            ["public.ImportRow.id", "public.ImportRow.importBatchId"],
            name="ImportSourceOccurrence_rep_row_batch_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["representativeImportBatchId", "accountId", "source"],
            ["public.ImportBatch.id", "public.ImportBatch.accountId", "public.ImportBatch.source"],
            name="ImportSourceOccurrence_rep_batch_scope_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["canonicalTransactionId", "accountId"],
            ["public.Transaction.id", "public.Transaction.accountId"],
            name="ImportSourceOccurrence_tx_account_fkey",
            ondelete="RESTRICT",
        ),
        Index(None, "accountId", "source", "createdAt"),
        Index(None, "canonicalTransactionId"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source: Mapped[ImportSource] = mapped_column(IMPORT_SOURCE_DB, nullable=False)
    fingerprint_hash: Mapped[str] = mapped_column("fingerprintHash", Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    representative_import_row_id: Mapped[str] = mapped_column(
        "representativeImportRowId", Text, nullable=False
    )
    representative_import_batch_id: Mapped[str] = mapped_column(
        "representativeImportBatchId", Text, nullable=False
    )
    canonical_transaction_id: Mapped[str | None] = mapped_column("canonicalTransactionId", Text)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    flags: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)
