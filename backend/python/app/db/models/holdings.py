from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import QUANTITY, TIMESTAMP
from app.db.models.enums import ASSET_TYPE_DB, AssetType


class HoldingModel(Base):
    __tablename__ = "Holding"
    __table_args__ = (
        UniqueConstraint("accountId", "listingId"),
        Index(None, "accountId"),
        Index(None, "assetId"),
        Index(None, "listingId"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    symbol: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    asset_type: Mapped[AssetType] = mapped_column("assetType", ASSET_TYPE_DB, nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    avg_buy_price: Mapped[Decimal] = mapped_column("avgBuyPrice", QUANTITY, nullable=False)
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    current_price: Mapped[Decimal | None] = mapped_column("currentPrice", QUANTITY)
    current_value: Mapped[Decimal | None] = mapped_column("currentValue", QUANTITY)
    unrealized_pnl: Mapped[Decimal | None] = mapped_column("unrealizedPnl", QUANTITY)
    realized_pnl: Mapped[Decimal | None] = mapped_column("realizedPnl", QUANTITY)
    asset_id: Mapped[str | None] = mapped_column(
        "assetId",
        ForeignKey("public.Asset.id", ondelete="SET NULL"),
    )
    listing_id: Mapped[str] = mapped_column(
        "listingId",
        ForeignKey("public.AssetListing.id", ondelete="RESTRICT"),
        nullable=False,
    )
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="RESTRICT"),
        nullable=False,
    )
    calculated_at: Mapped[datetime] = mapped_column(
        "calculatedAt",
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)
