"""Add listing-scoped provider identity and price-symbol lineage.

Revision ID: 420001yahooidentity
Revises: 410001serieslinks
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "420001yahooidentity"
down_revision: str | None = "410001serieslinks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_listing_market_identity"
affected_tables = ("AssetListing", "AssetAlias", "PriceSnapshot")
prisma_schema_impact = "required"
data_migration = True


def upgrade() -> None:
    op.add_column(
        "AssetListing",
        sa.Column("basePriority", sa.Integer(), nullable=False, server_default=sa.text("0")),
        schema="public",
    )
    op.create_check_constraint(
        "AssetListing_basePriority_nonnegative",
        "AssetListing",
        '"basePriority" >= 0',
        schema="public",
    )
    op.create_index(
        "AssetListing_id_assetId_key",
        "AssetListing",
        ["id", "assetId"],
        unique=True,
        schema="public",
    )
    op.add_column("AssetAlias", sa.Column("listingId", sa.Text()), schema="public")
    op.create_foreign_key(
        "AssetAlias_listing_asset_fkey",
        "AssetAlias",
        "AssetListing",
        ["listingId", "assetId"],
        ["id", "assetId"],
        source_schema="public",
        referent_schema="public",
        onupdate="CASCADE",
        ondelete="CASCADE",
    )
    op.create_index("AssetAlias_listingId_idx", "AssetAlias", ["listingId"], schema="public")
    # Existing duplicate aliases for one asset/provider cannot identify a single
    # provider symbol. They remain unresolved rather than blocking or deleting data.
    op.execute("""
        WITH unique_listing AS (
            SELECT "assetId", min("id") AS "listingId"
            FROM "public"."AssetListing"
            GROUP BY "assetId"
            HAVING count(*) = 1
        ), unique_alias AS (
            SELECT "assetId", "provider"
            FROM "public"."AssetAlias"
            GROUP BY "assetId", "provider"
            HAVING count(*) = 1
        )
        UPDATE "public"."AssetAlias" a
        SET "listingId" = l."listingId"
        FROM unique_listing l
        JOIN unique_alias u ON u."assetId" = l."assetId"
        WHERE a."assetId" = l."assetId" AND a."provider" = u."provider"
    """)
    op.create_index(
        "AssetAlias_listingId_provider_key",
        "AssetAlias",
        ["listingId", "provider"],
        unique=True,
        schema="public",
    )
    op.add_column("PriceSnapshot", sa.Column("providerSymbol", sa.Text()), schema="public")
    # Historical observations did not persist the exact provider symbol used at
    # acquisition time.  A current listing or alias cannot prove that lineage,
    # so legacy rows intentionally remain NULL and fail closed until refreshed.
    # The one exception is the narrowly proven Anycoin BTC transfer pipeline:
    # it always requested Yahoo BTC-USD and USD/CZK for an exact BTC/CZK Anycoin
    # listing.  Move those rows to a separate native-USD Yahoo reference listing
    # instead of leaving USD evidence attached to the CZK broker listing.
    op.execute("""
        WITH exact_anycoin_assets AS (
            SELECT min("assetId") AS "assetId", min("createdAt") AS "createdAt",
                   max("updatedAt") AS "updatedAt"
            FROM "public"."AssetListing"
            WHERE "symbol" = 'BTC'
              AND "exchange" = 'anycoin'
              AND "currency" = 'CZK'
              AND "provider" = 'exchange'
              AND "providerSymbol" = 'BTC'
            HAVING count(DISTINCT "assetId") = 1
        )
        INSERT INTO "public"."AssetListing" (
            "id", "assetId", "symbol", "exchange", "mic", "currency", "country",
            "provider", "providerSymbol", "isPrimary", "createdAt", "updatedAt",
            "basePriority"
        )
        SELECT "assetId" || '-yahoo-btc-usd', "assetId", 'BTC-USD', 'yahoo_crypto',
               NULL, 'USD', NULL, 'yahoo_finance', 'BTC-USD', false,
               "createdAt", "updatedAt", 0
        FROM exact_anycoin_assets
        ON CONFLICT DO NOTHING
    """)
    op.execute("""
        UPDATE "public"."PriceSnapshot" p
        SET "listingId" = r."id", "providerSymbol" = 'BTC-USD'
        FROM "public"."AssetListing" a
        JOIN "public"."AssetListing" r
          ON r."assetId" = a."assetId"
         AND r."provider" = 'yahoo_finance'
         AND r."providerSymbol" = 'BTC-USD'
         AND r."currency" = 'USD'
        WHERE p."listingId" = a."id"
          AND p."assetId" = a."assetId"
          AND p."source" = 'yahoo_finance'
          AND p."currency" = 'USD'
          AND a."symbol" = 'BTC'
          AND a."exchange" = 'anycoin'
          AND a."currency" = 'CZK'
          AND a."provider" = 'exchange'
          AND a."providerSymbol" = 'BTC'
    """)
    op.execute("""
        UPDATE "public"."AssetAlias" a
        SET "listingId" = r."id"
        FROM "public"."AssetListing" r
        WHERE a."assetId" = r."assetId"
          AND a."provider" = 'yahoo_finance'
          AND a."externalId" = 'BTC-USD'
          AND r."provider" = 'yahoo_finance'
          AND r."providerSymbol" = 'BTC-USD'
          AND r."currency" = 'USD'
    """)


def downgrade() -> None:
    raise RuntimeError("Listing-scoped provider identity and price lineage cannot be discarded.")
