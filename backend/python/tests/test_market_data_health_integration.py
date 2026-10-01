"""PostgreSQL lease and ordering checks; run with DATABASE_URL and migrated schema."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AssetType,
    MarketDataFailureReason,
    MarketDataHealthState,
    PriceSource,
)
from app.db.models.market_health import MarketDataListingHealthModel
from app.db.models.prices import PriceSnapshotModel
from app.db.url import normalize_database_url
from app.modules.market_data.health import ListingHealthOutcome
from app.modules.market_data.health_repository import MarketDataHealthRepository
from app.modules.market_data.health_service import MarketDataHealthService
from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.market_data.writer import (
    MarketEvidenceWriter,
    PersistMarketEvidenceCommand,
    price_snapshot_id,
)
from app.modules.prices.models import PriceObservation

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL, reason="requires migrated PostgreSQL DATABASE_URL"
)
NOW = datetime(2026, 9, 30, 12)


@pytest.mark.asyncio
async def test_persisted_lease_restart_ordering_and_provider_cooldown() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL), pool_size=5)
    prefix = f"health-{uuid4().hex}"
    asset_id = f"{prefix}-asset"
    first_id, second_id = f"{prefix}-one", f"{prefix}-two"
    first_symbol, second_symbol = f"{prefix}-AAPL", f"{prefix}-MSFT"

    async def claim(listing_id: str, owner: str, at: datetime) -> bool:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                return await MarketDataHealthService(MarketDataHealthRepository(session)).claim(
                    listing_id=listing_id,
                    provider=PriceSource.yahoo_finance,
                    provider_symbol=first_symbol if listing_id == first_id else second_symbol,
                    lease_owner=owner,
                    now=at,
                    lease_for=timedelta(seconds=30),
                )

    async def record(
        listing_id: str,
        owner: str,
        at: datetime,
        token: str,
        reason: MarketDataFailureReason | None = None,
    ):
        async with AsyncSession(engine, expire_on_commit=False) as session:
            async with session.begin():
                return await MarketDataHealthService(MarketDataHealthRepository(session)).record(
                    listing_id=listing_id,
                    provider=PriceSource.yahoo_finance,
                    provider_symbol=first_symbol if listing_id == first_id else second_symbol,
                    lease_owner=owner,
                    outcome=ListingHealthOutcome(
                        attempt_started_at=at,
                        attempt_token=token,
                        observed_at=at + timedelta(seconds=1),
                        reason=reason,
                    ),
                )

    try:
        async with AsyncSession(engine) as session:
            async with session.begin():
                session.add(
                    AssetModel(
                        id=asset_id,
                        symbol="AAPL",
                        isin=None,
                        name="Health fixture",
                        asset_type=AssetType.stock,
                        currency="USD",
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                await session.flush()
                for listing_id, symbol in ((first_id, first_symbol), (second_id, second_symbol)):
                    session.add(
                        AssetListingModel(
                            id=listing_id,
                            asset_id=asset_id,
                            symbol=symbol,
                            exchange="NASDAQ",
                            mic="XNAS",
                            currency="USD",
                            country="US",
                            provider=PriceSource.yahoo_finance,
                            provider_symbol=symbol,
                            is_primary=listing_id == first_id,
                            created_at=NOW,
                            updated_at=NOW,
                            base_priority=0,
                        )
                    )

        results = await asyncio.gather(
            claim(first_id, "worker-a", NOW), claim(first_id, "worker-b", NOW)
        )
        assert sorted(results) == [False, True]
        winner = "worker-a" if results[0] else "worker-b"
        loser = "worker-b" if results[0] else "worker-a"
        assert not await claim(first_id, loser, NOW + timedelta(seconds=29))
        assert await claim(first_id, loser, NOW + timedelta(seconds=31))

        success = await record(first_id, loser, NOW + timedelta(seconds=31), "newer")
        assert success is not None and success.state == MarketDataHealthState.healthy
        stale = await record(first_id, winner, NOW, "older", MarketDataFailureReason.timeout)
        assert stale is None
        replay = await record(first_id, loser, NOW + timedelta(seconds=31), "newer")
        assert replay == success

        stale_observation = PriceObservation(
            asset_id=asset_id,
            listing_id=first_id,
            provider=PriceSource.yahoo_finance,
            provider_symbol=first_symbol,
            price=Decimal("201.25"),
            currency="USD",
            observed_at=NOW + timedelta(seconds=32),
        )
        stale_price_id = price_snapshot_id(stale_observation)
        async with AsyncSession(engine, expire_on_commit=False) as session:
            health = MarketDataHealthService(MarketDataHealthRepository(session))

            async def reject_stale_owner() -> None:
                recorded = await health.record(
                    listing_id=first_id,
                    provider=PriceSource.yahoo_finance,
                    provider_symbol=first_symbol,
                    lease_owner=winner,
                    outcome=ListingHealthOutcome(
                        attempt_started_at=NOW,
                        attempt_token="older",
                        observed_at=NOW + timedelta(seconds=33),
                    ),
                )
                if recorded is None:
                    raise MarketEvidenceStateError()

            with pytest.raises(MarketEvidenceStateError):
                await MarketEvidenceWriter(session).write(
                    PersistMarketEvidenceCommand(
                        price_observations=(stale_observation,),
                        exchange_rate_observations=(),
                        created_at=NOW + timedelta(seconds=34),
                    ),
                    transactional_finalize=reject_stale_owner,
                )

        async with AsyncSession(engine) as session:
            assert await session.get(PriceSnapshotModel, stale_price_id) is None

        async with AsyncSession(engine) as session:
            row = await session.scalar(
                select(MarketDataListingHealthModel).where(
                    MarketDataListingHealthModel.listing_id == first_id
                )
            )
            assert row is not None and row.version == 3 and row.lease_owner is None
            assert row.last_failure_reason is None

        assert await claim(second_id, "worker-c", NOW + timedelta(minutes=1))
        limited = await record(
            second_id,
            "worker-c",
            NOW + timedelta(minutes=1),
            "rate-limit",
            MarketDataFailureReason.rate_limit,
        )
        assert limited is not None and limited.retry_after is not None
        assert not await claim(first_id, "worker-d", NOW + timedelta(minutes=2))
        assert await claim(first_id, "worker-d", limited.retry_after)
    finally:
        async with AsyncSession(engine) as session:
            async with session.begin():
                await session.execute(
                    delete(PriceSnapshotModel).where(PriceSnapshotModel.listing_id == first_id)
                )
                await session.execute(
                    delete(MarketDataListingHealthModel).where(
                        MarketDataListingHealthModel.listing_id.in_((first_id, second_id))
                    )
                )
                await session.execute(
                    delete(AssetListingModel).where(AssetListingModel.id.in_((first_id, second_id)))
                )
                await session.execute(delete(AssetModel).where(AssetModel.id == asset_id))
        await engine.dispose()
