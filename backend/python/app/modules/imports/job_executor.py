"""Durable, framework-independent execution of one logical import job."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import ImportStatus
from app.modules.imports.classification_service import ImportClassificationService
from app.modules.imports.deduplication import ImportDeduplicationService
from app.modules.imports.models import (
    ImportClassifyResponse,
    ImportDeduplicateResponse,
    ImportNormalizeResponse,
    ImportParseResponse,
    ImportSnapshotRefreshStatus,
)
from app.modules.imports.multi_file_service import (
    FinalizeImportBatchesCommand,
    FinalizeImportBatchesResult,
)
from app.modules.imports.normalization import ImportNormalizationService
from app.modules.imports.posting_service import (
    ImportBatchPostingService,
    PostImportBatchCommand,
    PostImportBatchResult,
)
from app.modules.imports.processing import ImportParserService
from app.modules.imports.repository import ImportBatchRepository
from app.modules.imports.service import ImportBatchNotFoundError

_TERMINAL_BATCH_STATUSES = {ImportStatus.completed, ImportStatus.partially_completed}
_MAX_BATCHES = 10


class ImportExecutionStage(StrEnum):
    parse = "parse"
    normalize = "normalize"
    deduplicate = "deduplicate"
    classify = "classify"
    canonical_post = "canonical_post"
    finalize = "finalize"


_STAGES = tuple(ImportExecutionStage)


@dataclass(frozen=True, slots=True)
class ImportExecutionPayload:
    """Durable non-sensitive import job input; raw file data never belongs here."""

    batch_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ImportExecutionCheckpoint:
    job_id: str
    stage: ImportExecutionStage


@dataclass(frozen=True, slots=True)
class ImportExecutionProgress:
    job_id: str
    stage: ImportExecutionStage
    completed_batches: int
    total_batches: int


@dataclass(frozen=True, slots=True)
class ImportExecutionResult:
    job_id: str
    batch_ids: tuple[str, ...]
    completed_stage: ImportExecutionStage
    finalization: FinalizeImportBatchesResult


class _Parser(Protocol):
    async def parse_batch(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        batch_id: str,
    ) -> object: ...


class _Normalizer(Protocol):
    async def normalize_batch(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        batch_id: str,
    ) -> object: ...


class _Deduplicator(Protocol):
    async def deduplicate_batch(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        batch_id: str,
    ) -> object: ...


class _Classifier(Protocol):
    async def classify_batch(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        batch_id: str,
    ) -> object: ...


class _Poster(Protocol):
    async def post_batch(self, command: PostImportBatchCommand) -> object: ...


class _Finalizer(Protocol):
    async def finalize(
        self, command: FinalizeImportBatchesCommand
    ) -> FinalizeImportBatchesResult: ...


class _BatchRepository(Protocol):
    async def get_for_account(
        self,
        *,
        account_id: str,
        batch_id: str,
    ) -> object | None: ...


type SessionFactory = Callable[[], AsyncSession]
type PrincipalResolver = Callable[[AsyncSession, str], Awaitable[AuthenticatedPrincipal]]
type ParserFactory = Callable[[AsyncSession], _Parser]
type NormalizerFactory = Callable[[AsyncSession], _Normalizer]
type DeduplicatorFactory = Callable[[AsyncSession], _Deduplicator]
type ClassifierFactory = Callable[[AsyncSession], _Classifier]
type PosterFactory = Callable[[AsyncSession], _Poster]
type FinalizerFactory = Callable[[AsyncSession], _Finalizer]
type BatchRepositoryFactory = Callable[[AsyncSession], _BatchRepository]
type PublicationBucketResolver = Callable[[], Awaitable[datetime]]
type CheckpointHook = Callable[[ImportExecutionCheckpoint], Awaitable[None]]
type ProgressHook = Callable[[ImportExecutionProgress], Awaitable[None]]


class ImportJobExecutionStateError(RuntimeError):
    """Raised before an executor could safely mutate canonical import state."""


class ImportJobExecutionRetryableError(RuntimeError):
    """A durable finalization has not published a complete portfolio read model yet."""

    def __init__(self, status: ImportSnapshotRefreshStatus) -> None:
        super().__init__("Import finalization will be retried before portfolio publication.")
        self.status = status


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ImportJobExecutionStateError("Import job input is invalid.")
    return value


def _checkpoint(value: object) -> ImportExecutionStage | None:
    if value is None:
        return None
    if not isinstance(value, ImportExecutionStage):
        raise ImportJobExecutionStateError("Import job checkpoint is invalid.")
    return value


def _payload(value: object) -> ImportExecutionPayload:
    if (
        not isinstance(value, ImportExecutionPayload)
        or not isinstance(value.batch_ids, tuple)
        or not value.batch_ids
        or len(value.batch_ids) > _MAX_BATCHES
        or value.batch_ids != tuple(sorted(value.batch_ids))
        or len(set(value.batch_ids)) != len(value.batch_ids)
        or any(
            not isinstance(batch_id, str) or not batch_id or batch_id != batch_id.strip()
            for batch_id in value.batch_ids
        )
    ):
        raise ImportJobExecutionStateError("Import job payload is invalid.")
    return value


def _count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ImportJobExecutionStateError("Import stage returned invalid counters.")
    return value


def _validate_processing_result(
    *, stage: ImportExecutionStage, batch_id: str, result: object
) -> None:
    counts: tuple[int, ...]
    if stage is ImportExecutionStage.parse:
        if not isinstance(result, ImportParseResponse):
            raise ImportJobExecutionStateError("Import parse returned invalid state.")
        counts = (result.rows_total, result.rows_pending, result.rows_failed)
        for count in counts:
            _count(count)
        if result.rows_pending + result.rows_failed != result.rows_total:
            raise ImportJobExecutionStateError("Import parse returned invalid counters.")
    elif stage is ImportExecutionStage.normalize:
        if not isinstance(result, ImportNormalizeResponse):
            raise ImportJobExecutionStateError("Import normalization returned invalid state.")
        counts = (
            result.rows_total,
            result.rows_normalized,
            result.rows_needs_review,
            result.rows_failed,
        )
        for count in counts:
            _count(count)
        if sum(counts[1:]) > counts[0]:
            raise ImportJobExecutionStateError("Import normalization returned invalid counters.")
    elif stage is ImportExecutionStage.deduplicate:
        if not isinstance(result, ImportDeduplicateResponse):
            raise ImportJobExecutionStateError("Import duplicate detection returned invalid state.")
        counts = (
            result.rows_total,
            result.rows_unique,
            result.rows_duplicate,
            result.rows_needs_review,
            result.rows_failed,
        )
        for count in counts:
            _count(count)
        if sum(counts[1:]) > counts[0]:
            raise ImportJobExecutionStateError(
                "Import duplicate detection returned invalid counters."
            )
    elif stage is ImportExecutionStage.classify:
        if not isinstance(result, ImportClassifyResponse):
            raise ImportJobExecutionStateError("Import classification returned invalid state.")
        counts = (
            result.rows_total,
            result.rows_classified,
            result.rows_needs_review,
            result.rows_duplicate,
            result.rows_skipped,
            result.rows_failed,
        )
        for count in counts:
            _count(count)
        if sum(counts[1:]) != counts[0]:
            raise ImportJobExecutionStateError("Import classification returned invalid counters.")
    else:
        raise ImportJobExecutionStateError("Import stage returned invalid state.")
    if result.batch_id != batch_id or result.status is not ImportStatus.processing:
        raise ImportJobExecutionStateError("Import stage returned invalid state.")


def _validate_post_result(*, batch_id: str, result: object) -> None:
    if not isinstance(result, PostImportBatchResult):
        raise ImportJobExecutionStateError("Import posting returned invalid state.")
    if result.batch_id != batch_id or result.status not in _TERMINAL_BATCH_STATUSES:
        raise ImportJobExecutionStateError("Import posting returned invalid state.")
    counts = (
        result.rows_total,
        result.rows_imported,
        result.rows_skipped,
        result.transaction_rows_imported,
        result.investment_event_rows_imported,
    )
    for count in counts:
        _count(count)
    if (
        result.rows_imported + result.rows_skipped != result.rows_total
        or result.transaction_rows_imported + result.investment_event_rows_imported
        != result.rows_imported
        or not isinstance(result.replayed, bool)
        or not isinstance(result.completed_at, datetime)
        or result.completed_at.tzinfo is not None
    ):
        raise ImportJobExecutionStateError("Import posting returned invalid state.")


class ImportJobExecutor:
    """Run durable stages with fresh authorization and a fenced checkpoint boundary."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        principal_resolver: PrincipalResolver,
        finalization_factory: FinalizerFactory,
        parser_factory: ParserFactory = ImportParserService,
        normalization_factory: NormalizerFactory = ImportNormalizationService,
        deduplication_factory: DeduplicatorFactory = ImportDeduplicationService,
        classification_factory: ClassifierFactory = ImportClassificationService,
        posting_factory: PosterFactory = ImportBatchPostingService,
        batch_repository_factory: BatchRepositoryFactory = ImportBatchRepository,
    ) -> None:
        self.session_factory = session_factory
        self.principal_resolver = principal_resolver
        self.finalization_factory = finalization_factory
        self.parser_factory = parser_factory
        self.normalization_factory = normalization_factory
        self.deduplication_factory = deduplication_factory
        self.classification_factory = classification_factory
        self.posting_factory = posting_factory
        self.batch_repository_factory = batch_repository_factory

    async def execute(
        self,
        job_id: str,
        user_id: str,
        account_id: str,
        payload: ImportExecutionPayload,
        checkpoint: ImportExecutionStage | None,
        on_checkpoint: CheckpointHook,
        *,
        on_progress: ProgressHook | None = None,
        publication_bucket: datetime | None = None,
        publication_bucket_resolver: PublicationBucketResolver | None = None,
    ) -> ImportExecutionResult:
        canonical_job_id = _nonblank(job_id)
        canonical_user_id = _nonblank(user_id)
        canonical_account_id = _nonblank(account_id)
        canonical_payload = _payload(payload)
        completed = _checkpoint(checkpoint)
        if not callable(on_checkpoint) or (on_progress is not None and not callable(on_progress)):
            raise ImportJobExecutionStateError("Import job hooks are invalid.")

        finalization: FinalizeImportBatchesResult | None = None
        for stage in _STAGES:
            if completed is not None and _STAGES.index(stage) <= _STAGES.index(completed):
                continue
            if stage is ImportExecutionStage.finalize:
                bucket = (
                    await publication_bucket_resolver()
                    if publication_bucket_resolver is not None
                    else publication_bucket
                )
                finalization = await self._finalize(
                    job_id=canonical_job_id,
                    user_id=canonical_user_id,
                    account_id=canonical_account_id,
                    batch_ids=canonical_payload.batch_ids,
                    publication_bucket=bucket,
                )
            else:
                await self._run_batch_stage(
                    stage=stage,
                    user_id=canonical_user_id,
                    account_id=canonical_account_id,
                    batch_ids=canonical_payload.batch_ids,
                    job_id=canonical_job_id,
                    on_progress=on_progress,
                )
            completed = stage
            await on_checkpoint(
                ImportExecutionCheckpoint(
                    job_id=canonical_job_id,
                    stage=stage,
                )
            )

        if finalization is None:
            if completed is not ImportExecutionStage.finalize:
                raise ImportJobExecutionStateError(
                    "Import job execution ended before finalization."
                )
            # A worker can crash after persisting its fenced checkpoint but before it marks
            # the job complete. Finalization is itself an exact replay boundary.
            bucket = (
                await publication_bucket_resolver()
                if publication_bucket_resolver is not None
                else publication_bucket
            )
            finalization = await self._finalize(
                job_id=canonical_job_id,
                user_id=canonical_user_id,
                account_id=canonical_account_id,
                batch_ids=canonical_payload.batch_ids,
                publication_bucket=bucket,
            )
        return ImportExecutionResult(
            job_id=canonical_job_id,
            batch_ids=canonical_payload.batch_ids,
            completed_stage=ImportExecutionStage.finalize,
            finalization=finalization,
        )

    async def _run_batch_stage(
        self,
        *,
        stage: ImportExecutionStage,
        user_id: str,
        account_id: str,
        batch_ids: tuple[str, ...],
        job_id: str,
        on_progress: ProgressHook | None,
    ) -> None:
        completed = 0
        async with self.session_factory() as session:
            repository = self.batch_repository_factory(session)
            for batch_id in batch_ids:
                principal = await self._principal(session=session, user_id=user_id)
                batch = await repository.get_for_account(account_id=account_id, batch_id=batch_id)
                if batch is None or getattr(batch, "user_id", None) != user_id:
                    raise ImportBatchNotFoundError()
                status = getattr(batch, "status", None)
                if (
                    stage is not ImportExecutionStage.canonical_post
                    and status in _TERMINAL_BATCH_STATUSES
                ):
                    completed += 1
                    continue
                if stage is ImportExecutionStage.parse:
                    result = await self.parser_factory(session).parse_batch(
                        principal=principal,
                        account_id=account_id,
                        batch_id=batch_id,
                    )
                    _validate_processing_result(stage=stage, batch_id=batch_id, result=result)
                elif stage is ImportExecutionStage.normalize:
                    result = await self.normalization_factory(session).normalize_batch(
                        principal=principal,
                        account_id=account_id,
                        batch_id=batch_id,
                    )
                    _validate_processing_result(stage=stage, batch_id=batch_id, result=result)
                elif stage is ImportExecutionStage.deduplicate:
                    result = await self.deduplication_factory(session).deduplicate_batch(
                        principal=principal,
                        account_id=account_id,
                        batch_id=batch_id,
                    )
                    _validate_processing_result(stage=stage, batch_id=batch_id, result=result)
                elif stage is ImportExecutionStage.classify:
                    result = await self.classification_factory(session).classify_batch(
                        principal=principal,
                        account_id=account_id,
                        batch_id=batch_id,
                    )
                    _validate_processing_result(stage=stage, batch_id=batch_id, result=result)
                elif stage is ImportExecutionStage.canonical_post:
                    result = await self.posting_factory(session).post_batch(
                        PostImportBatchCommand(
                            principal=principal,
                            account_id=account_id,
                            batch_id=batch_id,
                        )
                    )
                    _validate_post_result(batch_id=batch_id, result=result)
                else:
                    raise RuntimeError("Unknown import execution stage.")
                completed += 1
                if on_progress is not None:
                    await on_progress(
                        ImportExecutionProgress(
                            job_id=job_id,
                            stage=stage,
                            completed_batches=completed,
                            total_batches=len(batch_ids),
                        )
                    )

    async def _finalize(
        self,
        *,
        job_id: str,
        user_id: str,
        account_id: str,
        batch_ids: tuple[str, ...],
        publication_bucket: datetime | None,
    ) -> FinalizeImportBatchesResult:
        async with self.session_factory() as authorization_session:
            principal = await self._principal(
                session=authorization_session,
                user_id=user_id,
            )
        async with self.session_factory() as finalization_session:
            result = await self.finalization_factory(finalization_session).finalize(
                FinalizeImportBatchesCommand(
                    principal=principal,
                    account_id=account_id,
                    batch_ids=batch_ids,
                    background_job_id=_nonblank(job_id),
                    publication_bucket=publication_bucket,
                )
            )
        if not isinstance(result, FinalizeImportBatchesResult) or result.batch_ids != batch_ids:
            raise ImportJobExecutionStateError("Import finalization returned invalid state.")
        if result.snapshot_refresh_status in {
            ImportSnapshotRefreshStatus.unavailable,
            ImportSnapshotRefreshStatus.conflict,
        }:
            raise ImportJobExecutionRetryableError(result.snapshot_refresh_status)
        if result.snapshot_refresh_status not in {
            ImportSnapshotRefreshStatus.created,
            ImportSnapshotRefreshStatus.replayed,
            ImportSnapshotRefreshStatus.not_required,
        }:
            raise ImportJobExecutionStateError("Import finalization returned an invalid status.")
        return result

    async def _principal(
        self,
        *,
        session: AsyncSession,
        user_id: str,
    ) -> AuthenticatedPrincipal:
        principal = await self.principal_resolver(session, user_id)
        if not isinstance(principal, AuthenticatedPrincipal) or principal.user_id != user_id:
            raise ImportJobExecutionStateError("Import job authorization is no longer valid.")
        return principal


__all__ = [
    "CheckpointHook",
    "ImportExecutionCheckpoint",
    "ImportExecutionPayload",
    "ImportExecutionProgress",
    "ImportExecutionResult",
    "ImportExecutionStage",
    "ImportJobExecutionRetryableError",
    "ImportJobExecutionStateError",
    "ImportJobExecutor",
    "PrincipalResolver",
    "ProgressHook",
]
