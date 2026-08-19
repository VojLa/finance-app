"""One fail-closed operational read boundary for canonical cash rows.

Import posting is intentionally ahead of publication.  Operational readers must
therefore not infer that a canonical imported row is user-visible merely because
it exists in ``Transaction``.  This module is the single query/pure projection
used by the transaction list, budget progress, and operational dashboard.

Snapshot and import-worker repositories deliberately do not use this boundary:
they consume canonical evidence while a job is still being prepared.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from sqlalchemy import case, exists, func, literal, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.db.models.background_jobs import (
    BackgroundJobModel,
    ImportJobAffectedAccountModel,
    ImportJobBatchModel,
)
from app.db.models.enums import (
    TRANSACTION_TYPE_DB,
    BackgroundJobStatus,
    TransactionClassification,
    TransactionType,
)
from app.db.models.transactions import (
    TransactionModel,
    TransactionPairModel,
    TransactionReportingEvidenceModel,
)

_REPORTING_CURRENCY = "CZK"


@dataclass(frozen=True, slots=True)
class OperationalTransaction:
    """A transaction together with only publication-authorized interpretation."""

    transaction: TransactionModel
    published_pair_classification: TransactionClassification | None
    reporting_amount: Decimal | None
    reporting_currency: str | None

    @property
    def effective_classification(self) -> TransactionClassification:
        if self.published_pair_classification is not None:
            return self.published_pair_classification
        if self.transaction.classification is not None:
            return self.transaction.classification
        return _classification_for_type(self.transaction.type)

    @property
    def effective_type(self) -> TransactionType:
        return _type_for_classification(self.effective_classification)


def _classification_for_type(value: TransactionType) -> TransactionClassification:
    return {
        TransactionType.income: TransactionClassification.real_income,
        TransactionType.expense: TransactionClassification.real_expense,
        TransactionType.transfer: TransactionClassification.internal_transfer,
    }[value]


def _type_for_classification(value: TransactionClassification) -> TransactionType:
    if value is TransactionClassification.real_income:
        return TransactionType.income
    if value is TransactionClassification.real_expense:
        return TransactionType.expense
    return TransactionType.transfer


def _manifest_exists(transaction: type[TransactionModel] = TransactionModel) -> ColumnElement[bool]:
    return exists(
        select(ImportJobBatchModel.job_id).where(
            ImportJobBatchModel.batch_id == transaction.import_batch_id
        )
    )


def _incomplete_manifest_exists(
    transaction: type[TransactionModel] = TransactionModel,
) -> ColumnElement[bool]:
    return exists(
        select(ImportJobBatchModel.job_id)
        .join(BackgroundJobModel, BackgroundJobModel.id == ImportJobBatchModel.job_id)
        .where(
            ImportJobBatchModel.batch_id == transaction.import_batch_id,
            BackgroundJobModel.status != BackgroundJobStatus.completed,
        )
    )


def _published_reporting_amount(
    transaction: type[TransactionModel] = TransactionModel,
) -> ColumnElement[Decimal | None]:
    return cast(
        ColumnElement[Decimal | None],
        select(TransactionReportingEvidenceModel.reporting_amount)
        .join(
            BackgroundJobModel,
            BackgroundJobModel.id == TransactionReportingEvidenceModel.background_job_id,
        )
        .where(
            TransactionReportingEvidenceModel.transaction_id == transaction.id,
            TransactionReportingEvidenceModel.source_amount == transaction.amount,
            TransactionReportingEvidenceModel.source_currency == transaction.currency,
            TransactionReportingEvidenceModel.source_event_time == transaction.date,
            TransactionReportingEvidenceModel.reporting_currency == _REPORTING_CURRENCY,
            TransactionReportingEvidenceModel.published_at.is_not(None),
            BackgroundJobModel.status == BackgroundJobStatus.completed,
            exists(
                select(ImportJobBatchModel.job_id)
                .where(
                    ImportJobBatchModel.job_id
                    == TransactionReportingEvidenceModel.background_job_id,
                    ImportJobBatchModel.batch_id == transaction.import_batch_id,
                    ImportJobBatchModel.account_id == transaction.account_id,
                )
                .correlate(transaction, TransactionReportingEvidenceModel)
            ),
        )
        .order_by(TransactionReportingEvidenceModel.transaction_id)
        .limit(1)
        .scalar_subquery(),
    )


def _published_pair_classification(
    transaction: type[TransactionModel] = TransactionModel,
) -> ColumnElement[TransactionClassification | None]:
    raw_pair_count = _published_pair_count(transaction)
    valid_pair_count = _provenance_valid_published_pair_count(transaction)
    return (
        select(TransactionPairModel.classification)
        .join(BackgroundJobModel, BackgroundJobModel.id == TransactionPairModel.background_job_id)
        .join(
            ImportJobAffectedAccountModel,
            (ImportJobAffectedAccountModel.job_id == BackgroundJobModel.id)
            & (ImportJobAffectedAccountModel.user_id == BackgroundJobModel.user_id)
            & (ImportJobAffectedAccountModel.account_id == transaction.account_id),
        )
        .where(
            or_(
                TransactionPairModel.from_transaction_id == transaction.id,
                TransactionPairModel.to_transaction_id == transaction.id,
            ),
            TransactionPairModel.published_at.is_not(None),
            BackgroundJobModel.status == BackgroundJobStatus.completed,
            raw_pair_count == 1,
            valid_pair_count == 1,
        )
        .order_by(TransactionPairModel.id)
        .limit(1)
        .scalar_subquery()
    )


def _published_pair_count(
    transaction: type[TransactionModel] = TransactionModel,
) -> ColumnElement[int]:
    """Count every raw published pair touching one transaction.

    ``TransactionPair`` has independent unique constraints for its two legs, so
    malformed data can still place one transaction in two distinct pairs.  The
    operational boundary compares this raw count with the provenance-valid
    count. A missing affected-account manifest is therefore fail-closed rather
    than an ignored pair which would reveal the stale income/expense type.
    """

    pair = aliased(TransactionPairModel)
    return (
        select(func.count(pair.id))
        .select_from(pair)
        .where(
            or_(
                pair.from_transaction_id == transaction.id,
                pair.to_transaction_id == transaction.id,
            ),
            pair.published_at.is_not(None),
        )
        .correlate(transaction)
        .scalar_subquery()
    )


def _provenance_valid_published_pair_count(
    transaction: type[TransactionModel] = TransactionModel,
) -> ColumnElement[int]:
    pair = aliased(TransactionPairModel)
    job = aliased(BackgroundJobModel)
    affected_account = aliased(ImportJobAffectedAccountModel)
    return (
        select(func.count(pair.id))
        .select_from(pair)
        .join(job, job.id == pair.background_job_id)
        .join(
            affected_account,
            (affected_account.job_id == job.id)
            & (affected_account.user_id == job.user_id)
            & (affected_account.account_id == transaction.account_id),
        )
        .where(
            or_(
                pair.from_transaction_id == transaction.id,
                pair.to_transaction_id == transaction.id,
            ),
            pair.published_at.is_not(None),
            job.status == BackgroundJobStatus.completed,
        )
        .correlate(transaction)
        .scalar_subquery()
    )


def operational_visibility_predicate(
    transaction: type[TransactionModel] = TransactionModel,
) -> ColumnElement[bool]:
    """Return the shared visibility predicate.

    Import rows with no durable manifest remain explicitly legacy-visible.  A
    manifested imported row is invisible until every manifest job is completed;
    a foreign manifested row additionally needs exact, published, direct CZK
    reporting evidence whose own job is completed.  The latter never falls back
    to mutable denormalized ``Transaction.reporting*`` fields.
    """

    manifested = _manifest_exists(transaction)
    job_bound = transaction.import_batch_id.is_not(None) & manifested
    foreign_ready = _published_reporting_amount(transaction).is_not(None)
    raw_published_pair_count = _published_pair_count(transaction)
    valid_published_pair_count = _provenance_valid_published_pair_count(transaction)
    valid_pair_state = (raw_published_pair_count == valid_published_pair_count) & (
        raw_published_pair_count <= 1
    )
    return valid_pair_state & (
        (~job_bound)
        | (
            (~_incomplete_manifest_exists(transaction))
            & ((transaction.currency == _REPORTING_CURRENCY) | foreign_ready)
        )
    )


def operational_effective_type_expression(
    transaction: type[TransactionModel] = TransactionModel,
) -> ColumnElement[TransactionType]:
    pair_classification = _published_pair_classification(transaction)
    return case(
        (
            pair_classification == TransactionClassification.real_income,
            literal(TransactionType.income, type_=TRANSACTION_TYPE_DB),
        ),
        (
            pair_classification == TransactionClassification.real_expense,
            literal(TransactionType.expense, type_=TRANSACTION_TYPE_DB),
        ),
        (
            pair_classification.is_not(None),
            literal(TransactionType.transfer, type_=TRANSACTION_TYPE_DB),
        ),
        else_=transaction.type,
    )


def operational_projection_columns(
    transaction: type[TransactionModel] = TransactionModel,
) -> tuple[
    ColumnElement[TransactionClassification | None],
    ColumnElement[Decimal | None],
    ColumnElement[str | None],
]:
    """Columns needed to build :class:`OperationalTransaction` from a SQL row."""

    manifested = _manifest_exists(transaction)
    pair_classification = _published_pair_classification(transaction)
    published_reporting_amount = _published_reporting_amount(transaction)
    return (
        pair_classification.label("operational_published_pair_classification"),
        case(
            (manifested, published_reporting_amount),
            else_=transaction.reporting_amount,
        ).label("operational_reporting_amount"),
        case(
            (manifested, literal(_REPORTING_CURRENCY)),
            else_=transaction.reporting_currency,
        ).label("operational_reporting_currency"),
    )


def operational_transaction_from_values(
    transaction: TransactionModel,
    published_pair_classification: TransactionClassification | None,
    reporting_amount: Decimal | None,
    reporting_currency: str | None,
) -> OperationalTransaction:
    return OperationalTransaction(
        transaction=transaction,
        published_pair_classification=published_pair_classification,
        reporting_amount=reporting_amount,
        reporting_currency=reporting_currency,
    )


__all__ = [
    "OperationalTransaction",
    "operational_effective_type_expression",
    "operational_projection_columns",
    "operational_transaction_from_values",
    "operational_visibility_predicate",
]
