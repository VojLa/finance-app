"""Database boundary for manifest-scoped Raiffeisenbank card occurrences."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.background_jobs import BackgroundJobModel, ImportJobBatchModel
from app.db.models.enums import AccountType, BackgroundJobKind, BackgroundJobStatus, ImportSource
from app.db.models.imports import ImportBatchModel, ImportRowModel, ImportSourceOccurrenceModel
from app.modules.jobs.models import ImportJobPayload


@dataclass(frozen=True)
class ManifestedRaiffeisenbankRows:
    job: BackgroundJobModel
    batches: tuple[ImportBatchModel, ...]
    rows: tuple[tuple[ImportRowModel, ImportBatchModel], ...]
    is_credit_card_account: bool


class RaiffeisenbankCardOccurrenceRepository:
    """All operations remain within the caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_manifested_card_rows_for_update(
        self,
        *,
        job_id: str,
        user_id: str,
        account_id: str,
    ) -> ManifestedRaiffeisenbankRows | None:
        job = await self.session.scalar(
            select(BackgroundJobModel)
            .where(
                BackgroundJobModel.id == job_id,
                BackgroundJobModel.user_id == user_id,
                BackgroundJobModel.account_id == account_id,
                BackgroundJobModel.kind == BackgroundJobKind.import_workflow,
                BackgroundJobModel.status == BackgroundJobStatus.running,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None:
            return None
        manifests = tuple(
            (
                await self.session.execute(
                    select(ImportJobBatchModel, ImportBatchModel)
                    .join(ImportBatchModel, ImportBatchModel.id == ImportJobBatchModel.batch_id)
                    .where(
                        ImportJobBatchModel.job_id == job_id,
                        ImportJobBatchModel.user_id == user_id,
                        ImportJobBatchModel.account_id == account_id,
                    )
                    .order_by(ImportJobBatchModel.batch_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).tuples()
        )
        batches = tuple(batch for _, batch in manifests)
        if not manifests or any(
            batch.user_id != user_id
            or batch.account_id != account_id
            or batch.source is not ImportSource.raiffeisenbank
            for batch in batches
        ):
            raise RuntimeError("The import-job manifest is invalid.")
        try:
            payload = ImportJobPayload.model_validate(job.payload)
        except ValidationError as exc:
            raise RuntimeError("The import-job payload is invalid.") from exc
        if tuple(batch.id for batch in batches) != payload.batch_ids:
            raise RuntimeError("The import-job manifest does not match its payload.")
        account_type = await self.session.scalar(
            select(AccountModel.type).where(AccountModel.id == account_id).with_for_update()
        )
        if account_type is not AccountType.credit_card:
            # A durable RB job also owns bank, savings, and EUR statements.
            # They deliberately remain on the normal source-wide dedupe path;
            # only a credit-card account has the no-provider-ID multiset rule.
            return ManifestedRaiffeisenbankRows(
                job=job,
                batches=batches,
                rows=(),
                is_credit_card_account=False,
            )
        rows = tuple(
            (
                await self.session.execute(
                    select(ImportRowModel, ImportBatchModel)
                    .join(ImportBatchModel, ImportBatchModel.id == ImportRowModel.import_batch_id)
                    .join(
                        ImportJobBatchModel,
                        (ImportJobBatchModel.job_id == job_id)
                        & (ImportJobBatchModel.batch_id == ImportBatchModel.id),
                    )
                    .where(
                        ImportJobBatchModel.user_id == user_id,
                        ImportJobBatchModel.account_id == account_id,
                    )
                    .order_by(ImportBatchModel.id, ImportRowModel.row_number, ImportRowModel.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).tuples()
        )
        return ManifestedRaiffeisenbankRows(
            job=job,
            batches=batches,
            rows=rows,
            is_credit_card_account=True,
        )

    async def get_occurrence_for_update(
        self,
        *,
        account_id: str,
        fingerprint_hash: str,
        ordinal: int,
    ) -> ImportSourceOccurrenceModel | None:
        return await self.session.scalar(
            select(ImportSourceOccurrenceModel)
            .where(
                ImportSourceOccurrenceModel.account_id == account_id,
                ImportSourceOccurrenceModel.source == ImportSource.raiffeisenbank,
                ImportSourceOccurrenceModel.fingerprint_hash == fingerprint_hash,
                ImportSourceOccurrenceModel.ordinal == ordinal,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def add_occurrence(self, occurrence: ImportSourceOccurrenceModel) -> None:
        self.session.add(occurrence)
