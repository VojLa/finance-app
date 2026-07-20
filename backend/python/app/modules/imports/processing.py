from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import (
    AccountMemberRole,
    ImportLogEvent,
    ImportLogLevel,
    ImportRowStatus,
    ImportStatus,
)
from app.db.models.imports import ImportLogModel, ImportRowModel
from app.modules.accounts.access import require_account_access
from app.modules.imports.models import ImportParseResponse
from app.modules.imports.parsers import ImportParseError, parse_import_file
from app.modules.imports.repository import ImportBatchRepository
from app.modules.imports.storage import LocalImportStorage
from app.shared.errors import ApplicationError

PARSER_MAX_BYTES = 64 * 1024 * 1024
WRITE_ROLES = {
    AccountMemberRole.owner,
    AccountMemberRole.admin,
    AccountMemberRole.editor,
}


class ImportFileMissingError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_file_missing",
            message="The verified import file is not available.",
            status_code=409,
        )


class ImportFileInvalidError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_file_invalid",
            message="The stored import file does not match the registered metadata.",
            status_code=409,
        )


class ImportParseStateError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_parse_state_invalid",
            message="The import batch is not available for parsing.",
            status_code=409,
        )


class ImportParseFailedError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__(code="import_parse_failed", message=message, status_code=422)


class ImportParseFileTooLargeError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_parse_file_too_large",
            message="The import file exceeds the synchronous parser size limit.",
            status_code=413,
        )


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class ImportParserService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        storage: LocalImportStorage | None = None,
    ) -> None:
        self.session = session
        self.repository = ImportBatchRepository(session)
        self.storage = storage or LocalImportStorage()

    async def parse_batch(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        batch_id: str,
    ) -> ImportParseResponse:
        await require_account_access(
            session=self.session,
            principal=principal,
            account_id=account_id,
            allowed_roles=WRITE_ROLES,
        )
        batch = await self.repository.get_for_account(account_id=account_id, batch_id=batch_id)
        if batch is None:
            from app.modules.imports.service import ImportBatchNotFoundError

            raise ImportBatchNotFoundError()
        if batch.status is not ImportStatus.pending:
            raise ImportParseStateError()

        try:
            content = self._load_verified_file(
                batch_id=batch.id,
                expected_size=batch.file_size,
                expected_checksum=batch.checksum,
            )
            parsed_rows = parse_import_file(
                batch.source,
                content,
                encoding=batch.file_encoding,
            )
        except (ImportFileMissingError, ImportFileInvalidError, ImportParseError) as exc:
            await self._record_fatal_failure(
                account_id=account_id,
                batch_id=batch_id,
                message=str(exc),
            )
            if isinstance(exc, ApplicationError):
                raise
            raise ImportParseFailedError(str(exc)) from None
        except ImportParseFileTooLargeError as exc:
            await self._record_fatal_failure(
                account_id=account_id,
                batch_id=batch_id,
                message=exc.message,
            )
            raise

        locked = await self.repository.get_for_account(
            account_id=account_id,
            batch_id=batch_id,
            for_update=True,
        )
        if locked is None:
            from app.modules.imports.service import ImportBatchNotFoundError

            raise ImportBatchNotFoundError()
        if locked.status is not ImportStatus.pending or await self.repository.count_rows(batch_id):
            raise ImportParseStateError()

        try:
            now = _now()
            failed = 0
            for parsed in parsed_rows:
                status = ImportRowStatus.failed if parsed.error_message else ImportRowStatus.pending
                failed += int(status is ImportRowStatus.failed)
                self.repository.add_row(
                    ImportRowModel(
                        id=str(uuid4()),
                        import_batch_id=batch_id,
                        row_number=parsed.row_number,
                        raw_data=parsed.raw_data,
                        normalized_data=None,
                        validation_errors=parsed.validation_errors,
                        deduplication_key=None,
                        status=status,
                        error_message=parsed.error_message,
                        created_transaction_id=None,
                        created_investment_event_id=None,
                        created_at=now,
                    )
                )

            locked.status = ImportStatus.processing
            locked.rows_total = len(parsed_rows)
            locked.rows_imported = 0
            locked.rows_skipped = failed
            locked.completed_at = None
            if failed:
                self.repository.add_log(
                    ImportLogModel(
                        id=str(uuid4()),
                        import_batch_id=batch_id,
                        level=ImportLogLevel.warning,
                        event=ImportLogEvent.parse_error,
                        message=f"Parser preserved {failed} row(s) with issues.",
                        created_at=now,
                    )
                )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return ImportParseResponse(
            batch_id=batch_id,
            status=ImportStatus.processing,
            rows_total=len(parsed_rows),
            rows_pending=len(parsed_rows) - failed,
            rows_failed=failed,
        )

    def _load_verified_file(
        self,
        *,
        batch_id: str,
        expected_size: int | None,
        expected_checksum: str,
    ) -> bytes:
        path = self.storage.path_for(batch_id)
        if not path.is_file():
            raise ImportFileMissingError()
        size = path.stat().st_size
        if size > PARSER_MAX_BYTES:
            raise ImportParseFileTooLargeError()
        content = path.read_bytes()
        if (expected_size is not None and len(content) != expected_size) or sha256(
            content
        ).hexdigest() != expected_checksum:
            raise ImportFileInvalidError()
        return content

    async def _record_fatal_failure(
        self,
        *,
        account_id: str,
        batch_id: str,
        message: str,
    ) -> None:
        locked = await self.repository.get_for_account(
            account_id=account_id,
            batch_id=batch_id,
            for_update=True,
        )
        if locked is None or locked.status is not ImportStatus.pending:
            raise ImportParseStateError()
        try:
            now = _now()
            locked.status = ImportStatus.failed
            locked.rows_total = 0
            locked.rows_imported = 0
            locked.rows_skipped = 0
            locked.completed_at = now
            self.repository.add_log(
                ImportLogModel(
                    id=str(uuid4()),
                    import_batch_id=batch_id,
                    level=ImportLogLevel.error,
                    event=ImportLogEvent.failed,
                    message=message[:1000],
                    created_at=now,
                )
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
