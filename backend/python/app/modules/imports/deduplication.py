from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from copy import deepcopy
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
from app.db.models.imports import (
    ImportBatchModel,
    ImportLogModel,
    ImportRowModel,
    ImportSourceOccurrenceModel,
)
from app.modules.accounts.access import require_account_access
from app.modules.imports.cooperative import yield_after_rows
from app.modules.imports.models import ImportDeduplicateResponse
from app.modules.imports.posting_common import copied_canonical_payload
from app.modules.imports.raiffeisenbank import STATEMENT_KIND_FIELD
from app.modules.imports.raiffeisenbank_card_multiset import (
    RaiffeisenbankCardCandidate,
    RaiffeisenbankCardMultisetEvidenceError,
    plan_raiffeisenbank_card_multiset,
)
from app.modules.imports.raiffeisenbank_card_occurrence_repository import (
    RaiffeisenbankCardOccurrenceRepository,
)
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
    return _winner_ids_from_groups(by_key.values())


def _winner_ids_from_groups(rows_by_key: Iterable[list[ImportRowModel]]) -> set[str]:
    """Keep the small, pure winner-selection boundary synchronously testable."""

    winners: set[str] = set()
    for rows in rows_by_key:
        imported = [row for row in rows if row.status is ImportRowStatus.imported]
        if imported:
            winners.update(row.id for row in imported)
        else:
            winners.add(rows[0].id)
    return winners


async def _winner_ids_cooperatively(
    candidates: list[tuple[ImportRowModel, ImportBatchModel]],
) -> set[str]:
    by_key: dict[str, list[ImportRowModel]] = defaultdict(list)
    for index, (row, _) in enumerate(candidates, start=1):
        if row.deduplication_key is not None:
            by_key[row.deduplication_key].append(row)
        await yield_after_rows(index)

    winners: set[str] = set()
    for index, rows in enumerate(by_key.values(), start=1):
        imported = [row for row in rows if row.status is ImportRowStatus.imported]
        if imported:
            winners.update(row.id for row in imported)
        else:
            winners.add(rows[0].id)
        await yield_after_rows(index)
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
        job_id: str | None = None,
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
            keys: set[str] = set()
            for index, row in enumerate(rows, start=1):
                if not _is_valid_row_state(row):
                    raise ImportDeduplicateStateError()
                if row.status is ImportRowStatus.pending and row.deduplication_key is not None:
                    keys.add(row.deduplication_key)
                await yield_after_rows(index)

            manifest_response = await self._deduplicate_manifested_raiffeisenbank_cards(
                principal=principal,
                account_id=account_id,
                batch_id=batch_id,
                job_id=job_id,
                current_rows=rows,
                locked_batch=locked,
            )
            if manifest_response is not None:
                await self.session.commit()
                return manifest_response
            candidates = await self.repository.list_deduplication_candidates_for_update(
                account_id=account_id,
                source=locked.source,
                deduplication_keys=keys,
            )
            winner_ids = await _winner_ids_cooperatively(candidates)

            duplicate_counts: dict[str, int] = defaultdict(int)
            affected_batches: dict[str, ImportBatchModel] = {}
            for index, (candidate, candidate_batch) in enumerate(candidates, start=1):
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
                await yield_after_rows(index)

            for index, (affected_batch_id, newly_duplicate) in enumerate(
                duplicate_counts.items(), start=1
            ):
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
                await yield_after_rows(index)

            for index, row in enumerate(rows, start=1):
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
                await yield_after_rows(index)

            duplicate_count = needs_review = failed = skipped = unique = 0
            for index, row in enumerate(rows, start=1):
                duplicate_count += row.status is ImportRowStatus.duplicate
                needs_review += row.status is ImportRowStatus.needs_review
                failed += row.status is ImportRowStatus.failed
                skipped += row.status is ImportRowStatus.skipped
                unique += row.status is ImportRowStatus.pending
                await yield_after_rows(index)

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

    async def _deduplicate_manifested_raiffeisenbank_cards(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        batch_id: str,
        job_id: str | None,
        current_rows: list[ImportRowModel],
        locked_batch: ImportBatchModel,
    ) -> ImportDeduplicateResponse | None:
        """Apply the RB-2 multiset only inside one durable job manifest."""
        if job_id is None or locked_batch.source.value != "raiffeisenbank":
            return None
        if not isinstance(job_id, str) or not job_id or job_id != job_id.strip():
            raise ImportDeduplicateStateError()
        occurrence_repository = RaiffeisenbankCardOccurrenceRepository(self.session)
        manifested = await occurrence_repository.load_manifested_card_rows_for_update(
            job_id=job_id,
            user_id=principal.user_id,
            account_id=account_id,
        )
        if manifested is None:
            raise ImportDeduplicateStateError()
        if not manifested.is_credit_card_account:
            return None
        if batch_id not in {batch.id for batch in manifested.batches}:
            raise ImportDeduplicateStateError()

        candidates: list[RaiffeisenbankCardCandidate] = []
        rows_by_id: dict[str, ImportRowModel] = {}
        batch_by_row_id: dict[str, ImportBatchModel] = {}
        for index, (row, batch) in enumerate(manifested.rows, start=1):
            if not _is_valid_row_state(row):
                raise ImportDeduplicateStateError()
            if row.status in {ImportRowStatus.pending, ImportRowStatus.duplicate}:
                if (
                    not isinstance(row.raw_data, dict)
                    or row.raw_data.get(STATEMENT_KIND_FIELD) != "card_statement"
                    or not isinstance(row.normalized_data, dict)
                ):
                    raise ImportDeduplicateStateError()
                candidates.append(
                    RaiffeisenbankCardCandidate(
                        batch_id=batch.id,
                        row_id=row.id,
                        row_number=row.row_number,
                        raw_data=row.raw_data,
                        normalized_data=_card_multiset_normalized_payload(row),
                    )
                )
                rows_by_id[row.id] = row
                batch_by_row_id[row.id] = batch
            await yield_after_rows(index)
        if not candidates:
            raise ImportDeduplicateRowsMissingError()
        try:
            plan = plan_raiffeisenbank_card_multiset(
                account_id=account_id,
                candidates=candidates,
            )
        except RaiffeisenbankCardMultisetEvidenceError as exc:
            raise ImportDeduplicateStateError() from exc

        for index, occurrence in enumerate(plan.occurrences, start=1):
            existing = await occurrence_repository.get_occurrence_for_update(
                account_id=account_id,
                fingerprint_hash=occurrence.fingerprint,
                ordinal=occurrence.occurrence_ordinal,
            )
            member_ids = (occurrence.canonical_row_id, *occurrence.duplicate_row_ids)
            canonical_row_id = occurrence.canonical_row_id
            if existing is None:
                occurrence_repository.add_occurrence(
                    ImportSourceOccurrenceModel(
                        id=f"rb-occurrence-{occurrence.deduplication_key}",
                        account_id=account_id,
                        source=locked_batch.source,
                        fingerprint_hash=occurrence.fingerprint,
                        ordinal=occurrence.occurrence_ordinal,
                        representative_import_row_id=canonical_row_id,
                        representative_import_batch_id=batch_by_row_id[canonical_row_id].id,
                        canonical_transaction_id=None,
                        version=1,
                        flags={"deduplication_key": occurrence.deduplication_key},
                        created_at=_now(),
                        updated_at=_now(),
                    )
                )
            else:
                if (
                    existing.source is not locked_batch.source
                    or existing.version != 1
                    or existing.flags != {"deduplication_key": occurrence.deduplication_key}
                    or (
                        existing.representative_import_row_id not in member_ids
                        and existing.canonical_transaction_id is None
                    )
                ):
                    raise ImportDeduplicateStateError()
                if existing.representative_import_row_id not in member_ids:
                    canonical_row_id = ""
                else:
                    canonical_row_id = existing.representative_import_row_id

            for row_id in member_ids:
                row = rows_by_id[row_id]
                row.deduplication_key = occurrence.deduplication_key
                updated = copied_canonical_payload(row.normalized_data or {})
                is_canonical = row_id == canonical_row_id
                row.status = ImportRowStatus.pending if is_canonical else ImportRowStatus.duplicate
                updated["deduplication"] = {
                    "schema_version": 1,
                    "status": "unique" if is_canonical else "duplicate",
                }
                row.normalized_data = updated
                row.validation_errors = None
                row.error_message = None if is_canonical else "Duplicate normalized import row."
            await yield_after_rows(index)

        duplicate_count = sum(row.status is ImportRowStatus.duplicate for row in current_rows)
        needs_review = sum(row.status is ImportRowStatus.needs_review for row in current_rows)
        failed = sum(row.status is ImportRowStatus.failed for row in current_rows)
        skipped = sum(row.status is ImportRowStatus.skipped for row in current_rows)
        unique = sum(row.status is ImportRowStatus.pending for row in current_rows)
        locked_batch.rows_total = len(current_rows)
        locked_batch.rows_imported = 0
        locked_batch.rows_skipped = duplicate_count + needs_review + failed + skipped
        locked_batch.completed_at = None
        return ImportDeduplicateResponse(
            batch_id=batch_id,
            status=ImportStatus.processing,
            rows_total=len(current_rows),
            rows_unique=unique,
            rows_duplicate=duplicate_count,
            rows_needs_review=needs_review,
            rows_failed=failed,
        )


def _card_multiset_normalized_payload(row: ImportRowModel) -> dict[str, object]:
    """Return parser-normalizer evidence after accepting only the exact workflow marker.

    A card multiset replay sees rows which a prior manifest pass has already
    annotated.  The pure multiset planner intentionally accepts *only* raw
    normalizer output, so the workflow marker must be stripped at this narrow
    boundary.  Do not use the broader posting helper here: it would also hide
    a corrupt ``posting_intent`` marker.
    """

    normalized = row.normalized_data
    if not isinstance(normalized, dict):
        raise ImportDeduplicateStateError()
    if "posting_intent" in normalized:
        raise ImportDeduplicateStateError()
    marker = normalized.get("deduplication")
    expected_marker = {
        "schema_version": 1,
        "status": "unique" if row.status is ImportRowStatus.pending else "duplicate",
    }
    if marker is not None and marker != expected_marker:
        raise ImportDeduplicateStateError()
    canonical = deepcopy(normalized)
    canonical.pop("deduplication", None)
    return canonical
