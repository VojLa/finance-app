from __future__ import annotations

import os
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from support.cnb_fx import cnb_xml

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetAliasProvider,
    AssetType,
    ExchangeRateSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshots import (
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.dashboard_snapshot.authorized_service import (
    AuthorizedDashboardSnapshotService,
)
from app.modules.fx.models import ExchangeRateObservation
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.market_data.writer import exchange_rate_id, price_snapshot_id
from app.modules.portfolio_snapshot.models import (
    SnapshotGranularity as PortfolioSnapshotGranularity,
)
from app.modules.portfolio_snapshot.multi_account_service import (
    AuthorizedMultiAccountPortfolioSnapshotService,
    ExactAccountSnapshotSelection,
    ReadAuthorizedMultiAccountPortfolioSnapshotCommand,
)
from app.modules.prices.models import PriceObservation
from app.modules.snapshot_refresh.executor import (
    SnapshotRefreshExecutionStateError,
)
from app.modules.snapshot_refresh.market_backed_models import (
    ExecuteMarketBackedSnapshotRefreshCommand,
    MarketBackedSnapshotRefreshUnavailableError,
)
from app.modules.snapshot_refresh.market_backed_service import (
    MarketBackedSnapshotRefreshService,
)
from app.modules.snapshots.evidence_service import (
    AccountSnapshotEvidenceService,
    BuildAccountSnapshotEvidenceCommand,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="PostgreSQL integration test requires DATABASE_URL.",
)

EVENT_AT = datetime(2026, 8, 1, 10)
SNAPSHOT_AT = datetime(2026, 8, 6)
TWELVE_OBSERVED_AT = datetime(2026, 8, 5, 12, 34)
COINGECKO_OBSERVED_AT = datetime(2026, 8, 5, 23)
CALCULATED_AT = datetime(2026, 8, 6, 0, 0, 1)
CREATED_AT = datetime(2026, 8, 6, 0, 0, 2)
TWELVE_API_KEY = "r5b3a-test-server-key"


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=8)


def _command(user_id: str) -> ExecuteMarketBackedSnapshotRefreshCommand:
    return ExecuteMarketBackedSnapshotRefreshCommand(
        user_id=user_id,
        snapshot_timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.price_refresh,
        calculation_version=1,
        calculated_at=CALCULATED_AT,
        created_at=CREATED_AT,
        is_recalculated=False,
    )


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.test",
    )


async def _seed_mixed_user(
    prefix: str,
    *,
    listed_aliases: tuple[str, ...],
    crypto_aliases: tuple[str, ...],
    listed_symbol: str,
    crypto_symbol: str,
) -> tuple[str, tuple[str, str], tuple[str, str], tuple[str, str]]:
    user_id = f"{prefix}-user"
    broker_id = f"{prefix}-account-broker"
    exchange_id = f"{prefix}-account-exchange"
    listed_asset_id = f"{prefix}-asset-listed"
    crypto_asset_id = f"{prefix}-asset-crypto"
    listed_listing_id = f"{prefix}-listing-listed"
    crypto_listing_id = f"{prefix}-listing-crypto"
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    name=None,
                    password_hash=None,
                    base_currency="CZK",
                    created_at=CREATED_AT,
                    updated_at=CREATED_AT,
                )
            )
            session.add_all(
                (
                    AccountModel(
                        id=broker_id,
                        name="Synthetic broker",
                        type=AccountType.broker,
                        currency="USD",
                        color=None,
                        notes=None,
                        is_archived=False,
                        archived_at=None,
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                    AccountModel(
                        id=exchange_id,
                        name="Synthetic exchange",
                        type=AccountType.exchange,
                        currency="EUR",
                        color=None,
                        notes=None,
                        is_archived=False,
                        archived_at=None,
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                    AssetModel(
                        id=listed_asset_id,
                        symbol=listed_symbol,
                        isin=None,
                        name="Synthetic listed security",
                        asset_type=AssetType.stock,
                        currency="USD",
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                    AssetModel(
                        id=crypto_asset_id,
                        symbol=crypto_symbol,
                        isin=None,
                        name="Synthetic crypto asset",
                        asset_type=AssetType.crypto,
                        currency="EUR",
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                )
            )
            await session.flush()
            session.add_all(
                (
                    AccountMemberModel(
                        id=f"{prefix}-member-broker",
                        account_id=broker_id,
                        user_id=user_id,
                        role=AccountMemberRole.owner,
                        relation_type=AccountRelationType.owner,
                        invited_by_id=None,
                        accepted_at=CREATED_AT,
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                    AccountMemberModel(
                        id=f"{prefix}-member-exchange",
                        account_id=exchange_id,
                        user_id=user_id,
                        role=AccountMemberRole.owner,
                        relation_type=AccountRelationType.owner,
                        invited_by_id=None,
                        accepted_at=CREATED_AT,
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                    AssetListingModel(
                        id=listed_listing_id,
                        asset_id=listed_asset_id,
                        symbol=listed_symbol,
                        exchange=f"broker-{prefix}",
                        mic="XLON",
                        currency="USD",
                        country="US",
                        provider=PriceSource.broker,
                        provider_symbol=f"BROKER_{listed_symbol}_DIFFERENT",
                        is_primary=True,
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                    AssetListingModel(
                        id=crypto_listing_id,
                        asset_id=crypto_asset_id,
                        symbol=crypto_symbol,
                        exchange=f"exchange-{prefix}",
                        mic=None,
                        currency="EUR",
                        country=None,
                        provider=PriceSource.exchange,
                        provider_symbol=f"EXCHANGE_{crypto_symbol}_DIFFERENT",
                        is_primary=True,
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                )
            )
            for index, alias in enumerate(listed_aliases, start=1):
                session.add(
                    AssetAliasModel(
                        id=f"{prefix}-listed-alias-{index}",
                        asset_id=listed_asset_id,
                        provider=AssetAliasProvider.twelve_data,
                        external_id=alias,
                        created_at=CREATED_AT,
                    )
                )
            for index, alias in enumerate(crypto_aliases, start=1):
                session.add(
                    AssetAliasModel(
                        id=f"{prefix}-crypto-alias-{index}",
                        asset_id=crypto_asset_id,
                        provider=AssetAliasProvider.coingecko,
                        external_id=alias,
                        created_at=CREATED_AT,
                    )
                )
            await session.flush()
            session.add_all(
                (
                    HoldingModel(
                        id=f"{prefix}-holding-listed",
                        symbol=listed_symbol,
                        name="Synthetic listed holding",
                        asset_type=AssetType.stock,
                        quantity=Decimal("2"),
                        avg_buy_price=Decimal("200"),
                        currency="USD",
                        current_price=None,
                        current_value=None,
                        unrealized_pnl=None,
                        realized_pnl=None,
                        asset_id=listed_asset_id,
                        listing_id=listed_listing_id,
                        account_id=broker_id,
                        calculated_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                    HoldingModel(
                        id=f"{prefix}-holding-crypto",
                        symbol=crypto_symbol,
                        name="Synthetic crypto holding",
                        asset_type=AssetType.crypto,
                        quantity=Decimal("1"),
                        avg_buy_price=Decimal("400"),
                        currency="EUR",
                        current_price=None,
                        current_value=None,
                        unrealized_pnl=None,
                        realized_pnl=None,
                        asset_id=crypto_asset_id,
                        listing_id=crypto_listing_id,
                        account_id=exchange_id,
                        calculated_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    ),
                )
            )
            for account_id, currency in ((broker_id, "USD"), (exchange_id, "EUR")):
                event_id = f"{prefix}-event-{currency.lower()}"
                session.add(
                    InvestmentEventModel(
                        id=event_id,
                        account_id=account_id,
                        type=InvestmentEventType.cash_deposit,
                        date=EVENT_AT,
                        source=None,
                        external_id=f"{prefix}-deposit-{currency.lower()}",
                        order_id=None,
                        description=f"Synthetic {currency} deposit",
                        realized_pnl=None,
                        realized_pnl_currency=None,
                        import_batch_id=None,
                        archived_at=None,
                        deleted_at=None,
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    )
                )
                await session.flush()
                session.add(
                    InvestmentMovementModel(
                        id=f"{prefix}-movement-{currency.lower()}",
                        event_id=event_id,
                        account_id=account_id,
                        asset_id=None,
                        listing_id=None,
                        kind=InvestmentMovementKind.cash,
                        direction=MovementDirection.incoming,
                        quantity=Decimal("1000"),
                        currency=currency,
                        price_per_unit=None,
                        value_amount=Decimal("1000"),
                        value_currency=currency,
                        source_symbol=None,
                        source_asset_type=None,
                        note=None,
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    )
                )
            await session.commit()
    finally:
        await engine.dispose()
    return (
        user_id,
        (broker_id, exchange_id),
        (listed_asset_id, crypto_asset_id),
        (listed_listing_id, crypto_listing_id),
    )


def _transports(
    session: AsyncSession,
    *,
    listed_symbol: str,
    crypto_alias: str,
    twelve_status: int = 200,
    coingecko_stale: bool = False,
    cnb_status: int = 200,
) -> tuple[
    httpx.MockTransport,
    httpx.MockTransport,
    httpx.MockTransport,
    list[tuple[str, str]],
]:
    calls: list[tuple[str, str]] = []
    twelve_epoch = int(TWELVE_OBSERVED_AT.replace(tzinfo=UTC).timestamp())
    coin_observed = datetime(2026, 8, 1) if coingecko_stale else COINGECKO_OBSERVED_AT
    coin_epoch = int(coin_observed.replace(tzinfo=UTC).timestamp())

    def twelve_handler(request: httpx.Request) -> httpx.Response:
        assert not session.in_transaction()
        calls.append(("twelve_data", request.url.params["symbol"]))
        return httpx.Response(
            twelve_status,
            headers={"content-type": "application/json"},
            content=(
                f'{{"symbol":"{listed_symbol}","mic_code":"XNAS",'
                f'"currency":"USD","datetime":"2026-08-05 12:34:00",'
                f'"timestamp":{twelve_epoch},"last_quote_at":{twelve_epoch},'
                f'"close":"225.3200000000"}}'
            ).encode(),
        )

    def coingecko_handler(request: httpx.Request) -> httpx.Response:
        assert not session.in_transaction()
        calls.append(("coingecko", request.url.params["ids"]))
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=(
                f'{{"{crypto_alias}":{{"eur":414.5888,"last_updated_at":{coin_epoch}}}}}'
            ).encode(),
        )

    def cnb_handler(request: httpx.Request) -> httpx.Response:
        assert not session.in_transaction()
        requested = request.url.params["date"]
        calls.append(("cnb", requested))
        if cnb_status != 200:
            return httpx.Response(
                cnb_status,
                headers={"content-type": "text/xml"},
                content=b"unavailable",
            )
        publication = datetime.strptime(requested, "%d.%m.%Y").date()
        is_event = publication == EVENT_AT.date()
        return httpx.Response(
            200,
            headers={"content-type": "text/xml"},
            content=cnb_xml(
                publication,
                (
                    ("EUR", "1", "24,000" if is_event else "25,000"),
                    ("USD", "1", "22,000" if is_event else "23,000"),
                ),
            ),
        )

    return (
        httpx.MockTransport(twelve_handler),
        httpx.MockTransport(coingecko_handler),
        httpx.MockTransport(cnb_handler),
        calls,
    )


def _service(
    session: AsyncSession,
    *,
    listed_symbol: str,
    crypto_alias: str,
    twelve_status: int = 200,
    coingecko_stale: bool = False,
    cnb_status: int = 200,
    snapshot_executor: object | None = None,
) -> tuple[MarketBackedSnapshotRefreshService, list[tuple[str, str]]]:
    twelve, coingecko, cnb, calls = _transports(
        session,
        listed_symbol=listed_symbol,
        crypto_alias=crypto_alias,
        twelve_status=twelve_status,
        coingecko_stale=coingecko_stale,
        cnb_status=cnb_status,
    )

    def factory(active_session: AsyncSession, settings: Settings):
        return create_production_market_evidence_service(
            active_session,
            settings,
            http_transport=cnb,
            coingecko_http_transport=coingecko,
            twelve_data_http_transport=twelve,
        )

    return (
        MarketBackedSnapshotRefreshService(
            session,
            Settings(
                environment="test",
                twelve_data_api_key=TWELVE_API_KEY,
                _env_file=None,
            ),
            market_service_factory=factory,
            snapshot_executor=snapshot_executor,  # type: ignore[arg-type]
        ),
        calls,
    )


async def _counts(
    session: AsyncSession,
    *,
    user_id: str,
    account_ids: tuple[str, str],
    listing_ids: tuple[str, str],
) -> tuple[int, int, int, int]:
    prices = await session.scalar(
        select(func.count())
        .select_from(PriceSnapshotModel)
        .where(PriceSnapshotModel.listing_id.in_(listing_ids))
    )
    rates = await session.scalar(select(func.count()).select_from(ExchangeRateModel))
    snapshots = await session.scalar(
        select(func.count())
        .select_from(AccountSnapshotModel)
        .where(AccountSnapshotModel.account_id.in_(account_ids))
    )
    net_worth = await session.scalar(
        select(func.count())
        .select_from(NetWorthSnapshotModel)
        .where(NetWorthSnapshotModel.user_id == user_id)
    )
    return int(prices or 0), int(rates or 0), int(snapshots or 0), int(net_worth or 0)


@pytest.mark.asyncio
async def test_mixed_production_market_backed_refresh_e2e_and_replay() -> None:
    prefix = f"r5b3a-mixed-{uuid4()}"
    listed_symbol = "AAPL"
    listed_alias = '{"symbol":"AAPL","mic_code":"XNAS"}'
    crypto_symbol = "BTC"
    crypto_alias = "bitcoin"
    user_id, account_ids, asset_ids, listing_ids = await _seed_mixed_user(
        prefix,
        listed_aliases=(listed_alias,),
        crypto_aliases=(crypto_alias,),
        listed_symbol=listed_symbol,
        crypto_symbol=crypto_symbol,
    )
    engine = _engine()
    insert_order: list[str] = []

    def record_insert(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        for table_name in (
            '"PriceSnapshot"',
            '"ExchangeRate"',
            '"AccountSnapshot"',
            '"NetWorthSnapshot"',
        ):
            if (
                statement.lstrip().startswith(f"INSERT INTO {table_name}")
                or f"INSERT INTO public.{table_name}" in statement
            ):
                insert_order.append(table_name)

    event.listen(engine.sync_engine, "after_cursor_execute", record_insert)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            service, provider_calls = _service(
                session,
                listed_symbol=listed_symbol,
                crypto_alias=crypto_alias,
            )
            combined = await service.execute(_command(user_id))
            assert not session.in_transaction()
            assert provider_calls == [
                ("twelve_data", "AAPL"),
                ("coingecko", "bitcoin"),
                ("cnb", "01.08.2026"),
                ("cnb", "06.08.2026"),
                ("cnb", "01.08.2026"),
                ("cnb", "06.08.2026"),
            ]
            assert insert_order.index('"PriceSnapshot"') < insert_order.index('"AccountSnapshot"')
            assert insert_order.index('"ExchangeRate"') < insert_order.index('"AccountSnapshot"')

            market = combined.market
            snapshots = combined.snapshots
            expected_prices = tuple(
                sorted(
                    (
                        price_snapshot_id(
                            PriceObservation(
                                asset_id=asset_ids[0],
                                listing_id=listing_ids[0],
                                provider=PriceSource.twelve_data,
                                provider_symbol=listed_alias,
                                price=Decimal("225.3200000000"),
                                currency="USD",
                                observed_at=TWELVE_OBSERVED_AT,
                            )
                        ),
                        price_snapshot_id(
                            PriceObservation(
                                asset_id=asset_ids[1],
                                listing_id=listing_ids[1],
                                provider=PriceSource.coingecko,
                                provider_symbol=crypto_alias,
                                price=Decimal("414.5888000000"),
                                currency="EUR",
                                observed_at=COINGECKO_OBSERVED_AT,
                            )
                        ),
                    )
                )
            )
            expected_rates = tuple(
                sorted(
                    exchange_rate_id(
                        ExchangeRateObservation(
                            from_currency=currency,
                            to_currency="CZK",
                            provider=ExchangeRateSource.cnb,
                            rate=rate,
                            effective_at=through,
                        )
                    )
                    for currency, rate, through in (
                        ("EUR", Decimal("24.00000000"), EVENT_AT.replace(hour=0)),
                        ("EUR", Decimal("25.00000000"), SNAPSHOT_AT),
                        ("USD", Decimal("22.00000000"), EVENT_AT.replace(hour=0)),
                        ("USD", Decimal("23.00000000"), SNAPSHOT_AT),
                    )
                )
            )
            assert market.price_ids == expected_prices
            assert market.exchange_rate_ids == expected_rates
            assert market.required_price_count == 2
            assert market.required_fx_count == 4
            assert snapshots.selected_account_snapshot_count == 2
            assert snapshots.created_account_snapshot_count == 2

            selected_prices: list[str] = []
            selected_snapshot_rates: list[str] = []
            selected_historical_rates: list[str] = []
            for identity in snapshots.required_account_snapshot_identities:
                async with session.begin():
                    await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                    evidence = await AccountSnapshotEvidenceService(session).build(
                        BuildAccountSnapshotEvidenceCommand(
                            account_id=identity.account_id,
                            snapshot_timestamp=SNAPSHOT_AT,
                            granularity=SnapshotGranularity.day,
                            source=SnapshotSource.price_refresh,
                            calculation_version=1,
                            output_currency="CZK",
                        )
                    )
                selected_prices.extend(evidence.selected_price_ids)
                selected_snapshot_rates.extend(evidence.selected_snapshot_exchange_rate_ids)
                selected_historical_rates.extend(evidence.selected_historical_exchange_rate_ids)
            assert tuple(sorted(selected_prices)) == expected_prices
            assert tuple(sorted(selected_snapshot_rates)) == tuple(
                sorted(
                    rate_id
                    for rate_id in expected_rates
                    if rate_id
                    in {
                        exchange_rate_id(
                            ExchangeRateObservation(
                                currency,
                                "CZK",
                                ExchangeRateSource.cnb,
                                rate,
                                SNAPSHOT_AT,
                            )
                        )
                        for currency, rate in (
                            ("EUR", Decimal("25.00000000")),
                            ("USD", Decimal("23.00000000")),
                        )
                    }
                )
            )
            assert tuple(sorted(selected_historical_rates)) == tuple(
                sorted(set(expected_rates) - set(selected_snapshot_rates))
            )

            read_command = ReadAuthorizedMultiAccountPortfolioSnapshotCommand(
                principal=_principal(user_id),
                timestamp=SNAPSHOT_AT,
                granularity=PortfolioSnapshotGranularity.day,
                currency="CZK",
                calculation_version=1,
                accounts=tuple(
                    ExactAccountSnapshotSelection(
                        account_id=identity.account_id,
                        required_snapshot_id=identity.snapshot_id,
                    )
                    for identity in snapshots.required_account_snapshot_identities
                ),
            )
            portfolio = (
                await AuthorizedMultiAccountPortfolioSnapshotService(session).read(read_command)
            ).portfolio
            dashboard = (
                await AuthorizedDashboardSnapshotService(
                    AuthorizedMultiAccountPortfolioSnapshotService(session)
                ).read(read_command)
            ).dashboard
            assert portfolio.summary.account_count == dashboard.summary.account_count == 2
            assert portfolio.summary.position_count == dashboard.summary.position_count == 2
            assert (
                portfolio.summary.cash_value
                == dashboard.summary.cash_value
                == Decimal("48000.000000")
            )
            assert (
                portfolio.summary.investment_value
                == dashboard.summary.investment_value
                == Decimal("20729.440000")
            )
            assert (
                portfolio.summary.investment_cost_basis
                == dashboard.summary.investment_cost_basis
                == Decimal("19200.000000")
            )
            assert (
                portfolio.summary.net_deposits_value
                == dashboard.summary.net_deposits_value
                == Decimal("46000.000000")
            )
            assert (
                portfolio.summary.total_value
                == dashboard.summary.total_value
                == Decimal("68729.440000")
            )

        async with AsyncSession(engine) as session:
            counts_before = await _counts(
                session,
                user_id=user_id,
                account_ids=account_ids,
                listing_ids=listing_ids,
            )
            assert counts_before[0] == 2
            assert counts_before[2:] == (2, 1)
            await session.rollback()
            replay_service, _ = _service(
                session,
                listed_symbol=listed_symbol,
                crypto_alias=crypto_alias,
            )
            replay = await replay_service.execute(_command(user_id))
            assert replay.market.prices_created == 0
            assert replay.market.prices_replayed == 2
            assert replay.market.rates_created == 0
            assert replay.market.rates_replayed == 4
            assert replay.snapshots.created_account_snapshot_count == 0
            assert replay.snapshots.replayed_account_snapshot_count == 2

        async with AsyncSession(engine) as session:
            counts_after = await _counts(
                session,
                user_id=user_id,
                account_ids=account_ids,
                listing_ids=listing_ids,
            )
            assert counts_after == counts_before
    finally:
        event.remove(engine.sync_engine, "after_cursor_execute", record_insert)
        await engine.dispose()


@pytest.mark.parametrize(
    ("failure", "expected_calls"),
    [
        ("twelve-429", 1),
        ("coingecko-stale", 2),
        ("cnb-failure", 3),
    ],
)
@pytest.mark.asyncio
async def test_provider_failure_matrix_writes_no_market_batch_or_snapshot_graph(
    failure: str,
    expected_calls: int,
) -> None:
    unique = uuid4().hex[:10]
    prefix = f"r5b3a-{failure}-{uuid4()}"
    listed_symbol = f"T{unique.upper()}"
    listed_alias = f'{{"symbol":"{listed_symbol}","mic_code":"XNAS"}}'
    crypto_alias = f"coin-{unique}"
    user_id, account_ids, _, listing_ids = await _seed_mixed_user(
        prefix,
        listed_aliases=(listed_alias,),
        crypto_aliases=(crypto_alias,),
        listed_symbol=listed_symbol,
        crypto_symbol=f"C{unique.upper()}",
    )
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            rates_before = await session.scalar(select(func.count()).select_from(ExchangeRateModel))
            await session.rollback()
            service, provider_calls = _service(
                session,
                listed_symbol=listed_symbol,
                crypto_alias=crypto_alias,
                twelve_status=429 if failure == "twelve-429" else 200,
                coingecko_stale=failure == "coingecko-stale",
                cnb_status=503 if failure == "cnb-failure" else 200,
            )
            with pytest.raises(MarketBackedSnapshotRefreshUnavailableError):
                await service.execute(_command(user_id))
            assert len(provider_calls) == expected_calls
            assert not session.in_transaction()
        async with AsyncSession(engine) as session:
            counts = await _counts(
                session,
                user_id=user_id,
                account_ids=account_ids,
                listing_ids=listing_ids,
            )
            assert counts == (0, int(rates_before or 0), 0, 0)
    finally:
        await engine.dispose()


@pytest.mark.parametrize("alias_failure", ["missing", "ambiguous"])
@pytest.mark.asyncio
async def test_missing_or_ambiguous_alias_fails_before_all_http(
    alias_failure: str,
) -> None:
    unique = uuid4().hex[:10]
    prefix = f"r5b3a-alias-{alias_failure}-{uuid4()}"
    listed_symbol = f"T{unique.upper()}"
    aliases = (
        ()
        if alias_failure == "missing"
        else (
            f'{{"symbol":"{listed_symbol}","mic_code":"XNAS"}}',
            f'{{"symbol":"ALT{unique.upper()}","mic_code":"XNAS"}}',
        )
    )
    crypto_alias = f"coin-{unique}"
    user_id, account_ids, _, listing_ids = await _seed_mixed_user(
        prefix,
        listed_aliases=aliases,
        crypto_aliases=(crypto_alias,),
        listed_symbol=listed_symbol,
        crypto_symbol=f"C{unique.upper()}",
    )
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            rates_before = await session.scalar(select(func.count()).select_from(ExchangeRateModel))
            await session.rollback()
            service, provider_calls = _service(
                session,
                listed_symbol=listed_symbol,
                crypto_alias=crypto_alias,
            )
            with pytest.raises(MarketBackedSnapshotRefreshUnavailableError):
                await service.execute(_command(user_id))
            assert provider_calls == []
        async with AsyncSession(engine) as session:
            assert await _counts(
                session,
                user_id=user_id,
                account_ids=account_ids,
                listing_ids=listing_ids,
            ) == (0, int(rates_before or 0), 0, 0)
    finally:
        await engine.dispose()


class _FailingSnapshotExecutor:
    async def execute(self, command: object) -> object:
        raise SnapshotRefreshExecutionStateError()


@pytest.mark.asyncio
async def test_snapshot_failure_after_market_writer_preserves_market_evidence() -> None:
    unique = uuid4().hex[:10]
    prefix = f"r5b3a-snapshot-failure-{uuid4()}"
    listed_symbol = f"T{unique.upper()}"
    listed_alias = f'{{"symbol":"{listed_symbol}","mic_code":"XNAS"}}'
    crypto_alias = f"coin-{unique}"
    user_id, account_ids, _, listing_ids = await _seed_mixed_user(
        prefix,
        listed_aliases=(listed_alias,),
        crypto_aliases=(crypto_alias,),
        listed_symbol=listed_symbol,
        crypto_symbol=f"C{unique.upper()}",
    )
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            rates_before = await session.scalar(select(func.count()).select_from(ExchangeRateModel))
            await session.rollback()
            service, provider_calls = _service(
                session,
                listed_symbol=listed_symbol,
                crypto_alias=crypto_alias,
                snapshot_executor=_FailingSnapshotExecutor(),
            )
            with pytest.raises(MarketBackedSnapshotRefreshUnavailableError):
                await service.execute(_command(user_id))
            assert len(provider_calls) == 6
            assert not session.in_transaction()
        async with AsyncSession(engine) as session:
            prices, rates, snapshots, net_worth = await _counts(
                session,
                user_id=user_id,
                account_ids=account_ids,
                listing_ids=listing_ids,
            )
            assert prices == 2
            assert int(rates_before or 0) <= rates <= int(rates_before or 0) + 4
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ExchangeRateModel)
                    .where(
                        ExchangeRateModel.source == ExchangeRateSource.cnb,
                        ExchangeRateModel.from_currency.in_(("EUR", "USD")),
                        ExchangeRateModel.to_currency == "CZK",
                        ExchangeRateModel.date.in_((EVENT_AT.replace(hour=0), SNAPSHOT_AT)),
                    )
                )
                == 4
            )
            assert snapshots == net_worth == 0
    finally:
        await engine.dispose()
