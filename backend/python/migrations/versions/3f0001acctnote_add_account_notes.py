"""Add optional account notes as the first Alembic-owned schema change."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f0001acctnote"
down_revision: str | None = "3e0001cutover"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_nullable_column"
affected_tables = ("Account",)
affected_columns = ("Account.notes",)
prisma_schema_impact = "required"
data_migration = False


def upgrade() -> None:
    """Add a nullable account note without rewriting existing rows."""
    op.add_column(
        "Account",
        sa.Column("notes", sa.Text(), nullable=True),
        schema="public",
    )


def downgrade() -> None:
    """Remove the column only when doing so cannot discard account notes."""
    connection = op.get_bind()
    notes_exist = connection.execute(
        sa.text('SELECT EXISTS (SELECT 1 FROM "public"."Account" WHERE "notes" IS NOT NULL)')
    ).scalar_one()
    if notes_exist:
        raise RuntimeError("Cannot remove Account.notes while non-null account note data exists.")
    op.drop_column("Account", "notes", schema="public")
