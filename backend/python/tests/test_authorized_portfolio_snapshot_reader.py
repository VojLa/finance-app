from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import AccountMemberRole, AccountRelationType
from app.modules.accounts.access import (
    AccountNotFoundError,
    AuthorizedAccount,
)
from app.modules.portfolio_snapshot.authorized_reader import (
    AuthorizedExactPortfolioSnapshotReader,
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
    ReadExactPortfolioSnapshotCommand,
)

SNAPSHOT_AT = datetime(2032, 8, 2)
MODULE = (
    Path(__file__).parents[1] / "app" / "modules" / "portfolio_snapshot" / "authorized_reader.py"
)


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="user-1", email="user@example.com", name="User")


def _position(listing_id: str = "listing-1") -> PortfolioPositionView:
    return PortfolioPositionView(
        listing_id=listing_id,
        asset_id=f"{listing_id}-asset",
        symbol="AAA",
        name="Asset",
        asset_type=AssetType.stock,
        quantity=Decimal("1.0000000000"),
        price_per_unit=Decimal("100.0000000000"),
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
    account_id: str = "account-1",
    snapshot_id: str = "snapshot-1",
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


class _Session:
    def __init__(self, *, active: bool = True) -> None:
        self.active = active
        self.commit_count = 0
        self.rollback_count = 0
        self.begin_count = 0
        self.execute_count = 0

    def in_transaction(self) -> bool:
        return self.active

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1

    def begin(self) -> object:
        self.begin_count += 1
        return object()

    async def execute(self, statement: object) -> object:
        self.execute_count += 1
        return statement


class _PersistedReader:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[ReadExactPortfolioSnapshotCommand] = []

    async def read(
        self,
        command: ReadExactPortfolioSnapshotCommand,
    ) -> CompletePortfolioSnapshotRead:
        self.calls.append(command)
        if isinstance(self.result, BaseException):
            raise self.result
        return cast(CompletePortfolioSnapshotRead, self.result)


def _service(
    *,
    role: AccountMemberRole = AccountMemberRole.owner,
    result: object | None = None,
    access_error: BaseException | None = None,
    active: bool = True,
) -> tuple[
    AuthorizedExactPortfolioSnapshotReader,
    _Session,
    _PersistedReader,
    list[dict[str, Any]],
]:
    session = _Session(active=active)
    view = _view()
    persisted = _PersistedReader(
        result
        or CompletePortfolioSnapshotRead(
            view=view,
            selected_snapshot_id=view.snapshot_id,
            selected_item_ids=(),
        )
    )
    access_calls: list[dict[str, Any]] = []

    async def access(**kwargs: Any) -> AuthorizedAccount:
        access_calls.append(kwargs)
        if access_error is not None:
            raise access_error
        return AuthorizedAccount(
            account_id=kwargs["account_id"],
            role=role,
            relation_type=AccountRelationType.owner,
        )

    service = AuthorizedExactPortfolioSnapshotReader(
        cast(AsyncSession, session),
        reader_factory=lambda _session: persisted,
        access_checker=access,
    )
    return service, session, persisted, access_calls


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
async def test_explicit_read_roles_share_the_exact_reader(role: AccountMemberRole) -> None:
    service, _, persisted, access_calls = _service(role=role)

    result = await service.read(_command())

    assert result == ReadAuthorizedPortfolioSnapshotResult(view=_view())
    assert access_calls[0]["allowed_roles"] == frozenset(
        {
            AccountMemberRole.owner,
            AccountMemberRole.admin,
            AccountMemberRole.editor,
            AccountMemberRole.viewer,
        }
    )
    assert len(persisted.calls) == 1


@pytest.mark.asyncio
async def test_access_contract_is_non_archived_and_unlocked() -> None:
    service, _, _, access_calls = _service()

    await service.read(_command())

    assert len(access_calls) == 1
    assert access_calls[0]["include_archived"] is False
    assert access_calls[0]["for_update"] is False
    assert access_calls[0]["account_id"] == "account-1"
    assert access_calls[0]["principal"] == _principal()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["foreign", "missing", "archived"])
async def test_hidden_account_states_preserve_not_found(kind: str) -> None:
    service, _, persisted, _ = _service(access_error=AccountNotFoundError())

    with pytest.raises(AccountNotFoundError):
        await service.read(_command())

    assert persisted.calls == []
    assert kind


@pytest.mark.asyncio
async def test_exact_reader_command_and_optional_guard_are_mapped_once() -> None:
    service, _, persisted, _ = _service(
        result=CompletePortfolioSnapshotRead(
            view=_view(snapshot_id="snapshot-1"),
            selected_snapshot_id="snapshot-1",
            selected_item_ids=(),
        )
    )

    await service.read(_command(required_snapshot_id="snapshot-1"))

    assert persisted.calls == [
        ReadExactPortfolioSnapshotCommand(
            account_id="account-1",
            timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.day,
            currency="EUR",
            calculation_version=1,
            required_snapshot_id="snapshot-1",
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        CompletePortfolioSnapshotRead(
            view=_view(account_id="other"),
            selected_snapshot_id="snapshot-1",
            selected_item_ids=(),
        ),
        CompletePortfolioSnapshotRead(
            view=_view(snapshot_id="other"),
            selected_snapshot_id="snapshot-1",
            selected_item_ids=(),
        ),
        CompletePortfolioSnapshotRead(
            view=_view(positions=(_position(),)),
            selected_snapshot_id="snapshot-1",
            selected_item_ids=(),
        ),
        CompletePortfolioSnapshotRead(
            view=_view(positions=(_position(),)),
            selected_snapshot_id="snapshot-1",
            selected_item_ids=("item-2", "item-1"),
        ),
        CompletePortfolioSnapshotRead(
            view=_view(positions=(_position(), _position("listing-2"))),
            selected_snapshot_id="snapshot-1",
            selected_item_ids=("item-1", "item-1"),
        ),
        CompletePortfolioSnapshotRead(
            view=_view(positions=(_position(),)),
            selected_snapshot_id="snapshot-1",
            selected_item_ids=(" item-1",),
        ),
    ],
)
async def test_inconsistent_reader_identity_or_items_fail_closed(result: object) -> None:
    service, _, _, _ = _service(result=result)

    with pytest.raises(PortfolioSnapshotUnavailableError):
        await service.read(_command())


@pytest.mark.asyncio
async def test_required_snapshot_guard_must_match_selected_identity() -> None:
    service, _, _, _ = _service()

    with pytest.raises(PortfolioSnapshotUnavailableError):
        await service.read(_command(required_snapshot_id="different"))


@pytest.mark.asyncio
async def test_active_caller_transaction_is_required() -> None:
    service, _, persisted, access_calls = _service(active=False)

    with pytest.raises(PortfolioSnapshotUnavailableError):
        await service.read(_command())

    assert access_calls == []
    assert persisted.calls == []


@pytest.mark.asyncio
async def test_shared_reader_never_owns_or_configures_transaction() -> None:
    service, session, _, _ = _service()

    await service.read(_command())

    assert session.active is True
    assert session.commit_count == 0
    assert session.rollback_count == 0
    assert session.begin_count == 0
    assert session.execute_count == 0


def test_shared_command_and_result_are_frozen() -> None:
    command = _command()
    result = ReadAuthorizedPortfolioSnapshotResult(view=_view())

    with pytest.raises(FrozenInstanceError):
        command.account_id = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.view = _view(account_id="changed")  # type: ignore[misc]
    assert replace(command, account_id="other").account_id == "other"


def test_shared_reader_boundary_has_no_transaction_or_live_finance_operations() -> None:
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert {"commit", "rollback", "begin", "execute"}.isdisjoint(calls)
    assert {
        "HoldingModel",
        "PriceSnapshotModel",
        "ExchangeRateModel",
        "AccountSnapshotModel",
    }.isdisjoint(imports)
    for forbidden in (
        "SET TRANSACTION",
        "for_update=True",
        "datetime.now",
        "float(",
        "round(",
        "latest",
        "fallback",
    ):
        assert forbidden not in source
