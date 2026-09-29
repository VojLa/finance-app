from __future__ import annotations

import asyncio
import importlib
import os
import threading
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, insert, inspect, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.connection import get_db_session
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.canonical_lineage import (
    AccountCanonicalStateModel,
    AccountSnapshotCanonicalBoundaryModel,
    SnapshotGenerationModel,
    SnapshotGenerationTargetModel,
)
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetType,
    LiabilityBalanceSource,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
    TransactionClassification,
    TransactionType,
)
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.main import create_app
from app.modules.portfolio_snapshot.reader import PreloadedPortfolioSnapshotRepository

_integration_support: Any = importlib.import_module("tests.test_portfolio_snapshot_api_integration")
SNAPSHOT_AT = _integration_support.SNAPSHOT_AT
CREATED_AT = _integration_support.CREATED_AT
_engine = _integration_support._engine
_headers = _integration_support._headers
_settings = _integration_support._settings

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
PORTFOLIO_PATH = "/api/v1/portfolio/snapshot"
DASHBOARD_PATH = "/api/v1/dashboard/snapshot"


def _prefix(label: str) -> str:
    return f"5lf-{uuid4().hex}-{label}"


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            account_ids = select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
            await session.execute(
                delete(TransactionModel).where(TransactionModel.account_id.in_(account_ids))
            )
            await session.commit()
    finally:
        await engine.dispose()
    await _integration_support._cleanup(prefix)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            await session.execute(
                delete(SnapshotGenerationModel).where(
                    SnapshotGenerationModel.id.startswith(f"{prefix}-")
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _seed(
    prefix: str,
    *,
    role: AccountMemberRole = AccountMemberRole.owner,
    account_type: AccountType = AccountType.broker,
    archived: bool = False,
    empty: bool = False,
) -> tuple[str, str, str]:
    user_id = f"{prefix}-user"
    account_id = f"{prefix}-account"
    snapshot_id = f"{prefix}-snapshot"
    generation_id = f"{prefix}-generation"
    liability = account_type in {AccountType.loan, AccountType.mortgage}
    credit_card = account_type is AccountType.credit_card
    with_items = not (liability or credit_card or empty)
    investment = Decimal("100.000000") if with_items else Decimal("0.000000")
    cost_basis = Decimal("80.000000") if with_items else Decimal("0.000000")
    cash = (
        Decimal("-25.000000")
        if credit_card
        else (Decimal("0.000000") if liability else Decimal("10.000000"))
    )
    liabilities = Decimal("25.000000") if liability else Decimal("0.000000")
    evidence_id = f"{prefix}-balance" if liability else None
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{user_id}@example.com",
                    name=user_id,
                    password_hash=None,
                    base_currency="CZK",
                    created_at=SNAPSHOT_AT,
                    updated_at=SNAPSHOT_AT,
                )
            )
            session.add(
                AccountModel(
                    id=account_id,
                    name=f"{prefix} account",
                    type=account_type,
                    currency="EUR",
                    color=None,
                    notes=None,
                    is_archived=archived,
                    archived_at=CREATED_AT if archived else None,
                    created_at=SNAPSHOT_AT,
                    updated_at=SNAPSHOT_AT,
                )
            )
            await session.flush()
            session.add(
                AccountMemberModel(
                    id=f"{prefix}-member",
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
            session.add(
                SnapshotGenerationModel(
                    id=generation_id,
                    state="published",
                    created_at=CREATED_AT,
                    published_at=CREATED_AT,
                )
            )
            await session.flush()
            session.add(
                SnapshotGenerationTargetModel(
                    generation_id=generation_id,
                    user_id=user_id,
                    created_at=CREATED_AT,
                    staged_by_job_id=None,
                    staged_lease_version=None,
                    staged_lease_owner=None,
                )
            )
            if credit_card:
                session.add(
                    TransactionModel(
                        id=f"{prefix}-purchase",
                        account_id=account_id,
                        date=SNAPSHOT_AT,
                        booking_date=SNAPSHOT_AT,
                        amount=Decimal("-25.000000"),
                        currency="EUR",
                        type=TransactionType.expense,
                        classification=TransactionClassification.real_expense,
                        description="card purchase",
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    )
                )
            elif liability:
                session.add(
                    LiabilityBalanceModel(
                        id=evidence_id,
                        account_id=account_id,
                        effective_at=SNAPSHOT_AT,
                        currency="EUR",
                        outstanding_principal=Decimal("25.000000"),
                        accrued_interest=Decimal("0.000000"),
                        fees_outstanding=Decimal("0.000000"),
                        total_outstanding=Decimal("25.000000"),
                        source=LiabilityBalanceSource.manual,
                        external_id=None,
                        created_at=CREATED_AT,
                    )
                )
            await session.flush()
            canonical_state = await session.get(AccountCanonicalStateModel, account_id)
            assert canonical_state is not None
            canonical_revision = canonical_state.last_revision
            if with_items:
                canonical_state.holding_revision = canonical_state.last_investment_revision
            session.add(
                AccountSnapshotModel(
                    id=snapshot_id,
                    account_id=account_id,
                    generation_id=generation_id,
                    timestamp=SNAPSHOT_AT,
                    granularity=SnapshotGranularity.day,
                    source=SnapshotSource.manual_recalculation,
                    currency="EUR",
                    cash_value=cash,
                    investment_value=investment,
                    investment_cost_basis=cost_basis,
                    liabilities_value=liabilities,
                    total_value=cash + investment - liabilities,
                    is_recalculated=True,
                    calculated_at=CREATED_AT,
                    calculation_version=1,
                    created_at=CREATED_AT,
                    net_deposits_value=Decimal("0.000000"),
                    realized_pnl_value=Decimal("0.000000"),
                    unrealized_pnl_value=investment - cost_basis,
                    fees_value=Decimal("0.000000"),
                    taxes_value=Decimal("0.000000"),
                    cash_value_by_currency={"EUR": format(cash, ".6f")},
                    investment_value_by_currency=None,
                    investment_cost_basis_by_currency=None,
                    net_deposits_by_currency={},
                    realized_pnl_by_currency=None,
                    unrealized_pnl_by_currency=None,
                    fees_by_currency=None,
                    taxes_by_currency=None,
                    exchange_rates=None,
                )
            )
            await session.flush()
            session.add(
                AccountSnapshotCanonicalBoundaryModel(
                    snapshot_id=snapshot_id,
                    account_id=account_id,
                    canonical_revision=canonical_revision,
                    investment_revision=0 if with_items else None,
                    holding_revision=0 if with_items else None,
                    selected_liability_balance_id=evidence_id,
                    created_at=CREATED_AT,
                )
            )
            if with_items:
                for suffix, symbol, native_currency, value, cost, allocation in (
                    ("a", "AAA", "USD", "60.000000", "50.0000000000", "60.0000"),
                    ("b", "BBB", "GBP", "40.000000", "30.0000000000", "40.0000"),
                ):
                    asset = AssetModel(
                        id=f"{prefix}-asset-{suffix}",
                        symbol=symbol,
                        isin=None,
                        name=f"{symbol} asset",
                        asset_type=AssetType.stock,
                        currency=native_currency,
                        created_at=SNAPSHOT_AT,
                        updated_at=SNAPSHOT_AT,
                    )
                    listing = AssetListingModel(
                        id=f"{prefix}-listing-{suffix}",
                        asset_id=asset.id,
                        symbol=symbol,
                        exchange=None,
                        mic=None,
                        currency=native_currency,
                        country=None,
                        provider=PriceSource.manual,
                        provider_symbol=None,
                        is_primary=True,
                        created_at=SNAPSHOT_AT,
                        updated_at=SNAPSHOT_AT,
                    )
                    session.add(asset)
                    await session.flush()
                    session.add(listing)
                    await session.flush()
                    session.add(
                        AccountSnapshotItemModel(
                            id=f"{prefix}-item-{suffix}",
                            snapshot_id=snapshot_id,
                            asset_id=asset.id,
                            listing_id=listing.id,
                            symbol=symbol,
                            quantity=Decimal("2.0000000000"),
                            price_per_unit=Decimal(value) / Decimal(2),
                            price_currency=native_currency,
                            price_source=PriceSource.manual,
                            price_timestamp=SNAPSHOT_AT,
                            value=Decimal(value),
                            cost_basis=Decimal(cost),
                            cost_currency="EUR",
                            allocation_pct=Decimal(allocation),
                            created_at=CREATED_AT,
                            native_value=Decimal(value),
                            value_currency=native_currency,
                            native_cost_basis=Decimal(cost),
                            native_cost_currency=native_currency,
                            native_cost_basis_by_currency={native_currency: cost},
                            average_buy_price=Decimal(cost) / Decimal(2),
                            average_buy_price_currency=native_currency,
                        )
                    )
            await session.commit()
    finally:
        await engine.dispose()
    return user_id, account_id, snapshot_id


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


async def _assert_fixture_lineage(
    user_id: str, account_id: str, snapshot_id: str, account_type: AccountType
) -> None:
    prefix = account_id.removesuffix("-account")
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            snapshot = await session.get(AccountSnapshotModel, snapshot_id)
            assert snapshot is not None
            assert snapshot.generation_id == f"{prefix}-generation"
            generation = await session.get(SnapshotGenerationModel, snapshot.generation_id)
            assert generation is not None and generation.state == "published"
            target = await session.get(
                SnapshotGenerationTargetModel, (snapshot.generation_id, user_id)
            )
            assert target is not None
            state = await session.get(AccountCanonicalStateModel, account_id)
            boundary = await session.get(AccountSnapshotCanonicalBoundaryModel, snapshot_id)
            assert state is not None and boundary is not None
            assert boundary.account_id == account_id
            assert boundary.canonical_revision == state.last_revision
            transactions = tuple(
                await session.scalars(
                    select(TransactionModel).where(TransactionModel.account_id == account_id)
                )
            )
            balances = tuple(
                await session.scalars(
                    select(LiabilityBalanceModel).where(
                        LiabilityBalanceModel.account_id == account_id
                    )
                )
            )
            if account_type is AccountType.credit_card:
                assert len(transactions) == 1 and transactions[0].amount == Decimal("-25")
                assert not balances and boundary.selected_liability_balance_id is None
                assert snapshot.cash_value == Decimal("-25")
                assert snapshot.liabilities_value == 0
            elif account_type in {AccountType.loan, AccountType.mortgage}:
                assert not transactions and len(balances) == 1
                assert balances[0].total_outstanding == Decimal("25")
                assert boundary.selected_liability_balance_id == balances[0].id
                assert snapshot.cash_value == 0
                assert snapshot.liabilities_value == Decimal("25")
            else:
                assert not transactions and not balances
                assert boundary.selected_liability_balance_id is None
    finally:
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
                native_cost_basis_by_currency={
                    "USD" if item_suffix == "a" else "GBP": format(quantity_cost, ".10f")
                },
                average_buy_price=quantity_cost,
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
@pytest.mark.parametrize(
    "account_type",
    [AccountType.broker, AccountType.loan, AccountType.credit_card],
)
async def test_fixture_has_published_canonical_and_account_evidence(
    account_type: AccountType,
) -> None:
    prefix = _prefix(f"5lf-lineage-{account_type.value}")
    await _cleanup(prefix)
    try:
        user_id, account_id, snapshot_id = await _seed(prefix, account_type=account_type)
        await _assert_fixture_lineage(user_id, account_id, snapshot_id, account_type)

        response = _call(PORTFOLIO_PATH, user_id, _body((account_id,)))

        assert response.status_code == 200
        assert response.json()["accounts"][0]["snapshotId"] == snapshot_id
        if account_type is AccountType.credit_card:
            assert response.json()["summary"]["cashValue"] == "-25.000000"
            assert response.json()["summary"]["liabilitiesValue"] == "0.000000"
        elif account_type is AccountType.loan:
            assert response.json()["summary"]["cashValue"] == "0.000000"
            assert response.json()["summary"]["liabilitiesValue"] == "25.000000"
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
async def test_repeating_dashboard_percentage_uses_exact_largest_remainder() -> None:
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

        assert response.status_code == 200
        assert [position["allocationPct"] for position in response.json()["topPositions"]] == [
            "66.6667",
            "33.3333",
        ]
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
    original = PreloadedPortfolioSnapshotRepository.load_exact_snapshots

    async def duplicated(
        repository: PreloadedPortfolioSnapshotRepository,
        **kwargs: Any,
    ) -> tuple[AccountSnapshotModel, ...]:
        rows = await original(repository, **kwargs)
        assert len(rows) == 1
        return rows + rows

    monkeypatch.setattr(
        PreloadedPortfolioSnapshotRepository,
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
        assert sum('"accountmember"' in statement for statement in normalized) == 1
        for table in (
            '"account"',
            '"accountsnapshot"',
            '"accountsnapshotitem"',
            '"assetlisting"',
            '"asset"',
        ):
            assert any(table in statement for statement in normalized[isolation_index:])
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
