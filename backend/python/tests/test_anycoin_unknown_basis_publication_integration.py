from __future__ import annotations

import csv
import importlib
import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any, cast
from uuid import uuid4

import asyncpg
import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.canonical_lineage import AccountCanonicalChangeModel
from app.db.models.common import QUANTITY
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetAliasProvider,
    AssetType,
    ExchangeRateSource,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import (
    InvestmentEventModel,
    InvestmentMovementModel,
    InvestmentMovementValuationEvidenceModel,
)
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.canonical_state import CanonicalChangeKind, CanonicalStateService
from app.modules.current_value.service import (
    CurrentValueService,
    ReadCurrentPortfolioCommand,
)
from app.modules.dashboard_snapshot.authorized_service import (
    AuthorizedDashboardSnapshotService,
)
from app.modules.holdings.rebuild_service import HoldingRebuildService
from app.modules.imports.anycoin_btc_alias import (
    AnycoinBtcAliasService,
    OnboardAnycoinBtcAliasCommand,
)
from app.modules.investments.transfer_valuation import transfer_valuation_fingerprint
from app.modules.market_data.factory import create_production_market_evidence_service
from app.modules.market_data.models import MarketEvidenceRefreshResult
from app.modules.market_data.service import RefreshMarketEvidenceCommand
from app.modules.market_data.source_policy import (
    LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
)
from app.modules.portfolio_snapshot.models import (
    SnapshotGranularity as PortfolioSnapshotGranularity,
)
from app.modules.portfolio_snapshot.multi_account_service import (
    AuthorizedMultiAccountPortfolioSnapshotService,
    ExactAccountSnapshotSelection,
    ReadAuthorizedMultiAccountPortfolioSnapshotCommand,
)
from app.modules.prices.providers.yahoo_finance_models import YahooFinanceHttpResponse
from app.modules.snapshot_refresh.executor import (
    ExecuteUserSnapshotRefreshCommand,
    UserSnapshotRefreshExecutor,
)
from app.shared.canonical_arithmetic import canonical_rounded

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required"),
]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
CURRENT_SCHEMA = BACKEND_ROOT / "database" / "revisions" / "440001assetaudit" / "schema.sql"
REAL_ANYCOIN_FIXTURE = (
    Path(__file__).parents[3] / "test_imports" / "AnyCoin" / "transactions (2).csv"
)
SNAPSHOT_AT = datetime(2026, 8, 19, 12, 0)


def _posting_support() -> ModuleType:
    return importlib.import_module("tests.test_import_posting_integration")


def _yahoo_body(
    *,
    symbol: str,
    currency: str,
    price_hint: int,
    points: tuple[tuple[datetime, str], ...],
) -> bytes:
    timestamps = [int(at.replace(tzinfo=UTC).timestamp()) for at, _ in points]
    rows = "[" + ",".join(value for _, value in points) + "]"
    document = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": symbol,
                        "currency": currency,
                        "priceHint": price_hint,
                        "dataGranularity": "1m",
                    },
                    "timestamp": timestamps,
                    "indicators": {
                        "quote": [{"close": "__ROWS__"}],
                        "adjclose": [{"adjclose": "__ROWS__"}],
                    },
                }
            ],
            "error": None,
        }
    }
    return json.dumps(document, separators=(",", ":")).replace('"__ROWS__"', rows).encode()


class _YahooTransport:
    def __init__(self, event_at: datetime) -> None:
        self.calls: list[tuple[str, datetime, datetime, str]] = []
        self.bodies = {
            "AAA": _yahoo_body(
                symbol="AAA",
                currency="EUR",
                price_hint=2,
                points=((SNAPSHOT_AT, "60.00"),),
            ),
            "BTC-USD": _yahoo_body(
                symbol="BTC-USD",
                currency="USD",
                price_hint=2,
                points=((SNAPSHOT_AT, "56794.4576072386"),),
            ),
            "EURCZK=X": _yahoo_body(
                symbol="EURCZK=X",
                currency="CZK",
                price_hint=8,
                points=((event_at, "25.00000000"), (SNAPSHOT_AT, "25.00000000")),
            ),
            "CZK=X": _yahoo_body(
                symbol="CZK=X",
                currency="CZK",
                price_hint=8,
                points=((SNAPSHOT_AT, "25.00000000"),),
            ),
        }

    async def fetch_chart(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> YahooFinanceHttpResponse:
        self.calls.append((symbol, start, end, interval))
        return YahooFinanceHttpResponse(200, "application/json", self.bodies[symbol])


class _ReplayMarketService:
    def __init__(
        self,
        *,
        user_id: str,
        price_ids: tuple[str, ...],
        rate_ids: tuple[str, ...],
        required_price_count: int,
        required_fx_count: int,
    ) -> None:
        self.user_id = user_id
        self.price_ids = price_ids[:required_price_count]
        self.rate_ids = rate_ids[-required_fx_count:] if required_fx_count else ()
        self.required_price_count = required_price_count
        self.required_fx_count = required_fx_count

    async def refresh(
        self,
        command: RefreshMarketEvidenceCommand,
    ) -> MarketEvidenceRefreshResult:
        return MarketEvidenceRefreshResult(
            user_id=self.user_id,
            snapshot_timestamp=command.snapshot_timestamp,
            output_currency="CZK",
            required_price_count=self.required_price_count,
            required_fx_count=self.required_fx_count,
            price_ids=self.price_ids,
            exchange_rate_ids=self.rate_ids,
            prices_created=0,
            prices_replayed=len(self.price_ids),
            rates_created=0,
            rates_replayed=len(self.rate_ids),
        )


async def _seed_known_trading_account(
    session: AsyncSession,
    *,
    prefix: str,
    user_id: str,
) -> tuple[str, datetime]:
    account_id = f"{prefix}-trading-account"
    asset_id = f"{prefix}-trading-asset"
    listing_id = f"{prefix}-trading-listing"
    event_id = f"{prefix}-trading-event"
    event_at = SNAPSHOT_AT - timedelta(days=1)
    async with session.begin():
        session.add_all(
            [
                AccountModel(
                    id=account_id,
                    name="Trading known basis",
                    type=AccountType.broker,
                    currency="EUR",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=event_at,
                    updated_at=event_at,
                ),
                AssetModel(
                    id=asset_id,
                    symbol="AAA",
                    isin=None,
                    name="Known asset",
                    asset_type=AssetType.stock,
                    currency="EUR",
                    created_at=event_at,
                    updated_at=event_at,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                AccountMemberModel(
                    id=f"{prefix}-trading-member",
                    account_id=account_id,
                    user_id=user_id,
                    role=AccountMemberRole.owner,
                    relation_type=AccountRelationType.owner,
                    invited_by_id=None,
                    accepted_at=event_at,
                    created_at=event_at,
                    updated_at=event_at,
                ),
                AssetListingModel(
                    id=listing_id,
                    asset_id=asset_id,
                    symbol="AAA",
                    exchange="TEST",
                    mic="XPAR",
                    currency="EUR",
                    country=None,
                    provider=PriceSource.yahoo_finance,
                    provider_symbol="AAA",
                    is_primary=True,
                    created_at=event_at,
                    updated_at=event_at,
                ),
                InvestmentEventModel(
                    id=event_id,
                    account_id=account_id,
                    type=InvestmentEventType.trade,
                    date=event_at,
                    source=ImportSource.trading212,
                    external_id=event_id,
                    order_id=None,
                    description="Known-basis fixture trade",
                    realized_pnl=None,
                    realized_pnl_currency=None,
                    import_batch_id=None,
                    archived_at=None,
                    deleted_at=None,
                    created_at=event_at,
                    updated_at=event_at,
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                InvestmentMovementModel(
                    id=f"{event_id}-asset",
                    event_id=event_id,
                    account_id=account_id,
                    asset_id=asset_id,
                    listing_id=listing_id,
                    kind=InvestmentMovementKind.asset,
                    direction=MovementDirection.incoming,
                    quantity=Decimal("2.0000000000"),
                    currency="AAA",
                    price_per_unit=Decimal("50.0000000000"),
                    value_amount=Decimal("100.0000000000"),
                    value_currency="EUR",
                    source_symbol="AAA",
                    source_asset_type=AssetType.stock,
                    note=None,
                    created_at=event_at,
                    updated_at=event_at,
                ),
                InvestmentMovementModel(
                    id=f"{event_id}-cash",
                    event_id=event_id,
                    account_id=account_id,
                    asset_id=None,
                    listing_id=None,
                    kind=InvestmentMovementKind.cash,
                    direction=MovementDirection.outgoing,
                    quantity=Decimal("100.0000000000"),
                    currency="EUR",
                    price_per_unit=None,
                    value_amount=Decimal("100.0000000000"),
                    value_currency="EUR",
                    source_symbol=None,
                    source_asset_type=None,
                    note=None,
                    created_at=event_at,
                    updated_at=event_at,
                ),
            ]
        )
        await session.flush()
        await CanonicalStateService(session).record(
            account_id=account_id,
            kind=CanonicalChangeKind.investment_event,
            entity_id=event_id,
            financial_timestamp=event_at,
            created_at=event_at,
            replay=False,
        )
    async with session.begin():
        rebuilt = await HoldingRebuildService(session).rebuild(
            account_id=account_id,
            rebuilt_at=SNAPSHOT_AT,
        )
        assert rebuilt.total == 1
    return account_id, event_at


async def _seed_anycoin_transfer_valuation_evidence(
    session: AsyncSession,
    *,
    prefix: str,
    account_id: str,
    created_at: datetime,
) -> None:
    rows = (
        await session.execute(
            select(InvestmentEventModel, InvestmentMovementModel)
            .join(
                InvestmentMovementModel,
                InvestmentMovementModel.event_id == InvestmentEventModel.id,
            )
            .where(
                InvestmentEventModel.account_id == account_id,
                InvestmentEventModel.source == ImportSource.anycoin,
                InvestmentEventModel.type == InvestmentEventType.asset_transfer,
                InvestmentEventModel.archived_at.is_(None),
                InvestmentEventModel.deleted_at.is_(None),
                InvestmentMovementModel.kind == InvestmentMovementKind.asset,
                InvestmentMovementModel.currency == "BTC",
                InvestmentMovementModel.source_symbol == "BTC",
                InvestmentMovementModel.source_asset_type == AssetType.crypto,
                InvestmentMovementModel.price_per_unit.is_(None),
                InvestmentMovementModel.value_amount.is_(None),
                InvestmentMovementModel.value_currency.is_(None),
            )
        )
    ).all()
    if not rows:
        return

    event_ids = tuple(event.id for event, _movement in rows)
    changes = {
        row.entity_id: row
        for row in (
            await session.scalars(
                select(AccountCanonicalChangeModel).where(
                    AccountCanonicalChangeModel.account_id == account_id,
                    AccountCanonicalChangeModel.kind == "investment_event",
                    AccountCanonicalChangeModel.entity_id.in_(event_ids),
                )
            )
        ).all()
    }
    timestamp_ids: dict[datetime, tuple[str, str]] = {}
    for event, movement in rows:
        if event.id not in changes or movement.asset_id is None or movement.listing_id is None:
            raise AssertionError("Anycoin transfer fixture is missing canonical identity.")
        timestamp_ids.setdefault(
            event.date,
            (
                f"{prefix}-transfer-price-{len(timestamp_ids) + 1}",
                f"{prefix}-transfer-rate-{len(timestamp_ids) + 1}",
            ),
        )

    first_movement = rows[0][1]
    assert first_movement.asset_id is not None and first_movement.listing_id is not None
    yahoo_reference_listing_id = f"{first_movement.asset_id}-yahoo-btc-usd"
    session.add(
        AssetListingModel(
            id=yahoo_reference_listing_id,
            asset_id=first_movement.asset_id,
            symbol="BTC-USD",
            exchange="yahoo_crypto",
            mic=None,
            currency="USD",
            country=None,
            provider=PriceSource.yahoo_finance,
            provider_symbol="BTC-USD",
            is_primary=False,
            created_at=created_at,
            updated_at=created_at,
            base_priority=0,
        )
    )
    await session.flush()
    for timestamp, (price_id, rate_id) in timestamp_ids.items():
        session.add_all(
            [
                PriceSnapshotModel(
                    id=price_id,
                    asset_id=first_movement.asset_id,
                    listing_id=yahoo_reference_listing_id,
                    price=Decimal("10000.0000000000"),
                    currency="USD",
                    source=PriceSource.yahoo_finance,
                    provider_symbol="BTC-USD",
                    timestamp=timestamp,
                    created_at=created_at,
                ),
                ExchangeRateModel(
                    id=rate_id,
                    from_currency="USD",
                    to_currency="CZK",
                    rate=Decimal("25.00000000"),
                    date=timestamp,
                    source=ExchangeRateSource.yahoo_finance,
                    created_at=created_at,
                ),
            ]
        )
    await session.flush()

    for event, movement in rows:
        change = changes.get(event.id)
        assert change is not None
        assert movement.asset_id is not None and movement.listing_id is not None
        price_id, rate_id = timestamp_ids[event.date]
        price_per_unit = canonical_rounded(
            Decimal("10000.0000000000") * Decimal("25.00000000"),
            QUANTITY,
        )
        value_amount = canonical_rounded(movement.quantity * price_per_unit, QUANTITY)
        fingerprint = transfer_valuation_fingerprint(
            movement=movement,
            effective_at=event.date,
            canonical_revision=change.revision,
            price_snapshot_id=price_id,
            exchange_rate_id=rate_id,
            calculation_version=1,
            selection_interval="30min",
        )
        session.add(
            InvestmentMovementValuationEvidenceModel(
                id=f"{prefix}-transfer-evidence-{movement.id}",
                account_id=account_id,
                movement_id=movement.id,
                revision=1,
                canonical_revision=change.revision,
                effective_at=event.date,
                calculation_version=1,
                selection_interval="30min",
                input_fingerprint=fingerprint,
                price_snapshot_id=price_id,
                exchange_rate_id=rate_id,
                price_amount=Decimal("10000.0000000000"),
                price_currency="USD",
                price_source=PriceSource.yahoo_finance,
                price_timestamp=event.date,
                fx_rate=Decimal("25.00000000"),
                fx_from_currency="USD",
                fx_to_currency="CZK",
                fx_source=ExchangeRateSource.yahoo_finance,
                fx_timestamp=event.date,
                price_per_unit=price_per_unit,
                value_amount=value_amount,
                value_currency="CZK",
                created_at=created_at,
            )
        )
    await session.flush()


@pytest.mark.skipif(not REAL_ANYCOIN_FIXTURE.exists(), reason="Local Anycoin fixture is absent")
@pytest.mark.asyncio
async def test_actual_anycoin_transfer_evidence_publishes_quantity_value_and_cost_metrics() -> None:
    assert DATABASE_URL is not None
    support = _posting_support()
    mutable_support = cast(Any, support)
    original_support_url = mutable_support.DATABASE_URL
    source_url = make_url(normalize_database_url(DATABASE_URL))
    database_name = f"finance_app_anycoin_unknown_{uuid4().hex}"
    admin_url = source_url.set(drivername="postgresql", database="postgres")
    target_url = source_url.set(database=database_name)
    admin_dsn = admin_url.render_as_string(hide_password=False)
    target_dsn = target_url.set(drivername="postgresql").render_as_string(hide_password=False)
    target_database_url = target_url.render_as_string(hide_password=False)
    prefix = f"anycoin-unknown-{uuid4().hex}"
    user_id = f"{prefix}-owner"
    account_id = f"{prefix}-account"
    admin = await asyncpg.connect(admin_dsn)
    try:
        await admin.execute(f'CREATE DATABASE "{database_name}"')
        target = await asyncpg.connect(target_dsn)
        try:
            await target.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
            current_schema = CURRENT_SCHEMA.read_text(encoding="utf-8").replace(
                'CREATE SCHEMA "public";\n', "", 1
            )
            await target.execute(current_schema)
            await target.execute(
                "CREATE TABLE public.alembic_version ("
                "version_num varchar(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
            await target.execute(
                "INSERT INTO public.alembic_version (version_num) VALUES ('440001assetaudit')"
            )
        finally:
            await target.close()

        mutable_support.DATABASE_URL = target_database_url
        with REAL_ANYCOIN_FIXTURE.open(encoding="utf-8-sig", newline="") as handle:
            raw_rows = list(csv.DictReader(handle))
        await support._seed(
            prefix,
            source=ImportSource.anycoin,
            rows=raw_rows,
            account_currency="CZK",
        )
        engine = create_async_engine(normalize_database_url(target_database_url))
        try:
            async with AsyncSession(engine) as session:
                user = await session.get(UserModel, user_id)
                anycoin_account = await session.get(AccountModel, account_id)
                assert user is not None and anycoin_account is not None
                user.base_currency = "CZK"
                anycoin_account.name = "Anycoin event-date valuation"
                anycoin_account.type = AccountType.exchange
                await session.commit()
            await support._prepare(prefix)
            posted = await support._post(prefix)
            assert posted.investment_event_rows_imported == 194

            async with AsyncSession(engine, expire_on_commit=False) as session:
                aliases = await AnycoinBtcAliasService(
                    session,
                    source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
                ).onboard(
                    OnboardAnycoinBtcAliasCommand(
                        account_id=account_id,
                        batch_ids=(f"{prefix}-batch",),
                        source=ImportSource.anycoin,
                        created_at=posted.completed_at,
                    )
                )
                assert len(aliases.aliases) == 1
                await _seed_anycoin_transfer_valuation_evidence(
                    session,
                    prefix=prefix,
                    account_id=account_id,
                    created_at=posted.completed_at,
                )
                rebuilt = await HoldingRebuildService(session).rebuild(
                    account_id=account_id,
                    rebuilt_at=SNAPSHOT_AT,
                )
                assert rebuilt.total == 1
                holding = await session.scalar(
                    select(HoldingModel).where(HoldingModel.account_id == account_id)
                )
                assert holding is not None
                assert holding.quantity > 0
                assert holding.avg_buy_price == Decimal("1458377.6860068004")
                assert holding.cost_basis_by_currency == {"CZK": "29167.5537201360"}

                asset = await session.get(AssetModel, holding.asset_id)
                assert asset is not None
                assert (asset.symbol, asset.name) == ("BTC", "Bitcoin")

                alias = await session.scalar(
                    select(AssetAliasModel).where(
                        AssetAliasModel.asset_id == holding.asset_id,
                        AssetAliasModel.provider == AssetAliasProvider.coingecko,
                    )
                )
                assert alias is not None and alias.external_id == "bitcoin"
                assert alias.listing_id is None
                # Holding rebuild participates in the caller-owned transaction.
                # Commit the same boundary used by durable import finalization before
                # the market planner opens its repeatable-read transaction.
                await session.commit()

                trading_account_id, trading_event_at = await _seed_known_trading_account(
                    session,
                    prefix=prefix,
                    user_id=user_id,
                )
                yahoo_transport = _YahooTransport(trading_event_at)

                observed_epoch = int(SNAPSHOT_AT.replace(tzinfo=UTC).timestamp())
                requests: list[httpx.Request] = []

                def coingecko_response(request: httpx.Request) -> httpx.Response:
                    requests.append(request)
                    return httpx.Response(
                        200,
                        headers={"content-type": "application/json"},
                        content=json.dumps(
                            {
                                "bitcoin": {
                                    "czk": 1419861.4401809645,
                                    "last_updated_at": observed_epoch,
                                }
                            }
                        ).encode(),
                    )

                market = await create_production_market_evidence_service(
                    session,
                    Settings(
                        environment="test",
                        market_evidence_source_mode="local_free",
                        _env_file=None,
                    ),
                    coingecko_http_transport=httpx.MockTransport(coingecko_response),
                    yahoo_finance_transport=yahoo_transport,
                ).refresh(
                    RefreshMarketEvidenceCommand(
                        user_id=user_id,
                        snapshot_timestamp=SNAPSHOT_AT,
                        created_at=SNAPSHOT_AT,
                    )
                )
                assert len(requests) == 1
                assert requests[0].url.params["ids"] == "bitcoin"
                assert requests[0].url.params["vs_currencies"] == "czk"
                assert {call[0] for call in yahoo_transport.calls} == {
                    "AAA",
                    "EURCZK=X",
                }
                assert market.required_price_count == 2
                assert market.required_fx_count == 2
                assert market.prices_created == 2
                assert market.rates_created == 2

                publication = await UserSnapshotRefreshExecutor(
                    session,
                    source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
                ).execute(
                    ExecuteUserSnapshotRefreshCommand(
                        user_id=user_id,
                        snapshot_timestamp=SNAPSHOT_AT,
                        granularity=SnapshotGranularity.minute,
                        source=SnapshotSource.import_event,
                        calculation_version=3,
                        calculated_at=SNAPSHOT_AT,
                        created_at=SNAPSHOT_AT,
                        is_recalculated=False,
                    )
                )
                assert publication.created_account_snapshot_count == 2
                assert publication.selected_account_snapshot_count == 2
                identities = {
                    identity.account_id: identity.snapshot_id
                    for identity in publication.required_account_snapshot_identities
                }
                assert set(identities) == {account_id, trading_account_id}

                snapshot = await session.get(
                    AccountSnapshotModel,
                    identities[account_id],
                )
                assert snapshot is not None
                assert snapshot.calculation_version == 3
                assert snapshot.investment_value > 0
                assert snapshot.total_value == snapshot.investment_value + snapshot.cash_value
                assert snapshot.investment_cost_basis == Decimal("29167.553720")
                assert snapshot.net_deposits_value == Decimal("40818.385000")
                assert snapshot.realized_pnl_value == Decimal("-4250.322065")
                assert snapshot.unrealized_pnl_value == Decimal("-770.324916")
                assert snapshot.fees_value >= 0
                assert snapshot.taxes_value >= 0

                item = await session.scalar(
                    select(AccountSnapshotItemModel).where(
                        AccountSnapshotItemModel.snapshot_id == snapshot.id
                    )
                )
                assert item is not None
                assert item.quantity == holding.quantity
                assert item.value > 0
                item_cost_metrics = (
                    item.native_cost_basis,
                    item.native_cost_currency,
                    item.native_cost_basis_by_currency,
                    item.average_buy_price,
                    item.average_buy_price_currency,
                    item.cost_basis,
                    item.cost_currency,
                )
                assert item_cost_metrics == (
                    Decimal("29167.5537201360"),
                    "CZK",
                    {"CZK": "29167.5537201360"},
                    Decimal("1458377.6860068004"),
                    "CZK",
                    Decimal("29167.553720"),
                    "CZK",
                ), item_cost_metrics
                holding_sql_null = await session.scalar(
                    text(
                        'SELECT "costBasisByCurrency" IS NULL FROM public."Holding" '
                        "WHERE id = :holding_id"
                    ),
                    {"holding_id": holding.id},
                )
                item_sql_null = await session.scalar(
                    text(
                        'SELECT "nativeCostBasisByCurrency" IS NULL '
                        'FROM public."AccountSnapshotItem" WHERE id = :item_id'
                    ),
                    {"item_id": item.id},
                )
                snapshot_sql_nulls = (
                    await session.execute(
                        text(
                            'SELECT "investmentCostBasisByCurrency" IS NULL, '
                            '"netDepositsByCurrency" IS NULL, '
                            '"realizedPnlByCurrency" IS NULL, '
                            '"unrealizedPnlByCurrency" IS NULL '
                            'FROM public."AccountSnapshot" WHERE id = :snapshot_id'
                        ),
                        {"snapshot_id": snapshot.id},
                    )
                ).one()
                assert holding_sql_null is False
                assert item_sql_null is False
                assert tuple(snapshot_sql_nulls) == (False, False, False, False)
                assert snapshot.unrealized_pnl_by_currency == {"CZK": "-770.324916"}

                net_worth = await session.get(
                    NetWorthSnapshotModel,
                    publication.net_worth_snapshot_id,
                )
                assert net_worth is not None
                assert net_worth.total_net_worth == Decimal("28897.228804")

                command = ReadAuthorizedMultiAccountPortfolioSnapshotCommand(
                    principal=AuthenticatedPrincipal(
                        user_id=user_id,
                        email=f"{prefix}@example.com",
                        name=prefix,
                    ),
                    timestamp=SNAPSHOT_AT,
                    granularity=PortfolioSnapshotGranularity.minute,
                    currency="CZK",
                    calculation_version=3,
                    accounts=tuple(
                        ExactAccountSnapshotSelection(
                            account_id=selected_account_id,
                            required_snapshot_id=selected_snapshot_id,
                        )
                        for selected_account_id, selected_snapshot_id in sorted(identities.items())
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
                assert portfolio.summary.total_value == dashboard.summary.total_value
                assert portfolio.summary.investment_value == dashboard.summary.investment_value
                assert portfolio.summary.total_value == Decimal("28897.228804")
                assert portfolio.summary.investment_cost_basis == Decimal("31667.553720")
                assert dashboard.summary.investment_cost_basis == Decimal("31667.553720")
                assert {account.account.name for account in portfolio.accounts} == {
                    "Anycoin event-date valuation",
                    "Trading known basis",
                }
                anycoin_view = next(
                    account
                    for account in portfolio.accounts
                    if account.account.account_id == account_id
                )
                trading_view = next(
                    account
                    for account in portfolio.accounts
                    if account.account.account_id == trading_account_id
                )
                assert anycoin_view.positions[0].native_value == Decimal("28397.2288036193")
                assert anycoin_view.summary.investment_cost_basis == Decimal("29167.553720")
                assert trading_view.summary.investment_cost_basis == Decimal("2500.000000")
                assert dashboard.top_positions[0].name == "Bitcoin"

                current_baseline_at = SNAPSHOT_AT + timedelta(hours=12)
                current_baseline = await UserSnapshotRefreshExecutor(
                    session,
                    source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
                ).execute(
                    ExecuteUserSnapshotRefreshCommand(
                        user_id=user_id,
                        snapshot_timestamp=current_baseline_at,
                        granularity=SnapshotGranularity.day,
                        source=SnapshotSource.manual_recalculation,
                        calculation_version=3,
                        calculated_at=current_baseline_at,
                        created_at=current_baseline_at,
                        is_recalculated=True,
                    )
                )
                assert current_baseline.selected_account_snapshot_count == 2

                settings = Settings(
                    environment="test",
                    market_evidence_source_mode="local_free",
                    _env_file=None,
                )
                current = await CurrentValueService(
                    session,
                    settings,
                    clock=lambda: current_baseline_at,
                    market_service_factory=lambda _session, _settings, _planner: (
                        _ReplayMarketService(
                            user_id=user_id,
                            price_ids=market.price_ids,
                            rate_ids=market.exchange_rate_ids,
                            required_price_count=len(cast(Any, _planner).plan.price_requirements),
                            required_fx_count=len(cast(Any, _planner).plan.fx_requirements),
                        )
                    ),
                ).read_portfolio(
                    ReadCurrentPortfolioCommand(
                        principal=AuthenticatedPrincipal(
                            user_id=user_id,
                            email=f"{prefix}@example.com",
                            name=prefix,
                        )
                    )
                )
                assert current.portfolio.summary.total_value == portfolio.summary.total_value
                assert current.portfolio.summary.investment_cost_basis == Decimal("31667.553720")
                assert {item.account.account_id for item in current.account_presentations} == {
                    account_id,
                    trading_account_id,
                }
        finally:
            await engine.dispose()
    finally:
        mutable_support.DATABASE_URL = original_support_url
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin.close()
