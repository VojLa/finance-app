from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import ImportRowStatus, ImportSource, ImportStatus
from app.modules.imports.normalization import (
    ImportNormalizationService,
    ImportNormalizeStateError,
)
from app.modules.imports.normalizers import normalize_import_row


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="user-a", email="a@example.com", name="A")


def test_normalizer_creates_canonical_data_and_stable_key() -> None:
    raw = {
        "Datum": "20.07.2026",
        "Částka": "1 234,50",
        "Měna": "czk",
        "Popis": "Salary",
        "Reference": "abc-1",
    }

    first = normalize_import_row(
        source=ImportSource.raiffeisenbank,
        account_id="account-a",
        raw_data=raw,
    )
    second = normalize_import_row(
        source=ImportSource.raiffeisenbank,
        account_id="account-a",
        raw_data=dict(reversed(list(raw.items()))),
    )

    assert first.validation_errors is None
    assert first.data == {
        "schema_version": 1,
        "source": "raiffeisenbank",
        "date": "2026-07-20",
        "amount": "1234.5",
        "currency": "CZK",
        "external_id": "abc-1",
        "description": "Salary",
    }
    assert first.deduplication_key == second.deduplication_key
    assert first.deduplication_key is not None
    assert len(first.deduplication_key) == 64


def test_normalizer_marks_missing_required_fields_for_review() -> None:
    result = normalize_import_row(
        source=ImportSource.manual,
        account_id="account-a",
        raw_data={"Description": "No financial fields"},
    )

    assert result.data is None
    assert result.deduplication_key is None
    assert {error["field"] for error in result.validation_errors or []} == {
        "date",
        "amount",
        "currency",
    }


def test_normalizer_rejects_nonfinite_amount() -> None:
    result = normalize_import_row(
        source=ImportSource.trading212,
        account_id="account-a",
        raw_data={"Date": "2026-07-20", "Amount": "NaN", "Currency": "EUR"},
    )

    assert result.data is None
    assert any(error["field"] == "amount" for error in result.validation_errors or [])


@pytest.mark.asyncio
async def test_service_normalizes_pending_rows_and_preserves_parser_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    service = ImportNormalizationService(session)
    batch = SimpleNamespace(
        id="batch-a",
        source=ImportSource.manual,
        status=ImportStatus.processing,
        rows_total=3,
        rows_imported=0,
        rows_skipped=1,
        completed_at=None,
    )
    valid = SimpleNamespace(
        status=ImportRowStatus.pending,
        raw_data={"Date": "2026-07-20", "Amount": "10.50", "Currency": "eur"},
        normalized_data=None,
        deduplication_key=None,
        validation_errors=None,
        error_message=None,
    )
    review = SimpleNamespace(
        status=ImportRowStatus.pending,
        raw_data={"Date": "bad", "Amount": "10", "Currency": "EUR"},
        normalized_data=None,
        deduplication_key=None,
        validation_errors=None,
        error_message=None,
    )
    failed = SimpleNamespace(
        status=ImportRowStatus.failed,
        raw_data={},
        normalized_data=None,
        deduplication_key=None,
        validation_errors={"code": "parse"},
        error_message="Parser failure",
    )
    service.repository.get_for_account = AsyncMock(return_value=batch)
    service.repository.list_rows_for_update = AsyncMock(return_value=[valid, review, failed])

    async def allow_access(**_: object) -> None:
        return None

    monkeypatch.setattr("app.modules.imports.normalization.require_account_access", allow_access)

    response = await service.normalize_batch(
        principal=_principal(),
        account_id="account-a",
        batch_id="batch-a",
    )

    assert response.rows_normalized == 1
    assert response.rows_needs_review == 1
    assert response.rows_failed == 1
    assert valid.normalized_data["amount"] == "10.5"
    assert valid.deduplication_key is not None
    assert valid.status is ImportRowStatus.pending
    assert review.status is ImportRowStatus.needs_review
    assert review.deduplication_key is None
    assert failed.status is ImportRowStatus.failed
    assert batch.rows_imported == 0
    assert batch.rows_skipped == 2
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_rejects_second_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    service = ImportNormalizationService(session)
    batch = SimpleNamespace(source=ImportSource.manual, status=ImportStatus.processing)
    row = SimpleNamespace(normalized_data={"schema_version": 1}, deduplication_key="a" * 64)
    service.repository.get_for_account = AsyncMock(return_value=batch)
    service.repository.list_rows_for_update = AsyncMock(return_value=[row])

    async def allow_access(**_: object) -> None:
        return None

    monkeypatch.setattr("app.modules.imports.normalization.require_account_access", allow_access)

    with pytest.raises(ImportNormalizeStateError):
        await service.normalize_batch(
            principal=_principal(),
            account_id="account-a",
            batch_id="batch-a",
        )

    session.commit.assert_not_awaited()
