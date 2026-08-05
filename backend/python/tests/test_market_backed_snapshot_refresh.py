from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from inspect import getsource
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from app.config.settings import Settings
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.modules.market_data.models import (
    MarketEvidenceConflictError,
    MarketEvidenceRefreshResult,
    MarketEvidenceStateError,
)
from app.modules.net_worth.evidence_service import SelectedAccountSnapshotIdentity
from app.modules.net_worth.writer import NetWorthSnapshotWriteDisposition
from app.modules.snapshot_refresh.executor import (
    AccountSnapshotRefreshExecutionDisposition,
    ExecutedAccountSnapshotRefresh,
    ExecuteUserSnapshotRefreshResult,
    SnapshotRefreshExecutionConflictError,
    SnapshotRefreshExecutionStateError,
)
from app.modules.snapshot_refresh.market_backed_models import (
    ExecuteMarketBackedSnapshotRefreshCommand,
    ExecuteMarketBackedSnapshotRefreshResult,
    MarketBackedSnapshotRefreshConflictError,
    MarketBackedSnapshotRefreshUnavailableError,
)
from app.modules.snapshot_refresh.market_backed_service import (
    MarketBackedSnapshotRefreshService,
)
from app.modules.snapshot_refresh.plan import AccountSnapshotRefreshMode

SNAPSHOT_AT = datetime(2026, 8, 3)
CALCULATED_AT = datetime(2026, 8, 3, 0, 0, 1)
CREATED_AT = datetime(2026, 8, 3, 0, 0, 2)


class _Session:
    def __init__(self) -> None:
        self.active = False
        self.rollback = AsyncMock(side_effect=self._rollback)

    async def _rollback(self) -> None:
        self.active = False

    def in_transaction(self) -> bool:
        return self.active


class _MarketService:
    def __init__(
        self,
        calls: list[str],
        result: object,
        *,
        session: _Session,
        error: Exception | None = None,
        leave_active: bool = False,
    ) -> None:
        self.calls = calls
        self.result = result
        self.session = session
        self.error = error
        self.leave_active = leave_active
        self.commands: list[Any] = []
        self.persisted_result: object | None = None

    async def refresh(self, command: Any) -> Any:
        assert not self.session.active
        self.calls.append("market")
        self.commands.append(command)
        if self.error is not None:
            if self.leave_active:
                self.session.active = True
            raise self.error
        self.persisted_result = self.result
        if self.leave_active:
            self.session.active = True
        return self.result


class _SnapshotExecutor:
    def __init__(
        self,
        calls: list[str],
        result: object,
        *,
        session: _Session,
        error: Exception | None = None,
        leave_active: bool = False,
    ) -> None:
        self.calls = calls
        self.result = result
        self.session = session
        self.error = error
        self.leave_active = leave_active
        self.commands: list[Any] = []

    async def execute(self, command: Any) -> Any:
        assert not self.session.active
        self.calls.append("snapshot")
        self.commands.append(command)
        if self.error is not None:
            if self.leave_active:
                self.session.active = True
            raise self.error
        if self.leave_active:
            self.session.active = True
        return self.result


def _command(**changes: object) -> ExecuteMarketBackedSnapshotRefreshCommand:
    values: dict[str, object] = {
        "user_id": "user-1",
        "snapshot_timestamp": SNAPSHOT_AT,
        "granularity": SnapshotGranularity.day,
        "source": SnapshotSource.price_refresh,
        "calculation_version": 1,
        "calculated_at": CALCULATED_AT,
        "created_at": CREATED_AT,
        "is_recalculated": False,
    }
    values.update(changes)
    return ExecuteMarketBackedSnapshotRefreshCommand(**cast(Any, values))


def _market_result(
    *,
    price_ids: tuple[str, ...] = ("price-a",),
    exchange_rate_ids: tuple[str, ...] = ("rate-a",),
    required_price_count: int | None = None,
    required_fx_count: int | None = None,
    **changes: object,
) -> MarketEvidenceRefreshResult:
    values: dict[str, object] = {
        "user_id": "user-1",
        "snapshot_timestamp": SNAPSHOT_AT,
        "output_currency": "CZK",
        "required_price_count": (
            len(price_ids) if required_price_count is None else required_price_count
        ),
        "required_fx_count": (
            len(exchange_rate_ids) if required_fx_count is None else required_fx_count
        ),
        "price_ids": price_ids,
        "exchange_rate_ids": exchange_rate_ids,
        "prices_created": len(price_ids),
        "prices_replayed": 0,
        "rates_created": len(exchange_rate_ids),
        "rates_replayed": 0,
    }
    values.update(changes)
    return MarketEvidenceRefreshResult(**cast(Any, values))


def _snapshot_result(**changes: object) -> ExecuteUserSnapshotRefreshResult:
    executions = (
        ExecutedAccountSnapshotRefresh(
            account_id="account-a",
            snapshot_id="snapshot-a",
            mode=AccountSnapshotRefreshMode.refresh,
            disposition=AccountSnapshotRefreshExecutionDisposition.created,
        ),
        ExecutedAccountSnapshotRefresh(
            account_id="account-b",
            snapshot_id="snapshot-b",
            mode=AccountSnapshotRefreshMode.reuse_only,
            disposition=AccountSnapshotRefreshExecutionDisposition.reused,
        ),
    )
    identities = tuple(
        SelectedAccountSnapshotIdentity(item.account_id, item.snapshot_id) for item in executions
    )
    values: dict[str, object] = {
        "user_id": "user-1",
        "snapshot_timestamp": SNAPSHOT_AT,
        "granularity": SnapshotGranularity.day,
        "output_currency": "CZK",
        "source": SnapshotSource.price_refresh,
        "calculation_version": 1,
        "account_snapshots": executions,
        "required_account_snapshot_identities": identities,
        "net_worth_snapshot_id": "net-worth-a",
        "net_worth_disposition": NetWorthSnapshotWriteDisposition.created,
        "refresh_account_count": 1,
        "reuse_only_account_count": 1,
        "created_account_snapshot_count": 1,
        "replayed_account_snapshot_count": 0,
        "reused_account_snapshot_count": 1,
        "selected_account_snapshot_count": 2,
    }
    values.update(changes)
    return ExecuteUserSnapshotRefreshResult(**cast(Any, values))


def _service(
    *,
    market_result: object | None = None,
    snapshot_result: object | None = None,
    market_error: Exception | None = None,
    snapshot_error: Exception | None = None,
    market_leave_active: bool = False,
    snapshot_leave_active: bool = False,
) -> tuple[
    MarketBackedSnapshotRefreshService,
    _Session,
    _MarketService,
    _SnapshotExecutor,
    list[str],
]:
    calls: list[str] = []
    session = _Session()
    market = _MarketService(
        calls,
        market_result if market_result is not None else _market_result(),
        session=session,
        error=market_error,
        leave_active=market_leave_active,
    )
    snapshots = _SnapshotExecutor(
        calls,
        snapshot_result if snapshot_result is not None else _snapshot_result(),
        session=session,
        error=snapshot_error,
        leave_active=snapshot_leave_active,
    )
    service = MarketBackedSnapshotRefreshService(
        cast(Any, session),
        Settings(environment="test", _env_file=None),
        market_service=market,
        snapshot_executor=snapshots,
    )
    return service, session, market, snapshots, calls


@pytest.mark.asyncio
async def test_market_runs_before_snapshot_and_projections_are_exact() -> None:
    service, _, market, snapshots, calls = _service()
    command = _command()

    result = await service.execute(command)

    assert calls == ["market", "snapshot"]
    assert market.commands[0].user_id == snapshots.commands[0].user_id == command.user_id
    assert (
        market.commands[0].snapshot_timestamp
        is snapshots.commands[0].snapshot_timestamp
        is command.snapshot_timestamp
    )
    assert market.commands[0].created_at is command.created_at
    snapshot_command = snapshots.commands[0]
    for field in (
        "user_id",
        "snapshot_timestamp",
        "granularity",
        "source",
        "calculation_version",
        "calculated_at",
        "created_at",
        "is_recalculated",
    ):
        assert getattr(snapshot_command, field) is getattr(command, field)
    assert result.market is market.result
    assert result.snapshots is snapshots.result


@pytest.mark.asyncio
async def test_market_failure_never_calls_or_constructs_snapshot_executor() -> None:
    calls: list[str] = []
    session = _Session()
    error = MarketEvidenceStateError()
    market = _MarketService(calls, _market_result(), session=session, error=error)
    executor_factory_calls = 0

    def executor_factory(_: object) -> _SnapshotExecutor:
        nonlocal executor_factory_calls
        executor_factory_calls += 1
        return _SnapshotExecutor(calls, _snapshot_result(), session=session)

    service = MarketBackedSnapshotRefreshService(
        cast(Any, session),
        Settings(environment="test", _env_file=None),
        market_service=market,
        executor_factory=cast(Any, executor_factory),
    )
    with pytest.raises(MarketBackedSnapshotRefreshUnavailableError) as caught:
        await service.execute(_command())

    assert caught.value.__cause__ is error
    assert calls == ["market"]
    assert executor_factory_calls == 0


@pytest.mark.parametrize(
    "market_result",
    [
        _market_result(price_ids=(), exchange_rate_ids=()),
        _market_result(price_ids=("coingecko-price",), exchange_rate_ids=()),
        _market_result(price_ids=("twelve-data-price",), exchange_rate_ids=()),
        _market_result(price_ids=(), exchange_rate_ids=("cnb-rate",)),
        _market_result(
            price_ids=("coingecko-price", "twelve-data-price"),
            exchange_rate_ids=("cnb-eur", "cnb-usd"),
        ),
    ],
    ids=["empty", "coingecko-only", "twelve-data-only", "cnb-only", "mixed"],
)
@pytest.mark.asyncio
async def test_valid_market_shapes_continue_to_snapshot(
    market_result: MarketEvidenceRefreshResult,
) -> None:
    service, _, _, snapshots, _ = _service(market_result=market_result)

    result = await service.execute(_command())

    assert result.market is market_result
    assert len(snapshots.commands) == 1


@pytest.mark.parametrize(
    "market_result",
    [
        _market_result(user_id="other"),
        _market_result(snapshot_timestamp=SNAPSHOT_AT.replace(day=2)),
        _market_result(price_ids=("duplicate", "duplicate"), required_price_count=2),
        _market_result(
            exchange_rate_ids=("duplicate", "duplicate"),
            required_fx_count=2,
        ),
        _market_result(prices_created=0, prices_replayed=0),
        _market_result(rates_created=0, rates_replayed=0),
        _market_result(price_ids=("z", "a"), required_price_count=2),
        _market_result(required_price_count=-1),
        _market_result(prices_created=True),
    ],
)
@pytest.mark.asyncio
async def test_invalid_market_result_stops_before_snapshot(
    market_result: MarketEvidenceRefreshResult,
) -> None:
    service, _, _, snapshots, _ = _service(market_result=market_result)

    with pytest.raises(MarketBackedSnapshotRefreshUnavailableError):
        await service.execute(_command())

    assert snapshots.commands == []


@pytest.mark.asyncio
async def test_positive_price_requirement_requires_physical_identity() -> None:
    market_result = _market_result(
        price_ids=(),
        exchange_rate_ids=(),
        required_price_count=1,
        required_fx_count=0,
        prices_created=0,
        prices_replayed=0,
    )
    service, _, _, snapshots, _ = _service(market_result=market_result)

    with pytest.raises(MarketBackedSnapshotRefreshUnavailableError):
        await service.execute(_command())

    assert snapshots.commands == []


@pytest.mark.asyncio
async def test_positive_fx_requirement_requires_physical_identity() -> None:
    market_result = _market_result(
        price_ids=(),
        exchange_rate_ids=(),
        required_price_count=0,
        required_fx_count=1,
        rates_created=0,
        rates_replayed=0,
    )
    service, _, _, snapshots, _ = _service(market_result=market_result)

    with pytest.raises(MarketBackedSnapshotRefreshUnavailableError):
        await service.execute(_command())

    assert snapshots.commands == []


@pytest.mark.asyncio
async def test_multiple_price_requirements_may_coalesce_to_one_identity() -> None:
    market_result = _market_result(
        price_ids=("price-a",),
        exchange_rate_ids=(),
        required_price_count=2,
        required_fx_count=0,
        prices_created=1,
        prices_replayed=0,
    )
    service, _, _, snapshots, _ = _service(market_result=market_result)

    result = await service.execute(_command())

    assert result.market is market_result
    assert len(snapshots.commands) == 1


@pytest.mark.asyncio
async def test_multiple_fx_requirements_may_coalesce_to_one_identity() -> None:
    market_result = _market_result(
        price_ids=(),
        exchange_rate_ids=("rate-a",),
        required_price_count=0,
        required_fx_count=2,
        rates_created=1,
        rates_replayed=0,
    )
    service, _, _, snapshots, _ = _service(market_result=market_result)

    result = await service.execute(_command())

    assert result.market is market_result
    assert len(snapshots.commands) == 1


@pytest.mark.parametrize(
    "snapshot_result",
    [
        _snapshot_result(user_id="other"),
        _snapshot_result(snapshot_timestamp=SNAPSHOT_AT.replace(day=2)),
        _snapshot_result(output_currency="EUR"),
        _snapshot_result(refresh_account_count=2),
        _snapshot_result(created_account_snapshot_count=0),
        _snapshot_result(reused_account_snapshot_count=0),
        _snapshot_result(selected_account_snapshot_count=1),
        _snapshot_result(
            required_account_snapshot_identities=(
                SelectedAccountSnapshotIdentity("account-a", "snapshot-a"),
            )
        ),
        _snapshot_result(
            required_account_snapshot_identities=(
                SelectedAccountSnapshotIdentity("account-a", "snapshot-a"),
                SelectedAccountSnapshotIdentity("account-b", "snapshot-a"),
            )
        ),
        _snapshot_result(account_snapshots=tuple(reversed(_snapshot_result().account_snapshots))),
    ],
)
@pytest.mark.asyncio
async def test_invalid_snapshot_result_fails_combined_validation(
    snapshot_result: ExecuteUserSnapshotRefreshResult,
) -> None:
    service, _, _, _, _ = _service(snapshot_result=snapshot_result)

    with pytest.raises(MarketBackedSnapshotRefreshUnavailableError):
        await service.execute(_command())


@pytest.mark.parametrize(
    "value",
    [
        cast(Any, object()),
        _command(user_id=""),
        _command(user_id=" user"),
        _command(snapshot_timestamp=SNAPSHOT_AT.replace(tzinfo=UTC)),
        _command(snapshot_timestamp=SNAPSHOT_AT.replace(microsecond=1)),
        _command(snapshot_timestamp=SNAPSHOT_AT.replace(hour=1)),
        _command(granularity=cast(Any, "day")),
        _command(source=cast(Any, "price_refresh")),
        _command(calculation_version=0),
        _command(calculation_version=True),
        _command(calculation_version=2_147_483_648),
        _command(calculated_at=CALCULATED_AT.replace(tzinfo=UTC)),
        _command(created_at=CREATED_AT.replace(microsecond=1)),
        _command(is_recalculated=cast(Any, 0)),
        _command(is_recalculated=True),
    ],
)
@pytest.mark.asyncio
async def test_invalid_command_fails_before_dependency_io(value: object) -> None:
    service, _, market, snapshots, calls = _service()

    with pytest.raises(MarketBackedSnapshotRefreshUnavailableError):
        await service.execute(cast(Any, value))

    assert calls == []
    assert market.commands == []
    assert snapshots.commands == []


@pytest.mark.parametrize(
    ("market_error", "snapshot_error", "expected"),
    [
        (
            MarketEvidenceConflictError(),
            None,
            MarketBackedSnapshotRefreshConflictError,
        ),
        (
            None,
            SnapshotRefreshExecutionConflictError(),
            MarketBackedSnapshotRefreshConflictError,
        ),
        (
            MarketEvidenceStateError(),
            None,
            MarketBackedSnapshotRefreshUnavailableError,
        ),
        (
            None,
            SnapshotRefreshExecutionStateError(),
            MarketBackedSnapshotRefreshUnavailableError,
        ),
    ],
)
@pytest.mark.asyncio
async def test_known_dependency_errors_map_with_cause(
    market_error: Exception | None,
    snapshot_error: Exception | None,
    expected: type[Exception],
) -> None:
    service, _, _, snapshots, _ = _service(
        market_error=market_error,
        snapshot_error=snapshot_error,
    )
    source = market_error or snapshot_error

    with pytest.raises(expected) as caught:
        await service.execute(_command())

    assert caught.value.__cause__ is source
    assert len(snapshots.commands) == (0 if market_error is not None else 1)


@pytest.mark.asyncio
async def test_unexpected_dependency_error_propagates_unchanged() -> None:
    error = RuntimeError("controlled programming error")
    service, _, _, _, _ = _service(snapshot_error=error)

    with pytest.raises(RuntimeError) as caught:
        await service.execute(_command())

    assert caught.value is error


@pytest.mark.asyncio
async def test_dependency_transaction_leaks_are_rolled_back_and_stop_flow() -> None:
    service, session, _, snapshots, _ = _service(market_leave_active=True)
    with pytest.raises(RuntimeError, match="market dependency left an active transaction"):
        await service.execute(_command())
    session.rollback.assert_awaited_once()
    assert snapshots.commands == []

    service, session, _, _, _ = _service(snapshot_leave_active=True)
    with pytest.raises(RuntimeError, match="snapshot dependency left an active transaction"):
        await service.execute(_command())
    session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_snapshot_failure_does_not_compensate_committed_market_result() -> None:
    service, _, market, snapshots, calls = _service(
        snapshot_error=SnapshotRefreshExecutionStateError()
    )

    with pytest.raises(MarketBackedSnapshotRefreshUnavailableError):
        await service.execute(_command())

    assert calls == ["market", "snapshot"]
    assert market.persisted_result is market.result
    assert len(snapshots.commands) == 1
    assert not hasattr(service, "delete_market_evidence")
    assert not hasattr(service, "compensate")


@pytest.mark.asyncio
async def test_injected_factories_are_independent_and_lazy() -> None:
    calls: list[str] = []
    session = _Session()
    factory_calls: list[str] = []

    def market_factory(session_arg: object, settings_arg: object) -> _MarketService:
        assert session_arg is session
        assert isinstance(settings_arg, Settings)
        factory_calls.append("market factory")
        return _MarketService(calls, _market_result(), session=session)

    def executor_factory(session_arg: object) -> _SnapshotExecutor:
        assert session_arg is session
        factory_calls.append("snapshot factory")
        return _SnapshotExecutor(calls, _snapshot_result(), session=session)

    service = MarketBackedSnapshotRefreshService(
        cast(Any, session),
        Settings(environment="test", _env_file=None),
        market_service_factory=cast(Any, market_factory),
        executor_factory=cast(Any, executor_factory),
    )
    await service.execute(_command())

    assert factory_calls == ["market factory", "snapshot factory"]
    assert calls == ["market", "snapshot"]


def test_contracts_are_frozen_and_errors_are_generic() -> None:
    command = _command()
    result = ExecuteMarketBackedSnapshotRefreshResult(
        market=_market_result(),
        snapshots=_snapshot_result(),
    )
    for value, field in ((command, "user_id"), (result, "market")):
        with pytest.raises(FrozenInstanceError):
            value.__setattr__(field, "changed")
        assert not hasattr(value, "__dict__")
    assert str(MarketBackedSnapshotRefreshUnavailableError()) == (
        "Market-backed snapshot refresh could not be completed."
    )
    assert str(MarketBackedSnapshotRefreshConflictError()) == (
        "Market-backed snapshot refresh conflicts with persisted state."
    )


def test_service_has_no_clock_retry_cache_or_background_task_creation() -> None:
    source = getsource(MarketBackedSnapshotRefreshService)
    for forbidden in (
        "datetime.now",
        "datetime.utcnow",
        "create_task",
        "sleep(",
        "retry",
        "cache",
    ):
        assert forbidden not in source
