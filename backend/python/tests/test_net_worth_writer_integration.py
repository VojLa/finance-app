from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any, cast

import pytest
from sqlalchemy import delete, event, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
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
from app.modules.net_worth.evidence_service import (
    BuildNetWorthEvidenceCommand,
    NetWorthEvidenceService,
    NetWorthEvidenceStateError,
)
from app.modules.net_worth.manual_service import (
    ManualNetWorthSnapshotService,
    NetWorthSnapshotConflictError,
    NetWorthSnapshotUnavailableError,
    RecalculateNetWorthSnapshotCommand,
    RecalculateNetWorthSnapshotResult,
)
from app.modules.net_worth.persistence_projection import (
    NetWorthSnapshotPersistenceMetadata,
    build_net_worth_snapshot_persistence_projection,
)
from app.modules.net_worth.writer import (
    NetWorthSnapshotWriteConflictError,
    NetWorthSnapshotWriteDisposition,
    NetWorthSnapshotWriter,
    NetWorthSnapshotWriteResult,
    NetWorthSnapshotWriteStateError,
    WriteNetWorthSnapshotCommand,
)
from app.modules.net_worth.writer_repository import NetWorthSnapshotWriterRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
BASE_AT = datetime(2032, 1, 3)


def _engine() -> AsyncEngine:
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=8)


def _snapshot_at(prefix: str) -> datetime:
    days = int.from_bytes(sha256(prefix.encode()).digest()[:4], "big") % 10_000
    return BASE_AT + timedelta(days=days)


def _user_id(prefix: str) -> str:
    return f"{prefix}-user"


def _user(prefix: str) -> UserModel:
    timestamp = _snapshot_at(prefix)
    return UserModel(
        id=_user_id(prefix),
        email=f"{prefix}@example.com",
        name="Net Worth Writer",
        password_hash=None,
        base_currency="CZK",
        created_at=timestamp,
        updated_at=timestamp,
    )


def _account(prefix: str, suffix: str, account_type: AccountType) -> AccountModel:
    timestamp = _snapshot_at(prefix)
    return AccountModel(
        id=f"{prefix}-{suffix}",
        name=suffix,
        type=account_type,
        currency="CZK",
        color=None,
        is_archived=False,
        archived_at=None,
        created_at=timestamp,
        updated_at=timestamp,
        notes=None,
    )


def _membership(prefix: str, account: AccountModel) -> AccountMemberModel:
    timestamp = _snapshot_at(prefix)
    return AccountMemberModel(
        id=f"{prefix}-member-{account.id}",
        account_id=account.id,
        user_id=_user_id(prefix),
        role=AccountMemberRole.owner,
        relation_type=AccountRelationType.owner,
        invited_by_id=None,
        accepted_at=timestamp,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _source_snapshot(
    prefix: str,
    account: AccountModel,
    *,
    timestamp: datetime | None = None,
    suffix: str = "",
    cash: Decimal | None = None,
    portfolio: Decimal | None = None,
    liability: Decimal | None = None,
    portfolio_breakdown: dict[str, str] | None = None,
    granularity: SnapshotGranularity = SnapshotGranularity.day,
    currency: str = "CZK",
    calculation_version: int = 1,
) -> AccountSnapshotModel:
    snapshot_at = timestamp or _snapshot_at(prefix)
    liability_account = account.type in {
        AccountType.credit_card,
        AccountType.loan,
        AccountType.mortgage,
    }
    cash_value = cash if cash is not None else Decimal(0 if liability_account else 100)
    portfolio_value = (
        portfolio if portfolio is not None else Decimal(0 if liability_account else 400)
    )
    liabilities_value = (
        liability if liability is not None else Decimal(250 if liability_account else 0)
    )
    investment_cost_basis = Decimal(0 if liability_account else 300)
    return AccountSnapshotModel(
        id=f"{prefix}-source-{account.id}{suffix}",
        account_id=account.id,
        timestamp=snapshot_at,
        granularity=granularity,
        source=SnapshotSource.manual_recalculation,
        currency=currency,
        cash_value=cash_value,
        investment_value=portfolio_value,
        investment_cost_basis=investment_cost_basis,
        liabilities_value=liabilities_value,
        total_value=cash_value + portfolio_value - liabilities_value,
        is_recalculated=True,
        calculated_at=snapshot_at,
        calculation_version=calculation_version,
        created_at=snapshot_at,
        net_deposits_value=Decimal(0),
        realized_pnl_value=Decimal(0),
        unrealized_pnl_value=portfolio_value - investment_cost_basis,
        fees_value=Decimal(0),
        taxes_value=Decimal(0),
        cash_value_by_currency=({} if cash_value == 0 else {"CZK": f"{cash_value:.6f}"}),
        investment_value_by_currency=(
            {}
            if portfolio_value == 0
            else (
                portfolio_breakdown
                if portfolio_breakdown is not None
                else {"CZK": f"{portfolio_value:.10f}"}
            )
        ),
        investment_cost_basis_by_currency=(
            {} if investment_cost_basis == 0 else {"CZK": f"{investment_cost_basis:.10f}"}
        ),
        net_deposits_by_currency={},
        realized_pnl_by_currency={},
        unrealized_pnl_by_currency=(
            {}
            if portfolio_value == investment_cost_basis
            else {"CZK": f"{portfolio_value - investment_cost_basis:.6f}"}
        ),
        fees_by_currency={},
        taxes_by_currency={},
        exchange_rates={
            "version": 1,
            "snapshotRates": [],
            "historicalRateIds": [],
        },
    )


def _command(prefix: str, **changes: object) -> WriteNetWorthSnapshotCommand:
    timestamp = _snapshot_at(prefix)
    values: dict[str, object] = {
        "user_id": _user_id(prefix),
        "snapshot_timestamp": timestamp,
        "granularity": SnapshotGranularity.day,
        "currency": "CZK",
        "source": SnapshotSource.manual_recalculation,
        "calculation_version": 1,
        "calculated_at": timestamp + timedelta(minutes=1),
        "created_at": timestamp + timedelta(minutes=2),
        "is_recalculated": True,
    }
    values.update(changes)
    return WriteNetWorthSnapshotCommand(**cast(Any, values))


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
        source_ids = tuple(
            await session.scalars(
                select(AccountSnapshotModel.id).where(
                    AccountSnapshotModel.account_id.in_(account_ids)
                )
            )
        )
        if source_ids:
            await session.execute(
                delete(AccountSnapshotItemModel).where(
                    AccountSnapshotItemModel.snapshot_id.in_(source_ids)
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
    snapshots: tuple[AccountSnapshotModel, ...] = (),
) -> None:
    await _cleanup(prefix)
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(_user(prefix))
        session.add_all(accounts)
        await session.flush()
        session.add_all(_membership(prefix, account) for account in accounts)
        session.add_all(snapshots)
        await session.commit()
    await engine.dispose()


async def _rows(prefix: str) -> tuple[NetWorthSnapshotModel, ...]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        result = tuple(
            await session.scalars(
                select(NetWorthSnapshotModel)
                .where(NetWorthSnapshotModel.user_id == _user_id(prefix))
                .order_by(NetWorthSnapshotModel.timestamp, NetWorthSnapshotModel.id)
            )
        )
    await engine.dispose()
    return result


async def _state(prefix: str) -> tuple[object, ...]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        users = tuple(
            (
                row.id,
                row.email,
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
                row.type,
                row.currency,
                row.is_archived,
                row.updated_at,
            )
            for row in await session.scalars(
                select(AccountModel)
                .where(AccountModel.id.startswith(f"{prefix}-"))
                .order_by(AccountModel.id)
            )
        )
        members = tuple(
            (
                row.id,
                row.account_id,
                row.user_id,
                row.role,
                row.accepted_at,
            )
            for row in await session.scalars(
                select(AccountMemberModel)
                .where(AccountMemberModel.account_id.in_(tuple(row[0] for row in accounts)))
                .order_by(AccountMemberModel.id)
            )
        )
        sources = tuple(
            (
                row.id,
                row.account_id,
                row.timestamp,
                row.total_value,
                row.cash_value,
                row.investment_value,
                row.liabilities_value,
            )
            for row in await session.scalars(
                select(AccountSnapshotModel)
                .where(AccountSnapshotModel.account_id.in_(tuple(row[0] for row in accounts)))
                .order_by(AccountSnapshotModel.id)
            )
        )
        source_items = tuple(
            (
                row.id,
                row.snapshot_id,
                row.asset_id,
                row.listing_id,
                row.value,
                row.cost_basis,
            )
            for row in await session.scalars(
                select(AccountSnapshotItemModel)
                .where(AccountSnapshotItemModel.snapshot_id.in_(tuple(row[0] for row in sources)))
                .order_by(AccountSnapshotItemModel.id)
            )
        )
        targets = tuple(
            (
                row.id,
                row.user_id,
                row.timestamp,
                row.cash_value,
                row.portfolio_value,
                row.liabilities_value,
                row.total_net_worth,
                row.source,
                row.calculated_at,
                row.created_at,
                row.cash_value_by_currency,
                row.portfolio_value_by_currency,
                row.liabilities_value_by_currency,
                row.total_net_worth_by_currency,
                row.exchange_rates,
            )
            for row in await session.scalars(
                select(NetWorthSnapshotModel)
                .where(NetWorthSnapshotModel.user_id.in_(tuple(row[0] for row in users)))
                .order_by(NetWorthSnapshotModel.id)
            )
        )
    await engine.dispose()
    return users, accounts, members, sources, source_items, targets


async def _expected_id(
    engine: AsyncEngine,
    command: WriteNetWorthSnapshotCommand,
) -> str:
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="SERIALIZABLE")
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            transaction = await session.begin()
            evidence = await NetWorthEvidenceService(session).build(
                BuildNetWorthEvidenceCommand(
                    user_id=command.user_id,
                    timestamp=command.snapshot_timestamp,
                    granularity=command.granularity,
                    currency=command.currency,
                    calculation_version=command.calculation_version,
                )
            )
            projection = build_net_worth_snapshot_persistence_projection(
                evidence,
                NetWorthSnapshotPersistenceMetadata(
                    source=command.source,
                    calculated_at=command.calculated_at,
                    created_at=command.created_at,
                    is_recalculated=command.is_recalculated,
                ),
            )
            await transaction.rollback()
    return projection.snapshot.id


@pytest.mark.asyncio
async def test_mixed_snapshot_create_and_exact_read_only_replay() -> None:
    prefix = "j5d-basic"
    broker = _account(prefix, "broker", AccountType.broker)
    crypto = _account(prefix, "crypto", AccountType.crypto_wallet)
    mortgage = _account(prefix, "mortgage", AccountType.mortgage)
    await _seed(
        prefix,
        (broker, crypto, mortgage),
        (
            _source_snapshot(
                prefix,
                broker,
                portfolio_breakdown={"USD": "0.1234567890"},
            ),
            _source_snapshot(prefix, crypto),
            _source_snapshot(prefix, mortgage),
        ),
    )
    engine = _engine()
    command = _command(prefix)
    try:
        before_sources = await _state(prefix)
        expected_id = await _expected_id(engine, command)
        async with AsyncSession(engine) as session:
            first = await NetWorthSnapshotWriter(session).write(command)
        after_first = await _state(prefix)
        rows = await _rows(prefix)
        assert first.disposition is NetWorthSnapshotWriteDisposition.created
        assert first.account_count == first.selected_account_snapshot_count == 3
        assert len(rows) == 1
        row = rows[0]
        assert row.id == first.snapshot_id == expected_id
        assert row.user_id == command.user_id
        assert row.timestamp == command.snapshot_timestamp
        assert row.granularity is command.granularity
        assert row.source is command.source
        assert row.currency == command.currency
        assert row.cash_value == Decimal("200.000000")
        assert row.portfolio_value == Decimal("800.000000")
        assert row.liabilities_value == Decimal("250.000000")
        assert row.total_net_worth == Decimal("750.000000")
        assert row.is_recalculated is True
        assert row.calculated_at == command.calculated_at
        assert row.calculation_version == command.calculation_version
        assert row.created_at == command.created_at
        assert row.cash_value_by_currency == {"CZK": "200.000000"}
        assert row.portfolio_value_by_currency == {
            "CZK": "400.0000000000",
            "USD": "0.1234567890",
        }
        assert row.liabilities_value_by_currency is None
        assert row.total_net_worth_by_currency is None
        assert row.exchange_rates is None
        physical_before_replay = after_first[-1]

        async with AsyncSession(engine) as session:
            second = await NetWorthSnapshotWriter(session).write(command)

        assert second.disposition is NetWorthSnapshotWriteDisposition.replayed
        assert second.snapshot_id == first.snapshot_id
        assert len(await _rows(prefix)) == 1
        assert (await _state(prefix))[-1] == physical_before_replay
        assert before_sources[:-1] == after_first[:-1]
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_empty_user_creates_exact_zero_snapshot_and_replays() -> None:
    prefix = "j5d-empty"
    await _seed(prefix)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            first = await NetWorthSnapshotWriter(session).write(_command(prefix))
        row = (await _rows(prefix))[0]
        assert first.account_count == 0
        assert first.selected_account_snapshot_count == 0
        assert row.cash_value == row.portfolio_value == row.liabilities_value == 0
        assert row.total_net_worth == 0
        assert row.cash_value_by_currency == {}
        assert row.portfolio_value_by_currency == {}
        assert row.liabilities_value_by_currency == {}
        assert row.total_net_worth_by_currency == {}
        async with AsyncSession(engine) as session:
            replay = await NetWorthSnapshotWriter(session).write(_command(prefix))
        assert replay.disposition is NetWorthSnapshotWriteDisposition.replayed
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_scale_ten_portfolio_and_total_breakdowns_survive_exactly() -> None:
    prefix = "j5d-scale-ten"
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(
        prefix,
        (account,),
        (
            _source_snapshot(
                prefix,
                account,
                cash=Decimal(0),
                portfolio=Decimal("1"),
                portfolio_breakdown={"USD": "0.1234567890"},
            ),
        ),
    )
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            await NetWorthSnapshotWriter(session).write(_command(prefix))
        row = (await _rows(prefix))[0]
        assert row.cash_value_by_currency == {}
        assert row.portfolio_value_by_currency == {"USD": "0.1234567890"}
        assert row.liabilities_value_by_currency is None
        assert row.total_net_worth_by_currency == {"USD": "0.1234567890"}
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.parametrize(
    "changes",
    [
        {"created_at": datetime(2040, 1, 1)},
        {"calculated_at": datetime(2040, 1, 1)},
        {
            "source": SnapshotSource.scheduled,
            "is_recalculated": False,
        },
    ],
)
@pytest.mark.asyncio
async def test_same_physical_identity_with_changed_metadata_conflicts(
    changes: dict[str, object],
) -> None:
    prefix = f"j5d-meta-{len(str(changes))}"
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (account,), (_source_snapshot(prefix, account),))
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            created = await NetWorthSnapshotWriter(session).write(_command(prefix))
        before = await _state(prefix)
        async with AsyncSession(engine) as session:
            with pytest.raises(NetWorthSnapshotWriteConflictError):
                await NetWorthSnapshotWriter(session).write(_command(prefix, **changes))
        assert await _state(prefix) == before
        assert (await _rows(prefix))[0].id == created.snapshot_id
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_changed_calculation_version_conflicts_after_evidence_version_changes() -> None:
    prefix = "j5d-meta-version"
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (account,), (_source_snapshot(prefix, account),))
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            created = await NetWorthSnapshotWriter(session).write(_command(prefix))
        original_target = (await _state(prefix))[-1]
        async with AsyncSession(engine) as session:
            source = await session.scalar(
                select(AccountSnapshotModel).where(
                    AccountSnapshotModel.account_id == f"{prefix}-broker"
                )
            )
            assert source is not None
            source.calculation_version = 2
            await session.commit()
        async with AsyncSession(engine) as session:
            with pytest.raises(NetWorthSnapshotWriteConflictError):
                await NetWorthSnapshotWriter(session).write(_command(prefix, calculation_version=2))
        assert (await _state(prefix))[-1] == original_target
        assert (await _rows(prefix))[0].id == created.snapshot_id
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cash_value", Decimal("999")),
        ("calculation_version", 2),
        ("portfolio_value_by_currency", {}),
        ("exchange_rates", {}),
    ],
)
@pytest.mark.asyncio
async def test_corrupt_persisted_snapshot_conflicts_without_repair(
    field: str,
    value: object,
) -> None:
    prefix = f"j5d-corrupt-{field.replace('_', '-')}"
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (account,), (_source_snapshot(prefix, account),))
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            result = await NetWorthSnapshotWriter(session).write(_command(prefix))
        async with AsyncSession(engine) as session:
            row = await session.get(NetWorthSnapshotModel, result.snapshot_id)
            assert row is not None
            setattr(row, field, value)
            await session.commit()
        before = await _state(prefix)
        async with AsyncSession(engine) as session:
            with pytest.raises(NetWorthSnapshotWriteConflictError):
                await NetWorthSnapshotWriter(session).write(_command(prefix))
        assert await _state(prefix) == before
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.parametrize(
    "account_type",
    [AccountType.broker, AccountType.bank],
)
@pytest.mark.asyncio
async def test_missing_or_unsupported_source_evidence_writes_nothing(
    account_type: AccountType,
) -> None:
    prefix = f"j5d-unavailable-{account_type.value.replace('_', '-')}"
    account = _account(prefix, "account", account_type)
    snapshots = (_source_snapshot(prefix, account),) if account_type is AccountType.bank else ()
    await _seed(prefix, (account,), snapshots)
    engine = _engine()
    before = await _state(prefix)
    try:
        async with AsyncSession(engine) as session:
            with pytest.raises(NetWorthEvidenceStateError):
                await NetWorthSnapshotWriter(session).write(_command(prefix))
        assert await _state(prefix) == before
        assert await _rows(prefix) == ()
    finally:
        await engine.dispose()
        await _cleanup(prefix)


class _FailingFlushRepository(NetWorthSnapshotWriterRepository):
    async def flush(self) -> None:
        await super().flush()
        raise SQLAlchemyError("controlled flush failure")


class _MismatchingReloadRepository(NetWorthSnapshotWriterRepository):
    async def reload_snapshot(self, snapshot_id: str) -> NetWorthSnapshotModel | None:
        row = await super().reload_snapshot(snapshot_id)
        assert row is not None
        row.total_net_worth = Decimal("999")
        return row


@pytest.mark.parametrize(
    "repository_type",
    [_FailingFlushRepository, _MismatchingReloadRepository],
)
@pytest.mark.asyncio
async def test_late_failure_rolls_back_and_clean_retry_succeeds_once(
    repository_type: type[NetWorthSnapshotWriterRepository],
) -> None:
    prefix = f"j5d-rollback-{repository_type.__name__.lower()}"
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (account,), (_source_snapshot(prefix, account),))
    engine = _engine()
    before = await _state(prefix)
    try:
        async with AsyncSession(engine) as session:
            with pytest.raises(NetWorthSnapshotWriteStateError):
                await NetWorthSnapshotWriter(
                    session,
                    repository=repository_type(session),
                ).write(_command(prefix))
        assert await _state(prefix) == before
        assert await _rows(prefix) == ()
        async with AsyncSession(engine) as session:
            result = await NetWorthSnapshotWriter(session).write(_command(prefix))
        assert result.disposition is NetWorthSnapshotWriteDisposition.created
        assert len(await _rows(prefix)) == 1
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_deterministic_id_collision_is_conflict_and_preserves_both_keys() -> None:
    prefix = "j5d-id-collision"
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (account,), (_source_snapshot(prefix, account),))
    engine = _engine()
    command = _command(prefix)
    try:
        expected_id = await _expected_id(engine, command)
        values = {
            "id": expected_id,
            "user_id": command.user_id,
            "timestamp": command.snapshot_timestamp + timedelta(days=1),
            "granularity": command.granularity,
            "source": command.source,
            "currency": command.currency,
            "cash_value": Decimal(0),
            "portfolio_value": Decimal(0),
            "liabilities_value": Decimal(0),
            "total_net_worth": Decimal(0),
            "is_recalculated": command.is_recalculated,
            "calculated_at": command.calculated_at,
            "calculation_version": command.calculation_version,
            "created_at": command.created_at,
            "cash_value_by_currency": {},
            "portfolio_value_by_currency": {},
            "liabilities_value_by_currency": {},
            "total_net_worth_by_currency": {},
            "exchange_rates": None,
        }
        async with AsyncSession(engine) as session:
            session.add(NetWorthSnapshotModel(**values))
            await session.commit()
        before = await _state(prefix)
        async with AsyncSession(engine) as session:
            with pytest.raises(NetWorthSnapshotWriteConflictError):
                await NetWorthSnapshotWriter(session).write(command)
        assert await _state(prefix) == before
        assert len(await _rows(prefix)) == 1
    finally:
        await engine.dispose()
        await _cleanup(prefix)


class _PausingRepository(NetWorthSnapshotWriterRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        locked: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
        pid_ready: asyncio.Future[int] | None = None,
    ) -> None:
        super().__init__(session)
        self.locked = locked
        self.release = release
        self.pid_ready = pid_ready

    async def acquire_snapshot_lock(self, **values: Any) -> None:
        pid = await self.session.scalar(select(func.pg_backend_pid()))
        if self.pid_ready is not None and pid is not None and not self.pid_ready.done():
            self.pid_ready.set_result(pid)
        await super().acquire_snapshot_lock(**values)
        if self.locked is not None:
            self.locked.set()
        if self.release is not None:
            await asyncio.wait_for(self.release.wait(), timeout=10)


class _HoldingReloadRepository(NetWorthSnapshotWriterRepository):
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

    async def reload_snapshot(self, snapshot_id: str) -> NetWorthSnapshotModel | None:
        row = await super().reload_snapshot(snapshot_id)
        self.holding.set()
        await asyncio.wait_for(self.release.wait(), timeout=10)
        return row


async def _wait_for_advisory_lock(engine: AsyncEngine, pid: int) -> None:
    for _ in range(100):
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
        await asyncio.sleep(0.02)
    raise AssertionError("Second writer did not wait on the net-worth advisory lock")


@pytest.mark.asyncio
async def test_same_key_concurrency_waits_then_creates_once_and_replays() -> None:
    prefix = "j5d-concurrent-same"
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (account,), (_source_snapshot(prefix, account),))
    engine = _engine()
    holding, release = asyncio.Event(), asyncio.Event()
    pid_ready: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:
        async with AsyncSession(engine) as first_session, AsyncSession(engine) as second_session:
            first = asyncio.create_task(
                NetWorthSnapshotWriter(
                    first_session,
                    repository=_HoldingReloadRepository(
                        first_session,
                        holding=holding,
                        release=release,
                    ),
                ).write(_command(prefix))
            )
            await asyncio.wait_for(holding.wait(), timeout=10)
            second = asyncio.create_task(
                NetWorthSnapshotWriter(
                    second_session,
                    repository=_PausingRepository(second_session, pid_ready=pid_ready),
                ).write(_command(prefix))
            )
            await _wait_for_advisory_lock(
                engine,
                await asyncio.wait_for(pid_ready, timeout=10),
            )
            release.set()
            first_result, second_result = await asyncio.wait_for(
                asyncio.gather(first, second),
                timeout=30,
            )
        assert first_result.disposition is NetWorthSnapshotWriteDisposition.created
        assert second_result.disposition is NetWorthSnapshotWriteDisposition.replayed
        assert first_result.snapshot_id == second_result.snapshot_id
        assert len(await _rows(prefix)) == 1
    finally:
        release.set()
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_same_key_concurrent_metadata_difference_creates_then_conflicts() -> None:
    prefix = "j5d-concurrent-conflict"
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (account,), (_source_snapshot(prefix, account),))
    engine = _engine()
    holding, release = asyncio.Event(), asyncio.Event()
    pid_ready: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:
        async with AsyncSession(engine) as first_session, AsyncSession(engine) as second_session:
            first = asyncio.create_task(
                NetWorthSnapshotWriter(
                    first_session,
                    repository=_HoldingReloadRepository(
                        first_session,
                        holding=holding,
                        release=release,
                    ),
                ).write(_command(prefix))
            )
            await asyncio.wait_for(holding.wait(), timeout=10)
            second = asyncio.create_task(
                NetWorthSnapshotWriter(
                    second_session,
                    repository=_PausingRepository(second_session, pid_ready=pid_ready),
                ).write(
                    _command(
                        prefix,
                        created_at=_snapshot_at(prefix) + timedelta(minutes=3),
                    )
                )
            )
            await _wait_for_advisory_lock(
                engine,
                await asyncio.wait_for(pid_ready, timeout=10),
            )
            release.set()
            first_result = await asyncio.wait_for(first, timeout=30)
            with pytest.raises(NetWorthSnapshotWriteConflictError):
                await asyncio.wait_for(second, timeout=30)
        assert first_result.disposition is NetWorthSnapshotWriteDisposition.created
        assert len(await _rows(prefix)) == 1
    finally:
        release.set()
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_different_users_do_not_share_the_snapshot_lock() -> None:
    first_prefix = "j5d-parallel-a"
    second_prefix = "j5d-parallel-b"
    first_account = _account(first_prefix, "broker", AccountType.broker)
    second_account = _account(second_prefix, "broker", AccountType.broker)
    await _seed(
        first_prefix,
        (first_account,),
        (_source_snapshot(first_prefix, first_account),),
    )
    await _seed(
        second_prefix,
        (second_account,),
        (_source_snapshot(second_prefix, second_account),),
    )
    engine = _engine()
    locked, release = asyncio.Event(), asyncio.Event()
    try:

        async def paused() -> NetWorthSnapshotWriteResult:
            async with AsyncSession(engine) as session:
                return await NetWorthSnapshotWriter(
                    session,
                    repository=_PausingRepository(
                        session,
                        locked=locked,
                        release=release,
                    ),
                ).write(_command(first_prefix))

        first = asyncio.create_task(paused())
        await asyncio.wait_for(locked.wait(), timeout=10)
        async with AsyncSession(engine) as session:
            second = await asyncio.wait_for(
                NetWorthSnapshotWriter(session).write(_command(second_prefix)),
                timeout=10,
            )
        assert second.disposition is NetWorthSnapshotWriteDisposition.created
        assert not first.done()
        release.set()
        first_result = await asyncio.wait_for(first, timeout=20)
        assert first_result.disposition is NetWorthSnapshotWriteDisposition.created
    finally:
        release.set()
        await engine.dispose()
        await _cleanup(first_prefix)
        await _cleanup(second_prefix)


@pytest.mark.asyncio
async def test_same_user_different_timestamps_do_not_share_the_snapshot_lock() -> None:
    prefix = "j5d-parallel-time"
    account = _account(prefix, "broker", AccountType.broker)
    first_at = _snapshot_at(prefix)
    second_at = first_at + timedelta(days=1)
    await _seed(
        prefix,
        (account,),
        (
            _source_snapshot(prefix, account),
            _source_snapshot(
                prefix,
                account,
                timestamp=second_at,
                suffix="-next",
            ),
        ),
    )
    engine = _engine()
    locked, release = asyncio.Event(), asyncio.Event()
    try:

        async def paused() -> NetWorthSnapshotWriteResult:
            async with AsyncSession(engine) as session:
                return await NetWorthSnapshotWriter(
                    session,
                    repository=_PausingRepository(
                        session,
                        locked=locked,
                        release=release,
                    ),
                ).write(_command(prefix))

        first = asyncio.create_task(paused())
        await asyncio.wait_for(locked.wait(), timeout=10)
        async with AsyncSession(engine) as session:
            second = await asyncio.wait_for(
                NetWorthSnapshotWriter(session).write(
                    _command(
                        prefix,
                        snapshot_timestamp=second_at,
                        calculated_at=second_at + timedelta(minutes=1),
                        created_at=second_at + timedelta(minutes=2),
                    )
                ),
                timeout=10,
            )
        assert second.disposition is NetWorthSnapshotWriteDisposition.created
        assert not first.done()
        release.set()
        first_result = await asyncio.wait_for(first, timeout=20)
        assert first_result.disposition is NetWorthSnapshotWriteDisposition.created
        assert len(await _rows(prefix)) == 2
    finally:
        release.set()
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_source_snapshot_commit_after_serializable_snapshot_is_coherent() -> None:
    prefix = "j5d-source-race"
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (account,), ())
    engine = _engine()
    locked, release = asyncio.Event(), asyncio.Event()
    try:

        async def write() -> NetWorthSnapshotWriteResult:
            async with AsyncSession(engine) as session:
                return await NetWorthSnapshotWriter(
                    session,
                    repository=_PausingRepository(
                        session,
                        locked=locked,
                        release=release,
                    ),
                ).write(_command(prefix))

        task = asyncio.create_task(write())
        await asyncio.wait_for(locked.wait(), timeout=10)
        async with AsyncSession(engine) as session:
            session.add(
                _source_snapshot(
                    prefix,
                    _account(prefix, "broker", AccountType.broker),
                )
            )
            await session.commit()
        release.set()
        with pytest.raises(NetWorthEvidenceStateError):
            await asyncio.wait_for(task, timeout=20)
        assert await _rows(prefix) == ()
        async with AsyncSession(engine) as session:
            result = await NetWorthSnapshotWriter(session).write(_command(prefix))
        assert result.disposition is NetWorthSnapshotWriteDisposition.created
    finally:
        release.set()
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_concurrent_membership_addition_yields_one_coherent_old_view() -> None:
    prefix = "j5d-membership-race"
    original = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (original,), (_source_snapshot(prefix, original),))
    engine = _engine()
    locked, release = asyncio.Event(), asyncio.Event()
    try:

        async def write() -> NetWorthSnapshotWriteResult:
            async with AsyncSession(engine) as session:
                return await NetWorthSnapshotWriter(
                    session,
                    repository=_PausingRepository(
                        session,
                        locked=locked,
                        release=release,
                    ),
                ).write(_command(prefix))

        task = asyncio.create_task(write())
        await asyncio.wait_for(locked.wait(), timeout=10)
        concurrent = _account(prefix, "crypto", AccountType.crypto_wallet)
        async with AsyncSession(engine) as session:
            session.add(concurrent)
            await session.flush()
            session.add(_membership(prefix, concurrent))
            session.add(_source_snapshot(prefix, concurrent))
            await session.commit()
        release.set()
        result = await asyncio.wait_for(task, timeout=30)
        assert result.disposition is NetWorthSnapshotWriteDisposition.created
        assert result.account_count == 1
        rows = await _rows(prefix)
        assert len(rows) == 1
        assert rows[0].portfolio_value == Decimal("400.000000")
        async with AsyncSession(engine) as session:
            with pytest.raises(NetWorthSnapshotWriteConflictError):
                await NetWorthSnapshotWriter(session).write(_command(prefix))
        assert (await _rows(prefix))[0].portfolio_value == Decimal("400.000000")
    finally:
        release.set()
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_first_statement_sets_serializable_isolation() -> None:
    prefix = "j5d-isolation"
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (account,), (_source_snapshot(prefix, account),))
    engine = _engine()
    statements: list[str] = []

    def capture(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with AsyncSession(engine) as session:
            result = await NetWorthSnapshotWriter(session).write(_command(prefix))
        assert result.disposition is NetWorthSnapshotWriteDisposition.created
        assert statements
        assert statements[0].strip().upper() == ("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        await engine.dispose()
        await _cleanup(prefix)


def _principal(prefix: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=_user_id(prefix),
        email=f"{prefix}@example.com",
        name=prefix,
    )


def _manual_source_snapshot(
    prefix: str,
    account: AccountModel,
) -> AccountSnapshotModel:
    return _source_snapshot(
        prefix,
        account,
        granularity=SnapshotGranularity.minute,
    )


async def _manual_recalculate(
    prefix: str,
    *,
    writer_factory: Any = NetWorthSnapshotWriter,
) -> RecalculateNetWorthSnapshotResult:
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            # Mirror CurrentPrincipal: authentication resolves the persisted User
            # and leaves the request session in an active read transaction.
            authenticated = await session.scalar(
                select(UserModel).where(UserModel.id == _user_id(prefix))
            )
            assert authenticated is not None
            return await ManualNetWorthSnapshotService(
                session,
                clock=lambda: _snapshot_at(prefix),
                writer_factory=writer_factory,
            ).recalculate(RecalculateNetWorthSnapshotCommand(principal=_principal(prefix)))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_manual_service_creates_then_replays_exact_snapshot() -> None:
    prefix = "j5e-manual-replay"
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (account,), (_manual_source_snapshot(prefix, account),))
    before = await _state(prefix)
    try:
        first = await _manual_recalculate(prefix)
        second = await _manual_recalculate(prefix)

        assert first.status == "created"
        assert second.status == "replayed"
        assert first.snapshot_id == second.snapshot_id
        assert first.currency == "CZK"
        assert first.account_count == 1
        assert first.selected_account_snapshot_count == 1
        rows = await _rows(prefix)
        assert len(rows) == 1
        assert rows[0].source is SnapshotSource.manual_recalculation
        assert rows[0].timestamp == _snapshot_at(prefix)
        after = await _state(prefix)
        assert before[:-1] == after[:-1]
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_manual_service_uses_only_authenticated_principal_memberships() -> None:
    first_prefix = "j5e-principal-a"
    second_prefix = "j5e-principal-b"
    first_account = _account(first_prefix, "broker", AccountType.broker)
    second_account = _account(second_prefix, "broker", AccountType.broker)
    await _seed(
        first_prefix,
        (first_account,),
        (_manual_source_snapshot(first_prefix, first_account),),
    )
    await _seed(
        second_prefix,
        (second_account,),
        (_manual_source_snapshot(second_prefix, second_account),),
    )
    try:
        result = await _manual_recalculate(first_prefix)

        assert result.account_count == 1
        assert len(await _rows(first_prefix)) == 1
        assert await _rows(second_prefix) == ()
        assert not hasattr(result, "selected_account_ids")
    finally:
        await _cleanup(first_prefix)
        await _cleanup(second_prefix)


@pytest.mark.asyncio
async def test_manual_service_missing_source_fails_without_creating_source_or_target() -> None:
    prefix = "j5e-missing-source"
    account = _account(prefix, "broker", AccountType.broker)
    account_id = account.id
    await _seed(prefix, (account,), ())
    try:
        with pytest.raises(NetWorthSnapshotUnavailableError):
            await _manual_recalculate(prefix)

        assert await _rows(prefix) == ()
        engine = _engine()
        async with AsyncSession(engine) as session:
            source_count = await session.scalar(
                select(func.count())
                .select_from(AccountSnapshotModel)
                .where(AccountSnapshotModel.account_id == account_id)
            )
        await engine.dispose()
        assert source_count == 0
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [AccountType.bank, AccountType.cash, AccountType.savings],
)
async def test_manual_service_unsupported_active_account_fails_complete_user(
    account_type: AccountType,
) -> None:
    prefix = f"j5e-unsupported-{account_type.value}"
    account = _account(prefix, account_type.value, account_type)
    await _seed(prefix, (account,), (_manual_source_snapshot(prefix, account),))
    try:
        with pytest.raises(NetWorthSnapshotUnavailableError):
            await _manual_recalculate(prefix)
        assert await _rows(prefix) == ()
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_manual_service_base_currency_race_fails_on_serializable_revalidation() -> None:
    prefix = "j5e-currency-race"
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (account,), (_manual_source_snapshot(prefix, account),))
    engine = _engine()

    class CurrencyChangingWriter:
        def __init__(self, session: AsyncSession) -> None:
            self.session = session

        async def write(
            self,
            command: WriteNetWorthSnapshotCommand,
        ) -> NetWorthSnapshotWriteResult:
            async with AsyncSession(engine) as other:
                persisted = await other.get(UserModel, command.user_id)
                assert persisted is not None
                persisted.base_currency = "EUR"
                await other.commit()
            return await NetWorthSnapshotWriter(self.session).write(command)

    try:
        with pytest.raises(NetWorthSnapshotUnavailableError):
            await _manual_recalculate(prefix, writer_factory=CurrencyChangingWriter)
        assert await _rows(prefix) == ()
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_manual_service_maps_existing_physical_corruption_to_conflict_without_repair() -> (
    None
):
    prefix = "j5e-conflict"
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (account,), (_manual_source_snapshot(prefix, account),))
    try:
        first = await _manual_recalculate(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            persisted = await session.get(NetWorthSnapshotModel, first.snapshot_id)
            assert persisted is not None
            persisted.cash_value = Decimal("999.000000")
            await session.commit()
        await engine.dispose()

        with pytest.raises(NetWorthSnapshotConflictError):
            await _manual_recalculate(prefix)

        rows = await _rows(prefix)
        assert len(rows) == 1
        assert rows[0].cash_value == Decimal("999.000000")
    finally:
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_manual_service_writer_transaction_starts_with_serializable_after_handoff() -> None:
    prefix = "j5e-handoff-isolation"
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (account,), (_manual_source_snapshot(prefix, account),))
    engine = _engine()
    writer_statements: list[str] = []

    def capture(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        writer_statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        async with AsyncSession(engine) as session:
            authenticated = await session.scalar(
                select(UserModel).where(UserModel.id == _user_id(prefix))
            )
            assert authenticated is not None

            def factory(received: AsyncSession) -> NetWorthSnapshotWriter:
                assert received is session
                assert received.in_transaction() is False
                writer_statements.clear()
                return NetWorthSnapshotWriter(received)

            result = await ManualNetWorthSnapshotService(
                session,
                clock=lambda: _snapshot_at(prefix),
                writer_factory=factory,
            ).recalculate(RecalculateNetWorthSnapshotCommand(principal=_principal(prefix)))

        assert result.status == "created"
        assert writer_statements
        assert writer_statements[0].strip().upper() == (
            "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
        )
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
        await engine.dispose()
        await _cleanup(prefix)
