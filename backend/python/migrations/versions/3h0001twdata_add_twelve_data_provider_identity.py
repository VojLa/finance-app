"""Add explicit Twelve Data provider identity."""

from collections.abc import Sequence

from alembic import op

revision: str = "3h0001twdata"
down_revision: str | None = "3g0001liabbal"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "extend_market_provider_identity_enums"
affected_tables = ("AssetAlias", "AssetListing", "PriceSnapshot")
affected_columns = (
    "AssetAlias.provider",
    "AssetListing.provider",
    "PriceSnapshot.source",
)
prisma_schema_impact = "required"
data_migration = False


def upgrade() -> None:
    op.execute(
        'ALTER TYPE "public"."AssetAliasProvider" '
        "ADD VALUE IF NOT EXISTS 'twelve_data' BEFORE 'broker'"
    )
    op.execute(
        'ALTER TYPE "public"."PriceSource" '
        "ADD VALUE IF NOT EXISTS 'twelve_data' BEFORE 'manual'"
    )


def downgrade() -> None:
    raise RuntimeError("Twelve Data provider enum values cannot be downgraded automatically.")
