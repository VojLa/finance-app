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
        validation_errors=None,
        error_message=None,
        created_transaction_id=None,
        created_investment_event_id=None,
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
    assert current_duplicate.normalized_data["deduplication"] == {
        "schema_version": 1,
        "status": "duplicate",
    }
    assert current_unique.normalized_data["deduplication"] == {
        "schema_version": 1,
        "status": "unique",
    }
    assert later_duplicate.normalized_data["deduplication"] == {
        "schema_version": 1,
        "status": "duplicate",
    }
    assert "posting_intent" not in later_duplicate.normalized_data
    assert later_duplicate.validation_errors is None
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
@pytest.mark.parametrize(
    ("status", "initial_marker", "expected_status"),
    [
        (ImportRowStatus.pending, None, "unique"),
        (
            ImportRowStatus.pending,
            {"schema_version": 1, "status": "unique"},
            "unique",
        ),
        (ImportRowStatus.duplicate, None, "duplicate"),
        (
            ImportRowStatus.duplicate,
            {"schema_version": 1, "status": "duplicate"},
            "duplicate",
        ),
    ],
    ids=["first-unique", "repeat-unique", "first-duplicate", "repeat-duplicate"],
)
async def test_service_persists_exact_phase_marker_with_new_json_dictionary(
    monkeypatch: pytest.MonkeyPatch,
    status: ImportRowStatus,
    initial_marker: dict | None,
    expected_status: str,
) -> None:
    session = AsyncMock()
    service = ImportDeduplicationService(session)
    batch = _batch()
    row = _row("row", key="a" * 64, status=status)
    row.normalized_data["provider_field"] = "preserved"
    if initial_marker is not None:
        row.normalized_data["deduplication"] = initial_marker
    original = row.normalized_data
    monkeypatch.setattr("app.modules.imports.deduplication.require_account_access", _allow_access)
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=batch))
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", AsyncMock())
    monkeypatch.setattr(service.repository, "list_rows_for_update", AsyncMock(return_value=[row]))
    candidates = [(row, batch)] if status is ImportRowStatus.pending else []
    monkeypatch.setattr(
        service.repository,
        "list_deduplication_candidates_for_update",
        AsyncMock(return_value=candidates),
    )

    await service.deduplicate_batch(
        principal=_principal(), account_id="account-a", batch_id="batch-a"
    )

    assert row.normalized_data is not original
    assert row.normalized_data["provider_field"] == "preserved"
    assert row.normalized_data["deduplication"] == {
        "schema_version": 1,
        "status": expected_status,
    }
    assert row.deduplication_key == "a" * 64
    session.commit.assert_awaited_once()


def _invalid_deduplication_row(case: str) -> SimpleNamespace:
    row = _row("invalid", key="a" * 64)
    if case == "pending-duplicate-marker":
        row.normalized_data["deduplication"] = {"schema_version": 1, "status": "duplicate"}
    elif case == "duplicate-unique-marker":
        row.status = ImportRowStatus.duplicate
        row.normalized_data["deduplication"] = {"schema_version": 1, "status": "unique"}
    elif case == "malformed-marker":
        row.normalized_data["deduplication"] = "unique"
    elif case == "unsupported-marker-version":
        row.normalized_data["deduplication"] = {"schema_version": 2, "status": "unique"}
    elif case in {"pending-intent", "duplicate-intent"}:
        row.status = (
            ImportRowStatus.duplicate if case == "duplicate-intent" else ImportRowStatus.pending
        )
        if row.status is ImportRowStatus.duplicate:
            row.normalized_data["deduplication"] = {
                "schema_version": 1,
                "status": "duplicate",
            }
        row.normalized_data["posting_intent"] = {"schema_version": 1, "target": "transaction"}
    elif case in {"skipped-intent", "skipped-marker"}:
        row.status = ImportRowStatus.skipped
        row.deduplication_key = None
        row.normalized_data = {"schema_version": 2, "source": "anycoin", "kind": "neutral_row"}
        row.normalized_data["posting_intent" if case == "skipped-intent" else "deduplication"] = {
            "schema_version": 1
        }
    elif case in {
        "failed-transaction",
        "failed-investment",
        "review-transaction",
        "review-investment",
    }:
        row.status = (
            ImportRowStatus.failed if case.startswith("failed") else ImportRowStatus.needs_review
        )
        row.normalized_data = None
        row.deduplication_key = None
        setattr(
            row,
            "created_transaction_id"
            if case.endswith("transaction")
            else "created_investment_event_id",
            "created",
        )
    elif case in {"pending-transaction", "pending-investment"}:
        setattr(
            row,
            "created_transaction_id"
            if case.endswith("transaction")
            else "created_investment_event_id",
            "created",
        )
    else:
        raise AssertionError(case)
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "pending-duplicate-marker",
        "duplicate-unique-marker",
        "malformed-marker",
        "unsupported-marker-version",
        "pending-intent",
        "duplicate-intent",
        "skipped-intent",
        "skipped-marker",
        "failed-transaction",
        "failed-investment",
        "review-transaction",
        "review-investment",
        "pending-transaction",
        "pending-investment",
    ],
)
async def test_service_rejects_invalid_phase_state_without_commit(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    session = AsyncMock()
    service = ImportDeduplicationService(session)
    row = _invalid_deduplication_row(case)
    monkeypatch.setattr("app.modules.imports.deduplication.require_account_access", _allow_access)
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=_batch()))
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", AsyncMock())
    monkeypatch.setattr(service.repository, "list_rows_for_update", AsyncMock(return_value=[row]))

    with pytest.raises(ImportDeduplicateStateError):
        await service.deduplicate_batch(
            principal=_principal(), account_id="account-a", batch_id="batch-a"
        )

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_cross_batch_demotion_removes_intent_and_preserves_canonical_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    session.add = MagicMock()
    service = ImportDeduplicationService(session)
    current_batch = _batch("current")
    later_batch = _batch("later")
    winner = _row("winner", key="a" * 64)
    loser = _row("loser", key="a" * 64)
    loser.normalized_data = {
        "schema_version": 1,
        "provider_field": "preserved",
        "deduplication": {"schema_version": 1, "status": "unique"},
        "posting_intent": {"schema_version": 1, "target": "transaction"},
    }
    loser.validation_errors = [{"field": "type", "code": "stale_review"}]
    loser.error_message = "Row requires classification review."
    original = loser.normalized_data
    monkeypatch.setattr("app.modules.imports.deduplication.require_account_access", _allow_access)
    monkeypatch.setattr(
        service.repository, "get_for_account", AsyncMock(return_value=current_batch)
    )
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", AsyncMock())
    monkeypatch.setattr(
        service.repository, "list_rows_for_update", AsyncMock(return_value=[winner])
    )
    monkeypatch.setattr(
        service.repository,
        "list_deduplication_candidates_for_update",
        AsyncMock(return_value=[(winner, current_batch), (loser, later_batch)]),
    )
    monkeypatch.setattr(service.repository, "add_log", MagicMock())

    await service.deduplicate_batch(
        principal=_principal(), account_id="account-a", batch_id="current"
    )

    assert loser.status is ImportRowStatus.duplicate
    assert loser.normalized_data is not original
    assert loser.normalized_data == {
        "schema_version": 1,
        "provider_field": "preserved",
        "deduplication": {"schema_version": 1, "status": "duplicate"},
    }
    assert loser.deduplication_key == "a" * 64
    assert loser.validation_errors is None
    assert loser.error_message == "Duplicate normalized import row."
    assert later_batch.rows_skipped == 1


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
