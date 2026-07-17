from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import QUANTITY, RATE, TIMESTAMP
from app.db.models.enums import (
    EXCHANGE_RATE_SOURCE_DB,
    PRICE_SOURCE_DB,
    ExchangeRateSource,
    PriceSource,
)


class PriceSnapshotModel(Base):
    __tablename__ = "PriceSnapshot"
    __table_args__ = (
        UniqueConstraint("listingId", "timestamp", "source"),
        Index(None, "assetId", "timestamp"),
        Index(None, "listingId", "timestamp"),
        Index(None, "source", "timestamp"),
        {"schema": "public"},
    )  # noqa: RUF012

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        "assetId",
        ForeignKey("public.Asset.id", ondelete="CASCADE"),
        nullable=False,
    )
    listing_id: Mapped[str] = mapped_column(
        "listingId",
        ForeignKey("public.AssetListing.id", ondelete="CASCADE"),
        nullable=False,
    )
    price: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[PriceSource] = mapped_column(PRICE_SOURCE_DB, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class ExchangeRateModel(Base):
    __tablename__ = "ExchangeRate"
    __table_args__ = (
        UniqueConstraint("fromCurrency", "toCurrency", "date", "source"),
        Index(None, "fromCurrency", "toCurrency", "date"),
        Index(None, "source", "date"),
        {"schema": "public"},
    )  # noqa: RUF012

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    from_currency: Mapped[str] = mapped_column("fromCurrency", Text, nullable=False)
    to_currency: Mapped[str] = mapped_column("toCurrency", Text, nullable=False)
    rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    date: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    source: Mapped[ExchangeRateSource] = mapped_column(
        EXCHANGE_RATE_SOURCE_DB,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
