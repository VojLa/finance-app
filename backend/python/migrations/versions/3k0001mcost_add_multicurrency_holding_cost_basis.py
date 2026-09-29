"""Persist canonical multi-currency holding and snapshot-item cost basis.

Revision ID: 3k0001mcost
Revises: 3j0001twfx
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3k0001mcost"
down_revision: str | None = "3j0001twfx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_multicurrency_holding_cost_basis"
affected_tables = ("Holding", "AccountSnapshotItem")
affected_columns = (
    "Holding.costBasisByCurrency",
    "AccountSnapshotItem.nativeCostBasisByCurrency",
    "AccountSnapshotItem.averageBuyPrice",
    "AccountSnapshotItem.averageBuyPriceCurrency",
)
prisma_schema_impact = "required"
data_migration = True


def half_even_quantity_sql(scaled_expression: str) -> str:
    """Return the canonical 10dp HALF_EVEN SQL expression for positive values."""
    return f"""\
        CASE
            WHEN {scaled_expression} - floor({scaled_expression}) < 0.5
                THEN floor({scaled_expression})
            WHEN {scaled_expression} - floor({scaled_expression}) > 0.5
                THEN floor({scaled_expression}) + 1
            WHEN mod(floor({scaled_expression}), 2) = 0 THEN floor({scaled_expression})
            ELSE floor({scaled_expression}) + 1
        END / 10000000000::numeric
    """


def upgrade() -> None:
    """Backfill immutable single-currency evidence before enforcing the new contract."""
    op.add_column(
        "Holding",
        sa.Column("costBasisByCurrency", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="public",
    )
    op.add_column(
        "AccountSnapshotItem",
        sa.Column(
            "nativeCostBasisByCurrency",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        schema="public",
    )
    op.add_column(
        "AccountSnapshotItem",
        sa.Column("averageBuyPrice", sa.Numeric(28, 10), nullable=True),
        schema="public",
    )
    op.add_column(
        "AccountSnapshotItem",
        sa.Column("averageBuyPriceCurrency", sa.Text(), nullable=True),
        schema="public",
    )

    connection = op.get_bind()
    incomplete_snapshot_cost = connection.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM "public"."AccountSnapshotItem"
                WHERE "nativeCostBasis" IS NULL
                   OR "nativeCostCurrency" IS NULL
                   OR "nativeCostBasis" <= 0
                   OR "quantity" <= 0
            )
            """
        )
    ).scalar_one()
    if incomplete_snapshot_cost:
        raise RuntimeError(
            "Cannot backfill AccountSnapshotItem.nativeCostBasisByCurrency "
            "without a complete native cost pair."
        )

    invalid_holding_cost = connection.execute(
        sa.text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM "public"."Holding"
                WHERE "quantity" <= 0
                   OR "avgBuyPrice" <= 0
                   OR "currency" = ''
            )
            """
        )
    ).scalar_one()
    if invalid_holding_cost:
        raise RuntimeError(
            "Cannot backfill Holding.costBasisByCurrency from invalid legacy holding evidence."
        )

    # PostgreSQL round(numeric, 10) is half-away-from-zero.  The canonical
    # QUANTITY boundary is explicitly HALF_EVEN, so calculate the 10dp integer
    # first and choose the even neighbour on ties.
    op.execute(
        sa.text(
            f"""
            WITH exact_cost AS (
                SELECT
                    "id",
                    "currency",
                    ("quantity" * "avgBuyPrice") * 10000000000::numeric AS scaled
                FROM "public"."Holding"
            ), rounded_cost AS (
                SELECT
                    "id",
                    "currency",
                    {half_even_quantity_sql("scaled")} AS amount
                FROM exact_cost
            )
            UPDATE "public"."Holding" AS holding
            SET "costBasisByCurrency" = jsonb_build_object(
                rounded_cost."currency",
                to_jsonb((rounded_cost.amount::numeric(28, 10))::text)
            )
            FROM rounded_cost
            WHERE holding."id" = rounded_cost."id"
            """
        )
    )
    # The historic native pair is the only pre-R12 quote-price evidence.  Use
    # the same explicit 10dp HALF_EVEN boundary as the Holding backfill.
    op.execute(
        sa.text(
            f"""
            WITH exact_average AS (
                SELECT
                    "id",
                    "nativeCostCurrency",
                    ("nativeCostBasis" / "quantity") * 10000000000::numeric AS scaled
                FROM "public"."AccountSnapshotItem"
            ), rounded_average AS (
                SELECT
                    "id",
                    "nativeCostCurrency",
                    {half_even_quantity_sql("scaled")} AS amount
                FROM exact_average
            )
            UPDATE "public"."AccountSnapshotItem" AS item
            SET "averageBuyPrice" = rounded_average.amount::numeric(28, 10),
                "averageBuyPriceCurrency" = rounded_average."nativeCostCurrency"
            FROM rounded_average
            WHERE item."id" = rounded_average."id"
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE "public"."AccountSnapshotItem"
            SET "nativeCostBasisByCurrency" = jsonb_build_object(
                "nativeCostCurrency",
                to_jsonb("nativeCostBasis"::text)
            )
            """
        )
    )

    op.alter_column("Holding", "costBasisByCurrency", nullable=False, schema="public")
    op.alter_column(
        "AccountSnapshotItem",
        "nativeCostBasisByCurrency",
        nullable=False,
        schema="public",
    )
    op.alter_column("AccountSnapshotItem", "averageBuyPrice", nullable=False, schema="public")
    op.alter_column(
        "AccountSnapshotItem",
        "averageBuyPriceCurrency",
        nullable=False,
        schema="public",
    )
    op.create_check_constraint(
        "Holding_costBasisByCurrency_nonempty_object",
        "Holding",
        "jsonb_typeof(\"costBasisByCurrency\") = 'object' "
        "AND \"costBasisByCurrency\" <> '{}'::jsonb",
        schema="public",
    )
    op.create_check_constraint(
        "AccountSnapshotItem_nativeCostBasisByCurrency_nonempty_object",
        "AccountSnapshotItem",
        "jsonb_typeof(\"nativeCostBasisByCurrency\") = 'object' "
        "AND \"nativeCostBasisByCurrency\" <> '{}'::jsonb",
        schema="public",
    )


def downgrade() -> None:
    """Refuse to discard settlement evidence that old rows cannot represent."""
    connection = op.get_bind()
    has_lossy_cost_evidence = connection.execute(
        sa.text(
            f"""
            SELECT
                EXISTS (
                    SELECT 1
                    FROM "public"."Holding"
                    WHERE 1 < (
                        SELECT count(*)
                        FROM jsonb_object_keys("costBasisByCurrency")
                    )
                )
                OR EXISTS (
                    SELECT 1
                    FROM "public"."AccountSnapshotItem"
                    WHERE 1 < (
                        SELECT count(*)
                        FROM jsonb_object_keys("nativeCostBasisByCurrency")
                    )
                )
                OR EXISTS (
                    SELECT 1
                    FROM "public"."AccountSnapshotItem"
                    WHERE "averageBuyPriceCurrency" <> "nativeCostCurrency"
                       OR "averageBuyPrice" <> (
                           {
                half_even_quantity_sql('("nativeCostBasis" / "quantity") * 10000000000::numeric')
            }
                       )::numeric(28, 10)
                )
            """
        )
    ).scalar_one()
    if has_lossy_cost_evidence:
        raise RuntimeError(
            "Cannot remove multi-currency or quote-average cost-basis evidence automatically."
        )

    op.drop_constraint(
        "AccountSnapshotItem_nativeCostBasisByCurrency_nonempty_object",
        "AccountSnapshotItem",
        schema="public",
        type_="check",
    )
    op.drop_constraint(
        "Holding_costBasisByCurrency_nonempty_object",
        "Holding",
        schema="public",
        type_="check",
    )
    op.drop_column("AccountSnapshotItem", "averageBuyPriceCurrency", schema="public")
    op.drop_column("AccountSnapshotItem", "averageBuyPrice", schema="public")
    op.drop_column("AccountSnapshotItem", "nativeCostBasisByCurrency", schema="public")
    op.drop_column("Holding", "costBasisByCurrency", schema="public")
