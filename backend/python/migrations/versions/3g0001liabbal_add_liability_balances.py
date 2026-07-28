"""Add canonical liability balance observations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3g0001liabbal"
down_revision: str | None = "3f0001acctnote"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_liability_balance_contract"
affected_tables = ("LiabilityBalance",)
affected_columns = (
    "LiabilityBalance.id",
    "LiabilityBalance.accountId",
    "LiabilityBalance.effectiveAt",
    "LiabilityBalance.currency",
    "LiabilityBalance.outstandingPrincipal",
    "LiabilityBalance.accruedInterest",
    "LiabilityBalance.feesOutstanding",
    "LiabilityBalance.totalOutstanding",
    "LiabilityBalance.source",
    "LiabilityBalance.externalId",
    "LiabilityBalance.createdAt",
)
prisma_schema_impact = "required"
data_migration = False

SOURCE_VALUES = ("manual", "statement", "provider", "import", "migration")
source_enum = postgresql.ENUM(
    *SOURCE_VALUES,
    name="LiabilityBalanceSource",
    schema="public",
)


def upgrade() -> None:
    source_enum.create(op.get_bind(), checkfirst=False)
    op.create_table(
        "LiabilityBalance",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("effectiveAt", postgresql.TIMESTAMP(precision=3), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("outstandingPrincipal", sa.Numeric(18, 6), nullable=False),
        sa.Column("accruedInterest", sa.Numeric(18, 6), nullable=False),
        sa.Column("feesOutstanding", sa.Numeric(18, 6), nullable=False),
        sa.Column("totalOutstanding", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "source",
            postgresql.ENUM(
                *SOURCE_VALUES,
                name="LiabilityBalanceSource",
                schema="public",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("externalId", sa.Text(), nullable=True),
        sa.Column("createdAt", postgresql.TIMESTAMP(precision=3), nullable=False),
        sa.CheckConstraint(
            '"outstandingPrincipal" >= 0',
            name="LiabilityBalance_outstandingPrincipal_nonnegative",
        ),
        sa.CheckConstraint(
            '"accruedInterest" >= 0',
            name="LiabilityBalance_accruedInterest_nonnegative",
        ),
        sa.CheckConstraint(
            '"feesOutstanding" >= 0',
            name="LiabilityBalance_feesOutstanding_nonnegative",
        ),
        sa.CheckConstraint(
            '"totalOutstanding" >= 0',
            name="LiabilityBalance_totalOutstanding_nonnegative",
        ),
        sa.CheckConstraint(
            '"totalOutstanding" = "outstandingPrincipal" + "accruedInterest" + "feesOutstanding"',
            name="LiabilityBalance_totalOutstanding_components",
        ),
        sa.ForeignKeyConstraint(
            ["accountId"],
            ["public.Account.id"],
            name="LiabilityBalance_accountId_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="LiabilityBalance_pkey"),
        schema="public",
    )
    op.create_index(
        "LiabilityBalance_accountId_effectiveAt_idx",
        "LiabilityBalance",
        ["accountId", "effectiveAt"],
        schema="public",
    )
    op.create_index(
        "LiabilityBalance_accountId_effectiveAt_source_key",
        "LiabilityBalance",
        ["accountId", "effectiveAt", "source"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "LiabilityBalance_accountId_source_externalId_key",
        "LiabilityBalance",
        ["accountId", "source", "externalId"],
        unique=True,
        schema="public",
    )


def downgrade() -> None:
    connection = op.get_bind()
    rows_exist = connection.execute(
        sa.text('SELECT EXISTS (SELECT 1 FROM "public"."LiabilityBalance")')
    ).scalar_one()
    if rows_exist:
        raise RuntimeError(
            "Cannot remove LiabilityBalance while canonical liability evidence exists."
        )
    op.drop_index(
        "LiabilityBalance_accountId_source_externalId_key",
        table_name="LiabilityBalance",
        schema="public",
    )
    op.drop_index(
        "LiabilityBalance_accountId_effectiveAt_source_key",
        table_name="LiabilityBalance",
        schema="public",
    )
    op.drop_index(
        "LiabilityBalance_accountId_effectiveAt_idx",
        table_name="LiabilityBalance",
        schema="public",
    )
    op.drop_table("LiabilityBalance", schema="public")
    source_enum.drop(connection, checkfirst=False)
