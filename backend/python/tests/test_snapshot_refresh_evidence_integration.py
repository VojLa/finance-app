"""PostgreSQL evidence for coherent read-only snapshot-refresh coverage."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, event, func, select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.snapshot_refresh import (
    BuildSnapshotRefreshCoverageCommand,
    CompleteSnapshotRefreshCoverage,
    SnapshotRefreshEvidenceService,
    SnapshotRefreshEvidenceStateError,
)
from app.modules.snapshot_refresh.repository import (
    SnapshotRefreshEvidenceRepository,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="DATABASE_URL is required",
)
NOW = datetime(2033, 8, 1)


def _engine() -> AsyncEngine:
    assert DATABASE_URL is not None
    return create_async_engine(
        normalize_database_url(DATABASE_URL),
        pool_size=8,
    )


@asynccontextmanager
async def _repeatable_session(
    engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="REPEATABLE READ")
        async with AsyncSession(
            bind=connection,
            expire_on_commit=False,
        ) as session:
            transaction = await session.begin()
            try:
                yield session
            finally:
                if transaction.is_active:
                    await transaction.rollback()


def _user(prefix: str, *, currency: str = "CZK") -> UserModel:
    return UserModel(
        id=f"{prefix}-user",
        email=f"{prefix}@example.test",
        name="Refresh",
        password_hash=None,
        base_currency=currency,
        created_at=NOW,
        updated_at=NOW,
    )


def _account(
    prefix: str,
    suffix: str,
    *,
    account_type: AccountType = AccountType.broker,
    currency: str = "CZK",
    archived: bool = False,
) -> AccountModel:
    return AccountModel(
        id=f"{prefix}-{suffix}",
        name=suffix,
        type=account_type,
        currency=currency,
        color=None,
        is_archived=archived,
        archived_at=NOW if archived else None,
        created_at=NOW,
        updated_at=NOW,
        notes=None,
    )


def _membership(
    prefix: str,
    account: AccountModel,
    *,
    role: AccountMemberRole = AccountMemberRole.owner,
    accepted_at: datetime | None = NOW,
) -> AccountMemberModel:
    return AccountMemberModel(
        id=f"{prefix}-member-{account.id}",
        account_id=account.id,
        user_id=f"{prefix}-user",
        role=role,
        relation_type=AccountRelationType.owner,
        invited_by_id=None,
        accepted_at=accepted_at,
        created_at=NOW,
        updated_at=NOW,
    )


def _snapshot(
    prefix: str,
    account: AccountModel,
    *,
    currency: str = "CZK",
    calculation_version: int = 1,
    source: SnapshotSource = SnapshotSource.manual_recalculation,
    is_recalculated: bool = True,
) -> AccountSnapshotModel:
    return AccountSnapshotModel(
        id=f"{prefix}-snapshot-{account.id}",
        account_id=account.id,
        timestamp=NOW,
        granularity=SnapshotGranularity.day,
        source=source,
        currency=currency,
        cash_value=Decimal("10"),
        investment_value=Decimal("20"),
        investment_cost_basis=Decimal("30"),
        liabilities_value=Decimal("40"),
        total_value=Decimal("50"),
        is_recalculated=is_recalculated,
        calculated_at=NOW,
        calculation_version=calculation_version,
        created_at=NOW,
        net_deposits_value=Decimal("60"),
        realized_pnl_value=Decimal("70"),
        unrealized_pnl_value=Decimal("80"),
        fees_value=Decimal("90"),
        taxes_value=Decimal("100"),
        cash_value_by_currency={"intentionally": "not-validated"},
        investment_value_by_currency=None,
        investment_cost_basis_by_currency=None,
        net_deposits_by_currency=None,
        realized_pnl_by_currency=None,
        unrealized_pnl_by_currency=None,
        fees_by_currency=None,
        taxes_by_currency=None,
        exchange_rates={"intentionally": "not-validated"},
    )


def _command(prefix: str) -> BuildSnapshotRefreshCoverageCommand:
    return BuildSnapshotRefreshCoverageCommand(
        user_id=f"{prefix}-user",
        snapshot_timestamp=NOW,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        calculated_at=NOW,
        created_at=NOW,
        is_recalculated=True,
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
        if user_ids:
            await session.execute(
                delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id.in_(user_ids))
            )
        if account_ids:
            await session.execute(
                delete(AccountSnapshotModel).where(AccountSnapshotModel.account_id.in_(account_ids))
            )
            await session.execute(
                delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
            )
            await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        if user_ids:
            await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        await session.commit()
    await engine.dispose()


async def _seed(
    prefix: str,
    accounts: tuple[AccountModel, ...] = (),
    *,
    memberships: tuple[AccountMemberModel, ...] | None = None,
    snapshots: tuple[AccountSnapshotModel, ...] = (),
    currency: str = "CZK",
) -> None:
    engine = _engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(_user(prefix, currency=currency))
        session.add_all(accounts)
        await session.flush()
        session.add_all(
            memberships
            if memberships is not None
            else tuple(_membership(prefix, account) for account in accounts)
        )
        session.add_all(snapshots)
        await session.commit()
    await engine.dispose()


async def _build(
    engine: AsyncEngine,
    prefix: str,
    *,
    repository: SnapshotRefreshEvidenceRepository | None = None,
) -> CompleteSnapshotRefreshCoverage:
    async with _repeatable_session(engine) as session:
        return await SnapshotRefreshEvidenceService(
            session,
            repository=repository,
        ).build(_command(prefix))


async def _state(prefix: str) -> tuple[object, ...]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        users = tuple(
            (
                row.id,
                row.base_currency,
                row.updated_at,
            )
            for row in await session.scalars(
                select(UserModel)
                .where(UserModel.id.startswith(f"{prefix}-"))
                .order_by(UserModel.id)
            )
        )
        accounts = tuple(
            (
                row.id,
                row.currency,
                row.is_archived,
                row.archived_at,
                row.updated_at,
            )
            for row in await session.scalars(
                select(AccountModel)
                .where(AccountModel.id.startswith(f"{prefix}-"))
                .order_by(AccountModel.id)
            )
        )
        memberships = tuple(
            (
                row.id,
                row.account_id,
                row.user_id,
                row.role,
                row.accepted_at,
                row.updated_at,
            )
            for row in await session.scalars(
                select(AccountMemberModel)
                .where(
                    AccountMemberModel.user_id.in_(
                        select(UserModel.id).where(UserModel.id.startswith(f"{prefix}-"))
                    )
                )
                .order_by(AccountMemberModel.id)
            )
        )
        snapshots = tuple(
            (
                row.id,
                row.account_id,
                row.timestamp,
                row.currency,
                row.source,
                row.calculation_version,
                row.calculated_at,
                row.created_at,
            )
            for row in await session.scalars(
                select(AccountSnapshotModel)
                .where(
                    AccountSnapshotModel.account_id.in_(
                        select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
                    )
                )
                .order_by(AccountSnapshotModel.id)
            )
        )
        item_count = await session.scalar(
            select(func.count())
            .select_from(AccountSnapshotItemModel)
            .join(
                AccountSnapshotModel,
                AccountSnapshotModel.id == AccountSnapshotItemModel.snapshot_id,
            )
            .where(
                AccountSnapshotModel.account_id.in_(
                    select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
                )
            )
        )
        net_worth_count = await session.scalar(
            select(func.count())
            .select_from(NetWorthSnapshotModel)
            .where(
                NetWorthSnapshotModel.user_id.in_(
                    select(UserModel.id).where(UserModel.id.startswith(f"{prefix}-"))
                )
            )
        )
    await engine.dispose()
    return (
        users,
        accounts,
        memberships,
        snapshots,
        item_count,
        net_worth_count,
    )


@pytest.mark.asyncio
async def test_owner_without_snapshot_is_refresh_target_and_read_only() -> None:
    prefix = "k5b-owner"
    await _cleanup(prefix)
    account = _account(prefix, "broker")
    await _seed(prefix, (account,))
    before = await _state(prefix)
    engine = _engine()
    try:
        result = await _build(engine, prefix)
    finally:
        await engine.dispose()
    assert result.refresh_target_count == 1
    assert result.reuse_only_target_count == 0
    assert result.selected_reuse_snapshot_count == 0
    assert await _state(prefix) == before
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_viewer_exact_snapshot_returns_only_reuse_identity() -> None:
    prefix = "k5b-viewer"
    await _cleanup(prefix)
    account = _account(prefix, "broker")
    await _seed(
        prefix,
        (account,),
        memberships=(_membership(prefix, account, role=AccountMemberRole.viewer),),
        snapshots=(_snapshot(prefix, account),),
    )
    before = await _state(prefix)
    engine = _engine()
    try:
        result = await _build(engine, prefix)
    finally:
        await engine.dispose()
    assert result.refresh_target_count == 0
    assert result.reuse_only_target_count == 1
    assert result.selected_reuse_snapshots[0].account_id == account.id
    assert result.selected_reuse_snapshots[0].snapshot_id == (f"{prefix}-snapshot-{account.id}")
    assert await _state(prefix) == before
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_mixed_owner_and_viewer_partition_and_empty_user() -> None:
    prefix = "k5b-mixed"
    await _cleanup(prefix)
    owner = _account(prefix, "owner")
    viewer = _account(prefix, "viewer")
    await _seed(
        prefix,
        (owner, viewer),
        memberships=(
            _membership(prefix, owner),
            _membership(prefix, viewer, role=AccountMemberRole.viewer),
        ),
        snapshots=(_snapshot(prefix, viewer),),
    )
    engine = _engine()
    try:
        result = await _build(engine, prefix)
    finally:
        await engine.dispose()
    assert tuple(target.account_id for target in result.refresh_targets) == (owner.id,)
    assert tuple(identity.account_id for identity in result.selected_reuse_snapshots) == (
        viewer.id,
    )
    await _cleanup(prefix)

    empty_prefix = "k5b-empty"
    await _cleanup(empty_prefix)
    await _seed(empty_prefix)
    engine = _engine()
    try:
        empty = await _build(engine, empty_prefix)
    finally:
        await engine.dispose()
    assert empty.plan.account_targets == ()
    assert empty.plan.net_worth_target.required_account_ids == ()
    await _cleanup(empty_prefix)


@pytest.mark.asyncio
async def test_user_base_currency_controls_reuse_and_mixed_refresh() -> None:
    prefix = "k5b-currency"
    await _cleanup(prefix)
    viewer = _account(prefix, "viewer", currency="USD")
    refresh = _account(prefix, "refresh", currency="USD")
    await _seed(
        prefix,
        (viewer, refresh),
        memberships=(
            _membership(prefix, viewer, role=AccountMemberRole.viewer),
            _membership(prefix, refresh),
        ),
        snapshots=(_snapshot(prefix, viewer, currency="EUR"),),
        currency="EUR",
    )
    engine = _engine()
    try:
        result = await _build(engine, prefix)
    finally:
        await engine.dispose()
    assert result.selected_reuse_snapshot_count == 1
    assert result.refresh_targets[0].requires_fx_conversion is True
    assert result.refresh_targets[0].output_currency == "EUR"
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_viewer_account_currency_snapshot_does_not_cover_user_currency() -> None:
    prefix = "k5b-wrong-currency"
    await _cleanup(prefix)
    viewer = _account(prefix, "viewer", currency="USD")
    await _seed(
        prefix,
        (viewer,),
        memberships=(_membership(prefix, viewer, role=AccountMemberRole.viewer),),
        snapshots=(_snapshot(prefix, viewer, currency="USD"),),
        currency="EUR",
    )
    engine = _engine()
    try:
        with pytest.raises(SnapshotRefreshEvidenceStateError):
            await _build(engine, prefix)
    finally:
        await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prefix", "version", "source", "is_recalculated", "succeeds"),
    [
        (
            "k5b-version",
            2,
            SnapshotSource.manual_recalculation,
            True,
            False,
        ),
        (
            "k5b-source",
            1,
            SnapshotSource.scheduled,
            False,
            True,
        ),
        (
            "k5b-source-corrupt",
            1,
            SnapshotSource.scheduled,
            True,
            False,
        ),
    ],
)
async def test_snapshot_version_and_source_metadata(
    prefix: str,
    version: int,
    source: SnapshotSource,
    is_recalculated: bool,
    succeeds: bool,
) -> None:
    await _cleanup(prefix)
    account = _account(prefix, "viewer")
    await _seed(
        prefix,
        (account,),
        memberships=(_membership(prefix, account, role=AccountMemberRole.viewer),),
        snapshots=(
            _snapshot(
                prefix,
                account,
                calculation_version=version,
                source=source,
                is_recalculated=is_recalculated,
            ),
        ),
    )
    engine = _engine()
    try:
        if succeeds:
            result = await _build(engine, prefix)
            assert result.selected_reuse_snapshot_count == 1
        else:
            with pytest.raises(SnapshotRefreshEvidenceStateError):
                await _build(engine, prefix)
    finally:
        await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_current_archive_unsupported_incomplete_and_foreign_semantics() -> None:
    archived_prefix = "k5b-archived"
    await _cleanup(archived_prefix)
    archived = _account(
        archived_prefix,
        "bank",
        account_type=AccountType.bank,
        archived=True,
    )
    await _seed(archived_prefix, (archived,))
    engine = _engine()
    try:
        result = await _build(engine, archived_prefix)
        assert result.plan.account_targets == ()
    finally:
        await engine.dispose()
    await _cleanup(archived_prefix)

    for prefix, account_type, accepted_at in (
        ("k5b-unsupported", AccountType.bank, NOW),
        ("k5b-incomplete", AccountType.broker, None),
    ):
        await _cleanup(prefix)
        account = _account(prefix, "account", account_type=account_type)
        await _seed(
            prefix,
            (account,),
            memberships=(_membership(prefix, account, accepted_at=accepted_at),),
        )
        engine = _engine()
        try:
            with pytest.raises(SnapshotRefreshEvidenceStateError):
                await _build(engine, prefix)
        finally:
            await engine.dispose()
        await _cleanup(prefix)

    prefix = "k5b-foreign"
    await _cleanup(prefix)
    own = _account(prefix, "own")
    foreign = _account(prefix, "foreign")
    await _seed(prefix, (own,))
    other_prefix = "k5b-other"
    await _cleanup(other_prefix)
    await _seed(other_prefix, (foreign,))
    engine = _engine()
    try:
        result = await _build(engine, prefix)
        assert tuple(target.account_id for target in result.refresh_targets) == (own.id,)
    finally:
        await engine.dispose()
    await _cleanup(prefix)
    await _cleanup(other_prefix)


@pytest.mark.asyncio
async def test_contradictory_archive_state_fails_closed() -> None:
    prefix = "k5b-archive-corrupt"
    await _cleanup(prefix)
    account = _account(prefix, "account")
    account.archived_at = NOW
    await _seed(prefix, (account,))
    engine = _engine()
    try:
        with pytest.raises(SnapshotRefreshEvidenceStateError):
            await _build(engine, prefix)
    finally:
        await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_no_autoflush_no_write_sql_and_caller_rollback() -> None:
    prefix = "k5b-readonly"
    await _cleanup(prefix)
    await _seed(prefix)
    before = await _state(prefix)
    engine = _engine()
    statements: list[str] = []
    flushes: list[object] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement.lstrip().upper())

    def capture_flush(*args: object) -> None:
        flushes.append(args)

    event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        capture_statement,
    )
    try:
        async with _repeatable_session(engine) as session:
            event.listen(session.sync_session, "before_flush", capture_flush)
            session.add(
                UserModel(
                    id=f"{prefix}-pending",
                    email=f"{prefix}-pending@example.test",
                    name=None,
                    password_hash=None,
                    base_currency="CZK",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            result = await SnapshotRefreshEvidenceService(session).build(_command(prefix))
            event.remove(
                session.sync_session,
                "before_flush",
                capture_flush,
            )
            assert result.plan.account_targets == ()
    finally:
        event.remove(
            engine.sync_engine,
            "before_cursor_execute",
            capture_statement,
        )
        await engine.dispose()
    assert flushes == []
    assert all(statement.startswith(("SELECT", "SHOW")) for statement in statements)
    assert await _state(prefix) == before
    await _cleanup(prefix)


class PauseAfterAccessRepository(SnapshotRefreshEvidenceRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        paused: asyncio.Event,
        resume: asyncio.Event,
    ) -> None:
        super().__init__(session)
        self.paused = paused
        self.resume = resume

    async def load_account_accesses(self, user_id: str):
        result = await super().load_account_accesses(user_id)
        self.paused.set()
        await self.resume.wait()
        return result


class PauseAfterUserRepository(SnapshotRefreshEvidenceRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        paused: asyncio.Event,
        resume: asyncio.Event,
    ) -> None:
        super().__init__(session)
        self.paused = paused
        self.resume = resume

    async def load_user(self, user_id: str):
        result = await super().load_user(user_id)
        self.paused.set()
        await self.resume.wait()
        return result


@pytest.mark.asyncio
async def test_repeatable_read_membership_race_is_one_old_then_new_view() -> None:
    prefix = "k5b-race-member"
    await _cleanup(prefix)
    original = _account(prefix, "original")
    await _seed(prefix, (original,))
    engine = _engine()
    paused = asyncio.Event()
    resume = asyncio.Event()
    try:
        async with engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="REPEATABLE READ")
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
            ) as reader:
                transaction = await reader.begin()
                repository = PauseAfterAccessRepository(
                    reader,
                    paused=paused,
                    resume=resume,
                )
                task = asyncio.create_task(
                    SnapshotRefreshEvidenceService(
                        reader,
                        repository=repository,
                    ).build(_command(prefix))
                )
                await asyncio.wait_for(paused.wait(), timeout=5)
                concurrent = _account(prefix, "concurrent")
                async with AsyncSession(
                    engine,
                    expire_on_commit=False,
                ) as writer:
                    writer.add(concurrent)
                    await writer.flush()
                    writer.add(_membership(prefix, concurrent))
                    await writer.commit()
                resume.set()
                old = await asyncio.wait_for(task, timeout=5)
                await transaction.rollback()
        assert tuple(target.account_id for target in old.refresh_targets) == (original.id,)
        fresh = await _build(engine, prefix)
        assert tuple(target.account_id for target in fresh.refresh_targets) == (
            concurrent.id,
            original.id,
        )
    finally:
        await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_repeatable_read_base_currency_race_is_coherent() -> None:
    prefix = "k5b-race-currency"
    await _cleanup(prefix)
    account = _account(prefix, "account", currency="USD")
    await _seed(prefix, (account,), currency="CZK")
    engine = _engine()
    paused = asyncio.Event()
    resume = asyncio.Event()
    try:
        async with engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="REPEATABLE READ")
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
            ) as reader:
                transaction = await reader.begin()
                repository = PauseAfterUserRepository(
                    reader,
                    paused=paused,
                    resume=resume,
                )
                task = asyncio.create_task(
                    SnapshotRefreshEvidenceService(
                        reader,
                        repository=repository,
                    ).build(_command(prefix))
                )
                await asyncio.wait_for(paused.wait(), timeout=5)
                async with AsyncSession(engine) as writer:
                    await writer.execute(
                        update(UserModel)
                        .where(UserModel.id == f"{prefix}-user")
                        .values(base_currency="EUR")
                    )
                    await writer.commit()
                resume.set()
                old = await asyncio.wait_for(task, timeout=5)
                await transaction.rollback()
        assert old.plan.output_currency == "CZK"
        fresh = await _build(engine, prefix)
        assert fresh.plan.output_currency == "EUR"
    finally:
        await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_repeatable_read_reuse_insert_race_stays_missing_then_fresh() -> None:
    prefix = "k5b-race-reuse"
    await _cleanup(prefix)
    account = _account(prefix, "viewer")
    await _seed(
        prefix,
        (account,),
        memberships=(_membership(prefix, account, role=AccountMemberRole.viewer),),
    )
    engine = _engine()
    paused = asyncio.Event()
    resume = asyncio.Event()
    try:
        async with engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="REPEATABLE READ")
            async with AsyncSession(
                bind=connection,
                expire_on_commit=False,
            ) as reader:
                transaction = await reader.begin()
                repository = PauseAfterAccessRepository(
                    reader,
                    paused=paused,
                    resume=resume,
                )
                task = asyncio.create_task(
                    SnapshotRefreshEvidenceService(
                        reader,
                        repository=repository,
                    ).build(_command(prefix))
                )
                await asyncio.wait_for(paused.wait(), timeout=5)
                async with AsyncSession(
                    engine,
                    expire_on_commit=False,
                ) as writer:
                    writer.add(_snapshot(prefix, account))
                    await writer.commit()
                resume.set()
                with pytest.raises(SnapshotRefreshEvidenceStateError):
                    await asyncio.wait_for(task, timeout=5)
                await transaction.rollback()
        fresh = await _build(engine, prefix)
        assert fresh.selected_reuse_snapshot_count == 1
    finally:
        await engine.dispose()
    await _cleanup(prefix)
