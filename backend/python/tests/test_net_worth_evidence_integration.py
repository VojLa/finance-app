from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy import delete, event, func, select
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
from app.modules.net_worth.evidence_service import (
    BuildNetWorthEvidenceCommand,
    CompleteNetWorthEvidence,
    NetWorthEvidenceService,
    NetWorthEvidenceStateError,
)
from app.modules.net_worth.repository import NetWorthEvidenceRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
SNAPSHOT_AT = datetime(2032, 8, 2)


def _engine() -> AsyncEngine:
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=6)


@asynccontextmanager
async def _repeatable_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="REPEATABLE READ")
        async with AsyncSession(bind=connection, expire_on_commit=False) as session:
            transaction = await session.begin()
            try:
                yield session
            finally:
                if transaction.is_active:
                    await transaction.rollback()


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


def _user(prefix: str) -> UserModel:
    return UserModel(
        id=f"{prefix}-user",
        email=f"{prefix}@example.com",
        name="Net Worth",
        password_hash=None,
        base_currency="CZK",
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
    )


def _account(
    prefix: str,
    suffix: str,
    account_type: AccountType,
    *,
    archived: bool = False,
) -> AccountModel:
    return AccountModel(
        id=f"{prefix}-{suffix}",
        name=suffix,
        type=account_type,
        currency="CZK",
        color=None,
        is_archived=archived,
        archived_at=SNAPSHOT_AT if archived else None,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
        notes=None,
    )


def _membership(prefix: str, account: AccountModel) -> AccountMemberModel:
    return AccountMemberModel(
        id=f"{prefix}-member-{account.id}",
        account_id=account.id,
        user_id=f"{prefix}-user",
        role=AccountMemberRole.owner,
        relation_type=AccountRelationType.owner,
        invited_by_id=None,
        accepted_at=SNAPSHOT_AT,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
    )


def _snapshot(
    prefix: str,
    account: AccountModel,
    *,
    timestamp: datetime = SNAPSHOT_AT,
    granularity: SnapshotGranularity = SnapshotGranularity.day,
    currency: str = "CZK",
    calculation_version: int = 1,
    cash: str | None = None,
    investment: str | None = None,
    liability: str | None = None,
) -> AccountSnapshotModel:
    is_liability = account.type in {
        AccountType.credit_card,
        AccountType.loan,
        AccountType.mortgage,
    }
    cash_value = Decimal(cash if cash is not None else ("0" if is_liability else "100"))
    investment_value = Decimal(
        investment if investment is not None else ("0" if is_liability else "400")
    )
    cost_basis = Decimal(0) if is_liability else Decimal("300")
    liability_value = Decimal(
        liability if liability is not None else ("250" if is_liability else "0")
    )
    return AccountSnapshotModel(
        id=f"{prefix}-snapshot-{account.id}",
        account_id=account.id,
        timestamp=timestamp,
        granularity=granularity,
        source=SnapshotSource.manual_recalculation,
        currency=currency,
        cash_value=cash_value,
        investment_value=investment_value,
        investment_cost_basis=cost_basis,
        liabilities_value=liability_value,
        total_value=cash_value + investment_value - liability_value,
        is_recalculated=True,
        calculated_at=SNAPSHOT_AT,
        calculation_version=calculation_version,
        created_at=SNAPSHOT_AT,
        net_deposits_value=Decimal(0),
        realized_pnl_value=Decimal(0),
        unrealized_pnl_value=investment_value - cost_basis,
        fees_value=Decimal(0),
        taxes_value=Decimal(0),
        cash_value_by_currency=({} if cash_value == 0 else {"CZK": f"{cash_value:.6f}"}),
        investment_value_by_currency=(
            {} if investment_value == 0 else {"CZK": f"{investment_value:.10f}"}
        ),
        investment_cost_basis_by_currency=(
            {} if cost_basis == 0 else {"CZK": f"{cost_basis:.10f}"}
        ),
        net_deposits_by_currency={},
        realized_pnl_by_currency={},
        unrealized_pnl_by_currency=(
            {} if investment_value == cost_basis else {"CZK": "100.000000"}
        ),
        fees_by_currency={},
        taxes_by_currency={},
        exchange_rates={"version": 1, "snapshotRates": [], "historicalRateIds": []},
    )


def _command(prefix: str) -> BuildNetWorthEvidenceCommand:
    return BuildNetWorthEvidenceCommand(
        user_id=f"{prefix}-user",
        timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        currency="CZK",
        calculation_version=1,
    )


async def _seed(
    prefix: str,
    accounts: tuple[AccountModel, ...],
    snapshots: tuple[AccountSnapshotModel, ...],
) -> None:
    engine = _engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(_user(prefix))
        session.add_all(accounts)
        await session.flush()
        session.add_all(_membership(prefix, account) for account in accounts)
        session.add_all(snapshots)
        await session.commit()
    await engine.dispose()


async def _build(
    engine: AsyncEngine,
    prefix: str,
    *,
    repository: NetWorthEvidenceRepository | None = None,
) -> CompleteNetWorthEvidence:
    async with _repeatable_session(engine) as session:
        return await NetWorthEvidenceService(
            session,
            repository=repository,
        ).build(_command(prefix))


async def _state(prefix: str) -> tuple[object, ...]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        user_rows = tuple(
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
        account_rows = tuple(
            (
                row.id,
                row.type,
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
        membership_rows = tuple(
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
                .where(AccountMemberModel.user_id == f"{prefix}-user")
                .order_by(AccountMemberModel.id)
            )
        )
        snapshot_rows = tuple(
            (
                row.id,
                row.account_id,
                row.timestamp,
                row.granularity,
                row.currency,
                row.cash_value,
                row.investment_value,
                row.liabilities_value,
                row.total_value,
                row.cash_value_by_currency,
                row.investment_value_by_currency,
            )
            for row in await session.scalars(
                select(AccountSnapshotModel)
                .where(AccountSnapshotModel.id.startswith(f"{prefix}-"))
                .order_by(AccountSnapshotModel.id)
            )
        )
        counts = (
            await session.scalar(
                select(func.count())
                .select_from(AccountSnapshotItemModel)
                .join(
                    AccountSnapshotModel,
                    AccountSnapshotModel.id == AccountSnapshotItemModel.snapshot_id,
                )
                .where(AccountSnapshotModel.id.startswith(f"{prefix}-"))
            )
            or 0,
            await session.scalar(
                select(func.count())
                .select_from(NetWorthSnapshotModel)
                .where(NetWorthSnapshotModel.user_id == f"{prefix}-user")
            )
            or 0,
        )
    await engine.dispose()
    return user_rows, account_rows, membership_rows, snapshot_rows, counts


@pytest.mark.asyncio
async def test_empty_existing_user_builds_zero_without_writes() -> None:
    prefix = "j5b-empty"
    await _cleanup(prefix)
    await _seed(prefix, (), ())
    before = await _state(prefix)
    engine = _engine()
    try:
        result = await _build(engine, prefix)
    finally:
        await engine.dispose()

    assert result.projection.account_count == 0
    assert result.projection.net_worth_value == 0
    assert result.selected_account_snapshot_ids == ()
    assert await _state(prefix) == before
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_one_broker_maps_exact_persisted_values() -> None:
    prefix = "j5b-broker"
    await _cleanup(prefix)
    account = _account(prefix, "broker", AccountType.broker)
    snapshot = _snapshot(prefix, account)
    await _seed(prefix, (account,), (snapshot,))
    before = await _state(prefix)
    engine = _engine()
    try:
        result = await _build(engine, prefix)
    finally:
        await engine.dispose()

    assert result.projection.assets_value == Decimal("500.000000")
    assert result.projection.liabilities_value == 0
    assert result.projection.net_worth_value == Decimal("500.000000")
    assert result.selected_account_ids == (account.id,)
    assert result.selected_account_snapshot_ids == (snapshot.id,)
    assert await _state(prefix) == before
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_one_liability_maps_positive_debt_and_negative_net_worth() -> None:
    prefix = "j5b-liability"
    await _cleanup(prefix)
    account = _account(prefix, "mortgage", AccountType.mortgage)
    snapshot = _snapshot(prefix, account)
    await _seed(prefix, (account,), (snapshot,))
    engine = _engine()
    try:
        result = await _build(engine, prefix)
    finally:
        await engine.dispose()

    assert result.projection.cash_value == 0
    assert result.projection.portfolio_value == 0
    assert result.projection.liabilities_value == Decimal("250.000000")
    assert result.projection.net_worth_value == Decimal("-250.000000")
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_mixed_portfolio_is_complete_and_uses_one_snapshot_query() -> None:
    prefix = "j5b-mixed"
    await _cleanup(prefix)
    accounts = (
        _account(prefix, "broker", AccountType.broker),
        _account(prefix, "crypto", AccountType.crypto_wallet),
        _account(prefix, "mortgage", AccountType.mortgage),
        _account(prefix, "card", AccountType.credit_card),
    )
    snapshots = tuple(_snapshot(prefix, account) for account in accounts)
    await _seed(prefix, accounts, snapshots)
    engine = _engine()
    snapshot_selects: list[str] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT") and '"AccountSnapshot"' in statement:
            snapshot_selects.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture_statement)
    try:
        result = await _build(engine, prefix)
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture_statement)
        await engine.dispose()

    assert result.projection.assets_value == Decimal("1000.000000")
    assert result.projection.liabilities_value == Decimal("500.000000")
    assert result.projection.net_worth_value == Decimal("500.000000")
    assert result.selected_account_ids == tuple(sorted(account.id for account in accounts))
    assert len(snapshot_selects) == 1
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_missing_exact_snapshot_fails_closed() -> None:
    prefix = "j5b-missing"
    await _cleanup(prefix)
    account = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (account,), ())
    engine = _engine()
    try:
        with pytest.raises(NetWorthEvidenceStateError):
            await _build(engine, prefix)
    finally:
        await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("suffix", "changes"),
    [
        ("timestamp", {"timestamp": SNAPSHOT_AT - timedelta(days=1)}),
        ("granularity", {"granularity": SnapshotGranularity.hour}),
        ("currency", {"currency": "EUR"}),
        ("version", {"calculation_version": 2}),
    ],
)
async def test_mismatched_snapshot_identity_or_version_fails_closed(
    suffix: str,
    changes: dict[str, object],
) -> None:
    prefix = f"j5b-{suffix}"
    await _cleanup(prefix)
    account = _account(prefix, "broker", AccountType.broker)
    snapshot = _snapshot(prefix, account, **cast(Any, changes))
    await _seed(prefix, (account,), (snapshot,))
    engine = _engine()
    try:
        with pytest.raises(NetWorthEvidenceStateError):
            await _build(engine, prefix)
    finally:
        await engine.dispose()
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_unsupported_active_account_prevents_partial_net_worth() -> None:
    prefix = "j5b-unsupported"
    await _cleanup(prefix)
    broker = _account(prefix, "broker", AccountType.broker)
    bank = _account(prefix, "bank", AccountType.bank)
    await _seed(prefix, (broker, bank), (_snapshot(prefix, broker),))
    before = await _state(prefix)
    engine = _engine()
    try:
        with pytest.raises(NetWorthEvidenceStateError):
            await _build(engine, prefix)
    finally:
        await engine.dispose()
    assert await _state(prefix) == before
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_archived_account_is_excluded_under_current_state_contract() -> None:
    prefix = "j5b-archived"
    await _cleanup(prefix)
    archived = _account(prefix, "bank", AccountType.bank, archived=True)
    await _seed(prefix, (archived,), ())
    engine = _engine()
    try:
        result = await _build(engine, prefix)
    finally:
        await engine.dispose()
    assert result.projection.account_count == 0
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_corrupt_jsonb_fails_closed_without_repair() -> None:
    prefix = "j5b-json"
    await _cleanup(prefix)
    account = _account(prefix, "broker", AccountType.broker)
    snapshot = _snapshot(prefix, account)
    snapshot.cash_value_by_currency = cast(Any, ["corrupt"])
    await _seed(prefix, (account,), (snapshot,))
    before = await _state(prefix)
    engine = _engine()
    try:
        with pytest.raises(NetWorthEvidenceStateError):
            await _build(engine, prefix)
    finally:
        await engine.dispose()
    assert await _state(prefix) == before
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_corrupt_financial_row_is_rejected_by_projection_without_repair() -> None:
    prefix = "j5b-financial"
    await _cleanup(prefix)
    account = _account(prefix, "broker", AccountType.broker)
    snapshot = _snapshot(prefix, account)
    snapshot.total_value = Decimal("499.000000")
    await _seed(prefix, (account,), (snapshot,))
    before = await _state(prefix)
    engine = _engine()
    try:
        with pytest.raises(NetWorthEvidenceStateError):
            await _build(engine, prefix)
    finally:
        await engine.dispose()
    assert await _state(prefix) == before
    await _cleanup(prefix)


@pytest.mark.asyncio
async def test_service_does_not_implicitly_flush_caller_pending_state() -> None:
    prefix = "j5b-no-flush"
    await _cleanup(prefix)
    await _seed(prefix, (), ())
    before = await _state(prefix)
    engine = _engine()
    flushes: list[object] = []

    def capture_flush(*args: object) -> None:
        flushes.append(args)

    try:
        async with engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="REPEATABLE READ")
            async with AsyncSession(bind=connection, expire_on_commit=False) as session:
                transaction = await session.begin()
                event.listen(session.sync_session, "before_flush", capture_flush)
                session.add(
                    UserModel(
                        id=f"{prefix}-pending",
                        email=f"{prefix}-pending@example.com",
                        name=None,
                        password_hash=None,
                        base_currency="CZK",
                        created_at=SNAPSHOT_AT,
                        updated_at=SNAPSHOT_AT,
                    )
                )
                result = await NetWorthEvidenceService(session).build(_command(prefix))
                event.remove(session.sync_session, "before_flush", capture_flush)
                await transaction.rollback()
        assert result.projection.account_count == 0
        assert flushes == []
        assert await _state(prefix) == before
    finally:
        await engine.dispose()
    await _cleanup(prefix)


class PausingNetWorthEvidenceRepository(NetWorthEvidenceRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        discovered: asyncio.Event,
        resume: asyncio.Event,
    ) -> None:
        super().__init__(session)
        self.discovered = discovered
        self.resume = resume

    async def load_account_accesses(self, user_id: str):
        result = await super().load_account_accesses(user_id)
        self.discovered.set()
        await self.resume.wait()
        return result


@pytest.mark.asyncio
async def test_repeatable_read_excludes_concurrent_new_account_as_one_coherent_view() -> None:
    prefix = "j5b-coherent"
    await _cleanup(prefix)
    original = _account(prefix, "broker", AccountType.broker)
    await _seed(prefix, (original,), (_snapshot(prefix, original),))
    engine = _engine()
    discovered = asyncio.Event()
    resume = asyncio.Event()
    try:
        async with engine.connect() as connection:
            connection = await connection.execution_options(isolation_level="REPEATABLE READ")
            async with AsyncSession(bind=connection, expire_on_commit=False) as reader:
                transaction = await reader.begin()
                repository = PausingNetWorthEvidenceRepository(
                    reader,
                    discovered=discovered,
                    resume=resume,
                )
                task = asyncio.create_task(
                    NetWorthEvidenceService(reader, repository=repository).build(_command(prefix))
                )
                await asyncio.wait_for(discovered.wait(), timeout=5)

                concurrent = _account(prefix, "crypto", AccountType.crypto_wallet)
                async with AsyncSession(engine, expire_on_commit=False) as writer:
                    writer.add(concurrent)
                    await writer.flush()
                    writer.add(_membership(prefix, concurrent))
                    writer.add(_snapshot(prefix, concurrent))
                    await writer.commit()

                resume.set()
                old_view = await asyncio.wait_for(task, timeout=5)
                await transaction.rollback()

        assert old_view.selected_account_ids == (original.id,)
        new_view = await _build(engine, prefix)
        assert new_view.selected_account_ids == tuple(sorted((original.id, concurrent.id)))
    finally:
        await engine.dispose()
    await _cleanup(prefix)
