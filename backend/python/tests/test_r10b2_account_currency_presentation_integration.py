"""PostgreSQL acceptance for exact primary and account-currency presentation reads."""

from __future__ import annotations

import importlib
import os
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.enums import AccountType
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel

support: Any = importlib.import_module("tests.test_portfolio_dashboard_snapshot_api_integration")
single_support: Any = importlib.import_module("tests.test_portfolio_snapshot_api_integration")

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


async def _add_usd_companion(
    prefix: str,
    *,
    account_type: AccountType = AccountType.broker,
) -> tuple[str, str, str, str]:
    user_id, account_id, primary_id = await single_support._seed(
        prefix,
        account_type=account_type,
    )
    companion_id = f"{prefix}-usd-companion"
    engine = single_support._engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        primary = await session.get(AccountSnapshotModel, primary_id)
        assert primary is not None
        primary_items = tuple(
            await session.scalars(
                select(AccountSnapshotItemModel)
                .where(AccountSnapshotItemModel.snapshot_id == primary_id)
                .order_by(AccountSnapshotItemModel.id)
            )
        )
        await session.execute(
            update(AccountModel).where(AccountModel.id == account_id).values(currency="USD")
        )
        liability = account_type in {
            AccountType.credit_card,
            AccountType.loan,
            AccountType.mortgage,
        }
        cash = Decimal("0.000000") if liability else Decimal("2.000000")
        investment = Decimal("0.000000") if liability else Decimal("25.000000")
        cost = Decimal("0.000000") if liability else Decimal("20.000000")
        liabilities = Decimal("6.000000") if liability else Decimal("0.000000")
        companion = AccountSnapshotModel(
            id=companion_id,
            account_id=account_id,
            timestamp=primary.timestamp,
            granularity=primary.granularity,
            source=primary.source,
            currency="USD",
            cash_value=cash,
            investment_value=investment,
            investment_cost_basis=cost,
            liabilities_value=liabilities,
            total_value=cash + investment - liabilities,
            is_recalculated=primary.is_recalculated,
            calculated_at=primary.calculated_at,
            calculation_version=primary.calculation_version,
            created_at=primary.created_at,
            net_deposits_value=Decimal("0.000000"),
            realized_pnl_value=Decimal("0.000000"),
            unrealized_pnl_value=investment - cost,
            fees_value=Decimal("0.000000"),
            taxes_value=Decimal("0.000000"),
            cash_value_by_currency=primary.cash_value_by_currency,
            investment_value_by_currency=primary.investment_value_by_currency,
            investment_cost_basis_by_currency=primary.investment_cost_basis_by_currency,
            net_deposits_by_currency=primary.net_deposits_by_currency,
            realized_pnl_by_currency=primary.realized_pnl_by_currency,
            unrealized_pnl_by_currency=primary.unrealized_pnl_by_currency,
            fees_by_currency=primary.fees_by_currency,
            taxes_by_currency=primary.taxes_by_currency,
            exchange_rates=primary.exchange_rates,
        )
        session.add(companion)
        await session.flush()
        companion_values = (
            (
                (Decimal("15.000000"), Decimal("12.5000000000")),
                (Decimal("10.000000"), Decimal("7.5000000000")),
            )
            if primary_items
            else ()
        )
        for item, (value, item_cost) in zip(
            primary_items,
            companion_values,
            strict=True,
        ):
            session.add(
                AccountSnapshotItemModel(
                    id=f"{item.id}-usd",
                    snapshot_id=companion_id,
                    asset_id=item.asset_id,
                    listing_id=item.listing_id,
                    symbol=item.symbol,
                    quantity=item.quantity,
                    price_per_unit=item.price_per_unit,
                    price_currency=item.price_currency,
                    price_source=item.price_source,
                    price_timestamp=item.price_timestamp,
                    value=value,
                    cost_basis=item_cost,
                    cost_currency="USD",
                    allocation_pct=item.allocation_pct,
                    created_at=item.created_at,
                    native_value=item.native_value,
                    value_currency=item.value_currency,
                    native_cost_basis=item.native_cost_basis,
                    native_cost_currency=item.native_cost_currency,
                )
            )
        await session.commit()
    await engine.dispose()
    return user_id, account_id, primary_id, companion_id


async def _row_counts(prefix: str) -> tuple[int, int]:
    engine = single_support._engine()
    async with AsyncSession(engine) as session:
        snapshots = await session.scalar(
            select(func.count())
            .select_from(AccountSnapshotModel)
            .where(AccountSnapshotModel.id.startswith(prefix))
        )
        items = await session.scalar(
            select(func.count())
            .select_from(AccountSnapshotItemModel)
            .where(AccountSnapshotItemModel.id.startswith(prefix))
        )
    await engine.dispose()
    return int(snapshots or 0), int(items or 0)


@pytest.mark.asyncio
async def test_mixed_account_portfolio_and_dashboard_split_primary_and_presentation() -> None:
    prefix = single_support._prefix("r10b2-mixed")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, primary_id, companion_id = await _add_usd_companion(prefix)
        before = await _row_counts(prefix)
        body = support._body((account_id,), snapshot_ids=(primary_id,))

        portfolio = support._call(support.PORTFOLIO_PATH, user_id, body)
        dashboard = support._call(support.DASHBOARD_PATH, user_id, body)

        assert portfolio.status_code == dashboard.status_code == 200
        portfolio_json = portfolio.json()
        account = portfolio_json["accounts"][0]
        assert portfolio_json["currency"] == "EUR"
        assert portfolio_json["summary"]["investmentValue"] == "100.000000"
        assert account["snapshotId"] == companion_id
        assert account["primarySnapshotId"] == primary_id
        assert account["currency"] == account["account"]["currency"] == "USD"
        assert account["summary"]["investmentValue"] == "25.000000"
        assert {item["valueCurrency"] for item in account["positions"]} == {"USD"}
        assert {item["costCurrency"] for item in account["positions"]} == {"USD"}
        assert {
            item["position"]["valueCurrency"] for item in portfolio_json["aggregatePositions"]
        } == {"EUR"}

        dashboard_json = dashboard.json()
        assert dashboard_json["currency"] == "EUR"
        assert dashboard_json["summary"]["investmentValue"] == "100.000000"
        assert dashboard_json["assetTypeAllocations"][0]["value"] == "100.000000"
        assert {item["valueCurrency"] for item in dashboard_json["topPositions"]} == {"EUR"}
        assert dashboard_json["accounts"][0]["snapshotId"] == companion_id
        assert dashboard_json["accounts"][0]["primarySnapshotId"] == primary_id
        assert dashboard_json["accounts"][0]["outputCurrency"] == "USD"
        assert dashboard_json["accounts"][0]["investmentValue"] == "25.000000"
        assert await _row_counts(prefix) == before
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_liability_companion_is_exact_account_currency() -> None:
    prefix = single_support._prefix("r10b2-liability")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, primary_id, companion_id = await _add_usd_companion(
            prefix,
            account_type=AccountType.loan,
        )

        portfolio = support._call(
            support.PORTFOLIO_PATH,
            user_id,
            support._body((account_id,), snapshot_ids=(primary_id,)),
        )

        assert portfolio.status_code == 200
        account = portfolio.json()["accounts"][0]
        assert account["snapshotId"] == companion_id
        assert account["currency"] == "USD"
        assert account["summary"]["liabilitiesValue"] == "6.000000"
        assert account["summary"]["totalValue"] == "-6.000000"
        assert account["positions"] == []
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_missing_and_corrupt_companions_fail_closed() -> None:
    prefix = single_support._prefix("r10b2-missing")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, primary_id = await single_support._seed(prefix)
        engine = single_support._engine()
        async with AsyncSession(engine) as session:
            await session.execute(
                update(AccountModel).where(AccountModel.id == account_id).values(currency="USD")
            )
            await session.commit()
        await engine.dispose()
        body = support._body((account_id,), snapshot_ids=(primary_id,))

        missing = support._call(support.PORTFOLIO_PATH, user_id, body)

        assert missing.status_code == 409
        assert missing.json()["error"]["code"] == "portfolio_snapshot_unavailable"
        assert missing.json()["error"]["message"] == (
            "The requested portfolio snapshot is unavailable."
        )
        assert await _row_counts(prefix) == (1, 2)
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_corrupt_companion_version_fails_closed_without_fallback() -> None:
    prefix = single_support._prefix("r10b2-corrupt")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, primary_id, companion_id = await _add_usd_companion(prefix)
        engine = single_support._engine()
        async with AsyncSession(engine) as session:
            await session.execute(
                update(AccountSnapshotModel)
                .where(AccountSnapshotModel.id == companion_id)
                .values(calculation_version=2)
            )
            await session.commit()
        await engine.dispose()
        before = await _row_counts(prefix)

        response = support._call(
            support.DASHBOARD_PATH,
            user_id,
            support._body((account_id,), snapshot_ids=(primary_id,)),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "portfolio_snapshot_unavailable"
        assert await _row_counts(prefix) == before
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_same_currency_reuses_primary_snapshot_identity() -> None:
    prefix = single_support._prefix("r10b2-same")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, primary_id = await single_support._seed(prefix)

        portfolio = support._call(
            support.PORTFOLIO_PATH,
            user_id,
            support._body((account_id,), snapshot_ids=(primary_id,)),
        )

        assert portfolio.status_code == 200
        account = portfolio.json()["accounts"][0]
        assert account["snapshotId"] == account["primarySnapshotId"] == primary_id
        assert account["currency"] == "EUR"
        assert await _row_counts(prefix) == (1, 2)
    finally:
        await single_support._cleanup(prefix)
