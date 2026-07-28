"""Explicit PostgreSQL lock and persistence boundary for account snapshots."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.enums import SnapshotGranularity
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.modules.holdings.repository import HoldingRebuildRepository


def advisory_lock_id(scope: str) -> int:
    return int.from_bytes(sha256(scope.encode()).digest()[:8], "big", signed=True)


def account_snapshot_lock_scope(
    *,
    account_id: str,
    timestamp: datetime,
    currency: str,
    granularity: SnapshotGranularity,
) -> str:
    return "\0".join(
        (
            "snapshots:account",
            account_id,
            timestamp.isoformat(timespec="milliseconds"),
            currency,
            granularity.value,
        )
    )


class AccountSnapshotWriterRepository:
    """Repository helpers assume one active caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.holdings = HoldingRebuildRepository(session)

    async def load_account_for_share(self, account_id: str) -> AccountModel | None:
        return await self.session.scalar(
            select(AccountModel)
            .where(AccountModel.id == account_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )

    async def acquire_snapshot_lock(
        self,
        *,
        account_id: str,
        timestamp: datetime,
        currency: str,
        granularity: SnapshotGranularity,
    ) -> None:
        scope = account_snapshot_lock_scope(
            account_id=account_id,
            timestamp=timestamp,
            currency=currency,
            granularity=granularity,
        )
        await self.session.execute(select(func.pg_advisory_xact_lock(advisory_lock_id(scope))))

    async def lock_canonical_evidence(self, account_id: str) -> None:
        await self.holdings.lock_canonical_history_scopes(account_id)
        await self.holdings.load_active_events_for_update(account_id)
        movements = await self.holdings.load_active_account_movements_for_update(account_id)
        holdings = await self.holdings.lock_account_holdings(account_id)
        listing_ids = tuple(
            sorted(
                {
                    value
                    for value in (
                        *(movement.listing_id for movement in movements),
                        *(holding.listing_id for holding in holdings),
                    )
                    if isinstance(value, str) and value
                }
            )
        )
        asset_ids = tuple(
            sorted(
                {
                    value
                    for value in (
                        *(movement.asset_id for movement in movements),
                        *(holding.asset_id for holding in holdings),
                    )
                    if isinstance(value, str) and value
                }
            )
        )
        await self.holdings.load_listings_for_update(listing_ids)
        await self.holdings.load_assets_for_update(asset_ids)

    async def lock_market_evidence_tables(self) -> None:
        # READ COMMITTED is required so a waiter can observe a just-committed exact
        # snapshot replay. Compatible SHARE locks give the separate price and FX
        # selections one coherent insertion/update boundary without serializing
        # other snapshot readers.
        await self.session.execute(
            text('LOCK TABLE public."PriceSnapshot", public."ExchangeRate" IN SHARE MODE')
        )

    async def load_existing_snapshot(
        self,
        *,
        account_id: str,
        timestamp: datetime,
        currency: str,
        granularity: SnapshotGranularity,
    ) -> AccountSnapshotModel | None:
        return await self.session.scalar(
            select(AccountSnapshotModel)
            .where(
                AccountSnapshotModel.account_id == account_id,
                AccountSnapshotModel.timestamp == timestamp,
                AccountSnapshotModel.currency == currency,
                AccountSnapshotModel.granularity == granularity,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_snapshot_by_id(self, snapshot_id: str) -> AccountSnapshotModel | None:
        return await self.session.scalar(
            select(AccountSnapshotModel)
            .where(AccountSnapshotModel.id == snapshot_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_snapshot_items(
        self,
        snapshot_id: str,
    ) -> tuple[AccountSnapshotItemModel, ...]:
        result = await self.session.scalars(
            select(AccountSnapshotItemModel)
            .where(AccountSnapshotItemModel.snapshot_id == snapshot_id)
            .order_by(AccountSnapshotItemModel.listing_id, AccountSnapshotItemModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return tuple(result.all())

    def add_snapshot(self, snapshot: AccountSnapshotModel) -> None:
        self.session.add(snapshot)

    def add_items(self, items: tuple[AccountSnapshotItemModel, ...]) -> None:
        self.session.add_all(items)

    async def flush(self) -> None:
        await self.session.flush()

    async def reload_snapshot(self, snapshot_id: str) -> AccountSnapshotModel | None:
        return await self.session.scalar(
            select(AccountSnapshotModel)
            .where(AccountSnapshotModel.id == snapshot_id)
            .execution_options(populate_existing=True)
        )

    async def reload_snapshot_items(
        self,
        snapshot_id: str,
    ) -> tuple[AccountSnapshotItemModel, ...]:
        result = await self.session.scalars(
            select(AccountSnapshotItemModel)
            .where(AccountSnapshotItemModel.snapshot_id == snapshot_id)
            .order_by(AccountSnapshotItemModel.listing_id, AccountSnapshotItemModel.id)
            .execution_options(populate_existing=True)
        )
        return tuple(result.all())
