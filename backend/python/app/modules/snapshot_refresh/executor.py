"""Internal coordinated execution of exact account and net-worth snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid5

import structlog
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.models.accounts import AccountMemberModel
from app.db.models.background_jobs import (
    BackgroundJobModel,
    ImportJobAffectedAccountModel,
)
from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    AccountMemberRole,
    AccountType,
    BackgroundJobKind,
    BackgroundJobStatus,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.publication_targets import ImportJobPublicationTargetModel
from app.modules.daily_baselines import (
    DailyBaselineDisposition,
    DailyBaselineError,
    DailySnapshotBaselineService,
    PersistDailySnapshotBaselineCommand,
    PersistDailySnapshotBaselineResult,
)
from app.modules.market_data.source_policy import (
    CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    MarketEvidenceSourcePolicy,
    validate_market_evidence_source_policy,
)
from app.modules.net_worth.evidence_service import (
    NetWorthEvidenceStateError,
    SelectedAccountSnapshotIdentity,
)
from app.modules.net_worth.persistence_projection import (
    NetWorthSnapshotPersistenceProjectionError,
)
from app.modules.net_worth.writer import (
    NetWorthSnapshotWriteConflictError,
    NetWorthSnapshotWriteDisposition,
    NetWorthSnapshotWriter,
    NetWorthSnapshotWriteResult,
    NetWorthSnapshotWriteStateError,
    WriteNetWorthSnapshotCommand,
)
from app.modules.portfolio_snapshot.writer import (
    PortfolioSnapshotWriteError,
    PortfolioSnapshotWriter,
    PortfolioSnapshotWriteResult,
    WritePortfolioSnapshotCommand,
)
from app.modules.snapshot_refresh.evidence_service import (
    BuildSnapshotRefreshCoverageCommand,
    CompleteSnapshotRefreshCoverage,
    SelectedReusableAccountSnapshot,
    SnapshotRefreshEvidenceService,
    SnapshotRefreshEvidenceStateError,
)
from app.modules.snapshot_refresh.executor_repository import (
    SnapshotRefreshExecutorRepository,
)
from app.modules.snapshot_refresh.plan import (
    AccountSnapshotRefreshMode,
    ExpectedAccountSnapshotRefreshTarget,
    ExpectedNetWorthRefreshTarget,
    ExpectedUserSnapshotRefreshPlan,
    SnapshotRefreshPlanStateError,
)
from app.modules.snapshots.evidence_service import AccountSnapshotEvidenceService
from app.modules.snapshots.financial_metrics import AccountSnapshotEvidenceStateError
from app.modules.snapshots.persistence_projection import (
    AccountSnapshotPersistenceProjectionError,
)
from app.modules.snapshots.writer import (
    AccountSnapshotWriteConflictError,
    AccountSnapshotWriteDisposition,
    AccountSnapshotWriter,
    AccountSnapshotWriteResult,
    AccountSnapshotWriteStateError,
    WriteAccountSnapshotCommand,
)

_STATE_MESSAGE = "Coordinated snapshot refresh could not be completed."
_CONFLICT_MESSAGE = "Coordinated snapshot refresh conflicts with persisted state."
_POSTGRES_INTEGER_MAX = 2_147_483_647
_GENERATION_NAMESPACE = UUID("65793e32-457f-58af-8b54-23a2238347b0")
_SUPPORTED_ACCOUNT_TYPES = frozenset(
    {
        AccountType.bank,
        AccountType.cash,
        AccountType.savings,
        AccountType.broker,
        AccountType.exchange,
        AccountType.crypto_wallet,
        AccountType.credit_card,
        AccountType.loan,
        AccountType.mortgage,
    }
)
_REFRESH_ROLES = frozenset(
    {
        AccountMemberRole.owner,
        AccountMemberRole.admin,
        AccountMemberRole.editor,
    }
)


class SnapshotRefreshExecutionStateError(RuntimeError):
    """Raised when coordinated refresh state is incomplete or invalid."""

    def __init__(self) -> None:
        super().__init__(_STATE_MESSAGE)


class SnapshotRefreshExecutionConflictError(RuntimeError):
    """Raised when an immutable target conflicts with persisted state."""

    def __init__(self) -> None:
        super().__init__(_CONFLICT_MESSAGE)


class AccountSnapshotRefreshExecutionDisposition(StrEnum):
    created = "created"
    replayed = "replayed"
    reused = "reused"


@dataclass(frozen=True, slots=True)
class ExecuteUserSnapshotRefreshCommand:
    user_id: str
    snapshot_timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    calculation_version: int
    calculated_at: datetime
    created_at: datetime
    is_recalculated: bool
    publication_job_id: str | None = None
    publication_account_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutedAccountSnapshotRefresh:
    account_id: str
    snapshot_id: str
    mode: AccountSnapshotRefreshMode
    disposition: AccountSnapshotRefreshExecutionDisposition


@dataclass(frozen=True, slots=True)
class ExecuteUserSnapshotRefreshResult:
    user_id: str
    snapshot_timestamp: datetime
    granularity: SnapshotGranularity
    output_currency: str
    source: SnapshotSource
    calculation_version: int
    account_snapshots: tuple[ExecutedAccountSnapshotRefresh, ...]
    required_account_snapshot_identities: tuple[
        SelectedAccountSnapshotIdentity,
        ...,
    ]
    net_worth_snapshot_id: str
    net_worth_disposition: NetWorthSnapshotWriteDisposition
    refresh_account_count: int
    reuse_only_account_count: int
    created_account_snapshot_count: int
    replayed_account_snapshot_count: int
    reused_account_snapshot_count: int
    selected_account_snapshot_count: int
    generation_id: str = "legacy-snapshot-generation:3u0001"
    portfolio_snapshot_id: str | None = None


class _CoverageService(Protocol):
    async def build(
        self,
        command: BuildSnapshotRefreshCoverageCommand,
    ) -> CompleteSnapshotRefreshCoverage: ...


def _generation_id(command: ExecuteUserSnapshotRefreshCommand) -> str:
    return str(
        uuid5(
            _GENERATION_NAMESPACE,
            "\0".join(
                (
                    command.user_id,
                    command.snapshot_timestamp.isoformat(timespec="milliseconds"),
                    command.granularity.value,
                    command.source.value,
                    str(command.calculation_version),
                    command.calculated_at.isoformat(timespec="milliseconds"),
                    command.created_at.isoformat(timespec="milliseconds"),
                    command.publication_job_id or "",
                )
            ),
        )
    )


class _AccountWriter(Protocol):
    async def write(
        self,
        command: WriteAccountSnapshotCommand,
    ) -> AccountSnapshotWriteResult: ...


class _NetWorthWriter(Protocol):
    async def write(
        self,
        command: WriteNetWorthSnapshotCommand,
    ) -> NetWorthSnapshotWriteResult: ...


class _PortfolioWriter(Protocol):
    async def write(
        self,
        command: WritePortfolioSnapshotCommand,
    ) -> PortfolioSnapshotWriteResult: ...


class _DailyBaselineWriter(Protocol):
    async def persist(
        self,
        command: PersistDailySnapshotBaselineCommand,
    ) -> PersistDailySnapshotBaselineResult: ...


type CoverageServiceFactory = Callable[[AsyncSession], _CoverageService]
type AccountSnapshotWriterFactory = Callable[[AsyncSession], _AccountWriter]
type NetWorthSnapshotWriterFactory = Callable[[AsyncSession], _NetWorthWriter]
type PortfolioSnapshotWriterFactory = Callable[[AsyncSession], _PortfolioWriter]
type DailyBaselineWriterFactory = Callable[[AsyncSession], _DailyBaselineWriter]


def _fail() -> SnapshotRefreshExecutionStateError:
    return SnapshotRefreshExecutionStateError()


def _conflict() -> SnapshotRefreshExecutionConflictError:
    return SnapshotRefreshExecutionConflictError()


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    currency = _nonblank(value)
    if (
        len(currency) != 3
        or currency != currency.upper()
        or not currency.isascii()
        or not currency.isalpha()
    ):
        raise _fail()
    return currency


def _timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or precision is None
        or not 0 <= precision <= 6
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise _fail()
    return value


def _aligned_timestamp(
    value: object,
    granularity: SnapshotGranularity,
) -> datetime:
    timestamp = _timestamp(value)
    if granularity is SnapshotGranularity.minute:
        aligned = timestamp.second == 0 and timestamp.microsecond == 0
    elif granularity is SnapshotGranularity.hour:
        aligned = timestamp.minute == 0 and timestamp.second == 0 and timestamp.microsecond == 0
    elif granularity is SnapshotGranularity.day:
        aligned = timestamp.time() == datetime.min.time()
    elif granularity is SnapshotGranularity.week:
        aligned = timestamp.weekday() == 0 and timestamp.time() == datetime.min.time()
    elif granularity is SnapshotGranularity.month:
        aligned = timestamp.day == 1 and timestamp.time() == datetime.min.time()
    else:
        raise _fail()
    if not aligned:
        raise _fail()
    return timestamp


def _calculation_version(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 1 <= value <= _POSTGRES_INTEGER_MAX
    ):
        raise _fail()
    return value


def _count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise _fail()
    return value


def _publication_account_ids(
    value: object,
    *,
    publication_job_id: str | None,
) -> tuple[str, ...]:
    if not isinstance(value, tuple):
        raise _fail()
    account_ids = tuple(_nonblank(item) for item in value)
    if account_ids != tuple(sorted(account_ids)) or len(set(account_ids)) != len(account_ids):
        raise _fail()
    if (publication_job_id is None) != (not account_ids):
        raise _fail()
    return account_ids


def _validate_command(value: object) -> ExecuteUserSnapshotRefreshCommand:
    if not isinstance(value, ExecuteUserSnapshotRefreshCommand):
        raise _fail()
    user_id = _nonblank(value.user_id)
    if (
        not isinstance(value.granularity, SnapshotGranularity)
        or not isinstance(value.source, SnapshotSource)
        or not isinstance(value.is_recalculated, bool)
        or value.is_recalculated is not (value.source is SnapshotSource.manual_recalculation)
        or (
            value.publication_job_id is not None
            and not (
                value.granularity is SnapshotGranularity.minute
                and value.source is SnapshotSource.import_event
            )
        )
    ):
        raise _fail()
    return ExecuteUserSnapshotRefreshCommand(
        user_id=user_id,
        snapshot_timestamp=_aligned_timestamp(
            value.snapshot_timestamp,
            value.granularity,
        ),
        granularity=value.granularity,
        source=value.source,
        calculation_version=_calculation_version(value.calculation_version),
        calculated_at=_timestamp(value.calculated_at),
        created_at=_timestamp(value.created_at),
        is_recalculated=value.is_recalculated,
        publication_job_id=(
            _nonblank(value.publication_job_id) if value.publication_job_id is not None else None
        ),
        publication_account_ids=_publication_account_ids(
            value.publication_account_ids,
            publication_job_id=value.publication_job_id,
        ),
    )


def _target_metadata_matches(
    target: ExpectedAccountSnapshotRefreshTarget,
    command: ExecuteUserSnapshotRefreshCommand,
    *,
    output_currency: str,
) -> bool:
    return (
        target.snapshot_timestamp == command.snapshot_timestamp
        and target.granularity is command.granularity
        and target.source is command.source
        and target.calculation_version == command.calculation_version
        and target.calculated_at == command.calculated_at
        and target.created_at == command.created_at
        and target.is_recalculated is command.is_recalculated
        and target.output_currency == output_currency
    )


def _validated_coverage(
    value: object,
    command: ExecuteUserSnapshotRefreshCommand,
) -> CompleteSnapshotRefreshCoverage:
    if not isinstance(value, CompleteSnapshotRefreshCoverage):
        raise _fail()
    plan = value.plan
    if (
        not isinstance(plan, ExpectedUserSnapshotRefreshPlan)
        or not isinstance(plan.account_targets, tuple)
        or not isinstance(value.refresh_targets, tuple)
        or not isinstance(value.reuse_only_targets, tuple)
        or not isinstance(value.selected_reuse_snapshots, tuple)
        or not isinstance(plan.net_worth_target, ExpectedNetWorthRefreshTarget)
    ):
        raise _fail()
    output_currency = _currency(plan.output_currency)
    net_target = plan.net_worth_target
    if (
        _nonblank(plan.user_id) != command.user_id
        or net_target.user_id != command.user_id
        or net_target.output_currency != output_currency
        or net_target.snapshot_timestamp != command.snapshot_timestamp
        or net_target.granularity is not command.granularity
        or net_target.source is not command.source
        or net_target.calculation_version != command.calculation_version
        or net_target.calculated_at != command.calculated_at
        or net_target.created_at != command.created_at
        or net_target.is_recalculated is not command.is_recalculated
        or not isinstance(net_target.required_account_ids, tuple)
    ):
        raise _fail()

    account_ids: set[str] = set()
    validated_targets: list[ExpectedAccountSnapshotRefreshTarget] = []
    for target in plan.account_targets:
        if not isinstance(target, ExpectedAccountSnapshotRefreshTarget):
            raise _fail()
        account_id = _nonblank(target.account_id)
        account_currency = _currency(target.account_currency)
        if not isinstance(target.membership_role, AccountMemberRole):
            raise _fail()
        expected_mode = (
            AccountSnapshotRefreshMode.refresh
            if account_id in command.publication_account_ids
            or target.membership_role in _REFRESH_ROLES
            else AccountSnapshotRefreshMode.reuse_only
            if target.membership_role is AccountMemberRole.viewer
            else None
        )
        if (
            account_id in account_ids
            or not isinstance(target.account_type, AccountType)
            or target.account_type not in _SUPPORTED_ACCOUNT_TYPES
            or not isinstance(target.mode, AccountSnapshotRefreshMode)
            or target.mode is not expected_mode
            or not isinstance(target.requires_fx_conversion, bool)
            or target.requires_fx_conversion is not (account_currency != output_currency)
            or not _target_metadata_matches(
                target,
                command,
                output_currency=output_currency,
            )
        ):
            raise _fail()
        account_ids.add(account_id)
        validated_targets.append(target)

    plan_targets = tuple(validated_targets)
    plan_account_ids = tuple(target.account_id for target in plan_targets)
    expected_refresh = tuple(
        target for target in plan_targets if target.mode is AccountSnapshotRefreshMode.refresh
    )
    expected_reuse = tuple(
        target for target in plan_targets if target.mode is AccountSnapshotRefreshMode.reuse_only
    )
    if (
        plan_account_ids != tuple(sorted(plan_account_ids))
        or net_target.required_account_ids != plan_account_ids
        or _count(plan.refresh_account_count) != len(expected_refresh)
        or _count(plan.reuse_only_account_count) != len(expected_reuse)
        or _count(plan.fx_conversion_account_count)
        != sum(target.requires_fx_conversion for target in plan_targets)
        or value.refresh_targets != expected_refresh
        or value.reuse_only_targets != expected_reuse
        or _count(value.refresh_target_count) != len(expected_refresh)
        or _count(value.reuse_only_target_count) != len(expected_reuse)
        or _count(value.selected_reuse_snapshot_count) != len(value.selected_reuse_snapshots)
        or len(value.selected_reuse_snapshots) != len(expected_reuse)
    ):
        raise _fail()

    reuse_account_ids: set[str] = set()
    reuse_snapshot_ids: set[str] = set()
    for target, selected in zip(
        expected_reuse,
        value.selected_reuse_snapshots,
        strict=True,
    ):
        if (
            not isinstance(selected, SelectedReusableAccountSnapshot)
            or _nonblank(selected.account_id) != target.account_id
            or _nonblank(selected.snapshot_id) in reuse_snapshot_ids
            or selected.account_id in reuse_account_ids
            or selected.account_id in {item.account_id for item in expected_refresh}
        ):
            raise _fail()
        reuse_account_ids.add(selected.account_id)
        reuse_snapshot_ids.add(selected.snapshot_id)
    return value


def _validate_account_result(
    value: object,
    *,
    target: ExpectedAccountSnapshotRefreshTarget,
    account_ids: set[str],
    snapshot_ids: set[str],
) -> AccountSnapshotWriteResult:
    if (
        not isinstance(value, AccountSnapshotWriteResult)
        or _nonblank(value.account_id) != target.account_id
        or _nonblank(value.snapshot_id) in snapshot_ids
        or value.account_id in account_ids
        or value.timestamp != target.snapshot_timestamp
        or value.granularity is not target.granularity
        or value.currency != target.output_currency
        or not isinstance(value.disposition, AccountSnapshotWriteDisposition)
        or not isinstance(value.item_count, int)
        or isinstance(value.item_count, bool)
        or value.item_count < 0
    ):
        raise _fail()
    return value


def _execution_disposition(
    value: AccountSnapshotWriteDisposition,
    *,
    mode: AccountSnapshotRefreshMode,
) -> AccountSnapshotRefreshExecutionDisposition:
    if mode is AccountSnapshotRefreshMode.reuse_only and value in {
        AccountSnapshotWriteDisposition.created,
        AccountSnapshotWriteDisposition.replayed,
    }:
        # The physical snapshot is generation-local, but financially it is the
        # exact unchanged snapshot selected by coverage.  Public disposition
        # describes that financial decision rather than the clone insert.
        return AccountSnapshotRefreshExecutionDisposition.reused
    if value is AccountSnapshotWriteDisposition.created:
        return AccountSnapshotRefreshExecutionDisposition.created
    if value is AccountSnapshotWriteDisposition.replayed:
        return AccountSnapshotRefreshExecutionDisposition.replayed
    raise _fail()


def _lineage(
    executions: dict[str, ExecutedAccountSnapshotRefresh],
    required_account_ids: tuple[str, ...],
) -> tuple[SelectedAccountSnapshotIdentity, ...]:
    if set(executions) != set(required_account_ids):
        raise _fail()
    identities = tuple(
        SelectedAccountSnapshotIdentity(
            account_id=account_id,
            snapshot_id=executions[account_id].snapshot_id,
        )
        for account_id in required_account_ids
    )
    if (
        tuple(identity.account_id for identity in identities) != required_account_ids
        or len({identity.snapshot_id for identity in identities}) != len(identities)
        or identities
        != tuple(
            sorted(
                identities,
                key=lambda identity: (
                    identity.account_id,
                    identity.snapshot_id,
                ),
            )
        )
    ):
        raise _fail()
    return identities


def _validate_net_worth_result(
    value: object,
    *,
    target: ExpectedNetWorthRefreshTarget,
    identities: tuple[SelectedAccountSnapshotIdentity, ...],
) -> NetWorthSnapshotWriteResult:
    if (
        not isinstance(value, NetWorthSnapshotWriteResult)
        or _nonblank(value.snapshot_id) != value.snapshot_id
        or value.user_id != target.user_id
        or value.timestamp != target.snapshot_timestamp
        or value.granularity is not target.granularity
        or value.currency != target.output_currency
        or not isinstance(value.disposition, NetWorthSnapshotWriteDisposition)
        or _count(value.account_count) != len(identities)
        or _count(value.selected_account_snapshot_count) != len(identities)
        or value.selected_account_snapshot_identities != identities
    ):
        raise _fail()
    return value


class UserSnapshotRefreshExecutor:
    """Coordinate committed account writes followed by one guarded net-worth write."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: SnapshotRefreshExecutorRepository | None = None,
        coverage_service_factory: CoverageServiceFactory = (SnapshotRefreshEvidenceService),
        account_writer_factory: AccountSnapshotWriterFactory | None = None,
        source_policy: MarketEvidenceSourcePolicy = CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        net_worth_writer_factory: NetWorthSnapshotWriterFactory = (NetWorthSnapshotWriter),
        portfolio_writer_factory: PortfolioSnapshotWriterFactory = (PortfolioSnapshotWriter),
        daily_baseline_writer_factory: DailyBaselineWriterFactory = (DailySnapshotBaselineService),
    ) -> None:
        self.session = session
        self.repository = repository or SnapshotRefreshExecutorRepository(session)
        self.coverage_service_factory = coverage_service_factory
        self.source_policy = validate_market_evidence_source_policy(source_policy)
        self.account_writer_factory = account_writer_factory or (
            lambda writer_session: AccountSnapshotWriter(
                writer_session,
                evidence_service=AccountSnapshotEvidenceService(
                    writer_session,
                    source_policy=self.source_policy,
                ),
            )
        )
        self.net_worth_writer_factory = net_worth_writer_factory
        self.portfolio_writer_factory = portfolio_writer_factory
        self.daily_baseline_writer_factory = daily_baseline_writer_factory

    async def _dependency_must_leave_idle(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
            raise RuntimeError("Snapshot refresh dependency left an active transaction.")

    async def execute(
        self,
        command: ExecuteUserSnapshotRefreshCommand,
    ) -> ExecuteUserSnapshotRefreshResult:
        canonical = _validate_command(command)
        generation_id = _generation_id(canonical)
        bind = getattr(self.session, "bind", None)
        # Lightweight protocol fakes exercise the deterministic core directly;
        # production AsyncSession instances always take the database lock.
        if bind is None:
            return await self._execute_locked(canonical)
        if not isinstance(bind, AsyncEngine):
            raise _fail()
        async with bind.connect() as lock_connection:
            await lock_connection.execute(
                text("SELECT pg_advisory_lock(hashtextextended(:key, 0))"),
                {"key": generation_id},
            )
            try:
                return await self._execute_locked(canonical)
            finally:
                await lock_connection.execute(
                    text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"),
                    {"key": generation_id},
                )

    async def _execute_locked(
        self,
        command: ExecuteUserSnapshotRefreshCommand,
    ) -> ExecuteUserSnapshotRefreshResult:
        canonical = _validate_command(command)
        generation_id = _generation_id(canonical)
        if self.session.in_transaction():
            raise _fail()

        try:
            async with self.session.begin():
                await self.repository.set_transaction_repeatable_read()
                await self.repository.ensure_staged_generation(
                    generation_id=generation_id,
                    user_id=canonical.user_id,
                    created_at=canonical.created_at,
                )
                if canonical.publication_account_ids:
                    publication_job = await self.session.scalar(
                        select(BackgroundJobModel)
                        .join(
                            ImportJobPublicationTargetModel,
                            ImportJobPublicationTargetModel.job_id == BackgroundJobModel.id,
                        )
                        .where(
                            BackgroundJobModel.id == canonical.publication_job_id,
                            BackgroundJobModel.kind == BackgroundJobKind.import_workflow,
                            BackgroundJobModel.status == BackgroundJobStatus.running,
                            ImportJobPublicationTargetModel.user_id == canonical.user_id,
                            ImportJobPublicationTargetModel.bucket == canonical.snapshot_timestamp,
                            ImportJobPublicationTargetModel.published_at.is_(None),
                        )
                    )
                    if publication_job is None:
                        raise _fail()
                    affected_account_ids = tuple(
                        (
                            await self.session.scalars(
                                select(ImportJobAffectedAccountModel.account_id)
                                .where(
                                    ImportJobAffectedAccountModel.job_id
                                    == canonical.publication_job_id
                                )
                                .order_by(ImportJobAffectedAccountModel.account_id)
                            )
                        ).all()
                    ) or (publication_job.account_id,)
                    validated_publication_accounts = set(
                        (
                            await self.session.scalars(
                                select(AccountMemberModel.account_id).where(
                                    AccountMemberModel.user_id == canonical.user_id,
                                    AccountMemberModel.account_id.in_(affected_account_ids),
                                )
                            )
                        ).all()
                    )
                    if validated_publication_accounts != set(canonical.publication_account_ids):
                        raise _fail()
                coverage = await self.coverage_service_factory(self.session).build(
                    BuildSnapshotRefreshCoverageCommand(
                        user_id=canonical.user_id,
                        snapshot_timestamp=canonical.snapshot_timestamp,
                        granularity=canonical.granularity,
                        source=canonical.source,
                        calculation_version=canonical.calculation_version,
                        calculated_at=canonical.calculated_at,
                        created_at=canonical.created_at,
                        is_recalculated=canonical.is_recalculated,
                        publication_account_ids=canonical.publication_account_ids,
                    )
                )
                coverage = _validated_coverage(coverage, canonical)
        except (SnapshotRefreshEvidenceStateError, SnapshotRefreshPlanStateError) as exc:
            await self._dependency_must_leave_idle()
            raise _fail() from exc
        except SQLAlchemyError as exc:
            await self._dependency_must_leave_idle()
            raise _fail() from exc
        await self._dependency_must_leave_idle()

        executions: dict[str, ExecutedAccountSnapshotRefresh] = {}
        snapshot_ids: set[str] = set()
        # A publication generation is a complete immutable replacement. Even a
        # financially unchanged account receives a generation-local snapshot;
        # reusing an ID from the previous generation would break the manifest FK.
        for target in coverage.plan.account_targets:
            await self._dependency_must_leave_idle()
            writer = self.account_writer_factory(self.session)
            await self._dependency_must_leave_idle()
            try:
                account_result = await writer.write(
                    WriteAccountSnapshotCommand(
                        account_id=target.account_id,
                        snapshot_timestamp=target.snapshot_timestamp,
                        granularity=target.granularity,
                        source=target.source,
                        calculation_version=target.calculation_version,
                        calculated_at=target.calculated_at,
                        created_at=target.created_at,
                        is_recalculated=target.is_recalculated,
                        output_currency=target.output_currency,
                        generation_id=generation_id,
                    )
                )
            except AccountSnapshotWriteConflictError as exc:
                await self._dependency_must_leave_idle()
                raise _conflict() from exc
            except (
                AccountSnapshotWriteStateError,
                AccountSnapshotEvidenceStateError,
                AccountSnapshotPersistenceProjectionError,
            ) as exc:
                structlog.get_logger(__name__).warning(
                    "account_snapshot_refresh_state",
                    account_id=target.account_id,
                    cause_type=type(exc.__cause__).__name__ if exc.__cause__ is not None else None,
                )
                await self._dependency_must_leave_idle()
                raise _fail() from exc
            await self._dependency_must_leave_idle()
            validated = _validate_account_result(
                account_result,
                target=target,
                account_ids=set(executions),
                snapshot_ids=snapshot_ids,
            )
            snapshot_ids.add(validated.snapshot_id)
            executions[validated.account_id] = ExecutedAccountSnapshotRefresh(
                account_id=validated.account_id,
                snapshot_id=validated.snapshot_id,
                mode=target.mode,
                disposition=_execution_disposition(validated.disposition, mode=target.mode),
            )

        net_target = coverage.plan.net_worth_target
        required_identities = _lineage(
            executions,
            net_target.required_account_ids,
        )
        account_snapshots = tuple(
            executions[identity.account_id] for identity in required_identities
        )

        await self._dependency_must_leave_idle()
        portfolio_writer = self.portfolio_writer_factory(self.session)
        await self._dependency_must_leave_idle()
        try:
            portfolio_result = await portfolio_writer.write(
                WritePortfolioSnapshotCommand(
                    user_id=net_target.user_id,
                    generation_id=generation_id,
                    timestamp=net_target.snapshot_timestamp,
                    granularity=net_target.granularity,
                    source=net_target.source,
                    currency=net_target.output_currency,
                    calculation_version=net_target.calculation_version,
                    calculated_at=net_target.calculated_at,
                    created_at=net_target.created_at,
                    required_account_snapshot_identities=required_identities,
                )
            )
        except PortfolioSnapshotWriteError as exc:
            await self._dependency_must_leave_idle()
            raise _fail() from exc
        await self._dependency_must_leave_idle()
        if (
            portfolio_result.user_id != canonical.user_id
            or portfolio_result.generation_id != generation_id
            or not portfolio_result.portfolio_snapshot_id
        ):
            raise _fail()

        await self._dependency_must_leave_idle()
        net_worth_writer = self.net_worth_writer_factory(self.session)
        await self._dependency_must_leave_idle()
        try:
            net_worth_result = await net_worth_writer.write(
                WriteNetWorthSnapshotCommand(
                    user_id=net_target.user_id,
                    snapshot_timestamp=net_target.snapshot_timestamp,
                    granularity=net_target.granularity,
                    currency=net_target.output_currency,
                    source=net_target.source,
                    calculation_version=net_target.calculation_version,
                    calculated_at=net_target.calculated_at,
                    created_at=net_target.created_at,
                    is_recalculated=net_target.is_recalculated,
                    required_account_snapshot_identities=required_identities,
                    generation_id=generation_id,
                )
            )
        except NetWorthSnapshotWriteConflictError as exc:
            await self._dependency_must_leave_idle()
            raise _conflict() from exc
        except (
            NetWorthSnapshotWriteStateError,
            NetWorthEvidenceStateError,
            NetWorthSnapshotPersistenceProjectionError,
        ) as exc:
            structlog.get_logger(__name__).warning(
                "net_worth_snapshot_refresh_state",
                user_id=canonical.user_id,
                cause_type=type(exc.__cause__).__name__ if exc.__cause__ is not None else None,
            )
            await self._dependency_must_leave_idle()
            raise _fail() from exc
        await self._dependency_must_leave_idle()
        net_worth_result = _validate_net_worth_result(
            net_worth_result,
            target=net_target,
            identities=required_identities,
        )

        if canonical.granularity is SnapshotGranularity.day or (
            canonical.granularity is SnapshotGranularity.minute
            and canonical.source
            in {
                SnapshotSource.import_event,
                SnapshotSource.manual_recalculation,
                SnapshotSource.price_refresh,
                SnapshotSource.scheduled,
            }
            and (
                canonical.source is not SnapshotSource.import_event
                or canonical.publication_job_id is not None
            )
        ):
            await self._dependency_must_leave_idle()
            baseline_writer = self.daily_baseline_writer_factory(self.session)
            await self._dependency_must_leave_idle()
            try:
                baseline_result = await baseline_writer.persist(
                    PersistDailySnapshotBaselineCommand(
                        user_id=canonical.user_id,
                        net_worth_snapshot_id=net_worth_result.snapshot_id,
                        timestamp=canonical.snapshot_timestamp,
                        granularity=canonical.granularity,
                        publication_job_id=canonical.publication_job_id,
                        currency=coverage.plan.output_currency,
                        calculation_version=canonical.calculation_version,
                        source=canonical.source,
                        created_at=canonical.created_at,
                        primary_snapshot_identities=required_identities,
                    )
                )
            except DailyBaselineError as exc:
                structlog.get_logger(__name__).warning(
                    "daily_baseline_snapshot_refresh_state",
                    user_id=canonical.user_id,
                    cause_type=type(exc.__cause__).__name__ if exc.__cause__ is not None else None,
                )
                await self._dependency_must_leave_idle()
                raise _fail() from exc
            await self._dependency_must_leave_idle()
            if (
                not isinstance(baseline_result, PersistDailySnapshotBaselineResult)
                or not isinstance(baseline_result.baseline_id, str)
                or not baseline_result.baseline_id
                or baseline_result.baseline_id != baseline_result.baseline_id.strip()
                or baseline_result.net_worth_snapshot_id != net_worth_result.snapshot_id
                or baseline_result.account_count != len(required_identities)
                or not isinstance(baseline_result.disposition, DailyBaselineDisposition)
            ):
                raise _fail()

        return ExecuteUserSnapshotRefreshResult(
            user_id=canonical.user_id,
            snapshot_timestamp=canonical.snapshot_timestamp,
            granularity=canonical.granularity,
            output_currency=coverage.plan.output_currency,
            source=canonical.source,
            calculation_version=canonical.calculation_version,
            account_snapshots=account_snapshots,
            required_account_snapshot_identities=required_identities,
            net_worth_snapshot_id=net_worth_result.snapshot_id,
            net_worth_disposition=net_worth_result.disposition,
            refresh_account_count=coverage.refresh_target_count,
            reuse_only_account_count=coverage.reuse_only_target_count,
            created_account_snapshot_count=sum(
                item.disposition is AccountSnapshotRefreshExecutionDisposition.created
                for item in account_snapshots
            ),
            replayed_account_snapshot_count=sum(
                item.disposition is AccountSnapshotRefreshExecutionDisposition.replayed
                for item in account_snapshots
            ),
            reused_account_snapshot_count=sum(
                item.disposition is AccountSnapshotRefreshExecutionDisposition.reused
                for item in account_snapshots
            ),
            selected_account_snapshot_count=len(required_identities),
            generation_id=generation_id,
            portfolio_snapshot_id=portfolio_result.portfolio_snapshot_id,
        )
