from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from support import investment_fixture_e2e as support

from app.db.models.enums import ImportSource
from app.db.models.holdings import HoldingModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.main import create_app
from app.modules.snapshot_refresh.api import get_user_snapshot_refresh_clock

pytestmark = pytest.mark.skipif(
    not support.DATABASE_URL,
    reason="DATABASE_URL is required",
)

REFRESH_PATH = "/api/v1/snapshot-refresh/recalculate"
PORTFOLIO_PATH = "/api/v1/portfolio/snapshot"
DASHBOARD_PATH = "/api/v1/dashboard/snapshot"


async def _snapshot_counts(user_id: str, account_id: str) -> tuple[int, int]:
    db = support.engine()
    async with AsyncSession(db) as session:
        account_count = int(
            await session.scalar(
                select(func.count())
                .select_from(AccountSnapshotModel)
                .where(AccountSnapshotModel.account_id == account_id)
            )
            or 0
        )
        net_worth_count = int(
            await session.scalar(
                select(func.count())
                .select_from(NetWorthSnapshotModel)
                .where(NetWorthSnapshotModel.user_id == user_id)
            )
            or 0
        )
    await db.dispose()
    return account_count, net_worth_count


async def _snapshot_evidence(
    *,
    user_id: str,
    account_id: str,
    snapshot_id: str,
) -> dict[str, Any]:
    db = support.engine()
    async with AsyncSession(db) as session:
        snapshot = await session.get(AccountSnapshotModel, snapshot_id)
        assert snapshot is not None
        items = tuple(
            (
                await session.scalars(
                    select(AccountSnapshotItemModel)
                    .where(AccountSnapshotItemModel.snapshot_id == snapshot_id)
                    .order_by(AccountSnapshotItemModel.symbol)
                )
            ).all()
        )
        net_worth = await session.scalar(
            select(NetWorthSnapshotModel).where(
                NetWorthSnapshotModel.user_id == user_id,
                NetWorthSnapshotModel.timestamp == snapshot.timestamp,
                NetWorthSnapshotModel.currency == snapshot.currency,
                NetWorthSnapshotModel.granularity == snapshot.granularity,
            )
        )
        assert net_worth is not None
        holding = await session.scalar(
            select(HoldingModel).where(HoldingModel.account_id == account_id)
        )
        assert holding is not None
        exchange_rate_count = int(
            await session.scalar(select(func.count()).select_from(ExchangeRateModel)) or 0
        )
        selected_price_count = int(
            await session.scalar(
                select(func.count())
                .select_from(PriceSnapshotModel)
                .where(PriceSnapshotModel.listing_id.in_(tuple(item.listing_id for item in items)))
            )
            or 0
        )
        version = str(await session.scalar(text("SHOW server_version")))
        session.expunge(snapshot)
        session.expunge(net_worth)
        session.expunge(holding)
        for item in items:
            session.expunge(item)
    await db.dispose()
    return {
        "snapshot": snapshot,
        "items": items,
        "net_worth": net_worth,
        "holding": holding,
        "exchange_rate_count": exchange_rate_count,
        "selected_price_count": selected_price_count,
        "postgres_version": version,
    }


@pytest.mark.parametrize(
    ("source", "filename", "price", "expected"),
    [
        (
            ImportSource.trading212,
            "activity.csv",
            "110",
            {
                "symbol": "TSTETF",
                "quantity": Decimal("2"),
                "cash": Decimal("805.25"),
                "investment": Decimal("220"),
                "cost": Decimal("200"),
                "total": Decimal("1025.25"),
                "unrealized": Decimal("20"),
                "net_deposits": Decimal("1000"),
            },
        ),
        (
            ImportSource.anycoin,
            "history.csv",
            "60000",
            {
                "symbol": "BTC",
                "quantity": Decimal("0.01"),
                "cash": Decimal("-490"),
                "investment": Decimal("600"),
                "cost": Decimal("490"),
                "total": Decimal("110"),
                "unrealized": Decimal("110"),
                "net_deposits": Decimal("0"),
            },
        ),
    ],
)
def test_fixture_reaches_seeded_price_snapshot_and_both_exact_reads_without_fx(
    source: ImportSource,
    filename: str,
    price: str,
    expected: dict[str, Any],
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = f"r3-snapshot-{source.value}"
    user_id, account_id = asyncio.run(support.seed_identity(prefix, source=source))
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path / source.value))
    bucket = datetime(2026, 7, 26, 12, tzinfo=UTC)
    app = create_app(support.settings())
    app.dependency_overrides[get_user_snapshot_refresh_clock] = lambda: lambda: bucket
    try:
        with TestClient(app) as client:
            staged = support.run_stages(
                client,
                source=source,
                user_id=user_id,
                account_id=account_id,
                content=support.fixture(source, filename),
                filename=filename,
                post=False,
            )
            asyncio.run(support.seed_asset_listing(prefix, source=source))
            posted = support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=staged["batch_id"],
            )
            assert posted["snapshot_refresh_status"] == "unavailable"
            assert asyncio.run(_snapshot_counts(user_id, account_id)) == (0, 0)

            asyncio.run(
                support.seed_price(
                    prefix,
                    price=price,
                    snapshot_timestamp=bucket,
                )
            )
            refresh_response = client.post(
                REFRESH_PATH,
                headers=support.headers(user_id),
            )
            assert refresh_response.status_code == 200, refresh_response.text
            refresh = refresh_response.json()
            manifest = {field: deepcopy(refresh[field]) for field in support.MANIFEST_FIELDS}
            unchanged = deepcopy(manifest)
            portfolio_response = client.post(
                PORTFOLIO_PATH,
                headers=support.headers(user_id),
                json=manifest,
            )
            dashboard_response = client.post(
                DASHBOARD_PATH,
                headers=support.headers(user_id),
                json=manifest,
            )
            replay_response = client.post(
                REFRESH_PATH,
                headers=support.headers(user_id),
            )

        assert refresh["selectedAccountSnapshotCount"] == 1
        assert refresh["accounts"] == [
            {
                "accountId": account_id,
                "snapshotId": manifest["accounts"][0]["snapshotId"],
            }
        ]
        assert manifest == unchanged
        assert replay_response.status_code == 200
        assert {
            field: replay_response.json()[field] for field in support.MANIFEST_FIELDS
        } == manifest
        assert portfolio_response.status_code == 200, portfolio_response.text
        assert dashboard_response.status_code == 200, dashboard_response.text
        portfolio = portfolio_response.json()
        dashboard = dashboard_response.json()
        _assert_common_read_parity(
            manifest=manifest,
            portfolio=portfolio,
            dashboard=dashboard,
            account_id=account_id,
            expected=expected,
        )

        evidence = asyncio.run(
            _snapshot_evidence(
                user_id=user_id,
                account_id=account_id,
                snapshot_id=manifest["accounts"][0]["snapshotId"],
            )
        )
        _assert_persisted_snapshot(evidence=evidence, expected=expected)
    finally:
        asyncio.run(support.cleanup(prefix))


def _assert_persisted_snapshot(
    *,
    evidence: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    snapshot = evidence["snapshot"]
    item = evidence["items"][0]
    net_worth = evidence["net_worth"]
    holding = evidence["holding"]
    assert evidence["postgres_version"].startswith("16.")
    assert evidence["exchange_rate_count"] == 0
    assert evidence["selected_price_count"] == 1
    assert len(evidence["items"]) == 1
    assert snapshot.currency == "EUR"
    assert snapshot.cash_value == expected["cash"]
    assert snapshot.investment_value == expected["investment"]
    assert snapshot.investment_cost_basis == expected["cost"]
    assert snapshot.liabilities_value == Decimal("0")
    assert snapshot.total_value == expected["total"]
    assert snapshot.unrealized_pnl_value == expected["unrealized"]
    assert snapshot.net_deposits_value == expected["net_deposits"]
    assert snapshot.realized_pnl_value == Decimal("0")
    assert snapshot.fees_value == Decimal("0")
    assert snapshot.taxes_value == Decimal("0")
    assert snapshot.exchange_rates == {
        "version": 1,
        "snapshotRates": [],
        "historicalRateIds": [],
    }
    assert item.symbol == expected["symbol"]
    assert item.quantity == expected["quantity"]
    assert item.value == expected["investment"]
    assert item.cost_basis == expected["cost"]
    assert item.price_source.value == "manual"
    assert holding.quantity == expected["quantity"]
    assert holding.avg_buy_price == expected["cost"] / expected["quantity"]
    assert net_worth.currency == "EUR"
    assert net_worth.cash_value == expected["cash"]
    assert net_worth.portfolio_value == expected["investment"]
    assert net_worth.liabilities_value == Decimal("0")
    assert net_worth.total_net_worth == expected["total"]
    assert net_worth.exchange_rates is None


def _assert_common_read_parity(
    *,
    manifest: dict[str, Any],
    portfolio: dict[str, Any],
    dashboard: dict[str, Any],
    account_id: str,
    expected: dict[str, Any],
) -> None:
    assert portfolio["timestamp"] == dashboard["timestamp"] == manifest["timestamp"]
    assert portfolio["granularity"] == dashboard["granularity"] == manifest["granularity"]
    assert portfolio["currency"] == dashboard["currency"] == manifest["currency"] == "EUR"
    assert (
        portfolio["calculationVersion"]
        == dashboard["calculationVersion"]
        == manifest["calculationVersion"]
    )
    assert {value["account"]["accountId"] for value in portfolio["accounts"]} == {account_id}
    assert {value["accountId"] for value in dashboard["accounts"]} == {account_id}
    assert (
        portfolio["summary"]["totalValue"]
        == dashboard["summary"]["totalValue"]
        == str(expected["total"].quantize(Decimal("0.000001")))
    )
    assert portfolio["summary"]["cashValue"] == str(expected["cash"].quantize(Decimal("0.000001")))
    assert (
        portfolio["summary"]["investmentValue"]
        == dashboard["summary"]["investmentValue"]
        == str(expected["investment"].quantize(Decimal("0.000001")))
    )
    assert portfolio["summary"]["liabilitiesValue"] == "0.000000"
    assert dashboard["summary"]["liabilitiesValue"] == "0.000000"
    assert portfolio["summary"]["positionCount"] == dashboard["summary"]["positionCount"] == 1
    assert len(portfolio["accounts"][0]["positions"]) == 1
    assert len(dashboard["topPositions"]) == 1
    assert portfolio["accounts"][0]["positions"][0]["symbol"] == expected["symbol"]
    assert dashboard["topPositions"][0]["symbol"] == expected["symbol"]
