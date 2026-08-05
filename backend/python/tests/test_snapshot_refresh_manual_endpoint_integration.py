"""PostgreSQL endpoint evidence for coordinated manual snapshot refresh."""

from __future__ import annotations

import asyncio
import importlib
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.auth.dependencies import get_current_principal, get_request_settings
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    LiabilityBalanceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.snapshot_refresh.api import (
    get_market_backed_snapshot_refresh_service,
    get_user_snapshot_refresh_clock,
)
from app.modules.snapshot_refresh.executor import (
    ExecuteUserSnapshotRefreshCommand,
    ExecuteUserSnapshotRefreshResult,
    SnapshotRefreshExecutionConflictError,
    UserSnapshotRefreshExecutor,
)
from app.modules.snapshot_refresh.market_backed_service import (
    MarketBackedSnapshotRefreshService,
)
from app.modules.snapshots.writer import AccountSnapshotWriter, WriteAccountSnapshotCommand

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
BUCKET = datetime(2036, 7, 29, 14, 35)
EVIDENCE_AT = BUCKET - timedelta(days=1)
market_support = cast(
    Any,
    importlib.import_module("tests.test_market_backed_snapshot_refresh_integration"),
)


@dataclass(frozen=True, slots=True)
class _AccountSpec:
    suffix: str
    role: AccountMemberRole = AccountMemberRole.owner
    currency: str = "EUR"
    amount: Decimal = Decimal("100")
    account_type: AccountType = AccountType.loan


def _engine() -> AsyncEngine:
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=12)


def _user_id(prefix: str) -> str:
    return f"{prefix}-user"


def _account_id(prefix: str, suffix: str) -> str:
    return f"{prefix}-{suffix}"


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.test",
        name=user_id,
    )


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            user_ids = tuple(
                await session.scalars(
                    select(UserModel.id).where(UserModel.id.startswith(f"{prefix}-"))
                )
            )
            account_ids = tuple(
                await session.scalars(
                    select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
                )
            )
            snapshot_ids = (
                tuple(
                    await session.scalars(
                        select(AccountSnapshotModel.id).where(
                            AccountSnapshotModel.account_id.in_(account_ids)
                        )
                    )
                )
                if account_ids
                else ()
            )
            if snapshot_ids:
                await session.execute(
                    delete(AccountSnapshotItemModel).where(
                        AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids)
                    )
                )
            if user_ids:
                await session.execute(
                    delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id.in_(user_ids))
                )
            if account_ids:
                await session.execute(
                    delete(AccountSnapshotModel).where(
                        AccountSnapshotModel.account_id.in_(account_ids)
                    )
                )
                await session.execute(
                    delete(LiabilityBalanceModel).where(
                        LiabilityBalanceModel.account_id.in_(account_ids)
                    )
                )
                await session.execute(
                    delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
                )
                await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
            if user_ids:
                await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
            await session.commit()
    finally:
        await engine.dispose()


async def _seed(prefix: str, specs: tuple[_AccountSpec, ...]) -> None:
    await _cleanup(prefix)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                UserModel(
                    id=_user_id(prefix),
                    email=f"{prefix}@example.test",
                    name="Manual snapshot refresh",
                    password_hash=None,
                    base_currency="EUR",
                    created_at=EVIDENCE_AT,
                    updated_at=EVIDENCE_AT,
                )
            )
            for spec in specs:
                account_id = _account_id(prefix, spec.suffix)
                session.add(
                    AccountModel(
                        id=account_id,
                        name=spec.suffix,
                        type=spec.account_type,
                        currency=spec.currency,
                        color=None,
                        is_archived=False,
                        archived_at=None,
                        created_at=EVIDENCE_AT,
                        updated_at=EVIDENCE_AT,
                        notes=None,
                    )
                )
                await session.flush()
                session.add(
                    AccountMemberModel(
                        id=f"{prefix}-member-{spec.suffix}",
                        account_id=account_id,
                        user_id=_user_id(prefix),
                        role=spec.role,
                        relation_type=AccountRelationType.owner,
                        invited_by_id=None,
                        accepted_at=EVIDENCE_AT,
                        created_at=EVIDENCE_AT,
                        updated_at=EVIDENCE_AT,
                    )
                )
                if spec.account_type in {
                    AccountType.credit_card,
                    AccountType.loan,
                    AccountType.mortgage,
                }:
                    session.add(
                        LiabilityBalanceModel(
                            id=f"{prefix}-balance-{spec.suffix}",
                            account_id=account_id,
                            effective_at=EVIDENCE_AT,
                            currency=spec.currency,
                            outstanding_principal=spec.amount,
                            accrued_interest=Decimal("0"),
                            fees_outstanding=Decimal("0"),
                            total_outstanding=spec.amount,
                            source=LiabilityBalanceSource.statement,
                            external_id=f"{prefix}-external-{spec.suffix}",
                            created_at=EVIDENCE_AT,
                        )
                    )
            await session.commit()
    finally:
        await engine.dispose()


async def _write_viewer_snapshot(prefix: str, suffix: str) -> str:
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            result = await AccountSnapshotWriter(session).write(
                WriteAccountSnapshotCommand(
                    account_id=_account_id(prefix, suffix),
                    snapshot_timestamp=BUCKET,
                    granularity=SnapshotGranularity.minute,
                    source=SnapshotSource.manual_recalculation,
                    calculation_version=1,
                    calculated_at=BUCKET,
                    created_at=BUCKET,
                    is_recalculated=True,
                    output_currency="EUR",
                )
            )
        return result.snapshot_id
    finally:
        await engine.dispose()


def _call(prefix: str, *, user_id: str | None = None):
    settings = Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        internal_auth_secret="test-secret-that-is-long-enough-for-auth",
        _env_file=None,
    )
    app = create_app(settings)
    principal_id = _user_id(prefix) if user_id is None else user_id
    app.dependency_overrides[get_current_principal] = lambda: _principal(principal_id)
    app.dependency_overrides[get_user_snapshot_refresh_clock] = lambda: lambda: BUCKET
    with TestClient(app) as client:
        return client.post("/api/v1/snapshot-refresh/recalculate")


def _call_with_forbidden_provider_http(prefix: str):
    settings = Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        internal_auth_secret="r5b3b-no-fallback-secret-that-is-long-enough",
        twelve_data_api_key=market_support.TWELVE_API_KEY,
        _env_file=None,
    )
    app = create_app(settings)
    app.dependency_overrides[get_current_principal] = lambda: _principal(_user_id(prefix))
    app.dependency_overrides[get_user_snapshot_refresh_clock] = lambda: lambda: BUCKET
    requests: list[str] = []

    def unexpected_http(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(503)

    transport = httpx.MockTransport(unexpected_http)

    def market_backed_dependency(
        session: AsyncSession = Depends(get_db_session),
        request_settings: Settings = Depends(get_request_settings),
    ) -> MarketBackedSnapshotRefreshService:
        def market_factory(
            active_session: AsyncSession,
            active_settings: Settings,
        ):
            return create_production_market_evidence_service(
                active_session,
                active_settings,
                http_transport=transport,
                coingecko_http_transport=transport,
                twelve_data_http_transport=transport,
            )

        return MarketBackedSnapshotRefreshService(
            session,
            request_settings,
            market_service_factory=market_factory,
        )

    app.dependency_overrides[get_market_backed_snapshot_refresh_service] = market_backed_dependency
    with TestClient(app) as client:
        response = client.post("/api/v1/snapshot-refresh/recalculate")
    return response, requests


class _MarketEvidenceOrderCheckingExecutor:
    def __init__(
        self,
        session: AsyncSession,
        *,
        listing_ids: tuple[str, str],
        checks: list[tuple[int, int]],
    ) -> None:
        self.session = session
        self.listing_ids = listing_ids
        self.checks = checks

    async def execute(
        self,
        command: ExecuteUserSnapshotRefreshCommand,
    ) -> ExecuteUserSnapshotRefreshResult:
        price_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(PriceSnapshotModel)
                .where(PriceSnapshotModel.listing_id.in_(self.listing_ids))
            )
            or 0
        )
        rate_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(ExchangeRateModel)
                .where(
                    ExchangeRateModel.source == market_support.ExchangeRateSource.cnb,
                    ExchangeRateModel.from_currency.in_(("EUR", "USD")),
                    ExchangeRateModel.to_currency == "CZK",
                    ExchangeRateModel.date.in_(
                        (
                            market_support.EVENT_AT.replace(hour=0),
                            market_support.SNAPSHOT_AT,
                        )
                    ),
                )
            )
            or 0
        )
        self.checks.append((price_count, rate_count))
        await self.session.rollback()
        return await UserSnapshotRefreshExecutor(self.session).execute(command)


class _ConflictingSnapshotExecutor:
    async def execute(self, command: ExecuteUserSnapshotRefreshCommand) -> object:
        raise SnapshotRefreshExecutionConflictError()


def _mixed_endpoint_call(
    *,
    user_id: str,
    listed_symbol: str,
    crypto_alias: str,
    listing_ids: tuple[str, str],
    provider_call_batches: list[list[tuple[str, str]]],
    order_checks: list[tuple[int, int]] | None = None,
    twelve_status: int = 200,
    coingecko_stale: bool = False,
    cnb_status: int = 200,
    snapshot_conflict: bool = False,
):
    settings = Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        internal_auth_secret="r5b3b-endpoint-secret-that-is-long-enough",
        twelve_data_api_key=market_support.TWELVE_API_KEY,
        _env_file=None,
    )
    app = create_app(settings)
    app.dependency_overrides[get_current_principal] = lambda: _principal(user_id)
    app.dependency_overrides[get_user_snapshot_refresh_clock] = lambda: (
        lambda: market_support.SNAPSHOT_AT
    )

    def market_backed_dependency(
        session: AsyncSession = Depends(get_db_session),
        request_settings: Settings = Depends(get_request_settings),
    ) -> MarketBackedSnapshotRefreshService:
        twelve, coingecko, cnb, calls = market_support._transports(
            session,
            listed_symbol=listed_symbol,
            crypto_alias=crypto_alias,
            twelve_status=twelve_status,
            coingecko_stale=coingecko_stale,
            cnb_status=cnb_status,
        )
        provider_call_batches.append(calls)

        def market_factory(
            active_session: AsyncSession,
            active_settings: Settings,
        ):
            return create_production_market_evidence_service(
                active_session,
                active_settings,
                http_transport=cnb,
                coingecko_http_transport=coingecko,
                twelve_data_http_transport=twelve,
            )

        snapshot_executor: object | None = None
        if snapshot_conflict:
            snapshot_executor = _ConflictingSnapshotExecutor()
        elif order_checks is not None:
            snapshot_executor = _MarketEvidenceOrderCheckingExecutor(
                session,
                listing_ids=listing_ids,
                checks=order_checks,
            )
        return MarketBackedSnapshotRefreshService(
            session,
            request_settings,
            market_service_factory=market_factory,
            snapshot_executor=snapshot_executor,  # type: ignore[arg-type]
        )

    app.dependency_overrides[get_market_backed_snapshot_refresh_service] = market_backed_dependency
    with TestClient(app) as client:
        return client.post("/api/v1/snapshot-refresh/recalculate")


def _flatten_provider_calls(
    batches: list[list[tuple[str, str]]],
) -> list[tuple[str, str]]:
    return [call for batch in batches for call in batch]


async def _counts(prefix: str) -> tuple[int, int]:
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            account_ids = select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
            account_count = (
                await session.scalar(
                    select(func.count())
                    .select_from(AccountSnapshotModel)
                    .where(AccountSnapshotModel.account_id.in_(account_ids))
                )
                or 0
            )
            net_worth_count = (
                await session.scalar(
                    select(func.count())
                    .select_from(NetWorthSnapshotModel)
                    .where(NetWorthSnapshotModel.user_id == _user_id(prefix))
                )
                or 0
            )
            return int(account_count), int(net_worth_count)
    finally:
        await engine.dispose()


def test_production_mixed_provider_endpoint_e2e_and_replay() -> None:
    unique = uuid4().hex[:10]
    prefix = f"r5b3b-mixed-{uuid4()}"
    listed_symbol = f"T{unique.upper()}"
    listed_alias = f'{{"symbol":"{listed_symbol}","mic_code":"XNAS"}}'
    crypto_symbol = f"C{unique.upper()}"
    crypto_alias = f"coin-{unique}"
    user_id, account_ids, asset_ids, listing_ids = asyncio.run(
        market_support._seed_mixed_user(
            prefix,
            listed_aliases=(listed_alias,),
            crypto_aliases=(crypto_alias,),
            listed_symbol=listed_symbol,
            crypto_symbol=crypto_symbol,
        )
    )
    provider_call_batches: list[list[tuple[str, str]]] = []
    order_checks: list[tuple[int, int]] = []

    first = _mixed_endpoint_call(
        user_id=user_id,
        listed_symbol=listed_symbol,
        crypto_alias=crypto_alias,
        listing_ids=listing_ids,
        provider_call_batches=provider_call_batches,
        order_checks=order_checks,
    )
    replay = _mixed_endpoint_call(
        user_id=user_id,
        listed_symbol=listed_symbol,
        crypto_alias=crypto_alias,
        listing_ids=listing_ids,
        provider_call_batches=provider_call_batches,
        order_checks=order_checks,
    )

    assert first.status_code == replay.status_code == 200
    assert first.json()["currency"] == "CZK"
    assert first.json()["granularity"] == "minute"
    assert first.json()["createdAccountSnapshotCount"] == 2
    assert first.json()["replayedAccountSnapshotCount"] == 0
    assert replay.json()["createdAccountSnapshotCount"] == 0
    assert replay.json()["replayedAccountSnapshotCount"] == 2
    assert replay.json()["netWorthStatus"] == "replayed"
    assert replay.json()["netWorthSnapshotId"] == first.json()["netWorthSnapshotId"]
    assert replay.json()["accounts"] == first.json()["accounts"]
    assert tuple(item["accountId"] for item in first.json()["accounts"]) == account_ids
    assert order_checks == [(2, 4), (2, 4)]
    expected_calls = [
        ("twelve_data", listed_symbol),
        ("coingecko", crypto_alias),
        ("cnb", "01.08.2026"),
        ("cnb", "06.08.2026"),
        ("cnb", "01.08.2026"),
        ("cnb", "06.08.2026"),
    ]
    assert _flatten_provider_calls(provider_call_batches) == expected_calls * 2

    forbidden_market_keys = {
        "market",
        "provider",
        "providerSymbol",
        "priceIds",
        "exchangeRateIds",
        "requiredPriceCount",
        "requiredFxCount",
        "pricesCreated",
        "pricesReplayed",
        "ratesCreated",
        "ratesReplayed",
    }

    def audit(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden_market_keys.isdisjoint(value)
            for child in value.values():
                audit(child)
        elif isinstance(value, list):
            for child in value:
                audit(child)

    audit(first.json())

    async def verify_persistence_and_lineage() -> None:
        engine = _engine()
        try:
            async with AsyncSession(engine) as session:
                expected_prices = tuple(
                    sorted(
                        (
                            market_support.price_snapshot_id(
                                market_support.PriceObservation(
                                    asset_id=asset_ids[0],
                                    listing_id=listing_ids[0],
                                    provider=market_support.PriceSource.twelve_data,
                                    provider_symbol=listed_alias,
                                    price=Decimal("225.3200000000"),
                                    currency="USD",
                                    observed_at=market_support.TWELVE_OBSERVED_AT,
                                )
                            ),
                            market_support.price_snapshot_id(
                                market_support.PriceObservation(
                                    asset_id=asset_ids[1],
                                    listing_id=listing_ids[1],
                                    provider=market_support.PriceSource.coingecko,
                                    provider_symbol=crypto_alias,
                                    price=Decimal("414.5888000000"),
                                    currency="EUR",
                                    observed_at=market_support.COINGECKO_OBSERVED_AT,
                                )
                            ),
                        )
                    )
                )
                expected_rates = tuple(
                    sorted(
                        market_support.exchange_rate_id(
                            market_support.ExchangeRateObservation(
                                from_currency=currency,
                                to_currency="CZK",
                                provider=market_support.ExchangeRateSource.cnb,
                                rate=rate,
                                effective_at=through,
                            )
                        )
                        for currency, rate, through in (
                            (
                                "EUR",
                                Decimal("24.00000000"),
                                market_support.EVENT_AT.replace(hour=0),
                            ),
                            (
                                "EUR",
                                Decimal("25.00000000"),
                                market_support.SNAPSHOT_AT,
                            ),
                            (
                                "USD",
                                Decimal("22.00000000"),
                                market_support.EVENT_AT.replace(hour=0),
                            ),
                            (
                                "USD",
                                Decimal("23.00000000"),
                                market_support.SNAPSHOT_AT,
                            ),
                        )
                    )
                )
                assert (
                    tuple(
                        await session.scalars(
                            select(PriceSnapshotModel.id)
                            .where(PriceSnapshotModel.listing_id.in_(listing_ids))
                            .order_by(PriceSnapshotModel.id)
                        )
                    )
                    == expected_prices
                )
                assert (
                    tuple(
                        await session.scalars(
                            select(ExchangeRateModel.id)
                            .where(ExchangeRateModel.id.in_(expected_rates))
                            .order_by(ExchangeRateModel.id)
                        )
                    )
                    == expected_rates
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AccountSnapshotModel)
                        .where(AccountSnapshotModel.account_id.in_(account_ids))
                    )
                    == 2
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(NetWorthSnapshotModel)
                        .where(NetWorthSnapshotModel.user_id == user_id)
                    )
                    == 1
                )
                await session.rollback()

                selected_prices: list[str] = []
                selected_snapshot_rates: list[str] = []
                selected_historical_rates: list[str] = []
                for item in first.json()["accounts"]:
                    async with session.begin():
                        evidence = await market_support.AccountSnapshotEvidenceService(
                            session
                        ).build(
                            market_support.BuildAccountSnapshotEvidenceCommand(
                                account_id=item["accountId"],
                                snapshot_timestamp=market_support.SNAPSHOT_AT,
                                granularity=SnapshotGranularity.minute,
                                source=SnapshotSource.manual_recalculation,
                                calculation_version=1,
                                output_currency="CZK",
                            )
                        )
                    selected_prices.extend(evidence.selected_price_ids)
                    selected_snapshot_rates.extend(evidence.selected_snapshot_exchange_rate_ids)
                    selected_historical_rates.extend(evidence.selected_historical_exchange_rate_ids)
                assert tuple(sorted(selected_prices)) == expected_prices
                assert set(selected_snapshot_rates).isdisjoint(selected_historical_rates)
                assert (
                    tuple(sorted(selected_snapshot_rates + selected_historical_rates))
                    == expected_rates
                )

                read_command = market_support.ReadAuthorizedMultiAccountPortfolioSnapshotCommand(
                    principal=market_support._principal(user_id),
                    timestamp=market_support.SNAPSHOT_AT,
                    granularity=(market_support.PortfolioSnapshotGranularity.minute),
                    currency="CZK",
                    calculation_version=1,
                    accounts=tuple(
                        market_support.ExactAccountSnapshotSelection(
                            account_id=item["accountId"],
                            required_snapshot_id=item["snapshotId"],
                        )
                        for item in first.json()["accounts"]
                    ),
                )
                portfolio = (
                    await market_support.AuthorizedMultiAccountPortfolioSnapshotService(
                        session
                    ).read(read_command)
                ).portfolio
                dashboard = (
                    await market_support.AuthorizedDashboardSnapshotService(
                        market_support.AuthorizedMultiAccountPortfolioSnapshotService(session)
                    ).read(read_command)
                ).dashboard
                assert portfolio.summary.account_count == dashboard.summary.account_count == 2
                assert portfolio.summary.position_count == dashboard.summary.position_count == 2
                assert portfolio.summary.cash_value == dashboard.summary.cash_value
                assert portfolio.summary.investment_value == dashboard.summary.investment_value
                assert portfolio.summary.total_value == dashboard.summary.total_value
        finally:
            await engine.dispose()

    asyncio.run(verify_persistence_and_lineage())


@pytest.mark.parametrize(
    ("failure", "expected_call_count"),
    [
        ("twelve-429", 1),
        ("coingecko-stale", 2),
        ("cnb-failure", 3),
    ],
)
def test_provider_failure_endpoint_matrix_writes_no_market_or_snapshot_graph(
    failure: str,
    expected_call_count: int,
) -> None:
    unique = uuid4().hex[:10]
    prefix = f"r5b3b-{failure}-{uuid4()}"
    listed_symbol = f"T{unique.upper()}"
    listed_alias = f'{{"symbol":"{listed_symbol}","mic_code":"XNAS"}}'
    crypto_alias = f"coin-{unique}"
    user_id, account_ids, _, listing_ids = asyncio.run(
        market_support._seed_mixed_user(
            prefix,
            listed_aliases=(listed_alias,),
            crypto_aliases=(crypto_alias,),
            listed_symbol=listed_symbol,
            crypto_symbol=f"C{unique.upper()}",
        )
    )

    async def rates_before() -> int:
        engine = _engine()
        try:
            async with AsyncSession(engine) as session:
                return int(
                    await session.scalar(select(func.count()).select_from(ExchangeRateModel)) or 0
                )
        finally:
            await engine.dispose()

    initial_rate_count = asyncio.run(rates_before())
    provider_call_batches: list[list[tuple[str, str]]] = []
    response = _mixed_endpoint_call(
        user_id=user_id,
        listed_symbol=listed_symbol,
        crypto_alias=crypto_alias,
        listing_ids=listing_ids,
        provider_call_batches=provider_call_batches,
        twelve_status=429 if failure == "twelve-429" else 200,
        coingecko_stale=failure == "coingecko-stale",
        cnb_status=503 if failure == "cnb-failure" else 200,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "snapshot_refresh_unavailable"
    assert len(_flatten_provider_calls(provider_call_batches)) == expected_call_count

    async def verify_empty() -> None:
        engine = _engine()
        try:
            async with AsyncSession(engine) as session:
                assert await market_support._counts(
                    session,
                    user_id=user_id,
                    account_ids=account_ids,
                    listing_ids=listing_ids,
                ) == (0, initial_rate_count, 0, 0)
        finally:
            await engine.dispose()

    asyncio.run(verify_empty())


@pytest.mark.parametrize("alias_failure", ["missing", "ambiguous"])
def test_alias_failure_endpoint_stops_before_provider_http(
    alias_failure: str,
) -> None:
    unique = uuid4().hex[:10]
    prefix = f"r5b3b-alias-{alias_failure}-{uuid4()}"
    listed_symbol = f"T{unique.upper()}"
    listed_aliases = (
        ()
        if alias_failure == "missing"
        else (
            f'{{"symbol":"{listed_symbol}","mic_code":"XNAS"}}',
            f'{{"symbol":"ALT{unique.upper()}","mic_code":"XNAS"}}',
        )
    )
    crypto_alias = f"coin-{unique}"
    user_id, account_ids, _, listing_ids = asyncio.run(
        market_support._seed_mixed_user(
            prefix,
            listed_aliases=listed_aliases,
            crypto_aliases=(crypto_alias,),
            listed_symbol=listed_symbol,
            crypto_symbol=f"C{unique.upper()}",
        )
    )
    provider_call_batches: list[list[tuple[str, str]]] = []
    response = _mixed_endpoint_call(
        user_id=user_id,
        listed_symbol=listed_symbol,
        crypto_alias=crypto_alias,
        listing_ids=listing_ids,
        provider_call_batches=provider_call_batches,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "snapshot_refresh_unavailable"
    assert _flatten_provider_calls(provider_call_batches) == []

    async def verify_empty() -> None:
        engine = _engine()
        try:
            async with AsyncSession(engine) as session:
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(PriceSnapshotModel)
                        .where(PriceSnapshotModel.listing_id.in_(listing_ids))
                    )
                    == 0
                )
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(AccountSnapshotModel)
                        .where(AccountSnapshotModel.account_id.in_(account_ids))
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

    asyncio.run(verify_empty())


def test_snapshot_conflict_after_market_commit_preserves_market_evidence() -> None:
    unique = uuid4().hex[:10]
    prefix = f"r5b3b-snapshot-conflict-{uuid4()}"
    listed_symbol = f"T{unique.upper()}"
    listed_alias = f'{{"symbol":"{listed_symbol}","mic_code":"XNAS"}}'
    crypto_alias = f"coin-{unique}"
    user_id, account_ids, _, listing_ids = asyncio.run(
        market_support._seed_mixed_user(
            prefix,
            listed_aliases=(listed_alias,),
            crypto_aliases=(crypto_alias,),
            listed_symbol=listed_symbol,
            crypto_symbol=f"C{unique.upper()}",
        )
    )
    provider_call_batches: list[list[tuple[str, str]]] = []
    response = _mixed_endpoint_call(
        user_id=user_id,
        listed_symbol=listed_symbol,
        crypto_alias=crypto_alias,
        listing_ids=listing_ids,
        provider_call_batches=provider_call_batches,
        snapshot_conflict=True,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "snapshot_refresh_conflict"
    assert len(_flatten_provider_calls(provider_call_batches)) == 6

    async def verify_two_phase_persistence() -> None:
        engine = _engine()
        try:
            async with AsyncSession(engine) as session:
                prices, _, snapshots, net_worth = await market_support._counts(
                    session,
                    user_id=user_id,
                    account_ids=account_ids,
                    listing_ids=listing_ids,
                )
                assert prices == 2
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(ExchangeRateModel)
                        .where(
                            ExchangeRateModel.source == market_support.ExchangeRateSource.cnb,
                            ExchangeRateModel.from_currency.in_(("EUR", "USD")),
                            ExchangeRateModel.to_currency == "CZK",
                            ExchangeRateModel.date.in_(
                                (
                                    market_support.EVENT_AT.replace(hour=0),
                                    market_support.SNAPSHOT_AT,
                                )
                            ),
                        )
                    )
                    == 4
                )
                assert snapshots == net_worth == 0
        finally:
            await engine.dispose()

    asyncio.run(verify_two_phase_persistence())


def test_mixed_create_and_fresh_session_replay() -> None:
    prefix = "k5e1-mixed"
    asyncio.run(
        _seed(
            prefix,
            (
                _AccountSpec("a-owner"),
                _AccountSpec("b-editor", AccountMemberRole.editor),
                _AccountSpec("c-viewer", AccountMemberRole.viewer),
            ),
        )
    )
    asyncio.run(_write_viewer_snapshot(prefix, "c-viewer"))
    try:
        first = _call(prefix)
        replay = _call(prefix)

        assert first.status_code == replay.status_code == 200
        assert first.json() == {
            "netWorthSnapshotId": first.json()["netWorthSnapshotId"],
            "netWorthStatus": "created",
            "timestamp": "2036-07-29T14:35:00.000",
            "granularity": "minute",
            "currency": "EUR",
            "calculationVersion": 1,
            "accounts": first.json()["accounts"],
            "refreshAccountCount": 2,
            "reuseOnlyAccountCount": 1,
            "createdAccountSnapshotCount": 2,
            "replayedAccountSnapshotCount": 0,
            "reusedAccountSnapshotCount": 1,
            "selectedAccountSnapshotCount": 3,
        }
        assert replay.json()["netWorthStatus"] == "replayed"
        assert replay.json()["netWorthSnapshotId"] == first.json()["netWorthSnapshotId"]
        assert replay.json()["createdAccountSnapshotCount"] == 0
        assert replay.json()["replayedAccountSnapshotCount"] == 2
        assert replay.json()["reusedAccountSnapshotCount"] == 1
        assert replay.json()["accounts"] == first.json()["accounts"]
        assert [item["accountId"] for item in first.json()["accounts"]] == [
            _account_id(prefix, "a-owner"),
            _account_id(prefix, "b-editor"),
            _account_id(prefix, "c-viewer"),
        ]
        assert len({item["snapshotId"] for item in first.json()["accounts"]}) == 3
        assert asyncio.run(_counts(prefix)) == (3, 1)
    finally:
        asyncio.run(_cleanup(prefix))


def test_missing_viewer_coverage_is_generic_and_writes_nothing() -> None:
    prefix = "k5e1-viewer-missing"
    asyncio.run(
        _seed(
            prefix,
            (
                _AccountSpec("a-owner"),
                _AccountSpec("b-viewer", AccountMemberRole.viewer),
            ),
        )
    )
    try:
        response = _call(prefix)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "snapshot_refresh_unavailable"
        assert response.json()["error"]["message"] == (
            "Snapshot refresh cannot be completed from the current account data."
        )
        assert _account_id(prefix, "b-viewer") not in response.text
        assert asyncio.run(_counts(prefix)) == (0, 0)
    finally:
        asyncio.run(_cleanup(prefix))


def test_unsupported_non_czk_direct_fx_fails_before_snapshot_writes() -> None:
    prefix = "r5b3b-unsupported-direct-fx"
    asyncio.run(
        _seed(
            prefix,
            (
                _AccountSpec("a-eur"),
                _AccountSpec("b-usd", currency="USD"),
            ),
        )
    )
    try:

        async def matching_rate_count() -> int:
            engine = _engine()
            try:
                async with AsyncSession(engine) as session:
                    return int(
                        await session.scalar(
                            select(func.count())
                            .select_from(ExchangeRateModel)
                            .where(
                                ExchangeRateModel.from_currency == "USD",
                                ExchangeRateModel.to_currency == "EUR",
                                ExchangeRateModel.date.in_((EVIDENCE_AT, BUCKET)),
                            )
                        )
                        or 0
                    )
            finally:
                await engine.dispose()

        before = asyncio.run(matching_rate_count())
        first, provider_requests = _call_with_forbidden_provider_http(prefix)
        assert first.status_code == 409
        assert first.json()["error"]["code"] == "snapshot_refresh_unavailable"
        assert first.json()["error"]["message"] == (
            "Snapshot refresh cannot be completed from the current account data."
        )
        assert "USD" not in first.text
        assert provider_requests == []
        assert asyncio.run(_counts(prefix)) == (0, 0)
        assert asyncio.run(matching_rate_count()) == before
    finally:
        asyncio.run(_cleanup(prefix))


def test_empty_user_creates_and_replays_zero_account_net_worth() -> None:
    prefix = "k5e1-empty"
    asyncio.run(_seed(prefix, ()))
    try:
        first = _call(prefix)
        second = _call(prefix)
        assert first.status_code == second.status_code == 200
        assert first.json()["netWorthStatus"] == "created"
        assert second.json()["netWorthStatus"] == "replayed"
        for field in (
            "refreshAccountCount",
            "reuseOnlyAccountCount",
            "createdAccountSnapshotCount",
            "replayedAccountSnapshotCount",
            "reusedAccountSnapshotCount",
            "selectedAccountSnapshotCount",
        ):
            assert first.json()[field] == second.json()[field] == 0
        assert asyncio.run(_counts(prefix)) == (0, 1)
    finally:
        asyncio.run(_cleanup(prefix))


@pytest.mark.parametrize(
    "account_type",
    [AccountType.bank, AccountType.cash, AccountType.savings],
)
def test_empty_market_plan_refreshes_supported_non_investment_account(
    account_type: AccountType,
) -> None:
    prefix = f"r5b3b-empty-market-{account_type.value}"
    asyncio.run(_seed(prefix, (_AccountSpec("a", account_type=account_type),)))
    try:
        response = _call(prefix)
        assert response.status_code == 200
        assert response.json()["createdAccountSnapshotCount"] == 1
        assert response.json()["selectedAccountSnapshotCount"] == 1
        assert asyncio.run(_counts(prefix)) == (1, 1)
    finally:
        asyncio.run(_cleanup(prefix))


def test_physical_conflict_is_generic_and_does_not_repair() -> None:
    prefix = "k5e1-conflict"
    asyncio.run(_seed(prefix, (_AccountSpec("a"),)))
    try:
        first = _call(prefix)
        assert first.status_code == 200

        async def corrupt() -> datetime:
            corrupted_at = BUCKET + timedelta(minutes=1)
            engine = _engine()
            try:
                async with AsyncSession(engine) as session:
                    snapshot_id = await session.scalar(
                        select(AccountSnapshotModel.id).where(
                            AccountSnapshotModel.account_id == _account_id(prefix, "a")
                        )
                    )
                    assert snapshot_id is not None
                    await session.execute(
                        update(AccountSnapshotModel)
                        .where(AccountSnapshotModel.id == snapshot_id)
                        .values(created_at=corrupted_at)
                    )
                    await session.commit()
                return corrupted_at
            finally:
                await engine.dispose()

        corrupted_at = asyncio.run(corrupt())
        response = _call(prefix)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "snapshot_refresh_conflict"
        assert first.json()["netWorthSnapshotId"] not in response.text

        async def persisted_created_at() -> datetime:
            engine = _engine()
            try:
                async with AsyncSession(engine) as session:
                    value = await session.scalar(
                        select(AccountSnapshotModel.created_at).where(
                            AccountSnapshotModel.account_id == _account_id(prefix, "a")
                        )
                    )
                    assert value is not None
                    return value
            finally:
                await engine.dispose()

        assert asyncio.run(persisted_created_at()) == corrupted_at
        assert asyncio.run(_counts(prefix)) == (1, 1)
    finally:
        asyncio.run(_cleanup(prefix))


def test_principal_isolation_uses_only_current_user() -> None:
    prefix_a = "k5e1-principal-a"
    prefix_b = "k5e1-principal-b"
    asyncio.run(_seed(prefix_a, (_AccountSpec("a"),)))
    asyncio.run(_seed(prefix_b, (_AccountSpec("b"),)))
    try:
        response = _call(prefix_a)
        assert response.status_code == 200
        assert _user_id(prefix_a) not in response.text
        assert _user_id(prefix_b) not in response.text
        assert asyncio.run(_counts(prefix_a)) == (1, 1)
        assert asyncio.run(_counts(prefix_b)) == (0, 0)
    finally:
        asyncio.run(_cleanup(prefix_a))
        asyncio.run(_cleanup(prefix_b))


def test_concurrent_requests_converge_without_duplicate_rows() -> None:
    prefix = "k5e1-concurrent"
    asyncio.run(_seed(prefix, (_AccountSpec("a"),)))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(_call, prefix)
            second_future = pool.submit(_call, prefix)
            first = first_future.result(timeout=30)
            second = second_future.result(timeout=30)
        assert first.status_code == second.status_code == 200
        assert {first.json()["netWorthStatus"], second.json()["netWorthStatus"]} == {
            "created",
            "replayed",
        }
        assert first.json()["netWorthSnapshotId"] == second.json()["netWorthSnapshotId"]
        account_dispositions = {
            (
                response.json()["createdAccountSnapshotCount"],
                response.json()["replayedAccountSnapshotCount"],
            )
            for response in (first, second)
        }
        assert account_dispositions == {(1, 0), (0, 1)}
        assert asyncio.run(_counts(prefix)) == (1, 1)
    finally:
        asyncio.run(_cleanup(prefix))
