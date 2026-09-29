"""Request-level finalization for one logical multi-file import history."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import ImportSource, ImportStatus
from app.modules.accounts.access import require_account_access
from app.modules.imports.anycoin_btc_alias import (
    AnycoinBtcAliasService,
    OnboardAnycoinBtcAliasCommand,
)
from app.modules.imports.models import ImportSnapshotRefreshStatus
from app.modules.imports.post_processing_repository import (
    ImportBatchPostProcessingRepository,
)
from app.modules.imports.post_processing_service import (
    HoldingServiceFactory,
    ImportBatchPostProcessingService,
    PostingServiceFactory,
    RepositoryFactory,
    _holding_factory,
    _MarketBackedRefreshService,
    _validate_posting_result,
    _validate_principal_account,
)
from app.modules.imports.posting_service import (
    WRITE_ROLES,
    ImportBatchPostingService,
    PostImportBatchCommand,
)
from app.modules.imports.repository import ImportBatchRepository
from app.modules.imports.service import ImportBatchNotFoundError
from app.modules.imports.trading212_asset_alias import (
    OnboardTrading212AssetAliasesCommand,
    OnboardTrading212AssetAliasesResult,
)
from app.modules.investments.anycoin_transfer_valuation_service import (
    ValueAnycoinTransfersCommand,
    ValueAnycoinTransfersResult,
)
from app.modules.market_data.source_policy import (
    MarketEvidenceSourcePolicy,
    validate_market_evidence_source_policy,
)
from app.shared.errors import ApplicationError

_TERMINAL_STATUSES = {ImportStatus.completed, ImportStatus.partially_completed}
_MAX_BATCHES = 10

type BatchRepositoryFactory = Callable[[AsyncSession], ImportBatchRepository]
type AnycoinBtcAliasFactory = Callable[
    [AsyncSession, MarketEvidenceSourcePolicy], AnycoinBtcAliasService
]


class _AnycoinTransferValuationService(Protocol):
    async def value(self, command: ValueAnycoinTransfersCommand) -> ValueAnycoinTransfersResult: ...


type AnycoinTransferValuationFactory = Callable[[AsyncSession], _AnycoinTransferValuationService]


class _Trading212AssetAliasService(Protocol):
    async def onboard(
        self, command: OnboardTrading212AssetAliasesCommand
    ) -> OnboardTrading212AssetAliasesResult: ...


type Trading212AssetAliasFactory = Callable[[AsyncSession], _Trading212AssetAliasService]


def _anycoin_btc_alias_factory(
    session: AsyncSession,
    source_policy: MarketEvidenceSourcePolicy,
) -> AnycoinBtcAliasService:
    return AnycoinBtcAliasService(session, source_policy=source_policy)


class ImportBatchFinalizationStateError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_batch_finalization_state_invalid",
            message="The import batches are not available for finalization.",
            status_code=409,
        )


@dataclass(frozen=True, slots=True)
class FinalizeImportBatchesCommand:
    principal: AuthenticatedPrincipal
    account_id: str
    batch_ids: tuple[str, ...]
    background_job_id: str | None = None
    publication_bucket: datetime | None = None
    publication_account_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FinalizeImportBatchesResult:
    batch_ids: tuple[str, ...]
    snapshot_refresh_status: ImportSnapshotRefreshStatus


def _validate_command(value: object) -> FinalizeImportBatchesCommand:
    if not isinstance(value, FinalizeImportBatchesCommand):
        raise RuntimeError("Import finalization command is invalid.")
    _validate_principal_account(value.principal, value.account_id)
    if (
        not isinstance(value.batch_ids, tuple)
        or not value.batch_ids
        or len(value.batch_ids) > _MAX_BATCHES
        or any(
            not isinstance(batch_id, str) or not batch_id or batch_id != batch_id.strip()
            for batch_id in value.batch_ids
        )
        or len(set(value.batch_ids)) != len(value.batch_ids)
        or value.batch_ids != tuple(sorted(value.batch_ids))
    ):
        raise RuntimeError("Import finalization command is invalid.")
    if value.background_job_id is not None and (
        not isinstance(value.background_job_id, str)
        or not value.background_job_id
        or value.background_job_id != value.background_job_id.strip()
    ):
        raise RuntimeError("Import finalization command is invalid.")
    if value.publication_bucket is not None and (
        value.publication_bucket.tzinfo is not None
        or value.publication_bucket.second != 0
        or value.publication_bucket.microsecond != 0
    ):
        raise RuntimeError("Import finalization command is invalid.")
    if (
        not isinstance(value.publication_account_ids, tuple)
        or tuple(sorted(set(value.publication_account_ids))) != value.publication_account_ids
        or any(
            not isinstance(account_id, str) or not account_id or account_id != account_id.strip()
            for account_id in value.publication_account_ids
        )
        or (value.background_job_id is None) != (not value.publication_account_ids)
        or (
            value.background_job_id is not None
            and value.account_id not in value.publication_account_ids
        )
    ):
        raise RuntimeError("Import finalization command is invalid.")
    return value


class ImportMultiFileFinalizationService(ImportBatchPostProcessingService):
    """Validate persisted batches and execute one shared post-processing phase."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        market_backed_service: _MarketBackedRefreshService,
        source_policy: MarketEvidenceSourcePolicy,
        posting_service_factory: PostingServiceFactory = ImportBatchPostingService,
        holding_service_factory: HoldingServiceFactory = _holding_factory,
        repository_factory: RepositoryFactory = ImportBatchPostProcessingRepository,
        batch_repository_factory: BatchRepositoryFactory = ImportBatchRepository,
        anycoin_btc_alias_factory: AnycoinBtcAliasFactory = _anycoin_btc_alias_factory,
        anycoin_transfer_valuation_factory: AnycoinTransferValuationFactory | None = None,
        trading212_asset_alias_factory: Trading212AssetAliasFactory | None = None,
    ) -> None:
        super().__init__(
            session,
            market_backed_service=market_backed_service,
            posting_service_factory=posting_service_factory,
            holding_service_factory=holding_service_factory,
            repository_factory=repository_factory,
        )
        self.source_policy = validate_market_evidence_source_policy(source_policy)
        self.batch_repository = batch_repository_factory(session)
        self.anycoin_btc_alias_factory = anycoin_btc_alias_factory
        self.anycoin_transfer_valuation_factory = anycoin_transfer_valuation_factory
        self.trading212_asset_alias_factory = trading212_asset_alias_factory

    async def finalize(
        self,
        command: FinalizeImportBatchesCommand,
    ) -> FinalizeImportBatchesResult:
        canonical = _validate_command(command)
        await self._require_idle("Import finalization requires an idle session.")
        source: ImportSource | None = None
        async with self.session.begin():
            await require_account_access(
                session=self.session,
                principal=canonical.principal,
                account_id=canonical.account_id,
                allowed_roles=WRITE_ROLES,
            )
            for batch_id in canonical.batch_ids:
                batch = await self.batch_repository.get_for_account(
                    account_id=canonical.account_id,
                    batch_id=batch_id,
                )
                if batch is None or batch.user_id != canonical.principal.user_id:
                    raise ImportBatchNotFoundError()
                if batch.status not in _TERMINAL_STATUSES or batch.completed_at is None:
                    raise ImportBatchFinalizationStateError()
                if source is None:
                    source = batch.source
                elif batch.source is not source:
                    raise ImportBatchFinalizationStateError()
        await self._require_idle("Import finalization validation left an active transaction.")

        postings = []
        for batch_id in canonical.batch_ids:
            posting_command = PostImportBatchCommand(
                principal=canonical.principal,
                account_id=canonical.account_id,
                batch_id=batch_id,
            )
            posting_service = self.posting_service_factory(self.session)
            try:
                value = await posting_service.post_batch(posting_command)
            except Exception as exc:
                if self.session.in_transaction():
                    await self.session.rollback()
                    raise RuntimeError("Import posting replay left an active transaction.") from exc
                raise
            posting = _validate_posting_result(value, posting_command)
            await self._require_idle("Import posting replay left an active transaction.")
            postings.append(posting)

        if source is None:
            raise ImportBatchFinalizationStateError()
        alias_service = self.anycoin_btc_alias_factory(self.session, self.source_policy)
        await alias_service.onboard(
            OnboardAnycoinBtcAliasCommand(
                account_id=canonical.account_id,
                batch_ids=canonical.batch_ids,
                source=source,
                created_at=max(posting.completed_at for posting in postings),
            )
        )
        await self._require_idle("Anycoin BTC alias onboarding left an active transaction.")

        if source is ImportSource.trading212 and self.trading212_asset_alias_factory is not None:
            trading_alias_service = self.trading212_asset_alias_factory(self.session)
            await trading_alias_service.onboard(
                OnboardTrading212AssetAliasesCommand(
                    account_id=canonical.account_id,
                    batch_ids=canonical.batch_ids,
                    source=source,
                    created_at=max(posting.completed_at for posting in postings),
                )
            )
            await self._require_idle(
                "Trading 212 asset alias onboarding left an active transaction."
            )

        if (
            source is ImportSource.anycoin
            and any(posting.investment_event_rows_imported > 0 for posting in postings)
            and self.anycoin_transfer_valuation_factory is not None
        ):
            valuation_service = self.anycoin_transfer_valuation_factory(self.session)
            await valuation_service.value(
                ValueAnycoinTransfersCommand(
                    account_id=canonical.account_id,
                    source=source,
                    created_at=max(posting.completed_at for posting in postings),
                )
            )
            await self._require_idle("Anycoin transfer valuation left an active transaction.")

        status = await self._finalize_postings(
            principal=canonical.principal,
            account_id=canonical.account_id,
            postings=tuple(postings),
            background_job_id=canonical.background_job_id,
            publication_bucket=canonical.publication_bucket,
            publication_account_ids=canonical.publication_account_ids,
        )
        return FinalizeImportBatchesResult(
            batch_ids=canonical.batch_ids,
            snapshot_refresh_status=status,
        )
