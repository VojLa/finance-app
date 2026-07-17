from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import QUANTITY, TIMESTAMP
from app.db.models.enums import (
    ASSET_TYPE_DB,
    IMPORT_SOURCE_DB,
    INVESTMENT_EVENT_TYPE_DB,
    INVESTMENT_MOVEMENT_KIND_DB,
    MOVEMENT_DIRECTION_DB,
    AssetType,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
)


class InvestmentEventModel(Base):
    __tablename__ = "InvestmentEvent"
    __table_args__ = (
        Index(None, "accountId", "date"),
        Index(None, "accountId", "externalId"),
        Index(None, "orderId"),
        Index(None, "importBatchId"),
        {"schema": "public"},
    )  # noqa: RUF012

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id"),
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
        ForeignKey("public.ImportBatch.id"),
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
    )  # noqa: RUF012

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[str] = mapped_column(
        "eventId",
        ForeignKey("public.InvestmentEvent.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id"),
        nullable=False,
    )
    asset_id: Mapped[str | None] = mapped_column(
        "assetId",
        ForeignKey("public.Asset.id"),
    )
    listing_id: Mapped[str | None] = mapped_column(
        "listingId",
        ForeignKey("public.AssetListing.id"),
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
