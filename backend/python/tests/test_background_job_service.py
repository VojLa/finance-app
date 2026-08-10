from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import BackgroundJobStatus, ImportStatus
from app.modules.jobs.models import canonical_import_job_idempotency_key
from app.modules.jobs.repository import EnqueuedBackgroundJob
from app.modules.jobs.service import (
    BackgroundJobEnqueueStateError,
    BackgroundJobService,
    EnqueueImportJobCommand,
)

PRINCIPAL = AuthenticatedPrincipal(user_id="user-1", email="user@example.test")


def _batch(batch_id: str, *, user_id: str = "user-1", status: ImportStatus = ImportStatus.pending):
    return SimpleNamespace(
        id=batch_id,
        user_id=user_id,
        account_id="account-1",
        status=status,
        completed_at=None,
    )


def _job(payload: dict[str, object]):
    return SimpleNamespace(
        id="job-1",
        user_id="user-1",
        account_id="account-1",
        status=BackgroundJobStatus.queued,
        payload=payload,
        created_at=datetime(2030, 1, 1),
    )


@pytest.mark.asyncio
async def test_enqueue_authorizes_and_persists_one_canonical_job(monkeypatch) -> None:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    authorize = AsyncMock()
    monkeypatch.setattr("app.modules.jobs.service.require_account_access", authorize)
    batches = MagicMock()
    batches.get_for_account = AsyncMock(side_effect=[_batch("batch-a"), _batch("batch-b")])
    repository = MagicMock()
    payload = {"schema_version": 1, "batch_ids": ["batch-a", "batch-b"]}
    repository.enqueue_import_job = AsyncMock(
        return_value=EnqueuedBackgroundJob(job=_job(payload), created=True)
    )

    result = await BackgroundJobService(
        session,
        repository=repository,
        batch_repository=batches,
    ).enqueue_import_job(
        EnqueueImportJobCommand(
            principal=PRINCIPAL,
            account_id="account-1",
            batch_ids=("batch-a", "batch-b"),
        )
    )

    assert result.created is True
    authorize.assert_awaited_once()
    assert repository.enqueue_import_job.await_args.kwargs["idempotency_key"] == (
        canonical_import_job_idempotency_key(
            user_id="user-1",
            account_id="account-1",
            batch_ids=("batch-a", "batch-b"),
        )
    )
    assert repository.enqueue_import_job.await_args.kwargs["max_attempts"] == 5
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_enqueue_replays_repository_canonical_job(monkeypatch) -> None:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    monkeypatch.setattr("app.modules.jobs.service.require_account_access", AsyncMock())
    batches = MagicMock()
    batches.get_for_account = AsyncMock(return_value=_batch("batch-a"))
    payload = {"schema_version": 1, "batch_ids": ["batch-a"]}
    canonical = _job(payload)
    repository = MagicMock()
    repository.enqueue_import_job = AsyncMock(
        return_value=EnqueuedBackgroundJob(job=canonical, created=False)
    )

    result = await BackgroundJobService(
        session,
        repository=repository,
        batch_repository=batches,
    ).enqueue_import_job(
        EnqueueImportJobCommand(
            principal=PRINCIPAL,
            account_id="account-1",
            batch_ids=("batch-a",),
        )
    )

    assert result.job is canonical
    assert result.created is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("batch", "batch_ids"),
    [
        (_batch("batch-a", user_id="other"), ("batch-a",)),
        (_batch("batch-a", status=ImportStatus.completed), ("batch-a",)),
        (_batch("batch-a"), ("batch-b", "batch-a")),
    ],
)
async def test_enqueue_fails_closed_on_foreign_terminal_or_noncanonical_batches(
    monkeypatch,
    batch,
    batch_ids,
) -> None:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    monkeypatch.setattr("app.modules.jobs.service.require_account_access", AsyncMock())
    batches = MagicMock()
    batches.get_for_account = AsyncMock(return_value=batch)
    repository = MagicMock()

    with pytest.raises(BackgroundJobEnqueueStateError):
        await BackgroundJobService(
            session,
            repository=repository,
            batch_repository=batches,
        ).enqueue_import_job(
            EnqueueImportJobCommand(
                principal=PRINCIPAL,
                account_id="account-1",
                batch_ids=batch_ids,
            )
        )
    repository.enqueue_import_job.assert_not_called()
