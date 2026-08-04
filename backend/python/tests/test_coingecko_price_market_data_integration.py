from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from support.coingecko_price_integration import (
    coingecko_engine,
    seed_crypto_holding,
)

from app.config.settings import Settings
from app.db.models.enums import PriceSource
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.market_data.service import RefreshMarketEvidenceCommand

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="PostgreSQL integration test requires DATABASE_URL.",
)

SNAPSHOT_AT = datetime(2026, 8, 4)
OBSERVED_AT = datetime(2026, 8, 3, 23)
OBSERVED_EPOCH = int(OBSERVED_AT.replace(tzinfo=UTC).timestamp())
CREATED_AT = datetime(2026, 8, 4, 12, 1)


def _success_transport(
    provider_symbol: str,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=(
                f'{{"{provider_symbol}":{{"eur":61234.123456789,'
                f'"last_updated_at":{OBSERVED_EPOCH}}}}}'
            ).encode(),
        )

    return httpx.MockTransport(handler), requests


@pytest.mark.asyncio
async def test_production_coingecko_registry_persists_exact_price_and_replays() -> None:
    prefix = f"r5b2a-market-{uuid4()}"
    user_id, _, asset_id, listing_id = await seed_crypto_holding(
        prefix,
        event_at=datetime(2026, 8, 1),
        created_at=CREATED_AT,
        aliases=("bitcoin",),
        listing_provider_symbol="BTC",
    )
    transport, requests = _success_transport("bitcoin")
    engine = coingecko_engine()
    settings = Settings(environment="test", _env_file=None)
    try:
        async with AsyncSession(engine) as session:
            rates_before = await session.scalar(select(func.count()).select_from(ExchangeRateModel))
            await session.rollback()
            first = await create_production_market_evidence_service(
                session,
                settings,
                coingecko_http_transport=transport,
            ).refresh(RefreshMarketEvidenceCommand(user_id, SNAPSHOT_AT, CREATED_AT))
            replay = await create_production_market_evidence_service(
                session,
                settings,
                coingecko_http_transport=transport,
            ).refresh(
                RefreshMarketEvidenceCommand(
                    user_id,
                    SNAPSHOT_AT,
                    datetime(2026, 8, 4, 12, 2),
                )
            )
            assert not session.in_transaction()

        assert len(requests) == 2
        for request in requests:
            assert request.url.params.multi_items() == [
                ("ids", "bitcoin"),
                ("vs_currencies", "eur"),
                ("include_last_updated_at", "true"),
                ("precision", "full"),
            ]
        assert first.required_price_count == 1
        assert first.required_fx_count == 0
        assert first.prices_created == 1
        assert first.prices_replayed == 0
        assert first.exchange_rate_ids == ()
        assert replay.price_ids == first.price_ids
        assert replay.prices_created == 0
        assert replay.prices_replayed == 1

        async with AsyncSession(engine) as session:
            persisted = await session.get(PriceSnapshotModel, first.price_ids[0])
            assert persisted is not None
            assert persisted.asset_id == asset_id
            assert persisted.listing_id == listing_id
            assert persisted.source is PriceSource.coingecko
            assert persisted.price == Decimal("61234.1234567890")
            assert persisted.currency == "EUR"
            assert persisted.timestamp == OBSERVED_AT
            assert (
                await session.scalar(select(func.count()).select_from(ExchangeRateModel))
                == rates_before
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("aliases", [(), ("bitcoin", "wrapped-bitcoin")])
async def test_missing_or_ambiguous_coingecko_alias_fails_before_http(
    aliases: tuple[str, ...],
) -> None:
    prefix = f"r5b2a-alias-{uuid4()}"
    exact_aliases = tuple(f"{alias}-{prefix}" for alias in aliases)
    user_id, _, _, listing_id = await seed_crypto_holding(
        prefix,
        event_at=datetime(2026, 8, 1),
        created_at=CREATED_AT,
        aliases=exact_aliases,
    )
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("HTTP must not run without one exact alias")

    engine = coingecko_engine()
    try:
        async with AsyncSession(engine) as session:
            with pytest.raises(MarketEvidenceStateError, match="unavailable"):
                await create_production_market_evidence_service(
                    session,
                    Settings(environment="test", _env_file=None),
                    coingecko_http_transport=httpx.MockTransport(handler),
                ).refresh(RefreshMarketEvidenceCommand(user_id, SNAPSHOT_AT, CREATED_AT))
            assert calls == 0
            assert not session.in_transaction()
        async with AsyncSession(engine) as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PriceSnapshotModel)
                    .where(PriceSnapshotModel.listing_id == listing_id)
                )
                == 0
            )
    finally:
        await engine.dispose()
