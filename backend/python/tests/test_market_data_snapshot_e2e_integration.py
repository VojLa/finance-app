from __future__ import annotations

import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
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
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.fx.models import ExchangeRateObservation
from app.modules.market_data.models import (
    ExchangeRateRequirement,
    MarketEvidenceStateError,
    PriceRequirement,
)
from app.modules.market_data.providers import (
    ExchangeRateProviderRegistry,
    PriceProviderRegistry,
)
from app.modules.market_data.service import (
    MarketEvidenceRefreshService,
    RefreshMarketEvidenceCommand,
)
from app.modules.market_data.writer import exchange_rate_id, price_snapshot_id
from app.modules.prices.models import PriceObservation
from app.modules.snapshot_refresh.executor import (
    ExecuteUserSnapshotRefreshCommand,
    SnapshotRefreshExecutionStateError,
    UserSnapshotRefreshExecutor,
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

SNAPSHOT_AT = datetime(2026, 8, 3)
EVENT_AT = SNAPSHOT_AT - timedelta(days=10)
CALCULATED_AT = datetime(2026, 8, 3, 0, 1)
CREATED_AT = datetime(2026, 8, 3, 0, 2)


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=8)


class _PriceProvider:
    source = PriceSource.yahoo_finance

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.requirements: list[PriceRequirement] = []

    async def fetch(self, requirement: PriceRequirement) -> PriceObservation:
        assert not self.session.in_transaction()
        self.requirements.append(requirement)
        return PriceObservation(
            asset_id=requirement.asset_id,
            listing_id=requirement.listing_id,
            provider=requirement.provider,
            provider_symbol=requirement.provider_symbol,
            price=Decimal("110.0000000000"),
            currency=requirement.listing_currency,
            observed_at=requirement.through - timedelta(hours=1),
        )


class _FxProvider:
    source = ExchangeRateSource.ecb

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.requirements: list[ExchangeRateRequirement] = []

    async def fetch(
        self,
        requirement: ExchangeRateRequirement,
    ) -> ExchangeRateObservation:
        assert not self.session.in_transaction()
        self.requirements.append(requirement)
        return ExchangeRateObservation(
            from_currency=requirement.from_currency,
            to_currency=requirement.to_currency,
            provider=requirement.provider,
            rate=(
                Decimal("25.00000000")
                if requirement.through == SNAPSHOT_AT
                else Decimal("24.00000000")
            ),
            effective_at=requirement.through - timedelta(days=1),
        )


class _FailingPriceProvider:
    source = PriceSource.yahoo_finance

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.calls = 0

    async def fetch(self, requirement: PriceRequirement) -> PriceObservation:
        assert not self.session.in_transaction()
        self.calls += 1
        raise RuntimeError("controlled provider failure")


async def _seed(prefix: str) -> tuple[str, str, str, str]:
    user_id = f"{prefix}-user"
    account_id = f"{prefix}-account"
    asset_id = f"{prefix}-asset"
    listing_id = f"{prefix}-listing"
    event_id = f"{prefix}-event"
    symbol = f"T{prefix[-12:].replace('-', '').upper()}"
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            UserModel(
                id=user_id,
                email=f"{user_id}@example.com",
                name=None,
                password_hash=None,
                base_currency="CZK",
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            )
        )
        session.add(
            AccountModel(
                id=account_id,
                name="Exact market evidence account",
                type=AccountType.broker,
                currency="EUR",
                color=None,
                notes=None,
                is_archived=False,
                archived_at=None,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            )
        )
        session.add(
            AssetModel(
                id=asset_id,
                symbol=symbol,
                isin=None,
                name="Exact market evidence asset",
                asset_type=AssetType.etf,
                currency="EUR",
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            )
        )
        await session.flush()
        session.add(
            AccountMemberModel(
                id=f"{prefix}-member",
                account_id=account_id,
                user_id=user_id,
                role=AccountMemberRole.owner,
                relation_type=AccountRelationType.owner,
                invited_by_id=None,
                accepted_at=CREATED_AT,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            )
        )
        session.add(
            AssetListingModel(
                id=listing_id,
                asset_id=asset_id,
                symbol=symbol,
                exchange=f"EX-{prefix}",
                mic=None,
                currency="EUR",
                country=None,
                provider=PriceSource.yahoo_finance,
                provider_symbol=f"EXACT-{prefix}",
                is_primary=False,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            )
        )
        await session.flush()
        session.add(
            HoldingModel(
                id=f"{prefix}-holding",
                symbol=symbol,
                name="Exact market evidence holding",
                asset_type=AssetType.etf,
                quantity=Decimal("2"),
                avg_buy_price=Decimal("100"),
                currency="EUR",
                current_price=None,
                current_value=None,
                unrealized_pnl=None,
                realized_pnl=None,
                asset_id=asset_id,
                listing_id=listing_id,
                account_id=account_id,
                calculated_at=CREATED_AT,
                updated_at=CREATED_AT,
            )
        )
        session.add(
            InvestmentEventModel(
                id=event_id,
                account_id=account_id,
                type=InvestmentEventType.cash_deposit,
                date=EVENT_AT,
                source=None,
                external_id=f"{prefix}-deposit",
                order_id=None,
                description="Exact external cash flow",
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
                id=f"{prefix}-movement",
                event_id=event_id,
                account_id=account_id,
                asset_id=None,
                listing_id=None,
                kind=InvestmentMovementKind.cash,
                direction=MovementDirection.incoming,
                quantity=Decimal("1000"),
                currency="EUR",
                price_per_unit=None,
                value_amount=Decimal("1000"),
                value_currency="EUR",
                source_symbol=None,
                source_asset_type=None,
                note=None,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            )
        )
        await session.commit()
    await engine.dispose()
    return user_id, account_id, asset_id, listing_id


def _snapshot_command(user_id: str) -> ExecuteUserSnapshotRefreshCommand:
    return ExecuteUserSnapshotRefreshCommand(
        user_id=user_id,
        snapshot_timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.price_refresh,
        calculation_version=1,
        calculated_at=CALCULATED_AT,
        created_at=CREATED_AT,
        is_recalculated=False,
    )


@pytest.mark.asyncio
async def test_provider_failure_writes_no_market_or_snapshot_rows() -> None:
    prefix = f"r5a-provider-failure-{uuid4()}"
    user_id, account_id, _, listing_id = await _seed(prefix)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            rates_before = await session.scalar(select(func.count()).select_from(ExchangeRateModel))
            await session.rollback()
            price_provider = _FailingPriceProvider(session)
            fx_provider = _FxProvider(session)
            with pytest.raises(MarketEvidenceStateError) as error:
                await MarketEvidenceRefreshService(
                    session,
                    price_registry=PriceProviderRegistry((price_provider,)),
                    fx_registry=ExchangeRateProviderRegistry((fx_provider,)),
                ).refresh(
                    RefreshMarketEvidenceCommand(
                        user_id,
                        SNAPSHOT_AT,
                        CREATED_AT,
                    )
                )
            assert str(error.value) == "Market evidence is unavailable."
            assert price_provider.calls == 1
            assert fx_provider.requirements == []
            assert not session.in_transaction()
        async with AsyncSession(engine) as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(PriceSnapshotModel)
                    .where(PriceSnapshotModel.listing_id == listing_id)
                )
                == 0
            )
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


@pytest.mark.asyncio
async def test_market_refresh_to_account_and_net_worth_snapshot_e2e() -> None:
    prefix = f"r5a-e2e-{uuid4()}"
    user_id, account_id, asset_id, listing_id = await _seed(prefix)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            with pytest.raises(SnapshotRefreshExecutionStateError):
                await UserSnapshotRefreshExecutor(session).execute(_snapshot_command(user_id))
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

        async with AsyncSession(engine, expire_on_commit=False) as session:
            price_provider = _PriceProvider(session)
            fx_provider = _FxProvider(session)
            market_result = await MarketEvidenceRefreshService(
                session,
                price_registry=PriceProviderRegistry((price_provider,)),
                fx_registry=ExchangeRateProviderRegistry((fx_provider,)),
            ).refresh(
                RefreshMarketEvidenceCommand(
                    user_id,
                    SNAPSHOT_AT,
                    CREATED_AT,
                )
            )
            assert not session.in_transaction()

            assert market_result.required_price_count == 1
            assert market_result.required_fx_count == 2
            assert len(price_provider.requirements) == 1
            assert [item.through for item in fx_provider.requirements] == [
                EVENT_AT,
                SNAPSHOT_AT,
            ]
            expected_price = PriceObservation(
                asset_id=asset_id,
                listing_id=listing_id,
                provider=PriceSource.yahoo_finance,
                provider_symbol=f"EXACT-{prefix}",
                price=Decimal("110.0000000000"),
                currency="EUR",
                observed_at=SNAPSHOT_AT - timedelta(hours=1),
            )
            expected_event_rate = ExchangeRateObservation(
                from_currency="EUR",
                to_currency="CZK",
                provider=ExchangeRateSource.ecb,
                rate=Decimal("24.00000000"),
                effective_at=EVENT_AT - timedelta(days=1),
            )
            expected_snapshot_rate = ExchangeRateObservation(
                from_currency="EUR",
                to_currency="CZK",
                provider=ExchangeRateSource.ecb,
                rate=Decimal("25.00000000"),
                effective_at=SNAPSHOT_AT - timedelta(days=1),
            )
            assert market_result.price_ids == (price_snapshot_id(expected_price),)
            assert market_result.exchange_rate_ids == tuple(
                sorted(
                    (
                        exchange_rate_id(expected_event_rate),
                        exchange_rate_id(expected_snapshot_rate),
                    )
                )
            )

            async with session.begin():
                await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
                evidence = await AccountSnapshotEvidenceService(session).build(
                    BuildAccountSnapshotEvidenceCommand(
                        account_id=account_id,
                        snapshot_timestamp=SNAPSHOT_AT,
                        granularity=SnapshotGranularity.day,
                        source=SnapshotSource.price_refresh,
                        calculation_version=1,
                        output_currency="CZK",
                    )
                )
            assert evidence.selected_price_ids == market_result.price_ids
            assert evidence.selected_snapshot_exchange_rate_ids == (
                exchange_rate_id(expected_snapshot_rate),
            )
            assert evidence.selected_historical_exchange_rate_ids == (
                exchange_rate_id(expected_event_rate),
            )

            refreshed = await UserSnapshotRefreshExecutor(session).execute(
                _snapshot_command(user_id)
            )
            assert not session.in_transaction()
            assert refreshed.selected_account_snapshot_count == 1
            assert refreshed.created_account_snapshot_count == 1

        async with AsyncSession(engine) as session:
            prices = tuple(
                await session.scalars(
                    select(PriceSnapshotModel).where(PriceSnapshotModel.listing_id == listing_id)
                )
            )
            rates = tuple(
                await session.scalars(
                    select(ExchangeRateModel).where(
                        ExchangeRateModel.id.in_(market_result.exchange_rate_ids)
                    )
                )
            )
            assert len(prices) == 1
            assert prices[0].id == market_result.price_ids[0]
            assert prices[0].price == Decimal("110.0000000000")
            assert prices[0].timestamp == SNAPSHOT_AT - timedelta(hours=1)
            assert prices[0].source is PriceSource.yahoo_finance
            assert len(rates) == 2
            assert {(item.id, item.rate, item.date, item.source) for item in rates} == {
                (
                    exchange_rate_id(expected_event_rate),
                    Decimal("24.00000000"),
                    EVENT_AT - timedelta(days=1),
                    ExchangeRateSource.ecb,
                ),
                (
                    exchange_rate_id(expected_snapshot_rate),
                    Decimal("25.00000000"),
                    SNAPSHOT_AT - timedelta(days=1),
                    ExchangeRateSource.ecb,
                ),
            }
            account_snapshot = await session.get(
                AccountSnapshotModel,
                refreshed.required_account_snapshot_identities[0].snapshot_id,
            )
            net_worth = await session.get(
                NetWorthSnapshotModel,
                refreshed.net_worth_snapshot_id,
            )
            items = tuple(
                await session.scalars(
                    select(AccountSnapshotItemModel).where(
                        AccountSnapshotItemModel.snapshot_id
                        == refreshed.required_account_snapshot_identities[0].snapshot_id
                    )
                )
            )
            assert account_snapshot is not None
            assert account_snapshot.cash_value == Decimal("25000.000000")
            assert account_snapshot.investment_value == Decimal("5500.000000")
            assert account_snapshot.investment_cost_basis == Decimal("5000.000000")
            assert account_snapshot.net_deposits_value == Decimal("24000.000000")
            assert account_snapshot.unrealized_pnl_value == Decimal("500.000000")
            assert account_snapshot.total_value == Decimal("30500.000000")
            assert account_snapshot.exchange_rates == {
                "version": 1,
                "snapshotRates": [
                    {
                        "rateId": exchange_rate_id(expected_snapshot_rate),
                        "from": "EUR",
                        "to": "CZK",
                        "rate": "25.00000000",
                        "timestamp": (SNAPSHOT_AT - timedelta(days=1)).isoformat(
                            timespec="milliseconds"
                        ),
                        "source": "ecb",
                    }
                ],
                "historicalRateIds": [exchange_rate_id(expected_event_rate)],
            }
            assert len(items) == 1
            assert items[0].price_per_unit == Decimal("110.0000000000")
            assert items[0].price_source is PriceSource.yahoo_finance
            assert net_worth is not None
            assert net_worth.cash_value == Decimal("25000.000000")
            assert net_worth.portfolio_value == Decimal("5500.000000")
            assert net_worth.liabilities_value == Decimal("0.000000")
            assert net_worth.total_net_worth == Decimal("30500.000000")

        async with AsyncSession(engine) as session:
            price_provider = _PriceProvider(session)
            fx_provider = _FxProvider(session)
            replayed_market = await MarketEvidenceRefreshService(
                session,
                price_registry=PriceProviderRegistry((price_provider,)),
                fx_registry=ExchangeRateProviderRegistry((fx_provider,)),
            ).refresh(
                RefreshMarketEvidenceCommand(
                    user_id,
                    SNAPSHOT_AT,
                    datetime(2026, 8, 3, 0, 3),
                )
            )
            replayed_snapshot = await UserSnapshotRefreshExecutor(session).execute(
                _snapshot_command(user_id)
            )
            assert replayed_market.prices_created == 0
            assert replayed_market.prices_replayed == 1
            assert replayed_market.rates_created == 0
            assert replayed_market.rates_replayed == 2
            assert replayed_snapshot.replayed_account_snapshot_count == 1
    finally:
        await engine.dispose()
