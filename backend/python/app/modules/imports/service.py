from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import (
    AccountMemberRole,
    ImportLogEvent,
    ImportLogLevel,
    ImportStatus,
)
from app.db.models.imports import ImportBatchModel, ImportLogModel
from app.modules.accounts.access import require_account_access
from app.modules.imports.models import (
    ImportBatchCreateRequest,
    ImportBatchResponse,
    ImportUploadResponse,
)
from app.modules.imports.repository import ImportBatchRepository
from app.modules.imports.storage import ImportFileTooLargeError, LocalImportStorage
from app.shared.errors import ApplicationError

WRITE_ROLES = {
    AccountMemberRole.owner,
    AccountMemberRole.admin,
    AccountMemberRole.editor,
}
MAX_UPLOAD_BYTES = 1_073_741_824


class ImportBatchNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_batch_not_found",
            message="The import batch was not found.",
            status_code=404,
        )


class ImportBatchExistsError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_batch_exists",
            message="An import batch with this checksum already exists.",
            status_code=409,
        )


class ImportUploadContentTypeError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_upload_content_type_invalid",
            message="The upload must use application/octet-stream.",
            status_code=415,
        )


class ImportUploadTooLargeError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_upload_too_large",
            message="The uploaded file exceeds the allowed size.",
            status_code=413,
        )


class ImportUploadMismatchError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_upload_mismatch",
            message="The uploaded file does not match the registered metadata.",
            status_code=422,
        )


class ImportUploadStateError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_upload_state_invalid",
            message="The import batch does not accept a raw file upload in its current state.",
            status_code=409,
        )


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ImportBatchService:
    def __init__(self, session: AsyncSession, storage: LocalImportStorage | None = None) -> None:
        self.session = session
        self.repository = ImportBatchRepository(session)
        self.storage = storage or LocalImportStorage()

    async def create_batch(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        payload: ImportBatchCreateRequest,
    ) -> ImportBatchResponse:
        await require_account_access(
            session=self.session,
            principal=principal,
            account_id=account_id,
            allowed_roles=WRITE_ROLES,
        )
        existing = await self.repository.get_by_checksum(
            user_id=principal.user_id,
            account_id=account_id,
            checksum=payload.checksum,
        )
        if existing is not None:
            raise ImportBatchExistsError()

        now = _now()
        batch = ImportBatchModel(
            id=str(uuid4()),
            user_id=principal.user_id,
            account_id=account_id,
            source=payload.source,
            filename=payload.filename,
            file_size=payload.file_size,
            file_encoding=payload.file_encoding,
            checksum=payload.checksum,
            status=ImportStatus.pending,
            rows_total=None,
            rows_imported=None,
            rows_skipped=None,
            created_at=now,
            completed_at=None,
            retain_until=None,
            raw_data_purged_at=None,
        )
        log = ImportLogModel(
            id=str(uuid4()),
            import_batch_id=batch.id,
            level=ImportLogLevel.info,
            event=ImportLogEvent.started,
            message="Import batch registered and awaiting processing.",
            created_at=now,
        )

        try:
            self.repository.add_batch(batch)
            await self.session.flush()
            self.repository.add_log(log)
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            duplicate = await self.repository.get_by_checksum(
                user_id=principal.user_id,
                account_id=account_id,
                checksum=payload.checksum,
            )
            if duplicate is not None:
                raise ImportBatchExistsError() from None
            raise
        except Exception:
            await self.session.rollback()
            raise

        return self._response(batch)

    async def upload_file(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        batch_id: str,
        content_type: str | None,
        chunks: AsyncIterator[bytes],
    ) -> ImportUploadResponse:
        await require_account_access(
            session=self.session,
            principal=principal,
            account_id=account_id,
            allowed_roles=WRITE_ROLES,
        )
        batch = await self.repository.get_for_account(account_id=account_id, batch_id=batch_id)
        if batch is None:
            raise ImportBatchNotFoundError()
        if batch.status is not ImportStatus.pending:
            raise ImportUploadStateError()
        if content_type is None or content_type.split(";", 1)[0].strip().lower() != "application/octet-stream":
            raise ImportUploadContentTypeError()

        maximum = batch.file_size if batch.file_size is not None else MAX_UPLOAD_BYTES
        try:
            stored = await self.storage.store(batch_id=batch.id, chunks=chunks, max_bytes=maximum)
        except ImportFileTooLargeError:
            raise ImportUploadTooLargeError() from None

        size_matches = batch.file_size is None or stored.size == batch.file_size
        checksum_matches = stored.checksum == batch.checksum
        if not size_matches or not checksum_matches:
            if stored.created:
                self.storage.remove(batch.id)
            raise ImportUploadMismatchError()

        return ImportUploadResponse(
            batch_id=batch.id,
            size=stored.size,
            checksum=stored.checksum,
            stored=True,
            idempotent=not stored.created,
        )

    async def list_batches(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
    ) -> list[ImportBatchResponse]:
        await require_account_access(
            session=self.session,
            principal=principal,
            account_id=account_id,
        )
        return [
            self._response(batch) for batch in await self.repository.list_for_account(account_id)
        ]

    async def get_batch(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        batch_id: str,
    ) -> ImportBatchResponse:
        await require_account_access(
            session=self.session,
            principal=principal,
            account_id=account_id,
        )
        batch = await self.repository.get_for_account(account_id=account_id, batch_id=batch_id)
        if batch is None:
            raise ImportBatchNotFoundError()
        return self._response(batch)

    @staticmethod
    def _response(batch: ImportBatchModel) -> ImportBatchResponse:
        return ImportBatchResponse(
            id=batch.id,
            account_id=batch.account_id,
            source=batch.source,
            filename=batch.filename,
            file_size=batch.file_size,
            file_encoding=batch.file_encoding,
            checksum=batch.checksum,
            status=batch.status,
            rows_total=batch.rows_total,
            rows_imported=batch.rows_imported,
            rows_skipped=batch.rows_skipped,
            created_at=batch.created_at,
            completed_at=batch.completed_at,
        )
