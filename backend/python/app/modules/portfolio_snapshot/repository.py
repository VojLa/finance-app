"""Explicit read-only SQL boundary for exact persisted portfolio snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import SnapshotGranularity
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel


@dataclass(frozen=True, slots=True)
class PersistedPortfolioSnapshotItem:
    """One physical item plus explicitly joined presentation metadata."""

    item: AccountSnapshotItemModel
    listing: AssetListingModel | None
    asset: AssetModel | None


class PortfolioSnapshotRepository:
    """Repository methods perform no writes and own no transaction boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_transaction_isolation(self) -> str | None:
        return await self.session.scalar(
            text("SHOW transaction_isolation").execution_options(autoflush=False)
        )

    async def load_account(self, account_id: str) -> AccountModel | None:
        return await self.session.scalar(
            select(AccountModel)
            .where(AccountModel.id == account_id)
            .execution_options(autoflush=False, populate_existing=True)
        )

    async def load_exact_snapshots(
        self,
        *,
        account_id: str,
        timestamp: datetime,
        granularity: SnapshotGranularity,
        currency: str,
    ) -> tuple[AccountSnapshotModel, ...]:
        result = await self.session.scalars(
            select(AccountSnapshotModel)
            .where(
                AccountSnapshotModel.account_id == account_id,
                AccountSnapshotModel.timestamp == timestamp,
                AccountSnapshotModel.granularity == granularity,
                AccountSnapshotModel.currency == currency,
            )
            .order_by(AccountSnapshotModel.id)
            .execution_options(autoflush=False, populate_existing=True)
        )
        return tuple(result)

    async def load_snapshot_items(
        self,
        snapshot_id: str,
    ) -> tuple[PersistedPortfolioSnapshotItem, ...]:
        result = await self.session.execute(
            select(
                AccountSnapshotItemModel,
                AssetListingModel,
                AssetModel,
            )
            .outerjoin(
                AssetListingModel,
                AssetListingModel.id == AccountSnapshotItemModel.listing_id,
            )
            .outerjoin(
                AssetModel,
                AssetModel.id == AssetListingModel.asset_id,
            )
            .where(AccountSnapshotItemModel.snapshot_id == snapshot_id)
            .order_by(
                AccountSnapshotItemModel.listing_id,
                AccountSnapshotItemModel.id,
                AccountSnapshotItemModel.asset_id,
            )
            .execution_options(autoflush=False, populate_existing=True)
        )
        return tuple(
            PersistedPortfolioSnapshotItem(item=item, listing=listing, asset=asset)
            for item, listing, asset in result
        )
