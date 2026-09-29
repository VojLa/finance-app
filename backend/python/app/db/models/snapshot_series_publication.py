"""Versioned metadata for immutable snapshot-series publication."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TIMESTAMP
from app.db.models.enums import SNAPSHOT_GRANULARITY_DB, SnapshotGranularity


class SnapshotSeriesVersionStateModel(Base):
    __tablename__ = "SnapshotSeriesVersionState"
    __table_args__ = (
        CheckConstraint(
            '"lastVersion" >= 0', name="SnapshotSeriesVersionState_lastVersion_nonnegative"
        ),
        {"schema": "public"},
    )

    user_id: Mapped[str] = mapped_column(
        "userId", ForeignKey("public.User.id", ondelete="CASCADE"), primary_key=True
    )
    last_version: Mapped[int] = mapped_column(
        "lastVersion", BigInteger, nullable=False, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column("updatedAt", TIMESTAMP, nullable=False)


class SnapshotSeriesHeadModel(Base):
    __tablename__ = "SnapshotSeriesHead"
    __table_args__ = (
        UniqueConstraint("userId", "version", name="SnapshotSeriesHead_user_version_key"),
        UniqueConstraint("id", "userId", name="SnapshotSeriesHead_id_user_key"),
        ForeignKeyConstraint(
            ("generationId", "userId"),
            (
                "public.SnapshotGenerationTarget.generationId",
                "public.SnapshotGenerationTarget.userId",
            ),
            name="SnapshotSeriesHead_generation_target_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("parentHeadId", "userId"),
            ("public.SnapshotSeriesHead.id", "public.SnapshotSeriesHead.userId"),
            name="SnapshotSeriesHead_parent_user_fkey",
            ondelete="RESTRICT",
        ),
        CheckConstraint('"version" >= 1', name="SnapshotSeriesHead_version_positive"),
        CheckConstraint(
            '"parentHeadId" IS NULL OR "parentHeadId" <> "id"',
            name="SnapshotSeriesHead_parent_distinct",
        ),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "userId", ForeignKey("public.User.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    parent_head_id: Mapped[str | None] = mapped_column("parentHeadId", Text)
    generation_id: Mapped[str] = mapped_column("generationId", Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column("createdAt", TIMESTAMP, nullable=False)


class SnapshotSeriesPointLinkModel(Base):
    __tablename__ = "SnapshotSeriesPointLink"
    __table_args__ = (
        UniqueConstraint(
            "userId",
            "timestamp",
            "granularity",
            "validFromVersion",
            name="SnapshotSeriesPointLink_coordinate_from_key",
        ),
        ForeignKeyConstraint(
            ("userId", "validFromVersion"),
            ("public.SnapshotSeriesHead.userId", "public.SnapshotSeriesHead.version"),
            name="SnapshotSeriesPointLink_from_head_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("baselineId", "generationId", "userId", "netWorthSnapshotId"),
            (
                "public.DailySnapshotBaseline.id",
                "public.DailySnapshotBaseline.generationId",
                "public.DailySnapshotBaseline.userId",
                "public.DailySnapshotBaseline.netWorthSnapshotId",
            ),
            name="SnapshotSeriesPointLink_baseline_exact_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("portfolioSnapshotId", "generationId", "userId"),
            (
                "public.PortfolioSnapshot.id",
                "public.PortfolioSnapshot.generationId",
                "public.PortfolioSnapshot.userId",
            ),
            name="SnapshotSeriesPointLink_portfolio_exact_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("netWorthSnapshotId", "generationId", "userId"),
            (
                "public.NetWorthSnapshot.id",
                "public.NetWorthSnapshot.generationId",
                "public.NetWorthSnapshot.userId",
            ),
            name="SnapshotSeriesPointLink_net_worth_exact_fkey",
            ondelete="RESTRICT",
        ),
        CheckConstraint('"validFromVersion" >= 1', name="SnapshotSeriesPointLink_from_positive"),
        CheckConstraint(
            '"validToVersion" IS NULL OR "validToVersion" > "validFromVersion"',
            name="SnapshotSeriesPointLink_to_after_from",
        ),
        ExcludeConstraint(
            ("userId", "="),
            ("timestamp", "="),
            ("granularity", "="),
            (text('int8range("validFromVersion", "validToVersion", \'[)\')'), "&&"),
            name="SnapshotSeriesPointLink_no_overlap",
            using="gist",
        ),
        Index(
            "SnapshotSeriesPointLink_one_current_coordinate_key",
            "userId",
            "timestamp",
            "granularity",
            unique=True,
            postgresql_where=text('"validToVersion" IS NULL'),
        ),
        Index(
            "SnapshotSeriesPointLink_user_visible_idx",
            "userId",
            "granularity",
            "timestamp",
            "validFromVersion",
            "validToVersion",
        ),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "userId", ForeignKey("public.User.id", ondelete="CASCADE"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    granularity: Mapped[SnapshotGranularity] = mapped_column(
        SNAPSHOT_GRANULARITY_DB, nullable=False
    )
    valid_from_version: Mapped[int] = mapped_column("validFromVersion", BigInteger, nullable=False)
    valid_to_version: Mapped[int | None] = mapped_column("validToVersion", BigInteger)
    generation_id: Mapped[str] = mapped_column("generationId", Text, nullable=False)
    baseline_id: Mapped[str] = mapped_column("baselineId", Text, nullable=False)
    portfolio_snapshot_id: Mapped[str] = mapped_column("portfolioSnapshotId", Text, nullable=False)
    net_worth_snapshot_id: Mapped[str] = mapped_column("netWorthSnapshotId", Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column("createdAt", TIMESTAMP, nullable=False)


class SnapshotSeriesPublicationReceiptModel(Base):
    __tablename__ = "SnapshotSeriesPublicationReceipt"
    __table_args__ = (
        UniqueConstraint("userId", "jobId", name="SnapshotSeriesPublicationReceipt_user_job_key"),
        UniqueConstraint(
            "userId", "generationId", name="SnapshotSeriesPublicationReceipt_user_generation_key"
        ),
        UniqueConstraint("userId", "headId", name="SnapshotSeriesPublicationReceipt_user_head_key"),
        CheckConstraint(
            'char_length("jobId") BETWEEN 1 AND 200',
            name="SnapshotSeriesPublicationReceipt_job_id_bounded",
        ),
        ForeignKeyConstraint(
            ("generationId", "userId"),
            (
                "public.SnapshotGenerationTarget.generationId",
                "public.SnapshotGenerationTarget.userId",
            ),
            name="SnapshotSeriesPublicationReceipt_generation_target_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ("headId", "userId"),
            ("public.SnapshotSeriesHead.id", "public.SnapshotSeriesHead.userId"),
            name="SnapshotSeriesPublicationReceipt_head_user_fkey",
            ondelete="RESTRICT",
        ),
        {"schema": "public"},
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[str] = mapped_column(
        "userId", ForeignKey("public.User.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[str] = mapped_column("jobId", Text, nullable=False)
    generation_id: Mapped[str] = mapped_column("generationId", Text, nullable=False)
    head_id: Mapped[str] = mapped_column("headId", Text, nullable=False)
    committed_at: Mapped[datetime] = mapped_column("committedAt", TIMESTAMP, nullable=False)
