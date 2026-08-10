from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from support.fx_integration import fx_engine, seed_eur_cash_flow

from app.config.settings import Settings
from app.db.models.enums import ExchangeRateSource
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.modules.fx.models import ExchangeRateObservation
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.market_data.service import RefreshMarketEvidenceCommand
from app.modules.market_data.writer import exchange_rate_id

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="PostgreSQL integration test requires DATABASE_URL.",
)

EVENT_AT = datetime(2026, 7, 24, 10)
SNAPSHOT_AT = datetime(2026, 8, 3)
CREATED_AT = datetime(2026, 8, 3, 12, 1)


@pytest.mark.asyncio
async def test_production_twelve_data_registry_persists_direct_rates_and_replays() -> None:
    prefix = f"r11j-twelve-fx-market-{uuid4()}"
    user_id, _ = await seed_eur_cash_flow(
        prefix,
        event_at=EVENT_AT,
        created_at=CREATED_AT,
        base_currency="USD",
    )
    requests: list[str] = []
    sessions: list[AsyncSession] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert sessions
        assert not sessions[0].in_transaction()
        assert request.url.params["symbol"] == "EUR/USD"
        publication = date.fromisoformat(request.url.params["end_date"]) - timedelta(days=1)
        requests.append(f"EUR/USD@{publication.isoformat()}")
        rate = "1.10000000" if publication == EVENT_AT.date() else "1.20000000"
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=(
                f'{{"meta":{{"symbol":"EUR/USD"}},"values":['
                f'{{"datetime":"{publication.isoformat()}","close":"{rate}"}}],'
                '"status":"ok"}'
            ).encode(),
        )

    transport = httpx.MockTransport(handler)
    settings = Settings(environment="test", twelve_data_api_key="test-key", _env_file=None)
    engine = fx_engine()
    try:
        async with AsyncSession(engine) as session:
            prices_before = await session.scalar(
                select(func.count()).select_from(PriceSnapshotModel)
            )
        async with AsyncSession(engine) as session:
            sessions[:] = [session]
            first = await create_production_market_evidence_service(
                session,
                settings,
                twelve_data_fx_http_transport=transport,
            ).refresh(RefreshMarketEvidenceCommand(user_id, SNAPSHOT_AT, CREATED_AT))
            replay = await create_production_market_evidence_service(
                session,
                settings,
                twelve_data_fx_http_transport=transport,
            ).refresh(
                RefreshMarketEvidenceCommand(
                    user_id,
                    SNAPSHOT_AT,
                    datetime(2026, 8, 3, 12, 2),
                )
            )
            assert not session.in_transaction()

        event_observation = ExchangeRateObservation(
            "EUR",
            "USD",
            ExchangeRateSource.twelve_data,
            Decimal("1.10000000"),
            datetime.combine(EVENT_AT.date(), datetime.min.time()),
        )
        snapshot_observation = ExchangeRateObservation(
            "EUR",
            "USD",
            ExchangeRateSource.twelve_data,
            Decimal("1.20000000"),
            datetime.combine(SNAPSHOT_AT.date(), datetime.min.time()),
        )
        expected_ids = tuple(
            sorted(
                (
                    exchange_rate_id(event_observation),
                    exchange_rate_id(snapshot_observation),
                )
            )
        )
        assert first.required_price_count == 0
        assert first.required_fx_count == 2
        assert first.price_ids == ()
        assert first.exchange_rate_ids == expected_ids
        assert first.rates_created + first.rates_replayed == 2
        assert replay.exchange_rate_ids == expected_ids
        assert replay.rates_created == 0
        assert replay.rates_replayed == 2
        assert requests == [
            "EUR/USD@2026-07-24",
            "EUR/USD@2026-08-03",
            "EUR/USD@2026-07-24",
            "EUR/USD@2026-08-03",
        ]

        async with AsyncSession(engine) as session:
            rates = tuple(
                await session.scalars(
                    select(ExchangeRateModel).where(ExchangeRateModel.id.in_(expected_ids))
                )
            )
            assert {(rate.source, rate.date, rate.rate) for rate in rates} == {
                (ExchangeRateSource.twelve_data, datetime(2026, 7, 24), Decimal("1.10000000")),
                (ExchangeRateSource.twelve_data, datetime(2026, 8, 3), Decimal("1.20000000")),
            }
            assert (
                await session.scalar(select(func.count()).select_from(PriceSnapshotModel))
                == prices_before
            )
    finally:
        await engine.dispose()
