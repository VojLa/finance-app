from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models.common import TIMESTAMP


class ImportJobPublicationTargetModel(Base):
    """Durable per-user publication reservation for one import workflow."""

    __tablename__ = "ImportJobPublicationTarget"
    __table_args__ = (
        UniqueConstraint("userId", "bucket", name="ImportJobPublicationTarget_user_bucket_key"),
        CheckConstraint(
            'date_trunc(\'minute\', "bucket") = "bucket"',
            name="ImportJobPublicationTarget_bucket_minute_aligned",
        ),
        Index("ImportJobPublicationTarget_unpublished_idx", "userId", "bucket"),
        {"schema": "public"},
    )

    job_id: Mapped[str] = mapped_column(
        "jobId",
        Text,
        ForeignKey("public.BackgroundJob.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        "userId",
        Text,
        ForeignKey("public.User.id", ondelete="CASCADE"),
        primary_key=True,
    )
    bucket: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column("publishedAt", TIMESTAMP)
