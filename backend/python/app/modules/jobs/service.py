from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.background_jobs import BackgroundJobModel
from app.db.models.enums import AccountMemberRole, ImportSource, ImportStatus
from app.modules.accounts.access import AccountNotFoundError, require_account_access
from app.modules.imports.repository import ImportBatchRepository
from app.modules.jobs.lifecycle import MAX_AUTOMATIC_ATTEMPTS
from app.modules.jobs.models import (
    ImportJobCheckpoint,
    ImportJobError,
    ImportJobPayload,
    ImportJobPhase,
    ImportJobProgress,
    ImportJobResponse,
    ImportJobResult,
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


class BackgroundJobRetryStateError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="background_job_retry_state_invalid",
            message="The background job cannot be retried in its current state.",
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
            key = canonical_import_job_idempotency_key(
                user_id=command.principal.user_id,
                account_id=command.account_id,
                batch_ids=payload.batch_ids,
            )
            existing = await self.repository.get_owned_by_key(
                user_id=command.principal.user_id,
                account_id=command.account_id,
                idempotency_key=key,
            )
            if existing is not None:
                if existing.payload != payload.model_dump(mode="json"):
                    raise RuntimeError(
                        "The canonical background job payload does not match replay."
                    )
                await self.session.commit()
                return EnqueueImportJobResult(job=existing, created=False)

            source: ImportSource | None = None
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
                if source is None:
                    source = batch.source
                elif batch.source is not source:
                    raise BackgroundJobEnqueueStateError()
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

    @staticmethod
    def public_response(job: BackgroundJobModel) -> ImportJobResponse:
        if (job.error_code is None) is not (job.error_message is None):
            raise RuntimeError("The persisted background job error is inconsistent.")
        error = None
        if job.error_code is not None and job.error_message is not None:
            error = ImportJobError(code=job.error_code, message=job.error_message)
        return ImportJobResponse(
            id=job.id,
            account_id=job.account_id,
            kind=job.kind,
            status=job.status,
            progress=ImportJobProgress.model_validate(job.progress),
            result=ImportJobResult.model_validate(job.result) if job.result is not None else None,
            error=error,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            manual_retry_count=job.manual_retry_count,
            run_after=job.run_after,
            started_at=job.started_at,
            finished_at=job.finished_at,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )

    async def get_import_job(
        self, *, principal: AuthenticatedPrincipal, account_id: str, job_id: str
    ) -> ImportJobResponse:
        try:
            await require_account_access(
                session=self.session, principal=principal, account_id=account_id
            )
        except AccountNotFoundError as exc:
            raise BackgroundJobNotFoundError() from exc
        job = await self.repository.get_owned(
            user_id=principal.user_id, account_id=account_id, job_id=job_id
        )
        if job is None:
            raise BackgroundJobNotFoundError()
        return self.public_response(job)

    async def retry_import_job(
        self, *, principal: AuthenticatedPrincipal, account_id: str, job_id: str
    ) -> ImportJobResponse:
        try:
            try:
                await require_account_access(
                    session=self.session,
                    principal=principal,
                    account_id=account_id,
                    allowed_roles=WRITE_ROLES,
                    for_update=True,
                )
            except AccountNotFoundError as exc:
                raise BackgroundJobNotFoundError() from exc
            retry = await self.repository.retry_failed(
                user_id=principal.user_id, account_id=account_id, job_id=job_id, now=_now()
            )
            if retry is None:
                raise BackgroundJobNotFoundError()
            if not retry.retried:
                raise BackgroundJobRetryStateError()
            await self.session.commit()
            return self.public_response(retry.job)
        except Exception:
            await self.session.rollback()
            raise
