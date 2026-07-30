from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from itertools import permutations
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.modules.accounts.access import AccountNotFoundError
from app.modules.dashboard_snapshot.authorized_service import (
    AuthorizedDashboardSnapshotService,
    ReadAuthorizedDashboardSnapshotResult,
)
from app.modules.dashboard_snapshot.models import DashboardSnapshotView
from app.modules.dashboard_snapshot.projection import DashboardSnapshotProjectionError
from app.modules.portfolio_snapshot.aggregate_models import MultiAccountPortfolioView
from app.modules.portfolio_snapshot.aggregation import (
    MultiAccountPortfolioProjectionError,
    build_multi_account_portfolio_view,
)
from app.modules.portfolio_snapshot.authorized_reader import (
    PortfolioSnapshotUnavailableError,
    ReadAuthorizedPortfolioSnapshotCommand,
    ReadAuthorizedPortfolioSnapshotResult,
)
from app.modules.portfolio_snapshot.models import (
    AccountType,
    AssetType,
    PortfolioAccountView,
    PortfolioPositionView,
    PortfolioSnapshotView,
    PortfolioSummaryView,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.portfolio_snapshot.multi_account_service import (
    AuthorizedMultiAccountPortfolioSnapshotService,
    ExactAccountSnapshotSelection,
    ReadAuthorizedMultiAccountPortfolioSnapshotCommand,
    ReadAuthorizedMultiAccountPortfolioSnapshotResult,
)

SNAPSHOT_AT = datetime(2032, 8, 2)
MODULE_DIR = Path(__file__).parents[1] / "app" / "modules"


def _principal(user_id: str = "user-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=user_id, email="user@example.com", name="User")


def _position(account_id: str, value: str, cost: str) -> PortfolioPositionView:
    value_decimal = Decimal(value).quantize(Decimal("0.000001"))
    cost_decimal = Decimal(cost).quantize(Decimal("0.0000000001"))
    return PortfolioPositionView(
        listing_id=f"{account_id}-listing",
        asset_id=f"{account_id}-asset",
        symbol=account_id.upper(),
        name=f"{account_id} asset",
        asset_type=AssetType.stock,
        quantity=Decimal("1.0000000000"),
        price_per_unit=Decimal(value).quantize(Decimal("0.0000000001")),
        price_currency="USD",
        price_timestamp=SNAPSHOT_AT,
        value=value_decimal,
        value_currency="EUR",
        cost_basis=cost_decimal,
        cost_currency="EUR",
        unrealized_pnl=value_decimal - cost_decimal,
        allocation_pct=Decimal("100.0000"),
        native_value=Decimal(value).quantize(Decimal("0.0000000001")),
        native_value_currency="USD",
        native_cost_basis=cost_decimal,
        native_cost_currency="USD",
    )


def _view(
    account_id: str,
    *,
    value: str = "100",
    cost: str = "80",
    account_type: AccountType = AccountType.broker,
) -> PortfolioSnapshotView:
    liability = account_type in {
        AccountType.credit_card,
        AccountType.loan,
        AccountType.mortgage,
    }
    positions = () if liability else (_position(account_id, value, cost),)
    investment = Decimal("0.000000") if liability else Decimal(value).quantize(Decimal("0.000001"))
    investment_cost = (
        Decimal("0.000000") if liability else Decimal(cost).quantize(Decimal("0.000001"))
    )
    liabilities = Decimal("25.000000") if liability else Decimal("0.000000")
    return PortfolioSnapshotView(
        snapshot_id=f"{account_id}-snapshot",
        account=PortfolioAccountView(
            account_id=account_id,
            name=f"{account_id} name",
            account_type=account_type,
            currency="CZK" if account_id == "account-a" else "USD",
        ),
        timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        currency="EUR",
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        summary=PortfolioSummaryView(
            cash_value=Decimal("0.000000"),
            investment_value=investment,
            investment_cost_basis=investment_cost,
            liabilities_value=liabilities,
            total_value=investment - liabilities,
            net_deposits_value=Decimal("0.000000"),
            realized_pnl_value=Decimal("0.000000"),
            unrealized_pnl_value=investment - investment_cost,
            fees_value=Decimal("0.000000"),
            taxes_value=Decimal("0.000000"),
            position_count=len(positions),
        ),
        positions=positions,
    )


def _command(
    accounts: tuple[ExactAccountSnapshotSelection, ...] | None = None,
    **changes: object,
) -> ReadAuthorizedMultiAccountPortfolioSnapshotCommand:
    values: dict[str, object] = {
        "principal": _principal(),
        "timestamp": SNAPSHOT_AT,
        "granularity": SnapshotGranularity.day,
        "currency": "EUR",
        "calculation_version": 1,
        "accounts": (
            (
                ExactAccountSnapshotSelection("account-a"),
                ExactAccountSnapshotSelection("account-b"),
            )
            if accounts is None
            else accounts
        ),
    }
    values.update(changes)
    return ReadAuthorizedMultiAccountPortfolioSnapshotCommand(**values)  # type: ignore[arg-type]


class _Transaction:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> _Transaction:
        assert self.session.active is False
        self.session.active = True
        self.session.transaction_id += 1
        self.session.events.append("begin")
        return self

    async def __aexit__(self, *args: object) -> None:
        self.session.events.append("rollback-read" if args[0] else "commit-read")
        if not self.session.leave_active:
            self.session.active = False


class _Session:
    def __init__(self, *, active: bool = True, leave_active: bool = False) -> None:
        self.active = active
        self.leave_active = leave_active
        self.events: list[str] = []
        self.transaction_id = 0
        self.commit_count = 0
        self.rollback_count = 0

    def in_transaction(self) -> bool:
        return self.active

    async def commit(self) -> None:
        self.events.append("commit-auth")
        self.commit_count += 1
        self.active = False

    async def rollback(self) -> None:
        self.events.append("rollback-session")
        self.rollback_count += 1
        self.active = False

    def begin(self) -> _Transaction:
        return _Transaction(self)

    async def execute(self, statement: object) -> object:
        assert self.active
        self.events.append(str(statement))
        return object()


class _AuthorizedReader:
    def __init__(
        self,
        session: _Session,
        views: dict[str, PortfolioSnapshotView],
        *,
        failure_at: str | None = None,
        failure: BaseException | None = None,
    ) -> None:
        self.session = session
        self.views = views
        self.failure_at = failure_at
        self.failure = failure
        self.calls: list[ReadAuthorizedPortfolioSnapshotCommand] = []
        self.transaction_ids: list[int] = []

    async def read(
        self,
        command: object,
    ) -> ReadAuthorizedPortfolioSnapshotResult:
        assert self.session.active
        assert type(command) is ReadAuthorizedPortfolioSnapshotCommand
        self.session.events.append(f"read:{command.account_id}")
        self.calls.append(command)
        self.transaction_ids.append(self.session.transaction_id)
        if command.account_id == self.failure_at and self.failure is not None:
            raise self.failure
        return ReadAuthorizedPortfolioSnapshotResult(view=self.views[command.account_id])


def _service(
    *,
    views: dict[str, PortfolioSnapshotView] | None = None,
    failure_at: str | None = None,
    failure: BaseException | None = None,
    aggregate_error: BaseException | None = None,
    leave_active: bool = False,
) -> tuple[
    AuthorizedMultiAccountPortfolioSnapshotService,
    _Session,
    _AuthorizedReader,
    list[int],
    list[tuple[PortfolioSnapshotView, ...]],
]:
    session = _Session(leave_active=leave_active)
    available = views or {
        "account-a": _view("account-a", value="60", cost="50"),
        "account-b": _view("account-b", value="40", cost="30"),
        "liability": _view("liability", account_type=AccountType.loan),
    }
    reader = _AuthorizedReader(
        session,
        available,
        failure_at=failure_at,
        failure=failure,
    )
    factory_calls: list[int] = []
    aggregate_calls: list[tuple[PortfolioSnapshotView, ...]] = []

    def factory(_session: AsyncSession) -> _AuthorizedReader:
        factory_calls.append(session.transaction_id)
        return reader

    def aggregate(values: tuple[PortfolioSnapshotView, ...]) -> MultiAccountPortfolioView:
        aggregate_calls.append(values)
        if aggregate_error is not None:
            raise aggregate_error
        return build_multi_account_portfolio_view(values)

    service = AuthorizedMultiAccountPortfolioSnapshotService(
        cast(AsyncSession, session),
        authorized_reader_factory=factory,
        aggregate_builder=aggregate,
    )
    return service, session, reader, factory_calls, aggregate_calls


@pytest.mark.asyncio
async def test_one_account_exact_snapshot_set() -> None:
    service, session, reader, factory_calls, aggregate_calls = _service()

    result = await service.read(_command((ExactAccountSnapshotSelection("account-a"),)))

    assert result.portfolio.summary.account_count == 1
    assert result.portfolio.summary.investment_value == Decimal("60.000000")
    assert len(reader.calls) == len(aggregate_calls) == len(factory_calls) == 1
    assert session.in_transaction() is False


@pytest.mark.asyncio
async def test_two_investment_accounts_use_one_reader_and_one_aggregate_call() -> None:
    service, session, reader, factory_calls, aggregate_calls = _service()

    result = await service.read(_command())

    assert result.portfolio.summary.investment_value == Decimal("100.000000")
    assert result.portfolio.summary.account_count == 2
    assert len(factory_calls) == 1
    assert len(reader.calls) == 2
    assert len(aggregate_calls) == 1
    assert reader.transaction_ids == [1, 1]
    assert session.events == [
        "commit-auth",
        "begin",
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
        "read:account-a",
        "read:account-b",
        "commit-read",
    ]


@pytest.mark.asyncio
async def test_investment_and_liability_accounts_are_all_returned() -> None:
    service, _, _, _, _ = _service()

    result = await service.read(
        _command(
            (
                ExactAccountSnapshotSelection("account-a"),
                ExactAccountSnapshotSelection("liability"),
            )
        )
    )

    assert result.portfolio.summary.account_count == 2
    assert result.portfolio.summary.liabilities_value == Decimal("25.000000")
    assert {account.account.account_id for account in result.portfolio.accounts} == {
        "account-a",
        "liability",
    }


@pytest.mark.asyncio
async def test_selectors_are_read_in_canonical_order_with_optional_guards() -> None:
    service, _, reader, _, _ = _service()
    command = _command(
        (
            ExactAccountSnapshotSelection("account-b", "account-b-snapshot"),
            ExactAccountSnapshotSelection("account-a", "account-a-snapshot"),
        )
    )

    await service.read(command)

    assert [(call.account_id, call.required_snapshot_id) for call in reader.calls] == [
        ("account-a", "account-a-snapshot"),
        ("account-b", "account-b-snapshot"),
    ]
    assert all(
        (
            call.timestamp,
            call.granularity,
            call.currency,
            call.calculation_version,
        )
        == (SNAPSHOT_AT, SnapshotGranularity.day, "EUR", 1)
        for call in reader.calls
    )


@pytest.mark.asyncio
async def test_every_selector_permutation_returns_identical_result() -> None:
    selectors = (
        ExactAccountSnapshotSelection("account-a"),
        ExactAccountSnapshotSelection("account-b"),
        ExactAccountSnapshotSelection("liability"),
    )
    results: list[MultiAccountPortfolioView] = []
    for permutation in permutations(selectors):
        service, _, _, _, _ = _service()
        results.append((await service.read(_command(permutation))).portfolio)

    assert all(result == results[0] for result in results)


@pytest.mark.asyncio
async def test_auth_transaction_is_closed_before_first_isolation_statement() -> None:
    service, session, _, _, _ = _service()

    await service.read(_command())

    assert session.commit_count == 1
    assert session.events[:3] == [
        "commit-auth",
        "begin",
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
    ]
    assert session.in_transaction() is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        object(),
        _command(accounts=cast(Any, [])),
        _command(accounts=()),
        _command(
            (
                ExactAccountSnapshotSelection("account-a"),
                ExactAccountSnapshotSelection("account-a"),
            )
        ),
        _command(
            (
                ExactAccountSnapshotSelection("account-a", "same"),
                ExactAccountSnapshotSelection("account-b", "same"),
            )
        ),
        _command((ExactAccountSnapshotSelection(""),)),
        _command((ExactAccountSnapshotSelection(" account-a"),)),
        _command((ExactAccountSnapshotSelection("account-a", ""),)),
        _command(currency="eur"),
        _command(timestamp=SNAPSHOT_AT.replace(tzinfo=UTC)),
        _command(timestamp=SNAPSHOT_AT.replace(hour=1)),
        _command(calculation_version=0),
        _command(calculation_version=True),
        _command(principal=object()),
    ],
)
async def test_invalid_command_closes_auth_transaction_without_financial_query(
    value: object,
) -> None:
    service, session, reader, factory_calls, aggregate_calls = _service()

    with pytest.raises(PortfolioSnapshotUnavailableError):
        await service.read(value)

    assert session.rollback_count == 1
    assert session.events == ["rollback-session"]
    assert reader.calls == []
    assert factory_calls == []
    assert aggregate_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failed_account", ["account-a", "account-b", "liability"])
async def test_any_account_failure_returns_no_partial_result(failed_account: str) -> None:
    service, session, reader, _, aggregate_calls = _service(
        failure_at=failed_account,
        failure=AccountNotFoundError(),
    )
    selectors = (
        ExactAccountSnapshotSelection("account-a"),
        ExactAccountSnapshotSelection("account-b"),
        ExactAccountSnapshotSelection("liability"),
    )

    with pytest.raises(AccountNotFoundError):
        await service.read(_command(selectors))

    assert failed_account in {call.account_id for call in reader.calls}
    assert aggregate_calls == []
    assert session.in_transaction() is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [PortfolioSnapshotUnavailableError(), SQLAlchemyError("read")],
)
async def test_reader_failures_map_to_generic_unavailable(failure: BaseException) -> None:
    service, session, _, _, aggregate_calls = _service(
        failure_at="account-b",
        failure=failure,
    )

    with pytest.raises(PortfolioSnapshotUnavailableError) as caught:
        await service.read(_command())

    assert caught.value.message == "The requested portfolio snapshot is unavailable."
    assert "account-b" not in caught.value.message
    assert aggregate_calls == []
    assert session.in_transaction() is False


@pytest.mark.asyncio
async def test_aggregate_projection_failure_maps_to_generic_unavailable() -> None:
    service, _, _, _, aggregate_calls = _service(
        aggregate_error=MultiAccountPortfolioProjectionError()
    )

    with pytest.raises(PortfolioSnapshotUnavailableError):
        await service.read(_command())

    assert len(aggregate_calls) == 1


@pytest.mark.asyncio
async def test_service_fails_if_session_is_not_idle_after_read() -> None:
    service, session, _, _, _ = _service(leave_active=True)

    with pytest.raises(RuntimeError):
        await service.read(_command())

    assert session.rollback_count == 1
    assert session.in_transaction() is False


def test_multi_account_command_and_result_are_frozen() -> None:
    command = _command()
    portfolio = build_multi_account_portfolio_view((_view("account-a", value="60", cost="50"),))
    result = ReadAuthorizedMultiAccountPortfolioSnapshotResult(portfolio=portfolio)

    with pytest.raises(FrozenInstanceError):
        command.currency = "USD"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.portfolio = portfolio  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        command.accounts[0].account_id = "changed"  # type: ignore[misc]


class _PortfolioService:
    def __init__(
        self,
        result: object,
    ) -> None:
        self.result = result
        self.calls: list[object] = []

    async def read(self, command: object) -> ReadAuthorizedMultiAccountPortfolioSnapshotResult:
        self.calls.append(command)
        if isinstance(self.result, BaseException):
            raise self.result
        return cast(ReadAuthorizedMultiAccountPortfolioSnapshotResult, self.result)


@pytest.mark.asyncio
async def test_dashboard_service_composes_portfolio_and_projection_once() -> None:
    portfolio = build_multi_account_portfolio_view(
        (
            _view("account-a", value="60", cost="50"),
            _view("account-b", value="40", cost="30"),
        )
    )
    portfolio_service = _PortfolioService(
        ReadAuthorizedMultiAccountPortfolioSnapshotResult(portfolio=portfolio)
    )
    projected: list[MultiAccountPortfolioView] = []

    def projector(value: MultiAccountPortfolioView) -> DashboardSnapshotView:
        projected.append(value)
        from app.modules.dashboard_snapshot.projection import build_dashboard_snapshot_view

        return build_dashboard_snapshot_view(value)

    service = AuthorizedDashboardSnapshotService(
        portfolio_service,
        dashboard_builder=projector,
    )
    command = _command()

    result = await service.read(command)

    assert portfolio_service.calls == [command]
    assert projected == [portfolio]
    assert type(result) is ReadAuthorizedDashboardSnapshotResult
    assert result.dashboard.summary.investment_value == Decimal("100.000000")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [AccountNotFoundError(), PortfolioSnapshotUnavailableError()],
)
async def test_dashboard_service_preserves_portfolio_errors(failure: BaseException) -> None:
    service = AuthorizedDashboardSnapshotService(_PortfolioService(failure))

    with pytest.raises(type(failure)) as caught:
        await service.read(_command())

    assert caught.value is failure


@pytest.mark.asyncio
async def test_dashboard_projection_failure_maps_to_unavailable() -> None:
    portfolio = build_multi_account_portfolio_view((_view("account-a"),))
    service = AuthorizedDashboardSnapshotService(
        _PortfolioService(ReadAuthorizedMultiAccountPortfolioSnapshotResult(portfolio=portfolio)),
        dashboard_builder=lambda _value: (_ for _ in ()).throw(DashboardSnapshotProjectionError()),
    )

    with pytest.raises(PortfolioSnapshotUnavailableError):
        await service.read(_command((ExactAccountSnapshotSelection("account-a"),)))


def test_services_have_no_financial_recalculation_or_forbidden_read_dependency() -> None:
    for path in (
        MODULE_DIR / "portfolio_snapshot" / "multi_account_service.py",
        MODULE_DIR / "dashboard_snapshot" / "authorized_service.py",
    ):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert {
            "HoldingModel",
            "PriceSnapshotModel",
            "ExchangeRateModel",
            "PortfolioSnapshotReader",
        }.isdisjoint(imports)
        for forbidden in (
            "asyncio.gather",
            "datetime.now",
            "float(",
            "round(",
            "latest",
            "fallback",
            "FOR UPDATE",
            "advisory",
            "INSERT",
            "UPDATE",
            "DELETE",
        ):
            assert forbidden not in source
