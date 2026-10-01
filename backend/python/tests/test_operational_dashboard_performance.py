"""Recent dashboard read shape and disposable-PostgreSQL timing evidence."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from decimal import Decimal
from math import ceil
from time import perf_counter
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    TransactionClassification,
    TransactionType,
)
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.operational_dashboard import repository as dashboard_repository
from app.modules.operational_dashboard.repository import OperationalDashboardRepository
from app.modules.transactions.operational_visibility import operational_transaction_from_values


class _EmptyResult:
    def all(self) -> list[object]:
        return []


class _RecordingSession:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: object) -> object:
        self.statements.append(str(statement))
        return _EmptyResult()


def test_recent_transactions_query_has_no_correlated_scalar_subqueries() -> None:
    session = _RecordingSession()
    repository = OperationalDashboardRepository(cast(AsyncSession, session))
    assert asyncio.run(repository.recent_transactions(account_ids=("account",), limit=6)) == []
    assert len(session.statements) == 1
    assert session.statements[0].upper().count("SELECT ") == 1


def test_recent_transactions_pages_past_hidden_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 9, 28, 12)
    account = AccountModel(id="account")
    hidden = [TransactionModel(id=f"hidden-{index}", date=now) for index in range(64)]
    visible = [TransactionModel(id=f"visible-{index}", date=now) for index in range(6)]

    class _PageSession(_RecordingSession):
        def __init__(self) -> None:
            super().__init__()
            self.pages = [
                [(transaction, account, None) for transaction in hidden],
                [(transaction, account, None) for transaction in visible],
            ]

        async def execute(self, statement: object) -> _PageResult:
            self.statements.append(str(statement))
            return _PageResult(self.pages.pop(0))

    class _PageResult:
        def __init__(self, rows: list[tuple[TransactionModel, AccountModel, None]]) -> None:
            self.rows = rows

        def all(self) -> list[tuple[TransactionModel, AccountModel, None]]:
            return self.rows

    async def evaluate(
        _session: AsyncSession, candidates: list[TransactionModel]
    ) -> dict[str, object]:
        return {
            transaction.id: operational_transaction_from_values(transaction, None, None, None)
            for transaction in candidates
            if transaction.id.startswith("visible-")
        }

    monkeypatch.setattr(dashboard_repository, "operational_transactions_for_candidates", evaluate)
    session = _PageSession()
    repository = OperationalDashboardRepository(cast(AsyncSession, session))
    rows = asyncio.run(repository.recent_transactions(account_ids=("account",), limit=6))
    assert [row.transaction.id for row, _, _ in rows] == [transaction.id for transaction in visible]
    assert len(session.statements) == 2


async def _measure(database_url: str) -> None:
    engine = create_async_engine(normalize_database_url(database_url))
    prefix = f"dashboard-perf-{uuid4().hex}"
    account_ids = tuple(f"{prefix}-account-{index:02d}" for index in range(20))
    now = datetime(2026, 9, 28, 12)
    try:
        async with AsyncSession(engine) as session:
            session.add(
                UserModel(
                    id=prefix,
                    email=f"{prefix}@example.test",
                    name="Performance test",
                    password_hash=None,
                    base_currency="CZK",
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            for account_id in account_ids:
                session.add(
                    AccountModel(
                        id=account_id,
                        name=account_id,
                        type=AccountType.bank,
                        currency="CZK",
                        color=None,
                        notes=None,
                        is_archived=False,
                        archived_at=None,
                        created_at=now,
                        updated_at=now,
                    )
                )
            await session.flush()
            for index, account_id in enumerate(account_ids):
                session.add(
                    AccountMemberModel(
                        id=f"{prefix}-member-{index:02d}",
                        account_id=account_id,
                        user_id=prefix,
                        role=AccountMemberRole.owner,
                        relation_type=AccountRelationType.owner,
                        invited_by_id=None,
                        accepted_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                for transaction_index in range(10):
                    session.add(
                        TransactionModel(
                            id=f"{prefix}-transaction-{index:02d}-{transaction_index:02d}",
                            date=now - timedelta(seconds=index * 10 + transaction_index),
                            booking_date=None,
                            amount=Decimal("1"),
                            currency="CZK",
                            reporting_amount=Decimal("1"),
                            reporting_currency="CZK",
                            type=TransactionType.income,
                            classification=TransactionClassification.real_income,
                            description=None,
                            note=None,
                            counterparty=None,
                            external_id=None,
                            is_reviewed=True,
                            archived_at=None,
                            deleted_at=None,
                            category_id=None,
                            account_id=account_id,
                            import_batch_id=None,
                            created_at=now,
                            updated_at=now,
                        )
                    )
            await session.flush()
            await session.commit()
            await session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
            repository = OperationalDashboardRepository(session)
            statements = 0

            def count_statement(*_: object) -> None:
                nonlocal statements
                statements += 1

            event.listen(engine.sync_engine, "before_cursor_execute", count_statement)
            try:
                for jit in ("on", "off"):
                    await session.execute(text(f"SET LOCAL jit = {jit}"))
                    for account_count in (1, 5, 20):
                        scope = account_ids[:account_count]
                        for _ in range(3):
                            assert (
                                len(
                                    await repository.recent_transactions(account_ids=scope, limit=6)
                                )
                                == 6
                            )
                        durations: list[float] = []
                        query_counts: list[int] = []
                        for _ in range(40):
                            before = statements
                            start = perf_counter()
                            rows = await repository.recent_transactions(account_ids=scope, limit=6)
                            durations.append((perf_counter() - start) * 1000)
                            query_counts.append(statements - before)
                            assert len(rows) == 6
                        ordered = sorted(durations)
                        p50 = ordered[ceil(0.50 * len(ordered)) - 1]
                        p95 = ordered[ceil(0.95 * len(ordered)) - 1]
                        print(
                            f"recent jit={jit} accounts={account_count} "
                            f"queries={sorted(set(query_counts))} "
                            f"p50_ms={p50:.2f} p95_ms={p95:.2f} "
                            f"min_ms={ordered[0]:.2f} max_ms={ordered[-1]:.2f}"
                        )
                        assert set(query_counts) == {3}
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", count_statement)
    finally:
        async with AsyncSession(engine) as cleanup:
            await cleanup.execute(
                delete(TransactionModel).where(TransactionModel.account_id.in_(account_ids))
            )
            await cleanup.execute(
                delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
            )
            await cleanup.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
            await cleanup.execute(delete(UserModel).where(UserModel.id == prefix))
            await cleanup.commit()
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(
    not (os.getenv("DATABASE_URL") or "").endswith("/finance_app_stabilization_test"),
    reason="dedicated finance_app_stabilization_test database is required",
)
def test_recent_transactions_disposable_postgresql_timing() -> None:
    database_url = os.environ["DATABASE_URL"]
    assert database_url.endswith("/finance_app_stabilization_test")
    asyncio.run(_measure(database_url))
