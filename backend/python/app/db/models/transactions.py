from datetime import datetime
from decimal import Decimal

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
from app.db.models.common import MONEY, TIMESTAMP
from app.db.models.enums import (
    IMPORT_SOURCE_DB,
    TRANSACTION_CLASSIFICATION_DB,
    TRANSACTION_TYPE_DB,
    ImportSource,
    TransactionClassification,
    TransactionType,
)


class TransactionModel(Base):
    __tablename__ = "Transaction"
    __table_args__ = (
        Index("Transaction_id_accountId_key", "id", "accountId", unique=True),
        Index(None, "accountId", "date"),
        Index(None, "accountId", "externalId"),
        Index(None, "categoryId", "date"),
        Index(None, "importBatchId"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    date: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    booking_date: Mapped[datetime | None] = mapped_column("bookingDate", TIMESTAMP)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    reporting_amount: Mapped[Decimal | None] = mapped_column("reportingAmount", MONEY)
    reporting_currency: Mapped[str | None] = mapped_column("reportingCurrency", Text)
    type: Mapped[TransactionType] = mapped_column(TRANSACTION_TYPE_DB, nullable=False)
    classification: Mapped[TransactionClassification | None] = mapped_column(
        TRANSACTION_CLASSIFICATION_DB
    )
    description: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    counterparty: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column("externalId", Text)
    is_reviewed: Mapped[bool] = mapped_column(
        "isReviewed",
        nullable=False,
        server_default=text("false"),
    )
    archived_at: Mapped[datetime | None] = mapped_column("archivedAt", TIMESTAMP)
    deleted_at: Mapped[datetime | None] = mapped_column("deletedAt", TIMESTAMP)
    category_id: Mapped[str | None] = mapped_column(
        "categoryId",
        ForeignKey("public.Category.id", ondelete="SET NULL"),
    )
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    import_batch_id: Mapped[str | None] = mapped_column(
        "importBatchId",
        ForeignKey("public.ImportBatch.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class TransactionPairModel(Base):
    __tablename__ = "TransactionPair"
    __table_args__ = (
        UniqueConstraint("fromTransactionId"),
        UniqueConstraint("toTransactionId"),
        CheckConstraint(
            '(("classification" IS NULL AND "source" IS NULL '
            'AND "evidenceVersion" IS NULL AND "evidenceHash" IS NULL) OR '
            '("classification" IS NOT NULL AND "source" IS NOT NULL '
            'AND "evidenceVersion" >= 1 AND "evidenceHash" ~ \'^[0-9a-f]{64}$\'))',
            name="TransactionPair_reconciliation_evidence_complete_or_legacy",
        ),
        CheckConstraint(
            '"backgroundJobId" IS NULL OR "classification" IS NOT NULL',
            name="TransactionPair_background_job_requires_evidence",
        ),
        CheckConstraint(
            '"publishedAt" IS NULL OR "backgroundJobId" IS NOT NULL',
            name="TransactionPair_publication_requires_background_job",
        ),
        ForeignKeyConstraint(
            ["backgroundJobId"],
            ["public.BackgroundJob.id"],
            name="TransactionPair_backgroundJobId_fkey",
            ondelete="RESTRICT",
        ),
        Index(None, "backgroundJobId"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    from_transaction_id: Mapped[str] = mapped_column(
        "fromTransactionId",
        ForeignKey("public.Transaction.id", ondelete="RESTRICT"),
        nullable=False,
    )
    to_transaction_id: Mapped[str] = mapped_column(
        "toTransactionId",
        ForeignKey("public.Transaction.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    classification: Mapped[TransactionClassification | None] = mapped_column(
        TRANSACTION_CLASSIFICATION_DB
    )
    source: Mapped[ImportSource | None] = mapped_column(IMPORT_SOURCE_DB)
    evidence_version: Mapped[int | None] = mapped_column("evidenceVersion", Integer)
    evidence_hash: Mapped[str | None] = mapped_column("evidenceHash", Text)
    background_job_id: Mapped[str | None] = mapped_column("backgroundJobId", Text)
    published_at: Mapped[datetime | None] = mapped_column("publishedAt", TIMESTAMP)


class TransactionSplitModel(Base):
    __tablename__ = "TransactionSplit"
    __table_args__ = (
        Index(None, "transactionId"),
        Index(None, "categoryId"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    transaction_id: Mapped[str] = mapped_column(
        "transactionId",
        ForeignKey("public.Transaction.id", ondelete="CASCADE"),
        nullable=False,
    )
    category_id: Mapped[str | None] = mapped_column(
        "categoryId",
        ForeignKey("public.Category.id", ondelete="SET NULL"),
    )
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class TransactionReportingEvidenceModel(Base):
    __tablename__ = "TransactionReportingEvidence"
    __table_args__ = (
        CheckConstraint(
            '"sourceAmount" <> 0',
            name="TransactionReportingEvidence_sourceAmount_nonzero",
        ),
        CheckConstraint(
            '"reportingAmount" <> 0',
            name="TransactionReportingEvidence_reportingAmount_nonzero",
        ),
        CheckConstraint(
            "\"sourceCurrency\" ~ '^[A-Z]{3}$'",
            name="TransactionReportingEvidence_sourceCurrency_iso4217",
        ),
        CheckConstraint(
            "\"reportingCurrency\" ~ '^[A-Z]{3}$'",
            name="TransactionReportingEvidence_reportingCurrency_iso4217",
        ),
        CheckConstraint(
            '"sourceCurrency" <> "reportingCurrency"',
            name="TransactionReportingEvidence_direct_conversion",
        ),
        CheckConstraint(
            '"calculationVersion" >= 1',
            name="TransactionReportingEvidence_calculationVersion_positive",
        ),
        CheckConstraint(
            '"publishedAt" IS NULL OR "backgroundJobId" IS NOT NULL',
            name="TransactionReportingEvidence_publish_requires_job",
        ),
        ForeignKeyConstraint(
            ["exchangeRateId", "sourceCurrency", "reportingCurrency"],
            [
                "public.ExchangeRate.id",
                "public.ExchangeRate.fromCurrency",
                "public.ExchangeRate.toCurrency",
            ],
            name="TransactionReportingEvidence_fx_direction_fkey",
            ondelete="RESTRICT",
        ),
        Index(None, "backgroundJobId"),
        {"schema": "public"},
    )

    transaction_id: Mapped[str] = mapped_column(
        "transactionId",
        ForeignKey(
            "public.Transaction.id",
            name="TransactionReportingEvidence_tx_fkey",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    source_amount: Mapped[Decimal] = mapped_column("sourceAmount", MONEY, nullable=False)
    source_currency: Mapped[str] = mapped_column("sourceCurrency", Text, nullable=False)
    source_event_time: Mapped[datetime] = mapped_column(
        "sourceEventTime", TIMESTAMP, nullable=False
    )
    reporting_amount: Mapped[Decimal] = mapped_column("reportingAmount", MONEY, nullable=False)
    reporting_currency: Mapped[str] = mapped_column("reportingCurrency", Text, nullable=False)
    exchange_rate_id: Mapped[str] = mapped_column("exchangeRateId", Text, nullable=False)
    calculation_version: Mapped[int] = mapped_column("calculationVersion", Integer, nullable=False)
    background_job_id: Mapped[str | None] = mapped_column(
        "backgroundJobId",
        ForeignKey(
            "public.BackgroundJob.id",
            name="TransactionReportingEvidence_job_fkey",
            ondelete="RESTRICT",
        ),
    )
    published_at: Mapped[datetime | None] = mapped_column("publishedAt", TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
