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
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    LiabilityBalanceSource,
    SnapshotGranularity,
    SnapshotSource,
    TransactionType,
)
from app.db.models.liabilities import LiabilityBalanceModel
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
from app.modules.liabilities.writer import (
    LiabilityBalanceWriter,
    WriteLiabilityBalanceCommand,
)
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
        await session.commit()
    await engine.dispose()


async def _seed(prefix: str) -> tuple[str, str]:
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
                base_currency="EUR",
                created_at=BASELINE_AT - timedelta(days=2),
                updated_at=BASELINE_AT - timedelta(days=2),
            )
        )
        session.add(
            AccountModel(
                id=account_id,
                name="Loan",
                type=AccountType.loan,
                currency="EUR",
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
    user_id, account_id = await _seed(prefix)
    engine = _engine()
    async with AsyncSession(engine) as session:
        account = await session.get(AccountModel, account_id)
        assert account is not None
        account.type = AccountType.bank
        await session.commit()
    await engine.dispose()
    return user_id, account_id


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


async def _current(user_id: str):
    engine = _engine()
    async with AsyncSession(engine) as session:
        result = await CurrentValueService(
            session,
            Settings(environment="test", _env_file=None),
            clock=lambda: CURRENT_AT,
        ).read_portfolio(
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
