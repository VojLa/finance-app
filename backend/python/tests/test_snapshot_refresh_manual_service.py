from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.modules.net_worth.evidence_service import SelectedAccountSnapshotIdentity
from app.modules.net_worth.writer import NetWorthSnapshotWriteDisposition
from app.modules.snapshot_refresh import version as snapshot_refresh_version
from app.modules.snapshot_refresh.executor import (
    AccountSnapshotRefreshExecutionDisposition,
    ExecutedAccountSnapshotRefresh,
    ExecuteUserSnapshotRefreshCommand,
    ExecuteUserSnapshotRefreshResult,
    SnapshotRefreshExecutionConflictError,
    SnapshotRefreshExecutionStateError,
)
from app.modules.snapshot_refresh.manual_service import (
    CURRENT_USER_SNAPSHOT_REFRESH_CALCULATION_VERSION,
    MANUAL_USER_SNAPSHOT_REFRESH_GRANULARITY,
    MANUAL_USER_SNAPSHOT_REFRESH_SOURCE,
    ManualUserSnapshotRefreshService,
    RecalculateUserSnapshotRefreshCommand,
    RecalculateUserSnapshotRefreshResult,
    UserSnapshotRefreshConflictError,
    UserSnapshotRefreshUnavailableError,
    canonical_manual_user_snapshot_refresh_bucket,
)
from app.modules.snapshot_refresh.plan import AccountSnapshotRefreshMode

BUCKET = datetime(2036, 4, 5, 10, 20)
RAW_NOW = datetime(
    2036,
    4,
    5,
    12,
    20,
    59,
    987654,
    tzinfo=timezone(timedelta(hours=2)),
)


def _principal(user_id: str = "user-a") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.test",
        name=user_id,
    )


def _execution(
    account_id: str,
    disposition: AccountSnapshotRefreshExecutionDisposition,
) -> ExecutedAccountSnapshotRefresh:
    mode = (
        AccountSnapshotRefreshMode.reuse_only
        if disposition is AccountSnapshotRefreshExecutionDisposition.reused
        else AccountSnapshotRefreshMode.refresh
    )
    return ExecutedAccountSnapshotRefresh(
        account_id=account_id,
        snapshot_id=f"snapshot-{account_id}",
        mode=mode,
        disposition=disposition,
    )


def _executor_result(
    *,
    net_worth_disposition: NetWorthSnapshotWriteDisposition = (
        NetWorthSnapshotWriteDisposition.created
    ),
    executions: tuple[ExecutedAccountSnapshotRefresh, ...] | None = None,
) -> ExecuteUserSnapshotRefreshResult:
    account_executions = (
        (
            _execution(
                "account-a",
                AccountSnapshotRefreshExecutionDisposition.created,
            ),
            _execution(
                "account-b",
                AccountSnapshotRefreshExecutionDisposition.replayed,
            ),
            _execution(
                "account-c",
                AccountSnapshotRefreshExecutionDisposition.reused,
            ),
        )
        if executions is None
        else executions
    )
    lineage = tuple(
        SelectedAccountSnapshotIdentity(item.account_id, item.snapshot_id)
        for item in account_executions
    )
    return ExecuteUserSnapshotRefreshResult(
        user_id="user-a",
        snapshot_timestamp=BUCKET,
        granularity=SnapshotGranularity.minute,
        output_currency="EUR",
        source=SnapshotSource.manual_recalculation,
        calculation_version=CURRENT_USER_SNAPSHOT_REFRESH_CALCULATION_VERSION,
        account_snapshots=account_executions,
        required_account_snapshot_identities=lineage,
        net_worth_snapshot_id="net-worth-a",
        net_worth_disposition=net_worth_disposition,
        refresh_account_count=sum(
            item.mode is AccountSnapshotRefreshMode.refresh for item in account_executions
        ),
        reuse_only_account_count=sum(
            item.mode is AccountSnapshotRefreshMode.reuse_only for item in account_executions
        ),
        created_account_snapshot_count=sum(
            item.disposition is AccountSnapshotRefreshExecutionDisposition.created
            for item in account_executions
        ),
        replayed_account_snapshot_count=sum(
            item.disposition is AccountSnapshotRefreshExecutionDisposition.replayed
            for item in account_executions
        ),
        reused_account_snapshot_count=sum(
            item.disposition is AccountSnapshotRefreshExecutionDisposition.reused
            for item in account_executions
        ),
        selected_account_snapshot_count=len(account_executions),
    )


def _session(
    *,
    active: bool = True,
    remain_active_after_commit: bool = False,
    commit_error: Exception | None = None,
) -> AsyncSession:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    state = {"active": active}
    cast(Any, session.in_transaction).side_effect = lambda: state["active"]

    async def commit() -> None:
        if commit_error is not None:
            raise commit_error
        if not remain_active_after_commit:
            state["active"] = False

    async def rollback() -> None:
        state["active"] = False

    cast(Any, session.commit).side_effect = commit
    cast(Any, session.rollback).side_effect = rollback
    return session


def _service(
    *,
    session: AsyncSession | None = None,
    result: object | None = None,
    error: Exception | None = None,
    clock: Mock | None = None,
) -> tuple[ManualUserSnapshotRefreshService, AsyncSession, Mock, Mock]:
    active_session = session or _session()
    executor = Mock(
        execute=AsyncMock(
            return_value=result or _executor_result(),
            side_effect=error,
        )
    )
    factory = Mock(return_value=executor)
    active_clock = clock or Mock(return_value=RAW_NOW)
    service = ManualUserSnapshotRefreshService(
        active_session,
        clock=active_clock,
        executor_factory=factory,
    )
    return service, active_session, factory, executor


@pytest.mark.parametrize(
    "command",
    [
        cast(Any, object()),
        RecalculateUserSnapshotRefreshCommand(principal=cast(Any, object())),
        RecalculateUserSnapshotRefreshCommand(principal=_principal("")),
        RecalculateUserSnapshotRefreshCommand(principal=_principal(" user-a")),
        RecalculateUserSnapshotRefreshCommand(principal=_principal("user-a ")),
    ],
)
async def test_invalid_command_fails_before_clock_and_executor(command: object) -> None:
    clock = Mock()
    service, session, factory, _ = _service(clock=clock)

    with pytest.raises(UserSnapshotRefreshUnavailableError):
        await service.recalculate(cast(Any, command))

    clock.assert_not_called()
    factory.assert_not_called()
    cast(Any, session.commit).assert_not_awaited()
    cast(Any, session.rollback).assert_awaited_once_with()


async def test_exact_executor_command_uses_principal_and_one_bucket() -> None:
    clock = Mock(return_value=RAW_NOW)
    service, session, factory, executor = _service(clock=clock)

    result = await service.recalculate(
        RecalculateUserSnapshotRefreshCommand(principal=_principal())
    )

    cast(Any, session.commit).assert_awaited_once_with()
    factory.assert_called_once_with(session)
    executor.execute.assert_awaited_once_with(
        ExecuteUserSnapshotRefreshCommand(
            user_id="user-a",
            snapshot_timestamp=BUCKET,
            granularity=MANUAL_USER_SNAPSHOT_REFRESH_GRANULARITY,
            source=MANUAL_USER_SNAPSHOT_REFRESH_SOURCE,
            calculation_version=CURRENT_USER_SNAPSHOT_REFRESH_CALCULATION_VERSION,
            calculated_at=BUCKET,
            created_at=BUCKET,
            is_recalculated=True,
        )
    )
    clock.assert_called_once_with()
    assert result.net_worth_snapshot_id == "net-worth-a"
    assert result.net_worth_status == "created"
    assert result.currency == "EUR"
    assert not hasattr(executor.execute.await_args.args[0], "output_currency")


def test_manual_bucket_normalizes_aware_and_naive_values() -> None:
    assert canonical_manual_user_snapshot_refresh_bucket(RAW_NOW) == BUCKET
    assert (
        canonical_manual_user_snapshot_refresh_bucket(BUCKET.replace(second=59, microsecond=999999))
        == BUCKET
    )
    assert canonical_manual_user_snapshot_refresh_bucket(
        RAW_NOW + timedelta(minutes=1)
    ) == BUCKET + timedelta(minutes=1)
    assert canonical_manual_user_snapshot_refresh_bucket(BUCKET).tzinfo is None


async def test_invalid_clock_result_maps_unavailable_without_executor() -> None:
    service, _, factory, _ = _service(clock=Mock(return_value="not-a-datetime"))

    with pytest.raises(UserSnapshotRefreshUnavailableError):
        await service.recalculate(RecalculateUserSnapshotRefreshCommand(principal=_principal()))

    factory.assert_not_called()


async def test_calculation_version_mismatch_fails_before_clock_and_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        snapshot_refresh_version,
        "CURRENT_NET_WORTH_CALCULATION_VERSION",
        CURRENT_USER_SNAPSHOT_REFRESH_CALCULATION_VERSION + 1,
    )
    clock = Mock()
    service, session, factory, _ = _service(clock=clock)

    with pytest.raises(UserSnapshotRefreshUnavailableError):
        await service.recalculate(RecalculateUserSnapshotRefreshCommand(principal=_principal()))

    clock.assert_not_called()
    factory.assert_not_called()
    cast(Any, session.rollback).assert_awaited_once_with()


async def test_commit_finishes_before_executor_factory_receives_idle_session() -> None:
    events: list[str] = []
    session = _session()
    original_commit = cast(Any, session.commit).side_effect
    executor = Mock(execute=AsyncMock(return_value=_executor_result()))

    async def commit() -> None:
        events.append("commit")
        await original_commit()

    def factory(received: AsyncSession) -> object:
        events.append("factory")
        assert received is session
        assert received.in_transaction() is False
        return executor

    cast(Any, session.commit).side_effect = commit
    await ManualUserSnapshotRefreshService(
        session,
        clock=lambda: RAW_NOW,
        executor_factory=cast(Any, factory),
    ).recalculate(RecalculateUserSnapshotRefreshCommand(principal=_principal()))

    assert events == ["commit", "factory"]


async def test_commit_failure_rolls_back_and_propagates_original() -> None:
    failure = SQLAlchemyError("controlled commit failure")
    session = _session(commit_error=failure)
    service, _, factory, _ = _service(session=session)

    with pytest.raises(SQLAlchemyError) as raised:
        await service.recalculate(RecalculateUserSnapshotRefreshCommand(principal=_principal()))

    assert raised.value is failure
    cast(Any, session.rollback).assert_awaited_once_with()
    factory.assert_not_called()


async def test_active_session_after_commit_is_internal_failure() -> None:
    session = _session(remain_active_after_commit=True)
    service, _, factory, _ = _service(session=session)

    with pytest.raises(RuntimeError, match="requires an idle database session"):
        await service.recalculate(RecalculateUserSnapshotRefreshCommand(principal=_principal()))

    cast(Any, session.rollback).assert_awaited_once_with()
    factory.assert_not_called()


@pytest.mark.parametrize("stage", ["factory", "executor"])
async def test_dependency_transaction_leak_rolls_back_as_runtime_error(
    stage: str,
) -> None:
    session = _session()
    state = cast(Any, session.in_transaction).side_effect
    executor = Mock(execute=AsyncMock(return_value=_executor_result()))

    def factory(received: AsyncSession) -> object:
        if stage == "factory":
            cast(Any, received.in_transaction).side_effect = lambda: True
        return executor

    if stage == "executor":

        async def execute(command: object) -> object:
            cast(Any, session.in_transaction).side_effect = lambda: True
            return _executor_result()

        executor.execute.side_effect = execute

    service = ManualUserSnapshotRefreshService(
        session,
        clock=lambda: RAW_NOW,
        executor_factory=cast(Any, factory),
    )
    with pytest.raises(RuntimeError, match="active database transaction"):
        await service.recalculate(RecalculateUserSnapshotRefreshCommand(principal=_principal()))

    cast(Any, session.rollback).assert_awaited_once_with()
    assert state is not None


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (
            SnapshotRefreshExecutionStateError(),
            UserSnapshotRefreshUnavailableError,
        ),
        (
            SnapshotRefreshExecutionConflictError(),
            UserSnapshotRefreshConflictError,
        ),
    ],
)
async def test_executor_errors_map_to_generic_application_errors(
    failure: Exception,
    expected: type[Exception],
) -> None:
    service, _, _, executor = _service(error=failure)

    with pytest.raises(expected) as raised:
        await service.recalculate(RecalculateUserSnapshotRefreshCommand(principal=_principal()))

    assert raised.value.__cause__ is failure
    assert str(failure) not in str(raised.value)
    executor.execute.assert_awaited_once()


async def test_unexpected_executor_error_propagates_unchanged() -> None:
    failure = RuntimeError("controlled programming error")
    service, _, _, _ = _service(error=failure)

    with pytest.raises(RuntimeError) as raised:
        await service.recalculate(RecalculateUserSnapshotRefreshCommand(principal=_principal()))

    assert raised.value is failure


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: cast(Any, object()),
        lambda value: replace(value, user_id="other"),
        lambda value: replace(value, snapshot_timestamp=BUCKET + timedelta(minutes=1)),
        lambda value: replace(value, granularity=SnapshotGranularity.hour),
        lambda value: replace(value, source=SnapshotSource.scheduled),
        lambda value: replace(value, calculation_version=2),
        lambda value: replace(value, output_currency="eur"),
        lambda value: replace(value, net_worth_snapshot_id=""),
        lambda value: replace(value, net_worth_disposition=cast(Any, "created")),
        lambda value: replace(value, refresh_account_count=-1),
        lambda value: replace(value, refresh_account_count=True),
        lambda value: replace(value, refresh_account_count=99),
        lambda value: replace(value, reuse_only_account_count=99),
        lambda value: replace(value, selected_account_snapshot_count=99),
        lambda value: replace(value, account_snapshots=value.account_snapshots[:-1]),
        lambda value: replace(
            value,
            required_account_snapshot_identities=(
                *value.required_account_snapshot_identities[:-1],
                SelectedAccountSnapshotIdentity("account-c", "wrong"),
            ),
        ),
        lambda value: replace(
            value,
            account_snapshots=(
                replace(
                    value.account_snapshots[0],
                    disposition=AccountSnapshotRefreshExecutionDisposition.reused,
                ),
                *value.account_snapshots[1:],
            ),
        ),
    ],
)
async def test_malformed_executor_result_maps_unavailable(mutate: Any) -> None:
    value = mutate(_executor_result())
    service, _, _, _ = _service(result=value)

    with pytest.raises(UserSnapshotRefreshUnavailableError):
        await service.recalculate(RecalculateUserSnapshotRefreshCommand(principal=_principal()))


@pytest.mark.parametrize(
    ("disposition", "status"),
    [
        (NetWorthSnapshotWriteDisposition.created, "created"),
        (NetWorthSnapshotWriteDisposition.replayed, "replayed"),
    ],
)
async def test_result_maps_only_safe_summary(
    disposition: NetWorthSnapshotWriteDisposition,
    status: str,
) -> None:
    service, _, _, _ = _service(result=_executor_result(net_worth_disposition=disposition))

    result = await service.recalculate(
        RecalculateUserSnapshotRefreshCommand(principal=_principal())
    )

    assert result.net_worth_status == status
    assert result.refresh_account_count == 2
    assert result.reuse_only_account_count == 1
    assert result.created_account_snapshot_count == 1
    assert result.replayed_account_snapshot_count == 1
    assert result.reused_account_snapshot_count == 1
    assert result.selected_account_snapshot_count == 3
    for field in (
        "user_id",
        "account_snapshots",
        "required_account_snapshot_identities",
        "account_ids",
        "lineage",
        "exchange_rates",
    ):
        assert not hasattr(result, field)


async def test_empty_user_result_is_valid() -> None:
    service, _, _, _ = _service(result=_executor_result(executions=()))
    result = await service.recalculate(
        RecalculateUserSnapshotRefreshCommand(principal=_principal())
    )

    assert result.refresh_account_count == 0
    assert result.reuse_only_account_count == 0
    assert result.selected_account_snapshot_count == 0


def test_command_and_result_are_frozen_and_slotted() -> None:
    command = RecalculateUserSnapshotRefreshCommand(principal=_principal())
    result = RecalculateUserSnapshotRefreshResult(
        net_worth_snapshot_id="net-worth-a",
        net_worth_status="created",
        timestamp=BUCKET,
        granularity=SnapshotGranularity.minute,
        currency="EUR",
        refresh_account_count=0,
        reuse_only_account_count=0,
        created_account_snapshot_count=0,
        replayed_account_snapshot_count=0,
        reused_account_snapshot_count=0,
        selected_account_snapshot_count=0,
    )
    for value, field in (
        (command, "principal"),
        (result, "currency"),
    ):
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(field, None)
        assert not hasattr(value, "__dict__")
