"""R12-F clean PostgreSQL proof for the durable mixed-settlement import path."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.dependencies import INTERNAL_AUTH_SERVICE_SUBJECT
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.background_jobs import (
    BackgroundJobModel,
    ImportJobAffectedAccountModel,
    ImportJobBatchModel,
)
from app.db.models.canonical_lineage import (
    DailySnapshotBaselineModel,
    SnapshotGenerationModel,
    SnapshotGenerationTargetModel,
    UserReadModelPublicationModel,
)
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AssetAliasProvider,
    AssetType,
    BackgroundJobStatus,
    ExchangeRateSource,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.imports import ImportBatchModel, ImportLogModel, ImportRowModel
from app.db.models.investment_snapshots import PortfolioSnapshotModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.publication_targets import ImportJobPublicationTargetModel
from app.db.models.snapshot_series_publication import (
    SnapshotSeriesHeadModel,
    SnapshotSeriesPointLinkModel,
    SnapshotSeriesPublicationReceiptModel,
    SnapshotSeriesVersionStateModel,
)
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.current_value.api import get_current_value_service
from app.modules.current_value.service import CurrentValueService
from app.modules.daily_baselines.service import DailySnapshotBaselineService
from app.modules.imports.multi_file_service import ImportMultiFileFinalizationService
from app.modules.jobs import import_executor as durable_import_executor_module
from app.modules.jobs import worker as background_worker_module
from app.modules.jobs.import_executor import DurableImportJobExecutor
from app.modules.jobs.lifecycle import LeaseIdentity
from app.modules.jobs.repository import BackgroundJobRepository, ClaimedBackgroundJob
from app.modules.jobs.worker import BackgroundJobWorker
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.market_data.source_policy import CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY
from app.modules.snapshot_refresh.market_backed_service import MarketBackedSnapshotRefreshService

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "r12f-durable-import-e2e-secret-at-least-32-characters"
TWELVE_API_KEY = "r12f-deterministic-twelve-key"
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _settings() -> Settings:
    assert DATABASE_URL is not None
    return Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        log_level="ERROR",
        log_json=False,
        internal_auth_secret=SECRET,
        twelve_data_api_key=TWELVE_API_KEY,
        _env_file=None,
    )


def _encode(value: object) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )


def _headers(subject: str, *, binary: bool = False) -> dict[str, str]:
    now = int(time.time())
    header = _encode({"alg": "HS256", "typ": "JWT"})
    payload = _encode(
        {
            "sub": subject,
            "iss": "finance-app-next",
            "aud": "finance-app-python",
            "iat": now,
            "exp": now + 300,
        }
    )
    signature = hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    result = {
        "Authorization": (
            f"Bearer {header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"
        )
    }
    if binary:
        result["Content-Type"] = "application/octet-stream"
    return result


def _csv(*rows: str) -> bytes:
    header = (
        "Action,Time,Ticker,ISIN,Name,Asset type,No. of shares,Price / share,"
        "Currency (Price / share),Total,Currency (Total),ID,Notes,"
        "Currency conversion fee,Currency (Currency conversion fee)"
    )
    return ("\n".join((header, *rows)) + "\n").encode()


EUR_FILE = _csv(
    "Deposit,2026-07-20T09:00:00Z,,,,,,,,1000,EUR,R12F-DEPOSIT-001,Opening cash,,",
    "Market buy,2026-07-20T10:00:00Z,TSTETF,TEST00000001,R12-F Test ETF,ETF,1,100,EUR,100,EUR,R12F-EUR-BUY-001,EUR execution,,",
)
USD_FILE = _csv(
    "Market buy,2026-07-21T10:00:00Z,TSTETF,TEST00000001,R12-F Test ETF,ETF,2,100,EUR,200,USD,R12F-USD-BUY-001,USD execution,,",
)
DUPLICATE_REPLAY_FILE = _csv(
    "Deposit,2026-07-20T09:00:00Z,,,,,,,,1000,EUR,R12F-DEPOSIT-001,Exact replay fixture,,",
    "Market buy,2026-07-20T10:00:00Z,TSTETF,TEST00000001,R12-F Test ETF,ETF,1,100,EUR,100,EUR,R12F-EUR-BUY-001,Exact replay fixture,,",
    "Market buy,2026-07-21T10:00:00Z,TSTETF,TEST00000001,R12-F Test ETF,ETF,2,100,EUR,200,USD,R12F-USD-BUY-001,Exact replay fixture,,",
)


def _fixture_files(prefix: str) -> tuple[str, bytes, bytes, bytes]:
    suffix = prefix.rsplit("-", 1)[-1]
    ticker = f"TSTETF{suffix.upper()}"
    replacements = {
        "TSTETF": ticker,
        "TEST00000001": f"TS{suffix[:10].upper()}",
        "R12F-DEPOSIT-001": f"R12F-DEPOSIT-{suffix}",
        "R12F-EUR-BUY-001": f"R12F-EUR-BUY-{suffix}",
        "R12F-USD-BUY-001": f"R12F-USD-BUY-{suffix}",
    }

    def distinct(content: bytes) -> bytes:
        value = content.decode()
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value.encode()

    return ticker, distinct(EUR_FILE), distinct(USD_FILE), distinct(DUPLICATE_REPLAY_FILE)


class _ProviderHarness:
    """Exact in-memory provider responses; network access is impossible in this test."""

    def __init__(self, observed_at: datetime) -> None:
        self.observed_at = observed_at
        self.calls: list[tuple[str, str]] = []

    def transports(
        self, session: AsyncSession
    ) -> tuple[httpx.MockTransport, httpx.MockTransport, httpx.MockTransport]:
        observed_epoch = int(self.observed_at.replace(tzinfo=UTC).timestamp())

        def _before(kind: str, identity: str) -> None:
            assert not session.in_transaction()
            self.calls.append((kind, identity))

        def quote(request: httpx.Request) -> httpx.Response:
            _before("quote", f"{request.url.params['symbol']}:{request.url.params['mic_code']}")
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "symbol": request.url.params["symbol"],
                    "mic_code": request.url.params["mic_code"],
                    "currency": "EUR",
                    "datetime": self.observed_at.strftime("%Y-%m-%d %H:%M:%S"),
                    "timestamp": observed_epoch,
                    "last_quote_at": observed_epoch,
                    "close": "125.0000000000",
                },
            )

        def coin(_: httpx.Request) -> httpx.Response:
            raise AssertionError("The Trading212 workflow must not request CoinGecko evidence.")

        def fx(request: httpx.Request) -> httpx.Response:
            symbol = request.url.params["symbol"]
            _before("fx", symbol)
            rate = {
                "EUR/CZK": "25.00000000",
                "USD/CZK": "23.00000000",
                "USD/EUR": "1.10000000",
                "EUR/USD": "0.90000000",
            }.get(symbol)
            assert rate is not None, f"Unexpected non-direct or unsupported FX pair: {symbol}"
            publication = datetime.fromisoformat(request.url.params["end_date"]).date() - timedelta(
                days=1
            )
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "meta": {"symbol": symbol},
                    "values": [{"datetime": publication.isoformat(), "close": rate}],
                    "status": "ok",
                },
            )

        return httpx.MockTransport(quote), httpx.MockTransport(coin), httpx.MockTransport(fx)


async def _seed_market_identity(prefix: str) -> tuple[str, str]:
    """Seed only the market identity, not any account, import, event, Holding, or snapshot."""

    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    asset_id, listing_id = f"{prefix}-asset", f"{prefix}-listing"
    ticker, _, _, _ = _fixture_files(prefix)
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    try:
        async with AsyncSession(engine) as session:
            session.add(
                AssetModel(
                    id=asset_id,
                    symbol=ticker,
                    isin=f"TS{prefix.rsplit('-', 1)[-1][:10].upper()}",
                    name="R12-F Test ETF",
                    asset_type=AssetType.etf,
                    currency="EUR",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            session.add(
                AssetListingModel(
                    id=listing_id,
                    asset_id=asset_id,
                    symbol=ticker,
                    exchange="trading212",
                    mic=None,
                    currency="EUR",
                    country=None,
                    provider=PriceSource.broker,
                    # Listing provider identities are globally unique.  Keep
                    # this test isolated even if a prior interrupted run left
                    # its own test asset behind.
                    provider_symbol=ticker,
                    is_primary=False,
                    created_at=now,
                    updated_at=now,
                )
            )
            # These independent ORM objects intentionally have no relationship
            # attributes, so make their foreign-key parents visible explicitly.
            await session.flush()
            session.add(
                AssetAliasModel(
                    id=f"{prefix}-alias",
                    asset_id=asset_id,
                    provider=AssetAliasProvider.twelve_data,
                    external_id=json.dumps(
                        {"symbol": f"TSTETF-{prefix}", "mic_code": "XNAS"},
                        separators=(",", ":"),
                    ),
                    created_at=now,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()
    return asset_id, listing_id


async def _state(*, account_id: str, user_id: str, job_id: str, listing_id: str) -> dict[str, Any]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    try:
        async with AsyncSession(engine) as session:
            batches = tuple(
                (
                    await session.scalars(
                        select(ImportBatchModel)
                        .where(ImportBatchModel.account_id == account_id)
                        .order_by(ImportBatchModel.id)
                    )
                ).all()
            )
            events = tuple(
                (
                    await session.scalars(
                        select(InvestmentEventModel)
                        .where(InvestmentEventModel.account_id == account_id)
                        .order_by(InvestmentEventModel.id)
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
            snapshots = tuple(
                (
                    await session.scalars(
                        select(AccountSnapshotModel)
                        .where(AccountSnapshotModel.account_id == account_id)
                        .order_by(AccountSnapshotModel.currency, AccountSnapshotModel.id)
                    )
                ).all()
            )
            snapshot_ids = tuple(snapshot.id for snapshot in snapshots)
            items = tuple(
                (
                    await session.scalars(
                        select(AccountSnapshotItemModel)
                        .where(AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids))
                        .order_by(AccountSnapshotItemModel.snapshot_id, AccountSnapshotItemModel.id)
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
            baselines = tuple(
                (
                    await session.scalars(
                        select(DailySnapshotBaselineModel)
                        .where(DailySnapshotBaselineModel.user_id == user_id)
                        .order_by(
                            DailySnapshotBaselineModel.timestamp, DailySnapshotBaselineModel.id
                        )
                    )
                ).all()
            )
            logs = tuple(
                (
                    await session.scalars(
                        select(ImportLogModel)
                        .where(ImportLogModel.import_batch_id.in_([batch.id for batch in batches]))
                        .order_by(ImportLogModel.id)
                    )
                ).all()
            )
            targets = tuple(
                (
                    await session.scalars(
                        select(ImportJobPublicationTargetModel)
                        .where(ImportJobPublicationTargetModel.job_id == job_id)
                        .order_by(ImportJobPublicationTargetModel.user_id)
                    )
                ).all()
            )
            movements = int(
                await session.scalar(
                    select(func.count())
                    .select_from(InvestmentMovementModel)
                    .where(InvestmentMovementModel.account_id == account_id)
                )
                or 0
            )
            job = await session.get(BackgroundJobModel, job_id)
            prices = tuple(
                (
                    await session.scalars(
                        select(PriceSnapshotModel)
                        .where(PriceSnapshotModel.listing_id == listing_id)
                        .order_by(PriceSnapshotModel.id)
                    )
                ).all()
            )
            rate_ids = tuple(
                rate_id for snapshot in snapshots for rate_id in _rate_ids(snapshot.exchange_rates)
            )
            rates = tuple(
                (
                    await session.scalars(
                        select(ExchangeRateModel)
                        .where(ExchangeRateModel.id.in_(rate_ids))
                        .order_by(ExchangeRateModel.id)
                    )
                ).all()
            )
            assert job is not None
            for collection in (
                batches,
                events,
                holdings,
                snapshots,
                items,
                net_worth,
                baselines,
                logs,
                targets,
                prices,
                rates,
            ):
                for row in collection:
                    session.expunge(row)
            session.expunge(job)
            return {
                "batches": batches,
                "events": events,
                "holdings": holdings,
                "snapshots": snapshots,
                "items": items,
                "net_worth": net_worth,
                "baselines": baselines,
                "logs": logs,
                "targets": targets,
                "movements": movements,
                "job": job,
                "prices": prices,
                "rates": rates,
            }
    finally:
        await engine.dispose()


def _rate_ids(evidence: object) -> tuple[str, ...]:
    if not isinstance(evidence, dict):
        return ()
    result: list[str] = []
    for item in evidence.get("snapshotRates", []):
        if isinstance(item, dict) and isinstance(item.get("rateId"), str):
            result.append(item["rateId"])
    for value in evidence.get("historicalRateIds", []):
        if isinstance(value, str):
            result.append(value)
    return tuple(sorted(set(result)))


async def _cleanup(
    prefix: str,
    *,
    account_id: str | None,
    user_id: str | None,
    rate_ids: tuple[str, ...],
) -> None:
    """Delete only rows attributable to this unique test prefix."""

    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    try:
        async with AsyncSession(engine) as session:
            effective_account_ids = (
                (account_id,)
                if account_id is not None
                else tuple(
                    (
                        await session.scalars(
                            select(AccountModel.id).where(AccountModel.name == prefix)
                        )
                    ).all()
                )
            )
            effective_user_ids = (
                (user_id,)
                if user_id is not None
                else tuple(
                    (
                        await session.scalars(
                            select(UserModel.id).where(UserModel.email == f"{prefix}@example.test")
                        )
                    ).all()
                )
            )
            if effective_account_ids:
                member_user_ids = tuple(
                    (
                        await session.scalars(
                            select(AccountMemberModel.user_id).where(
                                AccountMemberModel.account_id.in_(effective_account_ids)
                            )
                        )
                    ).all()
                )
                effective_user_ids = tuple(sorted(set(effective_user_ids) | set(member_user_ids)))
            generation_ids = tuple(
                (
                    await session.scalars(
                        select(SnapshotGenerationTargetModel.generation_id).where(
                            SnapshotGenerationTargetModel.user_id.in_(effective_user_ids)
                        )
                    )
                ).all()
            )
            snapshot_ids = (
                tuple(
                    (
                        await session.scalars(
                            select(AccountSnapshotModel.id).where(
                                AccountSnapshotModel.account_id.in_(effective_account_ids)
                            )
                        )
                    ).all()
                )
                if effective_account_ids
                else ()
            )
            event_ids = (
                tuple(
                    (
                        await session.scalars(
                            select(InvestmentEventModel.id).where(
                                InvestmentEventModel.account_id.in_(effective_account_ids)
                            )
                        )
                    ).all()
                )
                if effective_account_ids
                else ()
            )
            batch_ids = (
                tuple(
                    (
                        await session.scalars(
                            select(ImportBatchModel.id).where(
                                ImportBatchModel.account_id.in_(effective_account_ids)
                            )
                        )
                    ).all()
                )
                if effective_account_ids
                else ()
            )
            job_ids = (
                tuple(
                    (
                        await session.scalars(
                            select(BackgroundJobModel.id).where(
                                BackgroundJobModel.account_id.in_(effective_account_ids),
                                BackgroundJobModel.user_id.in_(effective_user_ids),
                            )
                        )
                    ).all()
                )
                if effective_account_ids and effective_user_ids
                else ()
            )
            if effective_user_ids:
                await session.execute(
                    delete(UserReadModelPublicationModel).where(
                        UserReadModelPublicationModel.user_id.in_(effective_user_ids)
                    )
                )
                # Immutable series rows need a transaction-local trigger bypass
                # while their test users still exist. All predicates use this
                # run's unique user and generation ids.
                await session.execute(sql_text("SET LOCAL session_replication_role = replica"))
                try:
                    await session.execute(
                        delete(SnapshotSeriesPublicationReceiptModel).where(
                            SnapshotSeriesPublicationReceiptModel.user_id.in_(effective_user_ids),
                            SnapshotSeriesPublicationReceiptModel.generation_id.in_(generation_ids),
                        )
                    )
                    await session.execute(
                        delete(SnapshotSeriesPointLinkModel).where(
                            SnapshotSeriesPointLinkModel.user_id.in_(effective_user_ids),
                            SnapshotSeriesPointLinkModel.generation_id.in_(generation_ids),
                        )
                    )
                    await session.execute(
                        delete(SnapshotSeriesHeadModel).where(
                            SnapshotSeriesHeadModel.user_id.in_(effective_user_ids),
                            SnapshotSeriesHeadModel.generation_id.in_(generation_ids),
                        )
                    )
                    await session.execute(
                        delete(SnapshotSeriesVersionStateModel).where(
                            SnapshotSeriesVersionStateModel.user_id.in_(effective_user_ids)
                        )
                    )
                finally:
                    await session.execute(sql_text("SET LOCAL session_replication_role = origin"))
                await session.execute(
                    delete(DailySnapshotBaselineModel).where(
                        DailySnapshotBaselineModel.user_id.in_(effective_user_ids)
                    )
                )
                await session.execute(
                    delete(ImportJobPublicationTargetModel).where(
                        ImportJobPublicationTargetModel.user_id.in_(effective_user_ids)
                    )
                )
                await session.execute(
                    delete(PortfolioSnapshotModel).where(
                        PortfolioSnapshotModel.user_id.in_(effective_user_ids)
                    )
                )
                await session.execute(
                    delete(NetWorthSnapshotModel).where(
                        NetWorthSnapshotModel.user_id.in_(effective_user_ids)
                    )
                )
            if snapshot_ids:
                await session.execute(
                    delete(AccountSnapshotItemModel).where(
                        AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids)
                    )
                )
            if effective_account_ids:
                await session.execute(
                    delete(AccountSnapshotModel).where(
                        AccountSnapshotModel.account_id.in_(effective_account_ids)
                    )
                )
                await session.execute(
                    delete(HoldingModel).where(HoldingModel.account_id.in_(effective_account_ids))
                )
            if event_ids:
                await session.execute(
                    delete(InvestmentMovementModel).where(
                        InvestmentMovementModel.event_id.in_(event_ids)
                    )
                )
                await session.execute(
                    delete(InvestmentEventModel).where(InvestmentEventModel.id.in_(event_ids))
                )
            if batch_ids:
                await session.execute(
                    delete(TransactionModel).where(TransactionModel.import_batch_id.in_(batch_ids))
                )
                await session.execute(
                    delete(ImportLogModel).where(ImportLogModel.import_batch_id.in_(batch_ids))
                )
                await session.execute(
                    delete(ImportRowModel).where(ImportRowModel.import_batch_id.in_(batch_ids))
                )
                await session.execute(
                    delete(ImportJobBatchModel).where(ImportJobBatchModel.batch_id.in_(batch_ids))
                )
                await session.execute(
                    delete(ImportBatchModel).where(ImportBatchModel.id.in_(batch_ids))
                )
            if job_ids:
                await session.execute(
                    delete(ImportJobAffectedAccountModel).where(
                        ImportJobAffectedAccountModel.job_id.in_(job_ids)
                    )
                )
                await session.execute(
                    delete(BackgroundJobModel).where(BackgroundJobModel.id.in_(job_ids))
                )
            await session.execute(
                delete(AssetAliasModel).where(AssetAliasModel.id == f"{prefix}-alias")
            )
            await session.execute(
                delete(AssetListingModel).where(AssetListingModel.id == f"{prefix}-listing")
            )
            await session.execute(delete(AssetModel).where(AssetModel.id == f"{prefix}-asset"))
            if rate_ids:
                await session.execute(
                    delete(ExchangeRateModel).where(ExchangeRateModel.id.in_(rate_ids))
                )
            if effective_account_ids:
                await session.execute(
                    delete(AccountMemberModel).where(
                        AccountMemberModel.account_id.in_(effective_account_ids)
                    )
                )
                await session.execute(
                    delete(AccountModel).where(AccountModel.id.in_(effective_account_ids))
                )
            if effective_user_ids:
                await session.execute(
                    delete(SnapshotGenerationTargetModel).where(
                        SnapshotGenerationTargetModel.user_id.in_(effective_user_ids)
                    )
                )
                await session.execute(delete(UserModel).where(UserModel.id.in_(effective_user_ids)))
            if generation_ids:
                await session.execute(
                    delete(SnapshotGenerationModel).where(
                        SnapshotGenerationModel.id.in_(generation_ids)
                    )
                )
            for model, predicate in (
                (UserModel, UserModel.id.in_(effective_user_ids)),
                (BackgroundJobModel, BackgroundJobModel.id.in_(job_ids)),
                (ImportBatchModel, ImportBatchModel.id.in_(batch_ids)),
                (AssetModel, AssetModel.id == f"{prefix}-asset"),
                (PortfolioSnapshotModel, PortfolioSnapshotModel.user_id.in_(effective_user_ids)),
                (
                    SnapshotGenerationTargetModel,
                    SnapshotGenerationTargetModel.user_id.in_(effective_user_ids),
                ),
                (SnapshotGenerationModel, SnapshotGenerationModel.id.in_(generation_ids)),
                (
                    SnapshotSeriesPointLinkModel,
                    SnapshotSeriesPointLinkModel.user_id.in_(effective_user_ids),
                ),
            ):
                assert (
                    int(
                        await session.scalar(
                            select(func.count()).select_from(model).where(predicate)
                        )
                        or 0
                    )
                    == 0
                )
            await session.commit()
    finally:
        await engine.dispose()


async def _run_worker(
    *,
    prefix: str,
    job_id: str,
    user_id: str,
    settings: Settings,
    harness: _ProviderHarness,
    before_complete: Callable[[], Awaitable[None]] | None = None,
) -> None:
    """Execute one real fenced worker claim on one asyncio loop and engine."""

    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL), pool_size=8)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    def member_market_factory(active_session: AsyncSession, active_settings: Settings):
        quote, coin, fx = harness.transports(active_session)
        return MarketBackedSnapshotRefreshService(
            active_session,
            active_settings,
            market_service_factory=lambda market_session, market_settings: (
                create_production_market_evidence_service(
                    market_session,
                    market_settings,
                    twelve_data_http_transport=quote,
                    coingecko_http_transport=coin,
                    twelve_data_fx_http_transport=fx,
                )
            ),
        )

    executor = DurableImportJobExecutor(
        session_factory,
        settings,
        market_refresh_factory=member_market_factory,
    )

    def finalizer(session: AsyncSession) -> ImportMultiFileFinalizationService:
        quote, coin, fx = harness.transports(session)

        def market_factory(active_session: AsyncSession, active_settings: Settings):
            return create_production_market_evidence_service(
                active_session,
                active_settings,
                twelve_data_http_transport=quote,
                coingecko_http_transport=coin,
                twelve_data_fx_http_transport=fx,
            )

        return ImportMultiFileFinalizationService(
            session,
            market_backed_service=MarketBackedSnapshotRefreshService(
                session, settings, market_service_factory=market_factory
            ),
            source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        )

    executor.executor.finalization_factory = finalizer

    class _PublicationProbeWorker(BackgroundJobWorker):
        async def _complete(self, claimed, result) -> None:
            if before_complete is not None:
                await before_complete()
            await super()._complete(claimed, result)

    worker = _PublicationProbeWorker(
        session_factory,
        executor,
        worker_id=f"{prefix}-worker",
        lease_duration=timedelta(minutes=5),
        heartbeat_interval=timedelta(seconds=5),
    )

    class _ScopedJobRepository(BackgroundJobRepository):
        async def claim_next(
            self, *, worker_id: str, now: datetime, lease_duration: timedelta
        ) -> ClaimedBackgroundJob | None:
            job = await self.session.scalar(
                select(BackgroundJobModel)
                .where(
                    BackgroundJobModel.id == job_id,
                    BackgroundJobModel.user_id == user_id,
                    BackgroundJobModel.status.in_(
                        (BackgroundJobStatus.queued, BackgroundJobStatus.retry_wait)
                    ),
                    BackgroundJobModel.run_after <= now,
                    BackgroundJobModel.attempt_count < BackgroundJobModel.max_attempts,
                )
                .with_for_update(skip_locked=True)
            )
            if job is None:
                return None
            job.status = BackgroundJobStatus.running
            job.lease_owner = worker_id
            job.lease_version += 1
            job.lease_expires_at = now + lease_duration
            job.lease_heartbeat_at = now
            job.attempt_count += 1
            job.started_at = job.started_at or now
            job.finished_at = None
            job.updated_at = now
            await self.session.flush()
            lease = LeaseIdentity(job_id=job.id, owner=worker_id, version=job.lease_version)
            return ClaimedBackgroundJob(job=job, lease=lease)

    patcher = pytest.MonkeyPatch()
    patcher.setattr(background_worker_module, "BackgroundJobRepository", _ScopedJobRepository)
    try:
        assert await worker.run_once() is True
    finally:
        patcher.undo()
        await engine.dispose()


async def _add_viewer(*, prefix: str, account_id: str) -> str:
    """Add a distinct-currency read-only member before target reservation."""

    assert DATABASE_URL is not None
    viewer_id = f"{prefix}-viewer"
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    try:
        async with AsyncSession(engine) as session, session.begin():
            session.add(
                UserModel(
                    id=viewer_id,
                    email=f"{viewer_id}@example.test",
                    name="R12-F viewer",
                    password_hash=None,
                    base_currency="USD",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            session.add(
                AccountMemberModel(
                    id=f"{prefix}-viewer-member",
                    account_id=account_id,
                    user_id=viewer_id,
                    # Create the prior immutable baseline while the member is
                    # an editor; the test then proves the import-only override
                    # refreshes the same account after it becomes a viewer.
                    role=AccountMemberRole.editor,
                    relation_type=AccountRelationType.collaborator,
                    invited_by_id=None,
                    accepted_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
    finally:
        await engine.dispose()
    return viewer_id


async def _set_member_viewer(*, prefix: str) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    try:
        async with AsyncSession(engine) as session, session.begin():
            await session.execute(
                update(AccountMemberModel)
                .where(AccountMemberModel.id == f"{prefix}-viewer-member")
                .values(role=AccountMemberRole.viewer)
            )
    finally:
        await engine.dispose()


async def _selected_current_baseline(*, user_id: str):
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    try:
        async with AsyncSession(engine) as session:
            through = datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)
            baseline = await DailySnapshotBaselineService(session).select_latest_valid(
                user_id=user_id,
                through=through,
            )
            return baseline
    finally:
        await engine.dispose()


def test_r12f_clean_async_trading212_multifile_import_survives_client_loss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The persisted job, not the initiating browser, owns posting and publication."""

    assert DATABASE_URL is not None
    prefix = f"r12f-e2e-{uuid4().hex[:12]}"
    _, eur_file, usd_file, _ = _fixture_files(prefix)
    email = f"{prefix}@example.test"
    account_id: str | None = None
    user_id: str | None = None
    viewer_id: str | None = None
    job_id: str | None = None
    listing_id: str | None = None
    rate_ids: tuple[str, ...] = ()
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path / "raw-imports"))
    settings = _settings()
    app = create_app(settings)

    try:
        # The first client owns only registration, byte-exact upload, and durable acceptance.
        with TestClient(app) as initiating_client:
            registered = initiating_client.post(
                "/api/v1/auth/register",
                headers=_headers(INTERNAL_AUTH_SERVICE_SUBJECT),
                json={"email": email, "password": "r12f-password", "name": "R12-F clean user"},
            )
            assert registered.status_code == 201, registered.text
            user_id = str(registered.json()["id"])
            headers = _headers(user_id)
            account = initiating_client.post(
                "/api/v1/accounts",
                headers=headers,
                json={"name": prefix, "type": "broker", "currency": "EUR"},
            )
            assert account.status_code == 201, account.text
            account_id = str(account.json()["id"])
            viewer_id = asyncio.run(_add_viewer(prefix=prefix, account_id=account_id))
            _, listing_id = asyncio.run(_seed_market_identity(prefix))
            observed_at = datetime.now(UTC).replace(
                tzinfo=None,
                second=0,
                microsecond=0,
            ) - timedelta(minutes=1)
            harness = _ProviderHarness(observed_at)

            def current_value_service(
                session: Annotated[AsyncSession, Depends(get_db_session)],
            ) -> CurrentValueService:
                def market_factory(
                    active_session: AsyncSession,
                    active_settings: Settings,
                    planner,
                ):
                    quote, coin, fx = harness.transports(active_session)
                    return create_production_market_evidence_service(
                        active_session,
                        active_settings,
                        planner=planner,
                        twelve_data_http_transport=quote,
                        coingecko_http_transport=coin,
                        twelve_data_fx_http_transport=fx,
                    )

                return CurrentValueService(
                    session,
                    settings,
                    market_service_factory=market_factory,
                )

            app.dependency_overrides[get_current_value_service] = current_value_service
            asyncio.run(_set_member_viewer(prefix=prefix))
            prior_current = initiating_client.post(
                "/api/v1/portfolio/current",
                headers=_headers(user_id),
            )
            assert prior_current.status_code == 409, prior_current.text
            assert prior_current.json()["error"]["code"] == "current_value_unavailable"
            viewer_prior_current = initiating_client.post(
                "/api/v1/portfolio/current",
                headers=_headers(viewer_id),
            )
            assert viewer_prior_current.status_code == 409, viewer_prior_current.text
            assert viewer_prior_current.json()["error"]["code"] == "current_value_unavailable"

            batch_ids: list[str] = []
            for filename, content in (("r12f-eur.csv", eur_file), ("r12f-usd.csv", usd_file)):
                created = initiating_client.post(
                    f"/api/v1/accounts/{account_id}/imports",
                    headers=headers,
                    json={
                        "source": "trading212",
                        "filename": filename,
                        "file_size": len(content),
                        "file_encoding": None,
                        "checksum": hashlib.sha256(content).hexdigest(),
                    },
                )
                assert created.status_code == 201, created.text
                assert created.json()["status"] == "upload_required"
                batch_id = str(created.json()["batch"]["id"])
                batch_ids.append(batch_id)
                uploaded = initiating_client.put(
                    f"/api/v1/accounts/{account_id}/imports/{batch_id}/file",
                    headers=_headers(user_id, binary=True),
                    content=content,
                )
                assert uploaded.status_code == 200, uploaded.text

            batch_ids.sort()
            accepted = initiating_client.post(
                f"/api/v1/accounts/{account_id}/imports/jobs",
                headers=headers,
                json={"batch_ids": batch_ids},
            )
            assert accepted.status_code == 202, accepted.text
            job_id = str(accepted.json()["id"])
            assert accepted.json()["status"] == "queued"

        # Discarding the initiating client must not affect the independently claimed job.
        assert viewer_id is not None
        publication_probe: dict[str, str] = {}

        async def before_complete() -> None:
            def read_current() -> None:
                with TestClient(app) as current_client:
                    portfolio = current_client.post(
                        "/api/v1/portfolio/current",
                        headers=_headers(user_id),
                    )
                    dashboard = current_client.post(
                        "/api/v1/dashboard/current",
                        headers=_headers(user_id),
                    )
                    assert portfolio.status_code == dashboard.status_code == 409, (
                        portfolio.text,
                        dashboard.text,
                    )
                    publication_probe["portfolio"] = portfolio.json()["error"]["code"]
                    publication_probe["dashboard"] = dashboard.json()["error"]["code"]
                    viewer_portfolio = current_client.post(
                        "/api/v1/portfolio/current",
                        headers=_headers(viewer_id),
                    )
                    viewer_dashboard = current_client.post(
                        "/api/v1/dashboard/current",
                        headers=_headers(viewer_id),
                    )
                    assert viewer_portfolio.status_code == viewer_dashboard.status_code == 409, (
                        viewer_portfolio.text,
                        viewer_dashboard.text,
                    )
                    publication_probe["viewer_portfolio"] = viewer_portfolio.json()["error"]["code"]
                    publication_probe["viewer_dashboard"] = viewer_dashboard.json()["error"]["code"]

            await asyncio.to_thread(read_current)

        asyncio.run(
            _run_worker(
                prefix=prefix,
                job_id=job_id,
                user_id=user_id,
                settings=settings,
                harness=harness,
                before_complete=before_complete,
            )
        )
        assert (
            account_id is not None
            and user_id is not None
            and viewer_id is not None
            and job_id is not None
            and listing_id is not None
        )
        probe_state = asyncio.run(
            _state(account_id=account_id, user_id=user_id, job_id=job_id, listing_id=listing_id)
        )
        assert probe_state["job"].status.value == "completed", (
            probe_state["job"].status,
            probe_state["job"].error_code,
            probe_state["job"].error_message,
            probe_state["job"].checkpoint,
            [(log.event, log.message) for log in probe_state["logs"]],
        )
        assert publication_probe == {
            "portfolio": "current_value_unavailable",
            "dashboard": "current_value_unavailable",
            "viewer_portfolio": "current_value_unavailable",
            "viewer_dashboard": "current_value_unavailable",
        }

        assert (
            account_id is not None
            and user_id is not None
            and viewer_id is not None
            and job_id is not None
            and listing_id is not None
        )
        completed = asyncio.run(
            _state(account_id=account_id, user_id=user_id, job_id=job_id, listing_id=listing_id)
        )
        assert completed["job"].status.value == "completed", (
            completed["job"].status,
            completed["job"].error_code,
            completed["job"].error_message,
            completed["job"].checkpoint,
            harness.calls,
        )
        assert completed["job"].attempt_count == 1
        assert completed["job"].result is not None
        assert completed["job"].result["batch_ids"] == batch_ids
        assert {target.user_id for target in completed["targets"]} == {user_id, viewer_id}
        assert all(target.published_at is not None for target in completed["targets"])
        assert len(completed["batches"]) == 2
        assert {batch.status.value for batch in completed["batches"]} == {"completed"}
        # Deposit plus the two executed buys are all canonical investment events.
        assert len(completed["events"]) == 3
        assert completed["movements"] == 5
        assert len(completed["holdings"]) == 1
        assert len(completed["baselines"]) == 1
        import_anchor = next(
            baseline
            for baseline in completed["baselines"]
            if baseline.granularity.value == "minute"
        )
        assert import_anchor.source.value == "import_event"
        assert import_anchor.background_job_id == job_id
        holding = completed["holdings"][0]
        assert holding.quantity == Decimal("3.0000000000")
        assert holding.avg_buy_price == Decimal("100.0000000000")
        assert holding.currency == "EUR"
        assert holding.cost_basis_by_currency == {"EUR": "100.0000000000", "USD": "200.0000000000"}
        assert {
            (item.average_buy_price, item.average_buy_price_currency) for item in completed["items"]
        } == {(Decimal("100.0000000000"), "EUR")}
        assert len(completed["prices"]) == 1
        assert completed["prices"][0].price == Decimal("125.0000000000")
        assert completed["prices"][0].source is PriceSource.twelve_data
        assert {rate.source for rate in completed["rates"]} == {ExchangeRateSource.twelve_data}
        rate_ids = tuple(rate.id for rate in completed["rates"])
        assert {f"{rate.from_currency}/{rate.to_currency}" for rate in completed["rates"]} == {
            "EUR/CZK",
            "EUR/USD",
            "USD/CZK",
            "USD/EUR",
        }
        assert ("quote", f"TSTETF-{prefix}:XNAS") in harness.calls
        assert {call for call in harness.calls if call[0] == "fx"} == {
            ("fx", "EUR/CZK"),
            ("fx", "USD/CZK"),
            ("fx", "USD/EUR"),
            ("fx", "EUR/USD"),
        }

        # A fresh client polls the published job and reads one exact manifest through both endpoints.
        aggregate_snapshot = next(
            snapshot
            for snapshot in completed["snapshots"]
            if snapshot.currency == "CZK" and snapshot.granularity is SnapshotGranularity.minute
        )
        manifest = {
            "timestamp": aggregate_snapshot.timestamp.isoformat(),
            "granularity": aggregate_snapshot.granularity.value,
            "currency": aggregate_snapshot.currency,
            "calculationVersion": aggregate_snapshot.calculation_version,
            "accounts": [{"accountId": account_id, "snapshotId": aggregate_snapshot.id}],
        }
        with TestClient(app) as polling_client:
            polled = polling_client.get(
                f"/api/v1/accounts/{account_id}/imports/jobs/{job_id}", headers=_headers(user_id)
            )
            assert polled.status_code == 200, polled.text
            assert polled.json()["status"] == "completed"
            selected_baseline = asyncio.run(_selected_current_baseline(user_id=user_id))
            assert selected_baseline.publication_job_id == job_id
            # The successful worker establishes the current-value publication
            # anchor itself. No test-only daily snapshot may bridge this read.
            current_portfolio = polling_client.post(
                "/api/v1/portfolio/current", headers=_headers(user_id)
            )
            current_dashboard = polling_client.post(
                "/api/v1/dashboard/current", headers=_headers(user_id)
            )
            viewer_current_portfolio = polling_client.post(
                "/api/v1/portfolio/current", headers=_headers(viewer_id)
            )
            viewer_current_dashboard = polling_client.post(
                "/api/v1/dashboard/current", headers=_headers(viewer_id)
            )
            assert current_portfolio.status_code == current_dashboard.status_code == 200, (
                current_portfolio.text,
                current_dashboard.text,
            )
            assert (
                viewer_current_portfolio.status_code == viewer_current_dashboard.status_code == 200
            ), (
                viewer_current_portfolio.text,
                viewer_current_dashboard.text,
            )
            assert (
                current_portfolio.json()["summary"]["totalValue"]
                == current_dashboard.json()["summary"]["totalValue"]
            )
            assert (
                viewer_current_portfolio.json()["summary"]["totalValue"]
                == viewer_current_dashboard.json()["summary"]["totalValue"]
            )
            assert Decimal(viewer_current_portfolio.json()["summary"]["totalValue"]) > 0
            portfolio = polling_client.post(
                "/api/v1/portfolio/snapshot", headers=_headers(user_id), json=manifest
            )
            dashboard = polling_client.post(
                "/api/v1/dashboard/snapshot", headers=_headers(user_id), json=manifest
            )
            assert portfolio.status_code == dashboard.status_code == 200, (
                portfolio.text,
                dashboard.text,
            )
            assert (
                portfolio.json()["summary"]["totalValue"]
                == dashboard.json()["summary"]["totalValue"]
            )
            position = portfolio.json()["aggregatePositions"][0]["position"]
            assert position["quantity"] == "3.0000000000"
            assert position["nativeCostBasisByCurrency"] == [
                {"amount": "100.0000000000", "currency": "EUR"},
                {"amount": "200.0000000000", "currency": "USD"},
            ]

            # A terminal exact replay is reported as already imported.  It must not expose a
            # reusable batch identity, upload raw data, or enqueue a second workflow.
            for filename, content in (("r12f-eur.csv", eur_file), ("r12f-usd.csv", usd_file)):
                replay = polling_client.post(
                    f"/api/v1/accounts/{account_id}/imports",
                    headers=_headers(user_id),
                    json={
                        "source": "trading212",
                        "filename": filename,
                        "file_size": len(content),
                        "file_encoding": None,
                        "checksum": hashlib.sha256(content).hexdigest(),
                    },
                )
                assert replay.status_code == 409, replay.text
                assert {
                    key: value
                    for key, value in replay.json()["error"].items()
                    if key != "request_id"
                } == {
                    "code": "import_batch_already_imported",
                    "message": "This import file has already been processed.",
                }

        replayed = asyncio.run(
            _state(account_id=account_id, user_id=user_id, job_id=job_id, listing_id=listing_id)
        )
        assert (
            tuple(batch.id for batch in replayed["batches"]),
            tuple(event.id for event in replayed["events"]),
            replayed["movements"],
            tuple(holding.id for holding in replayed["holdings"]),
            tuple(snapshot.id for snapshot in replayed["snapshots"]),
            tuple(item.id for item in replayed["items"]),
            tuple(snapshot.id for snapshot in replayed["net_worth"]),
        ) == (
            tuple(batch.id for batch in completed["batches"]),
            tuple(event.id for event in completed["events"]),
            completed["movements"],
            tuple(holding.id for holding in completed["holdings"]),
            tuple(snapshot.id for snapshot in completed["snapshots"]),
            tuple(item.id for item in completed["items"]),
            tuple(snapshot.id for snapshot in completed["net_worth"]),
        )
    finally:
        asyncio.run(_cleanup(prefix, account_id=account_id, user_id=user_id, rate_ids=rate_ids))


def test_r12f_duplicate_only_durable_job_publishes_exact_replay_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A new all-duplicate job still durably publishes, without mutating canonical history."""

    assert DATABASE_URL is not None
    prefix = f"r12f-duplicate-{uuid4().hex[:12]}"
    _, eur_file, usd_file, replay_file = _fixture_files(prefix)
    account_id: str | None = None
    user_id: str | None = None
    listing_id: str | None = None
    rate_ids: tuple[str, ...] = ()
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path / "raw-imports"))
    settings = _settings()
    app = create_app(settings)
    try:
        with TestClient(app) as client:
            registered = client.post(
                "/api/v1/auth/register",
                headers=_headers(INTERNAL_AUTH_SERVICE_SUBJECT),
                json={
                    "email": f"{prefix}@example.test",
                    "password": "r12f-duplicate-password",
                    "name": "R12-F duplicate replay",
                },
            )
            assert registered.status_code == 201, registered.text
            user_id = str(registered.json()["id"])
            headers = _headers(user_id)
            account = client.post(
                "/api/v1/accounts",
                headers=headers,
                json={"name": prefix, "type": "broker", "currency": "EUR"},
            )
            assert account.status_code == 201, account.text
            account_id = str(account.json()["id"])
            _, listing_id = asyncio.run(_seed_market_identity(prefix))
            worker_now = datetime.now(UTC).replace(
                tzinfo=None, second=0, microsecond=0
            ) + timedelta(minutes=5)
            harness = _ProviderHarness(worker_now - timedelta(minutes=1))
            monkeypatch.setattr(background_worker_module, "_now", lambda: worker_now)
            monkeypatch.setattr(durable_import_executor_module, "_now", lambda: worker_now)

            initial_batch_ids: list[str] = []
            for filename, content in (("initial-eur.csv", eur_file), ("initial-usd.csv", usd_file)):
                created = client.post(
                    f"/api/v1/accounts/{account_id}/imports",
                    headers=headers,
                    json={
                        "source": "trading212",
                        "filename": filename,
                        "file_size": len(content),
                        "file_encoding": None,
                        "checksum": hashlib.sha256(content).hexdigest(),
                    },
                )
                assert created.status_code == 201, created.text
                batch_id = str(created.json()["batch"]["id"])
                initial_batch_ids.append(batch_id)
                uploaded = client.put(
                    f"/api/v1/accounts/{account_id}/imports/{batch_id}/file",
                    headers=_headers(user_id, binary=True),
                    content=content,
                )
                assert uploaded.status_code == 200, uploaded.text
            initial_job = client.post(
                f"/api/v1/accounts/{account_id}/imports/jobs",
                headers=headers,
                json={"batch_ids": sorted(initial_batch_ids)},
            )
            assert initial_job.status_code == 202, initial_job.text
            initial_job_id = str(initial_job.json()["id"])

        asyncio.run(
            _run_worker(
                prefix=prefix,
                job_id=initial_job_id,
                user_id=user_id,
                settings=settings,
                harness=harness,
            )
        )
        assert account_id is not None and user_id is not None and listing_id is not None
        initial = asyncio.run(
            _state(
                account_id=account_id,
                user_id=user_id,
                job_id=initial_job_id,
                listing_id=listing_id,
            )
        )
        assert initial["job"].status.value == "completed"
        canonical_identity = (
            tuple(event.id for event in initial["events"]),
            initial["movements"],
            tuple(
                (
                    holding.id,
                    holding.quantity,
                    holding.avg_buy_price,
                    holding.cost_basis_by_currency,
                )
                for holding in initial["holdings"]
            ),
        )
        assert canonical_identity[0] and canonical_identity[1] and canonical_identity[2]

        with TestClient(app) as client:
            created = client.post(
                f"/api/v1/accounts/{account_id}/imports",
                headers=_headers(user_id),
                json={
                    "source": "trading212",
                    "filename": "same-canonical-history-different-export.csv",
                    "file_size": len(replay_file),
                    "file_encoding": None,
                    "checksum": hashlib.sha256(replay_file).hexdigest(),
                },
            )
            assert created.status_code == 201, created.text
            duplicate_batch_id = str(created.json()["batch"]["id"])
            uploaded = client.put(
                f"/api/v1/accounts/{account_id}/imports/{duplicate_batch_id}/file",
                headers=_headers(user_id, binary=True),
                content=replay_file,
            )
            assert uploaded.status_code == 200, uploaded.text
            accepted = client.post(
                f"/api/v1/accounts/{account_id}/imports/jobs",
                headers=_headers(user_id),
                json={"batch_ids": [duplicate_batch_id]},
            )
            assert accepted.status_code == 202, accepted.text
            duplicate_job_id = str(accepted.json()["id"])
            assert duplicate_job_id != initial_job_id

        # The first attempt reserves the next immutable minute and yields without consuming an
        # attempt.  It is a real worker execution, not a synthetic status update.
        asyncio.run(
            _run_worker(
                prefix=prefix,
                job_id=duplicate_job_id,
                user_id=user_id,
                settings=settings,
                harness=harness,
            )
        )
        deferred = asyncio.run(
            _state(
                account_id=account_id,
                user_id=user_id,
                job_id=duplicate_job_id,
                listing_id=listing_id,
            )
        )
        assert deferred["job"].status.value == "retry_wait"
        assert deferred["job"].attempt_count == 0
        assert len(deferred["targets"]) == 1
        target = deferred["targets"][0]
        assert target.user_id == user_id
        assert target.published_at is None

        # Advance the worker's durable clock to its persisted bucket.  The stage executor,
        # post-processing service, market refresh, anchor, and fenced completion stay real.
        monkeypatch.setattr(background_worker_module, "_now", lambda: target.bucket)
        monkeypatch.setattr(durable_import_executor_module, "_now", lambda: target.bucket)
        asyncio.run(
            _run_worker(
                prefix=prefix,
                job_id=duplicate_job_id,
                user_id=user_id,
                settings=settings,
                harness=harness,
            )
        )

        duplicate = asyncio.run(
            _state(
                account_id=account_id,
                user_id=user_id,
                job_id=duplicate_job_id,
                listing_id=listing_id,
            )
        )
        assert duplicate["job"].status.value == "completed", (
            duplicate["job"].error_code,
            duplicate["job"].error_message,
            duplicate["job"].checkpoint,
        )
        assert duplicate["job"].attempt_count == 1
        assert duplicate["job"].result == {
            "schema_version": 1,
            "batch_ids": [duplicate_batch_id],
            "rows_total": 3,
            "rows_imported": 0,
            "rows_skipped": 3,
            "snapshot_refresh_status": "created",
            "completed_at": duplicate["job"].result["completed_at"],
        }
        duplicate_batch = next(
            batch for batch in duplicate["batches"] if batch.id == duplicate_batch_id
        )
        assert (
            duplicate_batch.status.value,
            duplicate_batch.rows_total,
            duplicate_batch.rows_imported,
            duplicate_batch.rows_skipped,
        ) == ("completed", 3, 0, 3)
        assert (
            tuple(event.id for event in duplicate["events"]),
            duplicate["movements"],
            tuple(
                (
                    holding.id,
                    holding.quantity,
                    holding.avg_buy_price,
                    holding.cost_basis_by_currency,
                )
                for holding in duplicate["holdings"]
            ),
        ) == canonical_identity
        assert len(duplicate["targets"]) == 1
        completed_target = duplicate["targets"][0]
        assert (
            completed_target.user_id,
            completed_target.bucket,
            completed_target.published_at,
        ) == (user_id, target.bucket, target.bucket)
        anchors = tuple(
            baseline
            for baseline in duplicate["baselines"]
            if baseline.background_job_id == duplicate_job_id
        )
        assert len(anchors) == 1
        assert (
            anchors[0].user_id,
            anchors[0].timestamp,
            anchors[0].granularity,
            anchors[0].source,
        ) == (
            user_id,
            target.bucket,
            SnapshotGranularity.minute,
            SnapshotSource.import_event,
        )

        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        try:

            async def row_statuses() -> tuple[str, ...]:
                async with AsyncSession(engine) as session:
                    rows = tuple(
                        (
                            await session.scalars(
                                select(ImportRowModel.status)
                                .where(ImportRowModel.import_batch_id == duplicate_batch_id)
                                .order_by(ImportRowModel.row_number)
                            )
                        ).all()
                    )
                    return tuple(row.value for row in rows)

            assert asyncio.run(row_statuses()) == ("duplicate", "duplicate", "duplicate")
        finally:
            asyncio.run(engine.dispose())
        rate_ids = tuple(rate.id for rate in duplicate["rates"])
    finally:
        asyncio.run(_cleanup(prefix, account_id=account_id, user_id=user_id, rate_ids=rate_ids))
