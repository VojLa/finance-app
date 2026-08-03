"""Internal coordinated execution of exact account and net-worth snapshots."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    AccountMemberRole,
    AccountType,
    SnapshotGranularity,
    SnapshotSource,
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


class _CoverageService(Protocol):
    async def build(
        self,
        command: BuildSnapshotRefreshCoverageCommand,
    ) -> CompleteSnapshotRefreshCoverage: ...


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


type CoverageServiceFactory = Callable[[AsyncSession], _CoverageService]
type AccountSnapshotWriterFactory = Callable[[AsyncSession], _AccountWriter]
type NetWorthSnapshotWriterFactory = Callable[[AsyncSession], _NetWorthWriter]


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


def _validate_command(value: object) -> ExecuteUserSnapshotRefreshCommand:
    if not isinstance(value, ExecuteUserSnapshotRefreshCommand):
        raise _fail()
    user_id = _nonblank(value.user_id)
    if (
        not isinstance(value.granularity, SnapshotGranularity)
        or not isinstance(value.source, SnapshotSource)
        or not isinstance(value.is_recalculated, bool)
        or value.is_recalculated is not (value.source is SnapshotSource.manual_recalculation)
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
            if target.membership_role in _REFRESH_ROLES
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
) -> AccountSnapshotRefreshExecutionDisposition:
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
        account_writer_factory: AccountSnapshotWriterFactory = AccountSnapshotWriter,
        net_worth_writer_factory: NetWorthSnapshotWriterFactory = (NetWorthSnapshotWriter),
    ) -> None:
        self.session = session
        self.repository = repository or SnapshotRefreshExecutorRepository(session)
        self.coverage_service_factory = coverage_service_factory
        self.account_writer_factory = account_writer_factory
        self.net_worth_writer_factory = net_worth_writer_factory

    async def _dependency_must_leave_idle(self) -> None:
        if self.session.in_transaction():
            await self.session.rollback()
            raise RuntimeError("Snapshot refresh dependency left an active transaction.")

    async def execute(
        self,
        command: ExecuteUserSnapshotRefreshCommand,
    ) -> ExecuteUserSnapshotRefreshResult:
        canonical = _validate_command(command)
        if self.session.in_transaction():
            raise _fail()

        try:
            async with self.session.begin():
                await self.repository.set_transaction_repeatable_read()
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
        for target in coverage.refresh_targets:
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
                mode=AccountSnapshotRefreshMode.refresh,
                disposition=_execution_disposition(validated.disposition),
            )

        for selected in coverage.selected_reuse_snapshots:
            if selected.account_id in executions or selected.snapshot_id in snapshot_ids:
                raise _fail()
            snapshot_ids.add(selected.snapshot_id)
            executions[selected.account_id] = ExecutedAccountSnapshotRefresh(
                account_id=selected.account_id,
                snapshot_id=selected.snapshot_id,
                mode=AccountSnapshotRefreshMode.reuse_only,
                disposition=AccountSnapshotRefreshExecutionDisposition.reused,
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
            await self._dependency_must_leave_idle()
            raise _fail() from exc
        await self._dependency_must_leave_idle()
        net_worth_result = _validate_net_worth_result(
            net_worth_result,
            target=net_target,
            identities=required_identities,
        )

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
        )
