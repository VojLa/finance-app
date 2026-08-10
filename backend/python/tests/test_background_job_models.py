from datetime import datetime

import pytest
from pydantic import ValidationError

from app.modules.jobs.models import (
    ImportJobCheckpoint,
    ImportJobPayload,
    ImportJobPhase,
    ImportJobProgress,
    ImportJobResult,
    canonical_import_job_idempotency_key,
)


def test_import_job_payload_requires_sorted_unique_bounded_identifiers() -> None:
    assert ImportJobPayload(batch_ids=("batch-a", "batch-b")).model_dump(mode="json") == {
        "schema_version": 1,
        "batch_ids": ["batch-a", "batch-b"],
    }
    for invalid in ((), ("batch-b", "batch-a"), ("batch-a", "batch-a"), (" ",)):
        with pytest.raises(ValidationError):
            ImportJobPayload(batch_ids=invalid)


def test_import_job_idempotency_key_is_order_independent_and_scope_bound() -> None:
    first = canonical_import_job_idempotency_key(
        user_id="user-1",
        account_id="account-1",
        batch_ids=("batch-b", "batch-a"),
    )
    replay = canonical_import_job_idempotency_key(
        user_id="user-1",
        account_id="account-1",
        batch_ids=("batch-a", "batch-b"),
    )
    assert first == replay
    assert len(first) == 64
    assert first != canonical_import_job_idempotency_key(
        user_id="user-2",
        account_id="account-1",
        batch_ids=("batch-a", "batch-b"),
    )
    assert first != canonical_import_job_idempotency_key(
        user_id="user-1",
        account_id="account-2",
        batch_ids=("batch-a", "batch-b"),
    )


def test_import_job_idempotency_key_rejects_duplicate_or_empty_batches() -> None:
    with pytest.raises(ValueError):
        canonical_import_job_idempotency_key(
            user_id="user-1",
            account_id="account-1",
            batch_ids=("batch-a", "batch-a"),
        )
    with pytest.raises(ValidationError):
        canonical_import_job_idempotency_key(
            user_id="user-1",
            account_id="account-1",
            batch_ids=(),
        )


def test_checkpoint_and_progress_reject_inconsistent_or_unbounded_state() -> None:
    assert ImportJobCheckpoint().phase is ImportJobPhase.queued
    progress = ImportJobProgress(
        phase=ImportJobPhase.posting,
        completed_units=4,
        total_units=8,
        completed_batches=1,
        total_batches=2,
    )
    assert progress.completed_units == 4
    with pytest.raises(ValidationError):
        ImportJobProgress(
            phase=ImportJobPhase.posting,
            completed_units=9,
            total_units=8,
            completed_batches=1,
            total_batches=2,
        )
    with pytest.raises(ValidationError):
        ImportJobCheckpoint(completed_batch_ids=("batch-b", "batch-a"))


def test_completed_result_is_exact_and_never_reports_unavailable_snapshot() -> None:
    result = ImportJobResult(
        batch_ids=("batch-a",),
        rows_total=10,
        rows_imported=9,
        rows_skipped=1,
        snapshot_refresh_status="created",
        completed_at=datetime(2030, 1, 1),
    )
    assert result.rows_total == 10
    with pytest.raises(ValidationError):
        ImportJobResult(
            batch_ids=("batch-a",),
            rows_total=10,
            rows_imported=9,
            rows_skipped=0,
            snapshot_refresh_status="created",
            completed_at=datetime(2030, 1, 1),
        )
    with pytest.raises(ValidationError):
        ImportJobResult(
            batch_ids=("batch-a",),
            rows_total=10,
            rows_imported=9,
            rows_skipped=1,
            snapshot_refresh_status="unavailable",
            completed_at=datetime(2030, 1, 1),
        )
