from copy import deepcopy
from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import (
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    TransactionClassification,
    TransactionType,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.transactions import TransactionModel
from app.modules.imports.classification import classify_import_row
from app.modules.imports.transaction_posting import (
    ImportPostStateError,
    ImportTransactionPostingWriter,
    TransactionPostingPlan,
    _posting_amount,
    build_transaction_posting_plan,
)


def _batch(
    source: ImportSource = ImportSource.manual,
    *,
    status: ImportStatus = ImportStatus.processing,
) -> ImportBatchModel:
    return cast(
        ImportBatchModel,
        SimpleNamespace(
            id="batch",
            account_id="account",
            source=source,
            status=status,
            rows_total=1,
            rows_imported=0,
            rows_skipped=0,
            completed_at=None,
        ),
    )


def _canonical(
    source: ImportSource = ImportSource.manual,
    *,
    date: str = "2026-07-25",
    amount: str = "10.50",
    source_type: str = "income",
    description: str | None = "Salary",
    external_id: str | None = "provider-1",
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 1,
        "source": source.value,
        "date": date,
        "amount": amount,
        "currency": "EUR",
        "type": source_type,
    }
    if description is not None:
        data["description"] = description
    if external_id is not None:
        data["external_id"] = external_id
    return data


def _row(
    *,
    canonical: dict[str, Any] | None = None,
    source: ImportSource = ImportSource.manual,
    status: ImportRowStatus = ImportRowStatus.pending,
) -> ImportRowModel:
    canonical = canonical or _canonical(source)
    intent = classify_import_row(source=source, normalized_data=canonical).model_dump(mode="json")
    return cast(
        ImportRowModel,
        SimpleNamespace(
            id="row",
            import_batch_id="batch",
            raw_data={"raw": "preserved"},
            normalized_data={
                **deepcopy(canonical),
                "deduplication": {"schema_version": 1, "status": "unique"},
                "posting_intent": intent,
            },
            validation_errors=None,
            deduplication_key="a" * 64,
            status=status,
            error_message=None,
            created_transaction_id=None,
            created_investment_event_id=None,
            created_at=datetime(2026, 7, 25, 8, 0),
        ),
    )


def _session() -> MagicMock:
    session = MagicMock(spec=AsyncSession)
    session.get = AsyncMock()
    return session


def _existing(
    plan: TransactionPostingPlan,
    *,
    transaction_id: str = "transaction",
) -> TransactionModel:
    return TransactionModel(
        id=transaction_id,
        account_id=plan.account_id,
        import_batch_id=plan.import_batch_id,
        date=plan.date,
        booking_date=None,
        amount=plan.amount,
        currency=plan.currency,
        reporting_amount=None,
        reporting_currency=None,
        type=plan.transaction_type,
        classification=plan.transaction_classification,
        description=plan.description,
        note=None,
        counterparty=None,
        external_id=plan.external_id,
        category_id=None,
        archived_at=None,
        deleted_at=None,
        updated_at=datetime(2026, 7, 25, 9, 0),
    )


@pytest.mark.parametrize(
    (
        "source",
        "date_value",
        "amount",
        "source_type",
        "expected_date",
        "expected_type",
        "expected_classification",
    ),
    [
        (
            ImportSource.manual,
            "2026-07-25",
            "10.50",
            "income",
            datetime(2026, 7, 25),
            TransactionType.income,
            TransactionClassification.real_income,
        ),
        (
            ImportSource.raiffeisenbank,
            "2026-07-25",
            "-42.125",
            "expense",
            datetime(2026, 7, 25),
            TransactionType.expense,
            TransactionClassification.real_expense,
        ),
        (
            ImportSource.manual,
            "2026-07-25",
            "-12",
            "internal transfer",
            datetime(2026, 7, 25),
            TransactionType.transfer,
            TransactionClassification.internal_transfer,
        ),
        (
            ImportSource.manual,
            "2026-07-25T12:30:00+02:00",
            "1",
            "income",
            datetime(2026, 7, 25, 10, 30),
            TransactionType.income,
            TransactionClassification.real_income,
        ),
        (
            ImportSource.manual,
            "2026-07-25T12:30:00",
            "1",
            "income",
            datetime(2026, 7, 25, 12, 30),
            TransactionType.income,
            TransactionClassification.real_income,
        ),
        (
            ImportSource.manual,
            "2026-07-25",
            "1.230000",
            "income",
            datetime(2026, 7, 25),
            TransactionType.income,
            TransactionClassification.real_income,
        ),
        (
            ImportSource.manual,
            "2026-07-25",
            "1.23",
            "income",
            datetime(2026, 7, 25),
            TransactionType.income,
            TransactionClassification.real_income,
        ),
        (
            ImportSource.manual,
            "2026-07-25",
            "999999999999.999999",
            "income",
            datetime(2026, 7, 25),
            TransactionType.income,
            TransactionClassification.real_income,
        ),
        (
            ImportSource.manual,
            "2026-07-25",
            "-999999999999.999999",
            "expense",
            datetime(2026, 7, 25),
            TransactionType.expense,
            TransactionClassification.real_expense,
        ),
        (
            ImportSource.manual,
            "2026-07-25T10:00:00.123000",
            "1",
            "income",
            datetime(2026, 7, 25, 10, 0, 0, 123000),
            TransactionType.income,
            TransactionClassification.real_income,
        ),
        (
            ImportSource.manual,
            "2026-07-25T12:00:00.123000+02:00",
            "1",
            "income",
            datetime(2026, 7, 25, 10, 0, 0, 123000),
            TransactionType.income,
            TransactionClassification.real_income,
        ),
    ],
)
def test_build_plan_maps_supported_transactions_with_exact_decimal_and_date(
    source: ImportSource,
    date_value: str,
    amount: str,
    source_type: str,
    expected_date: datetime,
    expected_type: TransactionType,
    expected_classification: TransactionClassification,
) -> None:
    canonical = _canonical(
        source,
        date=date_value,
        amount=amount,
        source_type=source_type,
    )
    plan = build_transaction_posting_plan(
        account_id="account",
        batch=_batch(source),
        row=_row(canonical=canonical, source=source),
    )

    assert plan.date == expected_date
    assert plan.amount == Decimal(amount)
    assert isinstance(plan.amount, Decimal)
    assert plan.transaction_type is expected_type
    assert plan.transaction_classification is expected_classification
    assert plan.description == "Salary"
    assert plan.external_id == "provider-1"
    with pytest.raises(FrozenInstanceError):
        plan.amount = Decimal("1")  # type: ignore[misc]


@pytest.mark.parametrize("value", ["0", "1", "1.23", "1.230000"])
def test_money_representability_accepts_general_exact_values(value: str) -> None:
    amount = Decimal(value)
    assert _posting_amount(amount) is amount


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_money_representability_rejects_non_finite_values(value: str) -> None:
    with pytest.raises(ImportPostStateError):
        _posting_amount(Decimal(value))


@pytest.mark.asyncio
async def test_writer_creates_exact_model_and_preserves_row_and_batch_data() -> None:
    session = _session()
    batch = _batch()
    row = _row()
    normalized_object = row.normalized_data
    normalized_snapshot = deepcopy(row.normalized_data)
    raw_object = row.raw_data
    key = row.deduplication_key
    created_at = row.created_at
    batch_snapshot = (
        batch.status,
        batch.rows_total,
        batch.rows_imported,
        batch.rows_skipped,
        batch.completed_at,
    )

    transaction = await ImportTransactionPostingWriter(session).post_row(
        account_id="account",
        batch=batch,
        row=row,
    )

    session.add.assert_called_once_with(transaction)
    assert transaction.account_id == "account"
    assert transaction.import_batch_id == "batch"
    assert transaction.date == datetime(2026, 7, 25)
    assert transaction.amount == Decimal("10.50")
    assert transaction.currency == "EUR"
    assert transaction.type is TransactionType.income
    assert transaction.classification is TransactionClassification.real_income
    assert transaction.description == "Salary"
    assert transaction.external_id == "provider-1"
    assert transaction.booking_date is None
    assert transaction.reporting_amount is None
    assert transaction.reporting_currency is None
    assert transaction.note is None
    assert transaction.counterparty is None
    assert transaction.category_id is None
    assert transaction.archived_at is None
    assert transaction.deleted_at is None
    assert row.status is ImportRowStatus.imported
    assert row.created_transaction_id == transaction.id
    assert row.created_investment_event_id is None
    assert row.validation_errors is None
    assert row.error_message is None
    assert row.normalized_data is normalized_object
    assert row.normalized_data == normalized_snapshot
    assert row.raw_data is raw_object
    assert row.deduplication_key == key
    assert row.created_at == created_at
    assert (
        batch.status,
        batch.rows_total,
        batch.rows_imported,
        batch.rows_skipped,
        batch.completed_at,
    ) == batch_snapshot
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", "0.1234567"),
        ("amount", "-0.1234567"),
        ("amount", "1000000000000"),
        ("amount", "-1000000000000"),
        ("amount", "1E+100"),
        ("date", "2026-07-25T10:00:00.123456"),
        ("date", "2026-07-25T10:00:00.000001+00:00"),
    ],
    ids=[
        "amount-seven-decimals",
        "amount-negative-seven-decimals",
        "amount-positive-overflow",
        "amount-negative-overflow",
        "amount-large-exponent",
        "timestamp-sub-millisecond-naive",
        "timestamp-sub-millisecond-aware",
    ],
)
async def test_unrepresentable_plan_fails_before_any_mutation(
    field: str,
    value: str,
) -> None:
    canonical = _canonical()
    canonical[field] = value
    row = _row(canonical=canonical)
    batch = _batch()
    session = _session()
    normalized_object = row.normalized_data
    normalized_snapshot = deepcopy(row.normalized_data)
    raw_object = row.raw_data
    row_snapshot = (
        row.status,
        row.created_transaction_id,
        row.created_investment_event_id,
        row.deduplication_key,
        row.validation_errors,
        row.error_message,
    )
    batch_snapshot = (
        batch.status,
        batch.rows_total,
        batch.rows_imported,
        batch.rows_skipped,
        batch.completed_at,
    )

    with pytest.raises(ImportPostStateError) as exc_info:
        await ImportTransactionPostingWriter(session).post_row(
            account_id="account",
            batch=batch,
            row=row,
        )

    assert exc_info.value.code == "import_post_state_invalid"
    assert exc_info.value.status_code == 409
    assert row.normalized_data is normalized_object
    assert row.normalized_data == normalized_snapshot
    assert row.raw_data is raw_object
    assert (
        row.status,
        row.created_transaction_id,
        row.created_investment_event_id,
        row.deduplication_key,
        row.validation_errors,
        row.error_message,
    ) == row_snapshot
    assert (
        batch.status,
        batch.rows_total,
        batch.rows_imported,
        batch.rows_skipped,
        batch.completed_at,
    ) == batch_snapshot
    session.add.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_exact_replay_accepts_money_and_timestamp_boundary_values() -> None:
    canonical = _canonical(
        date="2026-07-25T12:00:00.123000+02:00",
        amount="999999999999.999999",
    )
    batch = _batch()
    row = _row(canonical=canonical, status=ImportRowStatus.imported)
    row.created_transaction_id = "transaction"
    plan = build_transaction_posting_plan(account_id="account", batch=batch, row=row)
    existing = _existing(plan)
    session = _session()
    session.get.return_value = existing

    returned = await ImportTransactionPostingWriter(session).post_row(
        account_id="account",
        batch=batch,
        row=row,
    )

    assert returned is existing
    assert returned.amount == Decimal("999999999999.999999")
    assert returned.date == datetime(2026, 7, 25, 10, 0, 0, 123000)
    session.get.assert_awaited_once_with(TransactionModel, "transaction")
    session.add.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


def _invalid_boundary(case: str) -> tuple[str, ImportBatchModel, ImportRowModel]:
    account_id = "account"
    batch = _batch()
    row = _row()
    assert row.normalized_data is not None
    data = row.normalized_data
    if case == "account-mismatch":
        account_id = "foreign"
    elif case == "batch-status":
        batch.status = ImportStatus.completed
    elif case == "row-batch-mismatch":
        row.import_batch_id = "other"
    elif case in {"duplicate", "skipped", "failed", "needs-review"}:
        row.status = ImportRowStatus(case.replace("-", "_"))
    elif case == "marker-missing":
        data.pop("deduplication")
    elif case == "marker-malformed":
        data["deduplication"] = "unique"
    elif case == "marker-version":
        data["deduplication"] = {"schema_version": 2, "status": "unique"}
    elif case == "marker-extra":
        data["deduplication"] = {
            "schema_version": 1,
            "status": "unique",
            "extra": True,
        }
    elif case == "key-missing":
        row.deduplication_key = None
    elif case == "key-empty":
        row.deduplication_key = ""
    elif case == "intent-missing":
        data.pop("posting_intent")
    elif case == "intent-malformed":
        data["posting_intent"] = "transaction"
    elif case == "intent-mismatch":
        data["posting_intent"]["amount"] = "999"
    elif case == "intent-review":
        data["posting_intent"]["target"] = "needs_review"
    elif case == "intent-investment":
        data["posting_intent"]["target"] = "investment_event"
    elif case == "source-mismatch":
        data["source"] = "raiffeisenbank"
    elif case == "noncanonical-date":
        data["date"] = "2026-07-25 12:30:00"
        data["posting_intent"] = classify_import_row(
            source=batch.source,
            normalized_data={
                key: value
                for key, value in data.items()
                if key not in {"deduplication", "posting_intent"}
            },
        ).model_dump(mode="json")
    elif case == "created-transaction":
        row.created_transaction_id = "transaction"
    elif case == "created-investment":
        row.created_investment_event_id = "investment"
    elif case == "validation-errors":
        row.validation_errors = [{"code": "invalid"}]
    elif case == "error-message":
        row.error_message = "invalid"
    elif case == "description-type":
        data["description"] = 1
        data["posting_intent"] = classify_import_row(
            source=batch.source,
            normalized_data={
                key: value
                for key, value in data.items()
                if key not in {"deduplication", "posting_intent"}
            },
        ).model_dump(mode="json")
    elif case == "external-id-oversized":
        data["external_id"] = "x" * 4097
        data["posting_intent"] = classify_import_row(
            source=batch.source,
            normalized_data={
                key: value
                for key, value in data.items()
                if key not in {"deduplication", "posting_intent"}
            },
        ).model_dump(mode="json")
    elif case == "imported-without-id":
        row.status = ImportRowStatus.imported
    elif case == "imported-with-investment-id":
        row.status = ImportRowStatus.imported
        row.created_transaction_id = "transaction"
        row.created_investment_event_id = "investment"
    else:
        raise AssertionError(case)
    return account_id, batch, row


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "account-mismatch",
        "batch-status",
        "row-batch-mismatch",
        "duplicate",
        "skipped",
        "failed",
        "needs-review",
        "marker-missing",
        "marker-malformed",
        "marker-version",
        "marker-extra",
        "key-missing",
        "key-empty",
        "intent-missing",
        "intent-malformed",
        "intent-mismatch",
        "intent-review",
        "intent-investment",
        "source-mismatch",
        "noncanonical-date",
        "created-transaction",
        "created-investment",
        "validation-errors",
        "error-message",
        "description-type",
        "external-id-oversized",
        "imported-without-id",
        "imported-with-investment-id",
    ],
)
async def test_writer_rejects_invalid_boundary_without_mutation(case: str) -> None:
    account_id, batch, row = _invalid_boundary(case)
    session = _session()
    normalized = deepcopy(row.normalized_data)

    with pytest.raises(ImportPostStateError) as exc_info:
        await ImportTransactionPostingWriter(session).post_row(
            account_id=account_id,
            batch=batch,
            row=row,
        )

    assert exc_info.value.code == "import_post_state_invalid"
    assert exc_info.value.status_code == 409
    assert row.normalized_data == normalized
    session.add.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


@pytest.mark.asyncio
async def test_exact_imported_replay_returns_existing_without_add_or_mutation() -> None:
    batch = _batch()
    row = _row(status=ImportRowStatus.imported)
    row.created_transaction_id = "transaction"
    plan = build_transaction_posting_plan(account_id="account", batch=batch, row=row)
    existing = _existing(plan)
    session = _session()
    session.get.return_value = existing
    normalized_object = row.normalized_data
    normalized_snapshot = deepcopy(row.normalized_data)

    returned = await ImportTransactionPostingWriter(session).post_row(
        account_id="account",
        batch=batch,
        row=row,
    )

    assert returned is existing
    session.get.assert_awaited_once_with(TransactionModel, "transaction")
    session.add.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
    assert row.status is ImportRowStatus.imported
    assert row.created_transaction_id == "transaction"
    assert row.normalized_data is normalized_object
    assert row.normalized_data == normalized_snapshot


@pytest.mark.asyncio
async def test_imported_replay_rejects_missing_transaction() -> None:
    row = _row(status=ImportRowStatus.imported)
    row.created_transaction_id = "missing"
    session = _session()
    session.get.return_value = None

    with pytest.raises(ImportPostStateError):
        await ImportTransactionPostingWriter(session).post_row(
            account_id="account",
            batch=_batch(),
            row=row,
        )

    session.add.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()


def _mismatch(transaction: TransactionModel, field: str) -> None:
    replacements: dict[str, Any] = {
        "id": "other",
        "account_id": "other",
        "import_batch_id": "other",
        "date": datetime(2026, 7, 26),
        "amount": Decimal("999"),
        "currency": "USD",
        "type": TransactionType.expense,
        "classification": TransactionClassification.real_expense,
        "description": "other",
        "external_id": "other",
        "booking_date": datetime(2026, 7, 25),
        "reporting_amount": Decimal("1"),
        "reporting_currency": "EUR",
        "note": "other",
        "counterparty": "other",
        "category_id": "category",
        "archived_at": datetime(2026, 7, 25),
        "deleted_at": datetime(2026, 7, 25),
    }
    setattr(transaction, field, replacements[field])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field",
    [
        "id",
        "account_id",
        "import_batch_id",
        "date",
        "amount",
        "currency",
        "type",
        "classification",
        "description",
        "external_id",
        "booking_date",
        "reporting_amount",
        "reporting_currency",
        "note",
        "counterparty",
        "category_id",
        "archived_at",
        "deleted_at",
    ],
)
async def test_imported_replay_rejects_every_canonical_field_mismatch(field: str) -> None:
    batch = _batch()
    row = _row(status=ImportRowStatus.imported)
    row.created_transaction_id = "transaction"
    existing = _existing(build_transaction_posting_plan(account_id="account", batch=batch, row=row))
    _mismatch(existing, field)
    session = _session()
    session.get.return_value = existing

    with pytest.raises(ImportPostStateError):
        await ImportTransactionPostingWriter(session).post_row(
            account_id="account",
            batch=batch,
            row=row,
        )

    session.add.assert_not_called()
    session.commit.assert_not_called()
    session.rollback.assert_not_called()
