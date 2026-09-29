from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import JSONB, TIMESTAMP
from app.db.models.enums import (
    ACCOUNT_TYPE_DB,
    SNAPSHOT_GRANULARITY_DB,
    SNAPSHOT_SOURCE_DB,
    AccountType,
    SnapshotGranularity,
    SnapshotSource,
)


class SnapshotGenerationModel(Base):
    """A staged or published batch of derived snapshots shared by its user targets."""

    __tablename__ = "SnapshotGeneration"
    __table_args__ = (
        UniqueConstraint("id", "state", name="SnapshotGeneration_id_state_key"),
        CheckConstraint(
            "\"state\" IN ('staged', 'published')",
            name="SnapshotGeneration_state_known",
        ),
        CheckConstraint(
            '(("state" = \'staged\' AND "publishedAt" IS NULL) OR '
            '("state" = \'published\' AND "publishedAt" IS NOT NULL))',
            name="SnapshotGeneration_publication_lifecycle",
        ),
        Index(None, "state", "createdAt"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column("createdAt", TIMESTAMP, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column("publishedAt", TIMESTAMP)


class SnapshotGenerationTargetModel(Base):
    """A user's complete, pointer-addressable target within a shared snapshot batch."""

    __tablename__ = "SnapshotGenerationTarget"
    __table_args__ = (
        ForeignKeyConstraint(
            ("generationId",),
            ("public.SnapshotGeneration.id",),
            name="SnapshotGenerationTarget_generationId_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("stagedByJobId", "userId"),
            ("public.SnapshotSeriesRebuildJob.id", "public.SnapshotSeriesRebuildJob.userId"),
            name="SnapshotGenerationTarget_staging_job_user_fkey",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            '("stagedByJobId" IS NULL AND "stagedLeaseVersion" IS NULL AND "stagedLeaseOwner" IS NULL) OR '
            '("stagedByJobId" IS NOT NULL AND "stagedLeaseVersion" IS NOT NULL AND "stagedLeaseVersion" >= 0 AND "stagedLeaseOwner" IS NOT NULL)',
            name="SnapshotGenerationTarget_staging_provenance_complete",
        ),
        Index(None, "userId", "generationId"),
        {"schema": "public"},
    )

    generation_id: Mapped[str] = mapped_column("generationId", Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("public.User.id", ondelete="CASCADE"),
        primary_key=True,
    )
    created_at: Mapped[datetime] = mapped_column("createdAt", TIMESTAMP, nullable=False)
    staged_by_job_id: Mapped[str | None] = mapped_column("stagedByJobId", Text)
    staged_lease_version: Mapped[int | None] = mapped_column("stagedLeaseVersion", BigInteger)
    staged_lease_owner: Mapped[str | None] = mapped_column("stagedLeaseOwner", Text)


class AccountCanonicalStateModel(Base):
    __tablename__ = "AccountCanonicalState"
    __table_args__ = (
        CheckConstraint(
            '"lastRevision" >= 0',
            name="AccountCanonicalState_lastRevision_nonnegative",
        ),
        CheckConstraint(
            '"lastInvestmentRevision" >= 0',
            name="AccountCanonicalState_lastInvestmentRevision_nonnegative",
        ),
        CheckConstraint(
            '"lastInvestmentRevision" <= "lastRevision"',
            name="AccountCanonicalState_investment_not_after_last",
        ),
        CheckConstraint(
            '"holdingRevision" IS NULL OR "holdingRevision" >= 0',
            name="AccountCanonicalState_holdingRevision_nonnegative",
        ),
        CheckConstraint(
            '"holdingRevision" IS NULL OR "holdingRevision" <= "lastInvestmentRevision"',
            name="AccountCanonicalState_holding_not_after_investment",
        ),
        {"schema": "public"},
    )

    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_revision: Mapped[int] = mapped_column(
        "lastRevision", BigInteger, nullable=False, server_default=text("0")
    )
    last_investment_revision: Mapped[int] = mapped_column(
        "lastInvestmentRevision", BigInteger, nullable=False, server_default=text("0")
    )
    holding_revision: Mapped[int | None] = mapped_column("holdingRevision", BigInteger)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class AccountCanonicalChangeModel(Base):
    __tablename__ = "AccountCanonicalChange"
    __table_args__ = (
        UniqueConstraint("kind", "entityId"),
        UniqueConstraint(
            "accountId",
            "revision",
            "kind",
            "entityId",
            "financialTimestamp",
            name="AccountCanonicalChange_exact_identity_key",
        ),
        CheckConstraint(
            '"revision" > 0',
            name="AccountCanonicalChange_revision_positive",
        ),
        CheckConstraint(
            "\"kind\" IN ('transaction', 'investment_event', 'liability_balance')",
            name="AccountCanonicalChange_kind_supported",
        ),
        Index(
            "AccountCanonicalChange_account_financial_revision_idx",
            "accountId",
            "financialTimestamp",
            "revision",
        ),
        {"schema": "public"},
    )

    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="CASCADE"),
        primary_key=True,
    )
    revision: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column("entityId", Text, nullable=False)
    financial_timestamp: Mapped[datetime] = mapped_column(
        "financialTimestamp", TIMESTAMP, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column("createdAt", TIMESTAMP, nullable=False)


class AccountSnapshotCanonicalBoundaryModel(Base):
    __tablename__ = "AccountSnapshotCanonicalBoundary"
    __table_args__ = (
        CheckConstraint(
            '"canonicalRevision" >= 0',
            name="AccountSnapshotCanonicalBoundary_canonical_nonnegative",
        ),
        CheckConstraint(
            '"investmentRevision" IS NULL OR "investmentRevision" >= 0',
            name="AccountSnapshotCanonicalBoundary_investment_nonnegative",
        ),
        CheckConstraint(
            '"holdingRevision" IS NULL OR "holdingRevision" >= 0',
            name="AccountSnapshotCanonicalBoundary_holding_nonnegative",
        ),
        CheckConstraint(
            '(("investmentRevision" IS NULL) = ("holdingRevision" IS NULL))',
            name="AccountSnapshotCanonicalBoundary_investment_holding_pair",
        ),
        CheckConstraint(
            '"investmentRevision" IS NULL OR "investmentRevision" = "holdingRevision"',
            name="AccountSnapshotCanonicalBoundary_holding_fresh",
        ),
        CheckConstraint(
            '"investmentRevision" IS NULL OR "investmentRevision" <= "canonicalRevision"',
            name="AccountSnapshotCanonicalBoundary_investment_not_after_canonical",
        ),
        Index(
            "AccountSnapshotBoundary_account_canonicalRevision_idx",
            "accountId",
            "canonicalRevision",
        ),
        {"schema": "public"},
    )

    snapshot_id: Mapped[str] = mapped_column(
        "snapshotId",
        ForeignKey("public.AccountSnapshot.id", ondelete="CASCADE"),
        primary_key=True,
    )
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="CASCADE"),
        nullable=False,
    )
    canonical_revision: Mapped[int] = mapped_column("canonicalRevision", BigInteger, nullable=False)
    investment_revision: Mapped[int | None] = mapped_column("investmentRevision", BigInteger)
    holding_revision: Mapped[int | None] = mapped_column("holdingRevision", BigInteger)
    selected_liability_balance_id: Mapped[str | None] = mapped_column(
        "selectedLiabilityBalanceId",
        ForeignKey(
            "public.LiabilityBalance.id",
            name="AccountSnapshotBoundary_liabilityBalanceId_fkey",
            ondelete="RESTRICT",
        ),
    )
    created_at: Mapped[datetime] = mapped_column("createdAt", TIMESTAMP, nullable=False)


class DailySnapshotBaselineModel(Base):
    __tablename__ = "DailySnapshotBaseline"
    __table_args__ = (
        UniqueConstraint("netWorthSnapshotId"),
        UniqueConstraint(
            "id",
            "generationId",
            "userId",
            name="DailySnapshotBaseline_id_generation_user_key",
        ),
        UniqueConstraint(
            "id",
            "generationId",
            "userId",
            "netWorthSnapshotId",
            name="DailySnapshotBaseline_exact_point_key",
        ),
        UniqueConstraint(
            "id",
            "generationId",
            name="DailySnapshotBaseline_id_generation_key",
        ),
        UniqueConstraint(
            "backgroundJobId",
            "userId",
            name="DailySnapshotBaseline_backgroundJob_user_key",
        ),
        ForeignKeyConstraint(
            ("backgroundJobId", "userId"),
            (
                "public.ImportJobPublicationTarget.jobId",
                "public.ImportJobPublicationTarget.userId",
            ),
            name="DailySnapshotBaseline_backgroundJob_user_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("netWorthSnapshotId", "generationId", "userId"),
            (
                "public.NetWorthSnapshot.id",
                "public.NetWorthSnapshot.generationId",
                "public.NetWorthSnapshot.userId",
            ),
            name="DailySnapshotBaseline_netWorthSnapshot_generation_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("generationId", "userId"),
            (
                "public.SnapshotGenerationTarget.generationId",
                "public.SnapshotGenerationTarget.userId",
            ),
            name="DailySnapshotBaseline_generation_target_fkey",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "userId",
            "timestamp",
            "currency",
            "calculationVersion",
            "generationId",
            name="DailyBaseline_user_timestamp_currency_generation_version_key",
        ),
        CheckConstraint(
            '(("granularity" = \'day\'::"SnapshotGranularity" '
            'AND "backgroundJobId" IS NULL) OR '
            '("granularity" = \'minute\'::"SnapshotGranularity" AND '
            '(("source" = \'import_event\'::"SnapshotSource" '
            'AND "backgroundJobId" IS NOT NULL) OR '
            '("source" = \'manual_recalculation\'::"SnapshotSource" '
            'AND "backgroundJobId" IS NULL) OR '
            '("source" IN (\'price_refresh\'::"SnapshotSource", '
            "'scheduled'::\"SnapshotSource\", 'holdings_recalculation'::\"SnapshotSource\") "
            'AND "backgroundJobId" IS NULL))))',
            name="DailySnapshotBaseline_day_or_import_anchor",
        ),
        CheckConstraint(
            '"calculationVersion" > 0',
            name="DailySnapshotBaseline_calculationVersion_positive",
        ),
        Index(None, "userId", "timestamp"),
        Index(None, "generationId", "userId", "timestamp"),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "userId", ForeignKey("public.User.id", ondelete="CASCADE"), nullable=False
    )
    net_worth_snapshot_id: Mapped[str] = mapped_column(
        "netWorthSnapshotId",
        ForeignKey("public.NetWorthSnapshot.id", ondelete="CASCADE"),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    granularity: Mapped[SnapshotGranularity] = mapped_column(
        SNAPSHOT_GRANULARITY_DB, nullable=False
    )
    currency: Mapped[str] = mapped_column(Text, nullable=False)
    calculation_version: Mapped[int] = mapped_column("calculationVersion", Integer, nullable=False)
    source: Mapped[SnapshotSource] = mapped_column(SNAPSHOT_SOURCE_DB, nullable=False)
    created_at: Mapped[datetime] = mapped_column("createdAt", TIMESTAMP, nullable=False)
    background_job_id: Mapped[str | None] = mapped_column(
        "backgroundJobId",
        Text,
    )
    generation_id: Mapped[str] = mapped_column(
        "generationId",
        ForeignKey("public.SnapshotGeneration.id", ondelete="RESTRICT"),
        nullable=False,
    )


class UserReadModelPublicationModel(Base):
    """The atomically published, non-financial version of a user's read models."""

    __tablename__ = "UserReadModelPublication"
    __table_args__ = (
        ForeignKeyConstraint(
            ("baselineId",),
            ("public.DailySnapshotBaseline.id",),
            name="UserReadModelPublication_baselineId_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("baselineId", "generationId", "userId"),
            (
                "public.DailySnapshotBaseline.id",
                "public.DailySnapshotBaseline.generationId",
                "public.DailySnapshotBaseline.userId",
            ),
            name="UserReadModelPublication_baseline_generation_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("generationId",),
            ("public.SnapshotGeneration.id",),
            name="UserReadModelPublication_generationId_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("generationId", "generationState"),
            ("public.SnapshotGeneration.id", "public.SnapshotGeneration.state"),
            name="UserReadModelPublication_generation_published_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("seriesHeadId", "userId"),
            ("public.SnapshotSeriesHead.id", "public.SnapshotSeriesHead.userId"),
            name="UserReadModelPublication_series_head_user_fkey",
            ondelete="RESTRICT",
        ),
        CheckConstraint("\"version\" <> ''", name="UserReadModelPublication_version_nonempty"),
        CheckConstraint(
            "\"generationState\" = 'published'",
            name="UserReadModelPublication_generation_published",
        ),
        {"schema": "public"},
    )

    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("public.User.id", ondelete="CASCADE"),
        primary_key=True,
    )
    version: Mapped[str] = mapped_column(Text, nullable=False)
    baseline_id: Mapped[str] = mapped_column("baselineId", Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime] = mapped_column("publishedAt", TIMESTAMP, nullable=False)
    generation_id: Mapped[str] = mapped_column("generationId", Text, nullable=False)
    generation_state: Mapped[str] = mapped_column(
        "generationState",
        Text,
        nullable=False,
        server_default=text("'published'::text"),
    )
    series_head_id: Mapped[str] = mapped_column("seriesHeadId", Text, nullable=False)


class UserReadModelPublicationWatermarkModel(Base):
    """Durable causal barrier shared by publication and empty-scope retirement."""

    __tablename__ = "UserReadModelPublicationWatermark"
    __table_args__ = (
        CheckConstraint(
            "\"kind\" IN ('published', 'retired')",
            name="UserReadModelPublicationWatermark_kind_known",
        ),
        CheckConstraint(
            '("kind" = \'published\' AND "generationId" IS NOT NULL) OR '
            '("kind" = \'retired\' AND "generationId" IS NULL)',
            name="UserReadModelPublicationWatermark_generation_matches_kind",
        ),
        {"schema": "public"},
    )

    user_id: Mapped[str] = mapped_column(
        "userId",
        ForeignKey("public.User.id", onupdate="NO ACTION", ondelete="CASCADE"),
        primary_key=True,
    )
    causal_at: Mapped[datetime] = mapped_column("causalAt", TIMESTAMP, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    generation_id: Mapped[str | None] = mapped_column("generationId", Text)
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class DailySnapshotBaselineAccountModel(Base):
    __tablename__ = "DailySnapshotBaselineAccount"
    __table_args__ = (
        UniqueConstraint("baselineId", "primarySnapshotId"),
        UniqueConstraint(
            "baselineId",
            "presentationSnapshotId",
            name="DailyBaselineAccount_baseline_presentationSnapshot_key",
        ),
        ForeignKeyConstraint(
            ("baselineId", "generationId"),
            ("public.DailySnapshotBaseline.id", "public.DailySnapshotBaseline.generationId"),
            name="DailyBaselineAccount_baseline_generation_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ("primarySnapshotId", "generationId", "accountId"),
            (
                "public.AccountSnapshot.id",
                "public.AccountSnapshot.generationId",
                "public.AccountSnapshot.accountId",
            ),
            name="DailyBaselineAccount_primarySnapshot_generation_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("presentationSnapshotId", "generationId", "accountId"),
            (
                "public.AccountSnapshot.id",
                "public.AccountSnapshot.generationId",
                "public.AccountSnapshot.accountId",
            ),
            name="DailyBaselineAccount_presentationSnapshot_generation_fkey",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            '"canonicalRevision" >= 0',
            name="DailySnapshotBaselineAccount_canonical_nonnegative",
        ),
        CheckConstraint(
            '"investmentRevision" IS NULL OR "investmentRevision" >= 0',
            name="DailySnapshotBaselineAccount_investment_nonnegative",
        ),
        CheckConstraint(
            '"holdingRevision" IS NULL OR "holdingRevision" >= 0',
            name="DailySnapshotBaselineAccount_holding_nonnegative",
        ),
        CheckConstraint(
            '(("investmentRevision" IS NULL) = ("holdingRevision" IS NULL))',
            name="DailySnapshotBaselineAccount_investment_holding_pair",
        ),
        CheckConstraint(
            '"investmentRevision" IS NULL OR "investmentRevision" = "holdingRevision"',
            name="DailySnapshotBaselineAccount_holding_fresh",
        ),
        Index(None, "accountId", "baselineId"),
        {"schema": "public"},
    )

    baseline_id: Mapped[str] = mapped_column(
        "baselineId",
        ForeignKey("public.DailySnapshotBaseline.id", ondelete="CASCADE"),
        primary_key=True,
    )
    account_id: Mapped[str] = mapped_column(
        "accountId",
        ForeignKey("public.Account.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    account_type: Mapped[AccountType] = mapped_column(
        "accountType", ACCOUNT_TYPE_DB, nullable=False
    )
    account_currency: Mapped[str] = mapped_column("accountCurrency", Text, nullable=False)
    primary_snapshot_id: Mapped[str] = mapped_column(
        "primarySnapshotId",
        ForeignKey("public.AccountSnapshot.id", ondelete="RESTRICT"),
        nullable=False,
    )
    presentation_snapshot_id: Mapped[str] = mapped_column(
        "presentationSnapshotId",
        ForeignKey("public.AccountSnapshot.id", ondelete="RESTRICT"),
        nullable=False,
    )
    canonical_revision: Mapped[int] = mapped_column("canonicalRevision", BigInteger, nullable=False)
    investment_revision: Mapped[int | None] = mapped_column("investmentRevision", BigInteger)
    holding_revision: Mapped[int | None] = mapped_column("holdingRevision", BigInteger)
    selected_liability_balance_id: Mapped[str | None] = mapped_column(
        "selectedLiabilityBalanceId",
        ForeignKey("public.LiabilityBalance.id", ondelete="RESTRICT"),
    )
    generation_id: Mapped[str] = mapped_column("generationId", Text, nullable=False)
