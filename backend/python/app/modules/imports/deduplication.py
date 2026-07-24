from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
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
from app.db.models.imports import ImportBatchModel, ImportLogModel, ImportRowModel
from app.modules.accounts.access import require_account_access
from app.modules.imports.models import ImportDeduplicateResponse
from app.modules.imports.repository import ImportBatchRepository
from app.shared.errors import ApplicationError

WRITE_ROLES = {
    AccountMemberRole.owner,
    AccountMemberRole.admin,
    AccountMemberRole.editor,
}


class ImportDeduplicateStateError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_deduplicate_state_invalid",
            message="The import batch is not available for duplicate detection.",
            status_code=409,
        )


class ImportDeduplicateRowsMissingError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_deduplicate_rows_missing",
            message="The import batch has no normalized rows for duplicate detection.",
            status_code=409,
        )


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _is_valid_row_state(row: ImportRowModel) -> bool:
    if row.status in {ImportRowStatus.pending, ImportRowStatus.duplicate}:
        if not isinstance(row.normalized_data, dict) or row.deduplication_key is None:
            return False
        if "posting_intent" in row.normalized_data:
            return False
        if (
            getattr(row, "created_transaction_id", None) is not None
            or getattr(row, "created_investment_event_id", None) is not None
        ):
            return False
        marker = row.normalized_data.get("deduplication")
        return marker is None or marker == {
            "schema_version": 1,
            "status": "unique" if row.status is ImportRowStatus.pending else "duplicate",
        }
    if row.status in {ImportRowStatus.failed, ImportRowStatus.needs_review}:
        return (
            row.normalized_data is None
            and row.deduplication_key is None
            and getattr(row, "created_transaction_id", None) is None
            and getattr(row, "created_investment_event_id", None) is None
        )
    if row.status is ImportRowStatus.skipped:
        return (
            isinstance(row.normalized_data, dict)
            and row.normalized_data.get("schema_version") == 2
            and row.normalized_data.get("source") == "anycoin"
            and row.normalized_data.get("kind")
            in {"group_member", "fully_refunded_group", "neutral_row"}
            and "posting_intent" not in row.normalized_data
            and "deduplication" not in row.normalized_data
            and row.deduplication_key is None
            and row.created_transaction_id is None
            and row.created_investment_event_id is None
        )
    return False


def _winner_ids(
    candidates: list[tuple[ImportRowModel, ImportBatchModel]],
) -> set[str]:
    by_key: dict[str, list[ImportRowModel]] = defaultdict(list)
    for row, _ in candidates:
        if row.deduplication_key is not None:
            by_key[row.deduplication_key].append(row)

    winners: set[str] = set()
    for rows in by_key.values():
        imported = [row for row in rows if row.status is ImportRowStatus.imported]
        if imported:
            winners.update(row.id for row in imported)
        else:
            winners.add(rows[0].id)
    return winners


class ImportDeduplicationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ImportBatchRepository(session)

    async def deduplicate_batch(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        batch_id: str,
    ) -> ImportDeduplicateResponse:
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
            raise ImportDeduplicateStateError()

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
                raise ImportDeduplicateStateError()

            rows = await self.repository.list_rows_for_update(batch_id)
            if not rows:
                raise ImportDeduplicateRowsMissingError()
            if not all(_is_valid_row_state(row) for row in rows):
                raise ImportDeduplicateStateError()

            keys = {
                row.deduplication_key
                for row in rows
                if row.status is ImportRowStatus.pending and row.deduplication_key is not None
            }
            candidates = await self.repository.list_deduplication_candidates_for_update(
                account_id=account_id,
                source=locked.source,
                deduplication_keys=keys,
            )
            winner_ids = _winner_ids(candidates)

            duplicate_counts: dict[str, int] = defaultdict(int)
            affected_batches: dict[str, ImportBatchModel] = {}
            for candidate, candidate_batch in candidates:
                if candidate.status is ImportRowStatus.pending and candidate.id not in winner_ids:
                    candidate.status = ImportRowStatus.duplicate
                    if isinstance(candidate.normalized_data, dict):
                        updated = dict(candidate.normalized_data)
                        updated["deduplication"] = {
                            "schema_version": 1,
                            "status": "duplicate",
                        }
                        updated.pop("posting_intent", None)
                        candidate.normalized_data = updated
                    candidate.validation_errors = None
                    candidate.error_message = "Duplicate normalized import row."
                    duplicate_counts[candidate_batch.id] += 1
                    affected_batches[candidate_batch.id] = candidate_batch

            for affected_batch_id, newly_duplicate in duplicate_counts.items():
                affected_batch = affected_batches[affected_batch_id]
                if affected_batch_id != batch_id:
                    affected_batch.rows_skipped = (
                        affected_batch.rows_skipped or 0
                    ) + newly_duplicate
                self.repository.add_log(
                    ImportLogModel(
                        id=str(uuid4()),
                        import_batch_id=affected_batch_id,
                        level=ImportLogLevel.warning,
                        event=ImportLogEvent.dedup_skipped,
                        message=f"Duplicate detection skipped {newly_duplicate} row(s).",
                        created_at=_now(),
                    )
                )

            for row in rows:
                if row.status in {ImportRowStatus.pending, ImportRowStatus.duplicate}:
                    assert isinstance(row.normalized_data, dict)
                    updated = dict(row.normalized_data)
                    updated["deduplication"] = {
                        "schema_version": 1,
                        "status": "unique"
                        if row.status is ImportRowStatus.pending
                        else "duplicate",
                    }
                    if row.status is ImportRowStatus.duplicate:
                        updated.pop("posting_intent", None)
                    row.normalized_data = updated

            duplicate_count = sum(row.status is ImportRowStatus.duplicate for row in rows)
            needs_review = sum(row.status is ImportRowStatus.needs_review for row in rows)
            failed = sum(row.status is ImportRowStatus.failed for row in rows)
            skipped = sum(row.status is ImportRowStatus.skipped for row in rows)
            unique = sum(row.status is ImportRowStatus.pending for row in rows)

            locked.rows_total = len(rows)
            locked.rows_imported = 0
            locked.rows_skipped = duplicate_count + needs_review + failed + skipped
            locked.completed_at = None
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return ImportDeduplicateResponse(
            batch_id=batch_id,
            status=ImportStatus.processing,
            rows_total=len(rows),
            rows_unique=unique,
            rows_duplicate=duplicate_count,
            rows_needs_review=needs_review,
            rows_failed=failed,
        )
