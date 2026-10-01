"""Append-only record of explicit server-operator alias decisions."""

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TIMESTAMP


class AssetAliasAuditModel(Base):
    __tablename__ = "AssetAliasAudit"
    __table_args__ = (
        CheckConstraint("length(btrim(actor)) > 0", name="AssetAliasAudit_actor_nonblank"),
        CheckConstraint(
            "action IN ('alias_created', 'alias_replayed', 'listing_created', 'listing_replayed', 'rejected')",
            name="AssetAliasAudit_action_allowed",
        ),
        Index("AssetAliasAudit_asset_created_idx", "assetId", "createdAt"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    actor: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    asset_id: Mapped[str] = mapped_column("assetId", Text, nullable=False)
    listing_id: Mapped[str | None] = mapped_column("listingId", Text)
    provider: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column("externalId", Text)
    before_identity: Mapped[dict | None] = mapped_column("beforeIdentity", JSONB)
    after_identity: Mapped[dict | None] = mapped_column("afterIdentity", JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        "createdAt", TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
