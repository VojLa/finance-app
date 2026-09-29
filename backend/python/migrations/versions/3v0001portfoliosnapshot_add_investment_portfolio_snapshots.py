"""Add generation-bound investment-account and portfolio snapshot projections.

Revision ID: 3v0001portfoliosnapshot
Revises: 3u0001snapshotgeneration
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3v0001portfoliosnapshot"
down_revision: str | None = "3u0001snapshotgeneration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_investment_portfolio_snapshot_projections"
affected_tables = (
    "InvestmentAccountSnapshot",
    "InvestmentAccountSnapshotItem",
    "PortfolioSnapshot",
    "PortfolioSnapshotInput",
    "PortfolioSnapshotItem",
    "PortfolioSnapshotItemAccount",
)
prisma_schema_impact = "required"
data_migration = False

_JSONB = postgresql.JSONB(astext_type=sa.Text())
_TIMESTAMP = postgresql.TIMESTAMP(precision=3)
_GRANULARITY = postgresql.ENUM(name="SnapshotGranularity", schema="public", create_type=False)
_SOURCE = postgresql.ENUM(name="SnapshotSource", schema="public", create_type=False)
_PRICE_SOURCE = postgresql.ENUM(name="PriceSource", schema="public", create_type=False)
_MONEY = sa.Numeric(18, 6)
_QUANTITY = sa.Numeric(28, 10)
_PERCENTAGE = sa.Numeric(8, 4)


def _projection_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("timestamp", _TIMESTAMP, nullable=False),
        sa.Column("valuationTimestamp", _TIMESTAMP, nullable=False),
        sa.Column("granularity", _GRANULARITY, nullable=False),
        sa.Column("source", _SOURCE, nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("cashValue", _MONEY, nullable=False),
        sa.Column("investmentValue", _MONEY, nullable=False),
        sa.Column("investmentCostBasis", _MONEY),
        sa.Column("netDepositsValue", _MONEY),
        sa.Column("realizedPnlValue", _MONEY),
        sa.Column("unrealizedPnlValue", _MONEY),
        sa.Column("feesValue", _MONEY, nullable=False, server_default=sa.text("0")),
        sa.Column("taxesValue", _MONEY, nullable=False, server_default=sa.text("0")),
        sa.Column("cashValueByCurrency", _JSONB),
        sa.Column("investmentValueByCurrency", _JSONB),
        sa.Column("investmentCostBasisByCurrency", _JSONB),
        sa.Column("netDepositsByCurrency", _JSONB),
        sa.Column("realizedPnlByCurrency", _JSONB),
        sa.Column("unrealizedPnlByCurrency", _JSONB),
        sa.Column("feesByCurrency", _JSONB),
        sa.Column("taxesByCurrency", _JSONB),
        sa.Column("priceEvidence", _JSONB),
        sa.Column("exchangeRates", _JSONB),
        sa.Column(
            "calculatedAt", _TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column("calculationVersion", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "createdAt", _TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
    ]


def _position_columns() -> list[sa.Column[object]]:
    return [
        sa.Column("assetId", sa.Text()),
        sa.Column("listingId", sa.Text(), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("quantity", _QUANTITY, nullable=False),
        sa.Column("pricePerUnit", _QUANTITY, nullable=False),
        sa.Column("priceCurrency", sa.Text()),
        sa.Column("priceSource", _PRICE_SOURCE),
        sa.Column("priceTimestamp", _TIMESTAMP),
        sa.Column("value", _MONEY, nullable=False),
        sa.Column("costBasis", _MONEY),
        sa.Column("allocationPct", _PERCENTAGE, nullable=False),
        sa.Column("nativeValue", _QUANTITY),
        sa.Column("valueCurrency", sa.Text()),
        sa.Column("nativeCostBasis", _QUANTITY),
        sa.Column("nativeCostCurrency", sa.Text()),
        sa.Column("priceEvidence", _JSONB),
        sa.Column(
            "createdAt", _TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "InvestmentAccountSnapshot",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("accountSnapshotId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("generationId", sa.Text(), nullable=False),
        *_projection_columns(),
        sa.ForeignKeyConstraint(
            ["accountSnapshotId", "generationId", "accountId"],
            [
                "public.AccountSnapshot.id",
                "public.AccountSnapshot.generationId",
                "public.AccountSnapshot.accountId",
            ],
            name="InvestmentAccountSnapshot_account_snapshot_generation_fkey",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "accountSnapshotId", name="InvestmentAccountSnapshot_accountSnapshot_key"
        ),
        sa.UniqueConstraint(
            "id",
            "generationId",
            "accountId",
            name="InvestmentAccountSnapshot_id_generation_account_key",
        ),
        sa.UniqueConstraint(
            "id",
            "accountSnapshotId",
            "generationId",
            "accountId",
            name="InvestmentAccountSnapshot_input_coordinate_key",
        ),
        schema="public",
    )
    op.create_index(
        "InvestmentAccountSnapshot_generation_account_timestamp_idx",
        "InvestmentAccountSnapshot",
        ["generationId", "accountId", "timestamp"],
        schema="public",
    )
    op.create_table(
        "InvestmentAccountSnapshotItem",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("investmentAccountSnapshotId", sa.Text(), nullable=False),
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        *_position_columns(),
        sa.ForeignKeyConstraint(
            ["assetId"], ["public.Asset.id"], ondelete="SET NULL", onupdate="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["listingId"], ["public.AssetListing.id"], ondelete="RESTRICT", onupdate="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["investmentAccountSnapshotId", "generationId", "accountId"],
            [
                "public.InvestmentAccountSnapshot.id",
                "public.InvestmentAccountSnapshot.generationId",
                "public.InvestmentAccountSnapshot.accountId",
            ],
            name="InvestmentAccountSnapshotItem_snapshot_generation_account_fkey",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "investmentAccountSnapshotId",
            "listingId",
            name="InvestmentAccountSnapshotItem_snapshot_listing_key",
        ),
        schema="public",
    )
    op.create_index(
        "InvestmentAccountSnapshotItem_listingId_idx",
        "InvestmentAccountSnapshotItem",
        ["listingId"],
        schema="public",
    )
    op.create_table(
        "PortfolioSnapshot",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("generationId", sa.Text(), nullable=False),
        *_projection_columns(),
        sa.ForeignKeyConstraint(
            ["userId"], ["public.User.id"], ondelete="RESTRICT", onupdate="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["generationId", "userId"],
            [
                "public.SnapshotGenerationTarget.generationId",
                "public.SnapshotGenerationTarget.userId",
            ],
            name="PortfolioSnapshot_generation_target_fkey",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "userId",
            "timestamp",
            "currency",
            "granularity",
            "generationId",
            name="PortfolioSnapshot_coordinate_generation_key",
        ),
        sa.UniqueConstraint(
            "id", "generationId", "userId", name="PortfolioSnapshot_id_generation_user_key"
        ),
        schema="public",
    )
    op.create_index(
        "PortfolioSnapshot_generation_user_timestamp_idx",
        "PortfolioSnapshot",
        ["generationId", "userId", "timestamp"],
        schema="public",
    )
    op.create_table(
        "PortfolioSnapshotInput",
        sa.Column("portfolioSnapshotId", sa.Text(), nullable=False),
        sa.Column("investmentAccountSnapshotId", sa.Text(), nullable=False),
        sa.Column("accountSnapshotId", sa.Text(), nullable=False),
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column(
            "createdAt", _TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(
            ["portfolioSnapshotId", "generationId", "userId"],
            [
                "public.PortfolioSnapshot.id",
                "public.PortfolioSnapshot.generationId",
                "public.PortfolioSnapshot.userId",
            ],
            name="PortfolioSnapshotInput_portfolio_generation_user_fkey",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [
                "investmentAccountSnapshotId",
                "accountSnapshotId",
                "generationId",
                "accountId",
            ],
            [
                "public.InvestmentAccountSnapshot.id",
                "public.InvestmentAccountSnapshot.accountSnapshotId",
                "public.InvestmentAccountSnapshot.generationId",
                "public.InvestmentAccountSnapshot.accountId",
            ],
            name="PortfolioSnapshotInput_investment_generation_account_fkey",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["accountSnapshotId", "generationId", "accountId"],
            [
                "public.AccountSnapshot.id",
                "public.AccountSnapshot.generationId",
                "public.AccountSnapshot.accountId",
            ],
            name="PortfolioSnapshotInput_account_snapshot_generation_fkey",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["accountId", "userId"],
            ["public.AccountMember.accountId", "public.AccountMember.userId"],
            name="PortfolioSnapshotInput_authorized_account_user_fkey",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("portfolioSnapshotId", "investmentAccountSnapshotId"),
        sa.UniqueConstraint(
            "portfolioSnapshotId",
            "investmentAccountSnapshotId",
            name="PortfolioSnapshotInput_portfolio_investment_key",
        ),
        sa.UniqueConstraint(
            "portfolioSnapshotId",
            "investmentAccountSnapshotId",
            "accountSnapshotId",
            "generationId",
            "userId",
            "accountId",
            name="PortfolioSnapshotInput_coordinate_key",
        ),
        schema="public",
    )
    op.create_table(
        "PortfolioSnapshotItem",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("portfolioSnapshotId", sa.Text(), nullable=False),
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=False),
        *_position_columns(),
        sa.ForeignKeyConstraint(
            ["assetId"], ["public.Asset.id"], ondelete="SET NULL", onupdate="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["listingId"], ["public.AssetListing.id"], ondelete="RESTRICT", onupdate="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["portfolioSnapshotId", "generationId", "userId"],
            [
                "public.PortfolioSnapshot.id",
                "public.PortfolioSnapshot.generationId",
                "public.PortfolioSnapshot.userId",
            ],
            name="PortfolioSnapshotItem_snapshot_generation_user_fkey",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "portfolioSnapshotId",
            "listingId",
            name="PortfolioSnapshotItem_snapshot_listing_key",
        ),
        sa.UniqueConstraint(
            "id",
            "portfolioSnapshotId",
            "generationId",
            "userId",
            "listingId",
            name="PortfolioSnapshotItem_identity_key",
        ),
        schema="public",
    )
    op.create_index(
        "PortfolioSnapshotItem_listingId_idx",
        "PortfolioSnapshotItem",
        ["listingId"],
        schema="public",
    )
    op.create_table(
        "PortfolioSnapshotItemAccount",
        sa.Column("portfolioSnapshotItemId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("portfolioSnapshotId", sa.Text(), nullable=False),
        sa.Column("investmentAccountSnapshotId", sa.Text(), nullable=False),
        sa.Column("accountSnapshotId", sa.Text(), nullable=False),
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("listingId", sa.Text(), nullable=False),
        sa.Column("quantity", _QUANTITY, nullable=False),
        sa.Column("value", _MONEY, nullable=False),
        sa.Column("costBasis", _MONEY),
        sa.Column("allocationPct", _PERCENTAGE, nullable=False),
        sa.Column(
            "createdAt", _TIMESTAMP, nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(
            [
                "portfolioSnapshotId",
                "investmentAccountSnapshotId",
                "accountSnapshotId",
                "generationId",
                "userId",
                "accountId",
            ],
            [
                "public.PortfolioSnapshotInput.portfolioSnapshotId",
                "public.PortfolioSnapshotInput.investmentAccountSnapshotId",
                "public.PortfolioSnapshotInput.accountSnapshotId",
                "public.PortfolioSnapshotInput.generationId",
                "public.PortfolioSnapshotInput.userId",
                "public.PortfolioSnapshotInput.accountId",
            ],
            name="PortfolioSnapshotItemAccount_input_coordinate_fkey",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [
                "portfolioSnapshotItemId",
                "portfolioSnapshotId",
                "generationId",
                "userId",
                "listingId",
            ],
            [
                "public.PortfolioSnapshotItem.id",
                "public.PortfolioSnapshotItem.portfolioSnapshotId",
                "public.PortfolioSnapshotItem.generationId",
                "public.PortfolioSnapshotItem.userId",
                "public.PortfolioSnapshotItem.listingId",
            ],
            name="PortfolioSnapshotItemAccount_item_coordinate_fkey",
            ondelete="CASCADE",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("portfolioSnapshotItemId", "accountId"),
        sa.UniqueConstraint(
            "portfolioSnapshotItemId",
            "accountId",
            name="PortfolioSnapshotItemAccount_item_account_key",
        ),
        schema="public",
    )


def downgrade() -> None:
    for table in (
        "PortfolioSnapshotItemAccount",
        "PortfolioSnapshotItem",
        "PortfolioSnapshotInput",
        "PortfolioSnapshot",
        "InvestmentAccountSnapshotItem",
        "InvestmentAccountSnapshot",
    ):
        op.drop_table(table, schema="public")
