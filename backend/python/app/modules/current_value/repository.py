"""Read-only PostgreSQL boundary for strict current-value projection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select, text, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.background_jobs import BackgroundJobModel, ImportJobAffectedAccountModel
from app.db.models.enums import (
    BackgroundJobKind,
    BackgroundJobStatus,
    ExchangeRateSource,
    MarketDataFailureReason,
    PriceSource,
)
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.market_health import MarketDataListingHealthModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.db.models.transactions import TransactionModel
from app.modules.current_value.delta_projection import CurrentInvestmentEvent
from app.modules.holdings.persistence_projection import (
    HoldingPersistenceEvent,
    HoldingPersistenceMovement,
)
from app.modules.portfolio_snapshot.models import (
    PortfolioSnapshotView,
    SnapshotGranularity,
)
from app.modules.portfolio_snapshot.reader import (
    PortfolioSnapshotReader,
    ReadExactPortfolioSnapshotCommand,
)
from app.modules.snapshots.evidence_repository import AccountSnapshotEvidenceRepository


@dataclass(frozen=True, slots=True)
class CurrentListingSelectionContext:
    requested_listing: AssetListingModel
    asset: AssetModel
    candidate_listings: tuple[AssetListingModel, ...]
    aliases: tuple[AssetAliasModel, ...]
    health: tuple[MarketDataListingHealthModel, ...]
    provider_retry_after: tuple[tuple[PriceSource, datetime], ...]


class CurrentValueRepository:
    """Load exact roots and market evidence without owning transactions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.snapshot_reader = PortfolioSnapshotReader(session)
        self.snapshot_evidence = AccountSnapshotEvidenceRepository(session)

    async def set_repeatable_read_only(self) -> None:
        await self.session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )

    async def load_active_import_account_ids(
        self,
        *,
        reader_user_id: str,
        account_ids: tuple[str, ...] | None = None,
    ) -> tuple[str, ...]:
        """Return visible accounts whose import result is not yet published."""

        if account_ids == ():
            return ()
        active_statuses = (
            BackgroundJobStatus.queued,
            BackgroundJobStatus.running,
            BackgroundJobStatus.retry_wait,
            BackgroundJobStatus.failed,
        )
        active_accounts = union_all(
            # The initiator branch is also the explicit legacy fallback for
            # jobs created before ImportJobAffectedAccount existed.
            select(BackgroundJobModel.account_id.label("account_id")).where(
                BackgroundJobModel.kind == BackgroundJobKind.import_workflow,
                BackgroundJobModel.status.in_(active_statuses),
            ),
            select(ImportJobAffectedAccountModel.account_id.label("account_id"))
            .join(
                BackgroundJobModel,
                BackgroundJobModel.id == ImportJobAffectedAccountModel.job_id,
            )
            .where(
                BackgroundJobModel.kind == BackgroundJobKind.import_workflow,
                BackgroundJobModel.status.in_(active_statuses),
            ),
        ).subquery()
        statement = (
            select(active_accounts.c.account_id)
            .join(
                AccountMemberModel,
                AccountMemberModel.account_id == active_accounts.c.account_id,
            )
            .where(
                AccountMemberModel.user_id == reader_user_id,
            )
            .distinct()
            .order_by(active_accounts.c.account_id)
            .execution_options(populate_existing=True, autoflush=False)
        )
        if account_ids is not None:
            statement = statement.where(active_accounts.c.account_id.in_(account_ids))
        rows = await self.session.scalars(statement)
        return tuple(rows.all())

    async def load_baseline_view(
        self,
        *,
        account_id: str,
        snapshot_id: str,
        timestamp: datetime,
        granularity: SnapshotGranularity,
        currency: str,
        calculation_version: int,
    ) -> PortfolioSnapshotView:
        result = await self.snapshot_reader.read(
            ReadExactPortfolioSnapshotCommand(
                account_id=account_id,
                timestamp=timestamp,
                granularity=granularity,
                currency=currency,
                calculation_version=calculation_version,
                required_snapshot_id=snapshot_id,
            )
        )
        return result.view

    async def load_snapshot(self, snapshot_id: str) -> AccountSnapshotModel | None:
        return await self.session.get(
            AccountSnapshotModel,
            snapshot_id,
            populate_existing=True,
        )

    async def load_snapshot_items_with_assets(
        self,
        snapshot_ids: tuple[str, ...],
    ) -> tuple[tuple[AccountSnapshotItemModel, AssetModel], ...]:
        """Return the persisted price provenance for exact baseline snapshots."""

        if not snapshot_ids:
            return ()
        rows = await self.session.execute(
            select(AccountSnapshotItemModel, AssetModel)
            .join(AssetModel, AssetModel.id == AccountSnapshotItemModel.asset_id)
            .where(AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids))
            .order_by(AccountSnapshotItemModel.snapshot_id, AccountSnapshotItemModel.id)
            .execution_options(populate_existing=True, autoflush=False)
        )
        return tuple((item, asset) for item, asset in rows.all())

    async def load_exchange_rates_by_ids(
        self,
        rate_ids: tuple[str, ...],
    ) -> tuple[ExchangeRateModel, ...]:
        """Return exact persisted FX rows named by immutable snapshot audit JSON."""

        if not rate_ids:
            return ()
        rows = await self.session.scalars(
            select(ExchangeRateModel)
            .where(ExchangeRateModel.id.in_(rate_ids))
            .order_by(ExchangeRateModel.id)
            .execution_options(populate_existing=True, autoflush=False)
        )
        return tuple(rows.all())

    async def load_transaction(self, transaction_id: str) -> TransactionModel | None:
        return await self.session.get(
            TransactionModel,
            transaction_id,
            populate_existing=True,
        )

    async def load_investment_event(
        self,
        *,
        event_id: str,
        account_id: str,
    ) -> CurrentInvestmentEvent | None:
        event = await self.session.get(
            InvestmentEventModel,
            event_id,
            populate_existing=True,
        )
        if (
            event is None
            or event.account_id != account_id
            or event.archived_at is not None
            or event.deleted_at is not None
        ):
            return None
        rows = (
            await self.session.execute(
                select(InvestmentMovementModel, AssetListingModel, AssetModel)
                .outerjoin(
                    AssetListingModel,
                    AssetListingModel.id == InvestmentMovementModel.listing_id,
                )
                .outerjoin(AssetModel, AssetModel.id == InvestmentMovementModel.asset_id)
                .where(InvestmentMovementModel.event_id == event_id)
                .order_by(InvestmentMovementModel.id)
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).all()
        movements: list[HoldingPersistenceMovement] = []
        for movement, listing, asset in rows:
            if movement.account_id != account_id:
                return None
            listing_asset_id = listing.asset_id if listing is not None else None
            if asset is not None and listing is not None and listing.asset_id != asset.id:
                return None
            movements.append(
                HoldingPersistenceMovement(
                    movement_id=movement.id,
                    event_id=movement.event_id,
                    account_id=movement.account_id,
                    kind=movement.kind,
                    direction=movement.direction,
                    quantity=movement.quantity,
                    currency=movement.currency,
                    asset_id=movement.asset_id,
                    listing_id=movement.listing_id,
                    listing_asset_id=listing_asset_id,
                    source_symbol=movement.source_symbol,
                    source_asset_type=movement.source_asset_type,
                    price_per_unit=movement.price_per_unit,
                    value_amount=movement.value_amount,
                    value_currency=movement.value_currency,
                    listing_currency=listing.currency if listing is not None else None,
                )
            )
        return CurrentInvestmentEvent(
            event=HoldingPersistenceEvent(
                event_id=event.id,
                account_id=event.account_id,
                event_type=event.type,
                event_date=event.date,
                external_id=event.external_id,
                movements=tuple(movements),
            ),
            realized_pnl=event.realized_pnl,
            realized_pnl_currency=event.realized_pnl_currency,
        )

    async def load_liability(self, liability_id: str) -> LiabilityBalanceModel | None:
        return await self.session.get(
            LiabilityBalanceModel,
            liability_id,
            populate_existing=True,
        )

    async def load_listing_metadata(
        self,
        listing_ids: tuple[str, ...],
    ) -> tuple[tuple[AssetListingModel, AssetModel], ...]:
        if not listing_ids:
            return ()
        rows = await self.session.execute(
            select(AssetListingModel, AssetModel)
            .join(AssetModel, AssetModel.id == AssetListingModel.asset_id)
            .where(AssetListingModel.id.in_(listing_ids))
            .order_by(AssetListingModel.id)
            .execution_options(populate_existing=True, autoflush=False)
        )
        return tuple((listing, asset) for listing, asset in rows.all())

    async def load_listing_identities(
        self,
        listing_ids: tuple[str, ...],
    ) -> tuple[tuple[AssetListingModel, AssetModel, tuple[AssetAliasModel, ...], int], ...]:
        metadata = await self.load_listing_metadata(listing_ids)
        if not metadata:
            return ()
        asset_ids = tuple(sorted({asset.id for _, asset in metadata}))
        count_rows = await self.session.execute(
            select(AssetListingModel.asset_id, func.count(AssetListingModel.id))
            .where(AssetListingModel.asset_id.in_(asset_ids))
            .group_by(AssetListingModel.asset_id)
            .execution_options(populate_existing=True, autoflush=False)
        )
        listing_counts = {asset_id: int(count) for asset_id, count in count_rows.all()}
        alias_rows = await self.session.scalars(
            select(AssetAliasModel)
            .where(AssetAliasModel.asset_id.in_(asset_ids))
            .order_by(
                AssetAliasModel.asset_id,
                AssetAliasModel.provider,
                AssetAliasModel.external_id,
                AssetAliasModel.id,
            )
            .execution_options(populate_existing=True, autoflush=False)
        )
        by_asset: dict[str, list[AssetAliasModel]] = {asset_id: [] for asset_id in asset_ids}
        for alias in alias_rows.all():
            by_asset[alias.asset_id].append(alias)
        return tuple(
            (
                listing,
                asset,
                tuple(
                    alias
                    for alias in by_asset[asset.id]
                    if alias.listing_id is None or alias.listing_id == listing.id
                ),
                listing_counts[asset.id],
            )
            for listing, asset in metadata
        )

    async def load_listing_selection_contexts(
        self,
        listing_ids: tuple[str, ...],
    ) -> tuple[CurrentListingSelectionContext, ...]:
        metadata = await self.load_listing_metadata(listing_ids)
        if not metadata:
            return ()
        asset_ids = tuple(sorted({asset.id for _, asset in metadata}))
        listings = (
            await self.session.scalars(
                select(AssetListingModel)
                .where(AssetListingModel.asset_id.in_(asset_ids))
                .order_by(AssetListingModel.asset_id, AssetListingModel.id)
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).all()
        aliases = (
            await self.session.scalars(
                select(AssetAliasModel)
                .where(AssetAliasModel.asset_id.in_(asset_ids))
                .order_by(AssetAliasModel.asset_id, AssetAliasModel.id)
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).all()
        health = (
            await self.session.scalars(
                select(MarketDataListingHealthModel)
                .join(
                    AssetListingModel,
                    AssetListingModel.id == MarketDataListingHealthModel.listing_id,
                )
                .where(AssetListingModel.asset_id.in_(asset_ids))
                .order_by(
                    MarketDataListingHealthModel.listing_id, MarketDataListingHealthModel.provider
                )
                .execution_options(populate_existing=True, autoflush=False)
            )
        ).all()
        retry_rows = await self.session.execute(
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
            .order_by(MarketDataListingHealthModel.provider)
            .execution_options(populate_existing=True, autoflush=False)
        )
        retry_by_provider = tuple(
            (provider, retry_after)
            for provider, retry_after in retry_rows.all()
            if retry_after is not None
        )
        return tuple(
            CurrentListingSelectionContext(
                requested_listing=listing,
                asset=asset,
                candidate_listings=tuple(item for item in listings if item.asset_id == asset.id),
                aliases=tuple(item for item in aliases if item.asset_id == asset.id),
                health=tuple(
                    item
                    for item in health
                    if any(
                        candidate.id == item.listing_id
                        for candidate in listings
                        if candidate.asset_id == asset.id
                    )
                ),
                provider_retry_after=retry_by_provider,
            )
            for listing, asset in metadata
        )

    async def load_price_candidates(
        self,
        listing_ids: tuple[str, ...],
        *,
        through: datetime,
    ) -> tuple[PriceSnapshotModel, ...]:
        return await self.snapshot_evidence.load_price_candidates(
            listing_ids,
            through=through,
        )

    async def load_exchange_rate_candidates(
        self,
        base_currencies: tuple[str, ...],
        quote_currency: str,
        *,
        source: ExchangeRateSource,
        through: datetime,
    ) -> tuple[ExchangeRateModel, ...]:
        return await self.snapshot_evidence.load_exchange_rate_candidates(
            base_currencies,
            quote_currency,
            source=source,
            through=through,
        )
