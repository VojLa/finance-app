"""PostgreSQL evidence for coordinated, resumable user snapshot refresh."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    ExchangeRateSource,
    LiabilityBalanceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.prices import ExchangeRateModel
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.net_worth.evidence_service import SelectedAccountSnapshotIdentity
from app.modules.net_worth.writer import (
    NetWorthSnapshotWriter,
    NetWorthSnapshotWriteResult,
    NetWorthSnapshotWriteStateError,
    WriteNetWorthSnapshotCommand,
)
from app.modules.snapshot_refresh.executor import (
    AccountSnapshotRefreshExecutionDisposition,
    ExecuteUserSnapshotRefreshCommand,
    SnapshotRefreshExecutionConflictError,
    SnapshotRefreshExecutionStateError,
    UserSnapshotRefreshExecutor,
)
from app.modules.snapshots.writer import (
    AccountSnapshotWriter,
    WriteAccountSnapshotCommand,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required",
)
AT = datetime(2034, 6, 1)
EVIDENCE_AT = AT - timedelta(days=1)


def _engine() -> AsyncEngine:
    assert DATABASE_URL is not None
    return create_async_engine(
        normalize_database_url(DATABASE_URL),
        pool_size=12,
    )


@dataclass(frozen=True, slots=True)
class _AccountSpec:
    suffix: str
    role: AccountMemberRole = AccountMemberRole.owner
    currency: str = "EUR"
    amount: Decimal = Decimal("100")
    with_rate: bool = True


def _user_id(prefix: str) -> str:
    return f"{prefix}-user"


def _account_id(prefix: str, suffix: str) -> str:
    return f"{prefix}-{suffix}"


def _command(prefix: str) -> ExecuteUserSnapshotRefreshCommand:
    return ExecuteUserSnapshotRefreshCommand(
        user_id=_user_id(prefix),
        snapshot_timestamp=AT,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        calculated_at=AT,
        created_at=AT,
        is_recalculated=True,
    )


def _account_command(account_id: str) -> WriteAccountSnapshotCommand:
    return WriteAccountSnapshotCommand(
        account_id=account_id,
        snapshot_timestamp=AT,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        calculated_at=AT,
        created_at=AT,
        is_recalculated=True,
        output_currency="EUR",
    )


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        user_ids = tuple(
            await session.scalars(select(UserModel.id).where(UserModel.id.startswith(f"{prefix}-")))
        )
        account_ids = tuple(
            await session.scalars(
                select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
            )
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
        if user_ids:
            await session.execute(
                delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id.in_(user_ids))
            )
        if account_ids:
            await session.execute(
                delete(AccountSnapshotModel).where(AccountSnapshotModel.account_id.in_(account_ids))
            )
            await session.execute(
                delete(LiabilityBalanceModel).where(
                    LiabilityBalanceModel.account_id.in_(account_ids)
                )
            )
            await session.execute(
                delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
            )
            await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        await session.execute(
            delete(ExchangeRateModel).where(ExchangeRateModel.id.startswith(f"{prefix}-"))
        )
        if user_ids:
            await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        await session.commit()
    await engine.dispose()


async def _seed(prefix: str, specs: tuple[_AccountSpec, ...]) -> None:
    await _cleanup(prefix)
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            UserModel(
                id=_user_id(prefix),
                email=f"{prefix}@example.test",
                name="Coordinated refresh",
                password_hash=None,
                base_currency="EUR",
                created_at=EVIDENCE_AT,
                updated_at=EVIDENCE_AT,
            )
        )
        needs_eur_pivot = False
        for spec in specs:
            account_id = _account_id(prefix, spec.suffix)
            session.add(
                AccountModel(
                    id=account_id,
                    name=spec.suffix,
                    type=AccountType.loan,
                    currency=spec.currency,
                    color=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=EVIDENCE_AT,
                    updated_at=EVIDENCE_AT,
                    notes=None,
                )
            )
            await session.flush()
            session.add(
                AccountMemberModel(
                    id=f"{prefix}-member-{spec.suffix}",
                    account_id=account_id,
                    user_id=_user_id(prefix),
                    role=spec.role,
                    relation_type=AccountRelationType.owner,
                    invited_by_id=None,
                    accepted_at=EVIDENCE_AT,
                    created_at=EVIDENCE_AT,
                    updated_at=EVIDENCE_AT,
                )
            )
            session.add(
                LiabilityBalanceModel(
                    id=f"{prefix}-balance-{spec.suffix}",
                    account_id=account_id,
                    effective_at=EVIDENCE_AT,
                    currency=spec.currency,
                    outstanding_principal=spec.amount,
                    accrued_interest=Decimal("0"),
                    fees_outstanding=Decimal("0"),
                    total_outstanding=spec.amount,
                    source=LiabilityBalanceSource.statement,
                    external_id=f"{prefix}-external-{spec.suffix}",
                    created_at=EVIDENCE_AT,
                )
            )
            if spec.currency != "EUR" and spec.with_rate:
                needs_eur_pivot = True
                session.add(
                    ExchangeRateModel(
                        id=f"{prefix}-rate-{spec.suffix}",
                        from_currency=spec.currency,
                        to_currency="CZK",
                        rate=Decimal("18.00000000"),
                        date=EVIDENCE_AT,
                        source=ExchangeRateSource.cnb,
                        created_at=EVIDENCE_AT,
                    )
                )
        if needs_eur_pivot:
            session.add(
                ExchangeRateModel(
                    id=f"{prefix}-rate-eur-pivot",
                    from_currency="EUR",
                    to_currency="CZK",
                    rate=Decimal("20.00000000"),
                    date=EVIDENCE_AT,
                    source=ExchangeRateSource.cnb,
                    created_at=EVIDENCE_AT,
                )
            )
        await session.commit()
    await engine.dispose()


async def _write_existing_snapshot(prefix: str, suffix: str) -> str:
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            result = await AccountSnapshotWriter(session).write(
                _account_command(_account_id(prefix, suffix))
            )
        return result.snapshot_id
    finally:
        await engine.dispose()


async def _counts(prefix: str) -> tuple[int, int, int]:
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            account_ids = select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
            account_snapshots = await session.scalar(
                select(func.count())
                .select_from(AccountSnapshotModel)
                .where(AccountSnapshotModel.account_id.in_(account_ids))
            )
            items = await session.scalar(
                select(func.count())
                .select_from(AccountSnapshotItemModel)
                .join(
                    AccountSnapshotModel,
                    AccountSnapshotModel.id == AccountSnapshotItemModel.snapshot_id,
                )
                .where(AccountSnapshotModel.account_id.in_(account_ids))
            )
            net_worth = await session.scalar(
                select(func.count())
                .select_from(NetWorthSnapshotModel)
                .where(NetWorthSnapshotModel.user_id == _user_id(prefix))
            )
        return int(account_snapshots or 0), int(items or 0), int(net_worth or 0)
    finally:
        await engine.dispose()


class _TrackingAccountWriter:
    def __init__(
        self,
        session: AsyncSession,
        calls: list[str],
    ) -> None:
        self.delegate = AccountSnapshotWriter(session)
        self.calls = calls

    async def write(self, command: WriteAccountSnapshotCommand) -> Any:
        self.calls.append(command.account_id)
        return await self.delegate.write(command)


class _TrackingAccountFactory:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, session: AsyncSession) -> _TrackingAccountWriter:
        return _TrackingAccountWriter(session, self.calls)


class _FailingNetWorthWriter:
    async def write(
        self,
        command: WriteNetWorthSnapshotCommand,
    ) -> NetWorthSnapshotWriteResult:
        raise NetWorthSnapshotWriteStateError()


class _MutationNetWorthWriter:
    def __init__(
        self,
        session: AsyncSession,
        mutate: Callable[[], Awaitable[None]],
    ) -> None:
        self.session = session
        self.mutate = mutate

    async def write(self, command: Any) -> Any:
        await self.mutate()
        return await NetWorthSnapshotWriter(self.session).write(command)


@pytest.mark.asyncio
async def test_mixed_refresh_reuse_create_and_fresh_session_replay() -> None:
    prefix = "k5d2-mixed"
    specs = (
        _AccountSpec("a-owner-gbp", currency="GBP"),
        _AccountSpec("b-editor-usd", AccountMemberRole.editor, "USD"),
        _AccountSpec("c-viewer", AccountMemberRole.viewer),
    )
    await _seed(prefix, specs)
    viewer_snapshot_id = await _write_existing_snapshot(prefix, "c-viewer")
    engine = _engine()
    first_factory = _TrackingAccountFactory()
    second_factory = _TrackingAccountFactory()
    try:
        async with AsyncSession(engine) as session:
            first = await UserSnapshotRefreshExecutor(
                session,
                account_writer_factory=first_factory,
            ).execute(_command(prefix))
        before_replay = await _counts(prefix)
        async with AsyncSession(engine) as session:
            second = await UserSnapshotRefreshExecutor(
                session,
                account_writer_factory=second_factory,
            ).execute(_command(prefix))

        expected_refresh = [
            _account_id(prefix, "a-owner-gbp"),
            _account_id(prefix, "b-editor-usd"),
        ]
        assert first_factory.calls == second_factory.calls == expected_refresh
        assert [item.disposition for item in first.account_snapshots] == [
            AccountSnapshotRefreshExecutionDisposition.created,
            AccountSnapshotRefreshExecutionDisposition.created,
            AccountSnapshotRefreshExecutionDisposition.reused,
        ]
        assert [item.disposition for item in second.account_snapshots] == [
            AccountSnapshotRefreshExecutionDisposition.replayed,
            AccountSnapshotRefreshExecutionDisposition.replayed,
            AccountSnapshotRefreshExecutionDisposition.reused,
        ]
        assert first.account_snapshots[-1].snapshot_id == viewer_snapshot_id
        assert first.required_account_snapshot_identities == tuple(
            SelectedAccountSnapshotIdentity(
                item.account_id,
                item.snapshot_id,
            )
            for item in first.account_snapshots
        )
        assert second.net_worth_snapshot_id == first.net_worth_snapshot_id
        assert first.selected_account_snapshot_count == 3
        assert len(first.required_account_snapshot_identities) == 3
        assert before_replay == await _counts(prefix) == (5, 0, 1)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_partial_account_failure_commits_prefix_and_exact_replay_resumes() -> None:
    prefix = "k5d2-resume"
    await _seed(
        prefix,
        (
            _AccountSpec("a-eur"),
            _AccountSpec("b-xzz", currency="XZZ", with_rate=False),
        ),
    )
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            with pytest.raises(SnapshotRefreshExecutionStateError):
                await UserSnapshotRefreshExecutor(session).execute(_command(prefix))
        assert await _counts(prefix) == (1, 0, 0)

        async with AsyncSession(engine) as session:
            session.add_all(
                (
                    ExchangeRateModel(
                        id=f"{prefix}-rate-b-xzz",
                        from_currency="XZZ",
                        to_currency="CZK",
                        rate=Decimal("18.00000000"),
                        date=EVIDENCE_AT,
                        source=ExchangeRateSource.cnb,
                        created_at=EVIDENCE_AT,
                    ),
                    ExchangeRateModel(
                        id=f"{prefix}-rate-eur-pivot",
                        from_currency="EUR",
                        to_currency="CZK",
                        rate=Decimal("20.00000000"),
                        date=EVIDENCE_AT,
                        source=ExchangeRateSource.cnb,
                        created_at=EVIDENCE_AT,
                    ),
                )
            )
            await session.commit()

        async with AsyncSession(engine) as session:
            resumed = await UserSnapshotRefreshExecutor(session).execute(_command(prefix))
        assert [item.disposition for item in resumed.account_snapshots] == [
            AccountSnapshotRefreshExecutionDisposition.replayed,
            AccountSnapshotRefreshExecutionDisposition.created,
        ]
        assert resumed.selected_account_snapshot_count == 2
        assert await _counts(prefix) == (3, 0, 1)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_failure_after_account_stage_keeps_commits_for_resume() -> None:
    prefix = "k5d2-net-failure"
    await _seed(prefix, (_AccountSpec("a"), _AccountSpec("b")))
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            executor = UserSnapshotRefreshExecutor(
                session,
                net_worth_writer_factory=lambda unused: _FailingNetWorthWriter(),
            )
            with pytest.raises(SnapshotRefreshExecutionStateError):
                await executor.execute(_command(prefix))
        assert await _counts(prefix) == (2, 0, 0)

        async with AsyncSession(engine) as session:
            resumed = await UserSnapshotRefreshExecutor(session).execute(_command(prefix))
        assert resumed.replayed_account_snapshot_count == 2
        assert await _counts(prefix) == (2, 0, 1)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_missing_viewer_coverage_stops_before_any_writer() -> None:
    prefix = "k5d2-viewer-missing"
    await _seed(
        prefix,
        (
            _AccountSpec("a-owner"),
            _AccountSpec("b-viewer", AccountMemberRole.viewer),
        ),
    )
    tracking = _TrackingAccountFactory()
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            with pytest.raises(SnapshotRefreshExecutionStateError):
                await UserSnapshotRefreshExecutor(
                    session,
                    account_writer_factory=tracking,
                ).execute(_command(prefix))
        assert tracking.calls == []
        assert await _counts(prefix) == (0, 0, 0)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


async def _insert_drift_account(
    prefix: str,
    suffix: str,
    *,
    remove_membership_suffix: str | None = None,
) -> None:
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            if remove_membership_suffix is not None:
                await session.execute(
                    delete(AccountMemberModel).where(
                        AccountMemberModel.id == f"{prefix}-member-{remove_membership_suffix}"
                    )
                )
            account_id = _account_id(prefix, suffix)
            session.add(
                AccountModel(
                    id=account_id,
                    name=suffix,
                    type=AccountType.loan,
                    currency="EUR",
                    color=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=EVIDENCE_AT,
                    updated_at=EVIDENCE_AT,
                    notes=None,
                )
            )
            await session.flush()
            session.add(
                AccountMemberModel(
                    id=f"{prefix}-member-{suffix}",
                    account_id=account_id,
                    user_id=_user_id(prefix),
                    role=AccountMemberRole.owner,
                    relation_type=AccountRelationType.owner,
                    invited_by_id=None,
                    accepted_at=EVIDENCE_AT,
                    created_at=EVIDENCE_AT,
                    updated_at=EVIDENCE_AT,
                )
            )
            await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.parametrize(
    ("prefix", "remove_suffix"),
    [
        ("k5d2-membership-drift", None),
        ("k5d2-substitution", "a"),
    ],
)
@pytest.mark.asyncio
async def test_d1_guard_rejects_membership_drift_and_same_count_substitution(
    prefix: str,
    remove_suffix: str | None,
) -> None:
    await _seed(prefix, (_AccountSpec("a"),))
    engine = _engine()

    async def mutation() -> None:
        await _insert_drift_account(
            prefix,
            "b",
            remove_membership_suffix=remove_suffix,
        )

    try:
        async with AsyncSession(engine) as session:
            executor = UserSnapshotRefreshExecutor(
                session,
                net_worth_writer_factory=lambda active: _MutationNetWorthWriter(
                    active,
                    mutation,
                ),
            )
            with pytest.raises(SnapshotRefreshExecutionStateError):
                await executor.execute(_command(prefix))
        assert await _counts(prefix) == (1, 0, 0)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_empty_user_creates_zero_net_worth_and_replays() -> None:
    prefix = "k5d2-empty"
    await _seed(prefix, ())
    tracking = _TrackingAccountFactory()
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            first = await UserSnapshotRefreshExecutor(
                session,
                account_writer_factory=tracking,
            ).execute(_command(prefix))
        async with AsyncSession(engine) as session:
            second = await UserSnapshotRefreshExecutor(
                session,
                account_writer_factory=tracking,
            ).execute(_command(prefix))
        assert tracking.calls == []
        assert first.required_account_snapshot_identities == ()
        assert second.required_account_snapshot_identities == ()
        assert first.net_worth_snapshot_id == second.net_worth_snapshot_id
        assert await _counts(prefix) == (0, 0, 1)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_concurrent_same_command_converges_without_duplicates() -> None:
    prefix = "k5d2-concurrent"
    await _seed(prefix, (_AccountSpec("a"),))
    engine = _engine()
    try:

        async def execute_once() -> Any:
            async with AsyncSession(engine) as session:
                return await UserSnapshotRefreshExecutor(session).execute(_command(prefix))

        first, second = await asyncio.wait_for(
            asyncio.gather(execute_once(), execute_once()),
            timeout=20,
        )
        account_dispositions = {
            first.account_snapshots[0].disposition,
            second.account_snapshots[0].disposition,
        }
        assert account_dispositions == {
            AccountSnapshotRefreshExecutionDisposition.created,
            AccountSnapshotRefreshExecutionDisposition.replayed,
        }
        assert first.net_worth_snapshot_id == second.net_worth_snapshot_id
        assert await _counts(prefix) == (1, 0, 1)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_physical_account_conflict_maps_without_repair() -> None:
    prefix = "k5d2-conflict"
    await _seed(prefix, (_AccountSpec("a"),))
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            first = await UserSnapshotRefreshExecutor(session).execute(_command(prefix))
        snapshot_id = first.account_snapshots[0].snapshot_id
        corrupted_at = AT + timedelta(minutes=1)
        async with AsyncSession(engine) as session:
            await session.execute(
                update(AccountSnapshotModel)
                .where(AccountSnapshotModel.id == snapshot_id)
                .values(created_at=corrupted_at)
            )
            await session.commit()

        async with AsyncSession(engine) as session:
            with pytest.raises(SnapshotRefreshExecutionConflictError):
                await UserSnapshotRefreshExecutor(session).execute(_command(prefix))
        async with AsyncSession(engine) as session:
            persisted = await session.get(AccountSnapshotModel, snapshot_id)
            assert persisted is not None
            assert persisted.created_at == corrupted_at
        assert await _counts(prefix) == (1, 0, 1)
    finally:
        await engine.dispose()
        await _cleanup(prefix)
