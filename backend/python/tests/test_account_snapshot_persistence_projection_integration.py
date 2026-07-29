from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountType,
    AssetType,
    ExchangeRateSource,
    LiabilityBalanceSource,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.db.url import normalize_database_url
from app.modules.snapshots.account_projection import (
    AccountSnapshotProjectionInput,
    LiabilityBalanceEvidence,
    SelectedExchangeRateEvidence,
    SelectedPriceEvidence,
    SnapshotHoldingEvidence,
    build_account_snapshot_projection,
)
from app.modules.snapshots.evidence_service import (
    CompleteAccountSnapshotEvidence,
    ExactSnapshotMetric,
)
from app.modules.snapshots.persistence_projection import (
    AccountSnapshotPersistenceMetadata,
    ExpectedAccountSnapshotPersistence,
    build_account_snapshot_persistence_projection,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")

SNAPSHOT_AT = datetime(2033, 8, 1, 0, 0)
CREATED_AT = datetime(2033, 8, 1, 0, 1)


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL))


def _rate(
    base: str,
    quote: str,
    rate: Decimal,
    *,
    rate_id: str,
) -> SelectedExchangeRateEvidence:
    return SelectedExchangeRateEvidence(
        rate_id=rate_id,
        base_currency=base,
        quote_currency=quote,
        rate=rate,
        source=ExchangeRateSource.ecb,
        timestamp=SNAPSHOT_AT,
    )


def _investment_projection(
    prefix: str,
    *,
    output_currency: str = "EUR",
) -> ExpectedAccountSnapshotPersistence:
    account_id = f"{prefix}-account"
    asset_id = f"{prefix}-asset"
    listing_id = f"{prefix}-listing"
    valuation = build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id=account_id,
            account_type=AccountType.broker,
            account_currency="USD",
            output_currency=output_currency,
            snapshot_timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.day,
            source=SnapshotSource.manual_recalculation,
            calculation_version=1,
            holdings=(
                SnapshotHoldingEvidence(
                    holding_id=f"{prefix}-holding",
                    account_id=account_id,
                    asset_id=asset_id,
                    listing_id=listing_id,
                    listing_asset_id=asset_id,
                    symbol="MIXED",
                    asset_type=AssetType.stock,
                    quantity=Decimal("2"),
                    average_buy_price=Decimal("10"),
                    cost_currency="USD",
                ),
            ),
            prices=(
                SelectedPriceEvidence(
                    price_id=f"{prefix}-price",
                    asset_id=asset_id,
                    listing_id=listing_id,
                    symbol="MIXED",
                    price=Decimal("15"),
                    currency="GBP",
                    source=PriceSource.broker,
                    timestamp=SNAPSHOT_AT,
                ),
            ),
            exchange_rates=(
                _rate(
                    "GBP",
                    output_currency,
                    Decimal("1.20000000"),
                    rate_id=f"{prefix}-gbp-output",
                ),
                _rate(
                    "USD",
                    output_currency,
                    Decimal("0.90000000"),
                    rate_id=f"{prefix}-usd-output",
                ),
            ),
            cash_balances=(),
            liabilities=(),
        )
    )
    zero = ExactSnapshotMetric(Decimal(0), ())
    evidence = CompleteAccountSnapshotEvidence(
        valuation=valuation,
        net_deposits=zero,
        realized_pnl=zero,
        unrealized_pnl=ExactSnapshotMetric(Decimal("18"), None),
        fees=zero,
        taxes=zero,
        selected_price_ids=(f"{prefix}-price",),
        selected_snapshot_exchange_rate_ids=(
            f"{prefix}-gbp-output",
            f"{prefix}-usd-output",
        ),
        selected_historical_exchange_rate_ids=(),
    )
    return build_account_snapshot_persistence_projection(
        evidence,
        AccountSnapshotPersistenceMetadata(
            calculated_at=CREATED_AT,
            created_at=CREATED_AT,
            is_recalculated=True,
        ),
    )


def _liability_projection(prefix: str) -> ExpectedAccountSnapshotPersistence:
    account_id = f"{prefix}-account"
    valuation = build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id=account_id,
            account_type=AccountType.loan,
            account_currency="USD",
            output_currency="EUR",
            snapshot_timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.day,
            source=SnapshotSource.manual_recalculation,
            calculation_version=1,
            holdings=(),
            prices=(),
            exchange_rates=(
                _rate(
                    "USD",
                    "EUR",
                    Decimal("0.90000000"),
                    rate_id=f"{prefix}-usd-eur",
                ),
            ),
            cash_balances=(),
            liabilities=(
                LiabilityBalanceEvidence(
                    liability_id=f"{prefix}-liability",
                    account_id=account_id,
                    currency="USD",
                    amount=Decimal("100"),
                    timestamp=SNAPSHOT_AT,
                ),
            ),
        )
    )
    zero = ExactSnapshotMetric(Decimal(0), ())
    evidence = CompleteAccountSnapshotEvidence(
        valuation=valuation,
        net_deposits=zero,
        realized_pnl=zero,
        unrealized_pnl=zero,
        fees=zero,
        taxes=zero,
        selected_price_ids=(),
        selected_snapshot_exchange_rate_ids=(f"{prefix}-usd-eur",),
        selected_historical_exchange_rate_ids=(),
        selected_liability_balance_id=f"{prefix}-liability",
        selected_liability_effective_at=SNAPSHOT_AT,
        selected_liability_source=LiabilityBalanceSource.statement,
    )
    return build_account_snapshot_persistence_projection(
        evidence,
        AccountSnapshotPersistenceMetadata(
            calculated_at=CREATED_AT,
            created_at=CREATED_AT,
            is_recalculated=True,
        ),
    )


def _account(account_id: str, account_type: AccountType) -> AccountModel:
    return AccountModel(
        id=account_id,
        name="Physical contract",
        type=account_type,
        currency="USD",
        color=None,
        notes=None,
        is_archived=False,
        archived_at=None,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
    )


def _asset_rows(prefix: str) -> tuple[AssetModel, AssetListingModel]:
    asset_id = f"{prefix}-asset"
    return (
        AssetModel(
            id=asset_id,
            symbol="MIXED",
            isin=None,
            name="Mixed asset",
            asset_type=AssetType.stock,
            currency="GBP",
            created_at=SNAPSHOT_AT,
            updated_at=SNAPSHOT_AT,
        ),
        AssetListingModel(
            id=f"{prefix}-listing",
            asset_id=asset_id,
            symbol="MIXED",
            exchange="TEST",
            mic=None,
            currency="GBP",
            country=None,
            provider=PriceSource.broker,
            provider_symbol="MIXED",
            is_primary=True,
            created_at=SNAPSHOT_AT,
            updated_at=SNAPSHOT_AT,
        ),
    )


@pytest.mark.asyncio
async def test_mixed_investment_projection_round_trips_exact_physical_rows() -> None:
    prefix = "k5c3-investment"
    projection = _investment_projection(prefix)
    engine = _engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.begin()
        asset, listing = _asset_rows(prefix)
        session.add(_account(f"{prefix}-account", AccountType.broker))
        session.add(asset)
        await session.flush()
        session.add(listing)
        session.add(AccountSnapshotModel(**projection.snapshot.model_values()))
        await session.flush()
        session.add_all(
            AccountSnapshotItemModel(**item.model_values()) for item in projection.items
        )
        await session.flush()
        session.expire_all()

        row = await session.get(AccountSnapshotModel, projection.snapshot.id)
        item = await session.get(AccountSnapshotItemModel, projection.items[0].id)
        assert row is not None
        assert item is not None
        assert row.currency == "EUR"
        assert row.investment_value == Decimal("36.000000")
        assert row.investment_cost_basis == Decimal("18.000000")
        assert row.unrealized_pnl_value == Decimal("18.000000")
        assert row.investment_value_by_currency == {"GBP": "30.0000000000"}
        assert row.investment_cost_basis_by_currency == {"USD": "20.0000000000"}
        assert item.price_currency == "GBP"
        assert item.value_currency == "GBP"
        assert item.native_value == Decimal("30.0000000000")
        assert item.value == Decimal("36.000000")
        assert item.native_cost_currency == "USD"
        assert item.native_cost_basis == Decimal("20.0000000000")
        assert item.cost_currency == "EUR"
        assert item.cost_basis == Decimal("18.0000000000")
        assert row.exchange_rates == projection.snapshot.exchange_rates.to_json()
        await session.rollback()
    async with AsyncSession(engine) as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AccountSnapshotModel)
                .where(AccountSnapshotModel.id == projection.snapshot.id)
            )
            == 0
        )
    await engine.dispose()


@pytest.mark.asyncio
async def test_mixed_liability_projection_round_trips_without_synthetic_items() -> None:
    prefix = "k5c3-liability"
    projection = _liability_projection(prefix)
    engine = _engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        await session.begin()
        session.add(_account(f"{prefix}-account", AccountType.loan))
        session.add(AccountSnapshotModel(**projection.snapshot.model_values()))
        await session.flush()
        session.expire_all()

        row = await session.get(AccountSnapshotModel, projection.snapshot.id)
        assert row is not None
        assert row.currency == "EUR"
        assert row.liabilities_value == Decimal("90.000000")
        assert row.total_value == Decimal("-90.000000")
        assert row.exchange_rates == projection.snapshot.exchange_rates.to_json()
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AccountSnapshotItemModel)
                .where(AccountSnapshotItemModel.snapshot_id == row.id)
            )
            == 0
        )
        await session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_output_currency_is_a_distinct_physical_unique_identity() -> None:
    prefix = "k5c3-identity"
    eur = _investment_projection(prefix, output_currency="EUR")
    czk = _investment_projection(prefix, output_currency="CZK")
    engine = _engine()
    async with AsyncSession(engine) as session:
        await session.begin()
        asset, listing = _asset_rows(prefix)
        session.add(_account(f"{prefix}-account", AccountType.broker))
        session.add(asset)
        await session.flush()
        session.add(listing)
        session.add_all(
            (
                AccountSnapshotModel(**eur.snapshot.model_values()),
                AccountSnapshotModel(**czk.snapshot.model_values()),
            )
        )
        await session.flush()
        session.add_all(
            AccountSnapshotItemModel(**item.model_values())
            for projection in (eur, czk)
            for item in projection.items
        )
        await session.flush()

        assert eur.snapshot.id != czk.snapshot.id
        assert eur.items[0].id != czk.items[0].id
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AccountSnapshotModel)
                .where(AccountSnapshotModel.account_id == f"{prefix}-account")
            )
            == 2
        )
        await session.rollback()
    await engine.dispose()
