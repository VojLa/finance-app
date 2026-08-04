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
from support.cnb_fx_integration import (
    cnb_engine,
    principal,
    seed_eur_cash_flow,
    snapshot_command,
)

from app.config.settings import Settings
from app.db.models.prices import ExchangeRateModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
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

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="PostgreSQL integration test requires DATABASE_URL.",
)

EVENT_AT = datetime(2026, 7, 24, 10)
SNAPSHOT_AT = datetime(2026, 8, 3)
CALCULATED_AT = datetime(2026, 8, 3, 12, 1)
CREATED_AT = datetime(2026, 8, 3, 12, 2)


def _success_transport() -> tuple[httpx.MockTransport, list[str]]:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested = request.url.params["date"]
        requests.append(requested)
        publication = datetime.strptime(requested, "%d.%m.%Y").date()
        rate = "24,000" if publication == EVENT_AT.date() else "25,000"
        return httpx.Response(
            200,
            headers={"content-type": "text/xml"},
            content=cnb_xml(publication, (("EUR", "1", rate),)),
        )

    return httpx.MockTransport(handler), requests


@pytest.mark.asyncio
async def test_cnb_evidence_reaches_exact_account_net_worth_and_read_models() -> None:
    prefix = f"r5b1-cnb-snapshot-{uuid4()}"
    user_id, _account_id = await seed_eur_cash_flow(
        prefix,
        event_at=EVENT_AT,
        created_at=CREATED_AT,
    )
    transport, requests = _success_transport()
    settings = Settings(environment="test", _env_file=None)
    engine = cnb_engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            market = await create_production_market_evidence_service(
                session,
                settings,
                http_transport=transport,
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
            portfolio_service = AuthorizedMultiAccountPortfolioSnapshotService(session)
            portfolio = (await portfolio_service.read(command)).portfolio
            dashboard = (
                await AuthorizedDashboardSnapshotService(
                    AuthorizedMultiAccountPortfolioSnapshotService(session)
                ).read(command)
            ).dashboard

            assert market.price_ids == ()
            assert len(market.exchange_rate_ids) == 2
            assert requests == ["24.07.2026", "03.08.2026"]
            assert refreshed.selected_account_snapshot_count == 1
            assert portfolio.timestamp == dashboard.timestamp == SNAPSHOT_AT
            assert portfolio.currency == dashboard.currency == "CZK"
            assert portfolio.calculation_version == dashboard.calculation_version == 1
            assert (
                portfolio.summary.cash_value
                == dashboard.summary.cash_value
                == Decimal("25000.000000")
            )
            assert (
                portfolio.summary.total_value
                == dashboard.summary.total_value
                == Decimal("25000.000000")
            )
            assert (
                portfolio.summary.investment_value
                == dashboard.summary.investment_value
                == Decimal("0.000000")
            )
            assert (
                portfolio.summary.liabilities_value
                == dashboard.summary.liabilities_value
                == Decimal("0.000000")
            )
            assert portfolio.summary.net_deposits_value == Decimal("24000.000000")
            assert portfolio.summary.account_count == dashboard.summary.account_count == 1
            assert portfolio.summary.position_count == dashboard.summary.position_count == 0

        async with AsyncSession(engine) as session:
            account_snapshot = await session.get(AccountSnapshotModel, identity.snapshot_id)
            net_worth = await session.get(
                NetWorthSnapshotModel,
                refreshed.net_worth_snapshot_id,
            )
            assert account_snapshot is not None
            assert account_snapshot.cash_value == Decimal("25000.000000")
            assert account_snapshot.net_deposits_value == Decimal("24000.000000")
            exchange_rates = account_snapshot.exchange_rates
            assert exchange_rates is not None
            assert set(exchange_rates["historicalRateIds"]).issubset(set(market.exchange_rate_ids))
            assert exchange_rates["snapshotRates"][0]["rateId"] in market.exchange_rate_ids
            assert net_worth is not None
            assert net_worth.cash_value == Decimal("25000.000000")
            assert net_worth.total_net_worth == Decimal("25000.000000")

        transport, replay_requests = _success_transport()
        async with AsyncSession(engine) as session:
            replay_market = await create_production_market_evidence_service(
                session,
                settings,
                http_transport=transport,
            ).refresh(
                RefreshMarketEvidenceCommand(
                    user_id,
                    SNAPSHOT_AT,
                    datetime(2026, 8, 3, 12, 3),
                )
            )
            replay_snapshot = await UserSnapshotRefreshExecutor(session).execute(
                snapshot_command(
                    user_id,
                    snapshot_at=SNAPSHOT_AT,
                    calculated_at=CALCULATED_AT,
                    created_at=CREATED_AT,
                )
            )
            assert replay_market.rates_created == 0
            assert replay_market.rates_replayed == 2
            assert replay_snapshot.replayed_account_snapshot_count == 1
            assert replay_requests == ["24.07.2026", "03.08.2026"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["stale", "http"])
async def test_cnb_failure_writes_no_rate_or_partial_snapshot(failure: str) -> None:
    prefix = f"r5b1-cnb-failure-{failure}-{uuid4()}"
    user_id, account_id = await seed_eur_cash_flow(
        prefix,
        event_at=EVENT_AT,
        created_at=CREATED_AT,
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure == "http":
            return httpx.Response(503, headers={"content-type": "text/xml"}, content=b"down")
        return httpx.Response(
            200,
            headers={"content-type": "text/xml"},
            content=cnb_xml(datetime(2026, 7, 1).date()),
        )

    settings = Settings(environment="test", _env_file=None)
    engine = cnb_engine()
    try:
        async with AsyncSession(engine) as session:
            rates_before = await session.scalar(select(func.count()).select_from(ExchangeRateModel))
            await session.rollback()
            with pytest.raises(MarketEvidenceStateError, match="unavailable"):
                await create_production_market_evidence_service(
                    session,
                    settings,
                    http_transport=httpx.MockTransport(handler),
                ).refresh(RefreshMarketEvidenceCommand(user_id, SNAPSHOT_AT, CREATED_AT))
            assert calls == 1
            assert not session.in_transaction()

        async with AsyncSession(engine) as session:
            assert (
                await session.scalar(select(func.count()).select_from(ExchangeRateModel))
                == rates_before
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
