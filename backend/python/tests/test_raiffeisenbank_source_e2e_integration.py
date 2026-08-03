from __future__ import annotations

import asyncio
import importlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.db.models.transactions import TransactionModel
from app.modules.snapshot_refresh.api import get_user_snapshot_refresh_clock

support = cast(
    Any,
    importlib.import_module("tests.test_raiffeisenbank_source_integration"),
)

pytestmark = pytest.mark.skipif(
    not support.DATABASE_URL,
    reason="DATABASE_URL is required",
)

REFRESH_PATH = "/api/v1/snapshot-refresh/recalculate"
PORTFOLIO_PATH = "/api/v1/portfolio/snapshot"
DASHBOARD_PATH = "/api/v1/dashboard/snapshot"
MANIFEST_FIELDS = (
    "timestamp",
    "granularity",
    "currency",
    "calculationVersion",
    "accounts",
)


async def _database_evidence(
    *,
    user_id: str,
    account_id: str,
    snapshot_id: str,
) -> tuple[list[TransactionModel], AccountSnapshotModel, NetWorthSnapshotModel, str]:
    engine = support._engine()
    async with AsyncSession(engine) as session:
        transactions = list(
            (
                await session.scalars(
                    select(TransactionModel)
                    .where(TransactionModel.account_id == account_id)
                    .order_by(TransactionModel.amount)
                )
            ).all()
        )
        account_snapshot = await session.get(AccountSnapshotModel, snapshot_id)
        net_worth = (
            await session.scalar(
                select(NetWorthSnapshotModel)
                .where(
                    NetWorthSnapshotModel.user_id == user_id,
                    NetWorthSnapshotModel.timestamp == account_snapshot.timestamp,
                    NetWorthSnapshotModel.currency == account_snapshot.currency,
                    NetWorthSnapshotModel.granularity == account_snapshot.granularity,
                )
                .limit(1)
            )
            if account_snapshot is not None
            else None
        )
        version = str(await session.scalar(text("SHOW server_version")))
        assert account_snapshot is not None
        assert net_worth is not None
        for transaction in transactions:
            session.expunge(transaction)
        session.expunge(account_snapshot)
        session.expunge(net_worth)
    await engine.dispose()
    return transactions, account_snapshot, net_worth, version


def test_cash_only_fixture_reaches_snapshots_and_both_exact_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = "r2-rb-cash-e2e"
    asyncio.run(support._seed(prefix, include_concurrent=False))
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path))
    app = support.create_app(support._settings())
    refresh_bucket = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(minutes=2)
    app.dependency_overrides[get_user_snapshot_refresh_clock] = lambda: lambda: refresh_bucket
    owner = f"{prefix}-owner"
    account = f"{prefix}-account"
    content = (support.FIXTURES / "account_statement.csv").read_bytes()
    try:
        with TestClient(app) as client:
            batch_id, parsed, normalized = support._create_and_prepare(
                client,
                user_id=owner,
                account_id=account,
                content=content,
                filename="cash-only-account-statement.csv",
            )
            completed = support._finish(
                client,
                user_id=owner,
                account_id=account,
                batch_id=batch_id,
            )
            refresh = client.post(REFRESH_PATH, headers=support._headers(owner))
            assert refresh.status_code == 200, refresh.text
            manifest = {field: deepcopy(refresh.json()[field]) for field in MANIFEST_FIELDS}
            manifest_before_reads = deepcopy(manifest)
            portfolio = client.post(
                PORTFOLIO_PATH,
                headers=support._headers(owner),
                json=manifest,
            )
            dashboard = client.post(
                DASHBOARD_PATH,
                headers=support._headers(owner),
                json=manifest,
            )

        assert parsed["rows_total"] == normalized["rows_normalized"] == 3
        assert completed["posted"]["rows_imported"] == 3
        assert completed["posted"]["snapshot_refresh_status"] in {"created", "replayed"}
        assert refresh.json()["selectedAccountSnapshotCount"] == 1
        assert refresh.json()["accounts"] == [
            {
                "accountId": account,
                "snapshotId": manifest["accounts"][0]["snapshotId"],
            }
        ]
        assert manifest == manifest_before_reads
        assert portfolio.status_code == 200, portfolio.text
        assert dashboard.status_code == 200, dashboard.text

        snapshot_id = manifest["accounts"][0]["snapshotId"]
        transactions, account_snapshot, net_worth, postgres_version = asyncio.run(
            _database_evidence(
                user_id=owner,
                account_id=account,
                snapshot_id=snapshot_id,
            )
        )
        assert postgres_version.startswith("16.")
        assert [transaction.amount for transaction in transactions] == [
            Decimal("-123.450000"),
            Decimal("-50.000000"),
            Decimal("10000.000000"),
        ]
        assert account_snapshot.cash_value == Decimal("9826.550000")
        assert account_snapshot.cash_value_by_currency == {"CZK": "9826.550000"}
        assert account_snapshot.investment_value == Decimal("0")
        assert account_snapshot.liabilities_value == Decimal("0")
        assert account_snapshot.total_value == Decimal("9826.550000")
        assert net_worth.cash_value == Decimal("9826.550000")
        assert net_worth.portfolio_value == Decimal("0")
        assert net_worth.liabilities_value == Decimal("0")
        assert net_worth.total_net_worth == Decimal("9826.550000")

        portfolio_payload = portfolio.json()
        dashboard_payload = dashboard.json()
        assert (
            portfolio_payload["timestamp"]
            == dashboard_payload["timestamp"]
            == manifest["timestamp"]
        )
        assert (
            portfolio_payload["granularity"]
            == dashboard_payload["granularity"]
            == manifest["granularity"]
        )
        assert portfolio_payload["currency"] == dashboard_payload["currency"] == "CZK"
        assert (
            portfolio_payload["calculationVersion"]
            == dashboard_payload["calculationVersion"]
            == manifest["calculationVersion"]
        )
        assert portfolio_payload["summary"]["cashValue"] == "9826.550000"
        assert portfolio_payload["summary"]["investmentValue"] == "0.000000"
        assert portfolio_payload["summary"]["liabilitiesValue"] == "0.000000"
        assert portfolio_payload["summary"]["totalValue"] == "9826.550000"
        assert dashboard_payload["summary"]["totalValue"] == "9826.550000"
        assert dashboard_payload["summary"]["investmentValue"] == "0.000000"
        assert dashboard_payload["summary"]["liabilitiesValue"] == "0.000000"
        assert dashboard_payload["summary"]["assetsValue"] == "9826.550000"
        assert {value["account"]["accountId"] for value in portfolio_payload["accounts"]} == {
            account
        }
        assert {value["accountId"] for value in dashboard_payload["accounts"]} == {account}
        assert portfolio_payload["summary"]["positionCount"] == 0
        assert dashboard_payload["summary"]["positionCount"] == 0
        assert dashboard_payload["assetTypeAllocations"] == []
        assert dashboard_payload["topPositions"] == []
    finally:
        asyncio.run(support._cleanup(prefix))
