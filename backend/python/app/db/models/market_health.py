from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    MARKET_DATA_HEALTH_FAILURE_REASON_DB,
    MARKET_DATA_HEALTH_STATE_DB,
    PRICE_SOURCE_DB,
    MarketDataFailureReason,
    MarketDataHealthState,
    PriceSource,
)


class MarketDataListingHealthModel(Base):
    __tablename__ = "MarketDataListingHealth"
    __table_args__ = (
        UniqueConstraint(
            "listingId", "provider", name="MarketDataListingHealth_listing_provider_key"
        ),
        CheckConstraint(
            '"consecutiveFailures" >= 0',
            name="MarketDataListingHealth_failures_nonnegative",
        ),
        CheckConstraint('"version" >= 1', name="MarketDataListingHealth_version_positive"),
        CheckConstraint(
            '"totalSuccesses" >= 0 AND "totalFailures" >= 0',
            name="MarketDataListingHealth_totals_nonnegative",
        ),
        CheckConstraint(
            '"providerSymbol" IS NULL OR length(btrim("providerSymbol")) > 0',
            name="MarketDataListingHealth_symbol_nonblank",
        ),
        CheckConstraint(
            '"lastAttemptToken" IS NULL OR length(btrim("lastAttemptToken")) > 0',
            name="MarketDataListingHealth_attempt_token_nonblank",
        ),
        CheckConstraint(
            '("lastAttemptAt" IS NULL) = ("lastAttemptToken" IS NULL)',
            name="MarketDataListingHealth_attempt_pair",
        ),
        CheckConstraint(
            '"leaseOwner" IS NULL OR length(btrim("leaseOwner")) > 0',
            name="MarketDataListingHealth_lease_owner_nonblank",
        ),
        CheckConstraint(
            '("leaseOwner" IS NULL) = ("leaseExpiresAt" IS NULL)',
            name="MarketDataListingHealth_lease_pair",
        ),
        CheckConstraint(
            '"lastFailureReason" NOT IN '
            "('unknown_symbol', 'currency_conflict', 'provider_identity_conflict', "
            "'missing_provider_symbol') OR \"state\" = 'unavailable'",
            name="MarketDataListingHealth_permanent_unavailable",
        ),
        Index("MarketDataListingHealth_provider_state_idx", "provider", "state"),
        Index("MarketDataListingHealth_retryAfter_idx", "retryAfter"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    listing_id: Mapped[str] = mapped_column(
        "listingId", ForeignKey("public.AssetListing.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[PriceSource] = mapped_column(PRICE_SOURCE_DB, nullable=False)
    provider_symbol: Mapped[str | None] = mapped_column("providerSymbol", Text)
    state: Mapped[MarketDataHealthState] = mapped_column(
        MARKET_DATA_HEALTH_STATE_DB,
        nullable=False,
        server_default=text("'unknown'::\"MarketDataHealthState\""),
    )
    last_success_at: Mapped[datetime | None] = mapped_column("lastSuccessAt", TIMESTAMP)
    last_attempt_at: Mapped[datetime | None] = mapped_column("lastAttemptAt", TIMESTAMP)
    consecutive_failures: Mapped[int] = mapped_column(
        "consecutiveFailures", Integer, nullable=False, server_default=text("0")
    )
    last_failure_reason: Mapped[MarketDataFailureReason | None] = mapped_column(
        "lastFailureReason", MARKET_DATA_HEALTH_FAILURE_REASON_DB
    )
    retry_after: Mapped[datetime | None] = mapped_column("retryAfter", TIMESTAMP)
    state_changed_at: Mapped[datetime] = mapped_column("stateChangedAt", TIMESTAMP, nullable=False)
    last_attempt_token: Mapped[str | None] = mapped_column("lastAttemptToken", Text)
    lease_owner: Mapped[str | None] = mapped_column("leaseOwner", Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column("leaseExpiresAt", TIMESTAMP)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    total_successes: Mapped[int] = mapped_column(
        "totalSuccesses", Integer, nullable=False, server_default=text("0")
    )
    total_failures: Mapped[int] = mapped_column(
        "totalFailures", Integer, nullable=False, server_default=text("0")
    )
