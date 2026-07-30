from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountType,
    AssetType,
    PriceSource,
    SnapshotSource,
)
from app.db.models.enums import (
    SnapshotGranularity as DbSnapshotGranularity,
)
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.db.url import normalize_database_url
from app.modules.portfolio_snapshot.models import SnapshotGranularity
from app.modules.portfolio_snapshot.reader import (
    CompletePortfolioSnapshotRead,
    PortfolioSnapshotReader,
    PortfolioSnapshotReadError,
    ReadExactPortfolioSnapshotCommand,
)
from app.modules.portfolio_snapshot.repository import PortfolioSnapshotRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
SNAPSHOT_AT = datetime(2032, 8, 2)
CREATED_AT = datetime(2032, 8, 2, 0, 0, 0, 123000)


def _engine() -> AsyncEngine:
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=6)


@asynccontextmanager
async def _repeatable_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="REPEATABLE READ")
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            transaction = await session.begin()
            try:
                yield session
            finally:
                if transaction.is_active:
                    await transaction.rollback()


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        account_ids = tuple(
            await session.scalars(
                select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
            )
        )
        snapshot_ids = tuple(
            await session.scalars(
                select(AccountSnapshotModel.id).where(
                    AccountSnapshotModel.account_id.in_(account_ids)
                )
            )
        )
        listing_ids = tuple(
            await session.scalars(
                select(AssetListingModel.id).where(AssetListingModel.id.startswith(f"{prefix}-"))
            )
        )
        asset_ids = tuple(
            await session.scalars(
                select(AssetModel.id).where(AssetModel.id.startswith(f"{prefix}-"))
            )
        )
        if snapshot_ids:
            await session.execute(
                delete(AccountSnapshotItemModel).where(
                    AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids)
                )
            )
            await session.execute(
                delete(AccountSnapshotModel).where(AccountSnapshotModel.id.in_(snapshot_ids))
            )
        if account_ids:
            await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        if listing_ids:
            await session.execute(
                delete(AssetListingModel).where(AssetListingModel.id.in_(listing_ids))
            )
        if asset_ids:
            await session.execute(delete(AssetModel).where(AssetModel.id.in_(asset_ids)))
        await session.commit()
    await engine.dispose()


def _account(
    prefix: str,
    suffix: str = "account",
    *,
    account_type: AccountType = AccountType.broker,
) -> AccountModel:
    return AccountModel(
        id=f"{prefix}-{suffix}",
        name=f"{suffix} name",
        type=account_type,
        currency="CZK",
        color=None,
        is_archived=False,
        archived_at=None,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
        notes=None,
    )


def _snapshot(
    prefix: str,
    account: AccountModel,
    *,
    snapshot_suffix: str = "snapshot",
    timestamp: datetime = SNAPSHOT_AT,
    currency: str = "EUR",
    empty: bool = False,
) -> AccountSnapshotModel:
    liability = account.type in {
        AccountType.credit_card,
        AccountType.loan,
        AccountType.mortgage,
    }
    investment = Decimal(0) if liability or empty else Decimal("100")
    cost = Decimal(0) if liability or empty else Decimal("80")
    cash = Decimal(0) if liability else Decimal("10")
    liabilities = Decimal("25") if liability else Decimal(0)
    return AccountSnapshotModel(
        id=f"{prefix}-{snapshot_suffix}",
        account_id=account.id,
        timestamp=timestamp,
        granularity=DbSnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        currency=currency,
        cash_value=cash,
        investment_value=investment,
        investment_cost_basis=cost,
        liabilities_value=liabilities,
        total_value=cash + investment - liabilities,
        is_recalculated=True,
        calculated_at=CREATED_AT,
        calculation_version=1,
        created_at=CREATED_AT,
        net_deposits_value=Decimal(0),
        realized_pnl_value=Decimal(0),
        unrealized_pnl_value=investment - cost,
        fees_value=Decimal(0),
        taxes_value=Decimal(0),
        cash_value_by_currency=None,
        investment_value_by_currency=None,
        investment_cost_basis_by_currency=None,
        net_deposits_by_currency=None,
        realized_pnl_by_currency=None,
        unrealized_pnl_by_currency=None,
        fees_by_currency=None,
        taxes_by_currency=None,
        exchange_rates=None,
    )


def _asset_graph(
    prefix: str,
    suffix: str,
    *,
    symbol: str,
    currency: str,
    asset_type: AssetType,
) -> tuple[AssetModel, AssetListingModel]:
    asset = AssetModel(
        id=f"{prefix}-asset-{suffix}",
        symbol=symbol,
        isin=None,
        name=f"{symbol} asset",
        asset_type=asset_type,
        currency=currency,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
    )
    listing = AssetListingModel(
        id=f"{prefix}-listing-{suffix}",
        asset_id=asset.id,
        symbol=symbol,
        exchange=None,
        mic=None,
        currency=currency,
        country=None,
        provider=PriceSource.manual,
        provider_symbol=None,
        is_primary=True,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
    )
    return asset, listing


def _item(
    prefix: str,
    suffix: str,
    *,
    snapshot: AccountSnapshotModel,
    asset: AssetModel,
    listing: AssetListingModel,
    quantity: str,
    price: str,
    value: str,
    cost: str,
    allocation: str,
) -> AccountSnapshotItemModel:
    return AccountSnapshotItemModel(
        id=f"{prefix}-item-{suffix}",
        snapshot_id=snapshot.id,
        asset_id=asset.id,
        listing_id=listing.id,
        symbol=listing.symbol,
        quantity=Decimal(quantity),
        price_per_unit=Decimal(price),
        price_currency=listing.currency,
        price_source=PriceSource.manual,
        price_timestamp=snapshot.timestamp,
        value=Decimal(value),
        cost_basis=Decimal(cost),
        cost_currency=snapshot.currency,
        allocation_pct=Decimal(allocation),
        created_at=snapshot.created_at,
        native_value=Decimal(quantity) * Decimal(price),
        value_currency=listing.currency,
        native_cost_basis=Decimal(cost),
        native_cost_currency=listing.currency,
    )


def _command(
    account: AccountModel,
    *,
    timestamp: datetime = SNAPSHOT_AT,
    granularity: SnapshotGranularity = SnapshotGranularity.day,
    currency: str = "EUR",
    required_snapshot_id: str | None = None,
) -> ReadExactPortfolioSnapshotCommand:
    return ReadExactPortfolioSnapshotCommand(
        account_id=account.id,
        timestamp=timestamp,
        granularity=granularity,
        currency=currency,
        calculation_version=1,
        required_snapshot_id=required_snapshot_id,
    )


async def _seed(
    *,
    accounts: tuple[AccountModel, ...],
    snapshots: tuple[AccountSnapshotModel, ...],
    assets: tuple[AssetModel, ...] = (),
    listings: tuple[AssetListingModel, ...] = (),
    items: tuple[AccountSnapshotItemModel, ...] = (),
) -> None:
    engine = _engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add_all(accounts)
        session.add_all(assets)
        await session.flush()
        session.add_all(listings)
        await session.flush()
        session.add_all(snapshots)
        await session.flush()
        session.add_all(items)
        await session.commit()
    await engine.dispose()


async def _read(
    engine: AsyncEngine,
    command: ReadExactPortfolioSnapshotCommand,
    *,
    repository: PortfolioSnapshotRepository | None = None,
) -> CompletePortfolioSnapshotRead:
    async with _repeatable_session(engine) as session:
        return await PortfolioSnapshotReader(session, repository=repository).read(command)


async def _state(prefix: str) -> tuple[object, ...]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        accounts = tuple(
            (
                row.id,
                row.name,
                row.type,
                row.currency,
                row.is_archived,
                row.archived_at,
            )
            for row in await session.scalars(
                select(AccountModel)
                .where(AccountModel.id.startswith(f"{prefix}-"))
                .order_by(AccountModel.id)
            )
        )
        snapshots = tuple(
            (
                row.id,
                row.account_id,
                row.timestamp,
                row.currency,
                row.total_value,
                row.calculation_version,
            )
            for row in await session.scalars(
                select(AccountSnapshotModel)
                .where(AccountSnapshotModel.id.startswith(f"{prefix}-"))
                .order_by(AccountSnapshotModel.id)
            )
        )
        items = tuple(
            (
                row.id,
                row.snapshot_id,
                row.asset_id,
                row.listing_id,
                row.value,
                row.value_currency,
                row.cost_currency,
            )
            for row in await session.scalars(
                select(AccountSnapshotItemModel)
                .where(AccountSnapshotItemModel.id.startswith(f"{prefix}-"))
                .order_by(AccountSnapshotItemModel.id)
            )
        )
    await engine.dispose()
    return accounts, snapshots, items


async def _seed_broker(prefix: str) -> tuple[AccountModel, AccountSnapshotModel]:
    account = _account(prefix)
    snapshot = _snapshot(prefix, account)
    asset_a, listing_a = _asset_graph(
        prefix,
        "a",
        symbol="AAA",
        currency="USD",
        asset_type=AssetType.stock,
    )
    asset_b, listing_b = _asset_graph(
        prefix,
        "b",
        symbol="BBB",
        currency="GBP",
        asset_type=AssetType.crypto,
    )
    items = (
        _item(
            prefix,
            "a",
            snapshot=snapshot,
            asset=asset_a,
            listing=listing_a,
            quantity="2",
            price="30",
            value="60",
            cost="50",
            allocation="60",
        ),
        _item(
            prefix,
            "b",
            snapshot=snapshot,
            asset=asset_b,
            listing=listing_b,
            quantity="4",
            price="10",
            value="40",
            cost="30",
            allocation="40",
        ),
    )
    await _seed(
        accounts=(account,),
        snapshots=(snapshot,),
        assets=(asset_a, asset_b),
        listings=(listing_a, listing_b),
        items=items,
    )
    return account, snapshot


@pytest.mark.asyncio
async def test_exact_broker_maps_two_mixed_native_items_to_one_output_currency() -> None:
    prefix = "l5b-exact"
    await _cleanup(prefix)
    account, snapshot = await _seed_broker(prefix)
    before = await _state(prefix)
    engine = _engine()
    try:
        result = await _read(
            engine,
            _command(account, required_snapshot_id=snapshot.id),
        )
    finally:
        await engine.dispose()

    assert result.selected_snapshot_id == snapshot.id
    assert result.selected_item_ids == (f"{prefix}-item-a", f"{prefix}-item-b")
    assert result.view.currency == "EUR"
    assert {position.price_currency for position in result.view.positions} == {"USD", "GBP"}
    assert {position.native_value_currency for position in result.view.positions} == {
        "USD",
        "GBP",
    }
    assert {position.value_currency for position in result.view.positions} == {"EUR"}
    assert {position.cost_currency for position in result.view.positions} == {"EUR"}
    assert {position.unrealized_pnl for position in result.view.positions} == {Decimal("10")}
    assert await _state(prefix) == before
    await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("suffix", "account_type", "empty"),
    [
        ("liability", AccountType.loan, False),
        ("empty", AccountType.broker, True),
    ],
)
async def test_summary_only_and_empty_snapshot_shapes(
    suffix: str,
    account_type: AccountType,
    empty: bool,
) -> None:
    prefix = f"l5b-{suffix}"
    await _cleanup(prefix)
    account = _account(prefix, account_type=account_type)
    snapshot = _snapshot(prefix, account, empty=empty)
    await _seed(accounts=(account,), snapshots=(snapshot,))
    engine = _engine()
    try:
        result = await _read(engine, _command(account))
    finally:
        await engine.dispose()

    assert result.view.positions == ()
    assert result.selected_item_ids == ()
    assert result.view.summary.liabilities_value == (
        Decimal("25") if account_type is AccountType.loan else 0
    )
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_exact_selection_never_falls_back_across_timestamp_or_currency() -> None:
    prefix = "l5b-no-fallback"
    await _cleanup(prefix)
    account = _account(prefix)
    old = _snapshot(
        prefix,
        account,
        snapshot_suffix="old",
        timestamp=SNAPSHOT_AT,
        empty=True,
    )
    newer = _snapshot(
        prefix,
        account,
        snapshot_suffix="new",
        timestamp=SNAPSHOT_AT + timedelta(days=1),
        empty=True,
    )
    await _seed(accounts=(account,), snapshots=(old, newer))
    engine = _engine()
    try:
        for command in (
            _command(account, timestamp=SNAPSHOT_AT + timedelta(days=2)),
            _command(account, granularity=SnapshotGranularity.hour),
            _command(account, currency="USD"),
        ):
            with pytest.raises(PortfolioSnapshotReadError):
                await _read(engine, command)
        matched = await _read(
            engine,
            _command(account, required_snapshot_id=old.id),
        )
        assert matched.selected_snapshot_id == old.id
        with pytest.raises(PortfolioSnapshotReadError):
            await _read(
                engine,
                _command(account, required_snapshot_id=newer.id),
            )
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("suffix", "column", "value"),
    [
        ("nullable", "native_value", None),
        ("value-currency", "value_currency", "JPY"),
        ("cost-currency", "cost_currency", "CZK"),
        ("future-price", "price_timestamp", SNAPSHOT_AT + timedelta(days=1)),
    ],
)
async def test_corrupt_legacy_item_fields_fail_closed(
    suffix: str,
    column: str,
    value: object,
) -> None:
    prefix = f"l5b-corrupt-{suffix}"
    await _cleanup(prefix)
    account, _ = await _seed_broker(prefix)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            await session.execute(
                update(AccountSnapshotItemModel)
                .where(AccountSnapshotItemModel.id == f"{prefix}-item-a")
                .values({column: value})
            )
            await session.commit()
        before = await _state(prefix)
        with pytest.raises(PortfolioSnapshotReadError):
            await _read(engine, _command(account))
        assert await _state(prefix) == before
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_item_listing_asset_mismatch_and_missing_asset_name_fail_closed() -> None:
    prefix = "l5b-graph"
    await _cleanup(prefix)
    account, _ = await _seed_broker(prefix)
    engine = _engine()
    try:
        asset_b_id = f"{prefix}-asset-b"
        async with AsyncSession(engine) as session:
            await session.execute(
                update(AccountSnapshotItemModel)
                .where(AccountSnapshotItemModel.id == f"{prefix}-item-a")
                .values(asset_id=asset_b_id)
            )
            await session.commit()
        with pytest.raises(PortfolioSnapshotReadError):
            await _read(engine, _command(account))

        async with AsyncSession(engine) as session:
            await session.execute(
                update(AccountSnapshotItemModel)
                .where(AccountSnapshotItemModel.id == f"{prefix}-item-a")
                .values(asset_id=f"{prefix}-asset-a")
            )
            await session.execute(
                update(AssetModel).where(AssetModel.id == f"{prefix}-asset-a").values(name=None)
            )
            await session.commit()
        with pytest.raises(PortfolioSnapshotReadError):
            await _read(engine, _command(account))
    finally:
        await engine.dispose()
        await _cleanup(prefix)


class CrossSnapshotRepository(PortfolioSnapshotRepository):
    def __init__(self, session: AsyncSession, *, foreign_snapshot_id: str) -> None:
        super().__init__(session)
        self.foreign_snapshot_id = foreign_snapshot_id

    async def load_snapshot_items(self, snapshot_id: str):
        selected = await super().load_snapshot_items(snapshot_id)
        foreign = await super().load_snapshot_items(self.foreign_snapshot_id)
        return selected + foreign


@pytest.mark.asyncio
async def test_item_from_another_snapshot_and_account_is_rejected() -> None:
    prefix = "l5b-cross"
    await _cleanup(prefix)
    account_a = _account(prefix, "account-a")
    account_b = _account(prefix, "account-b")
    snapshot_a = _snapshot(prefix, account_a, snapshot_suffix="snapshot-a", empty=True)
    snapshot_b = _snapshot(prefix, account_b, snapshot_suffix="snapshot-b")
    asset, listing = _asset_graph(
        prefix,
        "foreign",
        symbol="FFF",
        currency="USD",
        asset_type=AssetType.stock,
    )
    foreign_item = _item(
        prefix,
        "foreign",
        snapshot=snapshot_b,
        asset=asset,
        listing=listing,
        quantity="1",
        price="100",
        value="100",
        cost="80",
        allocation="100",
    )
    await _seed(
        accounts=(account_a, account_b),
        snapshots=(snapshot_a, snapshot_b),
        assets=(asset,),
        listings=(listing,),
        items=(foreign_item,),
    )
    engine = _engine()
    try:
        async with _repeatable_session(engine) as session:
            repository = CrossSnapshotRepository(
                session,
                foreign_snapshot_id=snapshot_b.id,
            )
            with pytest.raises(PortfolioSnapshotReadError):
                await PortfolioSnapshotReader(session, repository=repository).read(
                    _command(account_a)
                )
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_reader_is_read_only_lock_free_and_leaves_caller_transaction_open() -> None:
    prefix = "l5b-readonly"
    await _cleanup(prefix)
    account, _ = await _seed_broker(prefix)
    before = await _state(prefix)
    engine = _engine()
    statements: list[str] = []

    def capture(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="REPEATABLE READ")
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                transaction = await session.begin()
                await PortfolioSnapshotReader(session).read(_command(account))
                assert session.in_transaction()
                await transaction.rollback()
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        await engine.dispose()

    sql = "\n".join(statements).upper()
    assert "FOR UPDATE" not in sql
    assert "PG_ADVISORY" not in sql
    assert not any(
        statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in statements
    )
    assert await _state(prefix) == before
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_reader_rejects_read_committed_caller_transaction() -> None:
    prefix = "l5b-isolation"
    await _cleanup(prefix)
    account = _account(prefix)
    snapshot = _snapshot(prefix, account, empty=True)
    await _seed(accounts=(account,), snapshots=(snapshot,))
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            transaction = await session.begin()
            with pytest.raises(PortfolioSnapshotReadError):
                await PortfolioSnapshotReader(session).read(_command(account))
            assert transaction.is_active
            await transaction.rollback()
    finally:
        await engine.dispose()
        await _cleanup(prefix)


class PausingPortfolioSnapshotRepository(PortfolioSnapshotRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        account_loaded: asyncio.Event,
        resume: asyncio.Event,
    ) -> None:
        super().__init__(session)
        self.account_loaded = account_loaded
        self.resume = resume

    async def load_account(self, account_id: str):
        account = await super().load_account(account_id)
        self.account_loaded.set()
        await self.resume.wait()
        return account


@pytest.mark.asyncio
async def test_repeatable_read_keeps_account_metadata_coherent_during_concurrent_update() -> None:
    prefix = "l5b-coherent"
    await _cleanup(prefix)
    account = _account(prefix)
    snapshot = _snapshot(prefix, account, empty=True)
    await _seed(accounts=(account,), snapshots=(snapshot,))
    engine = _engine()
    account_loaded = asyncio.Event()
    resume = asyncio.Event()
    try:
        async with engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="REPEATABLE READ")
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                transaction = await session.begin()
                repository = PausingPortfolioSnapshotRepository(
                    session,
                    account_loaded=account_loaded,
                    resume=resume,
                )
                task = asyncio.create_task(
                    PortfolioSnapshotReader(session, repository=repository).read(_command(account))
                )
                await asyncio.wait_for(account_loaded.wait(), timeout=5)

                async with AsyncSession(engine) as writer:
                    await writer.execute(
                        update(AccountModel)
                        .where(AccountModel.id == account.id)
                        .values(name="changed name")
                    )
                    await writer.commit()

                resume.set()
                old_view = await asyncio.wait_for(task, timeout=5)
                await transaction.rollback()

        assert old_view.view.account.name == "account name"
        new_view = await _read(engine, _command(account))
        assert new_view.view.account.name == "changed name"
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_exact_account_scope_does_not_leak_another_accounts_snapshot() -> None:
    prefix = "l5b-scope"
    await _cleanup(prefix)
    account_a = _account(prefix, "account-a")
    account_b = _account(prefix, "account-b")
    snapshot_a = _snapshot(prefix, account_a, snapshot_suffix="snapshot-a", empty=True)
    snapshot_b = _snapshot(prefix, account_b, snapshot_suffix="snapshot-b", empty=True)
    await _seed(accounts=(account_a, account_b), snapshots=(snapshot_a, snapshot_b))
    engine = _engine()
    try:
        result = await _read(engine, _command(account_a))
    finally:
        await engine.dispose()

    assert result.view.account.account_id == account_a.id
    assert result.selected_snapshot_id == snapshot_a.id
    assert account_b.id not in repr(result)
    assert snapshot_b.id not in repr(result)
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_repository_uses_one_explicit_item_listing_asset_join() -> None:
    prefix = "l5b-query"
    await _cleanup(prefix)
    account, _ = await _seed_broker(prefix)
    engine = _engine()
    item_selects: list[str] = []

    def capture(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        upper = statement.upper()
        if upper.lstrip().startswith("SELECT") and '"ACCOUNTSNAPSHOTITEM"' in upper:
            item_selects.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        await _read(engine, _command(account))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        await engine.dispose()

    assert len(item_selects) == 1
    statement = item_selects[0]
    assert '"AssetListing"' in statement
    assert '"Asset"' in statement
    assert "ORDER BY" in statement
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_reader_does_not_create_rows_or_change_counts() -> None:
    prefix = "l5b-counts"
    await _cleanup(prefix)
    account, _ = await _seed_broker(prefix)
    engine = _engine()
    try:
        before = await _state(prefix)
        await _read(engine, _command(account))
        after = await _state(prefix)
        async with AsyncSession(engine) as session:
            counts = (
                await session.scalar(
                    select(func.count())
                    .select_from(AccountSnapshotModel)
                    .where(AccountSnapshotModel.account_id == account.id)
                ),
                await session.scalar(
                    select(func.count())
                    .select_from(AccountSnapshotItemModel)
                    .where(AccountSnapshotItemModel.id.startswith(f"{prefix}-"))
                ),
            )
    finally:
        await engine.dispose()

    assert after == before
    assert counts == (1, 2)
    await _cleanup(prefix)
