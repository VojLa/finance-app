from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import ImportRowStatus, ImportSource, ImportStatus
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.modules.imports.classification import classify_import_row
from app.modules.imports.posting_service import (
    ImportBatchPostingService,
    ImportBatchPostRowsMissingError,
    ImportBatchPostStateError,
    PostImportBatchCommand,
)
from app.modules.imports.service import ImportBatchNotFoundError


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="user", email="user@example.com", name="User")


def _command() -> PostImportBatchCommand:
    return PostImportBatchCommand(
        principal=_principal(),
        account_id="account",
        batch_id="batch",
    )


def _batch(
    *,
    status: ImportStatus = ImportStatus.processing,
    total: int = 1,
    imported: int = 0,
    skipped: int = 0,
    completed_at: datetime | None = None,
) -> ImportBatchModel:
    return cast(
        ImportBatchModel,
        SimpleNamespace(
            id="batch",
            user_id="user",
            account_id="account",
            source=ImportSource.manual,
            filename="manual.csv",
            file_size=1,
            file_encoding="utf-8",
            checksum="a" * 64,
            status=status,
            rows_total=total,
            rows_imported=imported,
            rows_skipped=skipped,
            created_at=datetime(2026, 7, 25, 10),
            completed_at=completed_at,
            retain_until=None,
            raw_data_purged_at=None,
        ),
    )


def _pending(row_id: str = "row", row_number: int = 2) -> ImportRowModel:
    canonical: dict[str, Any] = {
        "schema_version": 1,
        "source": "manual",
        "date": "2026-07-25",
        "amount": "10",
        "currency": "EUR",
        "type": "income",
        "external_id": row_id,
    }
    intent = classify_import_row(source=ImportSource.manual, normalized_data=canonical).model_dump(
        mode="json"
    )
    return cast(
        ImportRowModel,
        SimpleNamespace(
            id=row_id,
            import_batch_id="batch",
            row_number=row_number,
            raw_data={"preserved": True},
            normalized_data={
                **deepcopy(canonical),
                "deduplication": {"schema_version": 1, "status": "unique"},
                "posting_intent": intent,
            },
            validation_errors=None,
            deduplication_key=f"key-{row_id}",
            status=ImportRowStatus.pending,
            error_message=None,
            created_transaction_id=None,
            created_investment_event_id=None,
            created_at=datetime(2026, 7, 25, 10),
        ),
    )


def _duplicate(row_id: str = "duplicate") -> ImportRowModel:
    return cast(
        ImportRowModel,
        SimpleNamespace(
            id=row_id,
            import_batch_id="batch",
            row_number=3,
            raw_data={"preserved": True},
            normalized_data={
                "schema_version": 1,
                "source": "manual",
                "deduplication": {"schema_version": 1, "status": "duplicate"},
            },
            validation_errors=None,
            deduplication_key="duplicate-key",
            status=ImportRowStatus.duplicate,
            error_message="Duplicate normalized import row.",
            created_transaction_id=None,
            created_investment_event_id=None,
            created_at=datetime(2026, 7, 25, 10),
        ),
    )


def _session() -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.flush = AsyncMock()
    session.add = MagicMock()
    return session


def _service(session: MagicMock, batch: ImportBatchModel | None, rows: list[ImportRowModel]):
    service = ImportBatchPostingService(cast(AsyncSession, session))
    repository = cast(Any, service.repository)
    repository.get_for_account = AsyncMock(return_value=batch)
    repository.lock_deduplication_scope = AsyncMock()
    repository.list_rows_for_update = AsyncMock(return_value=rows)
    return service


def _run(value: Any) -> Any:
    return asyncio.run(value)


def test_success_posts_rows_in_locked_order_and_finalizes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.imports.posting_service as posting

    session = _session()
    batch = _batch(total=3, skipped=1)
    first, second, duplicate = _pending("first", 2), _pending("second", 3), _duplicate()
    calls: list[str] = []

    class _Writer:
        def __init__(self, _: object) -> None:
            pass

        async def post_row(self, *, account_id: str, batch: object, row: ImportRowModel):
            assert account_id == "account"
            calls.append(row.id)
            row.status = ImportRowStatus.imported
            row.created_transaction_id = f"transaction-{row.id}"
            return object()

    access = AsyncMock()
    monkeypatch.setattr(posting, "require_account_access", access)
    monkeypatch.setattr(posting, "ImportTransactionPostingWriter", _Writer)
    service = _service(session, batch, [first, second, duplicate])

    result = _run(service.post_batch(_command()))

    assert calls == ["first", "second"]
    assert result.status is ImportStatus.completed
    assert (result.rows_total, result.rows_imported, result.rows_skipped) == (3, 2, 1)
    assert result.completed_at is batch.completed_at and result.replayed is False
    assert session.flush.await_count == 1 and session.commit.await_count == 1
    session.rollback.assert_not_awaited()
    assert service.repository.get_for_account.await_args.kwargs["for_update"] is True
    service.repository.lock_deduplication_scope.assert_awaited_once()
    service.repository.list_rows_for_update.assert_awaited_once_with("batch")
    assert batch.status is ImportStatus.completed


def test_completed_replay_preserves_counters_timestamp_and_uses_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.imports.posting_service as posting

    completed_at = datetime(2026, 7, 25, 12)
    batch = _batch(
        status=ImportStatus.completed,
        imported=1,
        completed_at=completed_at,
    )
    row = _pending()
    row.status = ImportRowStatus.imported
    row.created_transaction_id = "transaction"
    session = _session()
    writer = AsyncMock()

    class _Writer:
        def __init__(self, _: object) -> None:
            pass

        post_row = writer

    monkeypatch.setattr(posting, "require_account_access", AsyncMock())
    monkeypatch.setattr(posting, "ImportTransactionPostingWriter", _Writer)
    service = _service(session, batch, [row])

    result = _run(service.post_batch(_command()))

    assert result.replayed is True and result.completed_at == completed_at
    assert batch.completed_at == completed_at
    assert (batch.rows_total, batch.rows_imported, batch.rows_skipped) == (1, 1, 0)
    writer.assert_awaited_once()
    session.flush.assert_not_awaited()
    session.commit.assert_awaited_once()


@pytest.mark.parametrize(
    ("batch", "rows", "error"),
    [
        (None, [], ImportBatchNotFoundError),
        (_batch(total=0), [], ImportBatchPostRowsMissingError),
        (_batch(status=ImportStatus.pending), [_pending()], ImportBatchPostStateError),
        (_batch(status=ImportStatus.failed), [_pending()], ImportBatchPostStateError),
        (_batch(status=ImportStatus.cancelled), [_pending()], ImportBatchPostStateError),
        (_batch(total=0), [_pending()], ImportBatchPostStateError),
        (_batch(total=2), [_pending()], ImportBatchPostStateError),
        (_batch(completed_at=datetime(2026, 7, 25)), [_pending()], ImportBatchPostStateError),
    ],
)
def test_invalid_batch_boundaries_roll_back(
    monkeypatch: pytest.MonkeyPatch,
    batch: ImportBatchModel | None,
    rows: list[ImportRowModel],
    error: type[Exception],
) -> None:
    import app.modules.imports.posting_service as posting

    monkeypatch.setattr(posting, "require_account_access", AsyncMock())
    session = _session()
    service = _service(session, batch, rows)

    with pytest.raises(error):
        _run(service.post_batch(_command()))

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
    session.add.assert_not_called()


def test_later_preflight_error_prevents_earlier_writer_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.imports.posting_service as posting

    first, corrupt = _pending("first"), _pending("corrupt")
    corrupt.normalized_data = None
    session = _session()
    writer = AsyncMock()

    class _Writer:
        def __init__(self, _: object) -> None:
            pass

        post_row = writer

    monkeypatch.setattr(posting, "require_account_access", AsyncMock())
    monkeypatch.setattr(posting, "ImportTransactionPostingWriter", _Writer)
    service = _service(session, _batch(total=2), [first, corrupt])

    with pytest.raises(ImportBatchPostStateError):
        _run(service.post_batch(_command()))

    writer.assert_not_awaited()
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


def test_commit_failure_rolls_back_all_service_mutations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.imports.posting_service as posting

    session = _session()
    session.commit.side_effect = RuntimeError("controlled commit failure")
    batch, row = _batch(), _pending()
    before = (batch.status, batch.rows_imported, batch.rows_skipped, batch.completed_at)

    class _Writer:
        def __init__(self, _: object) -> None:
            pass

        async def post_row(self, *, account_id: str, batch: object, row: ImportRowModel):
            row.status = ImportRowStatus.imported
            row.created_transaction_id = "transaction"
            return object()

    monkeypatch.setattr(posting, "require_account_access", AsyncMock())
    monkeypatch.setattr(posting, "ImportTransactionPostingWriter", _Writer)
    service = _service(session, batch, [row])

    with pytest.raises(RuntimeError, match="controlled"):
        _run(service.post_batch(_command()))

    session.rollback.assert_awaited_once()
    assert before != (batch.status, batch.rows_imported, batch.rows_skipped, batch.completed_at)


def test_access_boundary_receives_write_roles_before_batch_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.modules.imports.posting_service as posting

    access = AsyncMock(side_effect=RuntimeError("denied"))
    monkeypatch.setattr(posting, "require_account_access", access)
    session = _session()
    service = _service(session, _batch(), [_pending()])

    with pytest.raises(RuntimeError, match="denied"):
        _run(service.post_batch(_command()))

    access.assert_awaited_once()
    assert access.await_args is not None
    assert {role.value for role in access.await_args.kwargs["allowed_roles"]} == {
        "owner",
        "admin",
        "editor",
    }
    service.repository.get_for_account.assert_not_awaited()
