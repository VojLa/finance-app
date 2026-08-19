"""Internal canonical transaction-row posting with caller-owned transactions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_jobs import BackgroundJobModel, ImportJobBatchModel
from app.db.models.common import MONEY, TIMESTAMP
from app.db.models.enums import (
    BackgroundJobKind,
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    TransactionClassification,
    TransactionType,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.prices import ExchangeRateModel
from app.db.models.transactions import TransactionModel, TransactionReportingEvidenceModel
from app.modules.canonical_state import (
    CanonicalChangeKind,
    CanonicalStateError,
    CanonicalStateService,
)
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
from app.modules.imports.raiffeisenbank_reporting_fx import (
    REPORTING_FX_CALCULATION_VERSION,
    calculate_reporting_amount,
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
    counterparty: str | None
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
        counterparty=bounded_optional_text(canonical.get("counterparty")),
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
        and transaction.counterparty == plan.counterparty
        and transaction.external_id == plan.external_id
        and transaction.booking_date is None
        and transaction.note is None
        and transaction.category_id is None
        and transaction.archived_at is None
        and transaction.deleted_at is None
    )


class ImportTransactionPostingWriter:
    def __init__(
        self,
        session: AsyncSession,
        *,
        canonical_state: CanonicalStateService | None = None,
    ) -> None:
        self.session = session
        self.canonical_state = canonical_state or CanonicalStateService(session)

    async def _reporting_evidence_matches(
        self,
        *,
        transaction: TransactionModel,
        plan: TransactionPostingPlan,
    ) -> bool:
        """Accept only the durable reporting projection introduced after posting.

        Canonical transaction replay remains exact. A Raiffeisenbank workflow
        may acquire direct reporting-FX evidence before its final posting
        replay, however. That projection is acceptable only when its complete
        evidence and exchange-rate lineage still prove both populated fields.
        """

        if transaction.reporting_amount is None and transaction.reporting_currency is None:
            return True
        if transaction.reporting_amount is None or transaction.reporting_currency is None:
            return False
        evidence = await self.session.get(TransactionReportingEvidenceModel, transaction.id)
        if evidence is None or (
            evidence.transaction_id != transaction.id
            or evidence.source_amount != plan.amount
            or evidence.source_currency != plan.currency
            or evidence.source_event_time != plan.date
            or evidence.reporting_amount != transaction.reporting_amount
            or evidence.reporting_currency != transaction.reporting_currency
            or evidence.calculation_version != REPORTING_FX_CALCULATION_VERSION
            or not isinstance(evidence.background_job_id, str)
            or not evidence.background_job_id
        ):
            return False
        rate = await self.session.get(ExchangeRateModel, evidence.exchange_rate_id)
        if rate is None or (
            rate.id != evidence.exchange_rate_id
            or rate.from_currency != evidence.source_currency
            or rate.to_currency != evidence.reporting_currency
            or rate.date > evidence.source_event_time
        ):
            return False
        membership = await self.session.scalar(
            select(ImportJobBatchModel.job_id)
            .join(
                BackgroundJobModel,
                and_(
                    BackgroundJobModel.id == ImportJobBatchModel.job_id,
                    BackgroundJobModel.user_id == ImportJobBatchModel.user_id,
                    BackgroundJobModel.account_id == ImportJobBatchModel.account_id,
                ),
            )
            .join(
                ImportBatchModel,
                and_(
                    ImportBatchModel.id == ImportJobBatchModel.batch_id,
                    ImportBatchModel.user_id == ImportJobBatchModel.user_id,
                    ImportBatchModel.account_id == ImportJobBatchModel.account_id,
                ),
            )
            .where(
                ImportJobBatchModel.job_id == evidence.background_job_id,
                ImportJobBatchModel.batch_id == plan.import_batch_id,
                ImportJobBatchModel.account_id == plan.account_id,
                BackgroundJobModel.kind == BackgroundJobKind.import_workflow,
                ImportBatchModel.source == ImportSource.raiffeisenbank,
            )
        )
        if membership != evidence.background_job_id:
            return False
        try:
            return calculate_reporting_amount(plan.amount, rate.rate) == evidence.reporting_amount
        except (TypeError, ValueError):
            return False

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
            if (
                existing is None
                or not _transaction_matches(
                    existing,
                    transaction_id=row.created_transaction_id,
                    plan=plan,
                )
                or not await self._reporting_evidence_matches(transaction=existing, plan=plan)
            ):
                raise ImportPostStateError()
            try:
                await self.canonical_state.record(
                    account_id=plan.account_id,
                    kind=CanonicalChangeKind.transaction,
                    entity_id=existing.id,
                    financial_timestamp=existing.date,
                    created_at=existing.created_at,
                    replay=True,
                )
            except CanonicalStateError as exc:
                raise ImportPostStateError() from exc
            return existing

        updated_at = datetime.now(UTC).replace(tzinfo=None)
        precision = TIMESTAMP.precision
        if precision is None or not 0 <= precision <= 6:
            raise ImportPostStateError()
        unit = 10 ** (6 - precision)
        updated_at = updated_at.replace(
            microsecond=updated_at.microsecond - (updated_at.microsecond % unit)
        )
        transaction_id = str(uuid4())
        try:
            await self.canonical_state.record(
                account_id=plan.account_id,
                kind=CanonicalChangeKind.transaction,
                entity_id=transaction_id,
                financial_timestamp=plan.date,
                created_at=updated_at,
                replay=False,
            )
        except CanonicalStateError as exc:
            raise ImportPostStateError() from exc
        transaction = TransactionModel(
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
            counterparty=plan.counterparty,
            external_id=plan.external_id,
            category_id=None,
            archived_at=None,
            deleted_at=None,
            created_at=updated_at,
            updated_at=updated_at,
        )
        self.session.add(transaction)
        row.status = ImportRowStatus.imported
        row.created_transaction_id = transaction.id
        row.created_investment_event_id = None
        row.validation_errors = None
        row.error_message = None
        return transaction
