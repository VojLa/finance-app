"""PostgreSQL acceptance for exact dashboard deposited presentation."""

from __future__ import annotations

import importlib
import os
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.snapshots import AccountSnapshotModel

api_support: Any = importlib.import_module(
    "tests.test_portfolio_dashboard_snapshot_api_integration"
)
b2_support: Any = importlib.import_module(
    "tests.test_r10b2_account_currency_presentation_integration"
)
single_support: Any = importlib.import_module("tests.test_portfolio_snapshot_api_integration")

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


async def _set_net_deposits(
    primary_id: str,
    value: Decimal,
    *,
    companion_id: str | None = None,
    companion_value: Decimal | None = None,
) -> None:
    engine = single_support._engine()
    async with AsyncSession(engine) as session:
        await session.execute(
            update(AccountSnapshotModel)
            .where(AccountSnapshotModel.id == primary_id)
            .values(
                net_deposits_value=value,
                net_deposits_by_currency={"EUR": format(value, ".6f")},
            )
        )
        if companion_id is not None:
            assert companion_value is not None
            await session.execute(
                update(AccountSnapshotModel)
                .where(AccountSnapshotModel.id == companion_id)
                .values(
                    net_deposits_value=companion_value,
                    net_deposits_by_currency={"EUR": format(value, ".6f")},
                )
            )
        await session.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_mixed_currency_global_uses_primary_and_card_uses_companion() -> None:
    prefix = single_support._prefix("r10c-mixed")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, primary_id, companion_id = await b2_support._add_usd_companion(prefix)
        await _set_net_deposits(
            primary_id,
            Decimal("1000.000000"),
            companion_id=companion_id,
            companion_value=Decimal("1100.000000"),
        )
        before = await b2_support._row_counts(prefix)

        response = api_support._call(
            api_support.DASHBOARD_PATH,
            user_id,
            api_support._body((account_id,), snapshot_ids=(primary_id,)),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["currency"] == "EUR"
        assert payload["summary"]["netDepositsValue"] == "1000.000000"
        assert len(payload["accounts"]) == 1
        card = payload["accounts"][0]
        assert card["accountCurrency"] == card["outputCurrency"] == "USD"
        assert card["netDepositsValue"] == "1100.000000"
        assert card["snapshotId"] == companion_id
        assert card["primarySnapshotId"] == primary_id
        assert await b2_support._row_counts(prefix) == before
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_same_currency_reuses_primary_deposited_identity_and_signed_value() -> None:
    prefix = single_support._prefix("r10c-same")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, primary_id = await single_support._seed(prefix)
        await _set_net_deposits(primary_id, Decimal("-50.000000"))
        before = await b2_support._row_counts(prefix)

        response = api_support._call(
            api_support.DASHBOARD_PATH,
            user_id,
            api_support._body((account_id,), snapshot_ids=(primary_id,)),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["summary"]["netDepositsValue"] == "-50.000000"
        card = payload["accounts"][0]
        assert card["netDepositsValue"] == "-50.000000"
        assert card["snapshotId"] == card["primarySnapshotId"] == primary_id
        assert await b2_support._row_counts(prefix) == before == (1, 2)
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_missing_companion_fails_closed_without_read_mutation() -> None:
    prefix = single_support._prefix("r10c-missing")
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
        before = await b2_support._row_counts(prefix)

        response = api_support._call(
            api_support.DASHBOARD_PATH,
            user_id,
            api_support._body((account_id,), snapshot_ids=(primary_id,)),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "portfolio_snapshot_unavailable"
        assert await b2_support._row_counts(prefix) == before == (1, 2)
    finally:
        await single_support._cleanup(prefix)


@pytest.mark.asyncio
async def test_wrong_version_companion_fails_closed_without_primary_fallback() -> None:
    prefix = single_support._prefix("r10c-corrupt")
    await single_support._cleanup(prefix)
    try:
        user_id, account_id, primary_id, companion_id = await b2_support._add_usd_companion(prefix)
        engine = single_support._engine()
        async with AsyncSession(engine) as session:
            await session.execute(
                update(AccountSnapshotModel)
                .where(AccountSnapshotModel.id == companion_id)
                .values(calculation_version=2)
            )
            await session.commit()
        await engine.dispose()
        before = await b2_support._row_counts(prefix)

        response = api_support._call(
            api_support.DASHBOARD_PATH,
            user_id,
            api_support._body((account_id,), snapshot_ids=(primary_id,)),
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "portfolio_snapshot_unavailable"
        assert await b2_support._row_counts(prefix) == before
    finally:
        await single_support._cleanup(prefix)
