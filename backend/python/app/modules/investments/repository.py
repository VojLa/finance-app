from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.canonical_lineage import (
    AccountCanonicalChangeModel,
    AccountCanonicalStateModel,
)
from app.db.models.enums import MarketDataFailureReason, PriceSource
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.market_health import MarketDataListingHealthModel
from app.db.models.prices import PriceSnapshotModel
from app.modules.holdings.repository import advisory_lock_id


class InvestmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_idempotency_key(self, value: str) -> None:
        await self.session.execute(select(func.pg_advisory_xact_lock(advisory_lock_id(value))))

    async def ensure_canonical_state(self, account_id: str, now: datetime) -> None:
        state = await self.session.scalar(
            select(AccountCanonicalStateModel)
            .where(AccountCanonicalStateModel.account_id == account_id)
            .with_for_update()
        )
        if state is not None:
            return
        count = await self.session.scalar(
            select(func.count())
            .select_from(AccountCanonicalChangeModel)
            .where(AccountCanonicalChangeModel.account_id == account_id)
        )
        if count:
            raise RuntimeError("Canonical account state is unavailable.")
        self.session.add(
            AccountCanonicalStateModel(
                account_id=account_id,
                last_revision=0,
                last_investment_revision=0,
                holding_revision=None,
                updated_at=now,
            )
        )
        await self.session.flush()

    async def event_for_update(self, event_id: str) -> InvestmentEventModel | None:
        return await self.session.scalar(
            select(InvestmentEventModel)
            .where(InvestmentEventModel.id == event_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def event_movements_for_update(self, event_id: str) -> list[InvestmentMovementModel]:
        return list(
            (
                await self.session.scalars(
                    select(InvestmentMovementModel)
                    .where(InvestmentMovementModel.event_id == event_id)
                    .order_by(InvestmentMovementModel.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).all()
        )

    def add(self, value: object) -> None:
        self.session.add(value)

    async def flush(self) -> None:
        await self.session.flush()

    async def symbol_positions(
        self, *, user_id: str, symbol: str
    ) -> list[
        tuple[
            HoldingModel,
            AccountModel,
            AssetListingModel | None,
            AssetModel | None,
        ]
    ]:
        return [
            (holding, account, listing, asset)
            for holding, account, listing, asset in (
                await self.session.execute(
                    select(
                        HoldingModel,
                        AccountModel,
                        AssetListingModel,
                        AssetModel,
                    )
                    .join(AccountModel, AccountModel.id == HoldingModel.account_id)
                    .join(
                        AccountMemberModel,
                        AccountMemberModel.account_id == HoldingModel.account_id,
                    )
                    .outerjoin(AssetListingModel, AssetListingModel.id == HoldingModel.listing_id)
                    .outerjoin(AssetModel, AssetModel.id == AssetListingModel.asset_id)
                    .where(
                        AccountMemberModel.user_id == user_id,
                        AccountModel.is_archived.is_(False),
                        HoldingModel.symbol == symbol,
                    )
                    .order_by(AccountModel.created_at, AccountModel.id, HoldingModel.id)
                    .execution_options(autoflush=False)
                )
            ).all()
        ]

    async def exact_price(
        self,
        *,
        listing_id: str,
        asset_id: str,
        source: PriceSource,
        provider_symbol: str,
        currency: str,
    ) -> tuple[PriceSnapshotModel | None, bool]:
        price = await self.session.scalar(
            select(PriceSnapshotModel)
            .where(
                PriceSnapshotModel.listing_id == listing_id,
                PriceSnapshotModel.asset_id == asset_id,
                PriceSnapshotModel.source == source,
                PriceSnapshotModel.provider_symbol == provider_symbol,
                PriceSnapshotModel.currency == currency,
                PriceSnapshotModel.price > 0,
            )
            .order_by(PriceSnapshotModel.timestamp.desc(), PriceSnapshotModel.id.desc())
            .limit(1)
            .execution_options(autoflush=False)
        )
        if price is not None:
            return price, False
        other_price_id = await self.session.scalar(
            select(PriceSnapshotModel.id)
            .where(
                PriceSnapshotModel.listing_id == listing_id,
                PriceSnapshotModel.asset_id == asset_id,
                PriceSnapshotModel.price > 0,
                PriceSnapshotModel.provider_symbol.is_not(None),
                or_(
                    PriceSnapshotModel.source != source,
                    PriceSnapshotModel.provider_symbol != provider_symbol,
                    PriceSnapshotModel.currency != currency,
                ),
            )
            .limit(1)
            .execution_options(autoflush=False)
        )
        return None, other_price_id is not None

    async def symbol_events(
        self, *, user_id: str, symbol: str
    ) -> list[tuple[InvestmentEventModel, AccountModel, list[InvestmentMovementModel]]]:
        event_rows = list(
            (
                await self.session.execute(
                    select(InvestmentEventModel, AccountModel)
                    .join(AccountModel, AccountModel.id == InvestmentEventModel.account_id)
                    .join(
                        AccountMemberModel,
                        AccountMemberModel.account_id == InvestmentEventModel.account_id,
                    )
                    .where(
                        AccountMemberModel.user_id == user_id,
                        AccountModel.is_archived.is_(False),
                        InvestmentEventModel.archived_at.is_(None),
                        InvestmentEventModel.deleted_at.is_(None),
                        InvestmentEventModel.id.in_(
                            select(InvestmentMovementModel.event_id).where(
                                InvestmentMovementModel.source_symbol == symbol
                            )
                        ),
                    )
                    .order_by(InvestmentEventModel.date.desc(), InvestmentEventModel.id.desc())
                    .execution_options(autoflush=False)
                )
            ).all()
        )
        if not event_rows:
            return []
        event_ids = tuple(event.id for event, _ in event_rows)
        movements = list(
            (
                await self.session.scalars(
                    select(InvestmentMovementModel)
                    .where(InvestmentMovementModel.event_id.in_(event_ids))
                    .order_by(InvestmentMovementModel.event_id, InvestmentMovementModel.id)
                    .execution_options(autoflush=False)
                )
            ).all()
        )
        grouped: dict[str, list[InvestmentMovementModel]] = {event_id: [] for event_id in event_ids}
        for movement in movements:
            grouped[movement.event_id].append(movement)
        return [(event, account, grouped[event.id]) for event, account in event_rows]

    async def symbol_identity_context(
        self, asset_ids: tuple[str, ...]
    ) -> tuple[
        dict[str, tuple[AssetAliasModel, ...]],
        dict[str, tuple[AssetListingModel, ...]],
        dict[tuple[str, PriceSource], MarketDataListingHealthModel],
        dict[PriceSource, datetime],
    ]:
        if not asset_ids:
            return {}, {}, {}, {}
        aliases = list(
            (
                await self.session.scalars(
                    select(AssetAliasModel)
                    .where(AssetAliasModel.asset_id.in_(asset_ids))
                    .order_by(AssetAliasModel.asset_id, AssetAliasModel.id)
                    .execution_options(autoflush=False)
                )
            ).all()
        )
        listings = (
            await self.session.scalars(
                select(AssetListingModel)
                .where(AssetListingModel.asset_id.in_(asset_ids))
                .order_by(AssetListingModel.asset_id, AssetListingModel.id)
                .execution_options(autoflush=False)
            )
        ).all()
        health_rows = (
            await self.session.scalars(
                select(MarketDataListingHealthModel)
                .join(
                    AssetListingModel,
                    AssetListingModel.id == MarketDataListingHealthModel.listing_id,
                )
                .where(AssetListingModel.asset_id.in_(asset_ids))
                .execution_options(autoflush=False)
            )
        ).all()
        retry_rows = (
            await self.session.execute(
                select(
                    MarketDataListingHealthModel.provider,
                    func.max(MarketDataListingHealthModel.retry_after),
                )
                .where(
                    MarketDataListingHealthModel.last_failure_reason
                    == MarketDataFailureReason.rate_limit,
                    MarketDataListingHealthModel.retry_after.is_not(None),
                )
                .group_by(MarketDataListingHealthModel.provider)
                .execution_options(autoflush=False)
            )
        ).all()
        grouped: dict[str, list[AssetAliasModel]] = {asset_id: [] for asset_id in asset_ids}
        grouped_listings: dict[str, list[AssetListingModel]] = {
            asset_id: [] for asset_id in asset_ids
        }
        for alias in aliases:
            grouped[alias.asset_id].append(alias)
        for listing in listings:
            grouped_listings[listing.asset_id].append(listing)
        health = {(row.listing_id, row.provider): row for row in health_rows}
        return (
            {asset_id: tuple(items) for asset_id, items in grouped.items()},
            {asset_id: tuple(items) for asset_id, items in grouped_listings.items()},
            health,
            {
                provider: retry_after
                for provider, retry_after in retry_rows
                if retry_after is not None
            },
        )
