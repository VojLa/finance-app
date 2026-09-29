from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.accounts import AccountModel
from app.db.models.canonical_lineage import (
    AccountCanonicalChangeModel,
    AccountCanonicalStateModel,
)
from app.db.models.enums import AccountType, LiabilityBalanceSource
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.db.models.transactions import TransactionModel
from app.db.url import normalize_database_url
from app.modules.liabilities import (
    LiabilityBalanceEvidenceService,
    LiabilityBalanceWriteConflictError,
    LiabilityBalanceWriteDisposition,
    LiabilityBalanceWriter,
    LiabilityBalanceWriteStateError,
    SelectLiabilityBalanceCommand,
    WriteLiabilityBalanceCommand,
)
from app.modules.liabilities.writer_repository import LiabilityBalanceWriterRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
EFFECTIVE_AT = datetime(2026, 7, 28, 10, 20, 30, 123000)
CREATED_AT = datetime(2026, 7, 28, 10, 21, 0, 456000)
RUN_ID = uuid4().hex[:12]
_active_prefixes: set[str] = set()


def _prefix(value: str) -> str:
    prefix = f"{value}-{RUN_ID}"
    _active_prefixes.add(prefix)
    return prefix


@pytest.fixture(autouse=True)
async def _cleanup_after_test():
    try:
        yield
    finally:
        for prefix in tuple(_active_prefixes):
            await _cleanup(prefix)
        _active_prefixes.clear()


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=10)


def _account(
    prefix: str,
    *,
    account_type: AccountType = AccountType.loan,
    currency: str = "CZK",
) -> AccountModel:
    return AccountModel(
        id=f"{prefix}-account",
        name=f"{prefix} liability",
        type=account_type,
        currency=currency,
        color=None,
        notes=None,
        is_archived=False,
        archived_at=None,
        created_at=datetime(2026, 1, 1),
        updated_at=CREATED_AT,
    )


def _command(
    prefix: str,
    **changes: Any,
) -> WriteLiabilityBalanceCommand:
    values: dict[str, Any] = {
        "account_id": f"{prefix}-account",
        "effective_at": EFFECTIVE_AT,
        "currency": "CZK",
        "outstanding_principal": Decimal("100.123456"),
        "accrued_interest": Decimal("2.000001"),
        "fees_outstanding": Decimal("3.100000"),
        "source": LiabilityBalanceSource.statement,
        "external_id": f"{prefix}-statement-42",
        "created_at": CREATED_AT,
    }
    values.update(changes)
    return WriteLiabilityBalanceCommand(**values)


async def _cleanup(*prefixes: str) -> None:
    engine = _engine()
    account_ids = tuple(f"{prefix}-account" for prefix in prefixes)
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
            delete(TransactionModel).where(TransactionModel.account_id.in_(account_ids))
        )
        await session.execute(
            delete(LiabilityBalanceModel).where(LiabilityBalanceModel.account_id.in_(account_ids))
        )
        await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        await session.commit()
    await engine.dispose()


async def _seed(
    prefix: str,
    *,
    account_type: AccountType = AccountType.loan,
    currency: str = "CZK",
) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(_account(prefix, account_type=account_type, currency=currency))
        await session.commit()
    await engine.dispose()


async def _rows(prefix: str) -> tuple[LiabilityBalanceModel, ...]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        rows = tuple(
            await session.scalars(
                select(LiabilityBalanceModel)
                .where(LiabilityBalanceModel.account_id == f"{prefix}-account")
                .order_by(LiabilityBalanceModel.effective_at, LiabilityBalanceModel.id)
            )
        )
    await engine.dispose()
    return rows


async def _out_of_scope_counts(prefix: str) -> tuple[int, int, int]:
    engine = _engine()
    account_id = f"{prefix}-account"
    async with AsyncSession(engine) as session:
        snapshot_ids = tuple(
            await session.scalars(
                select(AccountSnapshotModel.id).where(AccountSnapshotModel.account_id == account_id)
            )
        )
        counts = (
            await session.scalar(
                select(func.count())
                .select_from(TransactionModel)
                .where(TransactionModel.account_id == account_id)
            )
            or 0,
            len(snapshot_ids),
            (
                await session.scalar(
                    select(func.count())
                    .select_from(AccountSnapshotItemModel)
                    .where(AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids))
                )
                if snapshot_ids
                else 0
            )
            or 0,
        )
    await engine.dispose()
    return counts


@pytest.mark.asyncio
async def test_loan_create_exact_replay_and_read_selector_compatibility() -> None:
    prefix = _prefix("l2a-loan-replay")
    await _seed(prefix)
    engine = _engine()
    command = _command(prefix)
    async with AsyncSession(engine) as session:
        first = await LiabilityBalanceWriter(session).write(command)
    async with AsyncSession(engine) as session:
        second = await LiabilityBalanceWriter(session).write(command)
    async with AsyncSession(engine) as session:
        evidence = await LiabilityBalanceEvidenceService(session).select(
            SelectLiabilityBalanceCommand(
                account_id=command.account_id,
                snapshot_timestamp=command.effective_at,
            )
        )
        await session.rollback()

    rows = await _rows(prefix)
    assert first.disposition is LiabilityBalanceWriteDisposition.created
    assert second.disposition is LiabilityBalanceWriteDisposition.replayed
    assert first.balance_id == second.balance_id == rows[0].id == evidence.balance_id
    assert len(rows) == 1
    assert rows[0].outstanding_principal == Decimal("100.123456")
    assert rows[0].accrued_interest == Decimal("2.000001")
    assert rows[0].fees_outstanding == Decimal("3.100000")
    assert rows[0].total_outstanding == evidence.total_outstanding == Decimal("105.223457")
    assert rows[0].created_at == CREATED_AT
    async with AsyncSession(engine) as session:
        state = await session.get(AccountCanonicalStateModel, command.account_id)
        change = await session.scalar(
            select(AccountCanonicalChangeModel).where(
                AccountCanonicalChangeModel.kind == "liability_balance",
                AccountCanonicalChangeModel.entity_id == rows[0].id,
            )
        )
        assert state is not None and change is not None
        assert (state.last_revision, state.last_investment_revision) == (1, 0)
        assert change.revision == 1
        assert change.financial_timestamp == command.effective_at
        assert change.created_at == command.created_at
    assert await _out_of_scope_counts(prefix) == (0, 0, 0)
    await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.parametrize(
    ("prefix", "account_type", "command"),
    [
        (
            "l2a-loan",
            AccountType.loan,
            {
                "outstanding_principal": Decimal("500000.123456"),
                "accrued_interest": Decimal("123.000001"),
                "fees_outstanding": Decimal("10.100000"),
            },
        ),
        (
            "l2a-mortgage",
            AccountType.mortgage,
            {
                "outstanding_principal": Decimal("999999999999.999999"),
                "accrued_interest": Decimal(0),
                "fees_outstanding": Decimal(0),
            },
        ),
        (
            "l2a-zero",
            AccountType.loan,
            {
                "outstanding_principal": Decimal(0),
                "accrued_interest": Decimal(0),
                "fees_outstanding": Decimal(0),
            },
        ),
    ],
)
@pytest.mark.asyncio
async def test_exact_component_boundaries_persist(
    prefix: str,
    account_type: AccountType,
    command: dict[str, Decimal],
) -> None:
    prefix = _prefix(prefix)
    await _seed(prefix, account_type=account_type)
    engine = _engine()
    async with AsyncSession(engine) as session:
        result = await LiabilityBalanceWriter(session).write(_command(prefix, **command))
    rows = await _rows(prefix)
    assert result.disposition is LiabilityBalanceWriteDisposition.created
    assert rows[0].total_outstanding == sum(command.values(), Decimal(0))
    assert len(rows) == 1
    await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.parametrize(
    "account_type", [AccountType.bank, AccountType.broker, AccountType.credit_card]
)
@pytest.mark.asyncio
async def test_unsupported_account_fails_without_write(account_type: AccountType) -> None:
    prefix = _prefix(f"l2a-unsupported-{account_type.value}")
    await _seed(prefix, account_type=account_type)
    engine = _engine()
    async with AsyncSession(engine) as session:
        with pytest.raises(LiabilityBalanceWriteStateError):
            await LiabilityBalanceWriter(session).write(_command(prefix))
    assert await _rows(prefix) == ()
    assert await _out_of_scope_counts(prefix) == (0, 0, 0)
    await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_account_currency_mismatch_fails_without_write() -> None:
    prefix = _prefix("l2a-currency")
    await _seed(prefix, currency="EUR")
    engine = _engine()
    async with AsyncSession(engine) as session:
        with pytest.raises(LiabilityBalanceWriteStateError):
            await LiabilityBalanceWriter(session).write(_command(prefix))
    assert await _rows(prefix) == ()
    await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_timestamp_identity_conflict_preserves_original() -> None:
    prefix = _prefix("l2a-time-conflict")
    await _seed(prefix)
    engine = _engine()
    original = _command(prefix)
    async with AsyncSession(engine) as session:
        await LiabilityBalanceWriter(session).write(original)
    conflicting = _command(prefix, outstanding_principal=Decimal("101.123456"))
    async with AsyncSession(engine) as session:
        with pytest.raises(LiabilityBalanceWriteConflictError):
            await LiabilityBalanceWriter(session).write(conflicting)
    rows = await _rows(prefix)
    assert len(rows) == 1
    assert rows[0].outstanding_principal == original.outstanding_principal
    await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_external_identity_conflict_preserves_original() -> None:
    prefix = _prefix("l2a-external-conflict")
    await _seed(prefix)
    engine = _engine()
    original = _command(prefix)
    async with AsyncSession(engine) as session:
        await LiabilityBalanceWriter(session).write(original)
    conflicting = _command(prefix, effective_at=EFFECTIVE_AT + timedelta(seconds=1))
    async with AsyncSession(engine) as session:
        with pytest.raises(LiabilityBalanceWriteConflictError):
            await LiabilityBalanceWriter(session).write(conflicting)
    rows = await _rows(prefix)
    assert len(rows) == 1
    assert rows[0].effective_at == original.effective_at
    await engine.dispose()
    await _cleanup(prefix)


class _ReloadFailureRepository(LiabilityBalanceWriterRepository):
    async def reload(self, balance_id: str) -> LiabilityBalanceModel | None:
        await super().reload(balance_id)
        return None


class _ConstraintFailureRepository(LiabilityBalanceWriterRepository):
    def add(self, balance: LiabilityBalanceModel) -> None:
        balance.total_outstanding = Decimal("-1")
        super().add(balance)


@pytest.mark.parametrize(
    "repository_type",
    [_ReloadFailureRepository, _ConstraintFailureRepository],
)
@pytest.mark.asyncio
async def test_failure_after_add_or_flush_rolls_back_and_clean_retry_succeeds(
    repository_type: type[LiabilityBalanceWriterRepository],
) -> None:
    prefix = _prefix(f"l2a-rollback-{repository_type.__name__.lower()}")
    await _seed(prefix)
    engine = _engine()
    command = _command(prefix)
    async with AsyncSession(engine) as session:
        with pytest.raises(LiabilityBalanceWriteStateError):
            await LiabilityBalanceWriter(
                session,
                repository=repository_type(session),
            ).write(command)
    assert await _rows(prefix) == ()
    async with AsyncSession(engine) as session:
        result = await LiabilityBalanceWriter(session).write(command)
    assert result.disposition is LiabilityBalanceWriteDisposition.created
    assert len(await _rows(prefix)) == 1
    await engine.dispose()
    await _cleanup(prefix)


class _HoldingReloadRepository(LiabilityBalanceWriterRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        holding: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        super().__init__(session)
        self.holding = holding
        self.release = release

    async def reload(self, balance_id: str) -> LiabilityBalanceModel | None:
        row = await super().reload(balance_id)
        self.holding.set()
        await asyncio.wait_for(self.release.wait(), timeout=10)
        return row


class _PidRepository(LiabilityBalanceWriterRepository):
    def __init__(self, session: AsyncSession, *, pid_ready: asyncio.Future[int]) -> None:
        super().__init__(session)
        self.pid_ready = pid_ready

    async def load_account_for_share(self, account_id: str) -> AccountModel | None:
        pid = await self.session.scalar(select(func.pg_backend_pid()))
        assert pid is not None
        if not self.pid_ready.done():
            self.pid_ready.set_result(pid)
        return await super().load_account_for_share(account_id)


async def _wait_for_advisory_lock(engine: Any, pid: int) -> None:
    try:
        async with asyncio.timeout(10):
            while True:
                async with AsyncSession(engine) as inspector:
                    waiting = await inspector.scalar(
                        text(
                            "SELECT EXISTS ("
                            "SELECT 1 FROM pg_locks "
                            "WHERE pid = :pid AND locktype = 'advisory' AND NOT granted)"
                        ),
                        {"pid": pid},
                    )
                if waiting:
                    return
    except TimeoutError as exc:
        raise AssertionError(
            "PostgreSQL backend did not wait on a liability advisory lock"
        ) from exc


async def _wait_for_blocker(engine: Any, pid: int) -> None:
    try:
        async with asyncio.timeout(10):
            while True:
                async with AsyncSession(engine) as inspector:
                    blocked = await inspector.scalar(
                        text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": pid},
                    )
                if blocked:
                    return
    except TimeoutError as exc:
        raise AssertionError("PostgreSQL backend did not wait on the locked Account row") from exc


@pytest.mark.asyncio
async def test_same_command_concurrency_creates_once_then_replays_with_proven_wait() -> None:
    prefix = _prefix("l2a-concurrent-same")
    await _seed(prefix)
    engine = _engine()
    holding, release = asyncio.Event(), asyncio.Event()
    pid_ready = asyncio.get_running_loop().create_future()
    command = _command(prefix)

    async with AsyncSession(engine) as first_session, AsyncSession(engine) as second_session:
        first = asyncio.create_task(
            LiabilityBalanceWriter(
                first_session,
                repository=_HoldingReloadRepository(
                    first_session,
                    holding=holding,
                    release=release,
                ),
            ).write(command)
        )
        await asyncio.wait_for(holding.wait(), timeout=10)
        second = asyncio.create_task(
            LiabilityBalanceWriter(
                second_session,
                repository=_PidRepository(second_session, pid_ready=pid_ready),
            ).write(command)
        )
        await _wait_for_advisory_lock(engine, await asyncio.wait_for(pid_ready, timeout=10))
        release.set()
        first_result, second_result = await asyncio.wait_for(
            asyncio.gather(first, second), timeout=10
        )

    assert first_result.disposition is LiabilityBalanceWriteDisposition.created
    assert second_result.disposition is LiabilityBalanceWriteDisposition.replayed
    assert first_result.balance_id == second_result.balance_id
    assert len(await _rows(prefix)) == 1
    await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_same_timestamp_different_values_concurrency_creates_once_and_conflicts_once() -> (
    None
):
    prefix = _prefix("l2a-concurrent-timestamp")
    await _seed(prefix)
    engine = _engine()
    holding, release = asyncio.Event(), asyncio.Event()
    pid_ready = asyncio.get_running_loop().create_future()
    first_command = _command(prefix)
    second_command = _command(prefix, outstanding_principal=Decimal("101.123456"))

    async with AsyncSession(engine) as first_session, AsyncSession(engine) as second_session:
        first = asyncio.create_task(
            LiabilityBalanceWriter(
                first_session,
                repository=_HoldingReloadRepository(
                    first_session,
                    holding=holding,
                    release=release,
                ),
            ).write(first_command)
        )
        await asyncio.wait_for(holding.wait(), timeout=10)
        second = asyncio.create_task(
            LiabilityBalanceWriter(
                second_session,
                repository=_PidRepository(second_session, pid_ready=pid_ready),
            ).write(second_command)
        )
        await _wait_for_advisory_lock(engine, await asyncio.wait_for(pid_ready, timeout=10))
        release.set()
        first_result = await asyncio.wait_for(first, timeout=10)
        with pytest.raises(LiabilityBalanceWriteConflictError):
            await asyncio.wait_for(second, timeout=10)

    assert first_result.disposition is LiabilityBalanceWriteDisposition.created
    rows = await _rows(prefix)
    assert len(rows) == 1
    assert rows[0].outstanding_principal == first_command.outstanding_principal
    await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_same_external_identity_concurrency_creates_once_and_conflicts_once() -> None:
    prefix = _prefix("l2a-concurrent-external")
    await _seed(prefix)
    engine = _engine()
    holding, release = asyncio.Event(), asyncio.Event()
    pid_ready = asyncio.get_running_loop().create_future()
    first_command = _command(prefix)
    second_command = _command(prefix, effective_at=EFFECTIVE_AT + timedelta(seconds=1))

    async with AsyncSession(engine) as first_session, AsyncSession(engine) as second_session:
        first = asyncio.create_task(
            LiabilityBalanceWriter(
                first_session,
                repository=_HoldingReloadRepository(
                    first_session,
                    holding=holding,
                    release=release,
                ),
            ).write(first_command)
        )
        await asyncio.wait_for(holding.wait(), timeout=10)
        second = asyncio.create_task(
            LiabilityBalanceWriter(
                second_session,
                repository=_PidRepository(second_session, pid_ready=pid_ready),
            ).write(second_command)
        )
        await _wait_for_advisory_lock(engine, await asyncio.wait_for(pid_ready, timeout=10))
        release.set()
        first_result = await asyncio.wait_for(first, timeout=10)
        with pytest.raises(LiabilityBalanceWriteConflictError):
            await asyncio.wait_for(second, timeout=10)

    assert first_result.disposition is LiabilityBalanceWriteDisposition.created
    assert len(await _rows(prefix)) == 1
    await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_same_account_different_manual_timestamps_serialize_canonical_revisions() -> None:
    prefix = _prefix("l2a-parallel-timestamps")
    await _seed(prefix)
    engine = _engine()
    holding, release = asyncio.Event(), asyncio.Event()
    pid_ready = asyncio.get_running_loop().create_future()
    first_command = _command(
        prefix,
        source=LiabilityBalanceSource.manual,
        external_id=None,
    )
    second_command = _command(
        prefix,
        effective_at=EFFECTIVE_AT + timedelta(seconds=1),
        source=LiabilityBalanceSource.manual,
        external_id=None,
    )

    async with AsyncSession(engine) as first_session, AsyncSession(engine) as second_session:
        first = asyncio.create_task(
            LiabilityBalanceWriter(
                first_session,
                repository=_HoldingReloadRepository(
                    first_session,
                    holding=holding,
                    release=release,
                ),
            ).write(first_command)
        )
        await asyncio.wait_for(holding.wait(), timeout=10)
        second = asyncio.create_task(
            LiabilityBalanceWriter(
                second_session,
                repository=_PidRepository(second_session, pid_ready=pid_ready),
            ).write(second_command)
        )
        await _wait_for_blocker(engine, await asyncio.wait_for(pid_ready, timeout=10))
        release.set()
        first_result = await asyncio.wait_for(first, timeout=10)
        second_result = await asyncio.wait_for(second, timeout=10)

    assert first_result.disposition is LiabilityBalanceWriteDisposition.created
    assert second_result.disposition is LiabilityBalanceWriteDisposition.created
    assert len(await _rows(prefix)) == 2
    await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_concurrent_archive_committed_before_account_lock_causes_zero_write() -> None:
    prefix = _prefix("l2a-concurrent-archive")
    await _seed(prefix)
    engine = _engine()
    pid_ready = asyncio.get_running_loop().create_future()

    async with AsyncSession(engine) as archiver, AsyncSession(engine) as writer_session:
        await archiver.begin()
        account = await archiver.scalar(
            select(AccountModel).where(AccountModel.id == f"{prefix}-account").with_for_update()
        )
        assert account is not None
        account.is_archived = True
        account.archived_at = CREATED_AT
        writer = asyncio.create_task(
            LiabilityBalanceWriter(
                writer_session,
                repository=_PidRepository(writer_session, pid_ready=pid_ready),
            ).write(_command(prefix))
        )
        await _wait_for_blocker(engine, await asyncio.wait_for(pid_ready, timeout=10))
        await archiver.commit()
        with pytest.raises(LiabilityBalanceWriteStateError):
            await asyncio.wait_for(writer, timeout=10)

    assert await _rows(prefix) == ()
    await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_different_accounts_do_not_share_a_global_liability_lock() -> None:
    first_prefix = _prefix("l2a-parallel-a")
    second_prefix = _prefix("l2a-parallel-b")
    await _seed(first_prefix)
    await _seed(second_prefix)
    engine = _engine()
    holding, release = asyncio.Event(), asyncio.Event()

    async with AsyncSession(engine) as first_session, AsyncSession(engine) as second_session:
        first = asyncio.create_task(
            LiabilityBalanceWriter(
                first_session,
                repository=_HoldingReloadRepository(
                    first_session,
                    holding=holding,
                    release=release,
                ),
            ).write(_command(first_prefix))
        )
        await asyncio.wait_for(holding.wait(), timeout=10)
        second = await asyncio.wait_for(
            LiabilityBalanceWriter(second_session).write(_command(second_prefix)),
            timeout=2,
        )
        assert second.disposition is LiabilityBalanceWriteDisposition.created
        release.set()
        first_result = await asyncio.wait_for(first, timeout=10)

    assert first_result.disposition is LiabilityBalanceWriteDisposition.created
    assert len(await _rows(first_prefix)) == len(await _rows(second_prefix)) == 1
    await engine.dispose()
    await _cleanup(first_prefix, second_prefix)
