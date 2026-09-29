from __future__ import annotations

import asyncio
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
    ImportSource,
    ImportStatus,
)
from app.db.models.imports import ImportLogModel, ImportRowModel
from app.modules.accounts.access import require_account_access
from app.modules.imports.models import ImportParseResponse
from app.modules.imports.parsers import ImportParseError, ParsedImportRow, parse_import_file
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
            message="The import file exceeds the parser size limit for this import worker.",
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
            replay = await self._reconcile_parse_replay(batch=batch)
            if replay is not None:
                return replay
            raise ImportParseStateError()

        try:
            parsed_rows = await asyncio.to_thread(
                self._load_and_parse_verified_file,
                batch_id=batch.id,
                expected_size=batch.file_size,
                expected_checksum=batch.checksum,
                source=batch.source,
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

    async def _reconcile_parse_replay(
        self,
        *,
        batch: object,
    ) -> ImportParseResponse | None:
        """Return only an exact persisted parse replay; never repair a batch."""

        status = getattr(batch, "status", None)
        batch_id = getattr(batch, "id", None)
        if not isinstance(batch_id, str) or not batch_id:
            raise ImportParseStateError()
        if status not in {
            ImportStatus.processing,
            ImportStatus.completed,
            ImportStatus.partially_completed,
            ImportStatus.failed,
        }:
            return None
        rows = await self.repository.list_rows_for_update(batch_id)
        rows_total = getattr(batch, "rows_total", None)
        rows_imported = getattr(batch, "rows_imported", None)
        rows_skipped = getattr(batch, "rows_skipped", None)
        completed_at = getattr(batch, "completed_at", None)
        if (
            not isinstance(rows_total, int)
            or isinstance(rows_total, bool)
            or rows_total < 0
            or len(rows) != rows_total
            or not isinstance(rows_imported, int)
            or isinstance(rows_imported, bool)
            or rows_imported < 0
            or not isinstance(rows_skipped, int)
            or isinstance(rows_skipped, bool)
            or rows_skipped < 0
        ):
            raise ImportParseStateError()
        failed = sum(row.status is ImportRowStatus.failed for row in rows)
        pending = sum(row.status is ImportRowStatus.pending for row in rows)
        imported = sum(row.status is ImportRowStatus.imported for row in rows)
        if status is ImportStatus.processing:
            if (
                completed_at is not None
                or rows_imported != 0
                or rows_skipped != rows_total - pending
            ):
                raise ImportParseStateError()
        elif status in {ImportStatus.completed, ImportStatus.partially_completed}:
            if (
                completed_at is None
                or pending
                or rows_imported != imported
                or rows_imported + rows_skipped != rows_total
            ):
                raise ImportParseStateError()
        elif status is ImportStatus.failed:
            # A terminal parser failure has no successful parse result to replay.
            await self.session.rollback()
            return None
        else:
            raise ImportParseStateError()
        await self.session.rollback()
        return ImportParseResponse(
            batch_id=batch_id,
            status=ImportStatus.processing,
            rows_total=rows_total,
            # The parse contract reports its original usable rows.  Later stages
            # intentionally change a row's status, so their current pending count
            # must never be presented as a parse replay result.
            rows_pending=rows_total - failed,
            rows_failed=failed,
        )

    def _load_and_parse_verified_file(
        self,
        *,
        batch_id: str,
        expected_size: int | None,
        expected_checksum: str,
        source: ImportSource,
        encoding: str | None,
    ) -> list[ParsedImportRow]:
        content = self._load_verified_file(
            batch_id=batch_id,
            expected_size=expected_size,
            expected_checksum=expected_checksum,
        )
        return parse_import_file(source, content, encoding=encoding)

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
