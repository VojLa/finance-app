"""Explicit PostgreSQL lock and persistence boundary for net-worth snapshots."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import SnapshotGranularity
from app.db.models.snapshots import NetWorthSnapshotModel


def advisory_lock_id(scope: str) -> int:
    return int.from_bytes(sha256(scope.encode()).digest()[:8], "big", signed=True)


def net_worth_snapshot_lock_scope(
    *,
    user_id: str,
    timestamp: datetime,
    currency: str,
    granularity: SnapshotGranularity,
) -> str:
    return "\0".join(
        (
            "net_worth:snapshot",
            user_id,
            timestamp.isoformat(timespec="milliseconds"),
            currency,
            granularity.value,
        )
    )


class NetWorthSnapshotWriterRepository:
    """Repository helpers assume one active writer-owned transaction attempt."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_transaction_serializable(self) -> None:
        await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))

    async def acquire_snapshot_lock(
        self,
        *,
        user_id: str,
        timestamp: datetime,
        currency: str,
        granularity: SnapshotGranularity,
    ) -> None:
        scope = net_worth_snapshot_lock_scope(
            user_id=user_id,
            timestamp=timestamp,
            currency=currency,
            granularity=granularity,
        )
        await self.session.execute(select(func.pg_advisory_xact_lock(advisory_lock_id(scope))))

    async def load_existing_snapshot(
        self,
        *,
        user_id: str,
        timestamp: datetime,
        currency: str,
        granularity: SnapshotGranularity,
    ) -> NetWorthSnapshotModel | None:
        return await self.session.scalar(
            select(NetWorthSnapshotModel)
            .where(
                NetWorthSnapshotModel.user_id == user_id,
                NetWorthSnapshotModel.timestamp == timestamp,
                NetWorthSnapshotModel.currency == currency,
                NetWorthSnapshotModel.granularity == granularity,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_snapshot_by_id(self, snapshot_id: str) -> NetWorthSnapshotModel | None:
        return await self.session.scalar(
            select(NetWorthSnapshotModel)
            .where(NetWorthSnapshotModel.id == snapshot_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def add_snapshot(self, snapshot: NetWorthSnapshotModel) -> None:
        self.session.add(snapshot)

    async def flush(self) -> None:
        await self.session.flush()

    async def reload_snapshot(self, snapshot_id: str) -> NetWorthSnapshotModel | None:
        return await self.session.scalar(
            select(NetWorthSnapshotModel)
            .where(NetWorthSnapshotModel.id == snapshot_id)
            .execution_options(populate_existing=True)
        )
