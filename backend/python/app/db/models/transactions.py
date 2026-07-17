from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import MONEY, TIMESTAMP
from app.db.models.enums import (
    TRANSACTION_CLASSIFICATION_DB,
    TRANSACTION_TYPE_DB,
    TransactionClassification,
    TransactionType,
)


class TransactionModel(Base):
    __tablename__ = "Transaction"
    __table_args__ = (
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
        ForeignKey("public.Category.id"),
    )
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id"),
        nullable=False,
    )
    import_batch_id: Mapped[str | None] = mapped_column(
        "importBatchId",
        ForeignKey("public.ImportBatch.id"),
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
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    from_transaction_id: Mapped[str] = mapped_column(
        "fromTransactionId",
        ForeignKey("public.Transaction.id"),
        nullable=False,
    )
    to_transaction_id: Mapped[str] = mapped_column(
        "toTransactionId",
        ForeignKey("public.Transaction.id"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


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
