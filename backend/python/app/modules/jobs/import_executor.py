from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.background_jobs import (
    ImportJobAffectedAccountModel,
    ImportJobBatchModel,
)
from app.db.models.canonical_lineage import AccountCanonicalStateModel
from app.db.models.enums import (
    AccountType,
    ImportSource,
    ImportStatus,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.imports import ImportBatchModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.modules.asset_aliases.models import (
    AssetAliasConflictError,
    AssetAliasDatabaseUnavailableError,
    AssetAliasInvalidError,
    AssetAliasNotFoundError,
    AssetAliasStateError,
)
from app.modules.imports.job_executor import (
    ImportExecutionCheckpoint as ExecutionCheckpoint,
)
from app.modules.imports.job_executor import (
    ImportExecutionPayload as ExecutionPayload,
)
from app.modules.imports.job_executor import (
    ImportExecutionProgress as ExecutionProgress,
)
from app.modules.imports.job_executor import (
    ImportExecutionStage,
    ImportJobExecutionRetryableError,
    ImportJobExecutionStateError,
    ImportJobWideStageResult,
)
from app.modules.imports.job_executor import (
    ImportJobExecutor as StageImportJobExecutor,
)
from app.modules.imports.models import ImportSnapshotRefreshStatus
from app.modules.imports.multi_file_service import ImportMultiFileFinalizationService
from app.modules.imports.raiffeisenbank_reconciliation_service import (
    RaiffeisenbankReconciliationService,
    RaiffeisenbankReconciliationStateError,
    ReconcileRaiffeisenbankJobCommand,
)
from app.modules.imports.raiffeisenbank_reporting_fx import (
    AcquireRaiffeisenbankReportingFxCommand,
    RaiffeisenbankReportingFxConflictError,
    RaiffeisenbankReportingFxStateError,
)
from app.modules.imports.raiffeisenbank_reporting_fx_factory import (
    create_raiffeisenbank_reporting_fx_service,
)
from app.modules.imports.trading212_asset_alias import Trading212AssetAliasService
from app.modules.investments.anycoin_transfer_valuation_service import (
    AnycoinTransferValuationService,
)
from app.modules.jobs.models import (
    ImportJobCheckpoint,
    ImportJobPayload,
    ImportJobPhase,
    ImportJobProgress,
    ImportJobResult,
)
from app.modules.jobs.publication_service import ImportJobPublicationService
from app.modules.jobs.repository import ClaimedBackgroundJob
from app.modules.jobs.worker import (
    CheckpointCallback,
    DeferredBackgroundJobError,
    PermanentBackgroundJobError,
    RetryableBackgroundJobError,
)
from app.modules.liabilities.evidence_service import (
    LiabilityBalanceEvidenceService,
    LiabilityBalanceEvidenceStateError,
    SelectLiabilityBalanceCommand,
)
from app.modules.market_data.source_policy import market_evidence_source_policy_from_settings
from app.modules.snapshot_refresh.market_backed_models import (
    ExecuteMarketBackedSnapshotRefreshCommand,
    MarketBackedSnapshotRefreshConflictError,
    MarketBackedSnapshotRefreshUnavailableError,
)
from app.modules.snapshot_refresh.market_backed_service import (
    MarketBackedSnapshotRefreshService,
)
from app.modules.snapshot_refresh.version import current_coordinated_snapshot_calculation_version
from app.shared.errors import ApplicationError

_TERMINAL_BATCH_STATUSES = {ImportStatus.completed, ImportStatus.partially_completed}
_STAGE_PHASE = {
    ImportExecutionStage.parse: ImportJobPhase.parsing,
    ImportExecutionStage.normalize: ImportJobPhase.normalizing,
    ImportExecutionStage.deduplicate: ImportJobPhase.deduplicating,
    ImportExecutionStage.classify: ImportJobPhase.classifying,
    ImportExecutionStage.canonical_post: ImportJobPhase.posting,
    ImportExecutionStage.reconcile: ImportJobPhase.reconciling,
    ImportExecutionStage.acquire_reporting_fx: ImportJobPhase.acquiring_reporting_fx,
    ImportExecutionStage.validate_liability_readiness: ImportJobPhase.validating_liability,
    ImportExecutionStage.finalize: ImportJobPhase.refreshing_snapshot,
}
_PHASE_STAGE = {phase: stage for stage, phase in _STAGE_PHASE.items()}
_BATCH_STAGES = (
    ImportExecutionStage.parse,
    ImportExecutionStage.normalize,
    ImportExecutionStage.deduplicate,
    ImportExecutionStage.classify,
    ImportExecutionStage.canonical_post,
)
_JOB_WIDE_STAGES = (
    ImportExecutionStage.reconcile,
    ImportExecutionStage.acquire_reporting_fx,
    ImportExecutionStage.validate_liability_readiness,
    ImportExecutionStage.finalize,
)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _now_milliseconds() -> datetime:
    value = _now()
    return value.replace(microsecond=(value.microsecond // 1_000) * 1_000)


_LIABILITY_ACCOUNT_TYPES = {AccountType.loan, AccountType.mortgage}


class ImportLiabilityBalanceRequiredError(RuntimeError):
    """An explicit liability observation is required before publication."""


class DurableImportJobExecutor:
    """Adapt the import stage executor to the persisted fenced job contract."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        *,
        market_refresh_factory: Callable[
            [AsyncSession, Settings], MarketBackedSnapshotRefreshService
        ]
        | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings
        self.market_refresh_factory = market_refresh_factory or MarketBackedSnapshotRefreshService
        self.executor = StageImportJobExecutor(
            session_factory,
            principal_resolver=self._resolve_principal,
            finalization_factory=self._finalization_service,
            job_wide_stage_hook=self._run_job_wide_stage,
        )

    async def execute(
        self,
        claimed: ClaimedBackgroundJob,
        *,
        checkpoint: CheckpointCallback,
    ) -> ImportJobResult:
        try:
            payload = ImportJobPayload.model_validate(claimed.job.payload)
            persisted_checkpoint = ImportJobCheckpoint.model_validate(claimed.job.checkpoint)
            initial_progress = ImportJobProgress.model_validate(claimed.job.progress)
        except ValueError as exc:
            raise PermanentBackgroundJobError(
                code="background_job_state_invalid",
                message="The persisted background job state is invalid.",
            ) from exc

        completed_stage = _PHASE_STAGE.get(persisted_checkpoint.phase)
        if persisted_checkpoint.phase is ImportJobPhase.completed:
            completed_stage = ImportExecutionStage.finalize
        if persisted_checkpoint.phase is ImportJobPhase.rebuilding_holdings:
            raise PermanentBackgroundJobError(
                code="background_job_state_invalid",
                message="The persisted background job state is invalid.",
            )
        current_completed = completed_stage

        async def on_progress(value: ExecutionProgress) -> None:
            nonlocal current_completed
            stage_index = _BATCH_STAGES.index(value.stage)
            progress = ImportJobProgress(
                phase=_STAGE_PHASE[value.stage],
                completed_units=(stage_index * len(payload.batch_ids)) + value.completed_batches,
                total_units=initial_progress.total_units,
                completed_batches=value.completed_batches,
                total_batches=len(payload.batch_ids),
            )
            await checkpoint(
                ImportJobCheckpoint(
                    phase=(
                        ImportJobPhase.queued
                        if current_completed is None
                        else _STAGE_PHASE[current_completed]
                    ),
                    completed_batch_ids=(),
                ),
                progress,
            )

        async def on_checkpoint(value: ExecutionCheckpoint) -> None:
            nonlocal current_completed
            current_completed = value.stage
            if value.stage in _BATCH_STAGES:
                completed_units = (_BATCH_STAGES.index(value.stage) + 1) * len(payload.batch_ids)
            else:
                completed_units = (len(_BATCH_STAGES) * len(payload.batch_ids)) + (
                    _JOB_WIDE_STAGES.index(value.stage) + 1
                )
            completed_units = min(initial_progress.total_units, completed_units)
            await checkpoint(
                ImportJobCheckpoint(
                    phase=_STAGE_PHASE[value.stage],
                    completed_batch_ids=payload.batch_ids,
                ),
                ImportJobProgress(
                    phase=_STAGE_PHASE[value.stage],
                    completed_units=completed_units,
                    total_units=initial_progress.total_units,
                    completed_batches=len(payload.batch_ids),
                    total_batches=len(payload.batch_ids),
                ),
            )

        targets: tuple = ()

        async def reserve_publication_bucket() -> datetime:
            nonlocal targets
            now = _now().replace(second=0, microsecond=0)
            async with self.session_factory() as publication_session:
                targets = await ImportJobPublicationService(publication_session).reserve(
                    job_id=claimed.job.id,
                    account_id=claimed.job.account_id,
                    requested_bucket=now,
                )
            own_target = next(
                (item for item in targets if item.user_id == claimed.job.user_id), None
            )
            if own_target is None:
                raise PermanentBackgroundJobError(
                    code="import_job_publication_members_invalid",
                    message="The import publication members are no longer available.",
                )
            future_targets = tuple(item.bucket for item in targets if item.bucket > now)
            if future_targets:
                raise DeferredBackgroundJobError(
                    run_after=max(future_targets),
                    code="import_publication_deferred",
                    message="Portfolio publication is waiting for its reserved snapshot window.",
                )
            return own_target.bucket

        try:
            execution = await self.executor.execute(
                claimed.job.id,
                claimed.job.user_id,
                claimed.job.account_id,
                ExecutionPayload(batch_ids=payload.batch_ids),
                completed_stage,
                on_checkpoint,
                on_progress=on_progress,
                publication_bucket_resolver=reserve_publication_bucket,
                affected_account_resolver=lambda: self._affected_account_ids(
                    job_id=claimed.job.id,
                    user_id=claimed.job.user_id,
                    fallback_account_id=claimed.job.account_id,
                ),
                on_job_wide_stage=self._run_job_wide_stage,
            )
        except ImportLiabilityBalanceRequiredError as exc:
            raise DeferredBackgroundJobError(
                run_after=_now() + timedelta(minutes=5),
                code="import_liability_balance_required",
                message=("An explicit liability balance is required before portfolio publication."),
            ) from exc
        except RaiffeisenbankReportingFxStateError as exc:
            raise RetryableBackgroundJobError(
                code="import_reporting_fx_unavailable",
                message="Required reporting-currency evidence is temporarily unavailable.",
            ) from exc
        except RaiffeisenbankReportingFxConflictError as exc:
            raise PermanentBackgroundJobError(
                code="import_reporting_fx_conflict",
                message="Persisted reporting-currency evidence is inconsistent.",
            ) from exc
        except RaiffeisenbankReconciliationStateError as exc:
            raise PermanentBackgroundJobError(
                code="import_reconciliation_state_invalid",
                message="Persisted bank reconciliation evidence is inconsistent.",
            ) from exc
        except ImportJobExecutionRetryableError as exc:
            raise RetryableBackgroundJobError(
                code="snapshot_refresh_incomplete",
                message="Portfolio publication is not complete and will be retried.",
            ) from exc
        except ImportJobExecutionStateError as exc:
            raise PermanentBackgroundJobError(
                code="import_job_state_invalid",
                message="The import job can no longer be processed safely.",
            ) from exc
        except AssetAliasDatabaseUnavailableError as exc:
            raise RetryableBackgroundJobError(
                code="import_asset_alias_dependency_unavailable",
                message="Required provider identity persistence is temporarily unavailable.",
            ) from exc
        except (
            AssetAliasConflictError,
            AssetAliasInvalidError,
            AssetAliasNotFoundError,
            AssetAliasStateError,
        ) as exc:
            raise PermanentBackgroundJobError(
                code="import_asset_alias_state_invalid",
                message="The imported asset cannot be assigned its exact provider identity.",
            ) from exc
        except ApplicationError as exc:
            if exc.status_code >= 500 or exc.code in {
                "snapshot_refresh_conflict",
                "snapshot_refresh_unavailable",
                "dependency_unavailable",
            }:
                raise RetryableBackgroundJobError(
                    code="import_job_dependency_unavailable",
                    message="Required import evidence is temporarily unavailable.",
                ) from exc
            raise PermanentBackgroundJobError(
                code="import_job_validation_failed",
                message="The import job cannot continue with the persisted input.",
            ) from exc

        snapshot_status = execution.finalization.snapshot_refresh_status
        if snapshot_status in {
            ImportSnapshotRefreshStatus.unavailable,
            ImportSnapshotRefreshStatus.conflict,
        }:
            raise RetryableBackgroundJobError(
                code="snapshot_refresh_incomplete",
                message="Portfolio publication is not complete and will be retried.",
            )
        # Reconcile membership after the initiating-user anchor exists: a
        # departed unpublished target is retired and a new member receives an
        # exact internal publication before completion.
        await reserve_publication_bucket()
        affected_account_ids = await self._affected_account_ids(
            job_id=claimed.job.id,
            user_id=claimed.job.user_id,
            fallback_account_id=claimed.job.account_id,
        )
        for target in targets:
            if target.user_id == claimed.job.user_id:
                continue
            try:
                async with self.session_factory() as publication_session:
                    await self.market_refresh_factory(
                        publication_session,
                        self.settings,
                    ).execute(
                        ExecuteMarketBackedSnapshotRefreshCommand(
                            user_id=target.user_id,
                            snapshot_timestamp=target.bucket,
                            granularity=SnapshotGranularity.minute,
                            source=SnapshotSource.import_event,
                            calculation_version=current_coordinated_snapshot_calculation_version(),
                            calculated_at=target.bucket,
                            created_at=target.bucket,
                            is_recalculated=False,
                            publication_job_id=claimed.job.id,
                            publication_account_ids=await self._authorized_affected_account_ids(
                                user_id=target.user_id,
                                affected_account_ids=affected_account_ids,
                            ),
                        )
                    )
            except (
                ApplicationError,
                MarketBackedSnapshotRefreshConflictError,
                MarketBackedSnapshotRefreshUnavailableError,
                ValueError,
            ) as exc:
                raise RetryableBackgroundJobError(
                    code="import_job_member_publication_unavailable",
                    message="A shared portfolio publication could not be completed.",
                ) from exc
        return await self._result(
            user_id=claimed.job.user_id,
            account_id=claimed.job.account_id,
            batch_ids=payload.batch_ids,
            snapshot_status=snapshot_status,
        )

    async def _run_job_wide_stage(
        self,
        stage: ImportExecutionStage,
        job_id: str,
        user_id: str,
        account_id: str,
        batch_ids: tuple[str, ...],
    ) -> ImportJobWideStageResult:
        source = await self._manifest_source(
            job_id=job_id,
            user_id=user_id,
            account_id=account_id,
            batch_ids=batch_ids,
        )
        if source is not ImportSource.raiffeisenbank:
            return ImportJobWideStageResult(job_id=job_id, stage=stage, applied=False)
        created_at = _now_milliseconds()
        if stage is ImportExecutionStage.reconcile:
            async with self.session_factory() as session:
                await RaiffeisenbankReconciliationService(session).reconcile(
                    command=ReconcileRaiffeisenbankJobCommand(
                        job_id=job_id,
                        user_id=user_id,
                        created_at=created_at,
                    )
                )
            return ImportJobWideStageResult(job_id=job_id, stage=stage, applied=True)
        if stage is ImportExecutionStage.acquire_reporting_fx:
            async with self.session_factory() as session:
                async with session.begin():
                    user = await session.scalar(select(UserModel).where(UserModel.id == user_id))
                    transaction_ids = tuple(
                        (
                            await session.scalars(
                                select(TransactionModel.id)
                                .where(TransactionModel.import_batch_id.in_(batch_ids))
                                .order_by(TransactionModel.id)
                            )
                        ).all()
                    )
                if user is None:
                    raise RaiffeisenbankReportingFxStateError()
                await create_raiffeisenbank_reporting_fx_service(
                    session,
                    self.settings,
                ).acquire(
                    AcquireRaiffeisenbankReportingFxCommand(
                        job_id=job_id,
                        user_id=user_id,
                        reporting_currency=user.base_currency,
                        canonical_transaction_ids=transaction_ids,
                        created_at=created_at,
                    )
                )
            return ImportJobWideStageResult(job_id=job_id, stage=stage, applied=True)
        if stage is ImportExecutionStage.validate_liability_readiness:
            through = _now_milliseconds().replace(second=0, microsecond=0)
            async with self.session_factory() as session:
                async with session.begin():
                    accounts = tuple(
                        (
                            await session.scalars(
                                select(AccountModel)
                                .join(
                                    AccountMemberModel,
                                    AccountMemberModel.account_id == AccountModel.id,
                                )
                                .join(
                                    AccountCanonicalStateModel,
                                    AccountCanonicalStateModel.account_id == AccountModel.id,
                                )
                                .where(
                                    AccountMemberModel.user_id == user_id,
                                    AccountModel.is_archived.is_(False),
                                    AccountCanonicalStateModel.last_revision > 0,
                                )
                                .order_by(AccountModel.id)
                            )
                        ).all()
                    )
                    evidence = LiabilityBalanceEvidenceService(session)
                    for account in accounts:
                        if account.type not in _LIABILITY_ACCOUNT_TYPES:
                            continue
                        try:
                            await evidence.select(
                                SelectLiabilityBalanceCommand(
                                    account_id=account.id,
                                    snapshot_timestamp=through,
                                )
                            )
                        except LiabilityBalanceEvidenceStateError as exc:
                            raise ImportLiabilityBalanceRequiredError() from exc
            return ImportJobWideStageResult(job_id=job_id, stage=stage, applied=True)
        raise ImportJobExecutionStateError("Import job-wide stage is invalid.")

    async def _manifest_source(
        self,
        *,
        job_id: str,
        user_id: str,
        account_id: str,
        batch_ids: tuple[str, ...],
    ) -> ImportSource:
        async with self.session_factory() as session:
            rows = tuple(
                (
                    await session.execute(
                        select(ImportJobBatchModel, ImportBatchModel)
                        .join(
                            ImportBatchModel,
                            ImportBatchModel.id == ImportJobBatchModel.batch_id,
                        )
                        .where(
                            ImportJobBatchModel.job_id == job_id,
                            ImportJobBatchModel.user_id == user_id,
                            ImportJobBatchModel.account_id == account_id,
                        )
                        .order_by(ImportJobBatchModel.batch_id)
                    )
                ).tuples()
            )
        if tuple(membership.batch_id for membership, _batch in rows) != batch_ids or any(
            batch.id != membership.batch_id
            or batch.user_id != user_id
            or batch.account_id != account_id
            or membership.user_id != user_id
            or membership.account_id != account_id
            for membership, batch in rows
        ):
            raise ImportJobExecutionStateError("Import job manifest is invalid.")
        sources = {batch.source for _membership, batch in rows}
        if len(sources) != 1:
            raise ImportJobExecutionStateError("Import job manifest is invalid.")
        return sources.pop()

    async def _affected_account_ids(
        self,
        *,
        job_id: str,
        user_id: str,
        fallback_account_id: str,
    ) -> tuple[str, ...]:
        async with self.session_factory() as session:
            rows = tuple(
                (
                    await session.scalars(
                        select(ImportJobAffectedAccountModel)
                        .where(ImportJobAffectedAccountModel.job_id == job_id)
                        .order_by(ImportJobAffectedAccountModel.account_id)
                    )
                ).all()
            )
        if not rows:
            return (fallback_account_id,)
        account_ids = tuple(row.account_id for row in rows)
        if (
            len(set(account_ids)) != len(account_ids)
            or fallback_account_id not in account_ids
            or any(row.user_id != user_id for row in rows)
        ):
            raise ImportJobExecutionStateError("Import affected-account manifest is invalid.")
        return account_ids

    async def _authorized_affected_account_ids(
        self,
        *,
        user_id: str,
        affected_account_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        async with self.session_factory() as session:
            result = tuple(
                (
                    await session.scalars(
                        select(AccountMemberModel.account_id)
                        .where(
                            AccountMemberModel.user_id == user_id,
                            AccountMemberModel.account_id.in_(affected_account_ids),
                        )
                        .order_by(AccountMemberModel.account_id)
                    )
                ).all()
            )
        if not result:
            raise ImportJobExecutionStateError("Import publication member scope is invalid.")
        return result

    async def _result(
        self,
        *,
        user_id: str,
        account_id: str,
        batch_ids: tuple[str, ...],
        snapshot_status: ImportSnapshotRefreshStatus,
    ) -> ImportJobResult:
        async with self.session_factory() as session:
            rows = tuple(
                (
                    await session.scalars(
                        select(ImportBatchModel)
                        .where(
                            ImportBatchModel.id.in_(batch_ids),
                            ImportBatchModel.user_id == user_id,
                            ImportBatchModel.account_id == account_id,
                        )
                        .order_by(ImportBatchModel.id)
                    )
                ).all()
            )
        if tuple(row.id for row in rows) != batch_ids or any(
            row.status not in _TERMINAL_BATCH_STATUSES
            or row.rows_total is None
            or row.rows_imported is None
            or row.rows_skipped is None
            or row.rows_imported + row.rows_skipped != row.rows_total
            or row.completed_at is None
            for row in rows
        ):
            raise PermanentBackgroundJobError(
                code="import_job_result_invalid",
                message="The completed import job result is inconsistent.",
            )
        completed_at = max(row.completed_at for row in rows if row.completed_at is not None)
        return ImportJobResult(
            batch_ids=batch_ids,
            rows_total=sum(int(row.rows_total or 0) for row in rows),
            rows_imported=sum(int(row.rows_imported or 0) for row in rows),
            rows_skipped=sum(int(row.rows_skipped or 0) for row in rows),
            snapshot_refresh_status=cast(
                Literal["created", "replayed", "not_required"], snapshot_status.value
            ),
            completed_at=completed_at or _now(),
        )

    async def _resolve_principal(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> AuthenticatedPrincipal:
        user = await session.scalar(select(UserModel).where(UserModel.id == user_id))
        if user is None:
            raise PermanentBackgroundJobError(
                code="import_job_authorization_removed",
                message="The import job authorization is no longer valid.",
            )
        return AuthenticatedPrincipal(user_id=user.id, email=user.email, name=user.name)

    def _finalization_service(self, session: AsyncSession) -> ImportMultiFileFinalizationService:
        return ImportMultiFileFinalizationService(
            session,
            market_backed_service=MarketBackedSnapshotRefreshService(session, self.settings),
            source_policy=market_evidence_source_policy_from_settings(self.settings),
            anycoin_transfer_valuation_factory=lambda active_session: (
                AnycoinTransferValuationService(active_session, self.settings)
            ),
            trading212_asset_alias_factory=lambda active_session: Trading212AssetAliasService(
                active_session,
                source_policy=market_evidence_source_policy_from_settings(self.settings),
            ),
        )
