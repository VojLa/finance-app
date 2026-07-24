from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import ImportRowStatus, ImportSource, ImportStatus
from app.modules.imports.classification import classify_import_row
from app.modules.imports.classification_service import (
    ImportClassificationService,
    ImportClassifyRowsMissingError,
    ImportClassifyStateError,
    _canonical,
    _marker_is,
)
from app.modules.imports.normalizers import normalize_import_row
from app.modules.imports.service import ImportBatchNotFoundError


def test_classifier_workflow_metadata_is_removed_from_canonical_payload() -> None:
    payload = {
        "schema_version": 1,
        "source": "manual",
        "amount": "1",
        "deduplication": {"schema_version": 1, "status": "unique"},
        "posting_intent": {"target": "transaction"},
    }

    canonical = _canonical(payload)

    assert canonical == {"schema_version": 1, "source": "manual", "amount": "1"}
    assert _marker_is(payload, "unique")
    assert payload["posting_intent"] == {"target": "transaction"}


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="owner", email="owner@example.com", name="Owner")


def _batch(
    source: ImportSource = ImportSource.manual,
    *,
    status: ImportStatus = ImportStatus.processing,
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        source=source,
        rows_total=0,
        rows_imported=0,
        rows_skipped=0,
        completed_at=None,
    )


def _row(
    *, status: ImportRowStatus = ImportRowStatus.pending, data: dict | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        id="row",
        status=status,
        normalized_data=data,
        deduplication_key="a" * 64 if data is not None else None,
        validation_errors=None,
        error_message=None,
        created_transaction_id=None,
        created_investment_event_id=None,
    )


def _manual_payload(
    source: ImportSource = ImportSource.manual,
    *,
    amount: str = "10",
    source_type: str = "income",
) -> dict:
    return {
        "schema_version": 1,
        "source": source.value,
        "date": "2026-07-23",
        "amount": amount,
        "currency": "EUR",
        "type": source_type,
    }


def _investment_payload(source: ImportSource, *, transfer: bool = False) -> dict:
    if source is ImportSource.trading212:
        normalized = normalize_import_row(
            source=source,
            account_id="account",
            raw_data={
                "Action": "Market buy",
                "Time": "2026-07-23T10:00:00Z",
                "Ticker": "VWCE",
                "No. of shares": "2",
                "Price / share": "100.50",
                "Currency (Price / share)": "EUR",
                "Total": "201",
                "Currency (Total)": "EUR",
                "ID": "trade-1",
            },
        )
        assert normalized.data is not None
        return normalized.data
    return {
        "schema_version": 2,
        "source": "anycoin",
        "kind": "investment_event",
        "date": "2026-07-23T10:00:00+00:00",
        "action": "asset_transfer" if transfer else "buy",
        "external_id": "provider-id",
        "order_id": None if transfer else "order-1",
        "raw_action": "deposit" if transfer else "grouped_trade",
        "asset": {"symbol": "BTC", "isin": None, "name": None, "asset_type_hint": "crypto"},
        "quantity": "1",
        "price": None if transfer else {"amount": "100", "currency": "EUR"},
        "total": None if transfer else {"amount": "100", "currency": "EUR"},
        "fee": None,
        "conversion": None,
        "realized_pnl": None,
        "is_promotional": False,
        "note": None,
        "asset_direction": "in" if transfer else None,
    }


def _unique(data: dict) -> dict:
    result = deepcopy(data)
    result["deduplication"] = {"schema_version": 1, "status": "unique"}
    return result


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    service: ImportClassificationService,
    batch: SimpleNamespace | None,
    rows: list[SimpleNamespace],
) -> None:
    monkeypatch.setattr(
        "app.modules.imports.classification_service.require_account_access", AsyncMock()
    )
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=batch))
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", AsyncMock())
    monkeypatch.setattr(service.repository, "list_rows_for_update", AsyncMock(return_value=rows))


@pytest.mark.asyncio
async def test_service_persists_manual_intent_with_replaced_json_dictionary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    session = AsyncMock()
    service = ImportClassificationService(session)
    row = _row(
        data={
            "schema_version": 1,
            "source": "manual",
            "date": "2026-07-23",
            "amount": "1",
            "currency": "EUR",
            "deduplication": {"schema_version": 1, "status": "unique"},
        }
    )
    original = row.normalized_data
    monkeypatch.setattr(
        "app.modules.imports.classification_service.require_account_access", AsyncMock()
    )
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=_batch()))
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", AsyncMock())
    monkeypatch.setattr(service.repository, "list_rows_for_update", AsyncMock(return_value=[row]))

    result = await service.classify_batch(
        principal=_principal(), account_id="account", batch_id="batch"
    )

    assert result.rows_classified == 1
    assert row.normalized_data is not original
    assert row.normalized_data["posting_intent"]["target"] == "transaction"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_preserves_normalization_review_without_classifier_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    service = ImportClassificationService(session)
    row = _row(status=ImportRowStatus.needs_review, data=None)
    monkeypatch.setattr(
        "app.modules.imports.classification_service.require_account_access", AsyncMock()
    )
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=_batch()))
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", AsyncMock())
    monkeypatch.setattr(service.repository, "list_rows_for_update", AsyncMock(return_value=[row]))

    result = await service.classify_batch(
        principal=_principal(), account_id="account", batch_id="batch"
    )

    assert result.rows_needs_review == 1
    assert row.normalized_data is None and row.deduplication_key is None


@pytest.mark.asyncio
async def test_service_persists_classification_review_with_safe_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    service = ImportClassificationService(session)
    row = _row(
        data={
            "schema_version": 1,
            "source": "manual",
            "date": "2026-07-23",
            "amount": "1",
            "currency": "EUR",
            "type": "transfer",
            "deduplication": {"schema_version": 1, "status": "unique"},
        }
    )
    monkeypatch.setattr(
        "app.modules.imports.classification_service.require_account_access", AsyncMock()
    )
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=_batch()))
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", AsyncMock())
    monkeypatch.setattr(service.repository, "list_rows_for_update", AsyncMock(return_value=[row]))

    response = await service.classify_batch(
        principal=_principal(), account_id="account", batch_id="batch"
    )

    assert response.rows_needs_review == 1
    assert row.status is ImportRowStatus.needs_review
    assert row.normalized_data["posting_intent"]["target"] == "needs_review"
    assert row.validation_errors == row.normalized_data["posting_intent"]["errors"]
    assert row.error_message == "Row requires classification review."


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved_key", ["posting_intent", "deduplication"])
async def test_service_rejects_reserved_metadata_on_skipped_marker(
    monkeypatch: pytest.MonkeyPatch, reserved_key: str
) -> None:
    session = AsyncMock()
    service = ImportClassificationService(session)
    data = {"schema_version": 2, "source": "anycoin", "kind": "neutral_row"}
    data[reserved_key] = {"schema_version": 1}
    row = _row(status=ImportRowStatus.skipped, data=data)
    row.deduplication_key = None
    monkeypatch.setattr(
        "app.modules.imports.classification_service.require_account_access", AsyncMock()
    )
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=_batch()))
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", AsyncMock())
    monkeypatch.setattr(service.repository, "list_rows_for_update", AsyncMock(return_value=[row]))

    with pytest.raises(ImportClassifyStateError):
        await service.classify_batch(principal=_principal(), account_id="account", batch_id="batch")

    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_rejects_created_entity_ids_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    service = ImportClassificationService(session)
    row = _row(data={"schema_version": 1, "source": "manual"})
    row.created_transaction_id = "created"
    monkeypatch.setattr(
        "app.modules.imports.classification_service.require_account_access", AsyncMock()
    )
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=_batch()))
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", AsyncMock())
    monkeypatch.setattr(service.repository, "list_rows_for_update", AsyncMock(return_value=[row]))

    with pytest.raises(ImportClassifyStateError):
        await service.classify_batch(principal=_principal(), account_id="account", batch_id="batch")
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "payload", "target"),
    [
        (ImportSource.manual, _manual_payload(), "transaction"),
        (
            ImportSource.raiffeisenbank,
            _manual_payload(ImportSource.raiffeisenbank, amount="-10", source_type="expense"),
            "transaction",
        ),
        (
            ImportSource.trading212,
            _investment_payload(ImportSource.trading212),
            "investment_event",
        ),
        (ImportSource.anycoin, _investment_payload(ImportSource.anycoin), "investment_event"),
        (
            ImportSource.anycoin,
            _investment_payload(ImportSource.anycoin, transfer=True),
            "investment_event",
        ),
    ],
    ids=["manual", "raiffeisenbank", "trading212", "anycoin-anchor", "anycoin-transfer"],
)
async def test_service_classifies_supported_provider_workflows(
    monkeypatch: pytest.MonkeyPatch,
    source: ImportSource,
    payload: dict,
    target: str,
) -> None:
    session = AsyncMock()
    service = ImportClassificationService(session)
    canonical = deepcopy(payload)
    row = _row(data=_unique(payload))
    original_key = row.deduplication_key
    batch = _batch(source)
    _configure(monkeypatch, service, batch, [row])

    response = await service.classify_batch(
        principal=_principal(), account_id="account", batch_id="batch"
    )

    expected = classify_import_row(source=source, normalized_data=canonical).model_dump(mode="json")
    assert response.model_dump() == {
        "batch_id": "batch",
        "status": ImportStatus.processing,
        "rows_total": 1,
        "rows_classified": 1,
        "rows_needs_review": 0,
        "rows_duplicate": 0,
        "rows_skipped": 0,
        "rows_failed": 0,
    }
    assert row.normalized_data == {
        **canonical,
        "deduplication": {"schema_version": 1, "status": "unique"},
        "posting_intent": expected,
    }
    assert row.normalized_data["posting_intent"]["target"] == target
    assert row.deduplication_key == original_key
    assert row.status is ImportRowStatus.pending
    assert row.validation_errors is None and row.error_message is None
    assert row.created_transaction_id is None and row.created_investment_event_id is None
    assert batch.rows_imported == 0 and batch.rows_skipped == 0
    assert batch.status is ImportStatus.processing and batch.completed_at is None


@pytest.mark.asyncio
async def test_service_preserves_all_nonclassifiable_states_and_exact_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    service = ImportClassificationService(session)
    successful = _row(data=_unique(_manual_payload()))
    review = _row(data=_unique(_manual_payload(source_type="transfer")))
    normalization_review = _row(status=ImportRowStatus.needs_review, data=None)
    duplicate = _row(
        status=ImportRowStatus.duplicate,
        data={
            **_manual_payload(),
            "deduplication": {"schema_version": 1, "status": "duplicate"},
        },
    )
    failed = _row(status=ImportRowStatus.failed, data=None)
    skipped_rows = []
    for kind in ("group_member", "fully_refunded_group", "neutral_row"):
        skipped = _row(
            status=ImportRowStatus.skipped,
            data={"schema_version": 2, "source": "anycoin", "kind": kind},
        )
        skipped.deduplication_key = None
        skipped_rows.append(skipped)
    preserved = [
        deepcopy(row.normalized_data)
        for row in [normalization_review, duplicate, failed, *skipped_rows]
    ]
    batch = _batch()
    rows = [successful, review, normalization_review, duplicate, failed, *skipped_rows]
    _configure(monkeypatch, service, batch, rows)

    response = await service.classify_batch(
        principal=_principal(), account_id="account", batch_id="batch"
    )

    assert response.model_dump() == {
        "batch_id": "batch",
        "status": ImportStatus.processing,
        "rows_total": 8,
        "rows_classified": 1,
        "rows_needs_review": 2,
        "rows_duplicate": 1,
        "rows_skipped": 3,
        "rows_failed": 1,
    }
    assert batch.rows_total == 8
    assert batch.rows_imported == 0
    assert batch.rows_skipped == 7
    assert batch.completed_at is None
    assert review.status is ImportRowStatus.needs_review
    assert review.validation_errors == review.normalized_data["posting_intent"]["errors"]
    assert review.error_message == "Row requires classification review."
    for row, expected in zip(
        [normalization_review, duplicate, failed, *skipped_rows], preserved, strict=True
    ):
        assert row.normalized_data == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("review", [False, True], ids=["successful", "classification-review"])
async def test_service_repeat_is_idempotent(monkeypatch: pytest.MonkeyPatch, review: bool) -> None:
    session = AsyncMock()
    service = ImportClassificationService(session)
    row = _row(data=_unique(_manual_payload(source_type="transfer" if review else "income")))
    batch = _batch()
    _configure(monkeypatch, service, batch, [row])

    first = await service.classify_batch(
        principal=_principal(), account_id="account", batch_id="batch"
    )
    stored = row.normalized_data
    snapshot = deepcopy(stored)
    errors = deepcopy(row.validation_errors)
    second = await service.classify_batch(
        principal=_principal(), account_id="account", batch_id="batch"
    )

    assert second == first
    assert row.normalized_data is stored
    assert row.normalized_data == snapshot
    assert row.validation_errors == errors
    assert session.commit.await_count == 2


def _invalid_classification_row(case: str) -> SimpleNamespace:
    canonical = _manual_payload()
    expected = classify_import_row(
        source=ImportSource.manual, normalized_data=canonical
    ).model_dump(mode="json")
    row = _row(data=_unique(canonical))
    if case == "stored-intent-mismatch":
        row.normalized_data["posting_intent"] = {**expected, "amount": "999"}
    elif case == "malformed-intent":
        row.normalized_data["posting_intent"] = "invalid"
    elif case == "pending-review-intent":
        review = classify_import_row(
            source=ImportSource.manual,
            normalized_data=_manual_payload(source_type="transfer"),
        ).model_dump(mode="json")
        row.normalized_data = _unique(_manual_payload(source_type="transfer"))
        row.normalized_data["posting_intent"] = review
    elif case in {"review-success-intent", "review-validation-errors", "review-message"}:
        row.status = ImportRowStatus.needs_review
        row.normalized_data["posting_intent"] = expected
        row.validation_errors = []
        row.error_message = "Row requires classification review."
        if case == "review-validation-errors":
            review = classify_import_row(
                source=ImportSource.manual,
                normalized_data=_manual_payload(source_type="transfer"),
            ).model_dump(mode="json")
            row.normalized_data = _unique(_manual_payload(source_type="transfer"))
            row.normalized_data["posting_intent"] = review
            row.validation_errors = []
        elif case == "review-message":
            row.normalized_data = _unique(_manual_payload(source_type="transfer"))
            row.normalized_data["posting_intent"] = classify_import_row(
                source=ImportSource.manual,
                normalized_data=_manual_payload(source_type="transfer"),
            ).model_dump(mode="json")
            row.validation_errors = row.normalized_data["posting_intent"]["errors"]
            row.error_message = "unsafe"
    elif case == "successful-validation-errors":
        row.normalized_data["posting_intent"] = expected
        row.validation_errors = []
    elif case == "successful-error-message":
        row.normalized_data["posting_intent"] = expected
        row.error_message = "unexpected"
    elif case == "malformed-marker":
        row.normalized_data["deduplication"] = "unique"
    elif case == "unsupported-marker-version":
        row.normalized_data["deduplication"] = {"schema_version": 2, "status": "unique"}
    elif case == "pending-without-key":
        row.deduplication_key = None
    elif case == "duplicate-without-marker":
        row.status = ImportRowStatus.duplicate
        row.normalized_data.pop("deduplication")
    elif case == "duplicate-with-intent":
        row.status = ImportRowStatus.duplicate
        row.normalized_data["deduplication"] = {"schema_version": 1, "status": "duplicate"}
        row.normalized_data["posting_intent"] = expected
    elif case in {"skipped-key", "skipped-intent", "skipped-marker"}:
        row.status = ImportRowStatus.skipped
        row.normalized_data = {"schema_version": 2, "source": "anycoin", "kind": "neutral_row"}
        row.deduplication_key = None
        if case == "skipped-key":
            row.deduplication_key = "a" * 64
        elif case == "skipped-intent":
            row.normalized_data["posting_intent"] = expected
        else:
            row.normalized_data["deduplication"] = {"schema_version": 1, "status": "unique"}
    elif case in {"failed-data", "failed-key"}:
        row.status = ImportRowStatus.failed
        row.normalized_data = None
        row.deduplication_key = None
        if case == "failed-data":
            row.normalized_data = canonical
        else:
            row.deduplication_key = "a" * 64
    elif case == "imported":
        row.status = ImportRowStatus.imported
    elif case == "created-transaction":
        row.created_transaction_id = "transaction"
    elif case == "created-investment":
        row.created_investment_event_id = "investment"
    else:
        raise AssertionError(case)
    return row


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "stored-intent-mismatch",
        "malformed-intent",
        "pending-review-intent",
        "review-success-intent",
        "review-validation-errors",
        "review-message",
        "successful-validation-errors",
        "successful-error-message",
        "malformed-marker",
        "unsupported-marker-version",
        "pending-without-key",
        "duplicate-without-marker",
        "duplicate-with-intent",
        "skipped-key",
        "skipped-intent",
        "skipped-marker",
        "failed-data",
        "failed-key",
        "imported",
        "created-transaction",
        "created-investment",
    ],
)
async def test_service_rejects_invalid_persisted_state_without_commit(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    session = AsyncMock()
    service = ImportClassificationService(session)
    row = _invalid_classification_row(case)
    original = deepcopy(row.normalized_data)
    _configure(monkeypatch, service, _batch(), [row])

    with pytest.raises(ImportClassifyStateError):
        await service.classify_batch(principal=_principal(), account_id="account", batch_id="batch")

    assert row.normalized_data == original
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_orchestration_uses_access_lock_reload_row_lock_and_one_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    service = ImportClassificationService(session)
    batch = _batch()
    row = _row(data=_unique(_manual_payload()))
    access = AsyncMock()
    lookup = AsyncMock(side_effect=[batch, batch])
    lock = AsyncMock()
    rows = AsyncMock(return_value=[row])
    monkeypatch.setattr("app.modules.imports.classification_service.require_account_access", access)
    monkeypatch.setattr(service.repository, "get_for_account", lookup)
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", lock)
    monkeypatch.setattr(service.repository, "list_rows_for_update", rows)

    await service.classify_batch(principal=_principal(), account_id="account", batch_id="batch")

    assert access.await_args is not None
    assert (
        access.await_args.kwargs["allowed_roles"]
        == service.classify_batch.__globals__["WRITE_ROLES"]
    )
    assert lookup.await_args_list == [
        call(account_id="account", batch_id="batch"),
        call(account_id="account", batch_id="batch", for_update=True),
    ]
    lock.assert_awaited_once_with(account_id="account", source=ImportSource.manual)
    rows.assert_awaited_once_with("batch")
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["missing-batch", "invalid-status", "missing-rows"])
async def test_service_rejects_invalid_batch_boundaries(
    monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    session = AsyncMock()
    service = ImportClassificationService(session)
    batch = None if boundary == "missing-batch" else _batch()
    if boundary == "invalid-status":
        assert batch is not None
        batch.status = ImportStatus.completed
    _configure(monkeypatch, service, batch, [])

    expected = (
        ImportBatchNotFoundError
        if boundary == "missing-batch"
        else ImportClassifyStateError
        if boundary == "invalid-status"
        else ImportClassifyRowsMissingError
    )
    with pytest.raises(expected):
        await service.classify_batch(principal=_principal(), account_id="account", batch_id="batch")
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_rolls_back_commit_failure_after_preparing_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    session.commit.side_effect = RuntimeError("controlled commit failure")
    service = ImportClassificationService(session)
    row = _row(data=_unique(_manual_payload()))
    _configure(monkeypatch, service, _batch(), [row])

    with pytest.raises(RuntimeError, match="controlled commit failure"):
        await service.classify_batch(principal=_principal(), account_id="account", batch_id="batch")

    assert row.normalized_data["posting_intent"]["target"] == "transaction"
    session.rollback.assert_awaited_once()
