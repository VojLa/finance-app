from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.config.settings import Settings
from app.modules.imports.job_executor import (
    ImportExecutionCheckpoint,
    ImportExecutionProgress,
    ImportExecutionResult,
    ImportExecutionStage,
)
from app.modules.imports.models import ImportSnapshotRefreshStatus
from app.modules.imports.multi_file_service import FinalizeImportBatchesResult
from app.modules.jobs import import_executor as durable_import_executor_module
from app.modules.jobs.import_executor import DurableImportJobExecutor
from app.modules.jobs.lifecycle import LeaseIdentity
from app.modules.jobs.models import ImportJobResult
from app.modules.jobs.publication_service import (
    ImportJobPublicationService,
    ImportPublicationTarget,
)
from app.modules.jobs.repository import ClaimedBackgroundJob
from app.modules.jobs.worker import RetryableBackgroundJobError


def _claimed() -> ClaimedBackgroundJob:
    return ClaimedBackgroundJob(
        job=cast(
            Any,
            SimpleNamespace(
                id="job-1",
                user_id="user-1",
                account_id="account-1",
                payload={"schema_version": 1, "batch_ids": ["batch-a", "batch-b"]},
                checkpoint={
                    "schema_version": 1,
                    "phase": "queued",
                    "completed_batch_ids": [],
                },
                progress={
                    "schema_version": 1,
                    "phase": "queued",
                    "completed_units": 0,
                    "total_units": 12,
                    "completed_batches": 0,
                    "total_batches": 2,
                },
            ),
        ),
        lease=LeaseIdentity(job_id="job-1", owner="worker-1", version=3),
    )


class _StageExecutor:
    def __init__(self, status: ImportSnapshotRefreshStatus) -> None:
        self.status = status

    async def execute(
        self,
        job_id,
        user_id,
        account_id,
        payload,
        checkpoint,
        on_checkpoint,
        *,
        on_progress,
        publication_bucket_resolver,
    ):
        assert (job_id, user_id, account_id, checkpoint) == (
            "job-1",
            "user-1",
            "account-1",
            None,
        )
        assert payload.batch_ids == ("batch-a", "batch-b")
        assert await publication_bucket_resolver() == datetime(2030, 1, 1, 12, 0)
        await on_progress(
            ImportExecutionProgress(
                job_id="job-1",
                stage=ImportExecutionStage.parse,
                completed_batches=1,
                total_batches=2,
            )
        )
        await on_checkpoint(
            ImportExecutionCheckpoint(job_id="job-1", stage=ImportExecutionStage.parse)
        )
        return ImportExecutionResult(
            job_id="job-1",
            batch_ids=("batch-a", "batch-b"),
            completed_stage=ImportExecutionStage.finalize,
            finalization=FinalizeImportBatchesResult(
                batch_ids=("batch-a", "batch-b"),
                snapshot_refresh_status=self.status,
            ),
        )


class _SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_args: object) -> None:
        return None


@pytest.mark.asyncio
async def test_adapter_maps_stage_progress_to_fenced_persisted_contract(monkeypatch) -> None:
    monkeypatch.setattr(durable_import_executor_module, "_now", lambda: datetime(2030, 1, 1, 12, 0))
    adapter = DurableImportJobExecutor(cast(Any, object()), Settings(_env_file=None))
    adapter.executor = cast(Any, _StageExecutor(ImportSnapshotRefreshStatus.created))
    expected = ImportJobResult(
        batch_ids=("batch-a", "batch-b"),
        rows_total=3,
        rows_imported=2,
        rows_skipped=1,
        snapshot_refresh_status="created",
        completed_at=datetime(2030, 1, 1),
    )
    adapter._result = AsyncMock(return_value=expected)  # type: ignore[method-assign]
    adapter.session_factory = _SessionContext  # type: ignore[assignment]
    monkeypatch.setattr(
        ImportJobPublicationService,
        "reserve",
        AsyncMock(return_value=(ImportPublicationTarget("user-1", datetime(2030, 1, 1, 12, 0)),)),
    )
    monkeypatch.setattr(
        "app.modules.jobs.import_executor._now",
        lambda: datetime(2030, 1, 1, 12, 0),
    )
    checkpoint = AsyncMock()

    result = await adapter.execute(_claimed(), checkpoint=checkpoint)

    assert result == expected
    assert checkpoint.await_count == 2
    progress_call, completed_call = checkpoint.await_args_list
    assert progress_call.args[0].phase.value == "queued"
    assert progress_call.args[1].phase.value == "parsing"
    assert progress_call.args[1].completed_units == 1
    assert completed_call.args[0].phase.value == "parsing"
    assert completed_call.args[1].completed_units == 2


@pytest.mark.asyncio
async def test_adapter_never_marks_incomplete_snapshot_publication_successful(monkeypatch) -> None:
    monkeypatch.setattr(durable_import_executor_module, "_now", lambda: datetime(2030, 1, 1, 12, 0))
    adapter = DurableImportJobExecutor(cast(Any, object()), Settings(_env_file=None))
    adapter.executor = cast(Any, _StageExecutor(ImportSnapshotRefreshStatus.unavailable))
    adapter._result = AsyncMock()  # type: ignore[method-assign]
    adapter.session_factory = _SessionContext  # type: ignore[assignment]
    monkeypatch.setattr(
        ImportJobPublicationService,
        "reserve",
        AsyncMock(return_value=(ImportPublicationTarget("user-1", datetime(2030, 1, 1, 12, 0)),)),
    )
    monkeypatch.setattr(
        "app.modules.jobs.import_executor._now",
        lambda: datetime(2030, 1, 1, 12, 0),
    )

    with pytest.raises(RetryableBackgroundJobError) as captured:
        await adapter.execute(_claimed(), checkpoint=AsyncMock())

    assert captured.value.code == "snapshot_refresh_incomplete"
    adapter._result.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_only_finalization_keeps_the_exact_publication_target(monkeypatch) -> None:
    """A no-new-row finalizer may complete only through the publication path."""

    now = datetime(2030, 1, 1, 12, 0)
    monkeypatch.setattr(durable_import_executor_module, "_now", lambda: now)
    adapter = DurableImportJobExecutor(cast(Any, object()), Settings(_env_file=None))
    adapter.executor = cast(Any, _StageExecutor(ImportSnapshotRefreshStatus.not_required))
    expected = ImportJobResult(
        batch_ids=("batch-a", "batch-b"),
        rows_total=2,
        rows_imported=0,
        rows_skipped=2,
        snapshot_refresh_status="not_required",
        completed_at=now,
    )
    adapter._result = AsyncMock(return_value=expected)  # type: ignore[method-assign]
    adapter.session_factory = _SessionContext  # type: ignore[assignment]
    reserve = AsyncMock(return_value=(ImportPublicationTarget("user-1", now),))
    monkeypatch.setattr(ImportJobPublicationService, "reserve", reserve)

    assert await adapter.execute(_claimed(), checkpoint=AsyncMock()) == expected
    # One reservation supplies the initiating anchor; the second reconciles
    # the exact member target before completion.
    assert reserve.await_count == 2
