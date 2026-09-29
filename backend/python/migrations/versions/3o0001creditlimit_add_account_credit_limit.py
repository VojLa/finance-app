"""Store the configured limit for credit-card accounts.

Revision ID: 3o0001creditlimit
Revises: 3r0001historycleanup
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3o0001creditlimit"
down_revision: str | None = "3r0001historycleanup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_account_credit_limit"
affected_tables = ("Account",)
affected_columns = ("Account.creditLimit",)
prisma_schema_impact = "required"
data_migration = False


def upgrade() -> None:
    op.add_column(
        "Account",
        sa.Column("creditLimit", sa.Numeric(18, 6), nullable=True),
        schema="public",
    )
    op.create_check_constraint(
        "Account_credit_limit_only_for_credit_cards",
        "Account",
        '"creditLimit" IS NULL OR ("type" = \'credit_card\'::"AccountType" AND "creditLimit" > 0)',
        schema="public",
    )


def downgrade() -> None:
    raise RuntimeError("Credit-limit migration cannot be downgraded automatically.")
