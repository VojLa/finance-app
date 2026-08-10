"""Pure SQL expressions for reading only published import projections."""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, and_, exists, or_, select

from app.db.models.background_jobs import BackgroundJobModel
from app.db.models.canonical_lineage import DailySnapshotBaselineModel
from app.db.models.enums import BackgroundJobStatus, SnapshotGranularity, SnapshotSource
from app.db.models.publication_targets import ImportJobPublicationTargetModel


def is_history_snapshot_visible(
    *,
    snapshot_id: Any,
    user_id: Any,
    timestamp: Any,
    source: Any,
) -> ColumnElement[bool]:
    """Return a correlated proof that a snapshot is safe for public history."""

    published_import_snapshot = exists(
        select(1)
        .select_from(DailySnapshotBaselineModel)
        .join(
            ImportJobPublicationTargetModel,
            and_(
                ImportJobPublicationTargetModel.job_id
                == DailySnapshotBaselineModel.background_job_id,
                ImportJobPublicationTargetModel.user_id == DailySnapshotBaselineModel.user_id,
            ),
        )
        .join(
            BackgroundJobModel,
            BackgroundJobModel.id == ImportJobPublicationTargetModel.job_id,
        )
        .where(
            DailySnapshotBaselineModel.net_worth_snapshot_id == snapshot_id,
            DailySnapshotBaselineModel.user_id == user_id,
            DailySnapshotBaselineModel.timestamp == timestamp,
            DailySnapshotBaselineModel.granularity == SnapshotGranularity.minute,
            DailySnapshotBaselineModel.source == SnapshotSource.import_event,
            ImportJobPublicationTargetModel.bucket == DailySnapshotBaselineModel.timestamp,
            ImportJobPublicationTargetModel.published_at.is_not(None),
            BackgroundJobModel.status == BackgroundJobStatus.completed,
        )
    )
    return or_(source != SnapshotSource.import_event, published_import_snapshot)
