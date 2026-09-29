from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.db.models.background_jobs import BackgroundJobModel
from app.db.models.enums import BackgroundJobKind, BackgroundJobStatus, ImportStatus
from app.db.models.imports import ImportBatchModel
from app.db.models.publication_targets import ImportJobPublicationTargetModel
from app.modules.portfolio_history_rebuild.repository import (
    PortfolioHistoryReplayRepositoryError,
    _completed_import_is_visible,
)

AT = datetime(2026, 8, 25, 12)


def _batch(*, status: ImportStatus = ImportStatus.completed) -> ImportBatchModel:
    return cast(
        Any,
        SimpleNamespace(
            status=status,
            completed_at=AT
            if status in {ImportStatus.completed, ImportStatus.partially_completed}
            else None,
        ),
    )


def _job(*, status: BackgroundJobStatus = BackgroundJobStatus.completed) -> BackgroundJobModel:
    return cast(
        Any,
        SimpleNamespace(
            id="job",
            user_id="importer",
            kind=BackgroundJobKind.import_workflow,
            status=status,
        ),
    )


def _target(
    *, user_id: str = "importer", published: bool = True
) -> ImportJobPublicationTargetModel:
    return cast(
        Any,
        SimpleNamespace(
            job_id="job",
            user_id=user_id,
            published_at=AT if published else None,
        ),
    )


def test_completed_import_uses_original_published_target_not_current_reader_identity() -> None:
    assert _completed_import_is_visible(
        batch=_batch(),
        job=_job(),
        targets=(_target(), _target(user_id="late-member", published=False)),
    )


@pytest.mark.parametrize(
    ("batch", "job", "targets"),
    [
        (_batch(), _job(), (_target(user_id="foreign"),)),
        (_batch(), _job(), (_target(published=False),)),
        (_batch(), _job(status=BackgroundJobStatus.failed), (_target(),)),
        (_batch(status=ImportStatus.failed), _job(status=BackgroundJobStatus.failed), (_target(),)),
    ],
)
def test_non_proven_import_roots_remain_invisible(
    batch: ImportBatchModel,
    job: BackgroundJobModel,
    targets: tuple[ImportJobPublicationTargetModel, ...],
) -> None:
    assert not _completed_import_is_visible(batch=batch, job=job, targets=targets)


def test_published_completed_job_with_failed_batch_is_rejected_as_corrupt() -> None:
    with pytest.raises(PortfolioHistoryReplayRepositoryError):
        _completed_import_is_visible(
            batch=_batch(status=ImportStatus.failed),
            job=_job(),
            targets=(_target(),),
        )
