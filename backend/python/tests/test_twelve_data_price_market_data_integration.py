from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from support.twelve_data_price_integration import (
    seed_listed_holding,
    twelve_data_engine,
)

from app.config.settings import Settings
from app.db.models.enums import PriceSource
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.market_data.service import RefreshMarketEvidenceCommand

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="PostgreSQL integration test requires DATABASE_URL.",
)

SNAPSHOT_AT = datetime(2026, 8, 6)
OBSERVED_AT = datetime(2026, 8, 5, 12, 34)
OBSERVED_EPOCH = int(OBSERVED_AT.replace(tzinfo=UTC).timestamp())
CREATED_AT = datetime(2026, 8, 5, 13, 1)
API_KEY = "integration-server-key"


def _quote_body(
    *,
    symbol: str = "AAPL",
    mic_code: str = "XNAS",
    currency: str = "USD",
    timestamp: int = OBSERVED_EPOCH,
    close: str = "225.3200000000",
) -> bytes:
    datetime_text = datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")
    return (
        f'{{"symbol":"{symbol}","name":"Example Corp","exchange":"NASDAQ",'
        f'"mic_code":"{mic_code}","currency":"{currency}",'
        f'"datetime":"{datetime_text}","timestamp":{timestamp},'
        f'"last_quote_at":{timestamp},"close":"{close}"}}'
    ).encode()


def _success_transport() -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=_quote_body(),
        )

    return httpx.MockTransport(handler), requests


def _settings() -> Settings:
    return Settings(
        environment="test",
        twelve_data_api_key=API_KEY,
        _env_file=None,
    )


@pytest.mark.asyncio
async def test_production_twelve_data_registry_persists_exact_price_and_replays() -> None:
    prefix = f"r5b2b1-market-{uuid4()}"
    user_id, _, asset_id, listing_id = await seed_listed_holding(
        prefix,
        event_at=datetime(2026, 8, 1),
        created_at=CREATED_AT,
        exact_trading212_identity=True,
    )
    transport, requests = _success_transport()
    engine = twelve_data_engine()
    try:
        async with AsyncSession(engine) as session:
            rates_before = await session.scalar(select(func.count()).select_from(ExchangeRateModel))
            await session.rollback()
            first = await create_production_market_evidence_service(
                session,
                _settings(),
                twelve_data_http_transport=transport,
            ).refresh(RefreshMarketEvidenceCommand(user_id, SNAPSHOT_AT, CREATED_AT))
            replay = await create_production_market_evidence_service(
                session,
                _settings(),
                twelve_data_http_transport=transport,
            ).refresh(
                RefreshMarketEvidenceCommand(
                    user_id,
                    SNAPSHOT_AT,
                    datetime(2026, 8, 5, 13, 2),
                )
            )
            assert not session.in_transaction()

        assert len(requests) == 2
        for request in requests:
            assert request.url.params["symbol"] == "AAPL"
            assert request.url.params["mic_code"] == "XNAS"
            assert "AAPL_US_EQ" not in str(request.url)
            assert "US0378331005" not in str(request.url)
            assert "XLON" not in str(request.url)
            assert request.headers["authorization"] == f"apikey {API_KEY}"
            assert API_KEY not in str(request.url)
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
            assert persisted.source is PriceSource.twelve_data
            assert persisted.price == Decimal("225.3200000000")
            assert persisted.currency == "USD"
            assert persisted.timestamp == OBSERVED_AT
            assert (
                await session.scalar(select(func.count()).select_from(ExchangeRateModel))
                == rates_before
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("alias_count", [0, 2])
async def test_missing_or_ambiguous_alias_fails_before_http(
    alias_count: int,
) -> None:
    prefix = f"r5b2b1-alias-{uuid4()}"
    symbol = "T" + uuid4().hex[:12].upper()
    aliases = (
        ()
        if alias_count == 0
        else (
            f'{{"symbol":"{symbol}","mic_code":"XNAS"}}',
            f'{{"symbol":"{symbol}B","mic_code":"XNYS"}}',
        )
    )
    user_id, account_id, _, listing_id = await seed_listed_holding(
        prefix,
        event_at=datetime(2026, 8, 1),
        created_at=CREATED_AT,
        aliases=aliases,
    )
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("HTTP must not run without one exact alias")

    engine = twelve_data_engine()
    try:
        async with AsyncSession(engine) as session:
            with pytest.raises(MarketEvidenceStateError, match="unavailable"):
                await create_production_market_evidence_service(
                    session,
                    _settings(),
                    twelve_data_http_transport=httpx.MockTransport(handler),
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
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AccountSnapshotModel)
                    .where(AccountSnapshotModel.account_id == account_id)
                )
                == 0
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(NetWorthSnapshotModel)
                    .where(NetWorthSnapshotModel.user_id == user_id)
                )
                == 0
            )
    finally:
        await engine.dispose()
