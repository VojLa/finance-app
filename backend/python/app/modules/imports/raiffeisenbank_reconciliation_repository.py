"""Locked database reads/writes for late-arrival RB reconciliation."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.background_jobs import (
    BackgroundJobModel,
    ImportJobAffectedAccountModel,
    ImportJobBatchModel,
)
from app.db.models.enums import (
    BackgroundJobKind,
    BackgroundJobStatus,
    ImportSource,
    ImportStatus,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel, ImportSourceOccurrenceModel
from app.db.models.transactions import TransactionModel, TransactionPairModel

_TERMINAL_BATCHES = (ImportStatus.completed, ImportStatus.partially_completed)


@dataclass(frozen=True)
class RaiffeisenbankReconciliationEvidenceRow:
    job: BackgroundJobModel
    batch: ImportBatchModel
    row: ImportRowModel
    transaction: TransactionModel


class RaiffeisenbankReconciliationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_current_and_completed_evidence_for_update(
        self,
        *,
        current_job_id: str,
        user_id: str,
    ) -> tuple[BackgroundJobModel, tuple[RaiffeisenbankReconciliationEvidenceRow, ...]]:
        current = await self.session.scalar(
            select(BackgroundJobModel)
            .where(
                BackgroundJobModel.id == current_job_id,
                BackgroundJobModel.user_id == user_id,
                BackgroundJobModel.kind == BackgroundJobKind.import_workflow,
                BackgroundJobModel.status == BackgroundJobStatus.running,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if current is None:
            raise RuntimeError("The current reconciliation job is invalid.")
        allowed_jobs = (BackgroundJobModel.id == current_job_id) | (
            (BackgroundJobModel.id != current_job_id)
            & (BackgroundJobModel.status == BackgroundJobStatus.completed)
        )
        result = await self.session.execute(
            select(BackgroundJobModel, ImportBatchModel, ImportRowModel, TransactionModel)
            .join(ImportJobBatchModel, ImportJobBatchModel.job_id == BackgroundJobModel.id)
            .join(ImportBatchModel, ImportBatchModel.id == ImportJobBatchModel.batch_id)
            .join(ImportRowModel, ImportRowModel.import_batch_id == ImportBatchModel.id)
            .join(TransactionModel, TransactionModel.id == ImportRowModel.created_transaction_id)
            .where(
                BackgroundJobModel.user_id == user_id,
                BackgroundJobModel.kind == BackgroundJobKind.import_workflow,
                allowed_jobs,
                ImportJobBatchModel.user_id == user_id,
                ImportJobBatchModel.account_id == ImportBatchModel.account_id,
                ImportBatchModel.user_id == user_id,
                ImportBatchModel.source == ImportSource.raiffeisenbank,
                ImportBatchModel.status.in_(_TERMINAL_BATCHES),
            )
            .order_by(BackgroundJobModel.id, ImportBatchModel.id, ImportRowModel.row_number)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        rows = tuple(
            RaiffeisenbankReconciliationEvidenceRow(*item) for item in result.tuples().all()
        )
        current_manifest_count = await self.session.scalar(
            select(ImportJobBatchModel.job_id)
            .where(
                ImportJobBatchModel.job_id == current_job_id,
                ImportJobBatchModel.user_id == user_id,
                ImportJobBatchModel.account_id == current.account_id,
            )
            .with_for_update()
        )
        if current_manifest_count is None:
            raise RuntimeError("The current reconciliation manifest is missing.")
        return current, rows

    async def lock_accounts_and_members(
        self,
        *,
        account_ids: tuple[str, ...],
        user_id: str,
    ) -> tuple[tuple[AccountModel, ...], tuple[AccountMemberModel, ...]]:
        accounts = tuple(
            (
                await self.session.scalars(
                    select(AccountModel)
                    .where(AccountModel.id.in_(account_ids))
                    .order_by(AccountModel.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        members = tuple(
            (
                await self.session.scalars(
                    select(AccountMemberModel)
                    .where(
                        AccountMemberModel.account_id.in_(account_ids),
                        AccountMemberModel.user_id == user_id,
                    )
                    .order_by(AccountMemberModel.account_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        return accounts, members

    async def load_occurrences_for_update(
        self,
        *,
        representative_row_ids: tuple[str, ...],
    ) -> tuple[ImportSourceOccurrenceModel, ...]:
        if not representative_row_ids:
            return ()
        return tuple(
            (
                await self.session.scalars(
                    select(ImportSourceOccurrenceModel)
                    .where(
                        ImportSourceOccurrenceModel.representative_import_row_id.in_(
                            representative_row_ids
                        ),
                        ImportSourceOccurrenceModel.source == ImportSource.raiffeisenbank,
                    )
                    .order_by(ImportSourceOccurrenceModel.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )

    async def load_pairs_for_update(
        self,
        *,
        transaction_ids: tuple[str, ...],
    ) -> tuple[TransactionPairModel, ...]:
        if not transaction_ids:
            return ()
        return tuple(
            (
                await self.session.scalars(
                    select(TransactionPairModel)
                    .where(
                        or_(
                            TransactionPairModel.from_transaction_id.in_(transaction_ids),
                            TransactionPairModel.to_transaction_id.in_(transaction_ids),
                        )
                    )
                    .order_by(TransactionPairModel.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )

    async def get_affected_account_for_update(
        self,
        *,
        job_id: str,
        account_id: str,
    ) -> ImportJobAffectedAccountModel | None:
        return await self.session.scalar(
            select(ImportJobAffectedAccountModel)
            .where(
                ImportJobAffectedAccountModel.job_id == job_id,
                ImportJobAffectedAccountModel.account_id == account_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def add_pair(self, value: TransactionPairModel) -> None:
        self.session.add(value)

    def add_affected_account(self, value: ImportJobAffectedAccountModel) -> None:
        self.session.add(value)

    async def flush(self) -> None:
        await self.session.flush()
