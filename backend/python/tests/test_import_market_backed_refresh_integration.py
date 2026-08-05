from __future__ import annotations

import asyncio
import importlib
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from support import investment_fixture_e2e as investment_support
from support.cnb_fx import cnb_xml

from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import (
    AssetAliasProvider,
    ExchangeRateSource,
    ImportLogEvent,
    ImportSource,
    PriceSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.imports import ImportBatchModel, ImportLogModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.db.models.users import UserModel
from app.main import create_app
from app.modules.imports.api import (
    get_import_market_backed_snapshot_refresh_service,
)
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.snapshot_refresh.executor import (
    ExecuteUserSnapshotRefreshCommand,
    SnapshotRefreshExecutionConflictError,
)
from app.modules.snapshot_refresh.market_backed_service import (
    MarketBackedSnapshotRefreshService,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="PostgreSQL integration test requires DATABASE_URL.",
)

rb_support = cast(
    Any,
    importlib.import_module("tests.test_raiffeisenbank_source_integration"),
)
TWELVE_API_KEY = "r5b3c-test-key"


def _observed_at() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0) - timedelta(minutes=1)


def _settings() -> Settings:
    assert DATABASE_URL is not None
    return Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        log_level="ERROR",
        log_json=False,
        internal_auth_secret=investment_support.SECRET,
        twelve_data_api_key=TWELVE_API_KEY,
        _env_file=None,
    )


class _ProviderHarness:
    def __init__(
        self,
        *,
        observed_at: datetime,
        twelve_status: int = 200,
        coingecko_stale: bool = False,
        cnb_status: int = 200,
        fail_on_any_call: bool = False,
        coin_price: Decimal = Decimal("414.5888"),
    ) -> None:
        self.observed_at = observed_at
        self.twelve_status = twelve_status
        self.coingecko_stale = coingecko_stale
        self.cnb_status = cnb_status
        self.fail_on_any_call = fail_on_any_call
        self.coin_price = coin_price
        self.calls: list[tuple[str, str]] = []

    def transports(
        self,
        session: AsyncSession,
    ) -> tuple[httpx.MockTransport, httpx.MockTransport, httpx.MockTransport]:
        observed_epoch = int(self.observed_at.replace(tzinfo=UTC).timestamp())
        coin_at = (
            self.observed_at - timedelta(days=30) if self.coingecko_stale else self.observed_at
        )
        coin_epoch = int(coin_at.replace(tzinfo=UTC).timestamp())

        def before_call(provider: str, identity: str) -> None:
            assert not session.in_transaction()
            if self.fail_on_any_call:
                raise AssertionError(f"unexpected {provider} provider call")
            self.calls.append((provider, identity))

        def twelve_handler(request: httpx.Request) -> httpx.Response:
            symbol = request.url.params["symbol"]
            mic_code = request.url.params["mic_code"]
            before_call("twelve_data", f"{symbol}:{mic_code}")
            if self.twelve_status != 200:
                return httpx.Response(
                    self.twelve_status,
                    headers={"content-type": "application/json"},
                    content=b'{"status":"error"}',
                )
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "symbol": symbol,
                    "mic_code": mic_code,
                    "currency": "EUR",
                    "datetime": self.observed_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "timestamp": observed_epoch,
                    "last_quote_at": observed_epoch,
                    "close": "225.3200000000",
                },
            )

        def coingecko_handler(request: httpx.Request) -> httpx.Response:
            coin_id = request.url.params["ids"]
            before_call("coingecko", coin_id)
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    coin_id: {
                        "eur": float(self.coin_price),
                        "last_updated_at": coin_epoch,
                    }
                },
            )

        def cnb_handler(request: httpx.Request) -> httpx.Response:
            requested = request.url.params["date"]
            before_call("cnb", requested)
            if self.cnb_status != 200:
                return httpx.Response(
                    self.cnb_status,
                    headers={"content-type": "text/xml"},
                    content=b"unavailable",
                )
            publication = datetime.strptime(requested, "%d.%m.%Y").date()
            return httpx.Response(
                200,
                headers={"content-type": "text/xml"},
                content=cnb_xml(
                    publication,
                    (
                        ("EUR", "1", "25,000"),
                        ("USD", "1", "23,000"),
                    ),
                ),
            )

        return (
            httpx.MockTransport(twelve_handler),
            httpx.MockTransport(coingecko_handler),
            httpx.MockTransport(cnb_handler),
        )


def _install_market_override(
    app: Any,
    harness: _ProviderHarness,
    *,
    snapshot_executor: object | None = None,
) -> None:
    def override(
        session: AsyncSession = Depends(get_db_session),
    ) -> MarketBackedSnapshotRefreshService:
        twelve, coingecko, cnb = harness.transports(session)

        def factory(active_session: AsyncSession, settings: Settings):
            return create_production_market_evidence_service(
                active_session,
                settings,
                http_transport=cnb,
                coingecko_http_transport=coingecko,
                twelve_data_http_transport=twelve,
            )

        return MarketBackedSnapshotRefreshService(
            session,
            _settings(),
            market_service_factory=factory,
            snapshot_executor=snapshot_executor,  # type: ignore[arg-type]
        )

    app.dependency_overrides[get_import_market_backed_snapshot_refresh_service] = override


class _ConflictingSnapshotExecutor:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, _command: ExecuteUserSnapshotRefreshCommand) -> None:
        self.calls += 1
        raise SnapshotRefreshExecutionConflictError


async def _add_alias(
    prefix: str,
    *,
    provider: AssetAliasProvider,
    external_id: str,
    suffix: str = "one",
) -> None:
    engine = investment_support.engine()
    async with AsyncSession(engine) as session:
        session.add(
            AssetAliasModel(
                id=f"{prefix}-alias-{suffix}",
                asset_id=f"{prefix}-asset",
                provider=provider,
                external_id=external_id,
                created_at=datetime.now(UTC).replace(tzinfo=None, microsecond=0),
            )
        )
        await session.commit()
    await engine.dispose()


async def _configure_trading_czk(prefix: str) -> None:
    engine = investment_support.engine()
    async with AsyncSession(engine) as session:
        user = await session.get(UserModel, f"{prefix}-owner")
        assert user is not None
        user.base_currency = "CZK"
        await session.commit()
    await engine.dispose()


async def _database_state(prefix: str) -> dict[str, Any]:
    engine = investment_support.engine()
    account_id = f"{prefix}-account"
    user_id = f"{prefix}-owner"
    async with AsyncSession(engine) as session:
        batch = await session.scalar(
            select(ImportBatchModel).where(ImportBatchModel.account_id == account_id)
        )
        assert batch is not None
        snapshots = tuple(
            (
                await session.scalars(
                    select(AccountSnapshotModel)
                    .where(AccountSnapshotModel.account_id == account_id)
                    .order_by(AccountSnapshotModel.id)
                )
            ).all()
        )
        net_worth = tuple(
            (
                await session.scalars(
                    select(NetWorthSnapshotModel)
                    .where(NetWorthSnapshotModel.user_id == user_id)
                    .order_by(NetWorthSnapshotModel.id)
                )
            ).all()
        )
        holdings = tuple(
            (
                await session.scalars(
                    select(HoldingModel).where(HoldingModel.account_id == account_id)
                )
            ).all()
        )
        prices = tuple(
            (
                await session.scalars(
                    select(PriceSnapshotModel)
                    .join(
                        AssetListingModel,
                        AssetListingModel.id == PriceSnapshotModel.listing_id,
                    )
                    .where(AssetListingModel.id == f"{prefix}-listing")
                    .order_by(PriceSnapshotModel.id)
                )
            ).all()
        )
        logs = tuple(
            (
                await session.scalars(
                    select(ImportLogModel)
                    .where(ImportLogModel.import_batch_id == batch.id)
                    .order_by(ImportLogModel.id)
                )
            ).all()
        )
        rates = tuple(
            (
                await session.scalars(
                    select(ExchangeRateModel)
                    .where(ExchangeRateModel.source == ExchangeRateSource.cnb)
                    .order_by(ExchangeRateModel.id)
                )
            ).all()
        )
        version = str(await session.scalar(text("SHOW server_version")))
        for collection in (snapshots, net_worth, holdings, prices, logs, rates):
            for row in collection:
                session.expunge(row)
        session.expunge(batch)
    await engine.dispose()
    return {
        "batch": batch,
        "snapshots": snapshots,
        "net_worth": net_worth,
        "holdings": holdings,
        "prices": prices,
        "logs": logs,
        "rates": rates,
        "version": version,
    }


async def _delete_cnb_rates() -> None:
    engine = investment_support.engine()
    async with AsyncSession(engine) as session:
        await session.execute(
            delete(ExchangeRateModel).where(ExchangeRateModel.source == ExchangeRateSource.cnb)
        )
        await session.commit()
    await engine.dispose()


async def _cleanup(prefix: str) -> None:
    await investment_support.cleanup(prefix)
    engine = investment_support.engine()
    async with AsyncSession(engine) as session:
        asset_ids = tuple(
            (
                await session.scalars(
                    select(AssetModel.id).where(AssetModel.id.startswith(f"{prefix}-"))
                )
            ).all()
        )
        if asset_ids:
            await session.execute(
                delete(AssetAliasModel).where(AssetAliasModel.asset_id.in_(asset_ids))
            )
            await session.execute(
                delete(AssetListingModel).where(AssetListingModel.asset_id.in_(asset_ids))
            )
            await session.execute(delete(AssetModel).where(AssetModel.id.in_(asset_ids)))
        await session.commit()
    await engine.dispose()


def _assert_read_parity(
    app: Any,
    *,
    headers: dict[str, str],
    account_id: str,
    state: dict[str, Any],
) -> None:
    snapshot = state["snapshots"][0]
    manifest = {
        "timestamp": snapshot.timestamp.isoformat(),
        "granularity": snapshot.granularity.value,
        "currency": snapshot.currency,
        "calculationVersion": snapshot.calculation_version,
        "accounts": [{"accountId": account_id, "snapshotId": snapshot.id}],
    }
    with TestClient(app) as client:
        portfolio = client.post(
            "/api/v1/portfolio/snapshot",
            headers=headers,
            json=manifest,
        )
        dashboard = client.post(
            "/api/v1/dashboard/snapshot",
            headers=headers,
            json=manifest,
        )
    assert portfolio.status_code == dashboard.status_code == 200
    expected_total = str(snapshot.total_value.quantize(Decimal("0.000001")))
    assert portfolio.json()["summary"]["totalValue"] == expected_total
    assert dashboard.json()["summary"]["totalValue"] == expected_total
    assert state["net_worth"][0].total_net_worth == snapshot.total_value


def test_raiffeisenbank_import_uses_empty_market_plan_and_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = f"r5b3c-rb-{uuid4().hex[:10]}"
    owner = f"{prefix}-owner"
    account = f"{prefix}-account"
    asyncio.run(rb_support._seed(prefix, include_concurrent=False))
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path))
    app = create_app(rb_support._settings())
    harness = _ProviderHarness(observed_at=_observed_at(), fail_on_any_call=True)
    _install_market_override(app, harness)
    content = (rb_support.FIXTURES / "account_statement.csv").read_bytes()
    try:
        with TestClient(app) as client:
            batch_id, parsed, normalized = rb_support._create_and_prepare(
                client,
                user_id=owner,
                account_id=account,
                content=content,
                filename="r5b3c-rb.csv",
            )
            completed = rb_support._finish(
                client,
                user_id=owner,
                account_id=account,
                batch_id=batch_id,
            )
            replay = client.post(
                f"/api/v1/accounts/{account}/imports/{batch_id}/post",
                headers=rb_support._headers(owner),
            )
            assert replay.status_code == 200, replay.text

        state = asyncio.run(_database_state(prefix))
        assert state["version"].startswith("16.")
        assert parsed["rows_total"] == normalized["rows_normalized"] == 3
        assert completed["posted"]["snapshot_refresh_status"] == "created"
        assert replay.json()["snapshot_refresh_status"] == "replayed"
        assert harness.calls == []
        assert state["prices"] == state["holdings"] == ()
        assert len(state["snapshots"]) == len(state["net_worth"]) == 1
        account_snapshot = state["snapshots"][0]
        net_worth = state["net_worth"][0]
        assert account_snapshot.cash_value == net_worth.cash_value == Decimal("9826.550000")
        assert account_snapshot.total_value == net_worth.total_net_worth
        _assert_read_parity(
            app,
            headers=rb_support._headers(owner),
            account_id=account,
            state=state,
        )
    finally:
        asyncio.run(rb_support._cleanup(prefix))


@pytest.mark.parametrize(
    ("source", "filename", "provider", "alias", "expected_call"),
    [
        (
            ImportSource.trading212,
            "activity.csv",
            AssetAliasProvider.twelve_data,
            '{"symbol":"AAPL","mic_code":"XNAS"}',
            ("twelve_data", "AAPL:XNAS"),
        ),
        (
            ImportSource.anycoin,
            "history.csv",
            AssetAliasProvider.coingecko,
            "bitcoin",
            ("coingecko", "bitcoin"),
        ),
    ],
)
def test_investment_import_uses_exact_provider_alias_and_replays(
    source: ImportSource,
    filename: str,
    provider: AssetAliasProvider,
    alias: str,
    expected_call: tuple[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = f"r5b3c-{source.value}-{uuid4().hex[:10]}"
    user_id, account_id = asyncio.run(investment_support.seed_identity(prefix, source=source))
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path / source.value))
    observed_at = _observed_at()
    harness = _ProviderHarness(observed_at=observed_at)
    app = create_app(_settings())
    _install_market_override(app, harness)
    try:
        with TestClient(app) as client:
            staged = investment_support.run_stages(
                client,
                source=source,
                user_id=user_id,
                account_id=account_id,
                content=investment_support.fixture(source, filename),
                filename=filename,
                post=False,
            )
            asyncio.run(investment_support.seed_asset_listing(prefix, source=source))
            asyncio.run(_add_alias(prefix, provider=provider, external_id=alias))
            if source is ImportSource.trading212:
                asyncio.run(_configure_trading_czk(prefix))
            first = investment_support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=staged["batch_id"],
            )
            second = investment_support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=staged["batch_id"],
            )

        state = asyncio.run(_database_state(prefix))
        assert state["version"].startswith("16.")
        assert first["snapshot_refresh_status"] == "created"
        assert second["snapshot_refresh_status"] == "replayed"
        assert len(state["holdings"]) == len(state["prices"]) == 1
        assert len(state["snapshots"]) == len(state["net_worth"]) == 1
        assert state["prices"][0].timestamp == observed_at
        assert state["prices"][0].price == (
            Decimal("225.3200000000")
            if source is ImportSource.trading212
            else Decimal("414.5888000000")
        )
        assert state["prices"][0].source == (
            PriceSource.twelve_data if source is ImportSource.trading212 else PriceSource.coingecko
        )
        assert harness.calls.count(expected_call) == 2
        if source is ImportSource.trading212:
            assert not any(call[0] == "coingecko" for call in harness.calls)
            requested_dates = [value for name, value in harness.calls if name == "cnb"]
            assert set(requested_dates) == {
                "20.07.2026",
                "21.07.2026",
                state["batch"].completed_at.strftime("%d.%m.%Y"),
            }
            assert state["rates"]
        else:
            assert not any(call[0] in {"twelve_data", "cnb"} for call in harness.calls)
        serialized_logs = json.dumps(
            [
                {
                    "event": log.event.value,
                    "message": log.message,
                }
                for log in state["logs"]
            ],
            sort_keys=True,
        )
        assert "price_ids" not in serialized_logs
        assert "exchange_rate_ids" not in serialized_logs
        assert "provider_symbol" not in serialized_logs
        assert set(first) == set(second)
        _assert_read_parity(
            app,
            headers=investment_support.headers(user_id),
            account_id=account_id,
            state=state,
        )
    finally:
        asyncio.run(_cleanup(prefix))
        asyncio.run(_delete_cnb_rates())


@pytest.mark.parametrize(
    ("source", "provider", "alias", "failure"),
    [
        (
            ImportSource.trading212,
            AssetAliasProvider.twelve_data,
            '{"symbol":"AAPL","mic_code":"XNAS"}',
            "twelve-429",
        ),
        (
            ImportSource.anycoin,
            AssetAliasProvider.coingecko,
            "bitcoin",
            "coingecko-stale",
        ),
        (
            ImportSource.trading212,
            AssetAliasProvider.twelve_data,
            '{"symbol":"AAPL","mic_code":"XNAS"}',
            "cnb-failure",
        ),
    ],
)
def test_provider_failure_preserves_posting_and_holdings_without_partial_graph(
    source: ImportSource,
    provider: AssetAliasProvider,
    alias: str,
    failure: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = f"r5b3c-{failure}-{uuid4().hex[:10]}"
    user_id, account_id = asyncio.run(investment_support.seed_identity(prefix, source=source))
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path / failure))
    harness = _ProviderHarness(
        observed_at=_observed_at(),
        twelve_status=429 if failure == "twelve-429" else 200,
        coingecko_stale=failure == "coingecko-stale",
        cnb_status=503 if failure == "cnb-failure" else 200,
    )
    app = create_app(_settings())
    _install_market_override(app, harness)
    try:
        with TestClient(app) as client:
            staged = investment_support.run_stages(
                client,
                source=source,
                user_id=user_id,
                account_id=account_id,
                content=investment_support.fixture(
                    source,
                    "activity.csv" if source is ImportSource.trading212 else "history.csv",
                ),
                filename=f"{failure}.csv",
                post=False,
            )
            asyncio.run(investment_support.seed_asset_listing(prefix, source=source))
            asyncio.run(_add_alias(prefix, provider=provider, external_id=alias))
            if failure == "cnb-failure":
                asyncio.run(_configure_trading_czk(prefix))
            response = investment_support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=staged["batch_id"],
            )

        state = asyncio.run(_database_state(prefix))
        assert response["snapshot_refresh_status"] == "unavailable"
        assert state["batch"].completed_at is not None
        assert len(state["holdings"]) == 1
        assert state["prices"] == state["snapshots"] == state["net_worth"] == ()
        events = {log.event for log in state["logs"]}
        assert ImportLogEvent.holdings_recalculated in events
        assert ImportLogEvent.snapshot_validation_failed in events
    finally:
        asyncio.run(_cleanup(prefix))


@pytest.mark.parametrize("alias_count", [0, 2])
def test_missing_or_ambiguous_alias_fails_before_http(
    alias_count: int,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = f"r5b3c-alias-{alias_count}-{uuid4().hex[:10]}"
    user_id, account_id = asyncio.run(
        investment_support.seed_identity(prefix, source=ImportSource.trading212)
    )
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path / str(alias_count)))
    harness = _ProviderHarness(observed_at=_observed_at(), fail_on_any_call=True)
    app = create_app(_settings())
    _install_market_override(app, harness)
    try:
        with TestClient(app) as client:
            staged = investment_support.run_stages(
                client,
                source=ImportSource.trading212,
                user_id=user_id,
                account_id=account_id,
                content=investment_support.fixture(ImportSource.trading212, "activity.csv"),
                filename="alias.csv",
                post=False,
            )
            asyncio.run(
                investment_support.seed_asset_listing(
                    prefix,
                    source=ImportSource.trading212,
                )
            )
            for index in range(alias_count):
                asyncio.run(
                    _add_alias(
                        prefix,
                        provider=AssetAliasProvider.twelve_data,
                        external_id=json.dumps(
                            {"symbol": f"AAP{index}", "mic_code": "XNAS"},
                            separators=(",", ":"),
                        ),
                        suffix=str(index),
                    )
                )
            response = investment_support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=staged["batch_id"],
            )

        state = asyncio.run(_database_state(prefix))
        assert response["snapshot_refresh_status"] == "unavailable"
        assert harness.calls == []
        assert len(state["holdings"]) == 1
        assert state["prices"] == state["snapshots"] == state["net_worth"] == ()
    finally:
        asyncio.run(_cleanup(prefix))


def test_snapshot_conflict_preserves_market_and_replay_market_conflict_skips_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = f"r5b3c-conflicts-{uuid4().hex[:10]}"
    user_id, account_id = asyncio.run(
        investment_support.seed_identity(prefix, source=ImportSource.anycoin)
    )
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path))
    observed_at = _observed_at()
    harness = _ProviderHarness(observed_at=observed_at)
    conflicting_executor = _ConflictingSnapshotExecutor()
    app = create_app(_settings())
    _install_market_override(
        app,
        harness,
        snapshot_executor=conflicting_executor,
    )
    try:
        with TestClient(app) as client:
            staged = investment_support.run_stages(
                client,
                source=ImportSource.anycoin,
                user_id=user_id,
                account_id=account_id,
                content=investment_support.fixture(ImportSource.anycoin, "history.csv"),
                filename="conflicts.csv",
                post=False,
            )
            asyncio.run(investment_support.seed_asset_listing(prefix, source=ImportSource.anycoin))
            asyncio.run(
                _add_alias(
                    prefix,
                    provider=AssetAliasProvider.coingecko,
                    external_id="bitcoin",
                )
            )
            snapshot_conflict = investment_support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=staged["batch_id"],
            )
            after_snapshot_conflict = asyncio.run(_database_state(prefix))
            harness.coin_price = Decimal("500")
            market_conflict = investment_support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=staged["batch_id"],
            )

        after_market_conflict = asyncio.run(_database_state(prefix))
        assert snapshot_conflict["snapshot_refresh_status"] == "conflict"
        assert market_conflict["snapshot_refresh_status"] == "conflict"
        assert conflicting_executor.calls == 1
        assert len(after_snapshot_conflict["prices"]) == 1
        assert after_snapshot_conflict["prices"][0].price == Decimal("414.5888000000")
        assert after_snapshot_conflict["snapshots"] == after_snapshot_conflict["net_worth"] == ()
        assert len(after_market_conflict["prices"]) == 1
        assert after_market_conflict["prices"][0].id == after_snapshot_conflict["prices"][0].id
        assert after_market_conflict["snapshots"] == after_market_conflict["net_worth"] == ()
    finally:
        asyncio.run(_cleanup(prefix))


def test_delayed_replay_rejects_future_provider_observation_without_moving_bucket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = f"r5b3c-delayed-{uuid4().hex[:10]}"
    user_id, account_id = asyncio.run(
        investment_support.seed_identity(prefix, source=ImportSource.anycoin)
    )
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path))
    future_observation = datetime.now(UTC).replace(tzinfo=None, microsecond=0) + timedelta(days=1)
    harness = _ProviderHarness(observed_at=future_observation)
    app = create_app(_settings())
    _install_market_override(app, harness)
    try:
        with TestClient(app) as client:
            staged = investment_support.run_stages(
                client,
                source=ImportSource.anycoin,
                user_id=user_id,
                account_id=account_id,
                content=investment_support.fixture(ImportSource.anycoin, "history.csv"),
                filename="delayed.csv",
                post=False,
            )
            asyncio.run(investment_support.seed_asset_listing(prefix, source=ImportSource.anycoin))
            asyncio.run(
                _add_alias(
                    prefix,
                    provider=AssetAliasProvider.coingecko,
                    external_id="bitcoin",
                )
            )
            first = investment_support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=staged["batch_id"],
            )
            state_before = asyncio.run(_database_state(prefix))
            second = investment_support.post_batch(
                client,
                user_id=user_id,
                account_id=account_id,
                batch_id=staged["batch_id"],
            )

        state_after = asyncio.run(_database_state(prefix))
        assert (
            first["snapshot_refresh_status"] == second["snapshot_refresh_status"] == "unavailable"
        )
        assert state_after["batch"].completed_at == state_before["batch"].completed_at
        assert state_after["holdings"][0].id == state_before["holdings"][0].id
        assert state_after["prices"] == state_after["snapshots"] == state_after["net_worth"] == ()
        assert future_observation > state_after["batch"].completed_at
    finally:
        asyncio.run(_cleanup(prefix))
