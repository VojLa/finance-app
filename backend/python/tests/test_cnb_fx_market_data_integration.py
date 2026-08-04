from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from support.cnb_fx import cnb_xml
from support.cnb_fx_integration import cnb_engine, seed_eur_cash_flow

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
async def test_production_cnb_registry_persists_exact_rates_and_replays() -> None:
    prefix = f"r5b1-cnb-market-{uuid4()}"
    user_id, _ = await seed_eur_cash_flow(
        prefix,
        event_at=EVENT_AT,
        created_at=CREATED_AT,
    )
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested = request.url.params["date"]
        requests.append(requested)
        publication = datetime.strptime(requested, "%d.%m.%Y").date()
        rate = "24,000" if publication == EVENT_AT.date() else "25,000"
        return httpx.Response(
            200,
            headers={"content-type": "application/xml"},
            content=cnb_xml(publication, (("EUR", "1", rate),)),
        )

    transport = httpx.MockTransport(handler)
    settings = Settings(environment="test", _env_file=None)
    engine = cnb_engine()
    try:
        async with AsyncSession(engine) as session:
            prices_before = await session.scalar(
                select(func.count()).select_from(PriceSnapshotModel)
            )
        async with AsyncSession(engine) as session:
            first = await create_production_market_evidence_service(
                session,
                settings,
                http_transport=transport,
            ).refresh(RefreshMarketEvidenceCommand(user_id, SNAPSHOT_AT, CREATED_AT))
            replay = await create_production_market_evidence_service(
                session,
                settings,
                http_transport=transport,
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
            "CZK",
            ExchangeRateSource.cnb,
            Decimal("24.000"),
            datetime.combine(EVENT_AT.date(), datetime.min.time()),
        )
        snapshot_observation = ExchangeRateObservation(
            "EUR",
            "CZK",
            ExchangeRateSource.cnb,
            Decimal("25.000"),
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
        assert first.rates_created == 2
        assert first.rates_replayed == 0
        assert replay.exchange_rate_ids == expected_ids
        assert replay.rates_created == 0
        assert replay.rates_replayed == 2
        assert requests == [
            "24.07.2026",
            "03.08.2026",
            "24.07.2026",
            "03.08.2026",
        ]

        async with AsyncSession(engine) as session:
            rates = tuple(
                await session.scalars(
                    select(ExchangeRateModel).where(ExchangeRateModel.id.in_(expected_ids))
                )
            )
            assert {(rate.source, rate.date, rate.rate) for rate in rates} == {
                (ExchangeRateSource.cnb, datetime(2026, 7, 24), Decimal("24.00000000")),
                (ExchangeRateSource.cnb, datetime(2026, 8, 3), Decimal("25.00000000")),
            }
            assert (
                await session.scalar(select(func.count()).select_from(PriceSnapshotModel))
                == prices_before
            )
    finally:
        await engine.dispose()
