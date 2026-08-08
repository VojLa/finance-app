"""Add canonical revision and daily baseline lineage."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3i0001d1base"
down_revision: str | None = "3h0001twdata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

schema_change = True
schema_change_kind = "add_daily_baseline_lineage"
affected_tables = (
    "AccountCanonicalState",
    "AccountCanonicalChange",
    "AccountSnapshotCanonicalBoundary",
    "DailySnapshotBaseline",
    "DailySnapshotBaselineAccount",
)
affected_columns: tuple[str, ...] = ()
prisma_schema_impact = "required"
data_migration = True


def upgrade() -> None:
    op.create_table(
        "AccountCanonicalState",
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("lastRevision", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "lastInvestmentRevision",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("holdingRevision", sa.BigInteger(), nullable=True),
        sa.Column("updatedAt", postgresql.TIMESTAMP(precision=3), nullable=False),
        sa.CheckConstraint(
            '"lastRevision" >= 0',
            name="AccountCanonicalState_lastRevision_nonnegative",
        ),
        sa.CheckConstraint(
            '"lastInvestmentRevision" >= 0',
            name="AccountCanonicalState_lastInvestmentRevision_nonnegative",
        ),
        sa.CheckConstraint(
            '"lastInvestmentRevision" <= "lastRevision"',
            name="AccountCanonicalState_investment_not_after_last",
        ),
        sa.CheckConstraint(
            '"holdingRevision" IS NULL OR "holdingRevision" >= 0',
            name="AccountCanonicalState_holdingRevision_nonnegative",
        ),
        sa.CheckConstraint(
            '"holdingRevision" IS NULL OR "holdingRevision" <= "lastInvestmentRevision"',
            name="AccountCanonicalState_holding_not_after_investment",
        ),
        sa.ForeignKeyConstraint(
            ["accountId"],
            ["public.Account.id"],
            name="AccountCanonicalState_accountId_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("accountId", name="AccountCanonicalState_pkey"),
        schema="public",
    )
    op.create_table(
        "AccountCanonicalChange",
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("entityId", sa.Text(), nullable=False),
        sa.Column("financialTimestamp", postgresql.TIMESTAMP(precision=3), nullable=False),
        sa.Column("createdAt", postgresql.TIMESTAMP(precision=3), nullable=False),
        sa.CheckConstraint(
            '"revision" > 0',
            name="AccountCanonicalChange_revision_positive",
        ),
        sa.CheckConstraint(
            "\"kind\" IN ('transaction', 'investment_event', 'liability_balance')",
            name="AccountCanonicalChange_kind_supported",
        ),
        sa.ForeignKeyConstraint(
            ["accountId"],
            ["public.Account.id"],
            name="AccountCanonicalChange_accountId_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("accountId", "revision", name="AccountCanonicalChange_pkey"),
        schema="public",
    )
    op.create_index(
        "AccountCanonicalChange_kind_entityId_key",
        "AccountCanonicalChange",
        ["kind", "entityId"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "AccountCanonicalChange_account_financial_revision_idx",
        "AccountCanonicalChange",
        ["accountId", "financialTimestamp", "revision"],
        schema="public",
    )
    op.execute(
        sa.text(
            """
            CREATE FUNCTION "public"."initializeAccountCanonicalState"()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                INSERT INTO "public"."AccountCanonicalState"
                    ("accountId", "lastRevision", "lastInvestmentRevision", "holdingRevision", "updatedAt")
                VALUES (NEW."id", 0, 0, NULL, NEW."updatedAt");
                RETURN NEW;
            END;
            $$
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER "Account_initializeCanonicalState"
            AFTER INSERT ON "public"."Account"
            FOR EACH ROW EXECUTE FUNCTION "public"."initializeAccountCanonicalState"()
            """
        )
    )
    op.create_table(
        "AccountSnapshotCanonicalBoundary",
        sa.Column("snapshotId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column("canonicalRevision", sa.BigInteger(), nullable=False),
        sa.Column("investmentRevision", sa.BigInteger(), nullable=True),
        sa.Column("holdingRevision", sa.BigInteger(), nullable=True),
        sa.Column("selectedLiabilityBalanceId", sa.Text(), nullable=True),
        sa.Column("createdAt", postgresql.TIMESTAMP(precision=3), nullable=False),
        sa.CheckConstraint(
            '"canonicalRevision" >= 0',
            name="AccountSnapshotCanonicalBoundary_canonical_nonnegative",
        ),
        sa.CheckConstraint(
            '"investmentRevision" IS NULL OR "investmentRevision" >= 0',
            name="AccountSnapshotCanonicalBoundary_investment_nonnegative",
        ),
        sa.CheckConstraint(
            '"holdingRevision" IS NULL OR "holdingRevision" >= 0',
            name="AccountSnapshotCanonicalBoundary_holding_nonnegative",
        ),
        sa.CheckConstraint(
            '(("investmentRevision" IS NULL) = ("holdingRevision" IS NULL))',
            name="AccountSnapshotCanonicalBoundary_investment_holding_pair",
        ),
        sa.CheckConstraint(
            '"investmentRevision" IS NULL OR "investmentRevision" = "holdingRevision"',
            name="AccountSnapshotCanonicalBoundary_holding_fresh",
        ),
        sa.CheckConstraint(
            '"investmentRevision" IS NULL OR "investmentRevision" <= "canonicalRevision"',
            name="AccountSnapshotCanonicalBoundary_investment_not_after_canonical",
        ),
        sa.ForeignKeyConstraint(
            ["snapshotId"],
            ["public.AccountSnapshot.id"],
            name="AccountSnapshotCanonicalBoundary_snapshotId_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["accountId"],
            ["public.Account.id"],
            name="AccountSnapshotCanonicalBoundary_accountId_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["selectedLiabilityBalanceId"],
            ["public.LiabilityBalance.id"],
            name="AccountSnapshotBoundary_liabilityBalanceId_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("snapshotId", name="AccountSnapshotCanonicalBoundary_pkey"),
        schema="public",
    )
    op.create_index(
        "AccountSnapshotBoundary_account_canonicalRevision_idx",
        "AccountSnapshotCanonicalBoundary",
        ["accountId", "canonicalRevision"],
        schema="public",
    )
    op.create_table(
        "DailySnapshotBaseline",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("userId", sa.Text(), nullable=False),
        sa.Column("netWorthSnapshotId", sa.Text(), nullable=False),
        sa.Column("timestamp", postgresql.TIMESTAMP(precision=3), nullable=False),
        sa.Column(
            "granularity",
            postgresql.ENUM(
                "minute",
                "hour",
                "day",
                "week",
                "month",
                name="SnapshotGranularity",
                schema="public",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("calculationVersion", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            postgresql.ENUM(
                "import_event",
                "price_refresh",
                "holdings_recalculation",
                "scheduled",
                "manual_recalculation",
                name="SnapshotSource",
                schema="public",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("createdAt", postgresql.TIMESTAMP(precision=3), nullable=False),
        sa.CheckConstraint(
            '"granularity" = \'day\'::"SnapshotGranularity"',
            name="DailySnapshotBaseline_day_only",
        ),
        sa.CheckConstraint(
            '"calculationVersion" > 0',
            name="DailySnapshotBaseline_calculationVersion_positive",
        ),
        sa.ForeignKeyConstraint(
            ["userId"],
            ["public.User.id"],
            name="DailySnapshotBaseline_userId_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["netWorthSnapshotId"],
            ["public.NetWorthSnapshot.id"],
            name="DailySnapshotBaseline_netWorthSnapshotId_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="DailySnapshotBaseline_pkey"),
        schema="public",
    )
    op.create_index(
        "DailySnapshotBaseline_netWorthSnapshotId_key",
        "DailySnapshotBaseline",
        ["netWorthSnapshotId"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "DailyBaseline_user_timestamp_currency_version_key",
        "DailySnapshotBaseline",
        ["userId", "timestamp", "currency", "calculationVersion"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "DailySnapshotBaseline_userId_timestamp_idx",
        "DailySnapshotBaseline",
        ["userId", "timestamp"],
        schema="public",
    )
    op.create_table(
        "DailySnapshotBaselineAccount",
        sa.Column("baselineId", sa.Text(), nullable=False),
        sa.Column("accountId", sa.Text(), nullable=False),
        sa.Column(
            "accountType",
            postgresql.ENUM(
                "bank",
                "cash",
                "savings",
                "broker",
                "exchange",
                "crypto_wallet",
                "credit_card",
                "loan",
                "mortgage",
                name="AccountType",
                schema="public",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("accountCurrency", sa.Text(), nullable=False),
        sa.Column("primarySnapshotId", sa.Text(), nullable=False),
        sa.Column("presentationSnapshotId", sa.Text(), nullable=False),
        sa.Column("canonicalRevision", sa.BigInteger(), nullable=False),
        sa.Column("investmentRevision", sa.BigInteger(), nullable=True),
        sa.Column("holdingRevision", sa.BigInteger(), nullable=True),
        sa.Column("selectedLiabilityBalanceId", sa.Text(), nullable=True),
        sa.CheckConstraint(
            '"canonicalRevision" >= 0',
            name="DailySnapshotBaselineAccount_canonical_nonnegative",
        ),
        sa.CheckConstraint(
            '"investmentRevision" IS NULL OR "investmentRevision" >= 0',
            name="DailySnapshotBaselineAccount_investment_nonnegative",
        ),
        sa.CheckConstraint(
            '"holdingRevision" IS NULL OR "holdingRevision" >= 0',
            name="DailySnapshotBaselineAccount_holding_nonnegative",
        ),
        sa.CheckConstraint(
            '(("investmentRevision" IS NULL) = ("holdingRevision" IS NULL))',
            name="DailySnapshotBaselineAccount_investment_holding_pair",
        ),
        sa.CheckConstraint(
            '"investmentRevision" IS NULL OR "investmentRevision" = "holdingRevision"',
            name="DailySnapshotBaselineAccount_holding_fresh",
        ),
        sa.ForeignKeyConstraint(
            ["baselineId"],
            ["public.DailySnapshotBaseline.id"],
            name="DailySnapshotBaselineAccount_baselineId_fkey",
            onupdate="CASCADE",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["accountId"],
            ["public.Account.id"],
            name="DailySnapshotBaselineAccount_accountId_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["primarySnapshotId"],
            ["public.AccountSnapshot.id"],
            name="DailySnapshotBaselineAccount_primarySnapshotId_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["presentationSnapshotId"],
            ["public.AccountSnapshot.id"],
            name="DailySnapshotBaselineAccount_presentationSnapshotId_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selectedLiabilityBalanceId"],
            ["public.LiabilityBalance.id"],
            name="DailySnapshotBaselineAccount_selectedLiabilityBalanceId_fkey",
            onupdate="CASCADE",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "baselineId", "accountId", name="DailySnapshotBaselineAccount_pkey"
        ),
        schema="public",
    )
    op.create_index(
        "DailySnapshotBaselineAccount_baselineId_primarySnapshotId_key",
        "DailySnapshotBaselineAccount",
        ["baselineId", "primarySnapshotId"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "DailyBaselineAccount_baseline_presentationSnapshot_key",
        "DailySnapshotBaselineAccount",
        ["baselineId", "presentationSnapshotId"],
        unique=True,
        schema="public",
    )
    op.create_index(
        "DailySnapshotBaselineAccount_accountId_baselineId_idx",
        "DailySnapshotBaselineAccount",
        ["accountId", "baselineId"],
        schema="public",
    )

    op.execute(
        sa.text(
            """
            INSERT INTO "public"."AccountCanonicalState"
                ("accountId", "lastRevision", "lastInvestmentRevision", "holdingRevision", "updatedAt")
            SELECT "id", 0, 0, NULL, "updatedAt"
            FROM "public"."Account"
            ORDER BY "id"
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH roots AS (
                SELECT "accountId", 'transaction'::text AS kind, "id" AS "entityId",
                       "date" AS "financialTimestamp", "createdAt"
                FROM "public"."Transaction"
                UNION ALL
                SELECT "accountId", 'investment_event'::text, "id", "date", "createdAt"
                FROM "public"."InvestmentEvent"
                UNION ALL
                SELECT "accountId", 'liability_balance'::text, "id", "effectiveAt", "createdAt"
                FROM "public"."LiabilityBalance"
            ), ordered AS (
                SELECT "accountId", kind, "entityId", "financialTimestamp", "createdAt",
                       row_number() OVER (
                           PARTITION BY "accountId"
                           ORDER BY "createdAt", kind, "entityId"
                       )::bigint AS revision
                FROM roots
            )
            INSERT INTO "public"."AccountCanonicalChange"
                ("accountId", revision, kind, "entityId", "financialTimestamp", "createdAt")
            SELECT "accountId", revision, kind, "entityId", "financialTimestamp", "createdAt"
            FROM ordered
            ORDER BY "accountId", revision
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE "public"."AccountCanonicalState" AS state
            SET "lastRevision" = summary.last_revision,
                "lastInvestmentRevision" = summary.last_investment_revision
            FROM (
                SELECT "accountId", max(revision) AS last_revision,
                       coalesce(max(revision) FILTER (WHERE kind = 'investment_event'), 0) AS last_investment_revision
                FROM "public"."AccountCanonicalChange"
                GROUP BY "accountId"
            ) AS summary
            WHERE state."accountId" = summary."accountId"
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    has_lineage = connection.execute(
        sa.text(
            """
            SELECT
                EXISTS (SELECT 1 FROM "public"."AccountCanonicalChange")
                OR EXISTS (SELECT 1 FROM "public"."AccountSnapshotCanonicalBoundary")
                OR EXISTS (SELECT 1 FROM "public"."DailySnapshotBaseline")
                OR EXISTS (
                    SELECT 1 FROM "public"."AccountCanonicalState"
                    WHERE "lastRevision" <> 0 OR "lastInvestmentRevision" <> 0
                       OR "holdingRevision" IS NOT NULL
                )
            """
        )
    ).scalar_one()
    if has_lineage:
        raise RuntimeError("Cannot remove persisted daily-baseline lineage automatically.")
    op.drop_index(
        "DailySnapshotBaselineAccount_accountId_baselineId_idx",
        table_name="DailySnapshotBaselineAccount",
        schema="public",
    )
    op.drop_table("DailySnapshotBaselineAccount", schema="public")
    op.drop_index(
        "DailySnapshotBaseline_userId_timestamp_idx",
        table_name="DailySnapshotBaseline",
        schema="public",
    )
    op.drop_table("DailySnapshotBaseline", schema="public")
    op.drop_index(
        "AccountSnapshotBoundary_account_canonicalRevision_idx",
        table_name="AccountSnapshotCanonicalBoundary",
        schema="public",
    )
    op.drop_table("AccountSnapshotCanonicalBoundary", schema="public")
    op.drop_index(
        "AccountCanonicalChange_account_financial_revision_idx",
        table_name="AccountCanonicalChange",
        schema="public",
    )
    op.drop_table("AccountCanonicalChange", schema="public")
    op.execute('DROP TRIGGER "Account_initializeCanonicalState" ON "public"."Account"')
    op.execute('DROP FUNCTION "public"."initializeAccountCanonicalState"()')
    op.drop_table("AccountCanonicalState", schema="public")
