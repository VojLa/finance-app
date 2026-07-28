from __future__ import annotations

import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.accounts import AccountModel
from app.db.models.enums import AccountType, LiabilityBalanceSource
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.db.models.transactions import TransactionModel
from app.db.url import normalize_database_url
from app.modules.liabilities import (
    LiabilityBalanceEvidenceService,
    LiabilityBalanceEvidenceStateError,
    SelectLiabilityBalanceCommand,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
SNAPSHOT_AT = datetime(2026, 7, 28, 12)


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=4)


def _account(
    prefix: str,
    *,
    account_type: AccountType,
    currency: str = "CZK",
    archived: bool = False,
) -> AccountModel:
    return AccountModel(
        id=f"{prefix}-account",
        name=f"{prefix} liability",
        type=account_type,
        currency=currency,
        color=None,
        notes=None,
        is_archived=archived,
        archived_at=SNAPSHOT_AT if archived else None,
        created_at=SNAPSHOT_AT - timedelta(days=365),
        updated_at=SNAPSHOT_AT - timedelta(days=1),
    )


def _balance(
    prefix: str,
    *,
    suffix: str,
    effective_at: datetime,
    principal: str,
    interest: str = "0",
    fees: str = "0",
    currency: str = "CZK",
    source: LiabilityBalanceSource = LiabilityBalanceSource.statement,
) -> LiabilityBalanceModel:
    return LiabilityBalanceModel(
        id=f"{prefix}-balance-{suffix}",
        account_id=f"{prefix}-account",
        effective_at=effective_at,
        currency=currency,
        outstanding_principal=Decimal(principal),
        accrued_interest=Decimal(interest),
        fees_outstanding=Decimal(fees),
        total_outstanding=Decimal(principal) + Decimal(interest) + Decimal(fees),
        source=source,
        external_id=f"{prefix}-{suffix}" if source is not LiabilityBalanceSource.manual else None,
        created_at=max(effective_at, SNAPSHOT_AT - timedelta(days=1)),
    )


def _command(prefix: str) -> SelectLiabilityBalanceCommand:
    return SelectLiabilityBalanceCommand(
        account_id=f"{prefix}-account",
        snapshot_timestamp=SNAPSHOT_AT,
    )


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    account_id = f"{prefix}-account"
    async with AsyncSession(engine) as session:
        snapshot_ids = tuple(
            await session.scalars(
                select(AccountSnapshotModel.id).where(AccountSnapshotModel.account_id == account_id)
            )
        )
        if snapshot_ids:
            await session.execute(
                delete(AccountSnapshotItemModel).where(
                    AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids)
                )
            )
        await session.execute(
            delete(AccountSnapshotModel).where(AccountSnapshotModel.account_id == account_id)
        )
        await session.execute(
            delete(TransactionModel).where(TransactionModel.account_id == account_id)
        )
        await session.execute(
            delete(LiabilityBalanceModel).where(LiabilityBalanceModel.account_id == account_id)
        )
        await session.execute(delete(AccountModel).where(AccountModel.id == account_id))
        await session.commit()
    await engine.dispose()


async def _seed(
    prefix: str,
    *,
    account_type: AccountType,
    balances: tuple[LiabilityBalanceModel, ...],
    currency: str = "CZK",
    archived: bool = False,
) -> None:
    await _cleanup(prefix)
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            _account(
                prefix,
                account_type=account_type,
                currency=currency,
                archived=archived,
            )
        )
        session.add_all(balances)
        await session.commit()
    await engine.dispose()


async def _counts(session: AsyncSession, prefix: str) -> tuple[int, int, int, int]:
    account_id = f"{prefix}-account"
    return (
        await session.scalar(
            select(func.count()).select_from(AccountModel).where(AccountModel.id == account_id)
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
            .select_from(TransactionModel)
            .where(TransactionModel.account_id == account_id)
        )
        or 0,
        await session.scalar(
            select(func.count())
            .select_from(AccountSnapshotModel)
            .where(AccountSnapshotModel.account_id == account_id)
        )
        or 0,
    )


@pytest.mark.asyncio
async def test_credit_card_selects_latest_exact_eligible_observation() -> None:
    prefix = "i5l-credit-card"
    older = _balance(
        prefix,
        suffix="older",
        effective_at=SNAPSHOT_AT - timedelta(days=10),
        principal="100.000000",
    )
    latest = _balance(
        prefix,
        suffix="latest",
        effective_at=SNAPSHOT_AT,
        principal="80.000000",
        interest="2.000000",
        fees="1.000000",
    )
    await _seed(
        prefix,
        account_type=AccountType.credit_card,
        balances=(older, latest),
    )
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            before = await _counts(session, prefix)
            result = await LiabilityBalanceEvidenceService(session).select(_command(prefix))
            after = await _counts(session, prefix)

            assert result.balance_id == f"{prefix}-balance-latest"
            assert result.total_outstanding == Decimal("83.000000")
            assert result.source is LiabilityBalanceSource.statement
            assert after == before == (1, 2, 0, 0)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("account_type", "prefix", "principal", "interest", "fees", "expected"),
    [
        (
            AccountType.loan,
            "i5l-loan",
            "500000.123456",
            "2500.100000",
            "99.000001",
            "502599.223457",
        ),
        (
            AccountType.mortgage,
            "i5l-mortgage",
            "999999999999.999999",
            "0",
            "0",
            "999999999999.999999",
        ),
    ],
)
async def test_liability_types_preserve_exact_money_components(
    account_type: AccountType,
    prefix: str,
    principal: str,
    interest: str,
    fees: str,
    expected: str,
) -> None:
    balance = _balance(
        prefix,
        suffix="exact",
        effective_at=SNAPSHOT_AT,
        principal=principal,
        interest=interest,
        fees=fees,
    )
    await _seed(prefix, account_type=account_type, balances=(balance,))
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            result = await LiabilityBalanceEvidenceService(session).select(_command(prefix))
            assert result.outstanding_principal == Decimal(principal)
            assert result.accrued_interest == Decimal(interest)
            assert result.fees_outstanding == Decimal(fees)
            assert result.total_outstanding == Decimal(expected)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_future_observation_is_ignored() -> None:
    prefix = "i5l-future"
    eligible = _balance(
        prefix,
        suffix="eligible",
        effective_at=SNAPSHOT_AT - timedelta(milliseconds=1),
        principal="70",
    )
    future = _balance(
        prefix,
        suffix="future",
        effective_at=SNAPSHOT_AT + timedelta(milliseconds=1),
        principal="90",
    )
    await _seed(
        prefix,
        account_type=AccountType.credit_card,
        balances=(eligible, future),
    )
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            result = await LiabilityBalanceEvidenceService(session).select(_command(prefix))
            assert result.balance_id == f"{prefix}-balance-eligible"
            assert result.total_outstanding == Decimal("70.000000")
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_missing_evidence_fails_without_mutation() -> None:
    prefix = "i5l-missing"
    await _seed(prefix, account_type=AccountType.loan, balances=())
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            before = await _counts(session, prefix)
            with pytest.raises(
                LiabilityBalanceEvidenceStateError,
                match=r"^Liability balance evidence is unavailable\.$",
            ):
                await LiabilityBalanceEvidenceService(session).select(_command(prefix))
            assert await _counts(session, prefix) == before == (1, 0, 0, 0)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_same_latest_timestamp_from_different_sources_is_ambiguous() -> None:
    prefix = "i5l-ambiguous"
    statement = _balance(
        prefix,
        suffix="statement",
        effective_at=SNAPSHOT_AT,
        principal="10",
    )
    provider = _balance(
        prefix,
        suffix="provider",
        effective_at=SNAPSHOT_AT,
        principal="11",
        source=LiabilityBalanceSource.provider,
    )
    await _seed(
        prefix,
        account_type=AccountType.credit_card,
        balances=(statement, provider),
    )
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            before = await _counts(session, prefix)
            with pytest.raises(LiabilityBalanceEvidenceStateError):
                await LiabilityBalanceEvidenceService(session).select(_command(prefix))
            assert await _counts(session, prefix) == before
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_currency_mismatch_is_persisted_corruption() -> None:
    prefix = "i5l-currency"
    mismatch = _balance(
        prefix,
        suffix="mismatch",
        effective_at=SNAPSHOT_AT,
        principal="10",
        currency="EUR",
    )
    await _seed(
        prefix,
        account_type=AccountType.loan,
        balances=(mismatch,),
        currency="CZK",
    )
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            before = await _counts(session, prefix)
            with pytest.raises(LiabilityBalanceEvidenceStateError):
                await LiabilityBalanceEvidenceService(session).select(_command(prefix))
            assert await _counts(session, prefix) == before
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("account_type", "prefix"),
    [
        (AccountType.bank, "i5l-bank"),
        (AccountType.broker, "i5l-broker"),
    ],
)
async def test_non_liability_account_type_is_rejected(
    account_type: AccountType,
    prefix: str,
) -> None:
    balance = _balance(
        prefix,
        suffix="invalid-type",
        effective_at=SNAPSHOT_AT,
        principal="10",
    )
    await _seed(prefix, account_type=account_type, balances=(balance,))
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            before = await _counts(session, prefix)
            with pytest.raises(LiabilityBalanceEvidenceStateError):
                await LiabilityBalanceEvidenceService(session).select(_command(prefix))
            assert await _counts(session, prefix) == before
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_archived_account_is_rejected() -> None:
    prefix = "i5l-archived"
    balance = _balance(
        prefix,
        suffix="archived",
        effective_at=SNAPSHOT_AT,
        principal="10",
    )
    await _seed(
        prefix,
        account_type=AccountType.mortgage,
        balances=(balance,),
        archived=True,
    )
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            before = await _counts(session, prefix)
            with pytest.raises(LiabilityBalanceEvidenceStateError):
                await LiabilityBalanceEvidenceService(session).select(_command(prefix))
            assert await _counts(session, prefix) == before
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_selection_respects_caller_owned_transaction_and_rollback() -> None:
    prefix = "i5l-caller-transaction"
    await _cleanup(prefix)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            await session.begin()
            session.add(_account(prefix, account_type=AccountType.credit_card))
            session.add(
                _balance(
                    prefix,
                    suffix="uncommitted",
                    effective_at=SNAPSHOT_AT,
                    principal="42",
                )
            )
            await session.flush()
            result = await LiabilityBalanceEvidenceService(session).select(_command(prefix))
            assert result.total_outstanding == Decimal("42.000000")
            await session.rollback()

        async with AsyncSession(engine) as independent:
            assert await _counts(independent, prefix) == (0, 0, 0, 0)
    finally:
        await engine.dispose()
        await _cleanup(prefix)
