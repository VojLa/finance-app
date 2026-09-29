"""PostgreSQL observations for the unresolved R10-D current-value invariant."""

from __future__ import annotations

import asyncio
import importlib
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.canonical_lineage import (
    AccountCanonicalChangeModel,
    DailySnapshotBaselineAccountModel,
    DailySnapshotBaselineModel,
    SnapshotGenerationModel,
    SnapshotGenerationTargetModel,
    UserReadModelPublicationModel,
    UserReadModelPublicationWatermarkModel,
)
from app.db.models.enums import (
    AccountType,
    LiabilityBalanceSource,
    SnapshotGranularity,
    SnapshotSource,
    TransactionClassification,
    TransactionType,
)
from app.db.models.investment_snapshots import PortfolioSnapshotModel
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.snapshot_series_jobs import (
    SnapshotSeriesDirtyStateModel,
    SnapshotSeriesRebuildJobModel,
)
from app.db.models.snapshot_series_publication import (
    SnapshotSeriesHeadModel,
    SnapshotSeriesPointLinkModel,
    SnapshotSeriesPublicationReceiptModel,
    SnapshotSeriesVersionStateModel,
)
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.modules.canonical_state.service import CanonicalChangeKind, CanonicalStateService
from app.modules.portfolio_history.invalidation.service import (
    PortfolioHistoryInvalidationService,
)
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
            user_id = support._user_id(prefix)
            generation_ids = tuple(
                await session.scalars(
                    select(SnapshotGenerationTargetModel.generation_id).where(
                        SnapshotGenerationTargetModel.user_id == user_id
                    )
                )
            )
            await session.execute(
                delete(UserReadModelPublicationModel).where(
                    UserReadModelPublicationModel.user_id == user_id
                )
            )
            # Immutable publication metadata needs a transaction-local test
            # teardown override; restore triggers before deleting evidence.
            await session.execute(text("SET LOCAL session_replication_role = replica"))
            await session.execute(
                delete(SnapshotSeriesPublicationReceiptModel).where(
                    SnapshotSeriesPublicationReceiptModel.user_id == user_id
                )
            )
            await session.execute(
                delete(SnapshotSeriesPointLinkModel).where(
                    SnapshotSeriesPointLinkModel.user_id == user_id
                )
            )
            heads = tuple(
                await session.scalars(
                    select(SnapshotSeriesHeadModel.id)
                    .where(SnapshotSeriesHeadModel.user_id == user_id)
                    .order_by(SnapshotSeriesHeadModel.version.desc())
                )
            )
            for head_id in heads:
                await session.execute(
                    delete(SnapshotSeriesHeadModel).where(SnapshotSeriesHeadModel.id == head_id)
                )
            await session.execute(
                delete(SnapshotSeriesVersionStateModel).where(
                    SnapshotSeriesVersionStateModel.user_id == user_id
                )
            )
            await session.execute(
                delete(UserReadModelPublicationWatermarkModel).where(
                    UserReadModelPublicationWatermarkModel.user_id == user_id
                )
            )
            await session.execute(text("SET LOCAL session_replication_role = origin"))
            await session.execute(
                delete(SnapshotSeriesDirtyStateModel).where(
                    SnapshotSeriesDirtyStateModel.user_id == user_id
                )
            )
            await session.execute(
                delete(PortfolioSnapshotModel).where(PortfolioSnapshotModel.user_id == user_id)
            )
            if account_ids:
                await session.execute(
                    delete(DailySnapshotBaselineAccountModel).where(
                        DailySnapshotBaselineAccountModel.account_id.in_(account_ids)
                    )
                )
            await session.execute(
                delete(DailySnapshotBaselineModel).where(
                    DailySnapshotBaselineModel.user_id == user_id
                )
            )
            if account_ids:
                await session.execute(
                    delete(TransactionModel).where(TransactionModel.account_id.in_(account_ids))
                )
            snapshot_ids = (
                tuple(
                    await session.scalars(
                        select(AccountSnapshotModel.id).where(
                            AccountSnapshotModel.account_id.in_(account_ids)
                        )
                    )
                )
                if account_ids
                else ()
            )
            if snapshot_ids:
                await session.execute(
                    delete(AccountSnapshotItemModel).where(
                        AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids)
                    )
                )
            await session.execute(
                delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id == user_id)
            )
            if account_ids:
                await session.execute(
                    delete(AccountSnapshotModel).where(
                        AccountSnapshotModel.account_id.in_(account_ids)
                    )
                )
                await session.execute(
                    delete(LiabilityBalanceModel).where(
                        LiabilityBalanceModel.account_id.in_(account_ids)
                    )
                )
            await session.execute(
                delete(SnapshotGenerationTargetModel).where(
                    SnapshotGenerationTargetModel.user_id == user_id
                )
            )
            await session.execute(
                delete(SnapshotSeriesRebuildJobModel).where(
                    SnapshotSeriesRebuildJobModel.user_id == user_id
                )
            )
            if generation_ids:
                await session.execute(
                    delete(SnapshotGenerationModel).where(
                        SnapshotGenerationModel.id.in_(generation_ids)
                    )
                )
            if account_ids:
                await session.execute(
                    delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
                )
                await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
            await session.execute(delete(UserModel).where(UserModel.id == user_id))
            assert await session.get(UserModel, user_id) is None
            assert not tuple(
                await session.scalars(
                    select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
                )
            )
            assert not tuple(
                await session.scalars(
                    select(SnapshotSeriesPointLinkModel.id).where(
                        SnapshotSeriesPointLinkModel.user_id == user_id
                    )
                )
            )
            assert not tuple(
                await session.scalars(
                    select(SnapshotGenerationTargetModel.generation_id).where(
                        SnapshotGenerationTargetModel.user_id == user_id
                    )
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


async def _clear_setup_invalidation(prefix: str) -> None:
    """Leave direct-publication fixtures clean after their setup evidence writes."""
    engine = support._engine()
    try:
        async with AsyncSession(engine) as session:
            user_id = support._user_id(prefix)
            await session.execute(
                delete(SnapshotSeriesDirtyStateModel).where(
                    SnapshotSeriesDirtyStateModel.user_id == user_id
                )
            )
            await session.execute(
                delete(SnapshotSeriesRebuildJobModel).where(
                    SnapshotSeriesRebuildJobModel.user_id == user_id
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


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
    invalidate: bool = False,
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
            await session.flush()
            invalidation = PortfolioHistoryInvalidationService(session)
            memberships = (
                await invalidation.lock_current_memberships((account_id,)) if invalidate else ()
            )
            recorded = await CanonicalStateService(session).record(
                account_id=account_id,
                kind=CanonicalChangeKind.transaction,
                entity_id=f"{prefix}-transaction-{suffix}",
                financial_timestamp=event_at,
                created_at=created_at,
                replay=False,
            )
            if invalidate:
                await invalidation.invalidate_recorded_changes(
                    changes=(recorded,),
                    locked_memberships=memberships,
                    now=created_at,
                )
            await session.commit()
    finally:
        await engine.dispose()


async def _write_daily(prefix: str) -> None:
    await _clear_setup_invalidation(prefix)
    engine = support._engine()
    try:
        async with AsyncSession(engine) as session:
            result = await UserSnapshotRefreshExecutor(session).execute(
                ExecuteUserSnapshotRefreshCommand(
                    user_id=support._user_id(prefix),
                    snapshot_timestamp=DAY,
                    granularity=SnapshotGranularity.day,
                    source=SnapshotSource.scheduled,
                    calculation_version=3,
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


async def _publication(prefix: str) -> tuple[str, str, str] | None:
    engine = support._engine()
    try:
        async with AsyncSession(engine) as session:
            pointer = await session.get(UserReadModelPublicationModel, support._user_id(prefix))
            if pointer is None:
                return None
            return pointer.baseline_id, pointer.generation_id, pointer.series_head_id
    finally:
        await engine.dispose()


async def _is_dirty(prefix: str) -> bool:
    engine = support._engine()
    try:
        async with AsyncSession(engine) as session:
            return (
                await session.get(SnapshotSeriesDirtyStateModel, support._user_id(prefix))
                is not None
            )
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
        asyncio.run(_clear_setup_invalidation(prefix))

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


def test_daily_baseline_and_later_clean_event_produce_complete_minute_graph() -> None:
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
        assert len(before[0]) == len(before[1]) == 1
        assert tuple(row.granularity for row in account_rows) == (
            SnapshotGranularity.day,
            SnapshotGranularity.minute,
        )
        assert tuple(row.cash_value for row in account_rows) == (
            Decimal("100.000000"),
            Decimal("150.000000"),
        )
        assert len(account_rows) == len(net_rows) == 2
        assert response.json()["accounts"] == [
            {"accountId": account_id, "snapshotId": account_rows[1].id}
        ]
        assert response.json()["netWorthSnapshotId"] == net_rows[1].id
    finally:
        asyncio.run(_cleanup(prefix))


def test_post_baseline_backfill_does_not_publish_staged_minute_graph() -> None:
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
        published_before = asyncio.run(_publication(prefix))
        asyncio.run(
            _add_transaction(
                prefix,
                account_id,
                "backfilled",
                event_at=DAY - timedelta(minutes=1),
                created_at=DAY + timedelta(hours=1),
                amount="25.000000",
                invalidate=True,
            )
        )
        assert asyncio.run(_is_dirty(prefix))
        before = asyncio.run(_rows(prefix))

        response = support._call(prefix)
        account_rows, net_rows = asyncio.run(_rows(prefix))

        assert response.status_code == 409
        assert len(before[0]) == len(before[1]) == 1
        assert any(row.id == before[0][0].id for row in account_rows)
        assert any(row.id == before[1][0].id for row in net_rows)
        assert before[0][0].cash_value == Decimal("100.000000")
        assert before[0][0].timestamp == DAY
        assert asyncio.run(_publication(prefix)) == published_before
    finally:
        asyncio.run(_cleanup(prefix))


def test_later_liability_point_requires_rebuild_before_publication() -> None:
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
                    await session.execute(
                        update(AccountCanonicalChangeModel)
                        .where(
                            AccountCanonicalChangeModel.account_id == account_id,
                            AccountCanonicalChangeModel.entity_id == f"{prefix}-balance-loan",
                        )
                        .values(financial_timestamp=INITIAL, created_at=INITIAL)
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(prepare())
        asyncio.run(_write_daily(prefix))
        published_before = asyncio.run(_publication(prefix))

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
                    await session.flush()
                    invalidation = PortfolioHistoryInvalidationService(session)
                    memberships = await invalidation.lock_current_memberships((account_id,))
                    recorded = await CanonicalStateService(session).record(
                        account_id=account_id,
                        kind=CanonicalChangeKind.liability_balance,
                        entity_id=f"{prefix}-balance-later",
                        financial_timestamp=LATER,
                        created_at=LATER,
                        replay=False,
                    )
                    await invalidation.invalidate_recorded_changes(
                        changes=(recorded,),
                        locked_memberships=memberships,
                        now=LATER,
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(add_later_balance())
        assert asyncio.run(_is_dirty(prefix))
        before = asyncio.run(_rows(prefix))
        response = support._call(prefix)
        account_rows, net_rows = asyncio.run(_rows(prefix))

        assert response.status_code == 409
        assert len(before[0]) == len(before[1]) == 1
        assert any(row.id == before[0][0].id for row in account_rows)
        assert any(row.id == before[1][0].id for row in net_rows)
        assert before[0][0].liabilities_value == Decimal("100.000000")
        assert before[0][0].granularity is SnapshotGranularity.day
        assert asyncio.run(_publication(prefix)) == published_before
    finally:
        asyncio.run(_cleanup(prefix))
