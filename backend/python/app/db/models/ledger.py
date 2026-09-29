from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import QUANTITY, RATE, TIMESTAMP
from app.db.models.enums import (
    ASSET_TYPE_DB,
    EXCHANGE_RATE_SOURCE_DB,
    IMPORT_SOURCE_DB,
    INVESTMENT_EVENT_TYPE_DB,
    INVESTMENT_MOVEMENT_KIND_DB,
    MOVEMENT_DIRECTION_DB,
    PRICE_SOURCE_DB,
    AssetType,
    ExchangeRateSource,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
)


class InvestmentEventModel(Base):
    __tablename__ = "InvestmentEvent"
    __table_args__ = (
        Index(None, "accountId", "date"),
        Index(None, "accountId", "externalId"),
        Index(None, "orderId"),
        Index(None, "importBatchId"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    type: Mapped[InvestmentEventType] = mapped_column(
        INVESTMENT_EVENT_TYPE_DB,
        nullable=False,
    )
    date: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    source: Mapped[ImportSource | None] = mapped_column(IMPORT_SOURCE_DB)
    external_id: Mapped[str | None] = mapped_column("externalId", Text)
    order_id: Mapped[str | None] = mapped_column("orderId", Text)
    description: Mapped[str | None] = mapped_column(Text)
    realized_pnl: Mapped[Decimal | None] = mapped_column("realizedPnl", QUANTITY)
    realized_pnl_currency: Mapped[str | None] = mapped_column("realizedPnlCurrency", Text)
    import_batch_id: Mapped[str | None] = mapped_column(
        "importBatchId",
        ForeignKey("public.ImportBatch.id", ondelete="SET NULL"),
    )
    archived_at: Mapped[datetime | None] = mapped_column("archivedAt", TIMESTAMP)
    deleted_at: Mapped[datetime | None] = mapped_column("deletedAt", TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class InvestmentMovementModel(Base):
    __tablename__ = "InvestmentMovement"
    __table_args__ = (
        Index(None, "eventId"),
        Index(None, "accountId", "createdAt"),
        Index(None, "assetId"),
        Index(None, "listingId"),
        Index(None, "kind"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[str] = mapped_column(
        "eventId",
        ForeignKey("public.InvestmentEvent.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    asset_id: Mapped[str | None] = mapped_column(
        "assetId",
        ForeignKey("public.Asset.id", ondelete="SET NULL"),
    )
    listing_id: Mapped[str | None] = mapped_column(
        "listingId",
        ForeignKey("public.AssetListing.id", ondelete="SET NULL"),
    )
    kind: Mapped[InvestmentMovementKind] = mapped_column(
        INVESTMENT_MOVEMENT_KIND_DB,
        nullable=False,
    )
    direction: Mapped[MovementDirection] = mapped_column(
        MOVEMENT_DIRECTION_DB,
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    price_per_unit: Mapped[Decimal | None] = mapped_column("pricePerUnit", QUANTITY)
    value_amount: Mapped[Decimal | None] = mapped_column("valueAmount", QUANTITY)
    value_currency: Mapped[str | None] = mapped_column("valueCurrency", Text)
    source_symbol: Mapped[str | None] = mapped_column("sourceSymbol", Text)
    source_asset_type: Mapped[AssetType | None] = mapped_column(
        "sourceAssetType",
        ASSET_TYPE_DB,
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class InvestmentMovementValuationEvidenceModel(Base):
    """Append-only, event-date valuation evidence overlaying an immutable movement."""

    __tablename__ = "InvestmentMovementValuationEvidence"
    __table_args__ = (
        Index(
            "InvestmentMovementValuationEvidence_movement_revision_key",
            "movementId",
            "revision",
            unique=True,
        ),
        Index(
            "InvestmentMovementValuationEvidence_movement_fingerprint_key",
            "movementId",
            "inputFingerprint",
            unique=True,
        ),
        CheckConstraint(
            '"revision" >= 1',
            name="InvestmentMovementValuationEvidence_revision_positive",
        ),
        CheckConstraint(
            '"canonicalRevision" >= 1',
            name="InvestmentMovementValuationEvidence_canonicalRevision_positive",
        ),
        CheckConstraint(
            '"calculationVersion" >= 1',
            name="InvestmentMovementValuationEvidence_calculationVersion_positive",
        ),
        CheckConstraint(
            "\"selectionInterval\" IN ('30min', '1day')",
            name="InvestmentMovementValuationEvidence_selectionInterval_known",
        ),
        CheckConstraint(
            '"priceAmount" > 0',
            name="InvestmentMovementValuationEvidence_priceAmount_positive",
        ),
        CheckConstraint(
            '"pricePerUnit" > 0',
            name="InvestmentMovementValuationEvidence_pricePerUnit_positive",
        ),
        CheckConstraint(
            '"valueAmount" > 0',
            name="InvestmentMovementValuationEvidence_valueAmount_positive",
        ),
        CheckConstraint(
            '(("exchangeRateId" IS NULL AND "fxRate" IS NULL '
            'AND "fxFromCurrency" IS NULL AND "fxToCurrency" IS NULL '
            'AND "fxSource" IS NULL AND "fxTimestamp" IS NULL) OR '
            '("exchangeRateId" IS NOT NULL AND "fxRate" IS NOT NULL '
            'AND "fxFromCurrency" IS NOT NULL AND "fxToCurrency" IS NOT NULL '
            'AND "fxSource" IS NOT NULL AND "fxTimestamp" IS NOT NULL))',
            name="InvestmentMovementValuationEvidence_fx_complete_or_absent",
        ),
        Index(None, "accountId"),
        Index(None, "movementId"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey(
            "public.Account.id",
            name="InvestmentMovementValuationEvidence_account_fkey",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    movement_id: Mapped[str] = mapped_column(
        "movementId",
        ForeignKey(
            "public.InvestmentMovement.id",
            name="InvestmentMovementValuationEvidence_movement_fkey",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    canonical_revision: Mapped[int] = mapped_column("canonicalRevision", BigInteger, nullable=False)
    effective_at: Mapped[datetime] = mapped_column("effectiveAt", TIMESTAMP, nullable=False)
    calculation_version: Mapped[int] = mapped_column("calculationVersion", Integer, nullable=False)
    selection_interval: Mapped[str] = mapped_column("selectionInterval", Text, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column("inputFingerprint", Text, nullable=False)
    price_snapshot_id: Mapped[str] = mapped_column(
        "priceSnapshotId",
        ForeignKey(
            "public.PriceSnapshot.id",
            name="InvestmentMovementValuationEvidence_priceSnapshot_fkey",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    exchange_rate_id: Mapped[str | None] = mapped_column(
        "exchangeRateId",
        ForeignKey(
            "public.ExchangeRate.id",
            name="InvestmentMovementValuationEvidence_exchangeRate_fkey",
            ondelete="RESTRICT",
        ),
    )
    price_amount: Mapped[Decimal] = mapped_column("priceAmount", QUANTITY, nullable=False)
    price_currency: Mapped[str] = mapped_column("priceCurrency", Text, nullable=False)
    price_source: Mapped[PriceSource] = mapped_column(
        "priceSource", PRICE_SOURCE_DB, nullable=False
    )
    price_timestamp: Mapped[datetime] = mapped_column("priceTimestamp", TIMESTAMP, nullable=False)
    fx_rate: Mapped[Decimal | None] = mapped_column("fxRate", RATE)
    fx_from_currency: Mapped[str | None] = mapped_column("fxFromCurrency", Text)
    fx_to_currency: Mapped[str | None] = mapped_column("fxToCurrency", Text)
    fx_source: Mapped[ExchangeRateSource | None] = mapped_column(
        "fxSource", EXCHANGE_RATE_SOURCE_DB
    )
    fx_timestamp: Mapped[datetime | None] = mapped_column("fxTimestamp", TIMESTAMP)
    price_per_unit: Mapped[Decimal] = mapped_column("pricePerUnit", QUANTITY, nullable=False)
    value_amount: Mapped[Decimal] = mapped_column("valueAmount", QUANTITY, nullable=False)
    value_currency: Mapped[str] = mapped_column("valueCurrency", Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
