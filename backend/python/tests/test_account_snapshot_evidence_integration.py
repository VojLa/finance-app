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
    LiabilityBalanceSource,
    MovementDirection,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
    TransactionClassification,
    TransactionType,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.db.models.transactions import TransactionModel
from app.db.url import normalize_database_url
from app.modules.snapshots.account_projection import CurrencyAmount
from app.modules.snapshots.evidence_service import (
    AccountSnapshotEvidenceService,
    BuildAccountSnapshotEvidenceCommand,
    ExactSnapshotMetric,
    SnapshotMetricUnsupportedReason,
    UnsupportedSnapshotMetric,
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
            delete(LiabilityBalanceModel).where(LiabilityBalanceModel.account_id.in_(account_ids))
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


def _command(
    account_id: str,
    *,
    output_currency: str | None = None,
) -> BuildAccountSnapshotEvidenceCommand:
    return BuildAccountSnapshotEvidenceCommand(
        account_id=account_id,
        snapshot_timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        output_currency=output_currency,
    )


def _transaction(
    *,
    transaction_id: str,
    account_id: str,
    amount: str,
    transaction_type: TransactionType,
    classification: TransactionClassification,
    currency: str = "CZK",
) -> TransactionModel:
    return TransactionModel(
        id=transaction_id,
        account_id=account_id,
        date=EVENT_AT,
        booking_date=None,
        amount=Decimal(amount),
        currency=currency,
        reporting_amount=None,
        reporting_currency=None,
        type=transaction_type,
        classification=classification,
        description="external deposit withdrawal bank fee tax",
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
    )


async def _snapshot_counts(session: AsyncSession) -> tuple[int, int]:
    return (
        await session.scalar(select(func.count()).select_from(AccountSnapshotModel)) or 0,
        await session.scalar(select(func.count()).select_from(AccountSnapshotItemModel)) or 0,
    )


async def _evidence_state_counts(
    session: AsyncSession,
    *,
    account_id: str,
    prefix: str,
) -> tuple[int, ...]:
    return (
        await session.scalar(
            select(func.count()).select_from(AccountModel).where(AccountModel.id == account_id)
        )
        or 0,
        await session.scalar(
            select(func.count())
            .select_from(HoldingModel)
            .where(HoldingModel.account_id == account_id)
        )
        or 0,
        await session.scalar(
            select(func.count())
            .select_from(InvestmentEventModel)
            .where(InvestmentEventModel.account_id == account_id)
        )
        or 0,
        await session.scalar(
            select(func.count())
            .select_from(InvestmentMovementModel)
            .where(InvestmentMovementModel.account_id == account_id)
        )
        or 0,
        await session.scalar(
            select(func.count())
            .select_from(TransactionModel)
            .where(TransactionModel.account_id == account_id)
        )
        or 0,
        await session.scalar(
            select(func.count())
            .select_from(PriceSnapshotModel)
            .where(PriceSnapshotModel.id.startswith(f"{prefix}-"))
        )
        or 0,
        await session.scalar(
            select(func.count())
            .select_from(ExchangeRateModel)
            .where(ExchangeRateModel.id.startswith(f"{prefix}-"))
        )
        or 0,
        await session.scalar(
            select(func.count())
            .select_from(LiabilityBalanceModel)
            .where(LiabilityBalanceModel.account_id == account_id)
        )
        or 0,
        await session.scalar(
            select(func.count())
            .select_from(AccountSnapshotModel)
            .where(AccountSnapshotModel.account_id == account_id)
        )
        or 0,
        await session.scalar(
            select(func.count())
            .select_from(AccountSnapshotItemModel)
            .join(
                AccountSnapshotModel,
                AccountSnapshotModel.id == AccountSnapshotItemModel.snapshot_id,
            )
            .where(AccountSnapshotModel.account_id == account_id)
        )
        or 0,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [AccountType.bank, AccountType.cash, AccountType.savings],
)
async def test_persisted_cash_account_balance_is_read_only(
    account_type: AccountType,
) -> None:
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
                    type=account_type,
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
                    _transaction(
                        transaction_id=f"{prefix}-income",
                        account_id=account_id,
                        amount="100.000000",
                        transaction_type=TransactionType.income,
                        classification=TransactionClassification.real_income,
                    ),
                    _transaction(
                        transaction_id=f"{prefix}-expense",
                        account_id=account_id,
                        amount="-25.000000",
                        transaction_type=TransactionType.expense,
                        classification=TransactionClassification.real_expense,
                    ),
                    _transaction(
                        transaction_id=f"{prefix}-internal",
                        account_id=account_id,
                        amount="-1.000000",
                        transaction_type=TransactionType.transfer,
                        classification=TransactionClassification.internal_transfer,
                    ),
                    _transaction(
                        transaction_id=f"{prefix}-investment",
                        account_id=account_id,
                        amount="-1.000000",
                        transaction_type=TransactionType.transfer,
                        classification=TransactionClassification.investment_transfer,
                    ),
                    _transaction(
                        transaction_id=f"{prefix}-exchange",
                        account_id=account_id,
                        amount="-1.000000",
                        transaction_type=TransactionType.transfer,
                        classification=TransactionClassification.cash_exchange,
                    ),
                    _transaction(
                        transaction_id=f"{prefix}-credit-card",
                        account_id=account_id,
                        amount="-1.000000",
                        transaction_type=TransactionType.transfer,
                        classification=TransactionClassification.credit_card_payment,
                    ),
                    _transaction(
                        transaction_id=f"{prefix}-loan",
                        account_id=account_id,
                        amount="-1.000000",
                        transaction_type=TransactionType.transfer,
                        classification=TransactionClassification.loan_repayment,
                    ),
                ]
            )
            await session.commit()

        async with AsyncSession(engine) as session:
            before = await _snapshot_counts(session)
            before_transactions = tuple(
                (
                    transaction.id,
                    transaction.amount,
                    transaction.classification,
                    transaction.description,
                    transaction.updated_at,
                )
                for transaction in await session.scalars(
                    select(TransactionModel)
                    .where(TransactionModel.account_id == account_id)
                    .order_by(TransactionModel.id)
                )
            )
            first = await AccountSnapshotEvidenceService(session).build(_command(account_id))
            second = await AccountSnapshotEvidenceService(session).build(_command(account_id))
            assert first == second
            assert first.valuation.cash_value == Decimal("70.000000")
            assert first.valuation.total_value == Decimal("70.000000")
            assert first.valuation.liabilities_value == Decimal(0)
            assert first.valuation.liabilities_value_by_currency == ()
            assert first.net_deposits == UnsupportedSnapshotMetric(
                SnapshotMetricUnsupportedReason.external_cash_flow_classification_unavailable
            )
            assert first.fees == UnsupportedSnapshotMetric(
                SnapshotMetricUnsupportedReason.fee_classification_unavailable
            )
            assert first.taxes == UnsupportedSnapshotMetric(
                SnapshotMetricUnsupportedReason.tax_classification_unavailable
            )
            assert first.realized_pnl == UnsupportedSnapshotMetric(
                SnapshotMetricUnsupportedReason.realized_pnl_evidence_unavailable
            )
            assert first.unrealized_pnl == ExactSnapshotMetric(Decimal(0), ())
            assert await _snapshot_counts(session) == before
            assert (
                tuple(
                    (
                        transaction.id,
                        transaction.amount,
                        transaction.classification,
                        transaction.description,
                        transaction.updated_at,
                    )
                    for transaction in await session.scalars(
                        select(TransactionModel)
                        .where(TransactionModel.account_id == account_id)
                        .order_by(TransactionModel.id)
                    )
                )
                == before_transactions
            )
            await session.rollback()
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_persisted_cash_output_currency_conversion_is_exact_and_read_only() -> None:
    prefix = "k5c2-cash"
    await _cleanup(prefix)
    account_id = f"{prefix}-account"
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                AccountModel(
                    id=account_id,
                    name="USD cash",
                    type=AccountType.bank,
                    currency="USD",
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
                    _transaction(
                        transaction_id=f"{prefix}-usd",
                        account_id=account_id,
                        amount="100.000000",
                        transaction_type=TransactionType.income,
                        classification=TransactionClassification.real_income,
                        currency="USD",
                    ),
                    _transaction(
                        transaction_id=f"{prefix}-eur",
                        account_id=account_id,
                        amount="20.000000",
                        transaction_type=TransactionType.income,
                        classification=TransactionClassification.real_income,
                        currency="EUR",
                    ),
                    ExchangeRateModel(
                        id=f"{prefix}-usd-eur",
                        from_currency="USD",
                        to_currency="EUR",
                        rate=Decimal("0.90000000"),
                        date=SNAPSHOT_AT,
                        source=ExchangeRateSource.ecb,
                        created_at=SNAPSHOT_AT,
                    ),
                    ExchangeRateModel(
                        id=f"{prefix}-eur-usd",
                        from_currency="EUR",
                        to_currency="USD",
                        rate=Decimal("1.10000000"),
                        date=SNAPSHOT_AT,
                        source=ExchangeRateSource.ecb,
                        created_at=SNAPSHOT_AT,
                    ),
                ]
            )
            await session.commit()

        async with AsyncSession(engine) as session:
            before = await _evidence_state_counts(
                session,
                account_id=account_id,
                prefix=prefix,
            )
            default = await AccountSnapshotEvidenceService(session).build(_command(account_id))
            explicit_account_currency = await AccountSnapshotEvidenceService(session).build(
                _command(account_id, output_currency="USD")
            )
            converted = await AccountSnapshotEvidenceService(session).build(
                _command(account_id, output_currency="EUR")
            )

            assert default == explicit_account_currency
            assert converted.valuation.currency == "EUR"
            assert converted.valuation.cash_value == Decimal("110.000000")
            assert converted.valuation.cash_value_by_currency == (
                CurrencyAmount("EUR", Decimal("20.000000")),
                CurrencyAmount("USD", Decimal("100.000000")),
            )
            assert converted.selected_snapshot_exchange_rate_ids == (f"{prefix}-usd-eur",)
            assert converted.selected_historical_exchange_rate_ids == ()
            assert (
                await _evidence_state_counts(
                    session,
                    account_id=account_id,
                    prefix=prefix,
                )
                == before
            )
            await session.rollback()
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [AccountType.broker, AccountType.exchange, AccountType.crypto_wallet],
)
async def test_persisted_investment_account_selects_price_and_fx_read_only(
    account_type: AccountType,
) -> None:
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
                    type=account_type,
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
            assert result.valuation.liabilities_value == Decimal(0)
            assert result.valuation.liabilities_value_by_currency == ()
            assert result.net_deposits == ExactSnapshotMetric(
                Decimal("200.000000"),
                (CurrencyAmount("EUR", Decimal("10.000000")),),
            )
            assert result.unrealized_pnl == ExactSnapshotMetric(
                Decimal("250.000000"),
                (CurrencyAmount("EUR", Decimal("10.000000")),),
            )
            assert result.selected_price_ids == (f"{prefix}-price",)
            assert result.selected_snapshot_exchange_rate_ids == (f"{prefix}-snapshot-rate",)
            assert result.selected_historical_exchange_rate_ids == (f"{prefix}-event-rate",)
            assert await _snapshot_counts(session) == before
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_persisted_mixed_currency_investment_uses_snapshot_and_event_time_fx() -> None:
    prefix = "k5c2-investment"
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
                    name="Mixed broker",
                    type=AccountType.broker,
                    currency="USD",
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
                    symbol="K5C2",
                    isin=None,
                    name="K5C2",
                    asset_type=AssetType.stock,
                    currency="GBP",
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            await session.flush()
            session.add(
                AssetListingModel(
                    id=listing_id,
                    asset_id=asset_id,
                    symbol="K5C2",
                    exchange="mixed",
                    mic=None,
                    currency="GBP",
                    country=None,
                    provider=PriceSource.broker,
                    provider_symbol="K5C2",
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
                    symbol="K5C2",
                    name="K5C2",
                    asset_type=AssetType.stock,
                    quantity=Decimal("2"),
                    avg_buy_price=Decimal("10"),
                    currency="USD",
                    current_price=None,
                    current_value=None,
                    unrealized_pnl=None,
                    realized_pnl=None,
                    calculated_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            session.add(
                PriceSnapshotModel(
                    id=f"{prefix}-price-gbp",
                    asset_id=asset_id,
                    listing_id=listing_id,
                    price=Decimal("15"),
                    currency="GBP",
                    source=PriceSource.broker,
                    timestamp=SNAPSHOT_AT,
                    created_at=SNAPSHOT_AT,
                )
            )
            session.add_all(
                [
                    ExchangeRateModel(
                        id=f"{prefix}-usd-event",
                        from_currency="USD",
                        to_currency="EUR",
                        rate=Decimal("0.80000000"),
                        date=EVENT_AT,
                        source=ExchangeRateSource.ecb,
                        created_at=EVENT_AT,
                    ),
                    ExchangeRateModel(
                        id=f"{prefix}-usd-snapshot",
                        from_currency="USD",
                        to_currency="EUR",
                        rate=Decimal("0.90000000"),
                        date=SNAPSHOT_AT,
                        source=ExchangeRateSource.ecb,
                        created_at=SNAPSHOT_AT,
                    ),
                    ExchangeRateModel(
                        id=f"{prefix}-gbp-snapshot",
                        from_currency="GBP",
                        to_currency="EUR",
                        rate=Decimal("1.20000000"),
                        date=SNAPSHOT_AT,
                        source=ExchangeRateSource.ecb,
                        created_at=SNAPSHOT_AT,
                    ),
                    ExchangeRateModel(
                        id=f"{prefix}-chf-snapshot",
                        from_currency="CHF",
                        to_currency="EUR",
                        rate=Decimal("1.05000000"),
                        date=SNAPSHOT_AT,
                        source=ExchangeRateSource.ecb,
                        created_at=SNAPSHOT_AT,
                    ),
                ]
            )
            session.add_all(
                [
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
                    ),
                    InvestmentEventModel(
                        id=f"{prefix}-interest",
                        account_id=account_id,
                        type=InvestmentEventType.interest,
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
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    InvestmentMovementModel(
                        id=f"{prefix}-cash-usd",
                        event_id=f"{prefix}-deposit",
                        account_id=account_id,
                        asset_id=None,
                        listing_id=None,
                        kind=InvestmentMovementKind.cash,
                        direction=MovementDirection.incoming,
                        quantity=Decimal("10"),
                        currency="USD",
                        price_per_unit=None,
                        value_amount=Decimal("10"),
                        value_currency="USD",
                        source_symbol=None,
                        source_asset_type=None,
                        note=None,
                        created_at=EVENT_AT,
                        updated_at=EVENT_AT,
                    ),
                    InvestmentMovementModel(
                        id=f"{prefix}-cash-chf",
                        event_id=f"{prefix}-interest",
                        account_id=account_id,
                        asset_id=None,
                        listing_id=None,
                        kind=InvestmentMovementKind.cash,
                        direction=MovementDirection.incoming,
                        quantity=Decimal("10"),
                        currency="CHF",
                        price_per_unit=None,
                        value_amount=Decimal("10"),
                        value_currency="CHF",
                        source_symbol=None,
                        source_asset_type=None,
                        note=None,
                        created_at=EVENT_AT,
                        updated_at=EVENT_AT,
                    ),
                ]
            )
            await session.commit()

        async with AsyncSession(engine) as session:
            before = await _evidence_state_counts(
                session,
                account_id=account_id,
                prefix=prefix,
            )
            result = await AccountSnapshotEvidenceService(session).build(
                _command(account_id, output_currency="EUR")
            )

            assert result.valuation.currency == "EUR"
            assert result.valuation.investment_value == Decimal("36.000000")
            assert result.valuation.investment_cost_basis == Decimal("18.000000")
            assert result.valuation.cash_value == Decimal("19.500000")
            assert result.valuation.total_value == Decimal("55.500000")
            assert result.valuation.cash_value_by_currency == (
                CurrencyAmount("CHF", Decimal("10.000000")),
                CurrencyAmount("USD", Decimal("10.000000")),
            )
            assert result.valuation.investment_value_by_currency == (
                CurrencyAmount("GBP", Decimal("30.0000000000")),
            )
            assert result.valuation.investment_cost_basis_by_currency == (
                CurrencyAmount("USD", Decimal("20.0000000000")),
            )
            assert result.net_deposits == ExactSnapshotMetric(
                Decimal("8.000000"),
                (CurrencyAmount("USD", Decimal("10.000000")),),
            )
            assert result.selected_snapshot_exchange_rate_ids == (
                f"{prefix}-chf-snapshot",
                f"{prefix}-gbp-snapshot",
                f"{prefix}-usd-snapshot",
            )
            assert result.selected_historical_exchange_rate_ids == (f"{prefix}-usd-event",)
            assert (
                await _evidence_state_counts(
                    session,
                    account_id=account_id,
                    prefix=prefix,
                )
                == before
            )
            await session.rollback()
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
async def test_persisted_liability_converts_to_output_currency_read_only() -> None:
    prefix = "k5c2-liability"
    await _cleanup(prefix)
    account_id = f"{prefix}-account"
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                AccountModel(
                    id=account_id,
                    name="USD loan",
                    type=AccountType.loan,
                    currency="USD",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            await session.flush()
            session.add_all(
                [
                    LiabilityBalanceModel(
                        id=f"{prefix}-balance",
                        account_id=account_id,
                        effective_at=EVENT_AT,
                        currency="USD",
                        outstanding_principal=Decimal("100.000000"),
                        accrued_interest=Decimal("10.000000"),
                        fees_outstanding=Decimal("5.000000"),
                        total_outstanding=Decimal("115.000000"),
                        source=LiabilityBalanceSource.statement,
                        external_id="statement-1",
                        created_at=EVENT_AT,
                    ),
                    ExchangeRateModel(
                        id=f"{prefix}-usd-eur",
                        from_currency="USD",
                        to_currency="EUR",
                        rate=Decimal("0.90000000"),
                        date=SNAPSHOT_AT,
                        source=ExchangeRateSource.ecb,
                        created_at=SNAPSHOT_AT,
                    ),
                ]
            )
            await session.commit()

        async with AsyncSession(engine) as session:
            before = await _evidence_state_counts(
                session,
                account_id=account_id,
                prefix=prefix,
            )
            result = await AccountSnapshotEvidenceService(session).build(
                _command(account_id, output_currency="EUR")
            )

            assert result.valuation.currency == "EUR"
            assert result.valuation.liabilities_value == Decimal("103.500000")
            assert result.valuation.total_value == Decimal("-103.500000")
            assert result.valuation.liabilities_value_by_currency == (
                CurrencyAmount("USD", Decimal("115.000000")),
            )
            assert result.selected_liability_balance_id == f"{prefix}-balance"
            assert result.selected_liability_effective_at == EVENT_AT
            assert result.selected_liability_source is LiabilityBalanceSource.statement
            assert result.selected_snapshot_exchange_rate_ids == (f"{prefix}-usd-eur",)
            assert result.selected_historical_exchange_rate_ids == ()
            assert (
                await _evidence_state_counts(
                    session,
                    account_id=account_id,
                    prefix=prefix,
                )
                == before
            )
            await session.rollback()
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_persisted_liability_currency_corruption_fails_without_mutation() -> None:
    prefix = "k5c2-liability-corrupt"
    await _cleanup(prefix)
    account_id = f"{prefix}-account"
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                AccountModel(
                    id=account_id,
                    name="USD loan",
                    type=AccountType.loan,
                    currency="USD",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            await session.flush()
            session.add(
                LiabilityBalanceModel(
                    id=f"{prefix}-balance",
                    account_id=account_id,
                    effective_at=EVENT_AT,
                    currency="GBP",
                    outstanding_principal=Decimal("100.000000"),
                    accrued_interest=Decimal("0.000000"),
                    fees_outstanding=Decimal("0.000000"),
                    total_outstanding=Decimal("100.000000"),
                    source=LiabilityBalanceSource.statement,
                    external_id="corrupt",
                    created_at=EVENT_AT,
                )
            )
            await session.commit()

        async with AsyncSession(engine) as session:
            before = await _evidence_state_counts(
                session,
                account_id=account_id,
                prefix=prefix,
            )
            with pytest.raises(AccountSnapshotEvidenceStateError):
                await AccountSnapshotEvidenceService(session).build(
                    _command(account_id, output_currency="EUR")
                )
            assert (
                await _evidence_state_counts(
                    session,
                    account_id=account_id,
                    prefix=prefix,
                )
                == before
            )
            await session.rollback()
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rate_case",
    ["missing", "reverse", "chained", "future", "ambiguous"],
)
async def test_persisted_output_currency_rate_failures_write_nothing(
    rate_case: str,
) -> None:
    prefix = f"k5c2-rate-{rate_case}"
    await _cleanup(prefix)
    account_id = f"{prefix}-account"
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                AccountModel(
                    id=account_id,
                    name="XUS cash",
                    type=AccountType.bank,
                    currency="XUS",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            session.add(
                _transaction(
                    transaction_id=f"{prefix}-transaction",
                    account_id=account_id,
                    amount="100.000000",
                    transaction_type=TransactionType.income,
                    classification=TransactionClassification.real_income,
                    currency="XUS",
                )
            )
            rates: list[ExchangeRateModel] = []
            if rate_case == "reverse":
                rates.append(
                    ExchangeRateModel(
                        id=f"{prefix}-reverse",
                        from_currency="EUR",
                        to_currency="XUS",
                        rate=Decimal("1.10000000"),
                        date=SNAPSHOT_AT,
                        source=ExchangeRateSource.ecb,
                        created_at=SNAPSHOT_AT,
                    )
                )
            elif rate_case == "chained":
                rates.extend(
                    [
                        ExchangeRateModel(
                            id=f"{prefix}-usd-czk",
                            from_currency="XUS",
                            to_currency="CZK",
                            rate=Decimal("20.00000000"),
                            date=SNAPSHOT_AT,
                            source=ExchangeRateSource.ecb,
                            created_at=SNAPSHOT_AT,
                        ),
                        ExchangeRateModel(
                            id=f"{prefix}-czk-eur",
                            from_currency="CZK",
                            to_currency="EUR",
                            rate=Decimal("0.04000000"),
                            date=SNAPSHOT_AT,
                            source=ExchangeRateSource.ecb,
                            created_at=SNAPSHOT_AT,
                        ),
                    ]
                )
            elif rate_case == "future":
                rates.append(
                    ExchangeRateModel(
                        id=f"{prefix}-future",
                        from_currency="XUS",
                        to_currency="EUR",
                        rate=Decimal("0.90000000"),
                        date=datetime(2026, 7, 28),
                        source=ExchangeRateSource.ecb,
                        created_at=SNAPSHOT_AT,
                    )
                )
            elif rate_case == "ambiguous":
                rates.extend(
                    [
                        ExchangeRateModel(
                            id=f"{prefix}-ecb",
                            from_currency="XUS",
                            to_currency="EUR",
                            rate=Decimal("0.90000000"),
                            date=SNAPSHOT_AT,
                            source=ExchangeRateSource.ecb,
                            created_at=SNAPSHOT_AT,
                        ),
                        ExchangeRateModel(
                            id=f"{prefix}-manual",
                            from_currency="XUS",
                            to_currency="EUR",
                            rate=Decimal("0.90000000"),
                            date=SNAPSHOT_AT,
                            source=ExchangeRateSource.manual,
                            created_at=SNAPSHOT_AT,
                        ),
                    ]
                )
            session.add_all(rates)
            await session.commit()

        async with AsyncSession(engine) as session:
            before = await _evidence_state_counts(
                session,
                account_id=account_id,
                prefix=prefix,
            )
            with pytest.raises(AccountSnapshotEvidenceStateError):
                await AccountSnapshotEvidenceService(session).build(
                    _command(account_id, output_currency="EUR")
                )
            assert (
                await _evidence_state_counts(
                    session,
                    account_id=account_id,
                    prefix=prefix,
                )
                == before
            )
            await session.rollback()
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [AccountType.credit_card, AccountType.loan, AccountType.mortgage],
)
async def test_persisted_liability_account_fails_before_projection_without_mutation(
    account_type: AccountType,
) -> None:
    prefix = "i5b-liability"
    await _cleanup(prefix)
    account_id = f"{prefix}-account"
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                AccountModel(
                    id=account_id,
                    name="Liability from account name",
                    type=account_type,
                    currency="CZK",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=EVENT_AT,
                    updated_at=EVENT_AT,
                )
            )
            await session.flush()
            session.add_all(
                [
                    TransactionModel(
                        id=f"{prefix}-negative-one",
                        account_id=account_id,
                        date=EVENT_AT,
                        booking_date=None,
                        amount=Decimal("-100.000000"),
                        currency="CZK",
                        reporting_amount=None,
                        reporting_currency=None,
                        type=TransactionType.expense,
                        classification=TransactionClassification.real_expense,
                        description="Outstanding principal",
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
                        id=f"{prefix}-negative-two",
                        account_id=account_id,
                        date=EVENT_AT,
                        booking_date=None,
                        amount=Decimal("-50.000000"),
                        currency="CZK",
                        reporting_amount=None,
                        reporting_currency=None,
                        type=TransactionType.expense,
                        classification=TransactionClassification.real_expense,
                        description=account_type.value,
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
            before_transactions = tuple(
                (
                    transaction.id,
                    transaction.amount,
                    transaction.description,
                    transaction.updated_at,
                )
                for transaction in await session.scalars(
                    select(TransactionModel)
                    .where(TransactionModel.account_id == account_id)
                    .order_by(TransactionModel.id)
                )
            )
            before_holdings = (
                await session.scalar(
                    select(func.count())
                    .select_from(HoldingModel)
                    .where(HoldingModel.account_id == account_id)
                )
                or 0
            )
            for _ in range(2):
                with pytest.raises(
                    AccountSnapshotEvidenceStateError,
                    match=r"Persisted evidence cannot produce a complete account snapshot\.",
                ):
                    await AccountSnapshotEvidenceService(session).build(_command(account_id))
            assert await _snapshot_counts(session) == before
            assert (
                tuple(
                    (
                        transaction.id,
                        transaction.amount,
                        transaction.description,
                        transaction.updated_at,
                    )
                    for transaction in await session.scalars(
                        select(TransactionModel)
                        .where(TransactionModel.account_id == account_id)
                        .order_by(TransactionModel.id)
                    )
                )
                == before_transactions
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(HoldingModel)
                    .where(HoldingModel.account_id == account_id)
                )
                or 0
            ) == before_holdings
    finally:
        await engine.dispose()
        await _cleanup(prefix)
