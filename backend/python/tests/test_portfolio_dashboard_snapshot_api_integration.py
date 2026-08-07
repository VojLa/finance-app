from __future__ import annotations

import asyncio
import importlib
import os
import threading
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, insert, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connection import get_db_session
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
)
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.main import create_app
from app.modules.portfolio_snapshot.repository import PortfolioSnapshotRepository

_integration_support: Any = importlib.import_module("tests.test_portfolio_snapshot_api_integration")
SNAPSHOT_AT = _integration_support.SNAPSHOT_AT
_cleanup = _integration_support._cleanup
_engine = _integration_support._engine
_headers = _integration_support._headers
_prefix = _integration_support._prefix
_seed = _integration_support._seed
_settings = _integration_support._settings

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
PORTFOLIO_PATH = "/api/v1/portfolio/snapshot"
DASHBOARD_PATH = "/api/v1/dashboard/snapshot"


async def _add_access(
    prefix: str,
    *,
    user_id: str,
    account_id: str,
    role: AccountMemberRole = AccountMemberRole.owner,
) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            AccountMemberModel(
                id=f"{prefix}-shared-{role.value}-member",
                account_id=account_id,
                user_id=user_id,
                role=role,
                relation_type=AccountRelationType.owner,
                invited_by_id=None,
                accepted_at=SNAPSHOT_AT,
                created_at=SNAPSHOT_AT,
                updated_at=SNAPSHOT_AT,
            )
        )
        await session.commit()
    await engine.dispose()


async def _seed_pair(
    prefix: str,
    *,
    second_type: AccountType = AccountType.broker,
    second_empty: bool = False,
) -> tuple[str, tuple[str, str], tuple[str, str]]:
    user_id, account_a, snapshot_a = await _seed(f"{prefix}-a")
    _, account_b, snapshot_b = await _seed(
        f"{prefix}-b",
        account_type=second_type,
        empty=second_empty,
    )
    await _add_access(prefix, user_id=user_id, account_id=account_b)
    return user_id, (account_a, account_b), (snapshot_a, snapshot_b)


async def _set_single_position(
    prefix: str,
    *,
    snapshot_id: str,
    value: str,
    cost: str,
    item_suffix: str = "a",
) -> None:
    engine = _engine()
    money_value = Decimal(value).quantize(Decimal("0.000001"))
    quantity_value = Decimal(value).quantize(Decimal("0.0000000001"))
    money_cost = Decimal(cost).quantize(Decimal("0.000001"))
    quantity_cost = Decimal(cost).quantize(Decimal("0.0000000001"))
    async with AsyncSession(engine) as session:
        await session.execute(
            delete(AccountSnapshotItemModel).where(
                AccountSnapshotItemModel.snapshot_id == snapshot_id,
                AccountSnapshotItemModel.id != f"{prefix}-item-{item_suffix}",
            )
        )
        await session.execute(
            update(AccountSnapshotItemModel)
            .where(AccountSnapshotItemModel.id == f"{prefix}-item-{item_suffix}")
            .values(
                quantity=Decimal("1.0000000000"),
                price_per_unit=quantity_value,
                value=money_value,
                cost_basis=quantity_cost,
                allocation_pct=Decimal("100.0000"),
                native_value=quantity_value,
                native_cost_basis=quantity_cost,
            )
        )
        await session.execute(
            update(AccountSnapshotModel)
            .where(AccountSnapshotModel.id == snapshot_id)
            .values(
                investment_value=money_value,
                investment_cost_basis=money_cost,
                total_value=Decimal("10.000000") + money_value,
                unrealized_pnl_value=money_value - money_cost,
            )
        )
        await session.commit()
    await engine.dispose()


def _body(
    account_ids: tuple[str, ...],
    *,
    snapshot_ids: tuple[str | None, ...] | None = None,
    **changes: object,
) -> dict[str, object]:
    guards = snapshot_ids or (None,) * len(account_ids)
    result: dict[str, object] = {
        "timestamp": "2032-08-02T00:00:00.000",
        "granularity": "day",
        "currency": "EUR",
        "calculationVersion": 1,
        "accounts": [
            {
                "accountId": account_id,
                **({"snapshotId": guard} if guard is not None else {}),
            }
            for account_id, guard in zip(account_ids, guards, strict=True)
        ],
    }
    result.update(changes)
    return result


def _call(
    path: str,
    user_id: str,
    body: dict[str, object],
    *,
    sql: list[tuple[str, int]] | None = None,
    pause_after_first_access: tuple[threading.Event, threading.Event] | None = None,
    session_states: list[bool] | None = None,
):
    app = create_app(_settings())
    with TestClient(app) as client:
        database = app.state.database
        if session_states is not None:

            async def session_override() -> AsyncIterator[AsyncSession]:
                async with AsyncSession(database.engine, expire_on_commit=False) as session:
                    yield session
                    session_states.append(session.in_transaction())

            app.dependency_overrides[get_db_session] = session_override
        if sql is not None:

            def capture(
                connection: Any,
                _cursor: object,
                statement: str,
                _parameters: object,
                _context: object,
                _executemany: bool,
            ) -> None:
                transaction = connection.get_transaction()
                sql.append((statement, id(transaction)))

            event.listen(database.engine.sync_engine, "before_cursor_execute", capture)
        if pause_after_first_access is not None:
            reached, resume = pause_after_first_access
            paused = False

            def pause(
                _connection: Any,
                _cursor: object,
                statement: str,
                _parameters: object,
                _context: object,
                _executemany: bool,
            ) -> None:
                nonlocal paused
                normalized = " ".join(statement.lower().split())
                if not paused and '"accountmember"' in normalized:
                    paused = True
                    reached.set()
                    assert resume.wait(timeout=10)

            event.listen(database.engine.sync_engine, "after_cursor_execute", pause)
        return client.post(path, json=body, headers=_headers(user_id))


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [PORTFOLIO_PATH, DASHBOARD_PATH])
async def test_one_exact_broker_account_succeeds(path: str) -> None:
    prefix = _prefix(f"5lf-one-{path.split('/')[3]}")
    await _cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await _seed(prefix)

        response = _call(
            path,
            user_id,
            _body((account_id,), snapshot_ids=(snapshot_id,)),
        )

        assert response.status_code == 200
        assert response.json()["accounts"][0]["snapshotId"] == snapshot_id
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_two_investments_and_investment_liability_portfolios() -> None:
    prefix = _prefix("5lf-shapes")
    await _cleanup(prefix)
    try:
        user_id, accounts, snapshots = await _seed_pair(prefix)
        portfolio = _call(
            PORTFOLIO_PATH,
            user_id,
            _body(accounts, snapshot_ids=snapshots),
        )
        assert portfolio.status_code == 200
        assert portfolio.json()["summary"]["accountCount"] == 2
        assert portfolio.json()["summary"]["investmentValue"] == "200.000000"

        await _cleanup(prefix)
        user_id, accounts, snapshots = await _seed_pair(
            prefix,
            second_type=AccountType.loan,
        )
        mixed = _call(
            PORTFOLIO_PATH,
            user_id,
            _body(accounts, snapshot_ids=snapshots),
        )
        assert mixed.status_code == 200
        assert mixed.json()["summary"]["liabilitiesValue"] == "25.000000"
        assert mixed.json()["accounts"][1]["positions"] == []
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_dashboard_global_60_40_and_same_asset_remains_account_scoped() -> None:
    prefix = _prefix("5lf-global")
    await _cleanup(prefix)
    try:
        user_id, accounts, snapshots = await _seed_pair(prefix)
        await _set_single_position(
            f"{prefix}-a",
            snapshot_id=snapshots[0],
            value="60",
            cost="50",
        )
        await _set_single_position(
            f"{prefix}-b",
            snapshot_id=snapshots[1],
            value="40",
            cost="30",
        )
        engine = _engine()
        async with AsyncSession(engine) as session:
            first = await session.scalar(
                select(AccountSnapshotItemModel).where(
                    AccountSnapshotItemModel.snapshot_id == snapshots[0]
                )
            )
            second = await session.scalar(
                select(AccountSnapshotItemModel).where(
                    AccountSnapshotItemModel.snapshot_id == snapshots[1]
                )
            )
            assert first is not None and second is not None
            await session.execute(
                update(AccountSnapshotItemModel)
                .where(AccountSnapshotItemModel.id == second.id)
                .values(
                    asset_id=first.asset_id,
                    listing_id=first.listing_id,
                    symbol=first.symbol,
                )
            )
            await session.commit()
        await engine.dispose()

        response = _call(DASHBOARD_PATH, user_id, _body(accounts))

        assert response.status_code == 200
        positions = response.json()["topPositions"]
        assert [position["allocationPct"] for position in positions] == [
            "60.0000",
            "40.0000",
        ]
        assert len(positions) == 2
        assert {position["accountId"] for position in positions} == set(accounts)
        assert len({position["listingId"] for position in positions}) == 1
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("account_type", "empty"),
    [(AccountType.loan, False), (AccountType.broker, True)],
)
async def test_dashboard_without_investments_has_empty_breakdowns(
    account_type: AccountType,
    empty: bool,
) -> None:
    prefix = _prefix(f"5lf-empty-{account_type.value}")
    await _cleanup(prefix)
    try:
        user_id, account_id, _ = await _seed(
            prefix,
            account_type=account_type,
            empty=empty,
        )

        response = _call(DASHBOARD_PATH, user_id, _body((account_id,)))

        assert response.status_code == 200
        assert response.json()["assetTypeAllocations"] == []
        assert response.json()["topPositions"] == []
    finally:
        await _cleanup(prefix)


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
async def test_every_read_role_can_read_an_exact_set(role: AccountMemberRole) -> None:
    prefix = _prefix(f"5lf-role-{role.value}")
    await _cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await _seed(prefix, role=role)

        response = _call(
            PORTFOLIO_PATH,
            user_id,
            _body((account_id,), snapshot_ids=(snapshot_id,)),
        )

        assert response.status_code == 200
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_request_account_permutation_is_deterministic() -> None:
    prefix = _prefix("5lf-order")
    await _cleanup(prefix)
    try:
        user_id, accounts, _ = await _seed_pair(prefix)

        first = _call(PORTFOLIO_PATH, user_id, _body(accounts))
        second = _call(PORTFOLIO_PATH, user_id, _body(tuple(reversed(accounts))))

        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_foreign_missing_and_archived_selectors_share_404_without_partial_data() -> None:
    prefix = _prefix("5lf-hidden")
    await _cleanup(prefix)
    try:
        user_id, valid_account, _ = await _seed(f"{prefix}-valid")
        _, foreign_account, _ = await _seed(f"{prefix}-foreign")
        _, archived_account, _ = await _seed(f"{prefix}-archived", archived=True)
        await _add_access(prefix, user_id=user_id, account_id=archived_account)
        responses = (
            _call(
                PORTFOLIO_PATH,
                user_id,
                _body((valid_account, foreign_account)),
            ),
            _call(
                PORTFOLIO_PATH,
                user_id,
                _body((valid_account, f"{prefix}-missing-account")),
            ),
            _call(
                PORTFOLIO_PATH,
                user_id,
                _body((valid_account, archived_account)),
            ),
        )

        contracts = [
            (
                response.status_code,
                response.json()["error"]["code"],
                response.json()["error"]["message"],
            )
            for response in responses
        ]
        assert contracts == [(404, "account_not_found", "The account was not found.")] * 3
        for response in responses:
            assert "accounts" not in response.json()
            assert valid_account not in response.text
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "changes",
    [
        {"currency": "USD"},
        {"calculationVersion": 2},
        {"timestamp": "2032-08-03T00:00:00.000"},
    ],
)
async def test_exact_metadata_never_falls_back(changes: dict[str, object]) -> None:
    prefix = _prefix("5lf-selector")
    await _cleanup(prefix)
    try:
        user_id, account_id, _ = await _seed(prefix)

        body = _body((account_id,))
        body.update(changes)
        response = _call(PORTFOLIO_PATH, user_id, body)

        assert response.status_code == 409
        assert response.json()["error"] == {
            "code": "portfolio_snapshot_unavailable",
            "message": "The requested portfolio snapshot is unavailable.",
            "request_id": response.json()["error"]["request_id"],
        }
        assert account_id not in response.text
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_wrong_snapshot_guard_and_corrupt_item_return_generic_409() -> None:
    prefix = _prefix("5lf-corrupt")
    await _cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await _seed(prefix)
        wrong = _call(
            PORTFOLIO_PATH,
            user_id,
            _body((account_id,), snapshot_ids=("wrong-snapshot",)),
        )
        assert wrong.status_code == 409

        engine = _engine()
        async with AsyncSession(engine) as session:
            await session.execute(
                update(AccountSnapshotItemModel)
                .where(AccountSnapshotItemModel.snapshot_id == snapshot_id)
                .values(price_timestamp=SNAPSHOT_AT.replace(day=3))
            )
            await session.commit()
        await engine.dispose()
        corrupt = _call(PORTFOLIO_PATH, user_id, _body((account_id,)))

        assert corrupt.status_code == 409
        assert wrong.json()["error"]["code"] == corrupt.json()["error"]["code"]
        assert wrong.json()["error"]["message"] == corrupt.json()["error"]["message"]
        assert snapshot_id not in corrupt.text
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_corrupt_item_listing_asset_graph_returns_generic_409() -> None:
    prefix = _prefix("5lf-graph")
    await _cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await _seed(prefix)
        await _set_single_position(
            prefix,
            snapshot_id=snapshot_id,
            value="60",
            cost="50",
        )
        engine = _engine()
        async with AsyncSession(engine) as session:
            await session.execute(
                update(AccountSnapshotItemModel)
                .where(AccountSnapshotItemModel.id == f"{prefix}-item-a")
                .values(listing_id=f"{prefix}-listing-b")
            )
            await session.commit()
        await engine.dispose()

        response = _call(PORTFOLIO_PATH, user_id, _body((account_id,)))

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "portfolio_snapshot_unavailable"
        assert account_id not in response.text
        assert snapshot_id not in response.text
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_nonrepresentable_dashboard_percentage_returns_generic_409() -> None:
    prefix = _prefix("5lf-percentage")
    await _cleanup(prefix)
    try:
        user_id, accounts, snapshots = await _seed_pair(prefix)
        await _set_single_position(
            f"{prefix}-a",
            snapshot_id=snapshots[0],
            value="1",
            cost="1",
        )
        await _set_single_position(
            f"{prefix}-b",
            snapshot_id=snapshots[1],
            value="2",
            cost="2",
        )

        response = _call(DASHBOARD_PATH, user_id, _body(accounts))

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "portfolio_snapshot_unavailable"
        assert all(account_id not in response.text for account_id in accounts)
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_database_constraint_prevents_duplicate_exact_snapshot_identity() -> None:
    prefix = _prefix("5lf-duplicate")
    await _cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await _seed(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            existing = await session.get(AccountSnapshotModel, snapshot_id)
            assert existing is not None
            values = {
                column.name: getattr(
                    existing,
                    inspect(AccountSnapshotModel).get_property_by_column(column).key,
                )
                for column in AccountSnapshotModel.__table__.columns
            }
            values["id"] = f"{prefix}-duplicate-snapshot"
            with pytest.raises(IntegrityError):
                await session.execute(insert(AccountSnapshotModel).values(**values))
                await session.flush()
            await session.rollback()
        await engine.dispose()

        response = _call(PORTFOLIO_PATH, user_id, _body((account_id,)))

        assert response.status_code == 200
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_duplicate_repository_candidates_return_generic_409(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = _prefix("5lf-duplicate-candidate")
    await _cleanup(prefix)
    original = PortfolioSnapshotRepository.load_exact_snapshots

    async def duplicated(
        repository: PortfolioSnapshotRepository,
        **kwargs: Any,
    ) -> tuple[AccountSnapshotModel, ...]:
        rows = await original(repository, **kwargs)
        return rows + rows

    monkeypatch.setattr(
        PortfolioSnapshotRepository,
        "load_exact_snapshots",
        duplicated,
    )
    try:
        user_id, account_id, snapshot_id = await _seed(prefix)

        response = _call(PORTFOLIO_PATH, user_id, _body((account_id,)))

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "portfolio_snapshot_unavailable"
        assert account_id not in response.text
        assert snapshot_id not in response.text
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_all_financial_queries_share_one_repeatable_read_transaction_without_writes() -> None:
    prefix = _prefix("5lf-transaction")
    await _cleanup(prefix)
    try:
        user_id, accounts, _ = await _seed_pair(prefix)
        sql: list[tuple[str, int]] = []
        session_states: list[bool] = []

        response = _call(
            PORTFOLIO_PATH,
            user_id,
            _body(accounts),
            sql=sql,
            session_states=session_states,
        )

        assert response.status_code == 200
        normalized = [" ".join(statement.lower().split()) for statement, _ in sql]
        isolation_index = normalized.index("set transaction isolation level repeatable read")
        assert isolation_index > 0
        coherent_transaction = sql[isolation_index][1]
        financial = sql[isolation_index:]
        assert all(transaction == coherent_transaction for _, transaction in financial)
        assert sum('"accountmember"' in statement for statement in normalized) == 2
        assert all(
            not statement.lstrip().startswith(("insert ", "update ", "delete "))
            for statement, _ in financial
        )
        assert all("for update" not in statement.lower() for statement, _ in financial)
        assert all("advisory" not in statement.lower() for statement, _ in financial)
        assert session_states == [False]
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_repeatable_read_prevents_mixed_account_metadata_during_concurrent_update() -> None:
    prefix = _prefix("5lf-coherent")
    await _cleanup(prefix)
    reached = threading.Event()
    resume = threading.Event()
    try:
        user_id, accounts, _ = await _seed_pair(prefix)
        original_second_name = f"{prefix}-b account"
        task = asyncio.create_task(
            asyncio.to_thread(
                _call,
                PORTFOLIO_PATH,
                user_id,
                _body(accounts),
                pause_after_first_access=(reached, resume),
            )
        )
        assert await asyncio.to_thread(reached.wait, 10)

        engine = _engine()
        async with AsyncSession(engine) as session:
            await session.execute(
                update(AccountModel)
                .where(AccountModel.id == accounts[1])
                .values(name="concurrently changed")
            )
            await session.commit()
        await engine.dispose()
        resume.set()
        first = await asyncio.wait_for(task, timeout=15)

        assert first.status_code == 200
        names = {account["account"]["name"] for account in first.json()["accounts"]}
        assert original_second_name in names

        second = _call(PORTFOLIO_PATH, user_id, _body(accounts))
        assert second.status_code == 200
        new_names = {account["account"]["name"] for account in second.json()["accounts"]}
        assert "concurrently changed" in new_names
        assert original_second_name not in new_names
    finally:
        resume.set()
        await _cleanup(prefix)
