"""PostgreSQL observations for the unresolved R10-D current-value invariant."""

from __future__ import annotations

import asyncio
import importlib
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.enums import (
    AccountType,
    LiabilityBalanceSource,
    SnapshotGranularity,
    SnapshotSource,
    TransactionClassification,
    TransactionType,
)
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.modules.canonical_state.service import CanonicalChangeKind, CanonicalStateService
from app.modules.snapshot_refresh.executor import (
    ExecuteUserSnapshotRefreshCommand,
    UserSnapshotRefreshExecutor,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
support: Any = importlib.import_module("tests.test_snapshot_refresh_manual_endpoint_integration")

CURRENT = support.BUCKET
DAY = datetime(2036, 7, 28)
INITIAL = DAY - timedelta(hours=1)
LATER = CURRENT - timedelta(hours=1)


async def _cleanup(prefix: str) -> None:
    engine = support._engine()
    try:
        async with AsyncSession(engine) as session:
            account_ids = tuple(
                await session.scalars(
                    select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
                )
            )
            if account_ids:
                await session.execute(
                    delete(TransactionModel).where(TransactionModel.account_id.in_(account_ids))
                )
                await session.commit()
    finally:
        await engine.dispose()
    await support._cleanup(prefix)


async def _seed_bank(prefix: str) -> str:
    await support._seed(
        prefix,
        (support._AccountSpec(suffix="bank", account_type=AccountType.bank),),
    )
    account_id = support._account_id(prefix, "bank")
    engine = support._engine()
    try:
        async with AsyncSession(engine) as session:
            await session.execute(
                update(UserModel)
                .where(UserModel.id == support._user_id(prefix))
                .values(created_at=INITIAL, updated_at=INITIAL)
            )
            await session.execute(
                update(AccountModel)
                .where(AccountModel.id == account_id)
                .values(created_at=INITIAL, updated_at=INITIAL)
            )
            await session.commit()
    finally:
        await engine.dispose()
    return account_id


async def _add_transaction(
    prefix: str,
    account_id: str,
    suffix: str,
    *,
    event_at: datetime,
    created_at: datetime,
    amount: str,
) -> None:
    engine = support._engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                TransactionModel(
                    id=f"{prefix}-transaction-{suffix}",
                    account_id=account_id,
                    date=event_at,
                    booking_date=None,
                    amount=Decimal(amount),
                    currency="EUR",
                    reporting_amount=None,
                    reporting_currency=None,
                    type=TransactionType.income,
                    classification=TransactionClassification.real_income,
                    description=suffix,
                    note=None,
                    counterparty=None,
                    external_id=f"{prefix}-external-{suffix}",
                    is_reviewed=True,
                    archived_at=None,
                    deleted_at=None,
                    category_id=None,
                    import_batch_id=None,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _write_daily(prefix: str) -> None:
    engine = support._engine()
    try:
        async with AsyncSession(engine) as session:
            result = await UserSnapshotRefreshExecutor(session).execute(
                ExecuteUserSnapshotRefreshCommand(
                    user_id=support._user_id(prefix),
                    snapshot_timestamp=DAY,
                    granularity=SnapshotGranularity.day,
                    source=SnapshotSource.scheduled,
                    calculation_version=1,
                    calculated_at=DAY,
                    created_at=DAY,
                    is_recalculated=False,
                )
            )
            assert result.granularity is SnapshotGranularity.day
            assert result.selected_account_snapshot_count == 1
    finally:
        await engine.dispose()


async def _rows(
    prefix: str,
) -> tuple[tuple[AccountSnapshotModel, ...], tuple[NetWorthSnapshotModel, ...]]:
    engine = support._engine()
    try:
        async with AsyncSession(engine) as session:
            account_rows = tuple(
                await session.scalars(
                    select(AccountSnapshotModel)
                    .where(AccountSnapshotModel.account_id.startswith(f"{prefix}-"))
                    .order_by(AccountSnapshotModel.timestamp, AccountSnapshotModel.id)
                )
            )
            net_rows = tuple(
                await session.scalars(
                    select(NetWorthSnapshotModel)
                    .where(NetWorthSnapshotModel.user_id == support._user_id(prefix))
                    .order_by(NetWorthSnapshotModel.timestamp, NetWorthSnapshotModel.id)
                )
            )
            return account_rows, net_rows
    finally:
        await engine.dispose()


def test_current_workflow_succeeds_without_any_daily_baseline() -> None:
    prefix = f"r10d-no-day-{support.uuid4()}"
    try:
        account_id = asyncio.run(_seed_bank(prefix))
        asyncio.run(
            _add_transaction(
                prefix,
                account_id,
                "current",
                event_at=LATER,
                created_at=LATER,
                amount="100.000000",
            )
        )

        response = support._call(prefix)
        account_rows, net_rows = asyncio.run(_rows(prefix))

        assert response.status_code == 200
        assert response.json()["granularity"] == "minute"
        assert response.json()["timestamp"] == CURRENT.isoformat(timespec="milliseconds")
        assert len(account_rows) == len(net_rows) == 1
        assert account_rows[0].granularity is SnapshotGranularity.minute
        assert net_rows[0].granularity is SnapshotGranularity.minute
        assert account_rows[0].cash_value == Decimal("100.000000")
    finally:
        asyncio.run(_cleanup(prefix))


def test_daily_baseline_and_later_event_produce_a_new_complete_minute_graph() -> None:
    prefix = f"r10d-day-event-{support.uuid4()}"
    try:
        account_id = asyncio.run(_seed_bank(prefix))
        asyncio.run(
            _add_transaction(
                prefix,
                account_id,
                "initial",
                event_at=INITIAL,
                created_at=INITIAL,
                amount="100.000000",
            )
        )
        asyncio.run(_write_daily(prefix))
        asyncio.run(
            _add_transaction(
                prefix,
                account_id,
                "later",
                event_at=LATER,
                created_at=LATER,
                amount="50.000000",
            )
        )
        before = asyncio.run(_rows(prefix))

        response = support._call(prefix)
        account_rows, net_rows = asyncio.run(_rows(prefix))

        assert response.status_code == 200
        assert tuple(row.granularity for row in account_rows) == (
            SnapshotGranularity.day,
            SnapshotGranularity.minute,
        )
        assert tuple(row.cash_value for row in account_rows) == (
            Decimal("100.000000"),
            Decimal("150.000000"),
        )
        assert len(before[0]) == len(before[1]) == 1
        assert len(account_rows) == len(net_rows) == 2
        assert response.json()["accounts"] == [
            {"accountId": account_id, "snapshotId": account_rows[1].id}
        ]
        assert response.json()["netWorthSnapshotId"] == net_rows[1].id
    finally:
        asyncio.run(_cleanup(prefix))


def test_post_baseline_backfill_has_no_persisted_inclusion_watermark() -> None:
    prefix = f"r10d-backfill-{support.uuid4()}"
    try:
        account_id = asyncio.run(_seed_bank(prefix))
        asyncio.run(
            _add_transaction(
                prefix,
                account_id,
                "initial",
                event_at=INITIAL,
                created_at=INITIAL,
                amount="100.000000",
            )
        )
        asyncio.run(_write_daily(prefix))
        asyncio.run(
            _add_transaction(
                prefix,
                account_id,
                "backfilled",
                event_at=DAY - timedelta(minutes=1),
                created_at=DAY + timedelta(hours=1),
                amount="25.000000",
            )
        )

        response = support._call(prefix)
        account_rows, _ = asyncio.run(_rows(prefix))

        assert response.status_code == 200
        assert tuple(row.cash_value for row in account_rows) == (
            Decimal("100.000000"),
            Decimal("125.000000"),
        )
        assert account_rows[0].timestamp == DAY
        assert account_rows[1].timestamp == CURRENT
    finally:
        asyncio.run(_cleanup(prefix))


def test_liability_current_value_uses_a_later_point_not_a_persisted_delta() -> None:
    prefix = f"r10d-liability-{support.uuid4()}"
    try:
        asyncio.run(
            support._seed(
                prefix,
                (support._AccountSpec(suffix="loan", account_type=AccountType.loan),),
            )
        )
        account_id = support._account_id(prefix, "loan")

        async def prepare() -> None:
            engine = support._engine()
            try:
                async with AsyncSession(engine) as session:
                    await session.execute(
                        update(LiabilityBalanceModel)
                        .where(LiabilityBalanceModel.account_id == account_id)
                        .values(effective_at=INITIAL, created_at=INITIAL)
                    )
                    await CanonicalStateService(session).record(
                        account_id=account_id,
                        kind=CanonicalChangeKind.liability_balance,
                        entity_id=f"{prefix}-balance-loan",
                        financial_timestamp=INITIAL,
                        created_at=INITIAL,
                        replay=False,
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(prepare())
        asyncio.run(_write_daily(prefix))

        async def add_later_balance() -> None:
            engine = support._engine()
            try:
                async with AsyncSession(engine) as session:
                    session.add(
                        LiabilityBalanceModel(
                            id=f"{prefix}-balance-later",
                            account_id=account_id,
                            effective_at=LATER,
                            currency="EUR",
                            outstanding_principal=Decimal("140.000000"),
                            accrued_interest=Decimal("0.000000"),
                            fees_outstanding=Decimal("0.000000"),
                            total_outstanding=Decimal("140.000000"),
                            source=LiabilityBalanceSource.statement,
                            external_id=f"{prefix}-later",
                            created_at=LATER,
                        )
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(add_later_balance())
        response = support._call(prefix)
        account_rows, _ = asyncio.run(_rows(prefix))

        assert response.status_code == 200
        assert tuple(row.liabilities_value for row in account_rows) == (
            Decimal("100.000000"),
            Decimal("140.000000"),
        )
        assert tuple(row.granularity for row in account_rows) == (
            SnapshotGranularity.day,
            SnapshotGranularity.minute,
        )
    finally:
        asyncio.run(_cleanup(prefix))
