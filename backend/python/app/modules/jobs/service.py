from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.background_jobs import BackgroundJobModel
from app.db.models.enums import AccountMemberRole, ImportStatus
from app.modules.accounts.access import require_account_access
from app.modules.imports.repository import ImportBatchRepository
from app.modules.jobs.lifecycle import MAX_AUTOMATIC_ATTEMPTS
from app.modules.jobs.models import (
    ImportJobCheckpoint,
    ImportJobPayload,
    ImportJobPhase,
    ImportJobProgress,
    canonical_import_job_idempotency_key,
)
from app.modules.jobs.repository import BackgroundJobRepository, EnqueuedBackgroundJob
from app.shared.errors import ApplicationError

WRITE_ROLES = {
    AccountMemberRole.owner,
    AccountMemberRole.admin,
    AccountMemberRole.editor,
}


class BackgroundJobNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="background_job_not_found",
            message="The background job was not found.",
            status_code=404,
        )


class BackgroundJobEnqueueStateError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="background_job_enqueue_state_invalid",
            message="The import batches are not available for background processing.",
            status_code=409,
        )


@dataclass(frozen=True, slots=True)
class EnqueueImportJobCommand:
    principal: AuthenticatedPrincipal
    account_id: str
    batch_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EnqueueImportJobResult:
    job: BackgroundJobModel
    created: bool


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _validate_command(command: EnqueueImportJobCommand) -> ImportJobPayload:
    if not isinstance(command, EnqueueImportJobCommand):
        raise BackgroundJobEnqueueStateError()
    if (
        not command.account_id
        or command.account_id != command.account_id.strip()
        or not command.principal.user_id
        or command.principal.user_id != command.principal.user_id.strip()
    ):
        raise BackgroundJobEnqueueStateError()
    try:
        return ImportJobPayload(batch_ids=command.batch_ids)
    except ValueError as exc:
        raise BackgroundJobEnqueueStateError() from exc


class BackgroundJobService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: BackgroundJobRepository | None = None,
        batch_repository: ImportBatchRepository | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or BackgroundJobRepository(session)
        self.batch_repository = batch_repository or ImportBatchRepository(session)

    async def enqueue_import_job(
        self,
        command: EnqueueImportJobCommand,
    ) -> EnqueueImportJobResult:
        payload = _validate_command(command)
        try:
            await require_account_access(
                session=self.session,
                principal=command.principal,
                account_id=command.account_id,
                allowed_roles=WRITE_ROLES,
                for_update=True,
            )
            for batch_id in payload.batch_ids:
                batch = await self.batch_repository.get_for_account(
                    account_id=command.account_id,
                    batch_id=batch_id,
                    for_update=True,
                )
                if (
                    batch is None
                    or batch.user_id != command.principal.user_id
                    or batch.status is not ImportStatus.pending
                    or batch.completed_at is not None
                ):
                    raise BackgroundJobEnqueueStateError()

            key = canonical_import_job_idempotency_key(
                user_id=command.principal.user_id,
                account_id=command.account_id,
                batch_ids=payload.batch_ids,
            )
            total_batches = len(payload.batch_ids)
            enqueued: EnqueuedBackgroundJob = await self.repository.enqueue_import_job(
                user_id=command.principal.user_id,
                account_id=command.account_id,
                idempotency_key=key,
                payload=payload.model_dump(mode="json"),
                checkpoint=ImportJobCheckpoint().model_dump(mode="json"),
                progress=ImportJobProgress(
                    phase=ImportJobPhase.queued,
                    completed_units=0,
                    total_units=(5 * total_batches) + 2,
                    completed_batches=0,
                    total_batches=total_batches,
                ).model_dump(mode="json"),
                max_attempts=MAX_AUTOMATIC_ATTEMPTS,
                now=_now(),
            )
            if enqueued.job.payload != payload.model_dump(mode="json"):
                raise RuntimeError("The canonical background job payload does not match replay.")
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return EnqueueImportJobResult(job=enqueued.job, created=enqueued.created)
