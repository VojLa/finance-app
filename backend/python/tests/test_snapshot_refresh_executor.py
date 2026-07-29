from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError

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
    NetWorthSnapshotWriteResult,
    NetWorthSnapshotWriteStateError,
)
from app.modules.snapshot_refresh.evidence_service import (
    BuildSnapshotRefreshCoverageCommand,
    CompleteSnapshotRefreshCoverage,
    SelectedReusableAccountSnapshot,
    SnapshotRefreshEvidenceStateError,
)
from app.modules.snapshot_refresh.executor import (
    AccountSnapshotRefreshExecutionDisposition,
    ExecutedAccountSnapshotRefresh,
    ExecuteUserSnapshotRefreshCommand,
    ExecuteUserSnapshotRefreshResult,
    SnapshotRefreshExecutionConflictError,
    SnapshotRefreshExecutionStateError,
    UserSnapshotRefreshExecutor,
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
    AccountSnapshotWriteResult,
    AccountSnapshotWriteStateError,
)

AT = datetime(2034, 5, 1)
CALCULATED_AT = datetime(2034, 5, 1, 0, 0, 1)
CREATED_AT = datetime(2034, 5, 1, 0, 0, 2)


class _Transaction:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> None:
        self.session.calls.append("coverage begin")
        self.session.active = True

    async def __aexit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        self.session.calls.append("coverage end")
        self.session.active = self.session.remain_active_after_coverage


class _Session:
    def __init__(
        self,
        calls: list[str],
        *,
        active: bool = False,
        remain_active_after_coverage: bool = False,
    ) -> None:
        self.calls = calls
        self.active = active
        self.remain_active_after_coverage = remain_active_after_coverage
        self.rollback = AsyncMock(side_effect=self._rollback)

    async def _rollback(self) -> None:
        self.active = False

    def in_transaction(self) -> bool:
        return self.active

    def begin(self) -> _Transaction:
        return _Transaction(self)


class _Repository:
    def __init__(self, calls: list[str], error: Exception | None = None) -> None:
        self.calls = calls
        self.error = error

    async def set_transaction_repeatable_read(self) -> None:
        self.calls.append("repeatable-read")
        if self.error is not None:
            raise self.error


class _Coverage:
    def __init__(
        self,
        calls: list[str],
        value: object,
        error: Exception | None = None,
    ) -> None:
        self.calls = calls
        self.value = value
        self.error = error
        self.commands: list[object] = []

    async def build(self, command: object) -> Any:
        self.calls.append("coverage build")
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return self.value


class _AccountWriters:
    def __init__(
        self,
        calls: list[str],
        results: dict[str, object],
        *,
        session: _Session | None = None,
        leave_active_for: str | None = None,
    ) -> None:
        self.calls = calls
        self.results = results
        self.session = session
        self.leave_active_for = leave_active_for
        self.commands: list[Any] = []
        self.factory_calls = 0

    def __call__(self, session: object) -> _AccountWriters:
        self.factory_calls += 1
        return self

    async def write(self, command: Any) -> Any:
        self.calls.append(f"account writer {command.account_id}")
        self.commands.append(command)
        value = self.results[command.account_id]
        if self.session is not None and command.account_id == self.leave_active_for:
            self.session.active = True
        if isinstance(value, Exception):
            raise value
        return value


class _NetWorthWriter:
    def __init__(
        self,
        calls: list[str],
        value: object,
        *,
        error: Exception | None = None,
        session: _Session | None = None,
        leave_active: bool = False,
    ) -> None:
        self.calls = calls
        self.value = value
        self.error = error
        self.session = session
        self.leave_active = leave_active
        self.commands: list[Any] = []
        self.factory_calls = 0

    def __call__(self, session: object) -> _NetWorthWriter:
        self.factory_calls += 1
        return self

    async def write(self, command: Any) -> Any:
        self.calls.append("net-worth writer")
        self.commands.append(command)
        if self.leave_active and self.session is not None:
            self.session.active = True
        if self.error is not None:
            raise self.error
        return self.value


def _command(**changes: object) -> ExecuteUserSnapshotRefreshCommand:
    values: dict[str, object] = {
        "user_id": "user-1",
        "snapshot_timestamp": AT,
        "granularity": SnapshotGranularity.day,
        "source": SnapshotSource.manual_recalculation,
        "calculation_version": 1,
        "calculated_at": CALCULATED_AT,
        "created_at": CREATED_AT,
        "is_recalculated": True,
    }
    values.update(changes)
    return ExecuteUserSnapshotRefreshCommand(**cast(Any, values))


def _target(
    account_id: str,
    mode: AccountSnapshotRefreshMode,
    *,
    output_currency: str = "EUR",
) -> ExpectedAccountSnapshotRefreshTarget:
    role = (
        AccountMemberRole.owner
        if mode is AccountSnapshotRefreshMode.refresh
        else AccountMemberRole.viewer
    )
    return ExpectedAccountSnapshotRefreshTarget(
        account_id=account_id,
        account_type=AccountType.loan,
        account_currency="CZK",
        output_currency=output_currency,
        requires_fx_conversion=output_currency != "CZK",
        mode=mode,
        membership_role=role,
        snapshot_timestamp=AT,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        calculated_at=CALCULATED_AT,
        created_at=CREATED_AT,
        is_recalculated=True,
    )


def _coverage(
    modes: tuple[tuple[str, AccountSnapshotRefreshMode], ...] = (
        ("account-a", AccountSnapshotRefreshMode.refresh),
        ("account-b", AccountSnapshotRefreshMode.refresh),
    ),
) -> CompleteSnapshotRefreshCoverage:
    targets = tuple(_target(account_id, mode) for account_id, mode in modes)
    refresh = tuple(
        target for target in targets if target.mode is AccountSnapshotRefreshMode.refresh
    )
    reuse = tuple(
        target for target in targets if target.mode is AccountSnapshotRefreshMode.reuse_only
    )
    selected = tuple(
        SelectedReusableAccountSnapshot(
            account_id=target.account_id,
            snapshot_id=f"snapshot-{target.account_id}",
        )
        for target in reuse
    )
    required = tuple(target.account_id for target in targets)
    net_target = ExpectedNetWorthRefreshTarget(
        user_id="user-1",
        output_currency="EUR",
        snapshot_timestamp=AT,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        calculated_at=CALCULATED_AT,
        created_at=CREATED_AT,
        is_recalculated=True,
        required_account_ids=required,
    )
    plan = ExpectedUserSnapshotRefreshPlan(
        user_id="user-1",
        output_currency="EUR",
        account_targets=targets,
        net_worth_target=net_target,
        refresh_account_count=len(refresh),
        reuse_only_account_count=len(reuse),
        fx_conversion_account_count=len(targets),
    )
    return CompleteSnapshotRefreshCoverage(
        plan=plan,
        refresh_targets=refresh,
        reuse_only_targets=reuse,
        selected_reuse_snapshots=selected,
        refresh_target_count=len(refresh),
        reuse_only_target_count=len(reuse),
        selected_reuse_snapshot_count=len(selected),
    )


def _account_result(
    account_id: str,
    disposition: AccountSnapshotWriteDisposition = (AccountSnapshotWriteDisposition.created),
) -> AccountSnapshotWriteResult:
    return AccountSnapshotWriteResult(
        snapshot_id=f"snapshot-{account_id}",
        account_id=account_id,
        disposition=disposition,
        item_count=0,
        timestamp=AT,
        granularity=SnapshotGranularity.day,
        currency="EUR",
    )


def _identities(
    coverage: CompleteSnapshotRefreshCoverage,
) -> tuple[SelectedAccountSnapshotIdentity, ...]:
    return tuple(
        SelectedAccountSnapshotIdentity(
            target.account_id,
            f"snapshot-{target.account_id}",
        )
        for target in coverage.plan.account_targets
    )


def _net_result(
    coverage: CompleteSnapshotRefreshCoverage,
    disposition: NetWorthSnapshotWriteDisposition = (NetWorthSnapshotWriteDisposition.created),
) -> NetWorthSnapshotWriteResult:
    identities = _identities(coverage)
    return NetWorthSnapshotWriteResult(
        snapshot_id="net-worth-1",
        user_id="user-1",
        disposition=disposition,
        timestamp=AT,
        granularity=SnapshotGranularity.day,
        currency="EUR",
        account_count=len(identities),
        selected_account_snapshot_count=len(identities),
        selected_account_snapshot_identities=identities,
    )


def _executor(
    coverage_value: object | None = None,
    *,
    account_results: dict[str, object] | None = None,
    net_value: object | None = None,
    session: _Session | None = None,
    repository_error: Exception | None = None,
    coverage_error: Exception | None = None,
    account_leave_active_for: str | None = None,
    net_error: Exception | None = None,
    net_leave_active: bool = False,
) -> tuple[
    UserSnapshotRefreshExecutor,
    _Session,
    _Coverage,
    _AccountWriters,
    _NetWorthWriter,
    list[str],
]:
    calls: list[str] = []
    active_coverage = coverage_value if coverage_value is not None else _coverage()
    contract_coverage = (
        active_coverage
        if isinstance(active_coverage, CompleteSnapshotRefreshCoverage)
        else _coverage()
    )
    active_session = session or _Session(calls)
    coverage = _Coverage(calls, active_coverage, coverage_error)
    results = account_results or {
        target.account_id: _account_result(target.account_id)
        for target in contract_coverage.refresh_targets
    }
    accounts = _AccountWriters(
        calls,
        results,
        session=active_session,
        leave_active_for=account_leave_active_for,
    )
    resolved_net = net_value if net_value is not None else _net_result(contract_coverage)
    net = _NetWorthWriter(
        calls,
        resolved_net,
        error=net_error,
        session=active_session,
        leave_active=net_leave_active,
    )
    executor = UserSnapshotRefreshExecutor(
        cast(Any, active_session),
        repository=cast(Any, _Repository(calls, repository_error)),
        coverage_service_factory=cast(Any, Mock(return_value=coverage)),
        account_writer_factory=cast(Any, accounts),
        net_worth_writer_factory=cast(Any, net),
    )
    return executor, active_session, coverage, accounts, net, calls


@pytest.mark.parametrize(
    "value",
    [
        cast(Any, object()),
        _command(user_id=""),
        _command(user_id=" user"),
        _command(snapshot_timestamp="2034-05-01"),
        _command(snapshot_timestamp=AT.replace(tzinfo=UTC)),
        _command(snapshot_timestamp=AT.replace(microsecond=1)),
        _command(snapshot_timestamp=AT.replace(hour=1)),
        _command(granularity=cast(Any, "day")),
        _command(source=cast(Any, "manual_recalculation")),
        _command(calculation_version=0),
        _command(calculation_version=-1),
        _command(calculation_version=True),
        _command(calculation_version=2_147_483_648),
        _command(calculated_at=CALCULATED_AT.replace(tzinfo=UTC)),
        _command(created_at=CREATED_AT.replace(microsecond=1)),
        _command(is_recalculated=False),
    ],
)
@pytest.mark.asyncio
async def test_invalid_command_fails_before_io(value: object) -> None:
    executor, session, coverage, accounts, net, calls = _executor()

    with pytest.raises(
        SnapshotRefreshExecutionStateError,
        match=r"^Coordinated snapshot refresh could not be completed\.$",
    ):
        await executor.execute(cast(Any, value))

    assert calls == []
    assert coverage.commands == []
    assert accounts.factory_calls == net.factory_calls == 0
    session.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_operation_order_commands_lineage_and_counts_are_exact() -> None:
    coverage_value = _coverage()
    executor, _, coverage, accounts, net, calls = _executor(coverage_value)

    result = await executor.execute(_command())

    assert calls == [
        "coverage begin",
        "repeatable-read",
        "coverage build",
        "coverage end",
        "account writer account-a",
        "account writer account-b",
        "net-worth writer",
    ]
    assert coverage.commands == [
        BuildSnapshotRefreshCoverageCommand(
            user_id="user-1",
            snapshot_timestamp=AT,
            granularity=SnapshotGranularity.day,
            source=SnapshotSource.manual_recalculation,
            calculation_version=1,
            calculated_at=CALCULATED_AT,
            created_at=CREATED_AT,
            is_recalculated=True,
        )
    ]
    assert [command.account_id for command in accounts.commands] == [
        "account-a",
        "account-b",
    ]
    assert all(command.output_currency == "EUR" for command in accounts.commands)
    assert net.commands[0].required_account_snapshot_identities == _identities(coverage_value)
    assert result.account_snapshots == (
        ExecutedAccountSnapshotRefresh(
            "account-a",
            "snapshot-account-a",
            AccountSnapshotRefreshMode.refresh,
            AccountSnapshotRefreshExecutionDisposition.created,
        ),
        ExecutedAccountSnapshotRefresh(
            "account-b",
            "snapshot-account-b",
            AccountSnapshotRefreshMode.refresh,
            AccountSnapshotRefreshExecutionDisposition.created,
        ),
    )
    assert result.created_account_snapshot_count == 2
    assert result.replayed_account_snapshot_count == 0
    assert result.reused_account_snapshot_count == 0
    assert result.selected_account_snapshot_count == 2


@pytest.mark.asyncio
async def test_mixed_refresh_and_reuse_never_writes_viewer_target() -> None:
    coverage_value = _coverage(
        (
            ("account-a", AccountSnapshotRefreshMode.refresh),
            ("account-b", AccountSnapshotRefreshMode.reuse_only),
        )
    )
    executor, _, _, accounts, net, _ = _executor(coverage_value)

    result = await executor.execute(_command())

    assert [command.account_id for command in accounts.commands] == ["account-a"]
    assert result.account_snapshots[1].mode is AccountSnapshotRefreshMode.reuse_only
    assert (
        result.account_snapshots[1].disposition is AccountSnapshotRefreshExecutionDisposition.reused
    )
    assert result.refresh_account_count == 1
    assert result.reuse_only_account_count == 1
    assert result.reused_account_snapshot_count == 1
    assert net.commands[0].required_account_snapshot_identities == _identities(coverage_value)


@pytest.mark.asyncio
async def test_all_reuse_and_empty_plans_skip_account_writer() -> None:
    for coverage_value in (
        _coverage(
            (
                ("account-a", AccountSnapshotRefreshMode.reuse_only),
                ("account-b", AccountSnapshotRefreshMode.reuse_only),
            )
        ),
        _coverage(()),
    ):
        executor, _, _, accounts, net, _ = _executor(coverage_value)

        result = await executor.execute(_command())

        assert accounts.commands == []
        assert result.required_account_snapshot_identities == _identities(coverage_value)
        assert len(net.commands) == 1


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: cast(Any, object()),
        lambda value: replace(value, refresh_target_count=99),
        lambda value: replace(
            value,
            plan=replace(value.plan, output_currency="usd"),
        ),
        lambda value: replace(
            value,
            plan=replace(value.plan, user_id="other"),
        ),
        lambda value: replace(
            value,
            plan=replace(
                value.plan,
                net_worth_target=replace(
                    value.plan.net_worth_target,
                    required_account_ids=("account-b", "account-a"),
                ),
            ),
        ),
        lambda value: replace(
            value,
            refresh_targets=value.refresh_targets[1:],
        ),
        lambda value: replace(
            value,
            reuse_only_targets=(value.refresh_targets[0],),
        ),
    ],
)
@pytest.mark.asyncio
async def test_malformed_coverage_fails_before_writer(
    mutate: Any,
) -> None:
    mixed = _coverage(
        (
            ("account-a", AccountSnapshotRefreshMode.refresh),
            ("account-b", AccountSnapshotRefreshMode.reuse_only),
        )
    )
    executor, _, _, accounts, net, _ = _executor(mutate(mixed))

    with pytest.raises(SnapshotRefreshExecutionStateError):
        await executor.execute(_command())

    assert accounts.commands == []
    assert net.commands == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_id", "other"),
        ("snapshot_id", ""),
        ("timestamp", AT.replace(day=2)),
        ("granularity", SnapshotGranularity.hour),
        ("currency", "CZK"),
        ("disposition", cast(Any, "created")),
        ("item_count", -1),
        ("item_count", True),
    ],
)
@pytest.mark.asyncio
async def test_malformed_account_result_stops_before_next_stage(
    field: str,
    value: object,
) -> None:
    result = replace(
        _account_result("account-a"),
        **cast(Any, {field: value}),
    )
    executor, _, _, accounts, net, _ = _executor(
        account_results={
            "account-a": result,
            "account-b": _account_result("account-b"),
        }
    )

    with pytest.raises(SnapshotRefreshExecutionStateError):
        await executor.execute(_command())

    assert len(accounts.commands) == 1
    assert net.commands == []


@pytest.mark.asyncio
async def test_duplicate_snapshot_identity_fails_before_net_worth() -> None:
    duplicate = replace(
        _account_result("account-b"),
        snapshot_id="snapshot-account-a",
    )
    executor, _, _, _, net, _ = _executor(
        account_results={
            "account-a": _account_result("account-a"),
            "account-b": duplicate,
        }
    )

    with pytest.raises(SnapshotRefreshExecutionStateError):
        await executor.execute(_command())

    assert net.commands == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("user_id", "other"),
        ("snapshot_id", ""),
        ("timestamp", AT.replace(day=2)),
        ("granularity", SnapshotGranularity.hour),
        ("currency", "CZK"),
        ("disposition", cast(Any, "created")),
        ("account_count", 1),
        ("selected_account_snapshot_count", 1),
        ("selected_account_snapshot_identities", ()),
    ],
)
@pytest.mark.asyncio
async def test_malformed_net_worth_result_fails_closed(
    field: str,
    value: object,
) -> None:
    coverage_value = _coverage()
    malformed = replace(
        _net_result(coverage_value),
        **cast(Any, {field: value}),
    )
    executor, _, _, _, _, _ = _executor(
        coverage_value,
        net_value=malformed,
    )

    with pytest.raises(SnapshotRefreshExecutionStateError):
        await executor.execute(_command())


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (SnapshotRefreshEvidenceStateError(), SnapshotRefreshExecutionStateError),
        (SnapshotRefreshPlanStateError(), SnapshotRefreshExecutionStateError),
        (SQLAlchemyError("db"), SnapshotRefreshExecutionStateError),
    ],
)
@pytest.mark.asyncio
async def test_coverage_errors_map_with_cause(
    error: Exception,
    expected: type[Exception],
) -> None:
    executor, _, _, _, _, _ = _executor(coverage_error=error)

    with pytest.raises(expected) as caught:
        await executor.execute(_command())

    assert caught.value.__cause__ is error


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (AccountSnapshotWriteStateError(), SnapshotRefreshExecutionStateError),
        (AccountSnapshotEvidenceStateError(), SnapshotRefreshExecutionStateError),
        (
            AccountSnapshotPersistenceProjectionError(),
            SnapshotRefreshExecutionStateError,
        ),
        (AccountSnapshotWriteConflictError(), SnapshotRefreshExecutionConflictError),
    ],
)
@pytest.mark.asyncio
async def test_account_errors_map_and_stop_remaining_targets(
    error: Exception,
    expected: type[Exception],
) -> None:
    executor, _, _, accounts, net, _ = _executor(
        account_results={
            "account-a": error,
            "account-b": _account_result("account-b"),
        }
    )

    with pytest.raises(expected) as caught:
        await executor.execute(_command())

    assert caught.value.__cause__ is error
    assert len(accounts.commands) == 1
    assert net.commands == []


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (NetWorthSnapshotWriteStateError(), SnapshotRefreshExecutionStateError),
        (NetWorthEvidenceStateError(), SnapshotRefreshExecutionStateError),
        (
            NetWorthSnapshotPersistenceProjectionError(),
            SnapshotRefreshExecutionStateError,
        ),
        (NetWorthSnapshotWriteConflictError(), SnapshotRefreshExecutionConflictError),
    ],
)
@pytest.mark.asyncio
async def test_net_worth_errors_map_with_cause(
    error: Exception,
    expected: type[Exception],
) -> None:
    executor, _, _, _, _, _ = _executor(net_error=error)

    with pytest.raises(expected) as caught:
        await executor.execute(_command())

    assert caught.value.__cause__ is error


@pytest.mark.asyncio
async def test_unexpected_factory_error_propagates_unchanged() -> None:
    error = RuntimeError("controlled programming error")
    executor, _, _, _, _, _ = _executor()
    executor.account_writer_factory = Mock(side_effect=error)

    with pytest.raises(RuntimeError) as caught:
        await executor.execute(_command())

    assert caught.value is error


@pytest.mark.asyncio
async def test_active_entry_session_is_rejected() -> None:
    calls: list[str] = []
    session = _Session(calls, active=True)
    executor, _, _, _, _, _ = _executor(session=session)

    with pytest.raises(SnapshotRefreshExecutionStateError):
        await executor.execute(_command())

    assert calls == []


@pytest.mark.asyncio
async def test_dependency_transaction_leaks_are_rolled_back_and_exposed() -> None:
    calls: list[str] = []
    coverage_session = _Session(
        calls,
        remain_active_after_coverage=True,
    )
    executor, _, _, _, _, _ = _executor(session=coverage_session)
    with pytest.raises(RuntimeError, match="left an active transaction"):
        await executor.execute(_command())
    coverage_session.rollback.assert_awaited_once()

    executor, account_session, _, _, _, _ = _executor(
        account_leave_active_for="account-a",
    )
    with pytest.raises(RuntimeError, match="left an active transaction"):
        await executor.execute(_command())
    account_session.rollback.assert_awaited_once()

    executor, net_session, _, _, _, _ = _executor(net_leave_active=True)
    with pytest.raises(RuntimeError, match="left an active transaction"):
        await executor.execute(_command())
    net_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_created_then_failed_run_can_resume_with_replay() -> None:
    first_executor, _, _, first_accounts, first_net, _ = _executor(
        account_results={
            "account-a": _account_result("account-a"),
            "account-b": AccountSnapshotWriteStateError(),
        }
    )
    with pytest.raises(SnapshotRefreshExecutionStateError):
        await first_executor.execute(_command())
    assert [item.account_id for item in first_accounts.commands] == [
        "account-a",
        "account-b",
    ]
    assert first_net.commands == []

    second_executor, _, _, _, _, _ = _executor(
        account_results={
            "account-a": _account_result(
                "account-a",
                AccountSnapshotWriteDisposition.replayed,
            ),
            "account-b": _account_result("account-b"),
        }
    )
    result = await second_executor.execute(_command())
    assert result.replayed_account_snapshot_count == 1
    assert result.created_account_snapshot_count == 1


@pytest.mark.asyncio
async def test_repository_emits_exact_repeatable_read_statement() -> None:
    session = Mock(execute=AsyncMock())
    await SnapshotRefreshExecutorRepository(cast(Any, session)).set_transaction_repeatable_read()

    session.execute.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    assert str(statement) == "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"


def test_command_and_result_contracts_are_frozen() -> None:
    command = _command()
    execution = ExecutedAccountSnapshotRefresh(
        "account-a",
        "snapshot-a",
        AccountSnapshotRefreshMode.refresh,
        AccountSnapshotRefreshExecutionDisposition.created,
    )
    result = ExecuteUserSnapshotRefreshResult(
        user_id="user-1",
        snapshot_timestamp=AT,
        granularity=SnapshotGranularity.day,
        output_currency="EUR",
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        account_snapshots=(execution,),
        required_account_snapshot_identities=(
            SelectedAccountSnapshotIdentity("account-a", "snapshot-a"),
        ),
        net_worth_snapshot_id="net-worth-1",
        net_worth_disposition=NetWorthSnapshotWriteDisposition.created,
        refresh_account_count=1,
        reuse_only_account_count=0,
        created_account_snapshot_count=1,
        replayed_account_snapshot_count=0,
        reused_account_snapshot_count=0,
        selected_account_snapshot_count=1,
    )

    for value, field in (
        (command, "user_id"),
        (execution, "account_id"),
        (result, "user_id"),
    ):
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(field, "changed")
        assert not hasattr(value, "__dict__")
