from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.db.models.snapshots import NetWorthSnapshotModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.portfolio_history.models import PortfolioHistoryRange
from app.modules.portfolio_history.service import (
    PortfolioHistoryUnavailableError,
    ReadPortfolioHistoryCommand,
    SnapshotBackedPortfolioHistoryService,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
END = datetime(2026, 8, 1, 12, 0, 0, 123000)


def _engine() -> AsyncEngine:
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=6)


def _user(prefix: str, suffix: str, currency: str = "EUR") -> UserModel:
    user_id = f"{prefix}-{suffix}"
    return UserModel(
        id=user_id,
        email=f"{user_id}@example.test",
        name=user_id,
        password_hash=None,
        base_currency=currency,
        created_at=END,
        updated_at=END,
    )


def _snapshot(
    user_id: str,
    suffix: str,
    timestamp: datetime,
    *,
    granularity: SnapshotGranularity = SnapshotGranularity.day,
    currency: str = "EUR",
    cash: str = "10.000000",
    portfolio: str = "100.000000",
    liabilities: str = "20.000000",
    total: str = "90.000000",
) -> NetWorthSnapshotModel:
    return NetWorthSnapshotModel(
        id=f"{user_id}-{suffix}",
        user_id=user_id,
        timestamp=timestamp,
        granularity=granularity,
        source=SnapshotSource.scheduled,
        currency=currency,
        cash_value=Decimal(cash),
        portfolio_value=Decimal(portfolio),
        liabilities_value=Decimal(liabilities),
        total_net_worth=Decimal(total),
        is_recalculated=False,
        calculated_at=timestamp,
        calculation_version=1,
        created_at=timestamp,
        cash_value_by_currency=None,
        portfolio_value_by_currency=None,
        liabilities_value_by_currency=None,
        total_net_worth_by_currency=None,
        exchange_rates=None,
    )


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        user_ids = tuple(
            await session.scalars(select(UserModel.id).where(UserModel.id.startswith(f"{prefix}-")))
        )
        if user_ids:
            await session.execute(
                delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id.in_(user_ids))
            )
            await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        await session.commit()
    await engine.dispose()


async def _seed(prefix: str) -> dict[str, str]:
    engine = _engine()
    users = {
        "a": f"{prefix}-a",
        "b": f"{prefix}-b",
        "empty": f"{prefix}-empty",
        "corrupt": f"{prefix}-corrupt",
    }
    async with AsyncSession(engine) as session:
        session.add_all(
            (
                _user(prefix, "a"),
                _user(prefix, "b"),
                _user(prefix, "empty"),
                _user(prefix, "corrupt"),
            )
        )
        await session.flush()
        duplicate_at = END - timedelta(days=2)
        session.add_all(
            (
                _snapshot(users["a"], "outside", END - timedelta(days=400)),
                _snapshot(
                    users["a"],
                    "inside-negative",
                    END - timedelta(days=10),
                    cash="-200.000000",
                    portfolio="100.000000",
                    liabilities="50.000000",
                    total="-150.000000",
                ),
                _snapshot(users["a"], "duplicate-day", duplicate_at),
                _snapshot(
                    users["a"],
                    "duplicate-minute",
                    duplicate_at,
                    granularity=SnapshotGranularity.minute,
                ),
                _snapshot(users["a"], "latest", END),
                _snapshot(users["a"], "future", END + timedelta(milliseconds=1)),
                _snapshot(users["a"], "wrong-currency", END - timedelta(days=1), currency="CZK"),
                _snapshot(
                    users["b"],
                    "foreign",
                    END - timedelta(days=3),
                    cash="1.000000",
                    portfolio="2.000000",
                    liabilities="0.000000",
                    total="3.000000",
                ),
                _snapshot(users["corrupt"], "bad-total", END, total="91.000000"),
            )
        )
        await session.commit()
    await engine.dispose()
    return users


@pytest.mark.integration
def test_postgresql_history_read_is_exact_isolated_read_only_and_idle() -> None:
    prefix = f"r7a-history-{uuid4().hex}"
    asyncio.run(_cleanup(prefix))
    users = asyncio.run(_seed(prefix))

    async def scenario() -> None:
        engine = _engine()
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                version = await session.scalar(text("SHOW server_version"))
                assert isinstance(version, str) and version.startswith("16.")
                await session.rollback()
                before = await session.scalar(
                    select(func.count()).select_from(NetWorthSnapshotModel)
                )
                await session.rollback()
                service = SnapshotBackedPortfolioHistoryService(session, clock=lambda: END)
                result = await service.read(
                    ReadPortfolioHistoryCommand(
                        AuthenticatedPrincipal(
                            user_id=users["a"],
                            email="a@example.test",
                            name="A",
                        ),
                        PortfolioHistoryRange.one_year,
                    )
                )
                assert not session.in_transaction()
                assert result.history.currency == "EUR"
                assert tuple(point.timestamp for point in result.history.points) == (
                    END - timedelta(days=10),
                    END - timedelta(days=2),
                    END,
                )
                assert result.selected_snapshot_ids == (
                    f"{users['a']}-inside-negative",
                    f"{users['a']}-duplicate-minute",
                    f"{users['a']}-latest",
                )
                assert result.history.points[0].net_worth_value == Decimal("-150.000000")
                after = await session.scalar(
                    select(func.count()).select_from(NetWorthSnapshotModel)
                )
                await session.rollback()
                assert before == after

                empty = await service.read(
                    ReadPortfolioHistoryCommand(
                        AuthenticatedPrincipal(
                            user_id=users["empty"],
                            email="empty@example.test",
                            name=None,
                        ),
                        PortfolioHistoryRange.all,
                    )
                )
                assert empty.history.points == ()
                assert not session.in_transaction()

                with pytest.raises(PortfolioHistoryUnavailableError):
                    await service.read(
                        ReadPortfolioHistoryCommand(
                            AuthenticatedPrincipal(
                                user_id=users["corrupt"],
                                email="corrupt@example.test",
                                name=None,
                            ),
                            PortfolioHistoryRange.all,
                        )
                    )
                assert not session.in_transaction()
        finally:
            await engine.dispose()

    try:
        asyncio.run(scenario())
    finally:
        asyncio.run(_cleanup(prefix))
