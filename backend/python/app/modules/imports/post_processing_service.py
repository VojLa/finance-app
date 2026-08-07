"""Post-commit Holdings and coordinated snapshot orchestration for imports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    ImportLogEvent,
    ImportLogLevel,
    ImportStatus,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.imports import ImportLogModel
from app.modules.holdings.models import HoldingRebuildResponse
from app.modules.holdings.orchestration import (
    HoldingRebuildApplicationService,
    HoldingRebuildUnavailableError,
    RebuildHoldingsCommand,
)
from app.modules.imports.models import ImportPostResponse, ImportSnapshotRefreshStatus
from app.modules.imports.post_processing_repository import (
    ImportBatchPostProcessingRepository,
)
from app.modules.imports.posting_service import (
    ImportBatchPostingService,
    PostImportBatchCommand,
    PostImportBatchResult,
)
from app.modules.net_worth.evidence_service import SelectedAccountSnapshotIdentity
from app.modules.net_worth.writer import NetWorthSnapshotWriteDisposition
from app.modules.snapshot_refresh.executor import (
    AccountSnapshotRefreshExecutionDisposition,
    ExecutedAccountSnapshotRefresh,
    ExecuteUserSnapshotRefreshResult,
)
from app.modules.snapshot_refresh.market_backed_models import (
    ExecuteMarketBackedSnapshotRefreshCommand,
    ExecuteMarketBackedSnapshotRefreshResult,
    MarketBackedSnapshotRefreshConflictError,
    MarketBackedSnapshotRefreshUnavailableError,
)
from app.modules.snapshot_refresh.plan import AccountSnapshotRefreshMode
from app.modules.snapshot_refresh.version import (
    coordinated_snapshot_calculation_version_marker,
    current_coordinated_snapshot_calculation_version,
)

_AUDIT_NAMESPACE = UUID("19ae2fc7-5461-5f58-98d4-3b4e3f9a66d4")
_TERMINAL_STATUSES = {ImportStatus.completed, ImportStatus.partially_completed}
_HOLDINGS_MESSAGE = "Holdings were rebuilt after canonical import posting."
_SNAPSHOTS_MESSAGE = "Coordinated snapshots were refreshed after canonical import posting."
_FAILURE_MESSAGE = (
    "Coordinated snapshot refresh could not be completed after canonical import posting."
)


class _PostingService(Protocol):
    async def post_batch(self, command: PostImportBatchCommand) -> PostImportBatchResult: ...


class _HoldingService(Protocol):
    async def rebuild(self, command: RebuildHoldingsCommand) -> HoldingRebuildResponse: ...


class _MarketBackedRefreshService(Protocol):
    async def execute(
        self,
        command: ExecuteMarketBackedSnapshotRefreshCommand,
    ) -> ExecuteMarketBackedSnapshotRefreshResult: ...


type PostingServiceFactory = Callable[[AsyncSession], _PostingService]
type HoldingServiceFactory = Callable[[AsyncSession, Callable[[], datetime]], _HoldingService]
type RepositoryFactory = Callable[[AsyncSession], ImportBatchPostProcessingRepository]


@dataclass(frozen=True, slots=True)
class _ExpectedAudit:
    id: str
    batch_id: str
    level: ImportLogLevel
    event: ImportLogEvent
    message: str
    created_at: datetime


def _holding_factory(
    session: AsyncSession,
    clock: Callable[[], datetime],
) -> HoldingRebuildApplicationService:
    return HoldingRebuildApplicationService(session, clock=clock)


def _runtime_error() -> RuntimeError:
    return RuntimeError("Import post-processing dependency returned invalid state.")


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _runtime_error()
    return value


def _count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _runtime_error()
    return value


def _timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or precision is None
        or not 0 <= precision <= 6
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise _runtime_error()
    return value


def _currency(value: object) -> str:
    currency = _nonblank(value)
    if (
        len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
        or currency != currency.upper()
    ):
        raise _runtime_error()
    return currency


def _validate_command(value: object) -> PostImportBatchCommand:
    if not isinstance(value, PostImportBatchCommand):
        raise _runtime_error()
    _validate_principal_account(value.principal, value.account_id)
    _nonblank(value.batch_id)
    return value


def _validate_principal_account(
    principal: object,
    account_id: object,
) -> tuple[AuthenticatedPrincipal, str]:
    if not isinstance(principal, AuthenticatedPrincipal):
        raise _runtime_error()
    _nonblank(principal.user_id)
    return principal, _nonblank(account_id)


def _validate_posting_result(
    value: object,
    command: PostImportBatchCommand,
) -> PostImportBatchResult:
    if not isinstance(value, PostImportBatchResult):
        raise _runtime_error()
    rows_total = _count(value.rows_total)
    rows_imported = _count(value.rows_imported)
    rows_skipped = _count(value.rows_skipped)
    transactions = _count(value.transaction_rows_imported)
    investments = _count(value.investment_event_rows_imported)
    if (
        value.batch_id != command.batch_id
        or value.status not in _TERMINAL_STATUSES
        or rows_imported + rows_skipped != rows_total
        or transactions + investments != rows_imported
        or not isinstance(value.replayed, bool)
    ):
        raise _runtime_error()
    _timestamp(value.completed_at)
    return value


def canonical_import_snapshot_bucket(value: datetime) -> datetime:
    return _timestamp(value).replace(second=0, microsecond=0)


def _validate_holding_result(
    value: object,
    *,
    command: PostImportBatchCommand,
    completed_at: datetime,
) -> HoldingRebuildResponse:
    if not isinstance(value, HoldingRebuildResponse):
        raise _runtime_error()
    created = _count(value.created)
    updated = _count(value.updated)
    deleted = _count(value.deleted)
    _count(value.total)
    if (
        value.account_id != command.account_id
        or not isinstance(value.replayed, bool)
        or (
            value.replayed
            and (created != 0 or updated != 0 or deleted != 0 or value.rebuilt_at is not None)
        )
        or (
            not value.replayed
            and (value.rebuilt_at != completed_at or created + updated + deleted == 0)
        )
    ):
        raise _runtime_error()
    if value.rebuilt_at is not None:
        _timestamp(value.rebuilt_at)
    return value


def _validated_executions(
    value: object,
) -> tuple[ExecutedAccountSnapshotRefresh, ...]:
    if not isinstance(value, tuple):
        raise _runtime_error()
    account_ids: set[str] = set()
    snapshot_ids: set[str] = set()
    executions: list[ExecutedAccountSnapshotRefresh] = []
    for item in value:
        if not isinstance(item, ExecutedAccountSnapshotRefresh):
            raise _runtime_error()
        account_id = _nonblank(item.account_id)
        snapshot_id = _nonblank(item.snapshot_id)
        if (
            account_id in account_ids
            or snapshot_id in snapshot_ids
            or not isinstance(item.mode, AccountSnapshotRefreshMode)
            or not isinstance(
                item.disposition,
                AccountSnapshotRefreshExecutionDisposition,
            )
            or (
                item.mode is AccountSnapshotRefreshMode.refresh
                and item.disposition
                not in {
                    AccountSnapshotRefreshExecutionDisposition.created,
                    AccountSnapshotRefreshExecutionDisposition.replayed,
                }
            )
            or (
                item.mode is AccountSnapshotRefreshMode.reuse_only
                and item.disposition is not AccountSnapshotRefreshExecutionDisposition.reused
            )
        ):
            raise _runtime_error()
        account_ids.add(account_id)
        snapshot_ids.add(snapshot_id)
        executions.append(item)
    return tuple(executions)


def _validate_executor_result(
    value: object,
    *,
    command: PostImportBatchCommand,
    bucket: datetime,
    version: int,
) -> ExecuteUserSnapshotRefreshResult:
    if not isinstance(value, ExecuteUserSnapshotRefreshResult):
        raise _runtime_error()
    executions = _validated_executions(value.account_snapshots)
    expected_lineage = tuple(
        SelectedAccountSnapshotIdentity(item.account_id, item.snapshot_id) for item in executions
    )
    lineage = value.required_account_snapshot_identities
    refresh_count = _count(value.refresh_account_count)
    reuse_count = _count(value.reuse_only_account_count)
    created_count = _count(value.created_account_snapshot_count)
    replayed_count = _count(value.replayed_account_snapshot_count)
    reused_count = _count(value.reused_account_snapshot_count)
    selected_count = _count(value.selected_account_snapshot_count)
    if (
        value.user_id != command.principal.user_id
        or value.snapshot_timestamp != bucket
        or value.granularity is not SnapshotGranularity.minute
        or value.source is not SnapshotSource.import_event
        or not isinstance(value.calculation_version, int)
        or isinstance(value.calculation_version, bool)
        or value.calculation_version != version
        or not isinstance(value.net_worth_disposition, NetWorthSnapshotWriteDisposition)
        or not isinstance(lineage, tuple)
        or lineage != expected_lineage
        or any(not isinstance(item, SelectedAccountSnapshotIdentity) for item in lineage)
        or refresh_count != created_count + replayed_count
        or reuse_count != reused_count
        or selected_count != refresh_count + reuse_count
        or len(executions) != selected_count
        or len(lineage) != selected_count
        or created_count
        != sum(
            item.disposition is AccountSnapshotRefreshExecutionDisposition.created
            for item in executions
        )
        or replayed_count
        != sum(
            item.disposition is AccountSnapshotRefreshExecutionDisposition.replayed
            for item in executions
        )
        or reused_count
        != sum(
            item.disposition is AccountSnapshotRefreshExecutionDisposition.reused
            for item in executions
        )
    ):
        raise _runtime_error()
    _currency(value.output_currency)
    _nonblank(value.net_worth_snapshot_id)
    return value


def _audit_id(
    *,
    batch_id: str,
    event: ImportLogEvent,
    bucket: datetime,
    version_marker: str,
    outcome: str,
) -> str:
    payload = "\0".join(
        (
            batch_id,
            event.value,
            bucket.isoformat(timespec="milliseconds"),
            version_marker,
            outcome,
        )
    )
    return str(uuid5(_AUDIT_NAMESPACE, payload))


def _audit(
    *,
    posting: PostImportBatchResult,
    event: ImportLogEvent,
    level: ImportLogLevel,
    message: str,
    bucket: datetime,
    version_marker: str,
    outcome: str,
) -> _ExpectedAudit:
    return _ExpectedAudit(
        id=_audit_id(
            batch_id=posting.batch_id,
            event=event,
            bucket=bucket,
            version_marker=version_marker,
            outcome=outcome,
        ),
        batch_id=posting.batch_id,
        level=level,
        event=event,
        message=message,
        created_at=posting.completed_at,
    )


class ImportBatchPostProcessingService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        market_backed_service: _MarketBackedRefreshService,
        posting_service_factory: PostingServiceFactory = ImportBatchPostingService,
        holding_service_factory: HoldingServiceFactory = _holding_factory,
        repository_factory: RepositoryFactory = ImportBatchPostProcessingRepository,
    ) -> None:
        self.session = session
        self.market_backed_service = market_backed_service
        self.posting_service_factory = posting_service_factory
        self.holding_service_factory = holding_service_factory
        self.repository_factory = repository_factory

    async def post_batch(self, command: PostImportBatchCommand) -> ImportPostResponse:
        canonical = _validate_command(command)
        posting_service = self.posting_service_factory(self.session)
        posting = _validate_posting_result(
            await posting_service.post_batch(canonical),
            canonical,
        )
        await self._require_idle("Import posting dependency left an active transaction.")
        status = await self._finalize_postings(
            principal=canonical.principal,
            account_id=canonical.account_id,
            postings=(posting,),
        )
        return self._response(posting, status)

    async def _finalize_postings(
        self,
        *,
        principal: AuthenticatedPrincipal,
        account_id: str,
        postings: tuple[PostImportBatchResult, ...],
    ) -> ImportSnapshotRefreshStatus:
        _validate_principal_account(principal, account_id)
        if not postings:
            raise _runtime_error()
        total_rows_imported = sum(posting.rows_imported for posting in postings)
        if total_rows_imported == 0:
            return ImportSnapshotRefreshStatus.not_required

        completed_at = max(posting.completed_at for posting in postings)
        bucket = canonical_import_snapshot_bucket(completed_at)
        audits: list[_ExpectedAudit] = []
        investment_postings = tuple(
            posting for posting in postings if posting.investment_event_rows_imported > 0
        )
        if investment_postings:
            await self._require_idle("Holding rebuild requires an idle session.")
            holding_service = self.holding_service_factory(
                self.session,
                lambda: completed_at,
            )
            await self._require_idle("Holding rebuild factory left an active transaction.")
            try:
                holding_result = await holding_service.rebuild(
                    RebuildHoldingsCommand(
                        principal=principal,
                        account_id=account_id,
                    )
                )
            except HoldingRebuildUnavailableError:
                await self._require_idle("Holding rebuild left an active transaction.")
                version_marker = coordinated_snapshot_calculation_version_marker()
                audits.extend(
                    _audit(
                        posting=item,
                        event=ImportLogEvent.snapshot_validation_failed,
                        level=ImportLogLevel.warning,
                        message=_FAILURE_MESSAGE,
                        bucket=bucket,
                        version_marker=version_marker,
                        outcome="holding_unavailable",
                    )
                    for item in postings
                )
                await self._write_audits(audits)
                return ImportSnapshotRefreshStatus.unavailable
            except Exception:
                await self._rollback_active()
                raise
            await self._require_idle("Holding rebuild left an active transaction.")
            holding_result = _validate_holding_result(
                holding_result,
                command=PostImportBatchCommand(
                    principal=principal,
                    account_id=account_id,
                    batch_id=postings[0].batch_id,
                ),
                completed_at=completed_at,
            )
            audits.extend(
                _audit(
                    posting=item,
                    event=ImportLogEvent.holdings_recalculated,
                    level=ImportLogLevel.info,
                    message=_HOLDINGS_MESSAGE,
                    bucket=bucket,
                    version_marker=coordinated_snapshot_calculation_version_marker(),
                    outcome="replayed" if holding_result.replayed else "rebuilt",
                )
                for item in investment_postings
            )

        try:
            version = current_coordinated_snapshot_calculation_version()
        except ValueError:
            audits.extend(
                _audit(
                    posting=item,
                    event=ImportLogEvent.snapshot_validation_failed,
                    level=ImportLogLevel.warning,
                    message=_FAILURE_MESSAGE,
                    bucket=bucket,
                    version_marker=coordinated_snapshot_calculation_version_marker(),
                    outcome="version_unavailable",
                )
                for item in postings
            )
            await self._write_audits(audits)
            return ImportSnapshotRefreshStatus.unavailable

        await self._require_idle("Market-backed snapshot refresh requires an idle session.")
        market_backed_command = ExecuteMarketBackedSnapshotRefreshCommand(
            user_id=principal.user_id,
            snapshot_timestamp=bucket,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.import_event,
            calculation_version=version,
            calculated_at=bucket,
            created_at=bucket,
            is_recalculated=False,
        )
        try:
            combined_result = await self.market_backed_service.execute(market_backed_command)
        except MarketBackedSnapshotRefreshUnavailableError:
            await self._require_idle("Market-backed snapshot refresh left an active transaction.")
            status = ImportSnapshotRefreshStatus.unavailable
            outcome = "snapshot_unavailable"
        except MarketBackedSnapshotRefreshConflictError:
            await self._require_idle("Market-backed snapshot refresh left an active transaction.")
            status = ImportSnapshotRefreshStatus.conflict
            outcome = "snapshot_conflict"
        except Exception as exc:
            if self.session.in_transaction():
                await self.session.rollback()
                raise _runtime_error() from exc
            raise
        else:
            await self._require_idle("Market-backed snapshot refresh left an active transaction.")
            if not isinstance(
                combined_result,
                ExecuteMarketBackedSnapshotRefreshResult,
            ):
                raise _runtime_error()
            validated = _validate_executor_result(
                combined_result.snapshots,
                command=PostImportBatchCommand(
                    principal=principal,
                    account_id=account_id,
                    batch_id=postings[0].batch_id,
                ),
                bucket=bucket,
                version=version,
            )
            status = (
                ImportSnapshotRefreshStatus.created
                if validated.net_worth_disposition is NetWorthSnapshotWriteDisposition.created
                else ImportSnapshotRefreshStatus.replayed
            )
            outcome = status.value

        if status in {
            ImportSnapshotRefreshStatus.created,
            ImportSnapshotRefreshStatus.replayed,
        }:
            event = ImportLogEvent.snapshots_recalculated
            level = ImportLogLevel.info
            message = _SNAPSHOTS_MESSAGE
        else:
            event = ImportLogEvent.snapshot_validation_failed
            level = ImportLogLevel.warning
            message = _FAILURE_MESSAGE
        audits.extend(
            _audit(
                posting=item,
                event=event,
                level=level,
                message=message,
                bucket=bucket,
                version_marker=str(version),
                outcome=outcome,
            )
            for item in postings
        )
        await self._write_audits(audits)
        return status

    async def _write_audits(self, audits: list[_ExpectedAudit]) -> None:
        if not audits:
            return
        await self._require_idle("Import audit requires an idle session.")
        repository = self.repository_factory(self.session)
        async with self.session.begin():
            for expected in sorted(audits, key=lambda item: item.id):
                await repository.acquire_audit_lock(expected.id)
                persisted = await repository.load_log_for_update(expected.id)
                if persisted is None:
                    repository.add_log(
                        ImportLogModel(
                            id=expected.id,
                            import_batch_id=expected.batch_id,
                            level=expected.level,
                            event=expected.event,
                            message=expected.message,
                            created_at=expected.created_at,
                        )
                    )
                elif (
                    not isinstance(persisted, ImportLogModel)
                    or persisted.import_batch_id != expected.batch_id
                    or persisted.level is not expected.level
                    or persisted.event is not expected.event
                    or persisted.message != expected.message
                    or persisted.created_at != expected.created_at
                ):
                    raise _runtime_error()
            await repository.flush()
        await self._require_idle("Import audit left an active transaction.")

    async def _require_idle(self, message: str) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
            raise RuntimeError(message)

    async def _rollback_active(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()

    @staticmethod
    def _response(
        posting: PostImportBatchResult,
        status: ImportSnapshotRefreshStatus,
    ) -> ImportPostResponse:
        return ImportPostResponse(
            batch_id=posting.batch_id,
            status=posting.status,
            rows_total=posting.rows_total,
            rows_imported=posting.rows_imported,
            rows_skipped=posting.rows_skipped,
            completed_at=posting.completed_at,
            replayed=posting.replayed,
            snapshot_refresh_status=status,
        )
