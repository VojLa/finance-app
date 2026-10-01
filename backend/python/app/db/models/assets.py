from datetime import datetime

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
from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    ASSET_ALIAS_PROVIDER_DB,
    ASSET_TYPE_DB,
    PRICE_SOURCE_DB,
    AssetAliasProvider,
    AssetType,
    PriceSource,
)


class AssetModel(Base):
    __tablename__ = "Asset"
    __table_args__ = (
        Index(None, "symbol"),
        Index(None, "isin"),
        Index(None, "assetType"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    isin: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    asset_type: Mapped[AssetType] = mapped_column("assetType", ASSET_TYPE_DB, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class AssetListingModel(Base):
    __tablename__ = "AssetListing"
    __table_args__ = (
        UniqueConstraint("assetId", "symbol", "exchange", "currency"),
        UniqueConstraint("symbol", "exchange", "currency"),
        UniqueConstraint("provider", "providerSymbol", "currency"),
        UniqueConstraint("id", "assetId", name="AssetListing_id_assetId_key"),
        CheckConstraint('"basePriority" >= 0', name="AssetListing_basePriority_nonnegative"),
        Index(None, "assetId"),
        Index(None, "symbol"),
        Index(None, "provider", "providerSymbol"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        "assetId",
        ForeignKey("public.Asset.id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str | None] = mapped_column(Text)
    mic: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    country: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[PriceSource | None] = mapped_column(PRICE_SOURCE_DB)
    provider_symbol: Mapped[str | None] = mapped_column("providerSymbol", Text)
    is_primary: Mapped[bool] = mapped_column(
        "isPrimary",
        nullable=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)
    base_priority: Mapped[int] = mapped_column(
        "basePriority", Integer, nullable=False, server_default=text("0")
    )


class AssetAliasModel(Base):
    __tablename__ = "AssetAlias"
    __table_args__ = (
        UniqueConstraint("provider", "externalId"),
        UniqueConstraint("listingId", "provider", name="AssetAlias_listingId_provider_key"),
        ForeignKeyConstraint(
            ["listingId", "assetId"],
            ["public.AssetListing.id", "public.AssetListing.assetId"],
            name="AssetAlias_listing_asset_fkey",
            ondelete="CASCADE",
        ),
        Index(None, "assetId", "provider"),
        Index(None, "listingId"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        "assetId",
        ForeignKey("public.Asset.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[AssetAliasProvider] = mapped_column(
        ASSET_ALIAS_PROVIDER_DB,
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column("externalId", Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    listing_id: Mapped[str | None] = mapped_column("listingId", Text)
