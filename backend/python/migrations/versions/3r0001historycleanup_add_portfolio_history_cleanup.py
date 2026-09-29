"""Add provenance-preserving portfolio-history cleanup receipts.

Revision ID: 3r0001historycleanup
Revises: 3q0001historygen
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3r0001historycleanup"
down_revision: str | None = "3q0001historygen"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_portfolio_history_cleanup_receipts"
affected_tables = (
    "PortfolioHistoryGeneration",
    "PortfolioHistoryGenerationCleanupReceipt",
    "PortfolioHistoryScheduleState",
)
prisma_schema_impact = "required"

_TIMESTAMP = postgresql.TIMESTAMP(precision=3)


def upgrade() -> None:
    op.execute('ALTER TYPE "public"."PortfolioHistoryJobKind" ADD VALUE \'history_cleanup\'')
    op.add_column(
        "PortfolioHistoryGeneration",
        sa.Column("supersededAt", _TIMESTAMP),
        schema="public",
    )
    op.create_check_constraint(
        "PortfolioHistoryGeneration_supersededAt_state",
        "PortfolioHistoryGeneration",
        '"supersededAt" IS NULL OR "state" = \'superseded\'::"HistoryGenerationState"',
        schema="public",
    )
    op.add_column(
        "PortfolioHistoryScheduleState",
        sa.Column("lastCleanedAt", _TIMESTAMP),
        schema="public",
    )
    op.create_table(
        "PortfolioHistoryGenerationCleanupReceipt",
        sa.Column("generationId", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("auditJobId", sa.Text(), nullable=False),
        sa.Column("retentionPolicyVersion", sa.Integer(), nullable=False),
        sa.Column("auditPolicyVersion", sa.Integer(), nullable=False),
        sa.Column("payloadManifestHash", sa.Text(), nullable=False),
        sa.Column("generationAccountCount", sa.BigInteger(), nullable=False),
        sa.Column("replayCheckpointCount", sa.BigInteger(), nullable=False),
        sa.Column("pointCount", sa.BigInteger(), nullable=False),
        sa.Column("accountPointCount", sa.BigInteger(), nullable=False),
        sa.Column("coverageCount", sa.BigInteger(), nullable=False),
        sa.Column("priceLineageCount", sa.BigInteger(), nullable=False),
        sa.Column("fxLineageCount", sa.BigInteger(), nullable=False),
        sa.Column("cleanedAt", _TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            '"retentionPolicyVersion" >= 1 AND "auditPolicyVersion" >= 1',
            name="PortfolioHistoryCleanupReceipt_policy_versions_positive",
        ),
        sa.CheckConstraint(
            "\"payloadManifestHash\" ~ '^[0-9a-f]{64}$'",
            name="PortfolioHistoryCleanupReceipt_manifest_sha256",
        ),
        sa.CheckConstraint(
            '"generationAccountCount" >= 0 AND "replayCheckpointCount" >= 0 AND '
            '"pointCount" >= 0 AND "accountPointCount" >= 0 AND "coverageCount" >= 0 AND '
            '"priceLineageCount" >= 0 AND "fxLineageCount" >= 0',
            name="PortfolioHistoryCleanupReceipt_counts_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["generationId", "userId"],
            ["public.PortfolioHistoryGeneration.id", "public.PortfolioHistoryGeneration.userId"],
            name="PortfolioHistoryCleanupReceipt_generation_user_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["auditJobId", "userId"],
            ["public.PortfolioHistoryJob.id", "public.PortfolioHistoryJob.userId"],
            name="PortfolioHistoryCleanupReceipt_audit_job_user_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("generationId"),
        schema="public",
    )
    op.create_index(
        "PortfolioHistoryCleanupReceipt_user_cleaned_idx",
        "PortfolioHistoryGenerationCleanupReceipt",
        ["userId", "cleanedAt"],
        schema="public",
    )


def downgrade() -> None:
    raise RuntimeError("Portfolio history cleanup provenance cannot be downgraded automatically.")
