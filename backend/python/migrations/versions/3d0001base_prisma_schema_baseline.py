"""Baseline for the Prisma-owned production schema.

Revision ID: 3d0001base
Revises: None
Create Date: 2026-07-17

"""
from collections.abc import Sequence

revision: str = "3d0001base"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = ("prisma_baseline",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """The inherited Prisma schema already exists before this revision is stamped."""


def downgrade() -> None:
    """Prevent Alembic from dropping a schema that it did not create."""
    raise RuntimeError("The Prisma schema baseline cannot be downgraded automatically.")
