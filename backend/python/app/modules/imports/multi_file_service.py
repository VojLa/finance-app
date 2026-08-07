"""Request-level finalization for one logical multi-file import history."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import ImportSource, ImportStatus
from app.modules.accounts.access import require_account_access
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
from app.shared.errors import ApplicationError

_TERMINAL_STATUSES = {ImportStatus.completed, ImportStatus.partially_completed}
_MAX_BATCHES = 10

type BatchRepositoryFactory = Callable[[AsyncSession], ImportBatchRepository]


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
    return value


class ImportMultiFileFinalizationService(ImportBatchPostProcessingService):
    """Validate persisted batches and execute one shared post-processing phase."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        market_backed_service: _MarketBackedRefreshService,
        posting_service_factory: PostingServiceFactory = ImportBatchPostingService,
        holding_service_factory: HoldingServiceFactory = _holding_factory,
        repository_factory: RepositoryFactory = ImportBatchPostProcessingRepository,
        batch_repository_factory: BatchRepositoryFactory = ImportBatchRepository,
    ) -> None:
        super().__init__(
            session,
            market_backed_service=market_backed_service,
            posting_service_factory=posting_service_factory,
            holding_service_factory=holding_service_factory,
            repository_factory=repository_factory,
        )
        self.batch_repository = batch_repository_factory(session)

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

        status = await self._finalize_postings(
            principal=canonical.principal,
            account_id=canonical.account_id,
            postings=tuple(postings),
        )
        return FinalizeImportBatchesResult(
            batch_ids=canonical.batch_ids,
            snapshot_refresh_status=status,
        )
