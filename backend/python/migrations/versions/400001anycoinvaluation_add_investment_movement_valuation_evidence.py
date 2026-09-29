"""Add append-only valuation evidence for immutable investment movements.

Revision ID: 400001anycoinvaluation
Revises: 3z0001historydrop
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "400001anycoinvaluation"
down_revision: str | None = "3z0001historydrop"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_investment_movement_valuation_evidence"
affected_tables = ("InvestmentMovementValuationEvidence",)
prisma_schema_impact = "required"
data_migration = False

_TIMESTAMP = postgresql.TIMESTAMP(precision=3)
_PRICE_SOURCE = postgresql.ENUM(name="PriceSource", schema="public", create_type=False)
_EXCHANGE_RATE_SOURCE = postgresql.ENUM(
    name="ExchangeRateSource", schema="public", create_type=False
)
_QUANTITY = sa.Numeric(28, 10)
_RATE = sa.Numeric(18, 8)


def upgrade() -> None:
    op.create_table(
        "InvestmentMovementValuationEvidence",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("movementId", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("canonicalRevision", sa.BigInteger(), nullable=False),
        sa.Column("effectiveAt", _TIMESTAMP, nullable=False),
        sa.Column("calculationVersion", sa.Integer(), nullable=False),
        sa.Column("selectionInterval", sa.Text(), nullable=False),
        sa.Column("inputFingerprint", sa.Text(), nullable=False),
        sa.Column("priceSnapshotId", sa.Text(), nullable=False),
        sa.Column("exchangeRateId", sa.Text()),
        sa.Column("priceAmount", _QUANTITY, nullable=False),
        sa.Column("priceCurrency", sa.Text(), nullable=False),
        sa.Column("priceSource", _PRICE_SOURCE, nullable=False),
        sa.Column("priceTimestamp", _TIMESTAMP, nullable=False),
        sa.Column("fxRate", _RATE),
        sa.Column("fxFromCurrency", sa.Text()),
        sa.Column("fxToCurrency", sa.Text()),
        sa.Column("fxSource", _EXCHANGE_RATE_SOURCE),
        sa.Column("fxTimestamp", _TIMESTAMP),
        sa.Column("pricePerUnit", _QUANTITY, nullable=False),
        sa.Column("valueAmount", _QUANTITY, nullable=False),
        sa.Column("valueCurrency", sa.Text(), nullable=False),
        sa.Column(
            "createdAt",
            _TIMESTAMP,
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            '"revision" >= 1',
            name="InvestmentMovementValuationEvidence_revision_positive",
        ),
        sa.CheckConstraint(
            '"canonicalRevision" >= 1',
            name="InvestmentMovementValuationEvidence_canonicalRevision_positive",
        ),
        sa.CheckConstraint(
            '"calculationVersion" >= 1',
            name="InvestmentMovementValuationEvidence_calculationVersion_positive",
        ),
        sa.CheckConstraint(
            "\"selectionInterval\" IN ('30min', '1day')",
            name="InvestmentMovementValuationEvidence_selectionInterval_known",
        ),
        sa.CheckConstraint(
            '"priceAmount" > 0',
            name="InvestmentMovementValuationEvidence_priceAmount_positive",
        ),
        sa.CheckConstraint(
            '"pricePerUnit" > 0',
            name="InvestmentMovementValuationEvidence_pricePerUnit_positive",
        ),
        sa.CheckConstraint(
            '"valueAmount" > 0',
            name="InvestmentMovementValuationEvidence_valueAmount_positive",
        ),
        sa.CheckConstraint(
            '(("exchangeRateId" IS NULL AND "fxRate" IS NULL '
            'AND "fxFromCurrency" IS NULL AND "fxToCurrency" IS NULL '
            'AND "fxSource" IS NULL AND "fxTimestamp" IS NULL) OR '
            '("exchangeRateId" IS NOT NULL AND "fxRate" IS NOT NULL '
            'AND "fxFromCurrency" IS NOT NULL AND "fxToCurrency" IS NOT NULL '
            'AND "fxSource" IS NOT NULL AND "fxTimestamp" IS NOT NULL))',
            name="InvestmentMovementValuationEvidence_fx_complete_or_absent",
        ),
        sa.ForeignKeyConstraint(
            ["accountId"],
            ["public.Account.id"],
            name="InvestmentMovementValuationEvidence_account_fkey",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["movementId"],
            ["public.InvestmentMovement.id"],
            name="InvestmentMovementValuationEvidence_movement_fkey",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["priceSnapshotId"],
            ["public.PriceSnapshot.id"],
            name="InvestmentMovementValuationEvidence_priceSnapshot_fkey",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exchangeRateId"],
            ["public.ExchangeRate.id"],
            name="InvestmentMovementValuationEvidence_exchangeRate_fkey",
            ondelete="RESTRICT",
            onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema="public",
    )
    op.create_index(
        "InvestmentMovementValuationEvidence_accountId_idx",
        "InvestmentMovementValuationEvidence",
        ["accountId"],
        schema="public",
    )
    op.create_index(
        "InvestmentMovementValuationEvidence_movementId_idx",
        "InvestmentMovementValuationEvidence",
        ["movementId"],
        schema="public",
    )
    op.create_index(
        "InvestmentMovementValuationEvidence_movement_revision_key",
        "InvestmentMovementValuationEvidence",
        ["movementId", "revision"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "InvestmentMovementValuationEvidence_movement_fingerprint_key",
        "InvestmentMovementValuationEvidence",
        ["movementId", "inputFingerprint"],
        unique=True,
        schema="public",
    )


def downgrade() -> None:
    op.drop_table("InvestmentMovementValuationEvidence", schema="public")
