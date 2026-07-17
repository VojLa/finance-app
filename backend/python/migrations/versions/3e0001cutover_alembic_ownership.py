"""Record the migration ownership cutover from Prisma to Alembic."""

from collections.abc import Sequence

revision: str = "3e0001cutover"
down_revision: str | None = "3d0001base"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ownership_cutover = True
previous_migration_owner = "prisma"
new_migration_owner = "alembic"
baseline_revision = "3d0001base"
prisma_archive_sha256 = "beac94880bdd44822530a39f120d2ea44b0414e04a76eeccf9bb5b8d35233cee"
prisma_schema_impact = "none"


def upgrade() -> None:
    """Record the ownership boundary without changing application schema."""


def downgrade() -> None:
    """Prevent automatic reversal of the migration ownership boundary."""
    raise RuntimeError("The Alembic ownership cutover cannot be downgraded automatically.")
