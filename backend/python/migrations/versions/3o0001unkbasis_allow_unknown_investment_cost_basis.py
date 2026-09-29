"""Allow truthful unknown investment cost basis without losing market value.

Revision ID: 3o0001unkbasis
Revises: 3n0001emptyhold
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3o0001unkbasis"
down_revision: str | None = "3n0001emptyhold"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "allow_unknown_investment_cost_basis"
affected_tables = ("Holding", "AccountSnapshot", "AccountSnapshotItem")
affected_columns = (
    "Holding.avgBuyPrice",
    "Holding.costBasisByCurrency",
    "AccountSnapshot.investmentCostBasis",
    "AccountSnapshot.netDepositsValue",
    "AccountSnapshot.realizedPnlValue",
    "AccountSnapshot.unrealizedPnlValue",
    "AccountSnapshotItem.costBasis",
    "AccountSnapshotItem.costCurrency",
    "AccountSnapshotItem.nativeCostBasis",
    "AccountSnapshotItem.nativeCostCurrency",
    "AccountSnapshotItem.nativeCostBasisByCurrency",
    "AccountSnapshotItem.averageBuyPrice",
    "AccountSnapshotItem.averageBuyPriceCurrency",
)
prisma_schema_impact = "required"
data_migration = False


def upgrade() -> None:
    op.drop_constraint(
        "Holding_costBasisByCurrency_nonempty_object",
        "Holding",
        schema="public",
        type_="check",
    )
    op.alter_column(
        "Holding",
        "avgBuyPrice",
        schema="public",
        existing_type=sa.Numeric(28, 10),
        nullable=True,
    )
    op.alter_column(
        "Holding",
        "costBasisByCurrency",
        schema="public",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
    )
    op.create_check_constraint(
        "Holding_costBasisByCurrency_nonempty_object",
        "Holding",
        '"costBasisByCurrency" IS NULL OR '
        "(jsonb_typeof(\"costBasisByCurrency\") = 'object' "
        "AND \"costBasisByCurrency\" <> '{}'::jsonb)",
        schema="public",
    )
    op.create_check_constraint(
        "Holding_cost_basis_completeness_pair",
        "Holding",
        '("avgBuyPrice" IS NULL) = ("costBasisByCurrency" IS NULL)',
        schema="public",
    )

    for column_name in (
        "investmentCostBasis",
        "netDepositsValue",
        "realizedPnlValue",
        "unrealizedPnlValue",
    ):
        op.alter_column(
            "AccountSnapshot",
            column_name,
            schema="public",
            existing_type=sa.Numeric(18, 6),
            nullable=True,
            server_default=None,
        )
    op.drop_constraint(
        "AccountSnapshotItem_nativeCostBasisByCurrency_nonempty_object",
        "AccountSnapshotItem",
        schema="public",
        type_="check",
    )
    op.alter_column(
        "AccountSnapshotItem",
        "nativeCostBasisByCurrency",
        schema="public",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=True,
    )
    op.alter_column(
        "AccountSnapshotItem",
        "averageBuyPrice",
        schema="public",
        existing_type=sa.Numeric(28, 10),
        nullable=True,
    )
    op.alter_column(
        "AccountSnapshotItem",
        "averageBuyPriceCurrency",
        schema="public",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.create_check_constraint(
        "AccountSnapshotItem_nativeCostBasisByCurrency_nonempty_object",
        "AccountSnapshotItem",
        '"nativeCostBasisByCurrency" IS NULL OR '
        "(jsonb_typeof(\"nativeCostBasisByCurrency\") = 'object' "
        "AND \"nativeCostBasisByCurrency\" <> '{}'::jsonb)",
        schema="public",
    )
    op.create_check_constraint(
        "AccountSnapshotItem_cost_basis_completeness",
        "AccountSnapshotItem",
        '("costBasis" IS NULL) = ("costCurrency" IS NULL) '
        'AND ("costBasis" IS NULL) = ("nativeCostBasis" IS NULL) '
        'AND ("costBasis" IS NULL) = ("nativeCostCurrency" IS NULL) '
        'AND ("costBasis" IS NULL) = ("nativeCostBasisByCurrency" IS NULL) '
        'AND ("costBasis" IS NULL) = ("averageBuyPrice" IS NULL) '
        'AND ("costBasis" IS NULL) = ("averageBuyPriceCurrency" IS NULL)',
        schema="public",
    )


def downgrade() -> None:
    connection = op.get_bind()
    unknown_evidence_exists = connection.execute(
        sa.text(
            """
            SELECT
                EXISTS (
                    SELECT 1 FROM "public"."Holding"
                    WHERE "avgBuyPrice" IS NULL OR "costBasisByCurrency" IS NULL
                )
                OR EXISTS (
                    SELECT 1 FROM "public"."AccountSnapshot"
                    WHERE "investmentCostBasis" IS NULL
                       OR "netDepositsValue" IS NULL
                       OR "realizedPnlValue" IS NULL
                       OR "unrealizedPnlValue" IS NULL
                )
                OR EXISTS (
                    SELECT 1 FROM "public"."AccountSnapshotItem"
                    WHERE "nativeCostBasisByCurrency" IS NULL
                       OR "averageBuyPrice" IS NULL
                       OR "averageBuyPriceCurrency" IS NULL
                )
            """
        )
    ).scalar_one()
    if unknown_evidence_exists:
        raise RuntimeError(
            "Cannot remove unknown investment cost-basis support while incomplete evidence exists."
        )

    op.drop_constraint(
        "AccountSnapshotItem_cost_basis_completeness",
        "AccountSnapshotItem",
        schema="public",
        type_="check",
    )
    op.drop_constraint(
        "AccountSnapshotItem_nativeCostBasisByCurrency_nonempty_object",
        "AccountSnapshotItem",
        schema="public",
        type_="check",
    )
    op.create_check_constraint(
        "AccountSnapshotItem_nativeCostBasisByCurrency_nonempty_object",
        "AccountSnapshotItem",
        "jsonb_typeof(\"nativeCostBasisByCurrency\") = 'object' "
        "AND \"nativeCostBasisByCurrency\" <> '{}'::jsonb",
        schema="public",
    )
    op.alter_column(
        "AccountSnapshotItem",
        "averageBuyPriceCurrency",
        schema="public",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "AccountSnapshotItem",
        "averageBuyPrice",
        schema="public",
        existing_type=sa.Numeric(28, 10),
        nullable=False,
    )
    op.alter_column(
        "AccountSnapshotItem",
        "nativeCostBasisByCurrency",
        schema="public",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
    )

    for column_name in (
        "unrealizedPnlValue",
        "realizedPnlValue",
        "netDepositsValue",
        "investmentCostBasis",
    ):
        op.alter_column(
            "AccountSnapshot",
            column_name,
            schema="public",
            existing_type=sa.Numeric(18, 6),
            nullable=False,
            server_default=sa.text("0"),
        )

    op.drop_constraint(
        "Holding_cost_basis_completeness_pair",
        "Holding",
        schema="public",
        type_="check",
    )
    op.drop_constraint(
        "Holding_costBasisByCurrency_nonempty_object",
        "Holding",
        schema="public",
        type_="check",
    )
    op.create_check_constraint(
        "Holding_costBasisByCurrency_nonempty_object",
        "Holding",
        "jsonb_typeof(\"costBasisByCurrency\") = 'object' "
        "AND \"costBasisByCurrency\" <> '{}'::jsonb",
        schema="public",
    )
    op.alter_column(
        "Holding",
        "costBasisByCurrency",
        schema="public",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
    )
    op.alter_column(
        "Holding",
        "avgBuyPrice",
        schema="public",
        existing_type=sa.Numeric(28, 10),
        nullable=False,
    )
