from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import ImportRowStatus, ImportSource, ImportStatus
from app.modules.imports.classification_service import (
    ImportClassificationService,
    _canonical,
    _marker_is,
)


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


def _batch() -> SimpleNamespace:
    return SimpleNamespace(status=ImportStatus.processing, source=ImportSource.manual)


def _row(
    *, status: ImportRowStatus = ImportRowStatus.pending, data: dict | None = None
) -> SimpleNamespace:
    return SimpleNamespace(
        status=status,
        normalized_data=data,
        deduplication_key="a" * 64 if data is not None else None,
        validation_errors=None,
        error_message=None,
        created_transaction_id=None,
        created_investment_event_id=None,
    )


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
    monkeypatch.setattr("app.modules.imports.classification_service.require_account_access", AsyncMock())
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=_batch()))
    monkeypatch.setattr(service.repository, "lock_deduplication_scope", AsyncMock())
    monkeypatch.setattr(service.repository, "list_rows_for_update", AsyncMock(return_value=[row]))

    response = await service.classify_batch(principal=_principal(), account_id="account", batch_id="batch")

    assert response.rows_needs_review == 1
    assert row.status is ImportRowStatus.needs_review
    assert row.normalized_data["posting_intent"]["target"] == "needs_review"
    assert row.validation_errors == row.normalized_data["posting_intent"]["errors"]
    assert row.error_message == "Row requires classification review."
