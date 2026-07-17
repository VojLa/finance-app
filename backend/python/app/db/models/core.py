from datetime import datetime
from decimal import Decimal
from typing import ClassVar

from sqlalchemy import Boolean, ForeignKey, Numeric, Text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.enums import (
    ACCOUNT_MEMBER_ROLE_DB,
    ACCOUNT_RELATION_TYPE_DB,
    ACCOUNT_TYPE_DB,
    ASSET_TYPE_DB,
    EXCHANGE_RATE_SOURCE_DB,
    PRICE_SOURCE_DB,
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetType,
    ExchangeRateSource,
    PriceSource,
)

_TIMESTAMP = postgresql.TIMESTAMP(precision=3, timezone=False)


class UserModel(Base):
    __tablename__ = "User"
    __table_args__: ClassVar[dict[str, str]] = {"schema": "public"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    password_hash: Mapped[str | None] = mapped_column("passwordHash", Text)
    base_currency: Mapped[str] = mapped_column("baseCurrency", Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column("createdAt", _TIMESTAMP, nullable=False)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", _TIMESTAMP, nullable=False)


class AccountModel(Base):
    __tablename__ = "Account"
    __table_args__: ClassVar[dict[str, str]] = {"schema": "public"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[AccountType] = mapped_column(ACCOUNT_TYPE_DB, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column("isArchived", Boolean, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column("archivedAt", _TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column("createdAt", _TIMESTAMP, nullable=False)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", _TIMESTAMP, nullable=False)


class AccountMemberModel(Base):
    __tablename__ = "AccountMember"
    __table_args__: ClassVar[dict[str, str]] = {"schema": "public"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("public.User.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[AccountMemberRole] = mapped_column(ACCOUNT_MEMBER_ROLE_DB, nullable=False)
    relation_type: Mapped[AccountRelationType] = mapped_column(
        "relationType",
        ACCOUNT_RELATION_TYPE_DB,
        nullable=False,
    )
    invited_by_id: Mapped[str | None] = mapped_column("invitedById", Text)
    accepted_at: Mapped[datetime | None] = mapped_column("acceptedAt", _TIMESTAMP)
    created_at: Mapped[datetime] = mapped_column("createdAt", _TIMESTAMP, nullable=False)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", _TIMESTAMP, nullable=False)


class AssetModel(Base):
    __tablename__ = "Asset"
    __table_args__: ClassVar[dict[str, str]] = {"schema": "public"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    isin: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    asset_type: Mapped[AssetType] = mapped_column("assetType", ASSET_TYPE_DB, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column("createdAt", _TIMESTAMP, nullable=False)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", _TIMESTAMP, nullable=False)


class AssetListingModel(Base):
    __tablename__ = "AssetListing"
    __table_args__: ClassVar[dict[str, str]] = {"schema": "public"}

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
    is_primary: Mapped[bool] = mapped_column("isPrimary", Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column("createdAt", _TIMESTAMP, nullable=False)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", _TIMESTAMP, nullable=False)


class HoldingModel(Base):
    __tablename__ = "Holding"
    __table_args__: ClassVar[dict[str, str]] = {"schema": "public"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    asset_type: Mapped[AssetType] = mapped_column("assetType", ASSET_TYPE_DB, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(28, 10), nullable=False)
    avg_buy_price: Mapped[Decimal] = mapped_column("avgBuyPrice", Numeric(28, 10), nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    current_price: Mapped[Decimal | None] = mapped_column("currentPrice", Numeric(28, 10))
    current_value: Mapped[Decimal | None] = mapped_column("currentValue", Numeric(28, 10))
    unrealized_pnl: Mapped[Decimal | None] = mapped_column("unrealizedPnl", Numeric(28, 10))
    realized_pnl: Mapped[Decimal | None] = mapped_column("realizedPnl", Numeric(28, 10))
    asset_id: Mapped[str | None] = mapped_column(
        "assetId",
        ForeignKey("public.Asset.id"),
    )
    listing_id: Mapped[str] = mapped_column(
        "listingId",
        ForeignKey("public.AssetListing.id"),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id"),
        nullable=False,
    )
    calculated_at: Mapped[datetime] = mapped_column("calculatedAt", _TIMESTAMP, nullable=False)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", _TIMESTAMP, nullable=False)


class ExchangeRateModel(Base):
    __tablename__ = "ExchangeRate"
    __table_args__: ClassVar[dict[str, str]] = {"schema": "public"}

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    from_currency: Mapped[str] = mapped_column("fromCurrency", Text, nullable=False)
    to_currency: Mapped[str] = mapped_column("toCurrency", Text, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    date: Mapped[datetime] = mapped_column(_TIMESTAMP, nullable=False)
    source: Mapped[ExchangeRateSource] = mapped_column(EXCHANGE_RATE_SOURCE_DB, nullable=False)
    created_at: Mapped[datetime] = mapped_column("createdAt", _TIMESTAMP, nullable=False)
