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
    principal,
    seed_crypto_holding,
    snapshot_command,
)

from app.config.settings import Settings
from app.db.models.enums import SnapshotGranularity, SnapshotSource
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

SNAPSHOT_AT = datetime(2026, 8, 4)
OBSERVED_AT = datetime(2026, 8, 3, 23)
OBSERVED_EPOCH = int(OBSERVED_AT.replace(tzinfo=UTC).timestamp())
CALCULATED_AT = datetime(2026, 8, 4, 12, 1)
CREATED_AT = datetime(2026, 8, 4, 12, 2)


def _transport(
    *,
    provider_symbol: str = "ethereum",
    status: int = 200,
    price: str = "61234.123456789",
    observed_epoch: int = OBSERVED_EPOCH,
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            headers={"content-type": "application/json"},
            content=(
                f'{{"{provider_symbol}":{{"eur":{price},"last_updated_at":{observed_epoch}}}}}'
            ).encode(),
        )

    return httpx.MockTransport(handler), requests


@pytest.mark.asyncio
async def test_coingecko_price_reaches_snapshots_and_exact_read_models() -> None:
    prefix = f"r5b2a-e2e-{uuid4()}"
    user_id, _account_id, _, _ = await seed_crypto_holding(
        prefix,
        event_at=datetime(2026, 8, 1),
        created_at=CREATED_AT,
        aliases=("ethereum",),
    )
    transport, requests = _transport()
    engine = coingecko_engine()
    settings = Settings(environment="test", _env_file=None)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            market = await create_production_market_evidence_service(
                session,
                settings,
                coingecko_http_transport=transport,
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
                        output_currency="EUR",
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
            assert market.exchange_rate_ids == ()
            assert evidence.selected_price_ids == market.price_ids
            assert evidence.selected_snapshot_exchange_rate_ids == ()
            assert evidence.selected_historical_exchange_rate_ids == ()
            assert refreshed.selected_account_snapshot_count == 1
            assert portfolio.timestamp == dashboard.timestamp == SNAPSHOT_AT
            assert portfolio.currency == dashboard.currency == "EUR"
            assert portfolio.calculation_version == dashboard.calculation_version == 1
            assert (
                portfolio.summary.investment_value
                == dashboard.summary.investment_value
                == Decimal("61234123.456789")
            )
            assert (
                portfolio.summary.investment_cost_basis
                == dashboard.summary.investment_cost_basis
                == Decimal("50000000.000000")
            )
            assert (
                portfolio.summary.unrealized_pnl_value
                == dashboard.summary.unrealized_pnl_value
                == Decimal("11234123.456789")
            )
            assert (
                portfolio.summary.cash_value
                == dashboard.summary.cash_value
                == Decimal("1000.000000")
            )
            assert (
                portfolio.summary.total_value
                == dashboard.summary.total_value
                == Decimal("61235123.456789")
            )
            assert portfolio.summary.liabilities_value == Decimal("0.000000")
            assert portfolio.summary.account_count == dashboard.summary.account_count == 1
            assert portfolio.summary.position_count == dashboard.summary.position_count == 1

        async with AsyncSession(engine) as session:
            account_snapshot = await session.get(AccountSnapshotModel, identity.snapshot_id)
            net_worth = await session.get(
                NetWorthSnapshotModel,
                refreshed.net_worth_snapshot_id,
            )
            item = await session.scalar(
                select(AccountSnapshotItemModel).where(
                    AccountSnapshotItemModel.snapshot_id == identity.snapshot_id
                )
            )
            assert account_snapshot is not None
            assert net_worth is not None
            assert item is not None
            assert item.price_per_unit == Decimal("61234.1234567890")
            assert item.price_timestamp == OBSERVED_AT
            assert item.value == Decimal("61234123.456789")
            assert net_worth.portfolio_value == Decimal("61234123.456789")
            assert net_worth.total_net_worth == Decimal("61235123.456789")

        replay_transport, replay_requests = _transport()
        async with AsyncSession(engine) as session:
            replay_market = await create_production_market_evidence_service(
                session,
                settings,
                coingecko_http_transport=replay_transport,
            ).refresh(
                RefreshMarketEvidenceCommand(
                    user_id,
                    SNAPSHOT_AT,
                    datetime(2026, 8, 4, 12, 3),
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
@pytest.mark.parametrize("failure", ["stale", "http", "zero"])
async def test_price_failure_creates_no_price_or_partial_snapshot(failure: str) -> None:
    prefix = f"r5b2a-failure-{failure}-{uuid4()}"
    provider_symbol = f"failure-coin-{prefix}"
    user_id, account_id, _, _ = await seed_crypto_holding(
        prefix,
        event_at=datetime(2026, 8, 1),
        created_at=CREATED_AT,
        aliases=(provider_symbol,),
    )
    observed = (
        int(datetime(2026, 7, 31).replace(tzinfo=UTC).timestamp())
        if failure == "stale"
        else OBSERVED_EPOCH
    )
    transport, requests = _transport(
        provider_symbol=provider_symbol,
        status=503 if failure == "http" else 200,
        price="0" if failure == "zero" else "61234.123456789",
        observed_epoch=observed,
    )
    engine = coingecko_engine()
    try:
        async with AsyncSession(engine) as session:
            with pytest.raises(MarketEvidenceStateError, match="unavailable"):
                await create_production_market_evidence_service(
                    session,
                    Settings(environment="test", _env_file=None),
                    coingecko_http_transport=transport,
                ).refresh(RefreshMarketEvidenceCommand(user_id, SNAPSHOT_AT, CREATED_AT))
            assert len(requests) == 1
            assert not session.in_transaction()
        async with AsyncSession(engine) as session:
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
