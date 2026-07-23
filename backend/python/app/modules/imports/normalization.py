from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import AccountMemberRole, ImportRowStatus, ImportStatus
from app.modules.accounts.access import require_account_access
from app.modules.imports.models import ImportNormalizeResponse
from app.modules.imports.normalizers import normalize_import_row
from app.modules.imports.repository import ImportBatchRepository
from app.shared.errors import ApplicationError

WRITE_ROLES = {
    AccountMemberRole.owner,
    AccountMemberRole.admin,
    AccountMemberRole.editor,
}


class ImportNormalizeStateError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_normalize_state_invalid",
            message="The import batch is not available for normalization.",
            status_code=409,
        )


class ImportNormalizeRowsMissingError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_normalize_rows_missing",
            message="The import batch has no parsed rows to normalize.",
            status_code=409,
        )


class ImportNormalizationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ImportBatchRepository(session)

    async def normalize_batch(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        batch_id: str,
    ) -> ImportNormalizeResponse:
        await require_account_access(
            session=self.session,
            principal=principal,
            account_id=account_id,
            allowed_roles=WRITE_ROLES,
        )
        batch = await self.repository.get_for_account(
            account_id=account_id,
            batch_id=batch_id,
        )
        if batch is None:
            from app.modules.imports.service import ImportBatchNotFoundError

            raise ImportBatchNotFoundError()
        if batch.status is not ImportStatus.processing:
            raise ImportNormalizeStateError()

        try:
            await self.repository.lock_deduplication_scope(
                account_id=account_id,
                source=batch.source,
            )
            locked = await self.repository.get_for_account(
                account_id=account_id,
                batch_id=batch_id,
                for_update=True,
            )
            if locked is None:
                from app.modules.imports.service import ImportBatchNotFoundError

                raise ImportBatchNotFoundError()
            if locked.status is not ImportStatus.processing:
                raise ImportNormalizeStateError()

            rows = await self.repository.list_rows_for_update(batch_id)
            if not rows:
                raise ImportNormalizeRowsMissingError()
            if any(
                row.normalized_data is not None or row.deduplication_key is not None for row in rows
            ):
                raise ImportNormalizeStateError()
            if any(
                row.status not in {ImportRowStatus.pending, ImportRowStatus.failed} for row in rows
            ):
                raise ImportNormalizeStateError()

            normalized = 0
            needs_review = 0
            parser_failed = 0
            for row in rows:
                if row.status is ImportRowStatus.failed:
                    parser_failed += 1
                    continue
                result = normalize_import_row(
                    source=locked.source,
                    account_id=account_id,
                    raw_data=row.raw_data,
                )
                if result.validation_errors:
                    row.normalized_data = None
                    row.deduplication_key = None
                    row.validation_errors = result.validation_errors
                    row.error_message = "Row requires normalization review."
                    row.status = ImportRowStatus.needs_review
                    needs_review += 1
                    continue
                row.normalized_data = result.data
                row.deduplication_key = result.deduplication_key
                row.validation_errors = None
                row.error_message = None
                row.status = ImportRowStatus.pending
                normalized += 1

            locked.rows_total = len(rows)
            locked.rows_imported = 0
            # Step 5D retains the legacy counter: "skipped" temporarily means rows that
            # cannot advance without review (parser failures plus normalization review).
            locked.rows_skipped = parser_failed + needs_review
            locked.completed_at = None
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return ImportNormalizeResponse(
            batch_id=batch_id,
            status=ImportStatus.processing,
            rows_total=len(rows),
            rows_normalized=normalized,
            rows_needs_review=needs_review,
            rows_failed=parser_failed,
        )
