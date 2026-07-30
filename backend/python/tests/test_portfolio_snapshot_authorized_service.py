from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import AccountMemberRole, AccountRelationType
from app.modules.accounts.access import (
    AccountAccessDeniedError,
    AccountNotFoundError,
    AuthorizedAccount,
)
from app.modules.portfolio_snapshot.authorized_service import (
    AuthorizedPortfolioSnapshotService,
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
from app.modules.portfolio_snapshot.reader import (
    CompletePortfolioSnapshotRead,
    PortfolioSnapshotReadError,
    ReadExactPortfolioSnapshotCommand,
)

SNAPSHOT_AT = datetime(2032, 8, 2)


def _principal(user_id: str = "user-1") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email="user@example.com",
        name="User",
    )


def _position(listing_id: str = "listing-1") -> PortfolioPositionView:
    return PortfolioPositionView(
        listing_id=listing_id,
        asset_id="asset-1",
        symbol="AAA",
        name="Asset",
        asset_type=AssetType.stock,
        quantity=Decimal("2.0000000000"),
        price_per_unit=Decimal("50.0000000000"),
        price_currency="USD",
        price_timestamp=SNAPSHOT_AT,
        value=Decimal("100.000000"),
        value_currency="EUR",
        cost_basis=Decimal("80.0000000000"),
        cost_currency="EUR",
        unrealized_pnl=Decimal("20.0000000000"),
        allocation_pct=Decimal("100.0000"),
        native_value=Decimal("100.0000000000"),
        native_value_currency="USD",
        native_cost_basis=Decimal("80.0000000000"),
        native_cost_currency="USD",
    )


def _view(
    *,
    snapshot_id: str = "snapshot-1",
    account_id: str = "account-1",
    positions: tuple[PortfolioPositionView, ...] = (),
) -> PortfolioSnapshotView:
    investment = Decimal("100.000000") if positions else Decimal("0.000000")
    cost = Decimal("80.000000") if positions else Decimal("0.000000")
    return PortfolioSnapshotView(
        snapshot_id=snapshot_id,
        account=PortfolioAccountView(
            account_id=account_id,
            name="Broker",
            account_type=AccountType.broker,
            currency="EUR",
        ),
        timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        currency="EUR",
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        summary=PortfolioSummaryView(
            cash_value=Decimal("0.000000"),
            investment_value=investment,
            investment_cost_basis=cost,
            liabilities_value=Decimal("0.000000"),
            total_value=investment,
            net_deposits_value=Decimal("0.000000"),
            realized_pnl_value=Decimal("0.000000"),
            unrealized_pnl_value=investment - cost,
            fees_value=Decimal("0.000000"),
            taxes_value=Decimal("0.000000"),
            position_count=len(positions),
        ),
        positions=positions,
    )


def _read(
    *,
    view: PortfolioSnapshotView | None = None,
    selected_snapshot_id: str = "snapshot-1",
    selected_item_ids: tuple[str, ...] = (),
) -> CompletePortfolioSnapshotRead:
    return CompletePortfolioSnapshotRead(
        view=view or _view(),
        selected_snapshot_id=selected_snapshot_id,
        selected_item_ids=selected_item_ids,
    )


def _command(**changes: object) -> ReadAuthorizedPortfolioSnapshotCommand:
    values: dict[str, object] = {
        "principal": _principal(),
        "account_id": "account-1",
        "timestamp": SNAPSHOT_AT,
        "granularity": SnapshotGranularity.day,
        "currency": "EUR",
        "calculation_version": 1,
        "required_snapshot_id": None,
    }
    values.update(changes)
    return ReadAuthorizedPortfolioSnapshotCommand(**values)  # type: ignore[arg-type]


class _Transaction:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> _Transaction:
        assert not self.session.active
        self.session.active = True
        self.session.transaction_token += 1
        self.session.events.append("begin")
        return self

    async def __aexit__(self, *args: object) -> None:
        self.session.events.append("rollback" if args[0] is not None else "commit-read")
        self.session.active = False


class _Session:
    def __init__(self, *, active: bool = True) -> None:
        self.active = active
        self.events: list[str] = []
        self.transaction_token = 0
        self.rollback_count = 0
        self.commit_count = 0

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


class _Reader:
    def __init__(
        self,
        session: _Session,
        result: object,
        events: list[str],
    ) -> None:
        self.session = session
        self.result = result
        self.events = events
        self.calls: list[ReadExactPortfolioSnapshotCommand] = []
        self.transaction_tokens: list[int] = []

    async def read(
        self,
        command: ReadExactPortfolioSnapshotCommand,
    ) -> CompletePortfolioSnapshotRead:
        assert self.session.active
        self.events.append("reader")
        self.calls.append(command)
        self.transaction_tokens.append(self.session.transaction_token)
        if isinstance(self.result, BaseException):
            raise self.result
        return cast(CompletePortfolioSnapshotRead, self.result)


def _service(
    *,
    result: object | None = None,
    role: AccountMemberRole = AccountMemberRole.owner,
    access_error: BaseException | None = None,
) -> tuple[
    AuthorizedPortfolioSnapshotService,
    _Session,
    _Reader,
    list[dict[str, Any]],
]:
    session = _Session()
    reader = _Reader(session, result or _read(), session.events)
    access_calls: list[dict[str, Any]] = []

    async def access(**kwargs: Any) -> AuthorizedAccount:
        assert session.active
        session.events.append("access")
        access_calls.append(kwargs)
        if access_error is not None:
            raise access_error
        return AuthorizedAccount(
            account_id=kwargs["account_id"],
            role=role,
            relation_type=AccountRelationType.owner,
        )

    service = AuthorizedPortfolioSnapshotService(
        cast(AsyncSession, session),
        reader_factory=lambda value: reader,
        access_checker=access,
    )
    return service, session, reader, access_calls


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    [
        AccountMemberRole.owner,
        AccountMemberRole.admin,
        AccountMemberRole.editor,
        AccountMemberRole.viewer,
    ],
)
async def test_all_current_read_roles_can_read_exact_portfolio_snapshot(
    role: AccountMemberRole,
) -> None:
    service, session, reader, access_calls = _service(role=role)

    result = await service.read(_command())

    assert result == ReadAuthorizedPortfolioSnapshotResult(view=_view())
    assert role in access_calls[0]["allowed_roles"]
    assert access_calls[0]["include_archived"] is False
    assert access_calls[0]["for_update"] is False
    assert reader.calls
    assert session.in_transaction() is False


@pytest.mark.asyncio
async def test_authorization_runs_before_reader_in_same_transaction() -> None:
    service, session, reader, _ = _service()

    await service.read(_command())

    assert session.events == [
        "commit-auth",
        "begin",
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ",
        "access",
        "reader",
        "commit-read",
    ]
    assert reader.transaction_tokens == [1]


@pytest.mark.asyncio
async def test_authentication_transaction_is_closed_before_coherent_read() -> None:
    service, session, _, _ = _service()

    await service.read(_command())

    assert session.commit_count == 1
    assert session.events.index("commit-auth") < session.events.index("begin")


@pytest.mark.asyncio
async def test_reader_receives_exact_command_and_guard_once() -> None:
    service, _, reader, _ = _service(
        result=_read(selected_snapshot_id="snapshot-1"),
    )
    command = _command(required_snapshot_id="snapshot-1")

    await service.read(command)

    assert reader.calls == [
        ReadExactPortfolioSnapshotCommand(
            account_id=command.account_id,
            timestamp=command.timestamp,
            granularity=command.granularity,
            currency=command.currency,
            calculation_version=command.calculation_version,
            required_snapshot_id="snapshot-1",
        )
    ]


@pytest.mark.asyncio
async def test_authorized_result_returns_only_pure_view_and_no_lineage() -> None:
    service, _, _, _ = _service()

    result = await service.read(_command())

    assert result.view == _view()
    assert not hasattr(result, "selected_item_ids")
    assert not hasattr(result, "selected_snapshot_id")
    assert not hasattr(result, "role")


@pytest.mark.asyncio
async def test_reader_error_maps_to_generic_unavailable_error() -> None:
    service, session, _, _ = _service(result=PortfolioSnapshotReadError())

    with pytest.raises(PortfolioSnapshotUnavailableError) as error:
        await service.read(_command())

    assert error.value.code == "portfolio_snapshot_unavailable"
    assert error.value.message == "The requested portfolio snapshot is unavailable."
    assert session.in_transaction() is False


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [AccountNotFoundError(), AccountAccessDeniedError()])
async def test_account_authorization_error_is_not_rewritten(error: BaseException) -> None:
    service, session, reader, _ = _service(access_error=error)

    with pytest.raises(type(error)) as caught:
        await service.read(_command())

    assert caught.value is error
    assert reader.calls == []
    assert session.in_transaction() is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        _read(view=_view(account_id="account-2")),
        _read(view=_view(snapshot_id="snapshot-2")),
        _read(
            view=_view(positions=(_position(), _position("listing-2"))),
            selected_item_ids=("item-1", "item-1"),
        ),
        _read(
            view=_view(positions=(_position(),)),
            selected_item_ids=("item-2", "item-1"),
        ),
        _read(
            view=_view(positions=(_position(),)),
            selected_item_ids=(" item-1",),
        ),
    ],
)
async def test_inconsistent_reader_result_fails_closed(result: object) -> None:
    service, session, _, _ = _service(result=result)

    with pytest.raises(PortfolioSnapshotUnavailableError):
        await service.read(_command())

    assert session.in_transaction() is False


@pytest.mark.asyncio
async def test_required_snapshot_mismatch_fails_closed() -> None:
    service, session, _, _ = _service()

    with pytest.raises(PortfolioSnapshotUnavailableError):
        await service.read(_command(required_snapshot_id="snapshot-2"))

    assert session.in_transaction() is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        object(),
        _command(principal=object()),
        _command(principal=_principal("")),
        _command(account_id=""),
        _command(account_id=" account-1"),
        _command(required_snapshot_id=""),
        _command(currency="EU"),
        _command(currency="eur"),
        _command(timestamp=SNAPSHOT_AT.replace(tzinfo=UTC)),
        _command(timestamp=SNAPSHOT_AT.replace(microsecond=1)),
        _command(timestamp=SNAPSHOT_AT.replace(hour=1)),
        _command(granularity="day"),
        _command(calculation_version=0),
        _command(calculation_version=True),
        _command(calculation_version=2_147_483_648),
    ],
)
async def test_invalid_command_fails_closed_and_closes_auth_transaction(value: object) -> None:
    service, session, reader, _ = _service()

    with pytest.raises(PortfolioSnapshotUnavailableError):
        await service.read(value)

    assert session.rollback_count == 1
    assert reader.calls == []
    assert session.in_transaction() is False


def test_command_and_result_are_immutable() -> None:
    command = _command()
    result = ReadAuthorizedPortfolioSnapshotResult(view=_view())

    with pytest.raises(FrozenInstanceError):
        command.account_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.view = _view(account_id="changed")  # type: ignore[misc]
    assert replace(command, account_id="account-2").account_id == "account-2"


def test_error_message_contains_no_identity_or_financial_detail() -> None:
    error = PortfolioSnapshotUnavailableError()
    message = error.message

    assert message == "The requested portfolio snapshot is unavailable."
    for forbidden in (
        "account-1",
        "snapshot-1",
        "item-1",
        "EUR",
        "2032",
        "100.000000",
    ):
        assert forbidden not in message


def test_authorized_service_has_no_financial_or_live_data_dependencies() -> None:
    source_path = (
        Path(__file__).parents[1]
        / "app"
        / "modules"
        / "portfolio_snapshot"
        / "authorized_service.py"
    )
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert {
        "HoldingModel",
        "PriceSnapshotModel",
        "ExchangeRateModel",
        "InvestmentEventModel",
        "InvestmentMovementModel",
        "TransactionModel",
        "NetWorthSnapshotModel",
        "ImportBatchModel",
        "ImportRowModel",
    }.isdisjoint(imported)
    for forbidden in ("datetime.now", "uuid", "float(", "round(", "latest", "fallback"):
        assert forbidden not in source
