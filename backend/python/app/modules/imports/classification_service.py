"""Persisted, idempotent classification after import deduplication."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import AccountMemberRole, ImportRowStatus, ImportStatus
from app.db.models.imports import ImportRowModel
from app.modules.accounts.access import require_account_access
from app.modules.imports.classification import classify_import_row
from app.modules.imports.models import ImportClassifyResponse
from app.modules.imports.repository import ImportBatchRepository
from app.shared.errors import ApplicationError

WRITE_ROLES = {AccountMemberRole.owner, AccountMemberRole.admin, AccountMemberRole.editor}
_MARKER = "deduplication"
_INTENT = "posting_intent"


class ImportClassifyStateError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_classify_state_invalid",
            message="The import batch is not available for classification.",
            status_code=409,
        )


class ImportClassifyRowsMissingError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_classify_rows_missing",
            message="The import batch has no rows for classification.",
            status_code=409,
        )


def _marker_is(data: dict[str, Any], status: str) -> bool:
    return data.get(_MARKER) == {"schema_version": 1, "status": status}


def _canonical(data: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(data)
    result.pop(_MARKER, None)
    result.pop(_INTENT, None)
    return result


def _valid_skipped(row: ImportRowModel) -> bool:
    return (
        isinstance(row.normalized_data, dict)
        and row.normalized_data.get("schema_version") == 2
        and row.normalized_data.get("source") == "anycoin"
        and row.normalized_data.get("kind")
        in {"group_member", "fully_refunded_group", "neutral_row"}
        and _INTENT not in row.normalized_data
    )


class ImportClassificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ImportBatchRepository(session)

    async def classify_batch(
        self, *, principal: AuthenticatedPrincipal, account_id: str, batch_id: str
    ) -> ImportClassifyResponse:
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
        if batch.status is not ImportStatus.processing:
            raise ImportClassifyStateError()
        try:
            await self.repository.lock_deduplication_scope(
                account_id=account_id, source=batch.source
            )
            batch = await self.repository.get_for_account(
                account_id=account_id, batch_id=batch_id, for_update=True
            )
            if batch is None or batch.status is not ImportStatus.processing:
                raise ImportClassifyStateError()
            rows = await self.repository.list_rows_for_update(batch_id)
            if not rows:
                raise ImportClassifyRowsMissingError()
            for row in rows:
                if (
                    row.created_transaction_id
                    or row.created_investment_event_id
                    or row.status is ImportRowStatus.imported
                ):
                    raise ImportClassifyStateError()
                if row.status is ImportRowStatus.pending:
                    if (
                        not isinstance(row.normalized_data, dict)
                        or not row.deduplication_key
                        or not _marker_is(row.normalized_data, "unique")
                    ):
                        raise ImportClassifyStateError()
                elif row.status is ImportRowStatus.duplicate:
                    if (
                        not isinstance(row.normalized_data, dict)
                        or not _marker_is(row.normalized_data, "duplicate")
                        or _INTENT in row.normalized_data
                    ):
                        raise ImportClassifyStateError()
                elif row.status is ImportRowStatus.skipped and not _valid_skipped(row):
                    raise ImportClassifyStateError()
                elif row.status is ImportRowStatus.failed and (
                    row.normalized_data is not None or row.deduplication_key is not None
                ):
                    raise ImportClassifyStateError()
                elif (
                    row.status is ImportRowStatus.needs_review
                    and row.normalized_data is None
                    and row.deduplication_key is None
                ):
                    continue
                elif row.status is ImportRowStatus.needs_review and not isinstance(
                    row.normalized_data, dict
                ):
                    raise ImportClassifyStateError()
            for row in rows:
                if row.status is not ImportRowStatus.pending:
                    continue
                assert isinstance(row.normalized_data, dict)
                intent = classify_import_row(
                    source=batch.source, normalized_data=_canonical(row.normalized_data)
                ).model_dump(mode="json")
                stored = row.normalized_data.get(_INTENT)
                if stored is not None:
                    if stored != intent:
                        raise ImportClassifyStateError()
                    continue
                row.normalized_data[_INTENT] = intent
                if intent["target"] == "needs_review":
                    row.status = ImportRowStatus.needs_review
                    row.validation_errors = intent["errors"]
                    row.error_message = "Row requires classification review."
                else:
                    row.validation_errors = None
                    row.error_message = None
            classified = sum(
                row.status is ImportRowStatus.pending
                and isinstance(row.normalized_data, dict)
                and _INTENT in row.normalized_data
                for row in rows
            )
            review = sum(row.status is ImportRowStatus.needs_review for row in rows)
            duplicate = sum(row.status is ImportRowStatus.duplicate for row in rows)
            skipped = sum(row.status is ImportRowStatus.skipped for row in rows)
            failed = sum(row.status is ImportRowStatus.failed for row in rows)
            batch.rows_total = len(rows)
            batch.rows_imported = 0
            batch.rows_skipped = review + duplicate + skipped + failed
            batch.completed_at = None
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return ImportClassifyResponse(
            batch_id=batch_id,
            status=ImportStatus.processing,
            rows_total=len(rows),
            rows_classified=classified,
            rows_needs_review=review,
            rows_duplicate=duplicate,
            rows_skipped=skipped,
            rows_failed=failed,
        )
