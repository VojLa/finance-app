from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import ImportStatus
from app.modules.imports.job_executor import (
    ImportExecutionCheckpoint,
    ImportExecutionPayload,
    ImportExecutionStage,
    ImportJobExecutionRetryableError,
    ImportJobExecutor,
)
from app.modules.imports.models import (
    ImportClassifyResponse,
    ImportDeduplicateResponse,
    ImportNormalizeResponse,
    ImportParseResponse,
    ImportSnapshotRefreshStatus,
)
from app.modules.imports.multi_file_service import FinalizeImportBatchesResult
from app.modules.imports.posting_service import PostImportBatchResult


@dataclass
class _Session:
    batches: dict[str, object]

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _BatchRepository:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def get_for_account(self, *, account_id: str, batch_id: str) -> object | None:
        batch = self.session.batches.get(batch_id)
        return batch if getattr(batch, "account_id", None) == account_id else None


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="user-a", email="user-a@example.test")


def _batch(batch_id: str, status: ImportStatus = ImportStatus.pending) -> object:
    return SimpleNamespace(id=batch_id, account_id="account-a", user_id="user-a", status=status)


def _executor(
    *,
    batches: dict[str, object],
) -> tuple[ImportJobExecutor, dict[str, Mock], AsyncMock]:
    calls: dict[str, Mock] = {}

    def service(name: str) -> Mock:
        value = Mock()
        method = {
            "parse": "parse_batch",
            "normalize": "normalize_batch",
            "deduplicate": "deduplicate_batch",
            "classify": "classify_batch",
            "post": "post_batch",
        }[name]

        def result_for(*, batch_id: str) -> object:
            if name == "parse":
                return ImportParseResponse(
                    batch_id=batch_id,
                    status=ImportStatus.processing,
                    rows_total=1,
                    rows_pending=1,
                    rows_failed=0,
                )
            if name == "normalize":
                return ImportNormalizeResponse(
                    batch_id=batch_id,
                    status=ImportStatus.processing,
                    rows_total=1,
                    rows_normalized=1,
                    rows_needs_review=0,
                    rows_failed=0,
                )
            if name == "deduplicate":
                return ImportDeduplicateResponse(
                    batch_id=batch_id,
                    status=ImportStatus.processing,
                    rows_total=1,
                    rows_unique=1,
                    rows_duplicate=0,
                    rows_needs_review=0,
                    rows_failed=0,
                )
            if name == "classify":
                return ImportClassifyResponse(
                    batch_id=batch_id,
                    status=ImportStatus.processing,
                    rows_total=1,
                    rows_classified=1,
                    rows_needs_review=0,
                    rows_duplicate=0,
                    rows_skipped=0,
                    rows_failed=0,
                )
            return PostImportBatchResult(
                batch_id=batch_id,
                status=ImportStatus.completed,
                rows_total=1,
                rows_imported=1,
                rows_skipped=0,
                completed_at=datetime(2026, 8, 10, 12),
                replayed=False,
                transaction_rows_imported=1,
                investment_event_rows_imported=0,
            )

        if name == "post":
            setattr(
                value,
                method,
                AsyncMock(side_effect=lambda command: result_for(batch_id=command.batch_id)),
            )
        else:
            setattr(
                value,
                method,
                AsyncMock(side_effect=lambda *, batch_id, **_: result_for(batch_id=batch_id)),
            )
        calls[name] = value
        return value

    parser = service("parse")
    normalization = service("normalize")
    deduplication = service("deduplicate")
    classification = service("classify")
    posting = service("post")
    finalizer = Mock(
        finalize=AsyncMock(
            return_value=FinalizeImportBatchesResult(
                batch_ids=tuple(sorted(batches)),
                snapshot_refresh_status=ImportSnapshotRefreshStatus.created,
            )
        )
    )
    calls["finalize"] = finalizer
    principal_resolver = AsyncMock(return_value=_principal())
    session = _Session(batches)
    executor = ImportJobExecutor(
        lambda: cast(AsyncSession, session),
        principal_resolver=principal_resolver,
        finalization_factory=Mock(return_value=finalizer),
        parser_factory=Mock(return_value=parser),
        normalization_factory=Mock(return_value=normalization),
        deduplication_factory=Mock(return_value=deduplication),
        classification_factory=Mock(return_value=classification),
        posting_factory=Mock(return_value=posting),
        batch_repository_factory=lambda _session: _BatchRepository(session),
    )
    return executor, calls, principal_resolver


@pytest.mark.parametrize("stage", list(ImportExecutionStage)[:-1])
async def test_executor_fails_closed_on_invalid_stage_result(stage: ImportExecutionStage) -> None:
    executor, calls, _ = _executor(batches={"batch-a": _batch("batch-a")})
    method = (
        calls["post"].post_batch
        if stage is ImportExecutionStage.canonical_post
        else getattr(calls[stage.value], f"{stage.value}_batch")
    )
    method.side_effect = None
    method.return_value = object()

    with pytest.raises(RuntimeError, match="invalid"):
        await executor.execute(
            "job-a",
            "user-a",
            "account-a",
            ImportExecutionPayload(("batch-a",)),
            ImportExecutionStage(
                list(ImportExecutionStage)[list(ImportExecutionStage).index(stage) - 1]
            )
            if stage is not ImportExecutionStage.parse
            else None,
            AsyncMock(),
        )


async def test_executor_runs_sorted_multi_file_pipeline_and_finalizes_once() -> None:
    batches = {"batch-a": _batch("batch-a"), "batch-b": _batch("batch-b")}
    executor, calls, principal_resolver = _executor(batches=batches)
    checkpoints: list[ImportExecutionCheckpoint] = []
    progress = AsyncMock()

    async def on_checkpoint(value: ImportExecutionCheckpoint) -> None:
        checkpoints.append(value)

    result = await executor.execute(
        "job-a",
        "user-a",
        "account-a",
        ImportExecutionPayload(("batch-a", "batch-b")),
        None,
        on_checkpoint,
        on_progress=progress,
    )

    assert result.completed_stage is ImportExecutionStage.finalize
    assert [item.stage for item in checkpoints] == list(ImportExecutionStage)
    for name in ("parse", "normalize", "deduplicate", "classify", "post"):
        method = getattr(calls[name], f"{name}_batch", None) or calls[name].post_batch
        assert method.await_count == 2
    calls["finalize"].finalize.assert_awaited_once()
    assert principal_resolver.await_count == 11
    assert progress.await_count == 10


async def test_crash_after_parse_commit_before_checkpoint_replays_parse_then_continues() -> None:
    batches = {"batch-a": _batch("batch-a")}
    executor, calls, _ = _executor(batches=batches)
    checkpoint = AsyncMock(side_effect=RuntimeError("worker crashed after parse"))

    with pytest.raises(RuntimeError, match="worker crashed"):
        await executor.execute(
            "job-a",
            "user-a",
            "account-a",
            ImportExecutionPayload(("batch-a",)),
            None,
            checkpoint,
        )

    assert calls["parse"].parse_batch.await_count == 1
    assert calls["normalize"].normalize_batch.await_count == 0

    completed: list[ImportExecutionCheckpoint] = []

    async def on_checkpoint(value: ImportExecutionCheckpoint) -> None:
        completed.append(value)

    result = await executor.execute(
        "job-a",
        "user-a",
        "account-a",
        ImportExecutionPayload(("batch-a",)),
        None,
        on_checkpoint,
    )

    assert result.finalization.snapshot_refresh_status is ImportSnapshotRefreshStatus.created
    assert calls["parse"].parse_batch.await_count == 2
    assert calls["normalize"].normalize_batch.await_count == 1
    calls["finalize"].finalize.assert_awaited_once()


async def test_terminal_batches_skip_pre_post_stages_but_replay_canonical_post_once() -> None:
    batches = {"batch-a": _batch("batch-a", ImportStatus.completed)}
    executor, calls, _ = _executor(batches=batches)

    await executor.execute(
        "job-a",
        "user-a",
        "account-a",
        ImportExecutionPayload(("batch-a",)),
        None,
        AsyncMock(),
    )

    calls["parse"].parse_batch.assert_not_awaited()
    calls["normalize"].normalize_batch.assert_not_awaited()
    calls["deduplicate"].deduplicate_batch.assert_not_awaited()
    calls["classify"].classify_batch.assert_not_awaited()
    calls["post"].post_batch.assert_awaited_once()
    calls["finalize"].finalize.assert_awaited_once()


async def test_final_checkpoint_replays_only_shared_finalization_after_worker_crash() -> None:
    batches = {"batch-a": _batch("batch-a", ImportStatus.completed)}
    executor, calls, _ = _executor(batches=batches)

    result = await executor.execute(
        "job-a",
        "user-a",
        "account-a",
        ImportExecutionPayload(("batch-a",)),
        ImportExecutionStage.finalize,
        AsyncMock(),
    )

    assert result.completed_stage is ImportExecutionStage.finalize
    for name in ("parse", "normalize", "deduplicate", "classify", "post"):
        method = getattr(calls[name], f"{name}_batch", None) or calls[name].post_batch
        method.assert_not_awaited()
    calls["finalize"].finalize.assert_awaited_once()


async def test_finalization_uses_an_idle_session_separate_from_principal_lookup() -> None:
    sessions: list[_Session] = []
    authorization_sessions: list[_Session] = []

    def session_factory() -> AsyncSession:
        session = _Session({})
        sessions.append(session)
        return cast(AsyncSession, session)

    async def principal_resolver(
        session: AsyncSession,
        user_id: str,
    ) -> AuthenticatedPrincipal:
        assert user_id == "user-a"
        authorization_sessions.append(cast(_Session, session))
        return _principal()

    class _IdleFinalizer:
        def __init__(self, session: AsyncSession) -> None:
            self.session = cast(_Session, session)

        async def finalize(self, command) -> FinalizeImportBatchesResult:
            assert command.account_id == "account-a"
            assert all(self.session is not item for item in authorization_sessions)
            return FinalizeImportBatchesResult(
                batch_ids=("batch-a",),
                snapshot_refresh_status=ImportSnapshotRefreshStatus.created,
            )

    executor = ImportJobExecutor(
        session_factory,
        principal_resolver=principal_resolver,
        finalization_factory=_IdleFinalizer,
    )

    result = await executor.execute(
        "job-a",
        "user-a",
        "account-a",
        ImportExecutionPayload(("batch-a",)),
        ImportExecutionStage.finalize,
        AsyncMock(),
    )

    assert result.finalization.snapshot_refresh_status is ImportSnapshotRefreshStatus.created
    assert len(sessions) == 2


@pytest.mark.parametrize(
    "status",
    [ImportSnapshotRefreshStatus.unavailable, ImportSnapshotRefreshStatus.conflict],
)
async def test_incomplete_finalization_is_retryable(
    status: ImportSnapshotRefreshStatus,
) -> None:
    batches = {"batch-a": _batch("batch-a")}
    executor, calls, _ = _executor(batches=batches)
    calls["finalize"].finalize.return_value = FinalizeImportBatchesResult(
        batch_ids=("batch-a",),
        snapshot_refresh_status=status,
    )

    with pytest.raises(ImportJobExecutionRetryableError) as raised:
        await executor.execute(
            "job-a",
            "user-a",
            "account-a",
            ImportExecutionPayload(("batch-a",)),
            ImportExecutionStage.canonical_post,
            AsyncMock(),
        )

    assert raised.value.status is status


@pytest.mark.parametrize(
    "payload",
    [
        ImportExecutionPayload(()),
        ImportExecutionPayload(("batch-b", "batch-a")),
        ImportExecutionPayload(("batch-a", "batch-a")),
    ],
)
async def test_executor_rejects_invalid_durable_payload_before_service_calls(
    payload: ImportExecutionPayload,
) -> None:
    executor, calls, _ = _executor(batches={"batch-a": _batch("batch-a")})

    with pytest.raises(RuntimeError):
        await executor.execute(
            "job-a",
            "user-a",
            "account-a",
            payload,
            None,
            AsyncMock(),
        )

    calls["parse"].parse_batch.assert_not_awaited()
    calls["finalize"].finalize.assert_not_awaited()
