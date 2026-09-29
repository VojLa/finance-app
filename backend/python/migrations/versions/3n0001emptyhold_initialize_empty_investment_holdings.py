"""Initialize the provably empty Holding revision for investment accounts.

Revision ID: 3n0001emptyhold
Revises: 3m0001importanchor
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3n0001emptyhold"
down_revision: str | None = "3m0001importanchor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "initialize_empty_investment_holding_revision"
affected_tables = ("Account", "AccountCanonicalState", "Holding")
affected_columns = (
    "Account.type",
    "AccountCanonicalState.lastInvestmentRevision",
    "AccountCanonicalState.holdingRevision",
    "Holding.accountId",
)
prisma_schema_impact = "required"
data_migration = True

_INVESTMENT_ACCOUNT_TYPES = "'broker', 'exchange', 'crypto_wallet'"


def _replace_initializer(*, investment_holding_revision: str) -> None:
    op.execute(
        sa.text(
            f"""
            CREATE OR REPLACE FUNCTION "public"."initializeAccountCanonicalState"()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                INSERT INTO "public"."AccountCanonicalState"
                    ("accountId", "lastRevision", "lastInvestmentRevision", "holdingRevision", "updatedAt")
                VALUES (
                    NEW."id",
                    0,
                    0,
                    {investment_holding_revision},
                    NEW."updatedAt"
                );
                RETURN NEW;
            END;
            $$
            """
        )
    )


def upgrade() -> None:
    _replace_initializer(
        investment_holding_revision=(
            f'CASE WHEN NEW."type" IN ({_INVESTMENT_ACCOUNT_TYPES}) THEN 0 ELSE NULL END'
        )
    )
    op.execute(
        sa.text(
            f"""
            UPDATE "public"."AccountCanonicalState" AS state
            SET "holdingRevision" = 0
            FROM "public"."Account" AS account
            WHERE account."id" = state."accountId"
              AND account."type" IN ({_INVESTMENT_ACCOUNT_TYPES})
              AND state."lastInvestmentRevision" = 0
              AND state."holdingRevision" IS NULL
              AND NOT EXISTS (
                  SELECT 1
                  FROM "public"."Holding" AS holding
                  WHERE holding."accountId" = state."accountId"
              )
              AND NOT EXISTS (
                  SELECT 1
                  FROM "public"."AccountCanonicalChange" AS change
                  WHERE change."accountId" = state."accountId"
                    AND change."kind" = 'investment_event'
              )
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    initialized_evidence_exists = connection.execute(
        sa.text(
            f"""
            SELECT EXISTS (
                SELECT 1
                FROM "public"."AccountCanonicalState" AS state
                JOIN "public"."Account" AS account
                  ON account."id" = state."accountId"
                WHERE account."type" IN ({_INVESTMENT_ACCOUNT_TYPES})
                  AND state."lastInvestmentRevision" = 0
                  AND state."holdingRevision" = 0
            )
            """
        )
    ).scalar_one()
    if initialized_evidence_exists:
        raise RuntimeError(
            "Cannot remove initialized empty investment Holding revisions automatically."
        )
    _replace_initializer(investment_holding_revision="NULL")
