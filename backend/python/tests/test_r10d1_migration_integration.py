from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.accounts import AccountModel
from app.db.models.canonical_lineage import (
    AccountCanonicalChangeModel,
    AccountCanonicalStateModel,
    DailySnapshotBaselineModel,
)
from app.db.models.enums import (
    AccountType,
    ImportSource,
    InvestmentEventType,
    LiabilityBalanceSource,
    TransactionClassification,
    TransactionType,
)
from app.db.models.ledger import InvestmentEventModel
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
AT = datetime(2026, 8, 8, 10, 0, 0, 123000)
PREFIX = "r10d1-migration"


def _run_alembic(*arguments: str) -> None:
    assert DATABASE_URL is not None
    environment = os.environ.copy()
    environment["DATABASE_URL"] = DATABASE_URL
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_populated_pre_d1_upgrade_has_deterministic_nonfictional_backfill() -> None:
    assert DATABASE_URL is not None
    database_name = make_url(normalize_database_url(DATABASE_URL)).database
    if database_name is None or "r10d1" not in database_name:
        pytest.skip("A dedicated r10d1 migration database is required.")

    async def cleanup() -> None:
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            account_id = f"{PREFIX}-account"
            await session.execute(
                delete(TransactionModel).where(TransactionModel.account_id == account_id)
            )
            await session.execute(
                delete(InvestmentEventModel).where(InvestmentEventModel.account_id == account_id)
            )
            await session.execute(
                delete(LiabilityBalanceModel).where(LiabilityBalanceModel.account_id == account_id)
            )
            await session.execute(delete(AccountModel).where(AccountModel.id == account_id))
            await session.execute(delete(UserModel).where(UserModel.id == f"{PREFIX}-user"))
            await session.commit()
        await engine.dispose()

    asyncio.run(cleanup())
    _run_alembic("downgrade", "3h0001twdata")

    async def seed_pre_d1() -> None:
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            user_id = f"{PREFIX}-user"
            account_id = f"{PREFIX}-account"
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{PREFIX}@example.test",
                    name="Pre-D1",
                    password_hash=None,
                    base_currency="CZK",
                    created_at=AT,
                    updated_at=AT,
                )
            )
            session.add(
                AccountModel(
                    id=account_id,
                    name="Pre-D1 account",
                    type=AccountType.broker,
                    currency="CZK",
                    color=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=AT,
                    updated_at=AT,
                    notes=None,
                )
            )
            await session.flush()
            session.add(
                TransactionModel(
                    id=f"{PREFIX}-transaction",
                    account_id=account_id,
                    import_batch_id=None,
                    date=AT,
                    booking_date=None,
                    amount=Decimal("12.340000"),
                    currency="CZK",
                    reporting_amount=None,
                    reporting_currency=None,
                    type=TransactionType.income,
                    classification=TransactionClassification.real_income,
                    description="Historical transaction",
                    note=None,
                    counterparty=None,
                    external_id=f"{PREFIX}-transaction",
                    category_id=None,
                    archived_at=None,
                    deleted_at=None,
                    created_at=AT,
                    updated_at=AT,
                )
            )
            session.add(
                InvestmentEventModel(
                    id=f"{PREFIX}-event",
                    account_id=account_id,
                    type=InvestmentEventType.interest,
                    date=AT,
                    source=ImportSource.manual,
                    external_id=f"{PREFIX}-event",
                    order_id=None,
                    description=None,
                    realized_pnl=None,
                    realized_pnl_currency=None,
                    import_batch_id=None,
                    archived_at=None,
                    deleted_at=None,
                    created_at=AT,
                    updated_at=AT,
                )
            )
            session.add(
                LiabilityBalanceModel(
                    id=f"{PREFIX}-liability",
                    account_id=account_id,
                    effective_at=AT,
                    currency="CZK",
                    outstanding_principal=Decimal("50.000000"),
                    accrued_interest=Decimal("1.000000"),
                    fees_outstanding=Decimal("2.000000"),
                    total_outstanding=Decimal("53.000000"),
                    source=LiabilityBalanceSource.manual,
                    external_id=f"{PREFIX}-liability",
                    created_at=AT,
                )
            )
            await session.commit()
        await engine.dispose()

    asyncio.run(seed_pre_d1())
    _run_alembic("upgrade", "head")

    async def verify() -> None:
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            account_id = f"{PREFIX}-account"
            state = await session.get(AccountCanonicalStateModel, account_id)
            assert state is not None
            assert (
                state.last_revision,
                state.last_investment_revision,
                state.holding_revision,
            ) == (3, 1, None)
            changes = tuple(
                (
                    await session.scalars(
                        select(AccountCanonicalChangeModel)
                        .where(AccountCanonicalChangeModel.account_id == account_id)
                        .order_by(AccountCanonicalChangeModel.revision)
                    )
                ).all()
            )
            assert tuple(
                (change.revision, change.kind, change.entity_id) for change in changes
            ) == (
                (1, "investment_event", f"{PREFIX}-event"),
                (2, "liability_balance", f"{PREFIX}-liability"),
                (3, "transaction", f"{PREFIX}-transaction"),
            )
            transaction = await session.get(TransactionModel, f"{PREFIX}-transaction")
            liability = await session.get(LiabilityBalanceModel, f"{PREFIX}-liability")
            assert transaction is not None and transaction.amount == Decimal("12.340000")
            assert liability is not None and liability.total_outstanding == Decimal("53.000000")
            assert (
                await session.scalar(select(func.count()).select_from(DailySnapshotBaselineModel))
                == 0
            )
        await engine.dispose()

    asyncio.run(verify())
