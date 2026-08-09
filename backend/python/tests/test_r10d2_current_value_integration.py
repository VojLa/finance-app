from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

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
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    LiabilityBalanceSource,
    MovementDirection,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
    TransactionType,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.canonical_state import CanonicalChangeKind, CanonicalStateService
from app.modules.current_value.service import (
    CurrentValueService,
    CurrentValueUnavailableError,
    ReadCurrentPortfolioCommand,
)
from app.modules.holdings.rebuild_service import HoldingRebuildService
from app.modules.liabilities.writer import (
    LiabilityBalanceWriter,
    WriteLiabilityBalanceCommand,
)
from app.modules.market_data.models import MarketEvidenceRefreshResult
from app.modules.market_data.service import RefreshMarketEvidenceCommand
from app.modules.snapshot_refresh.executor import (
    ExecuteUserSnapshotRefreshCommand,
    UserSnapshotRefreshExecutor,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
BASELINE_AT = datetime(2038, 9, 1)
CURRENT_AT = BASELINE_AT + timedelta(hours=12)


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=4)


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    user_id = f"{prefix}-user"
    account_id = f"{prefix}-account"
    async with AsyncSession(engine) as session:
        await session.execute(
            delete(ExchangeRateModel).where(ExchangeRateModel.id.startswith(prefix))
        )
        await session.execute(delete(HoldingModel).where(HoldingModel.account_id == account_id))
        await session.execute(
            delete(InvestmentMovementModel).where(InvestmentMovementModel.account_id == account_id)
        )
        await session.execute(
            delete(InvestmentEventModel).where(InvestmentEventModel.account_id == account_id)
        )
        await session.execute(
            delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id == user_id)
        )
        await session.execute(
            delete(AccountSnapshotModel).where(AccountSnapshotModel.account_id == account_id)
        )
        await session.execute(
            delete(LiabilityBalanceModel).where(LiabilityBalanceModel.account_id == account_id)
        )
        await session.execute(
            delete(TransactionModel).where(TransactionModel.account_id == account_id)
        )
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id == account_id)
        )
        await session.execute(delete(AccountModel).where(AccountModel.id == account_id))
        await session.execute(delete(UserModel).where(UserModel.id == user_id))
        await session.execute(
            delete(PriceSnapshotModel).where(PriceSnapshotModel.id.startswith(prefix))
        )
        await session.execute(delete(AssetAliasModel).where(AssetAliasModel.id.startswith(prefix)))
        await session.execute(
            delete(AssetListingModel).where(AssetListingModel.id.startswith(prefix))
        )
        await session.execute(delete(AssetModel).where(AssetModel.id.startswith(prefix)))
        await session.commit()
    await engine.dispose()


async def _seed(
    prefix: str,
    *,
    base_currency: str = "EUR",
    account_currency: str = "EUR",
    account_type: AccountType = AccountType.loan,
) -> tuple[str, str]:
    await _cleanup(prefix)
    user_id = f"{prefix}-user"
    account_id = f"{prefix}-account"
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            UserModel(
                id=user_id,
                email=f"{prefix}@example.test",
                name="D2 integration",
                password_hash=None,
                base_currency=base_currency,
                created_at=BASELINE_AT - timedelta(days=2),
                updated_at=BASELINE_AT - timedelta(days=2),
            )
        )
        session.add(
            AccountModel(
                id=account_id,
                name="Loan",
                type=account_type,
                currency=account_currency,
                color=None,
                is_archived=False,
                archived_at=None,
                created_at=BASELINE_AT - timedelta(days=2),
                updated_at=BASELINE_AT - timedelta(days=2),
                notes=None,
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
                accepted_at=BASELINE_AT - timedelta(days=2),
                created_at=BASELINE_AT - timedelta(days=2),
                updated_at=BASELINE_AT - timedelta(days=2),
            )
        )
        await session.commit()
    await engine.dispose()
    return user_id, account_id


async def _seed_cash(prefix: str) -> tuple[str, str]:
    return await _seed(prefix, account_type=AccountType.bank)


async def _transaction(
    account_id: str,
    *,
    transaction_id: str,
    date: datetime,
    amount: str,
) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            TransactionModel(
                id=transaction_id,
                date=date,
                booking_date=None,
                amount=Decimal(amount),
                currency="EUR",
                reporting_amount=None,
                reporting_currency=None,
                type=(TransactionType.income if Decimal(amount) > 0 else TransactionType.expense),
                classification=None,
                description="D2 canonical transaction",
                note=None,
                counterparty=None,
                external_id=transaction_id,
                is_reviewed=True,
                archived_at=None,
                deleted_at=None,
                category_id=None,
                account_id=account_id,
                import_batch_id=None,
                created_at=date,
                updated_at=date,
            )
        )
        await session.flush()
        await CanonicalStateService(session).record(
            account_id=account_id,
            kind=CanonicalChangeKind.transaction,
            entity_id=transaction_id,
            financial_timestamp=date,
            created_at=date,
            replay=False,
        )


async def _seed_investment(
    prefix: str,
    *,
    source: ImportSource,
    asset_type: AssetType,
    provider: AssetAliasProvider,
    external_id: str,
) -> tuple[str, str, str]:
    user_id, account_id = await _seed(prefix)
    asset_id = f"{prefix}-asset"
    listing_id = f"{prefix}-listing"
    engine = _engine()
    async with AsyncSession(engine) as session:
        account = await session.get(AccountModel, account_id)
        assert account is not None
        account.type = (
            AccountType.crypto_wallet if asset_type is AssetType.crypto else AccountType.broker
        )
        account.name = "Anycoin" if source is ImportSource.anycoin else "Trading212"
        session.add(
            AssetModel(
                id=asset_id,
                symbol="BTC" if asset_type is AssetType.crypto else "AAA",
                isin=None,
                name="Bitcoin" if asset_type is AssetType.crypto else "Audit stock",
                asset_type=asset_type,
                currency="EUR",
                created_at=BASELINE_AT - timedelta(days=2),
                updated_at=BASELINE_AT - timedelta(days=2),
            )
        )
        await session.flush()
        session.add(
            AssetListingModel(
                id=listing_id,
                asset_id=asset_id,
                symbol="BTC" if asset_type is AssetType.crypto else "AAA",
                exchange="CoinGecko" if asset_type is AssetType.crypto else "NASDAQ",
                mic=None if asset_type is AssetType.crypto else "XNAS",
                currency="EUR",
                country=None,
                provider=PriceSource.broker,
                provider_symbol="BTC" if asset_type is AssetType.crypto else "AAA",
                is_primary=True,
                created_at=BASELINE_AT - timedelta(days=2),
                updated_at=BASELINE_AT - timedelta(days=2),
            )
        )
        session.add(
            AssetAliasModel(
                id=f"{prefix}-alias",
                asset_id=asset_id,
                provider=provider,
                external_id=external_id,
                created_at=BASELINE_AT - timedelta(days=2),
            )
        )
        session.add_all(
            [
                PriceSnapshotModel(
                    id=f"{prefix}-baseline-price",
                    asset_id=asset_id,
                    listing_id=listing_id,
                    price=Decimal("10.0000000000"),
                    currency="EUR",
                    source=(
                        PriceSource.coingecko
                        if provider is AssetAliasProvider.coingecko
                        else PriceSource.twelve_data
                    ),
                    timestamp=BASELINE_AT,
                    created_at=BASELINE_AT,
                ),
                PriceSnapshotModel(
                    id=f"{listing_id}-current-price",
                    asset_id=asset_id,
                    listing_id=listing_id,
                    price=Decimal("30.0000000000"),
                    currency="EUR",
                    source=(
                        PriceSource.coingecko
                        if provider is AssetAliasProvider.coingecko
                        else PriceSource.twelve_data
                    ),
                    timestamp=CURRENT_AT,
                    created_at=CURRENT_AT,
                ),
            ]
        )
        await session.commit()
    await engine.dispose()
    return user_id, account_id, listing_id


async def _rate(
    prefix: str,
    *,
    currency: str,
    at: datetime,
    value: str,
) -> str:
    rate_id = f"{prefix}-{currency.lower()}-{at:%Y%m%d%H%M}-rate"
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            ExchangeRateModel(
                id=rate_id,
                from_currency=currency,
                to_currency="CZK",
                rate=Decimal(value),
                date=at,
                source=ExchangeRateSource.cnb,
                created_at=at,
            )
        )
        await session.commit()
    await engine.dispose()
    return rate_id


async def _investment_buy(
    prefix: str,
    *,
    account_id: str,
    listing_id: str,
    source: ImportSource,
    at: datetime,
    price: str,
) -> None:
    event_id = f"{prefix}-event-{at.hour}"
    asset_id = f"{prefix}-asset"
    symbol = "BTC" if source is ImportSource.anycoin else "AAA"
    asset_type = AssetType.crypto if source is ImportSource.anycoin else AssetType.stock
    engine = _engine()
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            InvestmentEventModel(
                id=event_id,
                account_id=account_id,
                type=InvestmentEventType.trade,
                date=at,
                source=source,
                external_id=event_id,
                order_id=None,
                description="Fixture-derived buy",
                realized_pnl=None,
                realized_pnl_currency=None,
                import_batch_id=None,
                archived_at=None,
                deleted_at=None,
                created_at=at,
                updated_at=at,
            )
        )
        amount = Decimal(price)
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
                    quantity=Decimal("1.0000000000"),
                    currency=symbol,
                    price_per_unit=amount,
                    value_amount=amount,
                    value_currency="EUR",
                    source_symbol=symbol,
                    source_asset_type=asset_type,
                    note=None,
                    created_at=at,
                    updated_at=at,
                ),
                InvestmentMovementModel(
                    id=f"{event_id}-cash",
                    event_id=event_id,
                    account_id=account_id,
                    asset_id=None,
                    listing_id=None,
                    kind=InvestmentMovementKind.cash,
                    direction=MovementDirection.outgoing,
                    quantity=amount,
                    currency="EUR",
                    price_per_unit=None,
                    value_amount=amount,
                    value_currency="EUR",
                    source_symbol=None,
                    source_asset_type=None,
                    note=None,
                    created_at=at,
                    updated_at=at,
                ),
            ]
        )
        await CanonicalStateService(session).record(
            account_id=account_id,
            kind=CanonicalChangeKind.investment_event,
            entity_id=event_id,
            financial_timestamp=at,
            created_at=at,
            replay=False,
        )
    await engine.dispose()


async def _investment_cash_deposit(
    prefix: str,
    *,
    account_id: str,
    at: datetime,
    amount: str,
    currency: str,
) -> None:
    event_id = f"{prefix}-deposit"
    engine = _engine()
    async with AsyncSession(engine) as session, session.begin():
        session.add(
            InvestmentEventModel(
                id=event_id,
                account_id=account_id,
                type=InvestmentEventType.cash_deposit,
                date=at,
                source=ImportSource.trading212,
                external_id=event_id,
                order_id=None,
                description="Forward deposit",
                realized_pnl=None,
                realized_pnl_currency=None,
                import_batch_id=None,
                archived_at=None,
                deleted_at=None,
                created_at=at,
                updated_at=at,
            )
        )
        session.add(
            InvestmentMovementModel(
                id=f"{event_id}-cash",
                event_id=event_id,
                account_id=account_id,
                asset_id=None,
                listing_id=None,
                kind=InvestmentMovementKind.cash,
                direction=MovementDirection.incoming,
                quantity=Decimal(amount),
                currency=currency,
                price_per_unit=None,
                value_amount=Decimal(amount),
                value_currency=currency,
                source_symbol=None,
                source_asset_type=None,
                note=None,
                created_at=at,
                updated_at=at,
            )
        )
        await CanonicalStateService(session).record(
            account_id=account_id,
            kind=CanonicalChangeKind.investment_event,
            entity_id=event_id,
            financial_timestamp=at,
            created_at=at,
            replay=False,
        )
    await engine.dispose()


async def _rebuild(account_id: str, *, at: datetime) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session, session.begin():
        await HoldingRebuildService(session).rebuild(account_id=account_id, rebuilt_at=at)
    await engine.dispose()


async def _liability(
    account_id: str,
    *,
    effective_at: datetime,
    external_id: str,
    amount: str,
) -> str:
    engine = _engine()
    async with AsyncSession(engine) as session:
        result = await LiabilityBalanceWriter(session).write(
            WriteLiabilityBalanceCommand(
                account_id=account_id,
                effective_at=effective_at,
                currency="EUR",
                outstanding_principal=Decimal(amount),
                accrued_interest=Decimal("0.000000"),
                fees_outstanding=Decimal("0.000000"),
                source=LiabilityBalanceSource.statement,
                external_id=external_id,
                created_at=effective_at,
            )
        )
    await engine.dispose()
    return result.balance_id


async def _daily_baseline(user_id: str) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        await UserSnapshotRefreshExecutor(session).execute(
            ExecuteUserSnapshotRefreshCommand(
                user_id=user_id,
                snapshot_timestamp=BASELINE_AT,
                granularity=SnapshotGranularity.day,
                source=SnapshotSource.manual_recalculation,
                calculation_version=1,
                calculated_at=BASELINE_AT,
                created_at=BASELINE_AT,
                is_recalculated=True,
            )
        )
    await engine.dispose()


class _ReplayMarketService:
    def __init__(
        self,
        user_id: str,
        output_currency: str,
        price_ids: tuple[str, ...],
        exchange_rate_ids: tuple[str, ...],
    ) -> None:
        self.user_id = user_id
        self.output_currency = output_currency
        self.price_ids = price_ids
        self.exchange_rate_ids = exchange_rate_ids

    async def refresh(
        self,
        command: RefreshMarketEvidenceCommand,
    ) -> MarketEvidenceRefreshResult:
        return MarketEvidenceRefreshResult(
            user_id=self.user_id,
            snapshot_timestamp=command.snapshot_timestamp,
            output_currency=self.output_currency,
            required_price_count=len(self.price_ids),
            required_fx_count=len(self.exchange_rate_ids),
            price_ids=self.price_ids,
            exchange_rate_ids=self.exchange_rate_ids,
            prices_created=0,
            prices_replayed=len(self.price_ids),
            rates_created=0,
            rates_replayed=len(self.exchange_rate_ids),
        )


async def _current(
    user_id: str,
    *,
    output_currency: str = "EUR",
    replay_price_ids: tuple[str, ...] = (),
    replay_exchange_rate_ids: tuple[str, ...] = (),
):
    engine = _engine()
    async with AsyncSession(engine) as session:
        settings = Settings(environment="test", _env_file=None)
        service = (
            CurrentValueService(
                session,
                settings,
                clock=lambda: CURRENT_AT,
                market_service_factory=lambda _session, _settings, _planner: _ReplayMarketService(
                    user_id,
                    output_currency,
                    replay_price_ids,
                    replay_exchange_rate_ids,
                ),
            )
            if replay_price_ids or replay_exchange_rate_ids
            else CurrentValueService(session, settings, clock=lambda: CURRENT_AT)
        )
        result = await service.read_portfolio(
            ReadCurrentPortfolioCommand(
                principal=AuthenticatedPrincipal(
                    user_id=user_id,
                    email=f"{user_id}@example.test",
                    name="D2",
                )
            )
        )
    await engine.dispose()
    return result


def test_current_liability_uses_daily_baseline_then_forward_replacement_without_snapshot_write() -> (
    None
):
    prefix = "r10d2-liability"

    async def scenario() -> None:
        user_id, account_id = await _seed(prefix)
        await _liability(
            account_id,
            effective_at=BASELINE_AT - timedelta(days=1),
            external_id="baseline",
            amount="100.000000",
        )
        await _daily_baseline(user_id)

        engine = _engine()
        async with AsyncSession(engine) as session:
            version = await session.scalar(text("select current_setting('server_version')"))
            assert isinstance(version, str) and version.startswith("16.10")
            before = (
                await session.scalar(select(func.count()).select_from(AccountSnapshotModel)),
                await session.scalar(select(func.count()).select_from(NetWorthSnapshotModel)),
            )
        await engine.dispose()

        baseline = await _current(user_id)
        assert baseline.portfolio.summary.liabilities_value == Decimal("100.000000")

        await _liability(
            account_id,
            effective_at=BASELINE_AT + timedelta(hours=2),
            external_id="forward",
            amount="75.000000",
        )
        current = await _current(user_id)
        assert current.portfolio.summary.liabilities_value == Decimal("75.000000")
        assert current.portfolio.summary.total_value == Decimal("-75.000000")

        engine = _engine()
        async with AsyncSession(engine) as session:
            after = (
                await session.scalar(select(func.count()).select_from(AccountSnapshotModel)),
                await session.scalar(select(func.count()).select_from(NetWorthSnapshotModel)),
            )
        await engine.dispose()
        assert after == before

        await _cleanup(prefix)

    asyncio.run(scenario())


def test_current_value_fails_closed_without_a_d1_baseline() -> None:
    prefix = "r10d2-no-baseline"

    async def scenario() -> None:
        user_id, _ = await _seed(prefix)
        with pytest.raises(CurrentValueUnavailableError):
            await _current(user_id)
        await _cleanup(prefix)

    asyncio.run(scenario())


def test_current_cash_applies_only_forward_canonical_delta_without_snapshot_write() -> None:
    prefix = "r10d2-cash"

    async def scenario() -> None:
        user_id, account_id = await _seed_cash(prefix)
        await _transaction(
            account_id,
            transaction_id=f"{prefix}-baseline",
            date=BASELINE_AT - timedelta(days=1),
            amount="100.000000",
        )
        await _daily_baseline(user_id)
        await _transaction(
            account_id,
            transaction_id=f"{prefix}-forward",
            date=BASELINE_AT + timedelta(hours=2),
            amount="25.000000",
        )

        engine = _engine()
        async with AsyncSession(engine) as session:
            before = (
                await session.scalar(select(func.count()).select_from(AccountSnapshotModel)),
                await session.scalar(select(func.count()).select_from(NetWorthSnapshotModel)),
            )
        await engine.dispose()

        current = await _current(user_id)
        assert current.portfolio.summary.cash_value == Decimal("125.000000")
        assert current.portfolio.summary.total_value == Decimal("125.000000")
        assert current.portfolio.summary.net_deposits_value == Decimal("0.000000")

        engine = _engine()
        async with AsyncSession(engine) as session:
            after = (
                await session.scalar(select(func.count()).select_from(AccountSnapshotModel)),
                await session.scalar(select(func.count()).select_from(NetWorthSnapshotModel)),
            )
        await engine.dispose()
        assert after == before

        await _cleanup(prefix)

    asyncio.run(scenario())


def test_mixed_currency_liability_projects_primary_and_presentation_from_one_forward_state() -> (
    None
):
    prefix = "r10d2-mixed-liability"

    async def scenario() -> None:
        user_id, account_id = await _seed(
            prefix,
            base_currency="CZK",
            account_currency="EUR",
        )
        await _liability(
            account_id,
            effective_at=BASELINE_AT - timedelta(days=1),
            external_id="baseline",
            amount="100.000000",
        )
        await _rate(
            prefix,
            currency="EUR",
            at=BASELINE_AT,
            value="25.00000000",
        )
        await _daily_baseline(user_id)
        await _liability(
            account_id,
            effective_at=BASELINE_AT + timedelta(hours=2),
            external_id="forward",
            amount="75.000000",
        )
        current_rate_id = await _rate(
            prefix,
            currency="EUR",
            at=CURRENT_AT,
            value="24.00000000",
        )

        result = await _current(
            user_id,
            output_currency="CZK",
            replay_exchange_rate_ids=(current_rate_id,),
        )
        assert result.portfolio.currency == "CZK"
        assert result.portfolio.summary.liabilities_value == Decimal("1800.000000")
        assert result.portfolio.summary.total_value == Decimal("-1800.000000")
        assert len(result.account_presentations) == 1
        presentation = result.account_presentations[0]
        assert presentation.currency == "EUR"
        assert presentation.summary.liabilities_value == Decimal("75.000000")
        assert presentation.summary.total_value == Decimal("-75.000000")
        await _cleanup(prefix)

    asyncio.run(scenario())


def test_forward_historical_metric_uses_event_date_fx_separately_from_current_cash_fx() -> None:
    prefix = "r10d2-historical-fx"
    event_at = BASELINE_AT + timedelta(hours=2)

    async def scenario() -> None:
        user_id, account_id = await _seed(
            prefix,
            base_currency="CZK",
            account_currency="EUR",
            account_type=AccountType.broker,
        )
        await _rebuild(account_id, at=BASELINE_AT - timedelta(hours=1))
        await _daily_baseline(user_id)
        await _investment_cash_deposit(
            prefix,
            account_id=account_id,
            at=event_at,
            amount="100.0000000000",
            currency="USD",
        )
        rate_ids = (
            await _rate(prefix, currency="USD", at=event_at, value="21.00000000"),
            await _rate(prefix, currency="EUR", at=event_at, value="24.00000000"),
            await _rate(prefix, currency="USD", at=CURRENT_AT, value="20.00000000"),
            await _rate(prefix, currency="EUR", at=CURRENT_AT, value="25.00000000"),
        )

        result = await _current(
            user_id,
            output_currency="CZK",
            replay_exchange_rate_ids=rate_ids,
        )
        primary = result.portfolio.accounts[0]
        presentation = result.account_presentations[0]
        assert primary.summary.cash_value == Decimal("2000.000000")
        assert primary.summary.net_deposits_value == Decimal("2100.000000")
        assert presentation.currency == "EUR"
        assert presentation.summary.cash_value == Decimal("80.000000")
        assert presentation.summary.net_deposits_value == Decimal("87.500000")
        assert primary.summary.cash_by_currency[0].amount == Decimal("100.000000")
        assert primary.summary.net_deposits_by_currency[0].amount == Decimal("100.000000")
        await _cleanup(prefix)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("suffix", "source", "asset_type", "provider", "external_id"),
    (
        (
            "trading212",
            ImportSource.trading212,
            AssetType.stock,
            AssetAliasProvider.twelve_data,
            '{"symbol":"AAA","mic_code":"XNAS"}',
        ),
        (
            "anycoin",
            ImportSource.anycoin,
            AssetType.crypto,
            AssetAliasProvider.coingecko,
            "bitcoin",
        ),
    ),
)
def test_fixture_derived_investment_delta_uses_baseline_items_and_current_price_without_snapshot_write(
    suffix: str,
    source: ImportSource,
    asset_type: AssetType,
    provider: AssetAliasProvider,
    external_id: str,
) -> None:
    prefix = f"r10d2-{suffix}"

    async def scenario() -> None:
        user_id, account_id, listing_id = await _seed_investment(
            prefix,
            source=source,
            asset_type=asset_type,
            provider=provider,
            external_id=external_id,
        )
        await _investment_buy(
            prefix,
            account_id=account_id,
            listing_id=listing_id,
            source=source,
            at=BASELINE_AT - timedelta(days=1),
            price="10.0000000000",
        )
        await _rebuild(account_id, at=BASELINE_AT - timedelta(hours=1))
        await _daily_baseline(user_id)
        await _investment_buy(
            prefix,
            account_id=account_id,
            listing_id=listing_id,
            source=source,
            at=BASELINE_AT + timedelta(hours=2),
            price="20.0000000000",
        )

        engine = _engine()
        async with AsyncSession(engine) as session:
            before = (
                await session.scalar(select(func.count()).select_from(AccountSnapshotModel)),
                await session.scalar(select(func.count()).select_from(NetWorthSnapshotModel)),
                await session.scalar(select(func.count()).select_from(HoldingModel)),
            )
        await engine.dispose()

        current = await _current(
            user_id,
            replay_price_ids=(f"{listing_id}-current-price",),
        )
        account = current.portfolio.accounts[0]
        assert account.summary.cash_value == Decimal("-30.000000")
        assert account.summary.investment_value == Decimal("60.000000")
        assert account.summary.investment_cost_basis == Decimal("30.000000")
        assert account.summary.unrealized_pnl_value == Decimal("30.000000")
        assert account.summary.total_value == Decimal("30.000000")
        assert len(account.positions) == 1
        assert account.positions[0].quantity == Decimal("2.0000000000")
        assert account.positions[0].native_cost_basis == Decimal("30.0000000000")

        engine = _engine()
        async with AsyncSession(engine) as session:
            after = (
                await session.scalar(select(func.count()).select_from(AccountSnapshotModel)),
                await session.scalar(select(func.count()).select_from(NetWorthSnapshotModel)),
                await session.scalar(select(func.count()).select_from(HoldingModel)),
            )
        await engine.dispose()
        assert after == before

        # The old complete-history minute calculation is a test oracle only.
        # D2 above already proved that its production read persisted no graph.
        await _rebuild(account_id, at=CURRENT_AT)
        engine = _engine()
        async with AsyncSession(engine) as session:
            oracle_result = await UserSnapshotRefreshExecutor(session).execute(
                ExecuteUserSnapshotRefreshCommand(
                    user_id=user_id,
                    snapshot_timestamp=CURRENT_AT,
                    granularity=SnapshotGranularity.minute,
                    source=SnapshotSource.manual_recalculation,
                    calculation_version=1,
                    calculated_at=CURRENT_AT,
                    created_at=CURRENT_AT,
                    is_recalculated=True,
                )
            )
            oracle = await session.get(
                AccountSnapshotModel,
                oracle_result.account_snapshots[0].snapshot_id,
            )
            oracle_net_worth = await session.get(
                NetWorthSnapshotModel,
                oracle_result.net_worth_snapshot_id,
            )
            assert oracle is not None and oracle_net_worth is not None
            assert oracle.cash_value == account.summary.cash_value
            assert oracle.investment_value == account.summary.investment_value
            assert oracle.investment_cost_basis == account.summary.investment_cost_basis
            assert oracle.liabilities_value == account.summary.liabilities_value
            assert oracle.total_value == account.summary.total_value
            assert oracle.net_deposits_value == account.summary.net_deposits_value
            assert oracle.realized_pnl_value == account.summary.realized_pnl_value
            assert oracle.unrealized_pnl_value == account.summary.unrealized_pnl_value
            assert oracle.fees_value == account.summary.fees_value
            assert oracle.taxes_value == account.summary.taxes_value
            assert oracle_net_worth.total_net_worth == current.portfolio.summary.total_value
        await engine.dispose()
        await _cleanup(prefix)

    asyncio.run(scenario())
