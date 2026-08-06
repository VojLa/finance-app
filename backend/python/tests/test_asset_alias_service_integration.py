from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountType,
    AssetAliasProvider,
    AssetType,
    PriceSource,
)
from app.db.models.holdings import HoldingModel
from app.db.url import normalize_database_url
from app.modules.asset_aliases.models import (
    AssetAliasConflictError,
    AssetAliasDatabaseUnavailableError,
    AssetAliasOnboardingDisposition,
    AssetAliasStateError,
    OnboardAssetAliasCommand,
)
from app.modules.asset_aliases.repository import AssetAliasWriterRepository
from app.modules.asset_aliases.service import (
    AssetAliasInventoryService,
    AssetAliasOnboardingService,
    AssetAliasWriter,
    asset_alias_id,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="PostgreSQL integration test requires DATABASE_URL.",
)
CREATED_AT = datetime(2026, 8, 5, 12, 30, 0, 123000)
TWELVE_ID = '{"symbol":"AAPL","mic_code":"XNAS"}'


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=12)


def _command(
    prefix: str,
    *,
    provider: AssetAliasProvider = AssetAliasProvider.coingecko,
    external_id: str = "bitcoin",
    created_at: datetime = CREATED_AT,
) -> OnboardAssetAliasCommand:
    twelve = provider is AssetAliasProvider.twelve_data
    return OnboardAssetAliasCommand(
        asset_id=f"{prefix}-asset-a",
        provider=provider,
        external_id=external_id,
        expected_symbol="AAPL" if twelve else "BTC",
        expected_asset_type=AssetType.stock if twelve else AssetType.crypto,
        expected_currency="USD" if twelve else "EUR",
        expected_isin="US0378331005" if twelve else None,
        created_at=created_at,
    )


async def _seed(prefix: str) -> None:
    await _cleanup(prefix)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add_all(
                (
                    AssetModel(
                        id=f"{prefix}-asset-a",
                        symbol="BTC",
                        isin=None,
                        name="Bitcoin",
                        asset_type=AssetType.crypto,
                        currency="EUR",
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                    AssetModel(
                        id=f"{prefix}-asset-b",
                        symbol="ETH",
                        isin=None,
                        name="Ethereum",
                        asset_type=AssetType.crypto,
                        currency="EUR",
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                    AssetModel(
                        id=f"{prefix}-asset-stock",
                        symbol="AAPL",
                        isin="US0378331005",
                        name="Apple",
                        asset_type=AssetType.stock,
                        currency="USD",
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            asset_ids = tuple(
                await session.scalars(
                    select(AssetModel.id).where(AssetModel.id.startswith(f"{prefix}-"))
                )
            )
            if asset_ids:
                await session.execute(
                    delete(AssetAliasModel).where(AssetAliasModel.asset_id.in_(asset_ids))
                )
                await session.execute(delete(AssetModel).where(AssetModel.id.in_(asset_ids)))
            await session.commit()
    finally:
        await engine.dispose()


async def _rows(prefix: str) -> tuple[AssetAliasModel, ...]:
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            rows = tuple(
                await session.scalars(
                    select(AssetAliasModel)
                    .where(AssetAliasModel.asset_id.startswith(f"{prefix}-"))
                    .order_by(AssetAliasModel.id)
                )
            )
            for row in rows:
                session.expunge(row)
            return rows
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("provider", "external_id"),
    [
        (AssetAliasProvider.coingecko, "bitcoin"),
        (AssetAliasProvider.twelve_data, TWELVE_ID),
    ],
)
@pytest.mark.asyncio
async def test_postgresql_create_and_replay_are_physically_exact(
    provider: AssetAliasProvider,
    external_id: str,
) -> None:
    prefix = f"r5b4-create-{provider.value}-{uuid4().hex[:10]}"
    await _seed(prefix)
    command = _command(prefix, provider=provider, external_id=external_id)
    if provider is AssetAliasProvider.twelve_data:
        command = OnboardAssetAliasCommand(
            asset_id=f"{prefix}-asset-stock",
            provider=provider,
            external_id=external_id,
            expected_symbol="AAPL",
            expected_asset_type=AssetType.stock,
            expected_currency="USD",
            expected_isin="US0378331005",
            created_at=CREATED_AT,
        )
    engine = _engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            service = AssetAliasOnboardingService(session)
            created = await service.onboard(command)
            assert not session.in_transaction()
            replayed = await service.onboard(replace(command, created_at=datetime(2026, 8, 5, 13)))
            assert not session.in_transaction()

        rows = await _rows(prefix)
        assert len(rows) == 1
        assert created.disposition is AssetAliasOnboardingDisposition.created
        assert replayed.disposition is AssetAliasOnboardingDisposition.replayed
        assert created.alias_id == replayed.alias_id == rows[0].id
        assert rows[0].id == asset_alias_id(command.asset_id, provider)
        assert rows[0].asset_id == command.asset_id
        assert rows[0].provider is provider
        assert rows[0].external_id == external_id
        assert rows[0].created_at == CREATED_AT
    finally:
        await engine.dispose()
        await _cleanup(prefix)


async def _execute_command(command: OnboardAssetAliasCommand) -> object:
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            return await AssetAliasOnboardingService(session).onboard(command)
    except Exception as exc:
        return exc
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_same_command_converges_to_one_physical_row() -> None:
    prefix = f"r5b4-concurrent-same-{uuid4().hex[:10]}"
    await _seed(prefix)
    try:
        first, second = await asyncio.gather(
            _execute_command(_command(prefix)),
            _execute_command(_command(prefix)),
        )

        dispositions = {
            getattr(first, "disposition", None),
            getattr(second, "disposition", None),
        }
        assert dispositions == {
            AssetAliasOnboardingDisposition.created,
            AssetAliasOnboardingDisposition.replayed,
        }
        assert len(await _rows(prefix)) == 1
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_concurrent_conflicting_commands_have_one_winner() -> None:
    prefix = f"r5b4-concurrent-conflict-{uuid4().hex[:10]}"
    await _seed(prefix)
    try:
        first, second = await asyncio.gather(
            _execute_command(_command(prefix, external_id=f"coin-a-{prefix}")),
            _execute_command(_command(prefix, external_id=f"coin-b-{prefix}")),
        )

        assert (
            sum(
                getattr(item, "disposition", None) is AssetAliasOnboardingDisposition.created
                for item in (first, second)
            )
            == 1
        )
        assert sum(isinstance(item, AssetAliasConflictError) for item in (first, second)) == 1
        assert len(await _rows(prefix)) == 1
    finally:
        await _cleanup(prefix)


@pytest.mark.parametrize(
    "state",
    [
        "external-owned",
        "different-same-asset",
        "multiple-same-asset",
        "deterministic-id-collision",
    ],
)
@pytest.mark.asyncio
async def test_existing_state_matrix_fails_without_repair(state: str) -> None:
    prefix = f"r5b4-state-{state}-{uuid4().hex[:8]}"
    await _seed(prefix)
    command = _command(prefix, external_id=f"requested-{prefix}")
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            rows: tuple[AssetAliasModel, ...]
            if state == "external-owned":
                rows = (
                    AssetAliasModel(
                        id=f"{prefix}-other-alias",
                        asset_id=f"{prefix}-asset-b",
                        provider=AssetAliasProvider.coingecko,
                        external_id=command.external_id,
                        created_at=CREATED_AT,
                    ),
                )
            elif state == "different-same-asset":
                rows = (
                    AssetAliasModel(
                        id=f"{prefix}-different",
                        asset_id=command.asset_id,
                        provider=command.provider,
                        external_id=f"different-{prefix}",
                        created_at=CREATED_AT,
                    ),
                )
            elif state == "multiple-same-asset":
                rows = (
                    AssetAliasModel(
                        id=f"{prefix}-one",
                        asset_id=command.asset_id,
                        provider=command.provider,
                        external_id=f"one-{prefix}",
                        created_at=CREATED_AT,
                    ),
                    AssetAliasModel(
                        id=f"{prefix}-two",
                        asset_id=command.asset_id,
                        provider=command.provider,
                        external_id=f"two-{prefix}",
                        created_at=CREATED_AT,
                    ),
                )
            else:
                rows = (
                    AssetAliasModel(
                        id=asset_alias_id(command.asset_id, command.provider),
                        asset_id=f"{prefix}-asset-b",
                        provider=command.provider,
                        external_id=f"collision-{prefix}",
                        created_at=CREATED_AT,
                    ),
                )
            session.add_all(rows)
            await session.commit()

        before = tuple((row.id, row.asset_id, row.external_id) for row in await _rows(prefix))
        async with AsyncSession(engine) as session:
            expected = (
                AssetAliasStateError if state == "multiple-same-asset" else AssetAliasConflictError
            )
            with pytest.raises(expected):
                await AssetAliasOnboardingService(session).onboard(command)
            assert not session.in_transaction()
        after = tuple((row.id, row.asset_id, row.external_id) for row in await _rows(prefix))
        assert after == before
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_historical_replay_rejects_foreign_deterministic_id_collision() -> None:
    prefix = f"r5b4-historical-id-collision-{uuid4().hex[:8]}"
    await _seed(prefix)
    command = _command(prefix, external_id=f"requested-{prefix}")
    historical_created_at = datetime(2025, 1, 1)
    collision_created_at = datetime(2025, 2, 1)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add_all(
                (
                    AssetAliasModel(
                        id=f"{prefix}-historical",
                        asset_id=command.asset_id,
                        provider=command.provider,
                        external_id=command.external_id,
                        created_at=historical_created_at,
                    ),
                    AssetAliasModel(
                        id=asset_alias_id(command.asset_id, command.provider),
                        asset_id=f"{prefix}-asset-b",
                        provider=command.provider,
                        external_id=f"collision-{prefix}",
                        created_at=collision_created_at,
                    ),
                )
            )
            await session.commit()

        before = tuple(
            (
                row.id,
                row.asset_id,
                row.provider,
                row.external_id,
                row.created_at,
            )
            for row in await _rows(prefix)
        )
        async with AsyncSession(engine) as session:
            with pytest.raises(AssetAliasConflictError):
                await AssetAliasOnboardingService(session).onboard(command)
            assert not session.in_transaction()
        after = tuple(
            (
                row.id,
                row.asset_id,
                row.provider,
                row.external_id,
                row.created_at,
            )
            for row in await _rows(prefix)
        )

        assert after == before
        assert len(after) == 2
    finally:
        await engine.dispose()
        await _cleanup(prefix)


class _ReloadFailureRepository(AssetAliasWriterRepository):
    async def reload_alias(self, alias_id: str) -> AssetAliasModel | None:
        return None


@pytest.mark.asyncio
async def test_reload_failure_rolls_back_insert_and_leaves_idle_session() -> None:
    prefix = f"r5b4-reload-{uuid4().hex[:10]}"
    await _seed(prefix)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            writer = AssetAliasWriter(
                session,
                repository=_ReloadFailureRepository(session),
            )
            with pytest.raises(AssetAliasStateError):
                await writer.write(_command(prefix))
            assert not session.in_transaction()
        assert await _rows(prefix) == ()
    finally:
        await engine.dispose()
        await _cleanup(prefix)


class _DriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("controlled")
        self.sqlstate = sqlstate


class _SqlStateError(SQLAlchemyError):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("controlled")
        self.orig = _DriverError(sqlstate)


class _FlushFailureRepository(AssetAliasWriterRepository):
    def __init__(self, session: AsyncSession, sqlstate: str) -> None:
        super().__init__(session)
        self.sqlstate = sqlstate
        self.flush_count = 0

    async def flush(self) -> None:
        self.flush_count += 1
        if self.flush_count == 1:
            raise _SqlStateError(self.sqlstate)
        await super().flush()


@pytest.mark.parametrize("sqlstate", ["40001", "40P01", "23505"])
@pytest.mark.asyncio
async def test_retryable_sqlstates_retry_complete_transaction(
    sqlstate: str,
) -> None:
    prefix = f"r5b4-retry-{sqlstate}-{uuid4().hex[:8]}"
    await _seed(prefix)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            repository = _FlushFailureRepository(session, sqlstate)
            result = await AssetAliasWriter(
                session,
                repository=repository,
            ).write(_command(prefix))
            assert result.disposition is AssetAliasOnboardingDisposition.created
            assert repository.flush_count == 2
            assert not session.in_transaction()
        assert len(await _rows(prefix)) == 1
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_nonretryable_sql_failure_rolls_back_without_retry() -> None:
    prefix = f"r5b4-nonretry-{uuid4().hex[:10]}"
    await _seed(prefix)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            repository = _FlushFailureRepository(session, "22003")
            with pytest.raises(AssetAliasDatabaseUnavailableError):
                await AssetAliasWriter(
                    session,
                    repository=repository,
                ).write(_command(prefix))
            assert repository.flush_count == 1
            assert not session.in_transaction()
        assert await _rows(prefix) == ()
        async with AsyncSession(engine) as session:
            version = str(await session.scalar(text("SHOW server_version")))
            count = await session.scalar(select(func.count()).select_from(AssetAliasModel))
            assert version.startswith("16.")
            assert isinstance(count, int)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_unresolved_inventory_filters_and_orders_physical_rows() -> None:
    prefix = f"r5b4-inventory-{uuid4().hex[:10]}"
    account_id = f"{prefix}-account"
    asset_specs = (
        ("crypto", "BTC", AssetType.crypto, Decimal("1")),
        ("stock", "AAPL", AssetType.stock, Decimal("2")),
        ("cash", "USD", AssetType.cash, Decimal("3")),
        ("zero", "ZERO", AssetType.crypto, Decimal("0")),
        ("resolved", "ETH", AssetType.crypto, Decimal("4")),
    )
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                AccountModel(
                    id=account_id,
                    name="R5 alias inventory",
                    type=AccountType.broker,
                    currency="CZK",
                    color=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=CREATED_AT,
                    updated_at=CREATED_AT,
                    notes=None,
                )
            )
            for suffix, symbol, asset_type, _quantity in asset_specs:
                session.add(
                    AssetModel(
                        id=f"{prefix}-asset-{suffix}",
                        symbol=symbol,
                        isin=None,
                        name=f"Inventory {suffix}",
                        asset_type=asset_type,
                        currency="USD",
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    )
                )
            await session.flush()

            for suffix, symbol, asset_type, quantity in asset_specs:
                listing_ids = (
                    (f"{prefix}-listing-stock-z", f"{prefix}-listing-stock-a")
                    if suffix == "stock"
                    else (f"{prefix}-listing-{suffix}",)
                )
                for index, listing_id in enumerate(listing_ids):
                    sort_index = 0 if listing_id.endswith("-a") else index + 1
                    session.add(
                        AssetListingModel(
                            id=listing_id,
                            asset_id=f"{prefix}-asset-{suffix}",
                            symbol=symbol,
                            exchange=f"{prefix}-exchange-{suffix}-{index}",
                            mic=None,
                            currency="USD",
                            country=None,
                            provider=PriceSource.broker,
                            provider_symbol=f"{symbol}-provider-{sort_index}",
                            is_primary=index == 0,
                            created_at=CREATED_AT,
                            updated_at=CREATED_AT,
                        )
                    )
                session.add(
                    HoldingModel(
                        id=f"{prefix}-holding-{suffix}",
                        symbol=symbol,
                        name=f"Inventory {suffix}",
                        asset_type=asset_type,
                        quantity=quantity,
                        avg_buy_price=Decimal("1"),
                        currency="USD",
                        current_price=None,
                        current_value=None,
                        unrealized_pnl=None,
                        realized_pnl=None,
                        asset_id=f"{prefix}-asset-{suffix}",
                        listing_id=listing_ids[0],
                        account_id=account_id,
                        calculated_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    )
                )
            session.add(
                AssetAliasModel(
                    id=f"{prefix}-resolved-alias",
                    asset_id=f"{prefix}-asset-resolved",
                    provider=AssetAliasProvider.coingecko,
                    external_id=f"resolved-{prefix}",
                    created_at=CREATED_AT,
                )
            )
            await session.commit()

        async with AsyncSession(engine) as session:
            coingecko = await AssetAliasInventoryService(session).list_unresolved(
                AssetAliasProvider.coingecko
            )
            twelve_data = await AssetAliasInventoryService(session).list_unresolved(
                AssetAliasProvider.twelve_data
            )
            assert not session.in_transaction()

        assert tuple(item.asset_id for item in coingecko) == (f"{prefix}-asset-crypto",)
        assert tuple(item.asset_id for item in twelve_data) == (f"{prefix}-asset-stock",)
        assert tuple(listing.listing_id for listing in twelve_data[0].listings) == (
            f"{prefix}-listing-stock-a",
            f"{prefix}-listing-stock-z",
        )
    finally:
        async with AsyncSession(engine) as session:
            await session.execute(
                delete(HoldingModel).where(HoldingModel.id.startswith(f"{prefix}-"))
            )
            await session.execute(
                delete(AssetAliasModel).where(AssetAliasModel.asset_id.startswith(f"{prefix}-"))
            )
            await session.execute(
                delete(AssetListingModel).where(AssetListingModel.asset_id.startswith(f"{prefix}-"))
            )
            await session.execute(delete(AssetModel).where(AssetModel.id.startswith(f"{prefix}-")))
            await session.execute(delete(AccountModel).where(AccountModel.id == account_id))
            await session.commit()
        await engine.dispose()
