from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import AccountMemberRole, BackgroundJobStatus, ImportSource, ImportStatus
from app.modules.accounts.access import AccountAccessDeniedError, AccountNotFoundError
from app.modules.jobs.lifecycle import MAX_MANUAL_RETRIES
from app.modules.jobs.models import canonical_import_job_idempotency_key
from app.modules.jobs.repository import (
    BackgroundJobRepository,
    EnqueuedBackgroundJob,
    ManualRetryBackgroundJob,
)
from app.modules.jobs.service import (
    BackgroundJobEnqueueStateError,
    BackgroundJobNotFoundError,
    BackgroundJobRetryStateError,
    BackgroundJobService,
    EnqueueImportJobCommand,
)

PRINCIPAL = AuthenticatedPrincipal(user_id="user-1", email="user@example.test")


def _batch(
    batch_id: str,
    *,
    user_id: str = "user-1",
    status: ImportStatus = ImportStatus.pending,
    source: ImportSource = ImportSource.trading212,
):
    return SimpleNamespace(
        id=batch_id,
        user_id=user_id,
        account_id="account-1",
        status=status,
        source=source,
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


def _retry_job(*, status: BackgroundJobStatus = BackgroundJobStatus.failed, retries: int = 0):
    now = datetime(2030, 1, 1)
    return SimpleNamespace(
        id="job-1",
        user_id="user-1",
        account_id="account-1",
        status=status,
        manual_retry_count=retries,
        attempt_count=3,
        run_after=now,
        result={"private": "old"},
        error_code="failed",
        error_message="failed safely",
        lease_owner="worker-a",
        lease_expires_at=now,
        lease_heartbeat_at=now,
        started_at=now,
        finished_at=now,
        updated_at=now,
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
    repository.get_owned_by_key = AsyncMock(return_value=None)
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
    repository.get_owned_by_key = AsyncMock(return_value=None)
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
    repository.get_owned_by_key = AsyncMock(return_value=None)

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


@pytest.mark.asyncio
async def test_enqueue_replays_running_job_before_revalidating_batch_state(monkeypatch) -> None:
    session = MagicMock(commit=AsyncMock(), rollback=AsyncMock())
    monkeypatch.setattr("app.modules.jobs.service.require_account_access", AsyncMock())
    payload = {"schema_version": 1, "batch_ids": ["batch-a"]}
    canonical = _job(payload)
    canonical.status = BackgroundJobStatus.running
    repository = MagicMock()
    repository.get_owned_by_key = AsyncMock(return_value=canonical)
    batches = MagicMock()
    batches.get_for_account = AsyncMock()

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
    batches.get_for_account.assert_not_awaited()
    repository.enqueue_import_job.assert_not_called()


@pytest.mark.asyncio
async def test_enqueue_rejects_mixed_sources_before_creating_job(monkeypatch) -> None:
    session = MagicMock(commit=AsyncMock(), rollback=AsyncMock())
    monkeypatch.setattr("app.modules.jobs.service.require_account_access", AsyncMock())
    batches = MagicMock()
    batches.get_for_account = AsyncMock(
        side_effect=[
            _batch("batch-a", source=ImportSource.trading212),
            _batch("batch-b", source=ImportSource.anycoin),
        ]
    )
    repository = MagicMock()
    repository.get_owned_by_key = AsyncMock(return_value=None)

    with pytest.raises(BackgroundJobEnqueueStateError):
        await BackgroundJobService(
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

    repository.enqueue_import_job.assert_not_called()


async def test_repository_manual_retry_resets_the_same_failed_job_and_increments_counter(
    monkeypatch,
) -> None:
    session = MagicMock(flush=AsyncMock())
    job = _retry_job()
    repository = BackgroundJobRepository(session)
    monkeypatch.setattr(repository, "get_owned", AsyncMock(return_value=job))
    now = datetime(2030, 1, 2)

    result = await repository.retry_failed(
        user_id="user-1", account_id="account-1", job_id="job-1", now=now
    )

    assert result == ManualRetryBackgroundJob(job=job, retried=True)
    assert job.id == "job-1"
    assert job.status is BackgroundJobStatus.queued
    assert job.attempt_count == 0
    assert job.manual_retry_count == 1
    assert job.result is job.error_code is job.error_message is None
    assert job.lease_owner is job.lease_expires_at is job.lease_heartbeat_at is None
    assert job.started_at is job.finished_at is None
    assert job.run_after == now
    session.flush.assert_awaited_once()


@pytest.mark.parametrize(
    ("status", "retries"),
    [
        (BackgroundJobStatus.queued, 0),
        (BackgroundJobStatus.completed, 0),
        (BackgroundJobStatus.running, 0),
        (BackgroundJobStatus.failed, MAX_MANUAL_RETRIES),
    ],
)
async def test_repository_manual_retry_rejects_nonfailed_or_limited_jobs(
    monkeypatch,
    status: BackgroundJobStatus,
    retries: int,
) -> None:
    session = MagicMock(flush=AsyncMock())
    job = _retry_job(status=status, retries=retries)
    repository = BackgroundJobRepository(session)
    monkeypatch.setattr(repository, "get_owned", AsyncMock(return_value=job))

    result = await repository.retry_failed(
        user_id="user-1",
        account_id="account-1",
        job_id="job-1",
        now=datetime(2030, 1, 2),
    )

    assert result == ManualRetryBackgroundJob(job=job, retried=False)
    session.flush.assert_not_awaited()


@pytest.mark.parametrize(
    "role",
    [AccountMemberRole.owner, AccountMemberRole.admin, AccountMemberRole.editor],
)
async def test_retry_permits_all_write_roles(monkeypatch, role: AccountMemberRole) -> None:
    session = MagicMock(commit=AsyncMock(), rollback=AsyncMock())
    repository = MagicMock()
    job = _retry_job()
    repository.retry_failed = AsyncMock(
        return_value=ManualRetryBackgroundJob(job=job, retried=True)
    )

    async def authorize(**kwargs: object) -> None:
        assert role in kwargs["allowed_roles"]  # type: ignore[operator]

    monkeypatch.setattr("app.modules.jobs.service.require_account_access", authorize)
    monkeypatch.setattr(
        BackgroundJobService, "public_response", staticmethod(lambda _job: object())
    )

    result = await BackgroundJobService(session, repository=repository).retry_import_job(
        principal=PRINCIPAL, account_id="account-1", job_id="job-1"
    )

    assert result is not None
    session.commit.assert_awaited_once()


async def test_retry_denies_viewer(monkeypatch) -> None:
    session = MagicMock(commit=AsyncMock(), rollback=AsyncMock())

    async def deny(**_: object) -> None:
        raise AccountAccessDeniedError()

    monkeypatch.setattr("app.modules.jobs.service.require_account_access", deny)

    with pytest.raises(AccountAccessDeniedError) as raised:
        await BackgroundJobService(session, repository=MagicMock()).retry_import_job(
            principal=PRINCIPAL, account_id="account-1", job_id="job-1"
        )

    assert raised.value.status_code == 403


async def test_get_hides_foreign_account_and_missing_or_foreign_job_identically(
    monkeypatch,
) -> None:
    session = MagicMock()
    repository = MagicMock(get_owned=AsyncMock(return_value=None))

    async def missing_account(**_: object) -> None:
        raise AccountNotFoundError()

    monkeypatch.setattr("app.modules.jobs.service.require_account_access", missing_account)
    with pytest.raises(BackgroundJobNotFoundError) as foreign_account:
        await BackgroundJobService(session, repository=repository).get_import_job(
            principal=PRINCIPAL, account_id="foreign-account", job_id="job-foreign"
        )

    monkeypatch.setattr("app.modules.jobs.service.require_account_access", AsyncMock())
    with pytest.raises(BackgroundJobNotFoundError) as absent_or_foreign_job:
        await BackgroundJobService(session, repository=repository).get_import_job(
            principal=PRINCIPAL, account_id="account-1", job_id="job-foreign"
        )

    assert (
        (
            foreign_account.value.status_code,
            foreign_account.value.code,
            foreign_account.value.message,
        )
        == (
            absent_or_foreign_job.value.status_code,
            absent_or_foreign_job.value.code,
            absent_or_foreign_job.value.message,
        )
        == (404, "background_job_not_found", "The background job was not found.")
    )


@pytest.mark.parametrize(
    ("status", "retries"),
    [
        (BackgroundJobStatus.queued, 0),
        (BackgroundJobStatus.completed, 0),
        (BackgroundJobStatus.running, 0),
        (BackgroundJobStatus.failed, MAX_MANUAL_RETRIES),
    ],
)
async def test_retry_service_returns_409_for_nonretryable_job(
    monkeypatch, status: BackgroundJobStatus, retries: int
) -> None:
    session = MagicMock(commit=AsyncMock(), rollback=AsyncMock())
    monkeypatch.setattr("app.modules.jobs.service.require_account_access", AsyncMock())
    repository = MagicMock(
        retry_failed=AsyncMock(
            return_value=ManualRetryBackgroundJob(
                job=_retry_job(status=status, retries=retries), retried=False
            )
        )
    )

    with pytest.raises(BackgroundJobRetryStateError) as raised:
        await BackgroundJobService(session, repository=repository).retry_import_job(
            principal=PRINCIPAL, account_id="account-1", job_id="job-1"
        )

    assert raised.value.status_code == 409
