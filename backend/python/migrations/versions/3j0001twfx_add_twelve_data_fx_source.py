"""Add the Twelve Data direct-pair FX source identity.

Revision ID: 3j0001twfx
Revises: 3i0001d1base
"""

from alembic import op

revision = "3j0001twfx"
down_revision = "3i0001d1base"
branch_labels = None
depends_on = None

schema_change = True
schema_change_kind = "extend_exchange_rate_source_identity"
affected_tables = ("ExchangeRate",)
prisma_schema_impact = "required"
data_migration = False


def upgrade() -> None:
    op.execute(
        'ALTER TYPE "public"."ExchangeRateSource" '
        "ADD VALUE IF NOT EXISTS 'twelve_data' BEFORE 'cnb'"
    )


def downgrade() -> None:
    # This enum extension cannot be downgraded automatically. PostgreSQL enum value
    # removal requires a destructive type rewrite, while historical source identities
    # and snapshot audit references must remain readable.
    pass
