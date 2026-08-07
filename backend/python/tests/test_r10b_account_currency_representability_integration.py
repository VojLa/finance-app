from __future__ import annotations

import os
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.accounts import AccountModel
from app.db.models.enums import (
    AccountType,
    AssetType,
    ExchangeRateSource,
    LiabilityBalanceSource,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.snapshots import AccountSnapshotModel
from app.db.url import normalize_database_url
from app.modules.snapshots.account_projection import (
    AccountSnapshotProjectionInput,
    CashBalanceEvidence,
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
    ExpectedAccountSnapshotRow,
    build_account_snapshot_persistence_projection,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")

PREFIX = "r10b-representability"
SNAPSHOT_AT = datetime(2036, 1, 11, 12, 0)
CREATED_AT = datetime(2036, 1, 11, 12, 0, 0, 123000)


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL))


def _rate(base: str, value: str, *, suffix: str) -> SelectedExchangeRateEvidence:
    return SelectedExchangeRateEvidence(
        rate_id=f"{PREFIX}-{suffix}",
        base_currency=base,
        quote_currency="CZK",
        rate=Decimal(value),
        source=ExchangeRateSource.cnb,
        timestamp=SNAPSHOT_AT,
    )


def _persist(
    valuation,
    *,
    price_ids: tuple[str, ...] = (),
    liability_id: str | None = None,
) -> ExpectedAccountSnapshotRow:
    zero = ExactSnapshotMetric(Decimal(0), ())
    evidence = CompleteAccountSnapshotEvidence(
        valuation=valuation,
        net_deposits=zero,
        realized_pnl=zero,
        unrealized_pnl=ExactSnapshotMetric(
            valuation.investment_value - valuation.investment_cost_basis,
            None if valuation.items else (),
        ),
        fees=zero,
        taxes=zero,
        selected_price_ids=price_ids,
        selected_snapshot_exchange_rate_ids=tuple(
            rate.rate_id for rate in valuation.exchange_rates
        ),
        selected_historical_exchange_rate_ids=(),
        selected_liability_balance_id=liability_id,
        selected_liability_effective_at=SNAPSHOT_AT if liability_id else None,
        selected_liability_source=LiabilityBalanceSource.statement if liability_id else None,
    )
    return build_account_snapshot_persistence_projection(
        evidence,
        AccountSnapshotPersistenceMetadata(
            calculated_at=CREATED_AT,
            created_at=CREATED_AT,
            is_recalculated=True,
        ),
    ).snapshot


def _investment(
    suffix: str,
    *,
    price_currency: str,
    cost_currency: str,
    rates: tuple[SelectedExchangeRateEvidence, ...],
) -> ExpectedAccountSnapshotRow:
    account_id = f"{PREFIX}-{suffix}"
    price_id = f"{account_id}-price"
    valuation = build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id=account_id,
            account_type=AccountType.broker,
            account_currency="EUR",
            output_currency="CZK",
            snapshot_timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.manual_recalculation,
            calculation_version=1,
            holdings=(
                SnapshotHoldingEvidence(
                    holding_id=f"{account_id}-holding",
                    account_id=account_id,
                    asset_id=f"{account_id}-asset",
                    listing_id=f"{account_id}-listing",
                    listing_asset_id=f"{account_id}-asset",
                    symbol="ASSET",
                    asset_type=AssetType.stock,
                    quantity=Decimal("2"),
                    average_buy_price=Decimal("80"),
                    cost_currency=cost_currency,
                ),
            ),
            prices=(
                SelectedPriceEvidence(
                    price_id=price_id,
                    asset_id=f"{account_id}-asset",
                    listing_id=f"{account_id}-listing",
                    symbol="ASSET",
                    price=Decimal("100"),
                    currency=price_currency,
                    source=PriceSource.twelve_data,
                    timestamp=SNAPSHOT_AT,
                ),
            ),
            exchange_rates=rates,
            cash_balances=(),
            liabilities=(),
        )
    )
    return _persist(valuation, price_ids=(price_id,))


def _cash() -> ExpectedAccountSnapshotRow:
    account_id = f"{PREFIX}-a"
    valuation = build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id=account_id,
            account_type=AccountType.bank,
            account_currency="CZK",
            output_currency="CZK",
            snapshot_timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.manual_recalculation,
            calculation_version=1,
            holdings=(),
            prices=(),
            exchange_rates=(),
            cash_balances=(
                CashBalanceEvidence(
                    balance_id=f"{account_id}-cash",
                    account_id=account_id,
                    currency="CZK",
                    amount=Decimal("1000.000000"),
                    timestamp=SNAPSHOT_AT,
                ),
            ),
            liabilities=(),
        )
    )
    return _persist(valuation)


def _liability() -> ExpectedAccountSnapshotRow:
    account_id = f"{PREFIX}-d"
    liability_id = f"{account_id}-liability"
    valuation = build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id=account_id,
            account_type=AccountType.loan,
            account_currency="EUR",
            output_currency="CZK",
            snapshot_timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.manual_recalculation,
            calculation_version=1,
            holdings=(),
            prices=(),
            exchange_rates=(_rate("EUR", "25.00000000", suffix="d-eur-czk"),),
            cash_balances=(),
            liabilities=(
                LiabilityBalanceEvidence(
                    liability_id=liability_id,
                    account_id=account_id,
                    currency="EUR",
                    amount=Decimal("100.000000"),
                    timestamp=SNAPSHOT_AT,
                ),
            ),
        )
    )
    return _persist(valuation, liability_id=liability_id)


@pytest.mark.asyncio
async def test_postgresql_proves_account_currency_presentation_is_not_representable() -> None:
    rows = (
        _cash(),
        _investment(
            "b",
            price_currency="EUR",
            cost_currency="EUR",
            rates=(_rate("EUR", "25.00000000", suffix="b-eur-czk"),),
        ),
        _investment(
            "c",
            price_currency="USD",
            cost_currency="EUR",
            rates=(
                _rate("USD", "23.00000000", suffix="c-usd-czk"),
                _rate("EUR", "25.00000000", suffix="c-eur-czk"),
            ),
        ),
        _liability(),
    )
    account_types = (
        AccountType.bank,
        AccountType.broker,
        AccountType.broker,
        AccountType.loan,
    )
    account_currencies = ("CZK", "EUR", "EUR", "EUR")
    engine = _engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await session.execute(
                delete(AccountSnapshotModel).where(
                    AccountSnapshotModel.account_id.startswith(PREFIX)
                )
            )
            await session.execute(delete(AccountModel).where(AccountModel.id.startswith(PREFIX)))
            session.add_all(
                AccountModel(
                    id=row.account_id,
                    name=f"R10-B {index}",
                    type=account_type,
                    currency=account_currency,
                    color=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=SNAPSHOT_AT,
                    updated_at=SNAPSHOT_AT,
                    notes=None,
                )
                for index, (row, account_type, account_currency) in enumerate(
                    zip(rows, account_types, account_currencies, strict=True),
                    start=1,
                )
            )
            await session.flush()
            session.add_all(AccountSnapshotModel(**row.model_values()) for row in rows)
            await session.commit()

        async with AsyncSession(engine) as session:
            physical = tuple(
                await session.scalars(
                    select(AccountSnapshotModel)
                    .where(AccountSnapshotModel.account_id.startswith(PREFIX))
                    .order_by(AccountSnapshotModel.account_id)
                )
            )
            currency_rows = await session.execute(
                select(AccountModel.currency, AccountSnapshotModel.currency)
                .join(
                    AccountSnapshotModel,
                    AccountSnapshotModel.account_id == AccountModel.id,
                )
                .where(AccountModel.id.startswith(PREFIX))
                .order_by(AccountModel.id)
            )
            currencies = tuple((row[0], row[1]) for row in currency_rows)
            liability_column = await session.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'AccountSnapshot'
                      AND column_name = 'liabilitiesValueByCurrency'
                    """
                )
            )

        assert currencies == (
            ("CZK", "CZK"),
            ("EUR", "CZK"),
            ("EUR", "CZK"),
            ("EUR", "CZK"),
        )
        assert len(physical) == 4
        mixed_rates = physical[2].exchange_rates
        assert mixed_rates is not None
        assert {(entry["from"], entry["to"]) for entry in mixed_rates["snapshotRates"]} == {
            ("EUR", "CZK"),
            ("USD", "CZK"),
        }
        assert all(entry["to"] != "EUR" for entry in mixed_rates["snapshotRates"])
        assert physical[3].liabilities_value == Decimal("2500.000000")
        assert liability_column == 0
    finally:
        async with AsyncSession(engine) as session:
            await session.execute(
                delete(AccountSnapshotModel).where(
                    AccountSnapshotModel.account_id.startswith(PREFIX)
                )
            )
            await session.execute(delete(AccountModel).where(AccountModel.id.startswith(PREFIX)))
            await session.commit()
        await engine.dispose()
