from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.enums import ImportRowStatus, ImportSource, ImportStatus
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.main import create_app
from app.modules.imports.deduplication import (
    ImportDeduplicateRowsMissingError,
    ImportDeduplicateStateError,
    ImportDeduplicationService,
    _is_valid_row_state,
    _winner_ids,
)


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="user-a", email="a@example.com", name="A")


def _batch(batch_id: str = "batch-a") -> SimpleNamespace:
    return SimpleNamespace(
        id=batch_id,
        source=ImportSource.manual,
        status=ImportStatus.processing,
        rows_total=4,
        rows_imported=0,
        rows_skipped=0,
        completed_at=None,
    )


def _row(
    row_id: str,
    *,
    key: str | None,
    status: ImportRowStatus = ImportRowStatus.pending,
) -> SimpleNamespace:
    normalized = (
        None
        if status in {ImportRowStatus.failed, ImportRowStatus.needs_review}
        else {"schema_version": 1}
    )
    return SimpleNamespace(
        id=row_id,
        status=status,
        normalized_data=normalized,
        deduplication_key=key,
        error_message=None,
    )


async def _allow_access(**_: object) -> None:
    return None


def test_deduplicate_openapi_and_authentication(test_settings: Settings) -> None:
    app = create_app(test_settings)
    operation = app.openapi()["paths"][
        "/api/v1/accounts/{account_id}/imports/{batch_id}/deduplicate"
    ]["post"]
    assert operation["security"] == [{"InternalSessionToken": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ImportDeduplicateResponse"
    }

    with TestClient(app) as client:
        missing = client.post("/api/v1/accounts/account-a/imports/batch-a/deduplicate")
        invalid = client.post(
            "/api/v1/accounts/account-a/imports/batch-a/deduplicate",
            headers={"Authorization": "Bearer invalid"},
        )

    assert (missing.status_code, missing.json()["error"]["code"]) == (
        401,
        "authentication_required",
    )
    assert (invalid.status_code, invalid.json()["error"]["code"]) == (
        401,
        "invalid_session_token",
    )


def test_winner_selection_prioritizes_imported_rows() -> None:
    older_pending = _row("older-pending", key="a" * 64)
    imported = _row(
        "already-imported",
        key="a" * 64,
        status=ImportRowStatus.imported,
    )
    other = _row("other", key="b" * 64)

    candidates = cast(
        list[tuple[ImportRowModel, ImportBatchModel]],
        [
            (older_pending, _batch("older")),
            (imported, _batch("imported")),
            (other, _batch("other")),
        ],
    )
    assert _winner_ids(candidates) == {"already-imported", "other"}


@pytest.mark.parametrize("reserved_key", ["posting_intent", "deduplication"])
def test_skipped_markers_reject_reserved_workflow_metadata(reserved_key: str) -> None:
    row = _row("skipped", key=None, status=ImportRowStatus.skipped)
    row.normalized_data = {"schema_version": 2, "source": "anycoin", "kind": "neutral_row"}
    row.normalized_data[reserved_key] = {"schema_version": 1}
    row.created_transaction_id = None
    row.created_investment_event_id = None
    assert not _is_valid_row_state(cast(ImportRowModel, row))


@pytest.mark.parametrize(
    ("status", "created_field"),
    [
        (ImportRowStatus.failed, "created_transaction_id"),
        (ImportRowStatus.failed, "created_investment_event_id"),
        (ImportRowStatus.needs_review, "created_transaction_id"),
        (ImportRowStatus.needs_review, "created_investment_event_id"),
    ],
)
def test_nonpostable_rows_reject_created_entity_ids(
    status: ImportRowStatus, created_field: str
) -> None:
    row = _row("invalid", key=None, status=status)
    row.created_transaction_id = None
    row.created_investment_event_id = None
    setattr(row, created_field, "created")
    assert not _is_valid_row_state(cast(ImportRowModel, row))


@pytest.mark.asyncio
async def test_service_reconciles_non_winners_across_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    session.add = MagicMock()
    service = ImportDeduplicationService(session)
    current_batch = _batch()
    previous_batch = _batch("previous")
    later_batch = _batch("later")
    prior_imported = _row(
        "prior-imported",
        key="a" * 64,
        status=ImportRowStatus.imported,
    )
    current_duplicate = _row("current-duplicate", key="a" * 64)
    current_unique = _row("current-unique", key="b" * 64)
    later_duplicate = _row("later-duplicate", key="b" * 64)
    review = _row("review", key=None, status=ImportRowStatus.needs_review)
    failed = _row("failed", key=None, status=ImportRowStatus.failed)

    monkeypatch.setattr(
        "app.modules.imports.deduplication.require_account_access",
        _allow_access,
    )
    monkeypatch.setattr(
        service.repository,
        "get_for_account",
        AsyncMock(return_value=current_batch),
    )
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", AsyncMock())
    monkeypatch.setattr(
        service.repository,
        "list_rows_for_update",
        AsyncMock(
            return_value=[
                current_duplicate,
                current_unique,
                review,
                failed,
            ]
        ),
    )
    monkeypatch.setattr(
        service.repository,
        "list_deduplication_candidates_for_update",
        AsyncMock(
            return_value=[
                (prior_imported, previous_batch),
                (current_duplicate, current_batch),
                (current_unique, current_batch),
                (later_duplicate, later_batch),
            ]
        ),
    )
    add_log = MagicMock()
    monkeypatch.setattr(service.repository, "add_log", add_log)

    response = await service.deduplicate_batch(
        principal=_principal(),
        account_id="account-a",
        batch_id="batch-a",
    )

    assert response.model_dump() == {
        "batch_id": "batch-a",
        "status": ImportStatus.processing,
        "rows_total": 4,
        "rows_unique": 1,
        "rows_duplicate": 1,
        "rows_needs_review": 1,
        "rows_failed": 1,
    }
    assert current_duplicate.status is ImportRowStatus.duplicate
    assert current_unique.status is ImportRowStatus.pending
    assert later_duplicate.status is ImportRowStatus.duplicate
    assert later_batch.rows_skipped == 1
    assert current_batch.rows_skipped == 3
    assert add_log.call_count == 2
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "normalized", "key"),
    [
        (ImportRowStatus.imported, {"schema_version": 1}, "a" * 64),
        (ImportRowStatus.skipped, {"schema_version": 1}, "a" * 64),
        (ImportRowStatus.pending, None, "a" * 64),
        (ImportRowStatus.pending, {"schema_version": 1}, None),
        (ImportRowStatus.needs_review, {"schema_version": 1}, None),
        (ImportRowStatus.failed, None, "a" * 64),
    ],
)
async def test_service_rejects_rows_outside_normalized_boundary(
    monkeypatch: pytest.MonkeyPatch,
    status: ImportRowStatus,
    normalized: dict[str, int] | None,
    key: str | None,
) -> None:
    session = AsyncMock()
    service = ImportDeduplicationService(session)
    row = _row("row-a", key=key, status=status)
    row.normalized_data = normalized
    monkeypatch.setattr(
        "app.modules.imports.deduplication.require_account_access",
        _allow_access,
    )
    monkeypatch.setattr(
        service.repository,
        "get_for_account",
        AsyncMock(return_value=_batch()),
    )
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", AsyncMock())
    monkeypatch.setattr(
        service.repository,
        "list_rows_for_update",
        AsyncMock(return_value=[row]),
    )

    with pytest.raises(ImportDeduplicateStateError):
        await service.deduplicate_batch(
            principal=_principal(),
            account_id="account-a",
            batch_id="batch-a",
        )

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_rejects_missing_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    service = ImportDeduplicationService(session)
    monkeypatch.setattr(
        "app.modules.imports.deduplication.require_account_access",
        _allow_access,
    )
    monkeypatch.setattr(
        service.repository,
        "get_for_account",
        AsyncMock(return_value=_batch()),
    )
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", AsyncMock())
    monkeypatch.setattr(
        service.repository,
        "list_rows_for_update",
        AsyncMock(return_value=[]),
    )

    with pytest.raises(ImportDeduplicateRowsMissingError):
        await service.deduplicate_batch(
            principal=_principal(),
            account_id="account-a",
            batch_id="batch-a",
        )

    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_rolls_back_commit_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    session.commit.side_effect = RuntimeError("controlled failure")
    service = ImportDeduplicationService(session)
    row = _row("row-a", key="a" * 64)
    monkeypatch.setattr(
        "app.modules.imports.deduplication.require_account_access",
        _allow_access,
    )
    monkeypatch.setattr(
        service.repository,
        "get_for_account",
        AsyncMock(return_value=_batch()),
    )
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", AsyncMock())
    monkeypatch.setattr(
        service.repository,
        "list_rows_for_update",
        AsyncMock(return_value=[row]),
    )
    monkeypatch.setattr(
        service.repository,
        "list_deduplication_candidates_for_update",
        AsyncMock(return_value=[(row, _batch())]),
    )

    with pytest.raises(RuntimeError, match="controlled failure"):
        await service.deduplicate_batch(
            principal=_principal(),
            account_id="account-a",
            batch_id="batch-a",
        )

    session.rollback.assert_awaited_once()
