from __future__ import annotations

import asyncio
import os
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountType,
    AssetType,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.url import normalize_database_url
from app.modules.holdings.projection import HoldingProjectionStateError
from app.modules.holdings.rebuild_service import (
    HoldingRebuildService,
    HoldingRebuildStateError,
    stable_holding_id,
)
from app.modules.holdings.repository import advisory_lock_id

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
NOW = datetime(2026, 7, 27, 10, 0, 0, 123000)
LATER = datetime(2026, 7, 28, 10, 0, 0, 123000)


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=8)


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    account_ids = [f"{prefix}-account", f"{prefix}-other-account"]
    async with AsyncSession(engine) as session:
        await session.execute(delete(HoldingModel).where(HoldingModel.account_id.in_(account_ids)))
        await session.execute(
            delete(InvestmentMovementModel).where(
                InvestmentMovementModel.account_id.in_(account_ids)
            )
        )
        await session.execute(
            delete(InvestmentEventModel).where(InvestmentEventModel.account_id.in_(account_ids))
        )
        await session.execute(
            delete(AssetListingModel).where(AssetListingModel.id.startswith(f"{prefix}-listing"))
        )
        await session.execute(delete(AssetModel).where(AssetModel.id.startswith(f"{prefix}-asset")))
        await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        await session.commit()
    await engine.dispose()


async def _seed_account(prefix: str, *, other: bool = False) -> str:
    account_id = f"{prefix}-{'other-' if other else ''}account"
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            AccountModel(
                id=account_id,
                name=account_id,
                type=AccountType.broker,
                currency="EUR",
                color=None,
                notes=None,
                is_archived=False,
                archived_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.commit()
    await engine.dispose()
    return account_id


async def _seed_asset(
    prefix: str,
    *,
    suffix: str = "",
    symbol: str = "VWCE",
) -> tuple[str, str]:
    asset_id = f"{prefix}-asset{suffix}"
    listing_id = f"{prefix}-listing{suffix}"
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            AssetModel(
                id=asset_id,
                symbol=symbol,
                isin=f"ISIN-{asset_id}",
                name=symbol,
                asset_type=AssetType.etf,
                currency="EUR",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add(
            AssetListingModel(
                id=listing_id,
                asset_id=asset_id,
                symbol=symbol,
                exchange=f"trading212-{prefix}",
                mic=None,
                currency="EUR",
                country=None,
                provider=PriceSource.broker,
                provider_symbol=f"{prefix}{suffix}",
                is_primary=False,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.commit()
    await engine.dispose()
    return asset_id, listing_id


async def _add_trade(
    prefix: str,
    *,
    event_suffix: str,
    asset_id: str,
    listing_id: str,
    symbol: str,
    direction: MovementDirection,
    quantity: str,
    price: str,
    date: datetime,
    account_id: str | None = None,
    cost_currency: str = "EUR",
) -> str:
    canonical_account_id = account_id or f"{prefix}-account"
    event_id = f"{prefix}-{event_suffix}"
    quantity_value = Decimal(quantity)
    price_value = Decimal(price)
    total = quantity_value * price_value
    cash_direction = (
        MovementDirection.outgoing
        if direction is MovementDirection.incoming
        else MovementDirection.incoming
    )
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            InvestmentEventModel(
                id=event_id,
                account_id=canonical_account_id,
                type=InvestmentEventType.trade,
                date=date,
                source=ImportSource.trading212,
                external_id=event_id,
                order_id=None,
                description=symbol,
                realized_pnl=None,
                realized_pnl_currency=None,
                import_batch_id=None,
                archived_at=None,
                deleted_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add_all(
            [
                InvestmentMovementModel(
                    id=f"{event_id}-asset",
                    event_id=event_id,
                    account_id=canonical_account_id,
                    asset_id=asset_id,
                    listing_id=listing_id,
                    kind=InvestmentMovementKind.asset,
                    direction=direction,
                    quantity=quantity_value,
                    currency=symbol,
                    price_per_unit=price_value,
                    value_amount=total,
                    value_currency=cost_currency,
                    source_symbol=symbol,
                    source_asset_type=AssetType.etf,
                    note=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
                InvestmentMovementModel(
                    id=f"{event_id}-cash",
                    event_id=event_id,
                    account_id=canonical_account_id,
                    asset_id=None,
                    listing_id=None,
                    kind=InvestmentMovementKind.cash,
                    direction=cash_direction,
                    quantity=total,
                    currency=cost_currency,
                    price_per_unit=None,
                    value_amount=total,
                    value_currency=cost_currency,
                    source_symbol=None,
                    source_asset_type=None,
                    note=None,
                    created_at=NOW,
                    updated_at=NOW,
                ),
            ]
        )
        await session.commit()
    await engine.dispose()
    return event_id


async def _add_cash_event(prefix: str, *, account_id: str | None = None) -> None:
    canonical_account_id = account_id or f"{prefix}-account"
    event_id = f"{prefix}-cash-only"
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            InvestmentEventModel(
                id=event_id,
                account_id=canonical_account_id,
                type=InvestmentEventType.interest,
                date=NOW,
                source=ImportSource.trading212,
                external_id=event_id,
                order_id=None,
                description=None,
                realized_pnl=None,
                realized_pnl_currency=None,
                import_batch_id=None,
                archived_at=None,
                deleted_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            InvestmentMovementModel(
                id=f"{event_id}-cash",
                event_id=event_id,
                account_id=canonical_account_id,
                asset_id=None,
                listing_id=None,
                kind=InvestmentMovementKind.cash,
                direction=MovementDirection.incoming,
                quantity=Decimal("5"),
                currency="EUR",
                price_per_unit=None,
                value_amount=Decimal("5"),
                value_currency="EUR",
                source_symbol=None,
                source_asset_type=None,
                note=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.commit()
    await engine.dispose()


async def _add_incoming_transfer(
    prefix: str,
    *,
    asset_id: str,
    listing_id: str,
    symbol: str,
) -> None:
    account_id = f"{prefix}-account"
    event_id = f"{prefix}-incoming-transfer"
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            InvestmentEventModel(
                id=event_id,
                account_id=account_id,
                type=InvestmentEventType.asset_transfer,
                date=datetime(2026, 7, 30),
                source=ImportSource.anycoin,
                external_id=event_id,
                order_id=None,
                description=symbol,
                realized_pnl=None,
                realized_pnl_currency=None,
                import_batch_id=None,
                archived_at=None,
                deleted_at=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            InvestmentMovementModel(
                id=f"{event_id}-asset",
                event_id=event_id,
                account_id=account_id,
                asset_id=asset_id,
                listing_id=listing_id,
                kind=InvestmentMovementKind.asset,
                direction=MovementDirection.incoming,
                quantity=Decimal("1"),
                currency=symbol,
                price_per_unit=None,
                value_amount=None,
                value_currency=None,
                source_symbol=symbol,
                source_asset_type=AssetType.etf,
                note=None,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.commit()
    await engine.dispose()


async def _holdings(account_id: str) -> list[HoldingModel]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        rows = list(
            (
                await session.scalars(
                    select(HoldingModel)
                    .where(HoldingModel.account_id == account_id)
                    .order_by(HoldingModel.listing_id)
                )
            ).all()
        )
        for row in rows:
            session.expunge(row)
    await engine.dispose()
    return rows


async def _rebuild(account_id: str, rebuilt_at: datetime = NOW):
    engine = _engine()
    async with AsyncSession(engine) as session:
        result = await HoldingRebuildService(session).rebuild(
            account_id=account_id,
            rebuilt_at=rebuilt_at,
        )
        await session.commit()
    await engine.dispose()
    return result


async def _seed_holding(
    *,
    account_id: str,
    holding_id: str,
    asset_id: str,
    listing_id: str,
    symbol: str,
    quantity: str,
    average: str,
    current_price: Decimal | None = None,
) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            HoldingModel(
                id=holding_id,
                account_id=account_id,
                asset_id=asset_id,
                listing_id=listing_id,
                symbol=symbol,
                name="stale",
                asset_type=AssetType.etf,
                quantity=Decimal(quantity),
                avg_buy_price=Decimal(average),
                currency="EUR",
                current_price=current_price,
                current_value=None,
                unrealized_pnl=None,
                realized_pnl=None,
                calculated_at=NOW,
                updated_at=NOW,
            )
        )
        await session.commit()
    await engine.dispose()


async def test_empty_history_replays_and_deletes_valid_stale_holding() -> None:
    prefix = "h5c-empty"
    await _cleanup(prefix)
    account_id = await _seed_account(prefix)
    empty = await _rebuild(account_id)
    assert empty.replayed is True
    assert empty.total == 0

    asset_id, listing_id = await _seed_asset(prefix)
    await _seed_holding(
        account_id=account_id,
        holding_id="stale",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        quantity="1",
        average="100",
    )
    deleted = await _rebuild(account_id, LATER)
    assert (deleted.created, deleted.updated, deleted.deleted, deleted.total) == (0, 0, 1, 0)
    assert await _holdings(account_id) == []
    await _cleanup(prefix)


async def test_buy_weighted_average_partial_sale_replay_and_stable_id() -> None:
    prefix = "h5c-trades"
    await _cleanup(prefix)
    account_id = await _seed_account(prefix)
    asset_id, listing_id = await _seed_asset(prefix)
    await _add_trade(
        prefix,
        event_suffix="buy-a",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        direction=MovementDirection.incoming,
        quantity="2",
        price="100",
        date=NOW,
    )
    first = await _rebuild(account_id)
    row = (await _holdings(account_id))[0]
    assert first.created == 1
    assert row.id == stable_holding_id(account_id, listing_id)
    assert row.quantity == Decimal("2")
    original_timestamps = (row.calculated_at, row.updated_at)

    replay = await _rebuild(account_id, LATER)
    replay_row = (await _holdings(account_id))[0]
    assert replay.replayed is True
    assert replay.rebuilt_at is None
    assert (replay_row.calculated_at, replay_row.updated_at) == original_timestamps

    await _add_trade(
        prefix,
        event_suffix="buy-b",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        direction=MovementDirection.incoming,
        quantity="2",
        price="200",
        date=datetime(2026, 7, 28),
    )
    await _add_trade(
        prefix,
        event_suffix="sell",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        direction=MovementDirection.outgoing,
        quantity="1",
        price="300",
        date=datetime(2026, 7, 29),
    )
    updated = await _rebuild(account_id, LATER)
    updated_row = (await _holdings(account_id))[0]
    assert updated.updated == 1
    assert updated_row.id == row.id
    assert updated_row.quantity == Decimal("3")
    assert updated_row.avg_buy_price == Decimal("150")
    assert updated_row.name is None
    assert updated_row.current_price is None
    await _cleanup(prefix)


async def test_full_sale_deletes_and_later_recreation_uses_same_id() -> None:
    prefix = "h5c-recreate"
    await _cleanup(prefix)
    account_id = await _seed_account(prefix)
    asset_id, listing_id = await _seed_asset(prefix)
    await _add_trade(
        prefix,
        event_suffix="buy",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        direction=MovementDirection.incoming,
        quantity="1",
        price="100",
        date=NOW,
    )
    await _rebuild(account_id)
    holding_id = (await _holdings(account_id))[0].id
    await _add_trade(
        prefix,
        event_suffix="sell",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        direction=MovementDirection.outgoing,
        quantity="1",
        price="110",
        date=datetime(2026, 7, 28),
    )
    assert (await _rebuild(account_id, LATER)).deleted == 1
    await _add_trade(
        prefix,
        event_suffix="buy-again",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        direction=MovementDirection.incoming,
        quantity="1",
        price="120",
        date=datetime(2026, 7, 29),
    )
    assert (await _rebuild(account_id, datetime(2026, 7, 30))).created == 1
    assert (await _holdings(account_id))[0].id == holding_id
    await _cleanup(prefix)


async def test_multiple_listings_remain_separate_and_cash_history_creates_none() -> None:
    prefix = "h5c-multiple"
    await _cleanup(prefix)
    account_id = await _seed_account(prefix)
    first_asset, first_listing = await _seed_asset(prefix)
    second_asset, second_listing = await _seed_asset(prefix, suffix="-b", symbol="EUNL")
    await _add_cash_event(prefix)
    await _add_trade(
        prefix,
        event_suffix="first",
        asset_id=first_asset,
        listing_id=first_listing,
        symbol="VWCE",
        direction=MovementDirection.incoming,
        quantity="1",
        price="100",
        date=datetime(2026, 7, 28),
    )
    await _add_trade(
        prefix,
        event_suffix="second",
        asset_id=second_asset,
        listing_id=second_listing,
        symbol="EUNL",
        direction=MovementDirection.incoming,
        quantity="2",
        price="50",
        date=datetime(2026, 7, 29),
    )
    result = await _rebuild(account_id)
    assert result.created == 2
    assert [row.listing_id for row in await _holdings(account_id)] == [
        first_listing,
        second_listing,
    ]
    await _cleanup(prefix)


async def test_relation_corruption_and_unsupported_history_leave_holding_unchanged() -> None:
    prefix = "h5c-corrupt"
    await _cleanup(prefix)
    account_id = await _seed_account(prefix)
    asset_id, listing_id = await _seed_asset(prefix)
    other_asset, _ = await _seed_asset(prefix, suffix="-b", symbol="EUNL")
    await _seed_holding(
        account_id=account_id,
        holding_id="preserved",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        quantity="1",
        average="100",
    )
    await _add_trade(
        prefix,
        event_suffix="corrupt",
        asset_id=other_asset,
        listing_id=listing_id,
        symbol="VWCE",
        direction=MovementDirection.incoming,
        quantity="1",
        price="100",
        date=NOW,
    )
    before = (await _holdings(account_id))[0]
    engine = _engine()
    async with AsyncSession(engine) as session:
        with pytest.raises(HoldingRebuildStateError):
            await HoldingRebuildService(session).rebuild(account_id=account_id, rebuilt_at=LATER)
        await session.rollback()
    await engine.dispose()
    after = (await _holdings(account_id))[0]
    assert (after.id, after.quantity, after.updated_at) == (
        before.id,
        before.quantity,
        before.updated_at,
    )
    await _cleanup(prefix)


async def test_cross_account_event_movement_relation_fails_closed() -> None:
    prefix = "h5c-cross-account"
    await _cleanup(prefix)
    account_id = await _seed_account(prefix)
    other_account_id = await _seed_account(prefix, other=True)
    asset_id, listing_id = await _seed_asset(prefix)
    event_id = await _add_trade(
        prefix,
        event_suffix="foreign-event",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        direction=MovementDirection.incoming,
        quantity="1",
        price="100",
        date=NOW,
        account_id=other_account_id,
    )
    engine = _engine()
    async with AsyncSession(engine) as session:
        movement = await session.get(InvestmentMovementModel, f"{event_id}-asset")
        assert movement is not None
        movement.account_id = account_id
        await session.commit()
    async with AsyncSession(engine) as session:
        with pytest.raises(HoldingRebuildStateError):
            await HoldingRebuildService(session).rebuild(
                account_id=account_id,
                rebuilt_at=LATER,
            )
        await session.rollback()
    await engine.dispose()
    assert await _holdings(account_id) == []
    await _cleanup(prefix)


async def test_mixed_currency_projection_failure_preserves_existing_holding() -> None:
    prefix = "h5c-currency"
    await _cleanup(prefix)
    account_id = await _seed_account(prefix)
    asset_id, listing_id = await _seed_asset(prefix)
    for suffix, currency, date in (
        ("eur", "EUR", NOW),
        ("usd", "USD", datetime(2026, 7, 28)),
    ):
        await _add_trade(
            prefix,
            event_suffix=suffix,
            asset_id=asset_id,
            listing_id=listing_id,
            symbol="VWCE",
            direction=MovementDirection.incoming,
            quantity="1",
            price="100",
            date=date,
            cost_currency=currency,
        )
    engine = _engine()
    async with AsyncSession(engine) as session:
        with pytest.raises(HoldingProjectionStateError):
            await HoldingRebuildService(session).rebuild(account_id=account_id, rebuilt_at=NOW)
        await session.rollback()
    await engine.dispose()
    assert await _holdings(account_id) == []
    await _cleanup(prefix)


async def test_unknown_basis_incoming_transfer_preserves_previous_projection() -> None:
    prefix = "h5c-transfer"
    await _cleanup(prefix)
    account_id = await _seed_account(prefix)
    asset_id, listing_id = await _seed_asset(prefix)
    await _add_trade(
        prefix,
        event_suffix="buy",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        direction=MovementDirection.incoming,
        quantity="1",
        price="100",
        date=NOW,
    )
    await _rebuild(account_id)
    before = (await _holdings(account_id))[0]
    await _add_incoming_transfer(
        prefix,
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
    )
    engine = _engine()
    async with AsyncSession(engine) as session:
        with pytest.raises(HoldingProjectionStateError):
            await HoldingRebuildService(session).rebuild(account_id=account_id, rebuilt_at=LATER)
        await session.rollback()
    await engine.dispose()
    after = (await _holdings(account_id))[0]
    assert (after.id, after.quantity, after.updated_at) == (
        before.id,
        before.quantity,
        before.updated_at,
    )
    await _cleanup(prefix)


async def test_malformed_current_holding_is_not_deleted_or_repaired() -> None:
    prefix = "h5c-malformed"
    await _cleanup(prefix)
    account_id = await _seed_account(prefix)
    asset_id, listing_id = await _seed_asset(prefix)
    await _seed_holding(
        account_id=account_id,
        holding_id="malformed",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        quantity="1",
        average="100",
    )
    engine = _engine()
    async with AsyncSession(engine) as session:
        holding = await session.get(HoldingModel, "malformed")
        assert holding is not None
        holding.currency = "eur"
        await session.commit()
    async with AsyncSession(engine) as session:
        with pytest.raises(HoldingRebuildStateError):
            await HoldingRebuildService(session).rebuild(account_id=account_id, rebuilt_at=LATER)
        await session.rollback()
    await engine.dispose()
    rows = await _holdings(account_id)
    assert len(rows) == 1
    assert rows[0].currency == "eur"
    await _cleanup(prefix)


async def test_flush_failure_rolls_back_create_update_delete_and_clean_retry_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = "h5c-rollback"
    await _cleanup(prefix)
    account_id = await _seed_account(prefix)
    asset_id, listing_id = await _seed_asset(prefix)
    second_asset, second_listing = await _seed_asset(prefix, suffix="-b", symbol="EUNL")
    stale_asset, stale_listing = await _seed_asset(prefix, suffix="-stale", symbol="STALE")
    await _add_trade(
        prefix,
        event_suffix="update",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        direction=MovementDirection.incoming,
        quantity="2",
        price="100",
        date=NOW,
    )
    await _add_trade(
        prefix,
        event_suffix="create",
        asset_id=second_asset,
        listing_id=second_listing,
        symbol="EUNL",
        direction=MovementDirection.incoming,
        quantity="1",
        price="50",
        date=datetime(2026, 7, 28),
    )
    await _seed_holding(
        account_id=account_id,
        holding_id="update-id",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        quantity="1",
        average="90",
    )
    await _seed_holding(
        account_id=account_id,
        holding_id="delete-id",
        asset_id=stale_asset,
        listing_id=stale_listing,
        symbol="STALE",
        quantity="1",
        average="10",
    )
    before = [(row.id, row.quantity, row.avg_buy_price) for row in await _holdings(account_id)]
    engine = _engine()
    async with AsyncSession(engine) as session:
        service = HoldingRebuildService(session)
        original_flush = service.repository.flush

        async def fail_after_flush() -> None:
            await original_flush()
            raise RuntimeError("controlled flush failure")

        monkeypatch.setattr(service.repository, "flush", fail_after_flush)
        with pytest.raises(RuntimeError, match="controlled flush failure"):
            await service.rebuild(account_id=account_id, rebuilt_at=LATER)
        await session.rollback()
    await engine.dispose()
    assert [
        (row.id, row.quantity, row.avg_buy_price) for row in await _holdings(account_id)
    ] == before

    retry = await _rebuild(account_id, LATER)
    assert (retry.created, retry.updated, retry.deleted) == (1, 1, 1)
    assert len(await _holdings(account_id)) == 2
    await _cleanup(prefix)


async def _wait_for_advisory_wait(engine: Any, pid: int) -> None:
    for _ in range(100):
        async with AsyncSession(engine) as inspector:
            waiting = await inspector.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks "
                    "WHERE pid = :pid AND locktype = 'advisory' AND NOT granted)"
                ),
                {"pid": pid},
            )
        if waiting:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("PostgreSQL backend did not wait on an advisory lock")


async def test_same_account_rebuilds_serialize_and_second_is_replay() -> None:
    prefix = "h5c-concurrent"
    await _cleanup(prefix)
    account_id = await _seed_account(prefix)
    asset_id, listing_id = await _seed_asset(prefix)
    await _add_trade(
        prefix,
        event_suffix="buy",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        direction=MovementDirection.incoming,
        quantity="1",
        price="100",
        date=NOW,
    )
    engine = _engine()
    first_ready = asyncio.Event()
    release = asyncio.Event()
    second_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def first() -> Any:
        async with AsyncSession(engine) as session:
            result = await HoldingRebuildService(session).rebuild(
                account_id=account_id, rebuilt_at=NOW
            )
            first_ready.set()
            await release.wait()
            await session.commit()
            return result

    async def second() -> Any:
        await first_ready.wait()
        async with AsyncSession(engine) as session:
            second_pid.set_result(int(await session.scalar(text("SELECT pg_backend_pid()"))))
            result = await HoldingRebuildService(session).rebuild(
                account_id=account_id, rebuilt_at=LATER
            )
            await session.commit()
            return result

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    pid = await asyncio.wait_for(second_pid, timeout=5)
    await _wait_for_advisory_wait(engine, pid)
    release.set()
    first_result, second_result = await asyncio.wait_for(
        asyncio.gather(first_task, second_task), timeout=10
    )
    assert first_result.created == 1
    assert second_result.replayed is True
    assert len(await _holdings(account_id)) == 1
    await engine.dispose()
    await _cleanup(prefix)


async def test_different_accounts_do_not_share_rebuild_lock() -> None:
    prefix = "h5c-independent"
    await _cleanup(prefix)
    first_account = await _seed_account(prefix)
    second_account = await _seed_account(prefix, other=True)
    engine = _engine()
    async with AsyncSession(engine) as first_session:
        await HoldingRebuildService(first_session).rebuild(account_id=first_account, rebuilt_at=NOW)
        async with AsyncSession(engine) as second_session:
            second = await asyncio.wait_for(
                HoldingRebuildService(second_session).rebuild(
                    account_id=second_account, rebuilt_at=NOW
                ),
                timeout=2,
            )
            assert second.replayed is True
            await second_session.commit()
        await first_session.rollback()
    await engine.dispose()
    await _cleanup(prefix)


async def test_lock_holder_rollback_allows_waiter_to_create_exact_projection() -> None:
    prefix = "h5c-lock-rollback"
    await _cleanup(prefix)
    account_id = await _seed_account(prefix)
    asset_id, listing_id = await _seed_asset(prefix)
    await _add_trade(
        prefix,
        event_suffix="buy",
        asset_id=asset_id,
        listing_id=listing_id,
        symbol="VWCE",
        direction=MovementDirection.incoming,
        quantity="1",
        price="100",
        date=NOW,
    )
    engine = _engine()
    async with AsyncSession(engine) as holder:
        await HoldingRebuildService(holder).rebuild(account_id=account_id, rebuilt_at=NOW)
        async with AsyncSession(engine) as waiter:
            pid = int(await waiter.scalar(text("SELECT pg_backend_pid()")))
            task = asyncio.create_task(
                HoldingRebuildService(waiter).rebuild(account_id=account_id, rebuilt_at=LATER)
            )
            await _wait_for_advisory_wait(engine, pid)
            await holder.rollback()
            result = await asyncio.wait_for(task, timeout=10)
            await waiter.commit()
    assert result.created == 1
    assert len(await _holdings(account_id)) == 1
    await engine.dispose()
    await _cleanup(prefix)


async def test_rebuild_waits_for_canonical_import_source_lock() -> None:
    prefix = "h5c-history-lock"
    await _cleanup(prefix)
    account_id = await _seed_account(prefix)
    engine = _engine()
    scope = f"imports:deduplication:{account_id}:{ImportSource.trading212.value}"
    async with AsyncSession(engine) as posting:
        await posting.execute(select(func.pg_advisory_xact_lock(advisory_lock_id(scope))))
        async with AsyncSession(engine) as rebuilding:
            pid = int(await rebuilding.scalar(text("SELECT pg_backend_pid()")))
            task = asyncio.create_task(
                HoldingRebuildService(rebuilding).rebuild(account_id=account_id, rebuilt_at=NOW)
            )
            await _wait_for_advisory_wait(engine, pid)
            await posting.rollback()
            result = await asyncio.wait_for(task, timeout=10)
            await rebuilding.commit()
    assert result.replayed is True
    await engine.dispose()
    await _cleanup(prefix)
