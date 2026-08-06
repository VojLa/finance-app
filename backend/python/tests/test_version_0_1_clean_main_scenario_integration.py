"""Clean PostgreSQL proof for the supported version 0.1 production scenario."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
from collections.abc import Coroutine
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetAliasModel
from app.db.models.holdings import HoldingModel
from app.db.models.imports import ImportBatchModel, ImportLogModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.main import create_app
from app.modules.imports import posting_service

DATABASE_URL = os.getenv("DATABASE_URL")
EXPECTED_DATABASE = "finance_app_version_0_1_r8"
PYTHON_ROOT = Path(__file__).resolve().parents[1]
UV = shutil.which("uv")
USER_ID = "version-0-1-r8-user"
USER_EMAIL = f"{USER_ID}@example.test"
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="The dedicated R8 PostgreSQL DATABASE_URL is required.",
)

investment_support = cast(
    Any,
    importlib.import_module("tests.support.investment_fixture_e2e"),
)
market_support = cast(
    Any,
    importlib.import_module("tests.test_import_market_backed_refresh_integration"),
)
alias_support = cast(
    Any,
    importlib.import_module("tests.test_asset_alias_onboarding_e2e_integration"),
)


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _headers(*, binary: bool = False) -> dict[str, str]:
    return investment_support.headers(USER_ID, binary=binary)


async def _database_name_version_and_head() -> tuple[str, str, str]:
    engine = investment_support.engine()
    async with AsyncSession(engine) as session:
        value = (
            str(await session.scalar(text("SELECT current_database()"))),
            str(await session.scalar(text("SHOW server_version"))),
            str(await session.scalar(text("SELECT version_num FROM alembic_version"))),
        )
    await engine.dispose()
    return value


async def _counts() -> dict[str, int]:
    models = {
        "users": UserModel,
        "accounts": AccountModel,
        "memberships": AccountMemberModel,
        "batches": ImportBatchModel,
        "rows": ImportRowModel,
        "transactions": TransactionModel,
        "events": InvestmentEventModel,
        "movements": InvestmentMovementModel,
        "holdings": HoldingModel,
        "account_snapshots": AccountSnapshotModel,
        "net_worth_snapshots": NetWorthSnapshotModel,
        "prices": PriceSnapshotModel,
        "rates": ExchangeRateModel,
    }
    engine = investment_support.engine()
    async with AsyncSession(engine) as session:
        result = {
            name: int(await session.scalar(select(func.count()).select_from(model)) or 0)
            for name, model in models.items()
        }
    await engine.dispose()
    return result


async def _seed_user() -> None:
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    engine = investment_support.engine()
    async with AsyncSession(engine) as session:
        session.add(
            UserModel(
                id=USER_ID,
                email=USER_EMAIL,
                name="Version 0.1 R8 clean scenario",
                password_hash=None,
                base_currency="CZK",
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    await engine.dispose()


async def _financial_state() -> dict[str, Any]:
    engine = investment_support.engine()
    async with AsyncSession(engine) as session:
        accounts = tuple(
            (
                await session.scalars(
                    select(AccountModel)
                    .join(AccountMemberModel, AccountMemberModel.account_id == AccountModel.id)
                    .where(AccountMemberModel.user_id == USER_ID)
                    .order_by(AccountModel.name)
                )
            ).all()
        )
        account_ids = tuple(account.id for account in accounts)
        batches = tuple(
            (
                await session.scalars(
                    select(ImportBatchModel)
                    .where(ImportBatchModel.account_id.in_(account_ids))
                    .order_by(ImportBatchModel.created_at, ImportBatchModel.id)
                )
            ).all()
        )
        batch_ids = tuple(batch.id for batch in batches)
        rows = tuple(
            (
                await session.scalars(
                    select(ImportRowModel)
                    .where(ImportRowModel.import_batch_id.in_(batch_ids))
                    .order_by(ImportRowModel.import_batch_id, ImportRowModel.row_number)
                )
            ).all()
        )
        transactions = tuple(
            (
                await session.scalars(
                    select(TransactionModel)
                    .where(TransactionModel.account_id.in_(account_ids))
                    .order_by(TransactionModel.account_id, TransactionModel.external_id)
                )
            ).all()
        )
        events = tuple(
            (
                await session.scalars(
                    select(InvestmentEventModel)
                    .where(InvestmentEventModel.account_id.in_(account_ids))
                    .order_by(InvestmentEventModel.account_id, InvestmentEventModel.external_id)
                )
            ).all()
        )
        event_ids = tuple(event.id for event in events)
        movements = tuple(
            (
                await session.scalars(
                    select(InvestmentMovementModel)
                    .where(InvestmentMovementModel.event_id.in_(event_ids))
                    .order_by(InvestmentMovementModel.event_id, InvestmentMovementModel.id)
                )
            ).all()
        )
        holdings = tuple(
            (
                await session.scalars(
                    select(HoldingModel)
                    .where(HoldingModel.account_id.in_(account_ids))
                    .order_by(HoldingModel.account_id, HoldingModel.symbol)
                )
            ).all()
        )
        snapshots = tuple(
            (
                await session.scalars(
                    select(AccountSnapshotModel)
                    .where(AccountSnapshotModel.account_id.in_(account_ids))
                    .order_by(AccountSnapshotModel.timestamp, AccountSnapshotModel.account_id)
                )
            ).all()
        )
        snapshot_ids = tuple(snapshot.id for snapshot in snapshots)
        items = tuple(
            (
                await session.scalars(
                    select(AccountSnapshotItemModel)
                    .where(AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids))
                    .order_by(AccountSnapshotItemModel.snapshot_id, AccountSnapshotItemModel.symbol)
                )
            ).all()
        )
        net_worth = tuple(
            (
                await session.scalars(
                    select(NetWorthSnapshotModel)
                    .where(NetWorthSnapshotModel.user_id == USER_ID)
                    .order_by(NetWorthSnapshotModel.timestamp, NetWorthSnapshotModel.id)
                )
            ).all()
        )
        prices = tuple(
            (
                await session.scalars(
                    select(PriceSnapshotModel).order_by(
                        PriceSnapshotModel.listing_id,
                        PriceSnapshotModel.timestamp,
                        PriceSnapshotModel.id,
                    )
                )
            ).all()
        )
        rates = tuple(
            (
                await session.scalars(
                    select(ExchangeRateModel).order_by(
                        ExchangeRateModel.from_currency,
                        ExchangeRateModel.to_currency,
                        ExchangeRateModel.date,
                        ExchangeRateModel.id,
                    )
                )
            ).all()
        )
        aliases = tuple(
            (
                await session.scalars(
                    select(AssetAliasModel).order_by(
                        AssetAliasModel.provider,
                        AssetAliasModel.external_id,
                    )
                )
            ).all()
        )
        logs = tuple(
            (
                await session.scalars(
                    select(ImportLogModel)
                    .where(ImportLogModel.import_batch_id.in_(batch_ids))
                    .order_by(ImportLogModel.import_batch_id, ImportLogModel.created_at)
                )
            ).all()
        )
        for collection in (
            accounts,
            batches,
            rows,
            transactions,
            events,
            movements,
            holdings,
            snapshots,
            items,
            net_worth,
            prices,
            rates,
            aliases,
            logs,
        ):
            for row in collection:
                session.expunge(row)
    await engine.dispose()
    return {
        "accounts": accounts,
        "batches": batches,
        "rows": rows,
        "transactions": transactions,
        "events": events,
        "movements": movements,
        "holdings": holdings,
        "snapshots": snapshots,
        "items": items,
        "net_worth": net_worth,
        "prices": prices,
        "rates": rates,
        "aliases": aliases,
        "logs": logs,
    }


def _create_account(
    client: TestClient,
    *,
    name: str,
    account_type: str,
    currency: str,
) -> str:
    response = client.post(
        "/api/v1/accounts",
        headers=_headers(),
        json={"name": name, "type": account_type, "currency": currency},
    )
    assert response.status_code == 201, response.text
    value = response.json()
    assert value["name"] == name
    assert value["type"] == account_type
    assert value["currency"] == currency
    assert value["role"] == "owner"
    return str(value["id"])


def _stage(
    client: TestClient,
    *,
    source: Any,
    account_id: str,
    filename: str,
    content: bytes,
) -> dict[str, Any]:
    return investment_support.run_stages(
        client,
        source=source,
        user_id=USER_ID,
        account_id=account_id,
        content=content,
        filename=filename,
        post=False,
    )


def _post(client: TestClient, *, account_id: str, batch_id: str) -> dict[str, Any]:
    return investment_support.post_batch(
        client,
        user_id=USER_ID,
        account_id=account_id,
        batch_id=batch_id,
    )


def _onboard(provider: str, external_id: str, asset_id: str) -> dict[str, Any]:
    assert DATABASE_URL is not None
    assert UV is not None
    inventory = alias_support._cli(["list-unresolved", "--provider", provider])
    assert inventory.returncode == 0, inventory.stderr
    assert inventory.stderr == ""
    item = next(value for value in json.loads(inventory.stdout) if value["assetId"] == asset_id)
    arguments = alias_support._onboard_arguments(
        item,
        provider=provider,
        external_id=external_id,
    )
    created = alias_support._cli(arguments)
    assert created.returncode == 0, created.stderr
    assert created.stderr == ""
    value = json.loads(created.stdout)
    assert value["disposition"] == "created"
    replayed = alias_support._cli(arguments)
    assert replayed.returncode == 0, replayed.stderr
    assert json.loads(replayed.stdout) == {**value, "disposition": "replayed"}
    return value


def _manifest(refresh: dict[str, Any]) -> dict[str, Any]:
    return {field: deepcopy(refresh[field]) for field in investment_support.MANIFEST_FIELDS}


def _public_reads(
    client: TestClient,
    *,
    refresh: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = _manifest(refresh)
    history = client.get(
        "/api/v1/portfolio/history?range=ALL",
        headers=_headers(),
    )
    portfolio = client.post(
        "/api/v1/portfolio/snapshot",
        headers=_headers(),
        json=manifest,
    )
    dashboard = client.post(
        "/api/v1/dashboard/snapshot",
        headers=_headers(),
        json=manifest,
    )
    assert portfolio.status_code == dashboard.status_code == history.status_code == 200, (
        portfolio.text,
        dashboard.text,
        history.text,
    )
    return portfolio.json(), dashboard.json(), history.json()


def _canonical_tuples(state: dict[str, Any]) -> dict[str, tuple[Any, ...]]:
    return {
        "transactions": tuple(
            (row.account_id, row.external_id, row.date, row.amount, row.currency)
            for row in state["transactions"]
        ),
        "events": tuple(
            (row.account_id, row.external_id, row.date, row.type) for row in state["events"]
        ),
        "movements": tuple(
            (
                row.account_id,
                row.event_id,
                row.kind,
                row.direction,
                row.quantity,
                row.currency,
                row.value_amount,
                row.value_currency,
            )
            for row in state["movements"]
        ),
        "holdings": tuple(
            (
                row.account_id,
                row.asset_id,
                row.listing_id,
                row.quantity,
                row.avg_buy_price,
                row.currency,
            )
            for row in state["holdings"]
        ),
    }


def test_clean_main_scenario_reaches_exact_browser_owned_read_models_and_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert DATABASE_URL is not None
    database, version, migration = _run(_database_name_version_and_head())
    assert database == EXPECTED_DATABASE
    assert version.startswith("16.")
    assert migration == "3h0001twdata"
    assert _run(_counts()) == {
        "users": 0,
        "accounts": 0,
        "memberships": 0,
        "batches": 0,
        "rows": 0,
        "transactions": 0,
        "events": 0,
        "movements": 0,
        "holdings": 0,
        "account_snapshots": 0,
        "net_worth_snapshots": 0,
        "prices": 0,
        "rates": 0,
    }

    _run(_seed_user())
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path / "imports"))
    base_bucket = datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0) - timedelta(
        minutes=8
    )
    posting_clock = {"value": base_bucket}
    monkeypatch.setattr(posting_service, "_current_timestamp", lambda: posting_clock["value"])
    harness = market_support._ProviderHarness(observed_at=base_bucket - timedelta(minutes=1))
    app = create_app(market_support._settings())
    alias_support._install_market_overrides(
        app,
        harness,
        manual_bucket=base_bucket + timedelta(minutes=5),
    )

    with TestClient(app) as client:
        account_ids = {
            "trading212": _create_account(
                client,
                name="R8 Trading212",
                account_type="broker",
                currency="EUR",
            ),
            "anycoin": _create_account(
                client,
                name="R8 Anycoin",
                account_type="exchange",
                currency="EUR",
            ),
            "raiffeisenbank": _create_account(
                client,
                name="R8 Raiffeisenbank",
                account_type="bank",
                currency="CZK",
            ),
        }
        assert len(set(account_ids.values())) == 3

        trading = _stage(
            client,
            source=investment_support.ImportSource.trading212,
            account_id=account_ids["trading212"],
            filename="r8-trading212.csv",
            content=investment_support.fixture(
                investment_support.ImportSource.trading212,
                "main_scenario.csv",
            ),
        )
        trading_asset, trading_listing = _run(
            investment_support.seed_asset_listing(
                "version-0-1-r8-trading212",
                source=investment_support.ImportSource.trading212,
            )
        )
        posting_clock["value"] = base_bucket
        assert (
            _post(
                client,
                account_id=account_ids["trading212"],
                batch_id=trading["batch_id"],
            )["snapshot_refresh_status"]
            == "unavailable"
        )

        anycoin = _stage(
            client,
            source=investment_support.ImportSource.anycoin,
            account_id=account_ids["anycoin"],
            filename="r8-anycoin.csv",
            content=investment_support.fixture(
                investment_support.ImportSource.anycoin,
                "history.csv",
            ),
        )
        anycoin_asset, anycoin_listing = _run(
            investment_support.seed_asset_listing(
                "version-0-1-r8-anycoin",
                source=investment_support.ImportSource.anycoin,
            )
        )
        posting_clock["value"] = base_bucket + timedelta(minutes=1)
        assert (
            _post(
                client,
                account_id=account_ids["anycoin"],
                batch_id=anycoin["batch_id"],
            )["snapshot_refresh_status"]
            == "unavailable"
        )
        assert harness.calls == []

        twelve_alias = _onboard(
            "twelve_data",
            '{"symbol":"AAPL","mic_code":"XNAS"}',
            trading_asset,
        )
        coin_alias = _onboard("coingecko", "bitcoin", anycoin_asset)
        assert twelve_alias["assetId"] == trading_asset
        assert coin_alias["assetId"] == anycoin_asset

        rb_content = investment_support.fixture(
            investment_support.ImportSource.raiffeisenbank,
            "account_statement.csv",
        )
        rb = _stage(
            client,
            source=investment_support.ImportSource.raiffeisenbank,
            account_id=account_ids["raiffeisenbank"],
            filename="r8-raiffeisenbank.csv",
            content=rb_content,
        )
        posting_clock["value"] = base_bucket + timedelta(minutes=2)
        rb_post = _post(
            client,
            account_id=account_ids["raiffeisenbank"],
            batch_id=rb["batch_id"],
        )
        assert rb_post["snapshot_refresh_status"] == "created"

        posting_clock["value"] = base_bucket
        trading_recovery = _post(
            client,
            account_id=account_ids["trading212"],
            batch_id=trading["batch_id"],
        )
        posting_clock["value"] = base_bucket + timedelta(minutes=1)
        anycoin_recovery = _post(
            client,
            account_id=account_ids["anycoin"],
            batch_id=anycoin["batch_id"],
        )
        assert trading_recovery["snapshot_refresh_status"] == "created"
        assert anycoin_recovery["snapshot_refresh_status"] == "created"

        before_failed_refresh = _run(_financial_state())
        harness.twelve_status = 429
        failed_refresh = client.post(
            "/api/v1/snapshot-refresh/recalculate",
            headers=_headers(),
        )
        assert failed_refresh.status_code == 409
        assert failed_refresh.json() == {
            "error": {
                "code": "snapshot_refresh_unavailable",
                "message": ("Snapshot refresh cannot be completed from the current account data."),
                "request_id": failed_refresh.json()["error"]["request_id"],
            }
        }
        assert not any(
            forbidden in failed_refresh.text
            for forbidden in ("traceback", "SELECT ", "api_key", "raw_data")
        )
        after_failed_refresh = _run(_financial_state())
        assert _canonical_tuples(after_failed_refresh) == _canonical_tuples(before_failed_refresh)
        assert tuple(row.id for row in after_failed_refresh["prices"]) == tuple(
            row.id for row in before_failed_refresh["prices"]
        )
        assert tuple(row.id for row in after_failed_refresh["rates"]) == tuple(
            row.id for row in before_failed_refresh["rates"]
        )
        assert tuple(row.id for row in after_failed_refresh["snapshots"]) == tuple(
            row.id for row in before_failed_refresh["snapshots"]
        )
        assert tuple(row.id for row in after_failed_refresh["net_worth"]) == tuple(
            row.id for row in before_failed_refresh["net_worth"]
        )

        harness.twelve_status = 200
        refresh_response = client.post(
            "/api/v1/snapshot-refresh/recalculate",
            headers=_headers(),
        )
        assert refresh_response.status_code == 200, refresh_response.text
        refresh = refresh_response.json()
        assert refresh["currency"] == "CZK"
        assert refresh["selectedAccountSnapshotCount"] == 3
        assert {item["accountId"] for item in refresh["accounts"]} == set(account_ids.values())
        portfolio, dashboard, history = _public_reads(client, refresh=refresh)

        before_reimport = _run(_financial_state())
        canonical_before = _canonical_tuples(before_reimport)
        public_before = deepcopy((portfolio, dashboard, history))
        snapshot_ids_before = tuple(row.id for row in before_reimport["snapshots"])
        net_worth_ids_before = tuple(row.id for row in before_reimport["net_worth"])
        market_ids_before = (
            tuple(row.id for row in before_reimport["prices"]),
            tuple(row.id for row in before_reimport["rates"]),
        )

        for offset, (source, account_key, filename, content) in enumerate(
            (
                (
                    investment_support.ImportSource.trading212,
                    "trading212",
                    "r8-trading212-replay.csv",
                    investment_support.fixture(
                        investment_support.ImportSource.trading212,
                        "main_scenario.csv",
                    )
                    + b"\n",
                ),
                (
                    investment_support.ImportSource.anycoin,
                    "anycoin",
                    "r8-anycoin-replay.csv",
                    investment_support.fixture(
                        investment_support.ImportSource.anycoin,
                        "history.csv",
                    )
                    + b"\n",
                ),
                (
                    investment_support.ImportSource.raiffeisenbank,
                    "raiffeisenbank",
                    "r8-raiffeisenbank-replay.csv",
                    rb_content + b"\n",
                ),
            ),
            start=6,
        ):
            posting_clock["value"] = base_bucket + timedelta(minutes=offset)
            replay = investment_support.run_stages(
                client,
                source=source,
                user_id=USER_ID,
                account_id=account_ids[account_key],
                content=content,
                filename=filename,
                post=True,
            )
            assert replay["post"]["rows_imported"] == 0
            assert replay["post"]["snapshot_refresh_status"] == "not_required"

        refresh_replay_response = client.post(
            "/api/v1/snapshot-refresh/recalculate",
            headers=_headers(),
        )
        assert refresh_replay_response.status_code == 200
        refresh_replay = refresh_replay_response.json()
        assert refresh_replay["netWorthStatus"] == "replayed"
        assert _manifest(refresh_replay) == _manifest(refresh)
        replay_public = _public_reads(client, refresh=refresh_replay)

    after_reimport = _run(_financial_state())
    assert _canonical_tuples(after_reimport) == canonical_before
    assert tuple(row.id for row in after_reimport["snapshots"]) == snapshot_ids_before
    assert tuple(row.id for row in after_reimport["net_worth"]) == net_worth_ids_before
    assert (
        tuple(row.id for row in after_reimport["prices"]),
        tuple(row.id for row in after_reimport["rates"]),
    ) == market_ids_before
    assert replay_public == public_before

    accounts_by_name = {row.name: row for row in after_reimport["accounts"]}
    assert {name: (row.type.value, row.currency) for name, row in accounts_by_name.items()} == {
        "R8 Anycoin": ("exchange", "EUR"),
        "R8 Raiffeisenbank": ("bank", "CZK"),
        "R8 Trading212": ("broker", "EUR"),
    }
    assert len(after_reimport["holdings"]) == 2
    holdings_by_account = {row.account_id: row for row in after_reimport["holdings"]}
    assert holdings_by_account[account_ids["trading212"]].quantity == Decimal("2")
    assert holdings_by_account[account_ids["anycoin"]].quantity == Decimal("0.01")
    trading_fees = tuple(
        row
        for row in after_reimport["movements"]
        if row.account_id == account_ids["trading212"] and row.kind.value == "fee"
    )
    assert len(trading_fees) == 1
    assert (
        trading_fees[0].quantity,
        trading_fees[0].currency,
        trading_fees[0].direction.value,
    ) == (Decimal("1.25"), "EUR", "out")
    assert {(row.provider.value, row.external_id) for row in after_reimport["aliases"]} == {
        ("coingecko", "bitcoin"),
        ("twelve_data", '{"symbol":"AAPL","mic_code":"XNAS"}'),
    }
    assert {row.listing_id for row in after_reimport["prices"]} == {
        trading_listing,
        anycoin_listing,
    }
    assert all(row.from_currency == "EUR" for row in after_reimport["rates"])
    assert all(row.to_currency == "CZK" for row in after_reimport["rates"])
    assert all(row.source.value == "cnb" for row in after_reimport["rates"])
    assert not any(row.from_currency == "CZK" for row in after_reimport["rates"])
    assert ("twelve_data", "AAPL:XNAS") in harness.calls
    assert ("coingecko", "bitcoin") in harness.calls
    cnb_dates = [identity for provider, identity in harness.calls if provider == "cnb"]
    assert cnb_dates
    assert "20.07.2026" in cnb_dates

    latest_snapshots = {
        row.account_id: row
        for row in after_reimport["snapshots"]
        if row.timestamp == base_bucket + timedelta(minutes=5)
    }
    assert set(latest_snapshots) == set(account_ids.values())
    assert {item["snapshotId"] for item in refresh["accounts"]} == {
        row.id for row in latest_snapshots.values()
    }
    assert all(row.currency == "CZK" for row in latest_snapshots.values())
    persisted_rate_ids = {row.id for row in after_reimport["rates"]}
    rb_rates = latest_snapshots[account_ids["raiffeisenbank"]].exchange_rates
    trading_rates = latest_snapshots[account_ids["trading212"]].exchange_rates
    anycoin_rates = latest_snapshots[account_ids["anycoin"]].exchange_rates
    assert rb_rates == {
        "version": 1,
        "snapshotRates": [],
        "historicalRateIds": [],
    }
    assert trading_rates is not None and anycoin_rates is not None
    for evidence in (trading_rates, anycoin_rates):
        assert evidence["version"] == 1
        assert len(evidence["snapshotRates"]) == 1
        selected = evidence["snapshotRates"][0]
        assert (
            selected["from"],
            selected["to"],
            selected["source"],
            selected["rate"],
        ) == ("EUR", "CZK", "cnb", "25.00000000")
        assert selected["rateId"] in persisted_rate_ids
    assert len(trading_rates["historicalRateIds"]) == 1
    assert set(trading_rates["historicalRateIds"]).issubset(persisted_rate_ids)
    assert anycoin_rates["historicalRateIds"] == []
    rb_snapshot = latest_snapshots[account_ids["raiffeisenbank"]]
    assert rb_snapshot.cash_value == Decimal("9826.550000")
    assert rb_snapshot.cash_value_by_currency == {"CZK": "9826.550000"}
    assert rb_snapshot.investment_value == Decimal("0")
    assert rb_snapshot.total_value == Decimal("9826.550000")
    assert latest_snapshots[account_ids["trading212"]].cash_value_by_currency == {
        "EUR": "804.000000"
    }
    assert latest_snapshots[account_ids["anycoin"]].cash_value_by_currency == {"EUR": "-490.000000"}
    latest_net_worth = after_reimport["net_worth"][-1]
    assert latest_net_worth.timestamp == base_bucket + timedelta(minutes=5)
    assert latest_net_worth.currency == "CZK"
    assert latest_net_worth.cash_value == sum(
        (row.cash_value for row in latest_snapshots.values()),
        Decimal(),
    )
    assert latest_net_worth.portfolio_value == sum(
        (row.investment_value for row in latest_snapshots.values()),
        Decimal(),
    )
    assert latest_net_worth.liabilities_value == Decimal("0")
    assert latest_net_worth.total_net_worth == (
        latest_net_worth.cash_value
        + latest_net_worth.portfolio_value
        - latest_net_worth.liabilities_value
    )

    portfolio, dashboard, history = public_before
    assert set(portfolio) == {
        "timestamp",
        "granularity",
        "currency",
        "calculationVersion",
        "summary",
        "accounts",
    }
    assert portfolio["currency"] == dashboard["currency"] == history["currency"] == "CZK"
    assert {row["account"]["accountId"] for row in portfolio["accounts"]} == set(
        account_ids.values()
    )
    assert {row["accountId"] for row in dashboard["accounts"]} == set(account_ids.values())
    assert portfolio["summary"]["totalValue"] == dashboard["summary"]["totalValue"]
    assert portfolio["summary"]["investmentValue"] == dashboard["summary"]["investmentValue"]
    assert portfolio["summary"]["liabilitiesValue"] == dashboard["summary"]["liabilitiesValue"]
    assert portfolio["summary"]["cashByCurrency"] == [
        {"currency": "CZK", "amount": "9826.550000"},
        {"currency": "EUR", "amount": "314.000000"},
    ]
    assert portfolio["summary"]["netDepositsByCurrency"] == [
        {"currency": "EUR", "amount": "1000.000000"}
    ]
    assert len(portfolio["accounts"]) == len(dashboard["accounts"]) == 3
    assert sum(len(account["positions"]) for account in portfolio["accounts"]) == 2
    assert len(dashboard["topPositions"]) == 2
    assert history["range"] == "ALL"
    assert history["points"]
    assert [point["timestamp"] for point in history["points"]] == sorted(
        point["timestamp"] for point in history["points"]
    )
    assert len({point["timestamp"] for point in history["points"]}) == len(history["points"])
    assert all(
        set(point)
        == {
            "timestamp",
            "cashValue",
            "investmentValue",
            "liabilitiesValue",
            "netWorthValue",
        }
        for point in history["points"]
    )
    public_document = json.dumps(public_before, sort_keys=True)
    for forbidden in (
        "selectedAccountSnapshotIds",
        "exchangeRates",
        "price_ids",
        "providerSymbol",
        "requestId",
        "traceback",
    ):
        assert forbidden not in public_document

    source_guard = (PYTHON_ROOT / "app" / "modules" / "snapshot_refresh" / "plan.py").read_text(
        encoding="utf-8"
    )
    api_guard = (PYTHON_ROOT / "app" / "modules" / "snapshot_refresh" / "api.py").read_text(
        encoding="utf-8"
    )
    assert '"CZK"' not in source_guard
    assert '"CZK"' not in api_guard
    cnb_provider = (PYTHON_ROOT / "app" / "modules" / "fx" / "providers" / "cnb.py").read_text(
        encoding="utf-8"
    )
    assert 'requirement.from_currency == "CZK"' in cnb_provider
    assert 'requirement.to_currency != "CZK"' in cnb_provider
    assert "1 /" not in cnb_provider
