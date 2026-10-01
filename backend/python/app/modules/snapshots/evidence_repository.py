"""Explicit read-only SQL boundary for persisted account-snapshot evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.canonical_lineage import AccountCanonicalChangeModel
from app.db.models.enums import ExchangeRateSource, MarketDataFailureReason, PriceSource
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import (
    InvestmentEventModel,
    InvestmentMovementModel,
    InvestmentMovementValuationEvidenceModel,
)
from app.db.models.market_health import MarketDataListingHealthModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.transactions import TransactionModel
from app.modules.investments.transfer_valuation import validate_transfer_valuation_citations


@dataclass(frozen=True, slots=True)
class PersistedHoldingEvidence:
    holding: HoldingModel
    listing: AssetListingModel | None
    asset: AssetModel | None
    aliases: tuple[AssetAliasModel, ...] = ()
    asset_listing_count: int | None = None
    candidate_listings: tuple[AssetListingModel, ...] = ()
    candidate_aliases: tuple[AssetAliasModel, ...] = ()
    candidate_health: tuple[MarketDataListingHealthModel, ...] = ()
    provider_retry_after: tuple[tuple[PriceSource, datetime], ...] = ()


class AccountSnapshotEvidenceRepository:
    """Repository methods deliberately perform no writes or transaction control."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_account(self, account_id: str) -> AccountModel | None:
        return await self.session.get(AccountModel, account_id)

    async def load_holdings(
        self,
        account_id: str,
    ) -> tuple[PersistedHoldingEvidence, ...]:
        result = await self.session.execute(
            select(HoldingModel, AssetListingModel, AssetModel)
            .outerjoin(
                AssetListingModel,
                AssetListingModel.id == HoldingModel.listing_id,
            )
            .outerjoin(AssetModel, AssetModel.id == HoldingModel.asset_id)
            .where(HoldingModel.account_id == account_id)
            .order_by(HoldingModel.listing_id, HoldingModel.id)
        )
        rows = result.all()
        asset_ids = tuple(sorted({asset.id for _, _, asset in rows if asset is not None}))
        aliases_by_asset: dict[str, list[AssetAliasModel]] = {}
        listings_by_asset: dict[str, list[AssetListingModel]] = {}
        health_by_asset: dict[str, list[MarketDataListingHealthModel]] = {}
        provider_retry_after: tuple[tuple[PriceSource, datetime], ...] = ()
        if asset_ids:
            listings = await self.session.scalars(
                select(AssetListingModel)
                .where(AssetListingModel.asset_id.in_(asset_ids))
                .order_by(
                    AssetListingModel.asset_id,
                    AssetListingModel.base_priority.desc(),
                    AssetListingModel.id,
                )
            )
            for candidate in listings.all():
                listings_by_asset.setdefault(candidate.asset_id, []).append(candidate)
            aliases = await self.session.scalars(
                select(AssetAliasModel)
                .where(AssetAliasModel.asset_id.in_(asset_ids))
                .order_by(
                    AssetAliasModel.asset_id,
                    AssetAliasModel.listing_id,
                    AssetAliasModel.provider,
                    AssetAliasModel.external_id,
                    AssetAliasModel.id,
                )
            )
            for alias in aliases.all():
                aliases_by_asset.setdefault(alias.asset_id, []).append(alias)
            health_rows = await self.session.execute(
                select(MarketDataListingHealthModel, AssetListingModel.asset_id)
                .join(
                    AssetListingModel,
                    AssetListingModel.id == MarketDataListingHealthModel.listing_id,
                )
                .where(AssetListingModel.asset_id.in_(asset_ids))
                .order_by(
                    AssetListingModel.asset_id,
                    MarketDataListingHealthModel.listing_id,
                    MarketDataListingHealthModel.provider,
                )
            )
            for health, asset_id in health_rows.all():
                health_by_asset.setdefault(asset_id, []).append(health)
            retries = await self.session.execute(
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
            )
            provider_retry_after = tuple(
                (provider, retry_after)
                for provider, retry_after in retries.all()
                if retry_after is not None
            )
        return tuple(
            PersistedHoldingEvidence(
                holding,
                listing,
                asset,
                tuple(
                    alias
                    for alias in aliases_by_asset.get(holding.asset_id or "", ())
                    if alias.listing_id is None
                    or (listing is not None and alias.listing_id == listing.id)
                ),
                len(listings_by_asset.get(holding.asset_id or "", ())),
                tuple(listings_by_asset.get(holding.asset_id or "", ())),
                tuple(aliases_by_asset.get(holding.asset_id or "", ())),
                tuple(health_by_asset.get(holding.asset_id or "", ())),
                provider_retry_after,
            )
            for holding, listing, asset in rows
        )

    async def load_price_candidates(
        self,
        listing_ids: tuple[str, ...],
        *,
        through,
    ) -> tuple[PriceSnapshotModel, ...]:
        if not listing_ids:
            return ()
        result = await self.session.scalars(
            select(PriceSnapshotModel)
            .where(
                PriceSnapshotModel.listing_id.in_(listing_ids),
                PriceSnapshotModel.timestamp <= through,
            )
            .order_by(
                PriceSnapshotModel.listing_id,
                PriceSnapshotModel.timestamp.desc(),
                PriceSnapshotModel.id.desc(),
            )
        )
        return tuple(result.all())

    async def load_exchange_rate_candidates(
        self,
        base_currencies: tuple[str, ...],
        quote_currency: str,
        *,
        source: ExchangeRateSource,
        through,
    ) -> tuple[ExchangeRateModel, ...]:
        if not base_currencies:
            return ()
        result = await self.session.scalars(
            select(ExchangeRateModel)
            .where(
                ExchangeRateModel.from_currency.in_(base_currencies),
                ExchangeRateModel.to_currency == quote_currency,
                ExchangeRateModel.source == source,
                ExchangeRateModel.date <= through,
            )
            .order_by(
                ExchangeRateModel.from_currency,
                ExchangeRateModel.date.desc(),
                ExchangeRateModel.id.desc(),
            )
        )
        return tuple(result.all())

    async def load_active_transactions(
        self,
        account_id: str,
        *,
        through,
    ) -> tuple[TransactionModel, ...]:
        result = await self.session.scalars(
            select(TransactionModel)
            .where(
                TransactionModel.account_id == account_id,
                TransactionModel.date <= through,
                TransactionModel.archived_at.is_(None),
                TransactionModel.deleted_at.is_(None),
            )
            .order_by(TransactionModel.date, TransactionModel.id)
        )
        return tuple(result.all())

    async def load_active_events(
        self,
        account_id: str,
        *,
        through,
    ) -> tuple[InvestmentEventModel, ...]:
        result = await self.session.scalars(
            select(InvestmentEventModel)
            .where(
                InvestmentEventModel.account_id == account_id,
                InvestmentEventModel.date <= through,
                InvestmentEventModel.archived_at.is_(None),
                InvestmentEventModel.deleted_at.is_(None),
            )
            .order_by(InvestmentEventModel.date, InvestmentEventModel.id)
        )
        return tuple(result.all())

    async def load_active_movements(
        self,
        account_id: str,
        *,
        through,
    ) -> tuple[InvestmentMovementModel, ...]:
        result = await self.session.scalars(
            select(InvestmentMovementModel)
            .join(
                InvestmentEventModel,
                InvestmentEventModel.id == InvestmentMovementModel.event_id,
            )
            .where(
                InvestmentEventModel.date <= through,
                InvestmentEventModel.archived_at.is_(None),
                InvestmentEventModel.deleted_at.is_(None),
                or_(
                    InvestmentEventModel.account_id == account_id,
                    InvestmentMovementModel.account_id == account_id,
                ),
            )
            .order_by(
                InvestmentMovementModel.event_id,
                InvestmentMovementModel.id,
            )
        )
        return tuple(result.all())

    async def load_transfer_valuations(
        self,
        movement_ids: tuple[str, ...],
    ) -> tuple[InvestmentMovementValuationEvidenceModel, ...]:
        if not movement_ids:
            return ()
        result = await self.session.execute(
            select(
                InvestmentMovementValuationEvidenceModel,
                PriceSnapshotModel,
                ExchangeRateModel,
                InvestmentMovementModel,
            )
            .join(
                PriceSnapshotModel,
                PriceSnapshotModel.id == InvestmentMovementValuationEvidenceModel.price_snapshot_id,
            )
            .outerjoin(
                ExchangeRateModel,
                ExchangeRateModel.id == InvestmentMovementValuationEvidenceModel.exchange_rate_id,
            )
            .join(
                InvestmentMovementModel,
                InvestmentMovementModel.id == InvestmentMovementValuationEvidenceModel.movement_id,
            )
            .where(InvestmentMovementValuationEvidenceModel.movement_id.in_(movement_ids))
            .order_by(
                InvestmentMovementValuationEvidenceModel.movement_id,
                InvestmentMovementValuationEvidenceModel.revision,
            )
        )
        rows: list[InvestmentMovementValuationEvidenceModel] = []
        for evidence, price, rate, movement in result.all():
            validate_transfer_valuation_citations(
                evidence=evidence,
                movement=movement,
                price=price,
                exchange_rate=rate,
            )
            rows.append(evidence)
        return tuple(rows)

    async def load_investment_event_revisions(
        self, account_id: str, event_ids: tuple[str, ...]
    ) -> dict[str, int]:
        if not event_ids:
            return {}
        rows = (
            await self.session.scalars(
                select(AccountCanonicalChangeModel).where(
                    AccountCanonicalChangeModel.account_id == account_id,
                    AccountCanonicalChangeModel.kind == "investment_event",
                    AccountCanonicalChangeModel.entity_id.in_(event_ids),
                )
            )
        ).all()
        return {row.entity_id: row.revision for row in rows}
