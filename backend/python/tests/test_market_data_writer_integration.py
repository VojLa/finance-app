from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import AssetType, ExchangeRateSource, PriceSource
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.url import normalize_database_url
from app.modules.fx.models import ExchangeRateObservation
from app.modules.market_data.models import (
    MarketEvidenceConflictError,
    MarketEvidenceStateError,
)
from app.modules.market_data.writer import (
    MarketEvidenceWriter,
    PersistMarketEvidenceCommand,
    exchange_rate_id,
    price_snapshot_id,
)
from app.modules.prices.models import PriceObservation

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="PostgreSQL integration test requires DATABASE_URL.",
)

OBSERVED_AT = datetime(2026, 8, 3, 12, 0, 0, 123000)
CREATED_AT = datetime(2026, 8, 3, 12, 1, 0, 456000)


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=8)


def _unique_at(*, offset_seconds: int = 0) -> datetime:
    return datetime(2030, 1, 1) + timedelta(
        milliseconds=uuid4().int % 1_000_000_000,
        seconds=offset_seconds,
    )


async def _seed_listing(prefix: str, suffix: str) -> tuple[str, str]:
    engine = _engine()
    asset_id = f"{prefix}-asset-{suffix}"
    listing_id = f"{prefix}-listing-{suffix}"
    async with AsyncSession(engine) as session:
        session.add(
            AssetModel(
                id=asset_id,
                symbol=f"{prefix}-SYM{suffix}",
                isin=None,
                name=f"Asset {suffix}",
                asset_type=AssetType.etf,
                currency="EUR",
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            )
        )
        await session.flush()
        session.add(
            AssetListingModel(
                id=listing_id,
                asset_id=asset_id,
                symbol=f"{prefix}-SYM{suffix}",
                exchange=f"{prefix}-EX{suffix}",
                mic=None,
                currency="EUR",
                country=None,
                provider=PriceSource.yahoo_finance,
                provider_symbol=f"{listing_id}-symbol",
                is_primary=False,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            )
        )
        await session.commit()
    await engine.dispose()
    return asset_id, listing_id


def _price(
    asset_id: str,
    listing_id: str,
    *,
    value: str = "110.1234567890",
) -> PriceObservation:
    return PriceObservation(
        asset_id=asset_id,
        listing_id=listing_id,
        provider=PriceSource.yahoo_finance,
        provider_symbol=f"{listing_id}-symbol",
        price=Decimal(value),
        currency="EUR",
        observed_at=OBSERVED_AT,
    )


def _rate(
    *,
    value: str = "25.12345678",
    effective_at: datetime = OBSERVED_AT,
) -> ExchangeRateObservation:
    return ExchangeRateObservation(
        from_currency="EUR",
        to_currency="CZK",
        provider=ExchangeRateSource.ecb,
        rate=Decimal(value),
        effective_at=effective_at,
    )


def _command(
    prices: tuple[PriceObservation, ...],
    rates: tuple[ExchangeRateObservation, ...],
) -> PersistMarketEvidenceCommand:
    return PersistMarketEvidenceCommand(prices, rates, CREATED_AT)


@pytest.mark.asyncio
async def test_atomic_writer_create_replay_conflict_and_physical_precision() -> None:
    prefix = f"r5a-writer-{uuid4()}"
    asset_id, listing_id = await _seed_listing(prefix, "z")
    price = _price(asset_id, listing_id)
    rate = _rate(effective_at=_unique_at())
    engine = _engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            created = await MarketEvidenceWriter(session).write(_command((price,), (rate,)))
            assert not session.in_transaction()
        assert created.prices_created == created.rates_created == 1
        assert created.prices_replayed == created.rates_replayed == 0
        assert created.price_ids == (price_snapshot_id(price),)
        assert created.exchange_rate_ids == (exchange_rate_id(rate),)

        async with AsyncSession(engine) as session:
            persisted_price = await session.get(
                PriceSnapshotModel,
                price_snapshot_id(price),
            )
            persisted_rate = await session.get(
                ExchangeRateModel,
                exchange_rate_id(rate),
            )
            assert persisted_price is not None
            assert persisted_price.price == Decimal("110.1234567890")
            assert persisted_price.timestamp == OBSERVED_AT
            assert persisted_price.source is PriceSource.yahoo_finance
            assert persisted_rate is not None
            assert persisted_rate.rate == Decimal("25.12345678")
            assert persisted_rate.date == rate.effective_at
            assert persisted_rate.source is ExchangeRateSource.ecb

        async with AsyncSession(engine) as session:
            replayed = await MarketEvidenceWriter(session).write(
                PersistMarketEvidenceCommand(
                    (price,),
                    (rate,),
                    datetime(2026, 8, 3, 13),
                )
            )
        assert replayed.prices_replayed == replayed.rates_replayed == 1
        assert replayed.prices_created == replayed.rates_created == 0

        async with AsyncSession(engine) as session:
            with pytest.raises(MarketEvidenceConflictError):
                await MarketEvidenceWriter(session).write(
                    _command(
                        (_price(asset_id, listing_id, value="111"),),
                        (),
                    )
                )
            assert not session.in_transaction()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_one_conflict_rolls_back_earlier_new_price_in_same_batch() -> None:
    prefix = f"r5a-rollback-{uuid4()}"
    asset_a, listing_a = await _seed_listing(prefix, "a")
    asset_z, listing_z = await _seed_listing(prefix, "z")
    original = _price(asset_z, listing_z, value="100")
    rate = _rate(effective_at=_unique_at(offset_seconds=1))
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            await MarketEvidenceWriter(session).write(_command((original,), ()))
        new_price = _price(asset_a, listing_a, value="200")
        conflict = _price(asset_z, listing_z, value="101")
        async with AsyncSession(engine) as session:
            with pytest.raises(MarketEvidenceConflictError):
                await MarketEvidenceWriter(session).write(_command((new_price, conflict), (rate,)))
        async with AsyncSession(engine) as session:
            assert (
                await session.get(
                    PriceSnapshotModel,
                    price_snapshot_id(new_price),
                )
                is None
            )
            assert (
                await session.get(
                    ExchangeRateModel,
                    exchange_rate_id(rate),
                )
                is None
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PriceSnapshotModel)
                    .where(PriceSnapshotModel.listing_id == listing_z)
                )
                == 1
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_identical_writers_create_once_and_replay_once() -> None:
    prefix = f"r5a-concurrency-{uuid4()}"
    asset_id, listing_id = await _seed_listing(prefix, "c")
    rate = _rate(effective_at=_unique_at(offset_seconds=2))
    command = _command((_price(asset_id, listing_id),), (rate,))
    engine = _engine()
    try:

        async def write_once():
            async with AsyncSession(engine) as session:
                return await MarketEvidenceWriter(session).write(command)

        first, second = await asyncio.gather(write_once(), write_once())
        assert sorted((first.prices_created, second.prices_created)) == [0, 1]
        assert sorted((first.prices_replayed, second.prices_replayed)) == [0, 1]
        assert sorted((first.rates_created, second.rates_created)) == [0, 1]
        assert sorted((first.rates_replayed, second.rates_replayed)) == [0, 1]
        async with AsyncSession(engine) as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PriceSnapshotModel)
                    .where(PriceSnapshotModel.listing_id == listing_id)
                )
                == 1
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_foreign_key_failure_rolls_back_price_and_fx_batch() -> None:
    missing_price = _price("missing-asset", "missing-listing")
    rate = _rate(effective_at=_unique_at(offset_seconds=3))
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            with pytest.raises(MarketEvidenceStateError):
                await MarketEvidenceWriter(session).write(_command((missing_price,), (rate,)))
        async with AsyncSession(engine) as session:
            assert (
                await session.get(
                    PriceSnapshotModel,
                    price_snapshot_id(missing_price),
                )
                is None
            )
            assert (
                await session.get(
                    ExchangeRateModel,
                    exchange_rate_id(rate),
                )
                is None
            )
    finally:
        await engine.dispose()
