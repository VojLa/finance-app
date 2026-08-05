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
    CANONICAL_ALIAS,
    principal,
    seed_listed_holding,
    snapshot_command,
    twelve_data_engine,
)

from app.config.settings import Settings
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.db.models.prices import PriceSnapshotModel
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.modules.dashboard_snapshot.authorized_service import (
    AuthorizedDashboardSnapshotService,
)
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.market_data.service import RefreshMarketEvidenceCommand
from app.modules.portfolio_snapshot.models import (
    SnapshotGranularity as PortfolioSnapshotGranularity,
)
from app.modules.portfolio_snapshot.multi_account_service import (
    AuthorizedMultiAccountPortfolioSnapshotService,
    ExactAccountSnapshotSelection,
    ReadAuthorizedMultiAccountPortfolioSnapshotCommand,
)
from app.modules.snapshot_refresh.executor import UserSnapshotRefreshExecutor
from app.modules.snapshots.evidence_service import (
    AccountSnapshotEvidenceService,
    BuildAccountSnapshotEvidenceCommand,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="PostgreSQL integration test requires DATABASE_URL.",
)

SNAPSHOT_AT = datetime(2026, 8, 6)
OBSERVED_AT = datetime(2026, 8, 5, 12, 34)
OBSERVED_EPOCH = int(OBSERVED_AT.replace(tzinfo=UTC).timestamp())
CALCULATED_AT = datetime(2026, 8, 5, 13, 1)
CREATED_AT = datetime(2026, 8, 5, 13, 2)
API_KEY = "integration-server-key"


def _transport(
    *,
    status: int = 200,
    symbol: str = "AAPL",
    mic_code: str = "XNAS",
    currency: str = "USD",
    observed_epoch: int = OBSERVED_EPOCH,
    last_quote_at: int | None = None,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    last_quote_at = observed_epoch if last_quote_at is None else last_quote_at
    datetime_text = datetime.fromtimestamp(observed_epoch, tz=UTC).strftime("%Y-%m-%d %H:%M:%S")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            headers={"content-type": "application/json"},
            content=(
                f'{{"symbol":"{symbol}","mic_code":"{mic_code}",'
                f'"currency":"{currency}","datetime":"{datetime_text}",'
                f'"timestamp":{observed_epoch},"last_quote_at":{last_quote_at},'
                f'"close":"225.3200000000"}}'
            ).encode(),
        )

    return httpx.MockTransport(handler), requests


def _settings(*, with_key: bool = True) -> Settings:
    return Settings(
        environment="test",
        twelve_data_api_key=API_KEY if with_key else None,
        _env_file=None,
    )


@pytest.mark.asyncio
async def test_twelve_data_price_reaches_snapshots_and_exact_read_models() -> None:
    prefix = f"r5b2b1-e2e-{uuid4()}"
    alias = CANONICAL_ALIAS.replace("AAPL", "MSFT")
    user_id, _, _, _ = await seed_listed_holding(
        prefix,
        event_at=datetime(2026, 8, 1),
        created_at=CREATED_AT,
        aliases=(alias,),
    )
    transport, requests = _transport(symbol="MSFT")
    engine = twelve_data_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            market = await create_production_market_evidence_service(
                session,
                _settings(),
                twelve_data_http_transport=transport,
            ).refresh(RefreshMarketEvidenceCommand(user_id, SNAPSHOT_AT, CREATED_AT))
            refreshed = await UserSnapshotRefreshExecutor(session).execute(
                snapshot_command(
                    user_id,
                    snapshot_at=SNAPSHOT_AT,
                    calculated_at=CALCULATED_AT,
                    created_at=CREATED_AT,
                )
            )
            identity = refreshed.required_account_snapshot_identities[0]
            async with session.begin():
                evidence = await AccountSnapshotEvidenceService(session).build(
                    BuildAccountSnapshotEvidenceCommand(
                        account_id=identity.account_id,
                        snapshot_timestamp=SNAPSHOT_AT,
                        granularity=SnapshotGranularity.day,
                        source=SnapshotSource.price_refresh,
                        calculation_version=1,
                        output_currency="USD",
                    )
                )
            command = ReadAuthorizedMultiAccountPortfolioSnapshotCommand(
                principal=principal(user_id),
                timestamp=SNAPSHOT_AT,
                granularity=PortfolioSnapshotGranularity(refreshed.granularity.value),
                currency=refreshed.output_currency,
                calculation_version=refreshed.calculation_version,
                accounts=(
                    ExactAccountSnapshotSelection(
                        account_id=identity.account_id,
                        required_snapshot_id=identity.snapshot_id,
                    ),
                ),
            )
            portfolio = (
                await AuthorizedMultiAccountPortfolioSnapshotService(session).read(command)
            ).portfolio
            dashboard = (
                await AuthorizedDashboardSnapshotService(
                    AuthorizedMultiAccountPortfolioSnapshotService(session)
                ).read(command)
            ).dashboard

            assert len(requests) == 1
            assert market.required_price_count == 1
            assert market.required_fx_count == 0
            assert evidence.selected_price_ids == market.price_ids
            assert evidence.selected_snapshot_exchange_rate_ids == ()
            assert evidence.selected_historical_exchange_rate_ids == ()
            assert refreshed.selected_account_snapshot_count == 1
            assert portfolio.timestamp == dashboard.timestamp == SNAPSHOT_AT
            assert portfolio.currency == dashboard.currency == "USD"
            assert (
                portfolio.summary.investment_value
                == dashboard.summary.investment_value
                == Decimal("450.640000")
            )
            assert (
                portfolio.summary.investment_cost_basis
                == dashboard.summary.investment_cost_basis
                == Decimal("400.000000")
            )
            assert (
                portfolio.summary.unrealized_pnl_value
                == dashboard.summary.unrealized_pnl_value
                == Decimal("50.640000")
            )
            assert (
                portfolio.summary.cash_value
                == dashboard.summary.cash_value
                == Decimal("1000.000000")
            )
            assert (
                portfolio.summary.total_value
                == dashboard.summary.total_value
                == Decimal("1450.640000")
            )
            assert portfolio.summary.liabilities_value == Decimal("0.000000")
            assert portfolio.summary.account_count == dashboard.summary.account_count == 1
            assert portfolio.summary.position_count == dashboard.summary.position_count == 1

        async with AsyncSession(engine) as session:
            item = await session.scalar(
                select(AccountSnapshotItemModel).where(
                    AccountSnapshotItemModel.snapshot_id == identity.snapshot_id
                )
            )
            net_worth = await session.get(
                NetWorthSnapshotModel,
                refreshed.net_worth_snapshot_id,
            )
            assert item is not None
            assert net_worth is not None
            assert item.price_per_unit == Decimal("225.3200000000")
            assert item.price_timestamp == OBSERVED_AT
            assert item.value == Decimal("450.640000")
            assert net_worth.portfolio_value == Decimal("450.640000")
            assert net_worth.total_net_worth == Decimal("1450.640000")

        replay_transport, replay_requests = _transport(symbol="MSFT")
        async with AsyncSession(engine) as session:
            replay_market = await create_production_market_evidence_service(
                session,
                _settings(),
                twelve_data_http_transport=replay_transport,
            ).refresh(
                RefreshMarketEvidenceCommand(
                    user_id,
                    SNAPSHOT_AT,
                    datetime(2026, 8, 5, 13, 3),
                )
            )
            replay_refresh = await UserSnapshotRefreshExecutor(session).execute(
                snapshot_command(
                    user_id,
                    snapshot_at=SNAPSHOT_AT,
                    calculated_at=CALCULATED_AT,
                    created_at=CREATED_AT,
                )
            )
            assert replay_market.prices_replayed == 1
            assert replay_refresh.replayed_account_snapshot_count == 1
            assert len(replay_requests) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        "401",
        "429",
        "stale",
        "wrong_mic",
        "wrong_currency",
        "missing_key",
        "timestamp_mismatch",
    ],
)
async def test_quote_failure_creates_no_market_or_snapshot_graph(failure: str) -> None:
    prefix = f"r5b2b1-failure-{failure}-{uuid4()}"
    symbol = "T" + uuid4().hex[:12].upper()
    alias = f'{{"symbol":"{symbol}","mic_code":"XNAS"}}'
    user_id, account_id, _, listing_id = await seed_listed_holding(
        prefix,
        event_at=datetime(2026, 8, 1),
        created_at=CREATED_AT,
        aliases=(alias,),
    )
    observed = (
        int(datetime(2026, 8, 1).replace(tzinfo=UTC).timestamp())
        if failure == "stale"
        else OBSERVED_EPOCH
    )
    transport, requests = _transport(
        status=int(failure) if failure in {"401", "429"} else 200,
        symbol=symbol,
        mic_code="XNYS" if failure == "wrong_mic" else "XNAS",
        currency="EUR" if failure == "wrong_currency" else "USD",
        observed_epoch=observed,
        last_quote_at=observed + 60 if failure == "timestamp_mismatch" else observed,
    )
    engine = twelve_data_engine()
    try:
        async with AsyncSession(engine) as session:
            with pytest.raises(MarketEvidenceStateError, match="unavailable"):
                await create_production_market_evidence_service(
                    session,
                    _settings(with_key=failure != "missing_key"),
                    twelve_data_http_transport=transport,
                ).refresh(RefreshMarketEvidenceCommand(user_id, SNAPSHOT_AT, CREATED_AT))
            assert len(requests) == (0 if failure == "missing_key" else 1)
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
