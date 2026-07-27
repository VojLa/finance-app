from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountType,
    AssetType,
    ExchangeRateSource,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
    TransactionClassification,
    TransactionType,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.db.models.transactions import TransactionModel
from app.db.url import normalize_database_url
from app.modules.snapshots.evidence_service import (
    AccountSnapshotEvidenceService,
    BuildAccountSnapshotEvidenceCommand,
)
from app.modules.snapshots.financial_metrics import AccountSnapshotEvidenceStateError

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
SNAPSHOT_AT = datetime(2026, 7, 27)
EVENT_AT = datetime(2026, 7, 26)


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=4)


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    account_ids = [f"{prefix}-account"]
    async with AsyncSession(engine) as session:
        snapshot_ids = tuple(
            await session.scalars(
                select(AccountSnapshotModel.id).where(
                    AccountSnapshotModel.account_id.in_(account_ids)
                )
            )
        )
        if snapshot_ids:
            await session.execute(
                delete(AccountSnapshotItemModel).where(
                    AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids)
                )
            )
        await session.execute(
            delete(AccountSnapshotModel).where(AccountSnapshotModel.account_id.in_(account_ids))
        )
        await session.execute(
            delete(InvestmentMovementModel).where(
                InvestmentMovementModel.account_id.in_(account_ids)
            )
        )
        await session.execute(
            delete(InvestmentEventModel).where(InvestmentEventModel.account_id.in_(account_ids))
        )
        await session.execute(
            delete(TransactionModel).where(TransactionModel.account_id.in_(account_ids))
        )
        await session.execute(
            delete(PriceSnapshotModel).where(PriceSnapshotModel.id.startswith(f"{prefix}-"))
        )
        await session.execute(
            delete(ExchangeRateModel).where(ExchangeRateModel.id.startswith(f"{prefix}-"))
        )
        await session.execute(delete(HoldingModel).where(HoldingModel.account_id.in_(account_ids)))
        await session.execute(
            delete(AssetListingModel).where(AssetListingModel.id.startswith(f"{prefix}-listing"))
        )
        await session.execute(delete(AssetModel).where(AssetModel.id.startswith(f"{prefix}-asset")))
        await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        await session.commit()
    await engine.dispose()


def _command(account_id: str) -> BuildAccountSnapshotEvidenceCommand:
    return BuildAccountSnapshotEvidenceCommand(
        account_id=account_id,
        snapshot_timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
    )


async def _snapshot_counts(session: AsyncSession) -> tuple[int, int]:
    return (
        await session.scalar(select(func.count()).select_from(AccountSnapshotModel)) or 0,
        await session.scalar(select(func.count()).select_from(AccountSnapshotItemModel)) or 0,
    )


@pytest.mark.asyncio
async def test_persisted_bank_balance_is_selected_without_snapshot_writes() -> None:
    prefix = "i5b-bank"
    await _cleanup(prefix)
    account_id = f"{prefix}-account"
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                AccountModel(
                    id=account_id,
                    name="Bank",
                    type=AccountType.bank,
                    currency="CZK",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            session.add_all(
                [
                    TransactionModel(
                        id=f"{prefix}-income",
                        account_id=account_id,
                        date=EVENT_AT,
                        booking_date=None,
                        amount=Decimal("100.000000"),
                        currency="CZK",
                        reporting_amount=None,
                        reporting_currency=None,
                        type=TransactionType.income,
                        classification=TransactionClassification.real_income,
                        description=None,
                        note=None,
                        counterparty=None,
                        external_id=None,
                        is_reviewed=False,
                        archived_at=None,
                        deleted_at=None,
                        category_id=None,
                        import_batch_id=None,
                        created_at=EVENT_AT,
                        updated_at=EVENT_AT,
                    ),
                    TransactionModel(
                        id=f"{prefix}-expense",
                        account_id=account_id,
                        date=EVENT_AT,
                        booking_date=None,
                        amount=Decimal("-25.000000"),
                        currency="CZK",
                        reporting_amount=None,
                        reporting_currency=None,
                        type=TransactionType.expense,
                        classification=TransactionClassification.real_expense,
                        description=None,
                        note=None,
                        counterparty=None,
                        external_id=None,
                        is_reviewed=False,
                        archived_at=None,
                        deleted_at=None,
                        category_id=None,
                        import_batch_id=None,
                        created_at=EVENT_AT,
                        updated_at=EVENT_AT,
                    ),
                ]
            )
            await session.commit()

        async with AsyncSession(engine) as session:
            before = await _snapshot_counts(session)
            first = await AccountSnapshotEvidenceService(session).build(_command(account_id))
            second = await AccountSnapshotEvidenceService(session).build(_command(account_id))
            assert first == second
            assert first.valuation.cash_value == Decimal("75.000000")
            assert first.valuation.total_value == Decimal("75.000000")
            assert await _snapshot_counts(session) == before
            await session.rollback()
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_persisted_broker_selects_price_snapshot_fx_and_event_fx() -> None:
    prefix = "i5b-broker"
    await _cleanup(prefix)
    account_id = f"{prefix}-account"
    asset_id = f"{prefix}-asset"
    listing_id = f"{prefix}-listing"
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                AccountModel(
                    id=account_id,
                    name="Broker",
                    type=AccountType.broker,
                    currency="CZK",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            session.add(
                AssetModel(
                    id=asset_id,
                    symbol="I5B",
                    isin=None,
                    name="I5B",
                    asset_type=AssetType.stock,
                    currency="EUR",
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            await session.flush()
            session.add(
                AssetListingModel(
                    id=listing_id,
                    asset_id=asset_id,
                    symbol="I5B",
                    exchange="trading212",
                    mic=None,
                    currency="EUR",
                    country=None,
                    provider=PriceSource.broker,
                    provider_symbol="I5B",
                    is_primary=False,
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            await session.flush()
            session.add(
                HoldingModel(
                    id=f"{prefix}-holding",
                    account_id=account_id,
                    asset_id=asset_id,
                    listing_id=listing_id,
                    symbol="I5B",
                    name="I5B",
                    asset_type=AssetType.stock,
                    quantity=Decimal("2"),
                    avg_buy_price=Decimal("10"),
                    currency="EUR",
                    current_price=Decimal("999"),
                    current_value=Decimal("999"),
                    unrealized_pnl=Decimal("999"),
                    realized_pnl=Decimal("999"),
                    calculated_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            session.add_all(
                [
                    PriceSnapshotModel(
                        id=f"{prefix}-price",
                        asset_id=asset_id,
                        listing_id=listing_id,
                        price=Decimal("15"),
                        currency="EUR",
                        source=PriceSource.broker,
                        timestamp=SNAPSHOT_AT,
                        created_at=SNAPSHOT_AT,
                    ),
                    PriceSnapshotModel(
                        id=f"{prefix}-future-price",
                        asset_id=asset_id,
                        listing_id=listing_id,
                        price=Decimal("999"),
                        currency="EUR",
                        source=PriceSource.broker,
                        timestamp=datetime(2026, 7, 28),
                        created_at=SNAPSHOT_AT,
                    ),
                    ExchangeRateModel(
                        id=f"{prefix}-event-rate",
                        from_currency="EUR",
                        to_currency="CZK",
                        rate=Decimal("20"),
                        date=EVENT_AT,
                        source=ExchangeRateSource.ecb,
                        created_at=EVENT_AT,
                    ),
                    ExchangeRateModel(
                        id=f"{prefix}-snapshot-rate",
                        from_currency="EUR",
                        to_currency="CZK",
                        rate=Decimal("25"),
                        date=SNAPSHOT_AT,
                        source=ExchangeRateSource.ecb,
                        created_at=SNAPSHOT_AT,
                    ),
                    ExchangeRateModel(
                        id=f"{prefix}-future-rate",
                        from_currency="EUR",
                        to_currency="CZK",
                        rate=Decimal("99"),
                        date=datetime(2026, 7, 28),
                        source=ExchangeRateSource.ecb,
                        created_at=SNAPSHOT_AT,
                    ),
                ]
            )
            session.add(
                InvestmentEventModel(
                    id=f"{prefix}-deposit",
                    account_id=account_id,
                    type=InvestmentEventType.cash_deposit,
                    date=EVENT_AT,
                    source=ImportSource.trading212,
                    external_id=None,
                    order_id=None,
                    description=None,
                    realized_pnl=None,
                    realized_pnl_currency=None,
                    import_batch_id=None,
                    archived_at=None,
                    deleted_at=None,
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            await session.flush()
            session.add(
                InvestmentMovementModel(
                    id=f"{prefix}-cash",
                    event_id=f"{prefix}-deposit",
                    account_id=account_id,
                    asset_id=None,
                    listing_id=None,
                    kind=InvestmentMovementKind.cash,
                    direction=MovementDirection.incoming,
                    quantity=Decimal("10"),
                    currency="EUR",
                    price_per_unit=None,
                    value_amount=Decimal("10"),
                    value_currency="EUR",
                    source_symbol=None,
                    source_asset_type=None,
                    note=None,
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            await session.commit()

        async with AsyncSession(engine) as session:
            before = await _snapshot_counts(session)
            result = await AccountSnapshotEvidenceService(session).build(_command(account_id))
            assert result.valuation.investment_value == Decimal("750.000000")
            assert result.valuation.investment_cost_basis == Decimal("500.000000")
            assert result.valuation.cash_value == Decimal("250.000000")
            assert result.net_deposits_value == Decimal("200.000000")
            assert result.unrealized_pnl_value == Decimal("250.000000")
            assert result.selected_price_ids == (f"{prefix}-price",)
            assert result.selected_snapshot_exchange_rate_ids == (f"{prefix}-snapshot-rate",)
            assert result.selected_historical_exchange_rate_ids == (f"{prefix}-event-rate",)
            assert await _snapshot_counts(session) == before
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_ambiguous_persisted_latest_price_fails_closed() -> None:
    prefix = "i5b-ambiguous"
    await _cleanup(prefix)
    account_id = f"{prefix}-account"
    asset_id = f"{prefix}-asset"
    listing_id = f"{prefix}-listing"
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                AccountModel(
                    id=account_id,
                    name="Broker",
                    type=AccountType.broker,
                    currency="EUR",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            session.add(
                AssetModel(
                    id=asset_id,
                    symbol="AMB",
                    isin=None,
                    name=None,
                    asset_type=AssetType.stock,
                    currency="EUR",
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            await session.flush()
            session.add(
                AssetListingModel(
                    id=listing_id,
                    asset_id=asset_id,
                    symbol="AMB",
                    exchange="x",
                    mic=None,
                    currency="EUR",
                    country=None,
                    provider=PriceSource.broker,
                    provider_symbol="AMB",
                    is_primary=False,
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            await session.flush()
            session.add(
                HoldingModel(
                    id=f"{prefix}-holding",
                    account_id=account_id,
                    asset_id=asset_id,
                    listing_id=listing_id,
                    symbol="AMB",
                    name=None,
                    asset_type=AssetType.stock,
                    quantity=Decimal("1"),
                    avg_buy_price=Decimal("1"),
                    currency="EUR",
                    current_price=None,
                    current_value=None,
                    unrealized_pnl=None,
                    realized_pnl=None,
                    calculated_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            session.add_all(
                [
                    PriceSnapshotModel(
                        id=f"{prefix}-broker",
                        asset_id=asset_id,
                        listing_id=listing_id,
                        price=Decimal("2"),
                        currency="EUR",
                        source=PriceSource.broker,
                        timestamp=SNAPSHOT_AT,
                        created_at=SNAPSHOT_AT,
                    ),
                    PriceSnapshotModel(
                        id=f"{prefix}-manual",
                        asset_id=asset_id,
                        listing_id=listing_id,
                        price=Decimal("2"),
                        currency="EUR",
                        source=PriceSource.manual,
                        timestamp=SNAPSHOT_AT,
                        created_at=SNAPSHOT_AT,
                    ),
                ]
            )
            await session.commit()
        async with AsyncSession(engine) as session:
            before = await _snapshot_counts(session)
            with pytest.raises(AccountSnapshotEvidenceStateError):
                await AccountSnapshotEvidenceService(session).build(_command(account_id))
            assert await _snapshot_counts(session) == before
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_persisted_liability_account_fails_without_balance_contract() -> None:
    prefix = "i5b-liability"
    await _cleanup(prefix)
    account_id = f"{prefix}-account"
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                AccountModel(
                    id=account_id,
                    name="Loan",
                    type=AccountType.loan,
                    currency="CZK",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            await session.commit()
        async with AsyncSession(engine) as session:
            before = await _snapshot_counts(session)
            with pytest.raises(AccountSnapshotEvidenceStateError):
                await AccountSnapshotEvidenceService(session).build(_command(account_id))
            assert await _snapshot_counts(session) == before
    finally:
        await engine.dispose()
        await _cleanup(prefix)
