"""PostgreSQL boundary for direct Raiffeisenbank reporting FX evidence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_jobs import BackgroundJobModel, ImportJobBatchModel
from app.db.models.enums import BackgroundJobKind, ExchangeRateSource, ImportRowStatus
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.prices import ExchangeRateModel
from app.db.models.transactions import TransactionModel, TransactionReportingEvidenceModel
from app.modules.market_data.writer_repository import advisory_lock_id


def reporting_fx_job_lock_scope(job_id: str) -> str:
    return "\0".join(("raiffeisenbank:reporting-fx", job_id))


def reporting_fx_rate_lock_scope(
    *,
    from_currency: str,
    to_currency: str,
    effective_at: datetime,
    source: ExchangeRateSource,
) -> str:
    return "\0".join(
        (
            "raiffeisenbank:reporting-fx-rate",
            from_currency,
            to_currency,
            effective_at.isoformat(timespec="milliseconds"),
            source.value,
        )
    )


class RaiffeisenbankReportingFxRepository:
    """All methods are caller-transaction-bound and never commit."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_transaction_repeatable_read_only(self) -> None:
        await self.session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )

    async def set_transaction_serializable(self) -> None:
        await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))

    async def acquire_locks(self, scopes: tuple[str, ...]) -> None:
        for scope in scopes:
            await self.session.execute(select(func.pg_advisory_xact_lock(advisory_lock_id(scope))))

    async def load_job(self, *, job_id: str, user_id: str) -> BackgroundJobModel | None:
        return await self.session.scalar(
            select(BackgroundJobModel)
            .where(
                BackgroundJobModel.id == job_id,
                BackgroundJobModel.user_id == user_id,
                BackgroundJobModel.kind == BackgroundJobKind.import_workflow,
            )
            .execution_options(populate_existing=True)
        )

    async def load_manifested_batches(
        self,
        *,
        job_id: str,
        user_id: str,
    ) -> tuple[tuple[ImportJobBatchModel, ImportBatchModel], ...]:
        result = await self.session.execute(
            select(ImportJobBatchModel, ImportBatchModel)
            .join(
                ImportBatchModel,
                ImportBatchModel.id == ImportJobBatchModel.batch_id,
            )
            .where(
                ImportJobBatchModel.job_id == job_id,
                ImportJobBatchModel.user_id == user_id,
            )
            .order_by(ImportJobBatchModel.batch_id)
            .execution_options(populate_existing=True)
        )
        return tuple(result.tuples())

    async def load_manifested_transactions(
        self,
        *,
        batch_ids: tuple[str, ...],
        for_update: bool,
    ) -> tuple[TransactionModel, ...]:
        statement = (
            select(TransactionModel)
            .where(TransactionModel.import_batch_id.in_(batch_ids))
            .order_by(TransactionModel.id)
            .execution_options(populate_existing=True)
        )
        if for_update:
            statement = statement.with_for_update()
        return tuple(await self.session.scalars(statement))

    async def load_imported_transaction_links(
        self,
        *,
        batch_ids: tuple[str, ...],
    ) -> tuple[tuple[str, str, str | None], ...]:
        result = await self.session.execute(
            select(
                ImportRowModel.id,
                ImportRowModel.import_batch_id,
                ImportRowModel.created_transaction_id,
            )
            .where(
                ImportRowModel.import_batch_id.in_(batch_ids),
                ImportRowModel.status == ImportRowStatus.imported,
            )
            .order_by(ImportRowModel.import_batch_id, ImportRowModel.id)
            .execution_options(populate_existing=True)
        )
        return tuple(result.tuples())

    async def load_exchange_rate(
        self,
        *,
        from_currency: str,
        to_currency: str,
        effective_at: datetime,
        source: ExchangeRateSource,
    ) -> ExchangeRateModel | None:
        return await self.session.scalar(
            select(ExchangeRateModel)
            .where(
                ExchangeRateModel.from_currency == from_currency,
                ExchangeRateModel.to_currency == to_currency,
                ExchangeRateModel.date == effective_at,
                ExchangeRateModel.source == source,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_exchange_rate_by_id(self, rate_id: str) -> ExchangeRateModel | None:
        return await self.session.scalar(
            select(ExchangeRateModel)
            .where(ExchangeRateModel.id == rate_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_reporting_evidence(
        self,
        transaction_id: str,
    ) -> TransactionReportingEvidenceModel | None:
        return await self.session.scalar(
            select(TransactionReportingEvidenceModel)
            .where(TransactionReportingEvidenceModel.transaction_id == transaction_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_reporting_evidence_bundle(
        self,
        *,
        transaction_ids: tuple[str, ...],
    ) -> tuple[tuple[TransactionReportingEvidenceModel, ExchangeRateModel], ...]:
        if not transaction_ids:
            return ()
        result = await self.session.execute(
            select(TransactionReportingEvidenceModel, ExchangeRateModel)
            .join(
                ExchangeRateModel,
                ExchangeRateModel.id == TransactionReportingEvidenceModel.exchange_rate_id,
            )
            .where(TransactionReportingEvidenceModel.transaction_id.in_(transaction_ids))
            .order_by(TransactionReportingEvidenceModel.transaction_id)
            .execution_options(populate_existing=True)
        )
        return tuple(result.tuples())

    def add_exchange_rate(self, row: ExchangeRateModel) -> None:
        self.session.add(row)

    def add_reporting_evidence(self, row: TransactionReportingEvidenceModel) -> None:
        self.session.add(row)

    async def flush(self) -> None:
        await self.session.flush()


__all__ = [
    "RaiffeisenbankReportingFxRepository",
    "reporting_fx_job_lock_scope",
    "reporting_fx_rate_lock_scope",
]
