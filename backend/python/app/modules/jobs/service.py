from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountModel
from app.db.models.background_jobs import BackgroundJobModel
from app.db.models.enums import (
    AccountMemberRole,
    BackgroundJobKind,
    BackgroundJobStatus,
    ImportSource,
    ImportStatus,
)
from app.db.models.imports import ImportBatchModel
from app.modules.accounts.access import AccountNotFoundError, require_account_access
from app.modules.imports.models import (
    ImportBatchCreateRequest,
    ImportRegistrationResponse,
    ImportRegistrationResumeJobResponse,
    ImportRegistrationUploadRequiredResponse,
)
from app.modules.imports.repository import ImportBatchRepository
from app.modules.imports.service import (
    ImportBatchAlreadyImportedError,
    ImportBatchNotReusableError,
    ImportBatchService,
)
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


class ImportRegistrationStateError(ImportBatchNotReusableError):
    """Fail closed when durable registration evidence is inconsistent."""


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

    async def register_import_batch(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        payload: ImportBatchCreateRequest,
    ) -> ImportRegistrationResponse:
        """Register one exact file and safely recover its canonical workflow.

        This is intentionally jobs-owned: a batch state alone cannot prove that
        it may be resumed.  The account and exact batch rows are locked until
        the response decision is committed.  The job lookup remains an MVCC
        read so it cannot invert the completion lock order; a concurrent status
        transition safely resolves as either resume-now or already-completed.
        """

        try:
            await require_account_access(
                session=self.session,
                principal=principal,
                account_id=account_id,
                allowed_roles=WRITE_ROLES,
                for_update=True,
            )
            account = await self.session.scalar(
                select(AccountModel.id).where(AccountModel.id == account_id).with_for_update()
            )
            if account is None:
                # Authorization already hides foreign accounts.  This only
                # protects a concurrent account deletion from creating state.
                raise ImportRegistrationStateError()

            registered = await ImportBatchService(self.session).register_exact_batch(
                principal=principal,
                account_id=account_id,
                payload=payload,
            )
            batch = registered.batch
            matches = await self.repository.find_owned_import_jobs_for_batch(
                user_id=principal.user_id,
                account_id=account_id,
                batch_id=batch.id,
            )
            response = self._registration_response(
                principal=principal,
                batch=batch,
                matches=matches,
            )
            await self.session.commit()
            return response
        except Exception:
            await self.session.rollback()
            raise

    @classmethod
    def _registration_response(
        cls,
        *,
        principal: AuthenticatedPrincipal,
        batch: ImportBatchModel,
        matches: list[BackgroundJobModel],
    ) -> ImportRegistrationResponse:
        if len(matches) > 1:
            raise ImportRegistrationStateError()
        if len(matches) == 1:
            job = matches[0]
            try:
                if (
                    job.user_id != principal.user_id
                    or job.account_id != batch.account_id
                    or job.kind is not BackgroundJobKind.import_workflow
                ):
                    raise ValueError("The matched job ownership is inconsistent.")
                parsed_payload = ImportJobPayload.model_validate(job.payload)
                if (
                    parsed_payload.model_dump(mode="json") != job.payload
                    or batch.id not in parsed_payload.batch_ids
                ):
                    raise ValueError("The matched job payload is not canonical.")
            except (AttributeError, TypeError, ValidationError, ValueError):
                raise ImportRegistrationStateError() from None

            if job.status in {
                BackgroundJobStatus.queued,
                BackgroundJobStatus.running,
                BackgroundJobStatus.retry_wait,
                BackgroundJobStatus.failed,
            }:
                try:
                    return ImportRegistrationResumeJobResponse(
                        status="resume_job",
                        job=cls.public_response(job),
                    )
                except (AttributeError, TypeError, ValidationError, ValueError):
                    raise ImportRegistrationStateError() from None
            if job.status is BackgroundJobStatus.completed and batch.status in {
                ImportStatus.completed,
                ImportStatus.partially_completed,
            }:
                raise ImportBatchAlreadyImportedError()
            raise ImportRegistrationStateError()

        if batch.status is ImportStatus.pending:
            try:
                return ImportRegistrationUploadRequiredResponse(
                    status="upload_required",
                    batch=ImportBatchService._response(batch),
                )
            except (AttributeError, TypeError, ValidationError, ValueError):
                raise ImportRegistrationStateError() from None
        if batch.status in {
            ImportStatus.completed,
            ImportStatus.partially_completed,
        }:
            raise ImportBatchAlreadyImportedError()
        raise ImportBatchNotReusableError()

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
                await self.repository.reconcile_import_job_manifest(
                    job=existing,
                    user_id=command.principal.user_id,
                    account_id=command.account_id,
                    batch_ids=payload.batch_ids,
                    now=_now(),
                    create_if_missing=False,
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
                    total_units=(5 * total_batches) + 4,
                    completed_batches=0,
                    total_batches=total_batches,
                ).model_dump(mode="json"),
                max_attempts=MAX_AUTOMATIC_ATTEMPTS,
                now=_now(),
            )
            if enqueued.job.payload != payload.model_dump(mode="json"):
                raise RuntimeError("The canonical background job payload does not match replay.")
            await self.repository.reconcile_import_job_manifest(
                job=enqueued.job,
                user_id=command.principal.user_id,
                account_id=command.account_id,
                batch_ids=payload.batch_ids,
                now=_now(),
                create_if_missing=enqueued.created,
            )
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
