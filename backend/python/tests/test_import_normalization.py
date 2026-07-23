import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import ImportRowStatus, ImportSource, ImportStatus
from app.modules.imports.normalization import (
    ImportNormalizationService,
    ImportNormalizeRowsMissingError,
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
        source=ImportSource.manual,
        account_id="account-a",
        raw_data={"Date": "2026-07-20", "Amount": "NaN", "Currency": "EUR"},
    )

    assert result.data is None
    assert any(error["field"] == "amount" for error in result.validation_errors or [])


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "-Infinity", "not-a-number"])
def test_normalizer_rejects_invalid_decimal_values(amount: str) -> None:
    result = normalize_import_row(
        source=ImportSource.manual,
        account_id="account-a",
        raw_data={"Date": "2026-07-20", "Amount": amount, "Currency": "EUR"},
    )
    assert result.data is None
    assert result.deduplication_key is None
    assert any(error["field"] == "amount" for error in result.validation_errors or [])


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1234.50", "1234.5"),
        ("1234,50", "1234.5"),
        ("1 234,50", "1234.5"),
        ("1\u00a0234,50", "1234.5"),
        ("1,234.50", "1234.5"),
        ("1.234,50", "1234.5"),
        ("-85.50", "-85.5"),
        ("+85.50", "85.5"),
        ("0.00", "0"),
        ("1,234", "1.234"),
        ("1.234", "1.234"),
    ],
)
def test_normalizer_canonicalizes_decimal_formats(value: str, expected: str) -> None:
    result = normalize_import_row(
        source=ImportSource.manual,
        account_id="account-a",
        raw_data={"Date": "2026-07-20", "Amount": value, "Currency": "EUR"},
    )
    assert result.validation_errors is None
    assert result.data is not None
    assert result.data["amount"] == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-07-20", "2026-07-20"),
        ("2026-07-20 12:30:00", "2026-07-20T12:30:00"),
        ("2026-07-20T12:30:00", "2026-07-20T12:30:00"),
        ("2026-07-20T12:30:00Z", "2026-07-20T12:30:00+00:00"),
        ("2026-07-20T12:30:00+02:00", "2026-07-20T10:30:00+00:00"),
        ("20.07.2026", "2026-07-20"),
        ("20.07.2026 12:30:00", "2026-07-20T12:30:00"),
        ("20/07/2026", "2026-07-20"),
        ("07/20/2026", "2026-07-20"),
    ],
)
def test_normalizer_canonicalizes_supported_dates(value: str, expected: str) -> None:
    result = normalize_import_row(
        source=ImportSource.manual,
        account_id="account-a",
        raw_data={"Date": value, "Amount": "1", "Currency": "EUR"},
    )
    assert result.validation_errors is None
    assert result.data is not None
    assert result.data["date"] == expected


def test_normalizer_rejects_ambiguous_slash_date() -> None:
    result = normalize_import_row(
        source=ImportSource.manual,
        account_id="account-a",
        raw_data={"Date": "01/02/2026", "Amount": "1", "Currency": "EUR"},
    )
    assert result.data is None
    assert result.deduplication_key is None
    assert result.validation_errors == [
        {"field": "date", "code": "invalid", "message": "Ambiguous slash date format."}
    ]


@pytest.mark.parametrize("currency", ["", "X", "US D", "../USD", "A" * 21])
def test_normalizer_rejects_invalid_currency(currency: str) -> None:
    result = normalize_import_row(
        source=ImportSource.manual,
        account_id="account-a",
        raw_data={"Date": "2026-07-20", "Amount": "1", "Currency": currency},
    )
    assert result.data is None
    assert any(error["field"] == "currency" for error in result.validation_errors or [])


@pytest.mark.parametrize(
    ("source", "raw", "expected"),
    [
        (
            ImportSource.raiffeisenbank,
            {"Datum": "20.07.2026", "Částka": "10,50", "Měna": "czk", "Popis": "Platba"},
            {"date": "2026-07-20", "amount": "10.5", "currency": "CZK", "description": "Platba"},
        ),
        (
            ImportSource.anycoin,
            {
                "Datum a čas": "20.07.2026 12:30:00",
                "Množství": "0,5",
                "Měna": "btc",
                "ID transakce": "a-1",
                "Typ": "Nákup",
            },
            {
                "date": "2026-07-20T12:30:00",
                "amount": "0.5",
                "currency": "BTC",
                "external_id": "a-1",
                "type": "Nákup",
            },
        ),
        (
            ImportSource.manual,
            {"Date": "2026-07-20", "Amount": "10", "Currency": "usd", "Description": " Manual "},
            {"date": "2026-07-20", "amount": "10", "currency": "USD", "description": "Manual"},
        ),
    ],
)
def test_normalizer_provider_alias_fixtures(
    source: ImportSource, raw: dict[str, str], expected: dict[str, str]
) -> None:
    result = normalize_import_row(source=source, account_id="account-a", raw_data=raw)
    assert result.validation_errors is None
    assert result.data is not None
    for field, value in expected.items():
        assert result.data[field] == value


def test_deduplication_key_is_stable_and_scoped() -> None:
    base = {
        " Date ": "20.07.2026",
        "AMOUNT": "1 234,50",
        "Currency": " eur ",
        "Description": "Salary",
    }
    equivalent = {
        "description": "Salary",
        "currency": "EUR",
        "amount": "1234.500",
        "date": "2026-07-20",
    }
    first = normalize_import_row(source=ImportSource.manual, account_id="account-a", raw_data=base)
    second = normalize_import_row(
        source=ImportSource.manual, account_id="account-a", raw_data=equivalent
    )
    other_account = normalize_import_row(
        source=ImportSource.manual, account_id="account-b", raw_data=equivalent
    )
    other_source = normalize_import_row(
        source=ImportSource.anycoin, account_id="account-a", raw_data=equivalent
    )
    assert first.deduplication_key == second.deduplication_key
    assert first.deduplication_key != other_account.deduplication_key
    assert first.deduplication_key != other_source.deduplication_key
    assert re.fullmatch(r"[0-9a-f]{64}", first.deduplication_key or "")


def test_duplicate_alias_selection_is_insertion_order_independent() -> None:
    raw = {"DATE": "2026-07-20", "date": "2026-07-21", "Amount": "1", "Currency": "EUR"}
    reversed_raw = dict(reversed(list(raw.items())))
    first = normalize_import_row(source=ImportSource.manual, account_id="account-a", raw_data=raw)
    second = normalize_import_row(
        source=ImportSource.manual, account_id="account-a", raw_data=reversed_raw
    )
    assert first.data == second.data
    assert first.deduplication_key == second.deduplication_key


def test_optional_identity_field_has_size_limit() -> None:
    result = normalize_import_row(
        source=ImportSource.manual,
        account_id="account-a",
        raw_data={
            "Date": "2026-07-20",
            "Amount": "1",
            "Currency": "EUR",
            "Description": "x" * 4097,
        },
    )
    assert result.data is None
    assert result.deduplication_key is None
    assert any(error["code"] == "too_long" for error in result.validation_errors or [])


@pytest.mark.asyncio
async def test_service_normalizes_pending_rows_and_preserves_parser_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=batch))
    monkeypatch.setattr(
        service.repository,
        "list_rows_for_update",
        AsyncMock(return_value=[valid, review, failed]),
    )

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
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=batch))
    monkeypatch.setattr(service.repository, "list_rows_for_update", AsyncMock(return_value=[row]))

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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        ImportRowStatus.imported,
        ImportRowStatus.skipped,
        ImportRowStatus.duplicate,
        ImportRowStatus.needs_review,
    ],
)
async def test_service_rejects_unexpected_existing_row_states(
    monkeypatch: pytest.MonkeyPatch, status: ImportRowStatus
) -> None:
    session = AsyncMock()
    service = ImportNormalizationService(session)
    batch = SimpleNamespace(source=ImportSource.manual, status=ImportStatus.processing)
    row = SimpleNamespace(status=status, normalized_data=None, deduplication_key=None)
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=batch))
    monkeypatch.setattr(service.repository, "list_rows_for_update", AsyncMock(return_value=[row]))

    async def allow_access(**_: object) -> None:
        return None

    monkeypatch.setattr("app.modules.imports.normalization.require_account_access", allow_access)
    with pytest.raises(ImportNormalizeStateError):
        await service.normalize_batch(
            principal=_principal(), account_id="account-a", batch_id="batch-a"
        )
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_rejects_processing_batch_without_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    service = ImportNormalizationService(session)
    monkeypatch.setattr(
        service.repository,
        "get_for_account",
        AsyncMock(
            return_value=SimpleNamespace(source=ImportSource.manual, status=ImportStatus.processing)
        ),
    )
    monkeypatch.setattr(service.repository, "list_rows_for_update", AsyncMock(return_value=[]))

    async def allow_access(**_: object) -> None:
        return None

    monkeypatch.setattr("app.modules.imports.normalization.require_account_access", allow_access)
    with pytest.raises(ImportNormalizeRowsMissingError):
        await service.normalize_batch(
            principal=_principal(), account_id="account-a", batch_id="batch-a"
        )
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_rolls_back_commit_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    session = AsyncMock()
    session.commit.side_effect = RuntimeError("controlled commit failure")
    service = ImportNormalizationService(session)
    batch = SimpleNamespace(
        source=ImportSource.manual,
        status=ImportStatus.processing,
        rows_total=0,
        rows_imported=0,
        rows_skipped=0,
        completed_at=None,
    )
    row = SimpleNamespace(
        status=ImportRowStatus.pending,
        raw_data={"Date": "2026-07-20", "Amount": "1", "Currency": "EUR"},
        normalized_data=None,
        deduplication_key=None,
        validation_errors=None,
        error_message=None,
    )
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=batch))
    monkeypatch.setattr(service.repository, "list_rows_for_update", AsyncMock(return_value=[row]))

    async def allow_access(**_: object) -> None:
        return None

    monkeypatch.setattr("app.modules.imports.normalization.require_account_access", allow_access)
    with pytest.raises(RuntimeError, match="controlled commit failure"):
        await service.normalize_batch(
            principal=_principal(), account_id="account-a", batch_id="batch-a"
        )
    session.rollback.assert_awaited_once()
