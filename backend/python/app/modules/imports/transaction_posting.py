"""Internal canonical transaction-row posting with caller-owned transactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.common import MONEY, TIMESTAMP
from app.db.models.enums import (
    ImportRowStatus,
    ImportStatus,
    TransactionClassification,
    TransactionType,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.transactions import TransactionModel
from app.modules.imports.classification import (
    PostingIntentTarget,
    TransactionPostingIntent,
    classify_import_row,
)
from app.modules.imports.posting_common import (
    DEDUPLICATION_METADATA_KEY,
    POSTING_INTENT_METADATA_KEY,
    UNIQUE_DEDUPLICATION_MARKER,
    ImportPostStateError,
    bounded_optional_text,
    copied_canonical_payload,
    exact_naive_timestamp,
    exact_numeric,
)


@dataclass(frozen=True, slots=True)
class TransactionPostingPlan:
    account_id: str
    import_batch_id: str
    source_row_id: str
    date: datetime
    amount: Decimal
    currency: str
    transaction_type: TransactionType
    transaction_classification: TransactionClassification
    description: str | None
    external_id: str | None


def _posting_amount(value: Decimal) -> Decimal:
    """Backward-compatible 5G-A boundary backed by the shared numeric helper."""
    return exact_numeric(value, MONEY)


def build_transaction_posting_plan(
    *,
    account_id: str,
    batch: ImportBatchModel,
    row: ImportRowModel,
) -> TransactionPostingPlan:
    if (
        batch.account_id != account_id
        or batch.status is not ImportStatus.processing
        or row.import_batch_id != batch.id
        or row.status not in {ImportRowStatus.pending, ImportRowStatus.imported}
        or not isinstance(row.normalized_data, dict)
        or row.normalized_data.get(DEDUPLICATION_METADATA_KEY) != UNIQUE_DEDUPLICATION_MARKER
        or not isinstance(row.deduplication_key, str)
        or not row.deduplication_key
        or row.validation_errors is not None
        or row.error_message is not None
        or row.created_investment_event_id is not None
    ):
        raise ImportPostStateError()
    if row.status is ImportRowStatus.pending and row.created_transaction_id is not None:
        raise ImportPostStateError()
    if row.status is ImportRowStatus.imported and (
        not isinstance(row.created_transaction_id, str) or not row.created_transaction_id
    ):
        raise ImportPostStateError()

    stored = row.normalized_data.get(POSTING_INTENT_METADATA_KEY)
    if not isinstance(stored, dict):
        raise ImportPostStateError()
    canonical = copied_canonical_payload(row.normalized_data)
    fresh = classify_import_row(
        source=batch.source,
        normalized_data=canonical,
    ).model_dump(mode="json")
    if fresh != stored or fresh.get("target") != PostingIntentTarget.transaction.value:
        raise ImportPostStateError()
    try:
        intent = TransactionPostingIntent.model_validate(stored)
    except ValidationError as exc:
        raise ImportPostStateError() from exc

    return TransactionPostingPlan(
        account_id=batch.account_id,
        import_batch_id=batch.id,
        source_row_id=row.id,
        date=exact_naive_timestamp(intent.date, TIMESTAMP),
        amount=_posting_amount(intent.amount),
        currency=intent.currency,
        transaction_type=intent.transaction_type,
        transaction_classification=intent.transaction_classification,
        description=bounded_optional_text(canonical.get("description")),
        external_id=bounded_optional_text(canonical.get("external_id")),
    )


def _transaction_matches(
    transaction: TransactionModel,
    *,
    transaction_id: str,
    plan: TransactionPostingPlan,
) -> bool:
    return (
        transaction.id == transaction_id
        and transaction.account_id == plan.account_id
        and transaction.import_batch_id == plan.import_batch_id
        and transaction.date == plan.date
        and transaction.amount == plan.amount
        and transaction.currency == plan.currency
        and transaction.type is plan.transaction_type
        and transaction.classification is plan.transaction_classification
        and transaction.description == plan.description
        and transaction.external_id == plan.external_id
        and transaction.booking_date is None
        and transaction.reporting_amount is None
        and transaction.reporting_currency is None
        and transaction.note is None
        and transaction.counterparty is None
        and transaction.category_id is None
        and transaction.archived_at is None
        and transaction.deleted_at is None
    )


class ImportTransactionPostingWriter:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def post_row(
        self,
        *,
        account_id: str,
        batch: ImportBatchModel,
        row: ImportRowModel,
    ) -> TransactionModel:
        plan = build_transaction_posting_plan(account_id=account_id, batch=batch, row=row)
        if row.status is ImportRowStatus.imported:
            assert row.created_transaction_id is not None
            existing = await self.session.get(TransactionModel, row.created_transaction_id)
            if existing is None or not _transaction_matches(
                existing,
                transaction_id=row.created_transaction_id,
                plan=plan,
            ):
                raise ImportPostStateError()
            return existing

        transaction = TransactionModel(
            id=str(uuid4()),
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
            updated_at=datetime.now(UTC).replace(tzinfo=None),
        )
        self.session.add(transaction)
        row.status = ImportRowStatus.imported
        row.created_transaction_id = transaction.id
        row.created_investment_event_id = None
        row.validation_errors = None
        row.error_message = None
        return transaction
