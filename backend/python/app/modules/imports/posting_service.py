"""Atomic public orchestration for canonical import batch posting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.common import TIMESTAMP
from app.db.models.enums import AccountMemberRole, ImportRowStatus, ImportStatus
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.modules.accounts.access import require_account_access
from app.modules.imports.investment_posting import ImportInvestmentPostingWriter
from app.modules.imports.investment_posting_plan import build_investment_posting_plan
from app.modules.imports.models import ImportPostResponse
from app.modules.imports.posting_common import ImportPostStateError
from app.modules.imports.repository import ImportBatchRepository
from app.modules.imports.service import ImportBatchNotFoundError
from app.modules.imports.transaction_posting import (
    ImportTransactionPostingWriter,
    build_transaction_posting_plan,
)
from app.shared.errors import ApplicationError

WRITE_ROLES = {AccountMemberRole.owner, AccountMemberRole.admin, AccountMemberRole.editor}
_UNIQUE = {"schema_version": 1, "status": "unique"}
_DUPLICATE = {"schema_version": 1, "status": "duplicate"}
_REVIEW_MESSAGE = "Row requires classification review."
_NORMALIZATION_REVIEW_MESSAGE = "Row requires normalization review."
_TERMINAL_BATCH_STATUSES = {ImportStatus.completed, ImportStatus.partially_completed}


class ImportBatchPostStateError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_post_batch_state_invalid",
            message="The import batch is not available for posting.",
            status_code=409,
        )


class ImportBatchPostRowsMissingError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="import_post_batch_rows_missing",
            message="The import batch has no rows for posting.",
            status_code=409,
        )


@dataclass(frozen=True, slots=True)
class PostImportBatchCommand:
    principal: AuthenticatedPrincipal
    account_id: str
    batch_id: str


@dataclass(frozen=True, slots=True)
class _BatchCounts:
    total: int
    imported: int
    skipped: int
    failed_or_review: int


def _current_timestamp() -> datetime:
    precision = TIMESTAMP.precision
    if precision is None or not 0 <= precision <= 6:
        raise RuntimeError("Canonical TIMESTAMP precision must be between zero and six")
    now = datetime.now(UTC).replace(tzinfo=None)
    unit = 10 ** (6 - precision)
    return now.replace(microsecond=now.microsecond - (now.microsecond % unit))


def _posting_target(row: ImportRowModel) -> str | None:
    if not isinstance(row.normalized_data, dict):
        return None
    intent = row.normalized_data.get("posting_intent")
    if not isinstance(intent, dict):
        return None
    target = intent.get("target")
    return target if isinstance(target, str) else None


def _valid_duplicate(row: ImportRowModel) -> bool:
    return (
        row.status is ImportRowStatus.duplicate
        and isinstance(row.normalized_data, dict)
        and row.normalized_data.get("deduplication") == _DUPLICATE
        and "posting_intent" not in row.normalized_data
        and isinstance(row.deduplication_key, str)
        and bool(row.deduplication_key)
        and row.validation_errors is None
        and row.error_message == "Duplicate normalized import row."
        and row.created_transaction_id is None
        and row.created_investment_event_id is None
    )


def _valid_skipped(row: ImportRowModel) -> bool:
    return (
        row.status is ImportRowStatus.skipped
        and isinstance(row.normalized_data, dict)
        and row.normalized_data.get("schema_version") == 2
        and row.normalized_data.get("source") == "anycoin"
        and row.normalized_data.get("kind")
        in {"group_member", "fully_refunded_group", "neutral_row"}
        and "deduplication" not in row.normalized_data
        and "posting_intent" not in row.normalized_data
        and row.deduplication_key is None
        and row.validation_errors is None
        and row.error_message is None
        and row.created_transaction_id is None
        and row.created_investment_event_id is None
    )


def _valid_failed(row: ImportRowModel) -> bool:
    errors = row.validation_errors
    valid_evidence = False
    if isinstance(errors, dict):
        if errors == {"code": "blank_row"}:
            valid_evidence = row.error_message == "The row is blank."
        elif set(errors) == {"code", "expected", "actual"}:
            expected = errors.get("expected")
            actual = errors.get("actual")
            if (
                errors.get("code") == "column_count_mismatch"
                and isinstance(expected, int)
                and not isinstance(expected, bool)
                and expected > 0
                and isinstance(actual, int)
                and not isinstance(actual, bool)
                and actual >= 0
                and actual != expected
            ):
                valid_evidence = row.error_message == (
                    "The row contains more values than the header defines."
                    if actual > expected
                    else "The row contains fewer values than the header defines."
                )
    return (
        row.status is ImportRowStatus.failed
        and row.normalized_data is None
        and row.deduplication_key is None
        and valid_evidence
        and row.created_transaction_id is None
        and row.created_investment_event_id is None
    )


def _valid_review(row: ImportRowModel) -> bool:
    if row.status is not ImportRowStatus.needs_review:
        return False
    if row.normalized_data is None:
        return (
            isinstance(row.validation_errors, list)
            and bool(row.validation_errors)
            and all(isinstance(error, dict) and bool(error) for error in row.validation_errors)
            and row.error_message == _NORMALIZATION_REVIEW_MESSAGE
            and row.deduplication_key is None
            and row.created_transaction_id is None
            and row.created_investment_event_id is None
        )
    intent = row.normalized_data.get("posting_intent")
    return (
        row.normalized_data.get("deduplication") == _UNIQUE
        and isinstance(row.deduplication_key, str)
        and bool(row.deduplication_key)
        and isinstance(intent, dict)
        and intent.get("target") == "needs_review"
        and row.validation_errors == intent.get("errors")
        and row.error_message == _REVIEW_MESSAGE
        and row.created_transaction_id is None
        and row.created_investment_event_id is None
    )


def _writer_batch(batch: ImportBatchModel) -> ImportBatchModel:
    """Create a transient processing view for closed row-writer replay contracts."""
    return ImportBatchModel(
        id=batch.id,
        user_id=batch.user_id,
        account_id=batch.account_id,
        source=batch.source,
        filename=batch.filename,
        file_size=batch.file_size,
        file_encoding=batch.file_encoding,
        checksum=batch.checksum,
        status=ImportStatus.processing,
        rows_total=batch.rows_total,
        rows_imported=batch.rows_imported,
        rows_skipped=batch.rows_skipped,
        created_at=batch.created_at,
        completed_at=None,
        retain_until=batch.retain_until,
        raw_data_purged_at=batch.raw_data_purged_at,
    )


def _validate_postable_row(
    *, account_id: str, batch: ImportBatchModel, row: ImportRowModel
) -> None:
    target = _posting_target(row)
    try:
        if target == "transaction":
            build_transaction_posting_plan(account_id=account_id, batch=batch, row=row)
        elif target == "investment_event":
            build_investment_posting_plan(account_id=account_id, batch=batch, row=row)
        else:
            raise ImportBatchPostStateError()
    except ImportPostStateError as exc:
        raise ImportBatchPostStateError() from exc


def _preflight(
    *,
    account_id: str,
    batch: ImportBatchModel,
    rows: list[ImportRowModel],
    replay: bool,
) -> _BatchCounts:
    if not rows:
        raise ImportBatchPostRowsMissingError()
    if len({row.id for row in rows}) != len(rows):
        raise ImportBatchPostStateError()
    if any(row.import_batch_id != batch.id for row in rows):
        raise ImportBatchPostStateError()
    if batch.rows_total != len(rows):
        raise ImportBatchPostStateError()
    writer_batch = _writer_batch(batch) if replay else batch
    postable_keys: set[str] = set()
    for row in rows:
        if row.status in {ImportRowStatus.pending, ImportRowStatus.imported}:
            if not isinstance(row.deduplication_key, str) or not row.deduplication_key:
                raise ImportBatchPostStateError()
            if row.deduplication_key in postable_keys:
                raise ImportBatchPostStateError()
            postable_keys.add(row.deduplication_key)
            _validate_postable_row(account_id=account_id, batch=writer_batch, row=row)
        elif not (
            _valid_duplicate(row) or _valid_skipped(row) or _valid_failed(row) or _valid_review(row)
        ):
            raise ImportBatchPostStateError()

    imported = sum(row.status is ImportRowStatus.imported for row in rows)
    skipped = len(rows) - imported - sum(row.status is ImportRowStatus.pending for row in rows)
    failed_or_review = sum(
        row.status in {ImportRowStatus.failed, ImportRowStatus.needs_review} for row in rows
    )
    counts = _BatchCounts(
        total=len(rows),
        imported=imported,
        skipped=skipped,
        failed_or_review=failed_or_review,
    )
    if replay:
        if any(row.status is ImportRowStatus.pending for row in rows):
            raise ImportBatchPostStateError()
        expected_status = (
            ImportStatus.partially_completed if failed_or_review else ImportStatus.completed
        )
        if (
            batch.status is not expected_status
            or batch.completed_at is None
            or batch.rows_imported != imported
            or batch.rows_skipped != skipped
        ):
            raise ImportBatchPostStateError()
    elif (
        batch.status is not ImportStatus.processing
        or batch.completed_at is not None
        or batch.rows_imported != imported
        or batch.rows_skipped != skipped
        or imported != 0
    ):
        raise ImportBatchPostStateError()
    return counts


class ImportBatchPostingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = ImportBatchRepository(session)

    async def post_batch(self, command: PostImportBatchCommand) -> ImportPostResponse:
        try:
            # Lock the persisted membership for the transaction so a concurrent role
            # revocation cannot commit between authorization and canonical posting.
            await require_account_access(
                session=self.session,
                principal=command.principal,
                account_id=command.account_id,
                allowed_roles=WRITE_ROLES,
                for_update=True,
            )
            batch = await self.repository.get_for_account(
                account_id=command.account_id,
                batch_id=command.batch_id,
                for_update=True,
            )
            if batch is None:
                raise ImportBatchNotFoundError()
            if batch.status not in {ImportStatus.processing, *_TERMINAL_BATCH_STATUSES}:
                raise ImportBatchPostStateError()
            await self.repository.lock_deduplication_scope(
                account_id=command.account_id,
                source=batch.source,
            )
            rows = await self.repository.list_rows_for_update(batch.id)
            replay = batch.status in _TERMINAL_BATCH_STATUSES
            _preflight(
                account_id=command.account_id,
                batch=batch,
                rows=rows,
                replay=replay,
            )
            writer_batch = _writer_batch(batch) if replay else batch
            for row in rows:
                if row.status not in {ImportRowStatus.pending, ImportRowStatus.imported}:
                    continue
                target = _posting_target(row)
                if target == "transaction":
                    await ImportTransactionPostingWriter(self.session).post_row(
                        account_id=command.account_id,
                        batch=writer_batch,
                        row=row,
                    )
                elif target == "investment_event":
                    await ImportInvestmentPostingWriter(self.session).post_row(
                        account_id=command.account_id,
                        batch=writer_batch,
                        row=row,
                    )
                else:
                    raise ImportBatchPostStateError()

            if not replay:
                imported = sum(row.status is ImportRowStatus.imported for row in rows)
                skipped = len(rows) - imported
                failed_or_review = sum(
                    row.status in {ImportRowStatus.failed, ImportRowStatus.needs_review}
                    for row in rows
                )
                if imported + skipped != len(rows):
                    raise ImportBatchPostStateError()
                batch.rows_total = len(rows)
                batch.rows_imported = imported
                batch.rows_skipped = skipped
                batch.status = (
                    ImportStatus.partially_completed if failed_or_review else ImportStatus.completed
                )
                batch.completed_at = _current_timestamp()
                await self.session.flush()
            if batch.completed_at is None:
                raise ImportBatchPostStateError()
            response = ImportPostResponse(
                batch_id=batch.id,
                status=batch.status,
                rows_total=int(batch.rows_total or 0),
                rows_imported=int(batch.rows_imported or 0),
                rows_skipped=int(batch.rows_skipped or 0),
                completed_at=batch.completed_at,
                replayed=replay,
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return response
