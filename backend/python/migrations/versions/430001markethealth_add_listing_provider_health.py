"""Add persisted health for an exact listing/provider identity.

Revision ID: 430001markethealth
Revises: 420001yahooidentity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "430001markethealth"
down_revision: str | None = "420001yahooidentity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_listing_provider_health"
affected_tables = ("MarketDataListingHealth",)
prisma_schema_impact = "required"
data_migration = False

_TIMESTAMP = postgresql.TIMESTAMP(precision=3, timezone=False)
_PRICE_SOURCE = postgresql.ENUM(name="PriceSource", schema="public", create_type=False)
_STATE = postgresql.ENUM(name="MarketDataHealthState", schema="public", create_type=False)
_REASON = postgresql.ENUM(name="MarketDataFailureReason", schema="public", create_type=False)


def upgrade() -> None:
    op.execute(
        'CREATE TYPE "public"."MarketDataHealthState" AS ENUM '
        "('healthy', 'suspect', 'degraded', 'unavailable', 'unknown')"
    )
    op.execute(
        'CREATE TYPE "public"."MarketDataFailureReason" AS ENUM '
        "('timeout', 'rate_limit', 'server_error', 'unknown_symbol', "
        "'currency_conflict', 'provider_identity_conflict', 'incomplete_response', "
        "'invalid_price', 'stale_timestamp', 'market_closed', 'missing_provider_symbol')"
    )
    op.create_table(
        "MarketDataListingHealth",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "listingId",
            sa.Text(),
            sa.ForeignKey("public.AssetListing.id", ondelete="CASCADE", onupdate="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", _PRICE_SOURCE, nullable=False),
        sa.Column("providerSymbol", sa.Text()),
        sa.Column(
            "state",
            _STATE,
            nullable=False,
            server_default=sa.text("'unknown'::\"MarketDataHealthState\""),
        ),
        sa.Column("lastSuccessAt", _TIMESTAMP),
        sa.Column("lastAttemptAt", _TIMESTAMP),
        sa.Column("consecutiveFailures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lastFailureReason", _REASON),
        sa.Column("retryAfter", _TIMESTAMP),
        sa.Column("stateChangedAt", _TIMESTAMP, nullable=False),
        sa.Column("lastAttemptToken", sa.Text()),
        sa.Column("leaseOwner", sa.Text()),
        sa.Column("leaseExpiresAt", _TIMESTAMP),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("totalSuccesses", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("totalFailures", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            '"consecutiveFailures" >= 0',
            name="MarketDataListingHealth_failures_nonnegative",
        ),
        sa.CheckConstraint('"version" >= 1', name="MarketDataListingHealth_version_positive"),
        sa.CheckConstraint(
            '"totalSuccesses" >= 0 AND "totalFailures" >= 0',
            name="MarketDataListingHealth_totals_nonnegative",
        ),
        sa.CheckConstraint(
            '"providerSymbol" IS NULL OR length(btrim("providerSymbol")) > 0',
            name="MarketDataListingHealth_symbol_nonblank",
        ),
        sa.CheckConstraint(
            '"lastAttemptToken" IS NULL OR length(btrim("lastAttemptToken")) > 0',
            name="MarketDataListingHealth_attempt_token_nonblank",
        ),
        sa.CheckConstraint(
            '("lastAttemptAt" IS NULL) = ("lastAttemptToken" IS NULL)',
            name="MarketDataListingHealth_attempt_pair",
        ),
        sa.CheckConstraint(
            '"leaseOwner" IS NULL OR length(btrim("leaseOwner")) > 0',
            name="MarketDataListingHealth_lease_owner_nonblank",
        ),
        sa.CheckConstraint(
            '("leaseOwner" IS NULL) = ("leaseExpiresAt" IS NULL)',
            name="MarketDataListingHealth_lease_pair",
        ),
        sa.CheckConstraint(
            '"lastFailureReason" NOT IN '
            "('unknown_symbol', 'currency_conflict', 'provider_identity_conflict', "
            "'missing_provider_symbol') OR \"state\" = 'unavailable'",
            name="MarketDataListingHealth_permanent_unavailable",
        ),
        schema="public",
    )
    op.create_index(
        "MarketDataListingHealth_listing_provider_key",
        "MarketDataListingHealth",
        ["listingId", "provider"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "MarketDataListingHealth_provider_state_idx",
        "MarketDataListingHealth",
        ["provider", "state"],
        schema="public",
    )
    op.create_index(
        "MarketDataListingHealth_retryAfter_idx",
        "MarketDataListingHealth",
        ["retryAfter"],
        schema="public",
    )


def downgrade() -> None:
    raise RuntimeError("Persisted market-data health must not be discarded by downgrade.")
