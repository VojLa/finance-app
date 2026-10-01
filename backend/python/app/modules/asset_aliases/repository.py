"""PostgreSQL reads, locks, and create-only persistence for AssetAlias."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from hashlib import sha256

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.asset_alias_audit import AssetAliasAuditModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import AssetAliasProvider, MarketDataHealthState, PriceSource
from app.db.models.holdings import HoldingModel
from app.db.models.market_health import MarketDataListingHealthModel
from app.db.models.prices import PriceSnapshotModel
from app.modules.asset_aliases.identity import provider_asset_types
from app.modules.asset_aliases.models import (
    UnresolvedAssetAlias,
    UnresolvedAssetListing,
)


def advisory_lock_id(scope: str) -> int:
    return int.from_bytes(sha256(scope.encode()).digest()[:8], "big", signed=True)


def asset_provider_lock_scope(
    asset_id: str,
    provider: AssetAliasProvider,
) -> str:
    return "\0".join(("asset_alias:asset_provider", asset_id, provider.value))


def provider_external_lock_scope(
    provider: AssetAliasProvider,
    external_id: str,
) -> str:
    return "\0".join(("asset_alias:provider_external", provider.value, external_id))


class AssetAliasReadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_transaction_read_only(self) -> None:
        await self.session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )

    async def load_asset(self, asset_id: str) -> AssetModel | None:
        return await self.session.scalar(
            select(AssetModel)
            .where(AssetModel.id == asset_id)
            .execution_options(populate_existing=True)
        )

    async def load_listing(self, listing_id: str) -> AssetListingModel | None:
        return await self.session.scalar(
            select(AssetListingModel)
            .where(AssetListingModel.id == listing_id)
            .execution_options(populate_existing=True)
        )

    async def load_asset_provider_aliases(
        self,
        asset_id: str,
        provider: AssetAliasProvider,
    ) -> tuple[AssetAliasModel, ...]:
        return tuple(
            await self.session.scalars(
                select(AssetAliasModel)
                .where(
                    AssetAliasModel.asset_id == asset_id,
                    AssetAliasModel.provider == provider,
                )
                .order_by(AssetAliasModel.id)
                .execution_options(populate_existing=True)
            )
        )

    async def load_provider_external_alias(
        self,
        provider: AssetAliasProvider,
        external_id: str,
    ) -> AssetAliasModel | None:
        return await self.session.scalar(
            select(AssetAliasModel)
            .where(
                AssetAliasModel.provider == provider,
                AssetAliasModel.external_id == external_id,
            )
            .execution_options(populate_existing=True)
        )

    async def load_alias_by_id(self, alias_id: str) -> AssetAliasModel | None:
        return await self.session.scalar(
            select(AssetAliasModel)
            .where(AssetAliasModel.id == alias_id)
            .execution_options(populate_existing=True)
        )

    async def load_provider_listings(
        self, provider: PriceSource, provider_symbol: str
    ) -> tuple[AssetListingModel, ...]:
        return tuple(
            await self.session.scalars(
                select(AssetListingModel).where(
                    AssetListingModel.provider == provider,
                    AssetListingModel.provider_symbol == provider_symbol,
                )
            )
        )

    async def list_unresolved(
        self,
        provider: AssetAliasProvider,
    ) -> tuple[UnresolvedAssetAlias, ...]:
        compatible_types = provider_asset_types(provider)
        held_asset_ids = (
            select(AssetListingModel.asset_id)
            .join(HoldingModel, HoldingModel.listing_id == AssetListingModel.id)
            .where(HoldingModel.quantity != 0)
            .distinct()
        )
        assets = tuple(
            await self.session.scalars(
                select(AssetModel)
                .where(
                    AssetModel.id.in_(held_asset_ids),
                    AssetModel.asset_type.in_(compatible_types),
                )
                .order_by(AssetModel.symbol, AssetModel.id)
            )
        )
        if not assets:
            return ()
        asset_ids = tuple(asset.id for asset in assets)
        aliases = tuple(
            await self.session.scalars(
                select(AssetAliasModel).where(
                    AssetAliasModel.asset_id.in_(asset_ids),
                    AssetAliasModel.provider == provider,
                )
            )
        )
        aliases_by_asset: defaultdict[str, list[AssetAliasModel]] = defaultdict(list)
        for alias in aliases:
            aliases_by_asset[alias.asset_id].append(alias)
        listing_count_rows = (
            await self.session.execute(
                select(AssetListingModel.asset_id, func.count(AssetListingModel.id))
                .where(AssetListingModel.asset_id.in_(asset_ids))
                .group_by(AssetListingModel.asset_id)
            )
        ).all()
        listing_counts: dict[str, int] = dict(
            (asset_id, int(count)) for asset_id, count in listing_count_rows
        )
        listings_by_asset: defaultdict[str, list[UnresolvedAssetListing]] = defaultdict(list)
        listings = tuple(
            await self.session.scalars(
                select(AssetListingModel)
                .where(AssetListingModel.asset_id.in_(asset_ids))
                .order_by(
                    AssetListingModel.asset_id,
                    AssetListingModel.provider,
                    AssetListingModel.provider_symbol,
                    AssetListingModel.exchange,
                    AssetListingModel.currency,
                    AssetListingModel.id,
                )
            )
        )
        price_source = PriceSource(provider.value)
        listing_ids = tuple(listing.id for listing in listings)
        health_rows = tuple(
            await self.session.scalars(
                select(MarketDataListingHealthModel).where(
                    MarketDataListingHealthModel.listing_id.in_(listing_ids),
                    MarketDataListingHealthModel.provider == price_source,
                )
            )
        )
        health_by_listing = {row.listing_id: row for row in health_rows}
        valid_price_rows = (
            await self.session.execute(
                select(PriceSnapshotModel.listing_id, func.max(PriceSnapshotModel.timestamp))
                .join(AssetListingModel, AssetListingModel.id == PriceSnapshotModel.listing_id)
                .outerjoin(
                    AssetAliasModel,
                    and_(
                        AssetAliasModel.listing_id == AssetListingModel.id,
                        AssetAliasModel.provider == provider,
                    ),
                )
                .where(
                    PriceSnapshotModel.listing_id.in_(listing_ids),
                    PriceSnapshotModel.source == price_source,
                    PriceSnapshotModel.price > 0,
                    PriceSnapshotModel.currency == AssetListingModel.currency,
                    PriceSnapshotModel.provider_symbol.is_not(None),
                    func.length(func.btrim(PriceSnapshotModel.provider_symbol)) > 0,
                    or_(
                        and_(
                            AssetListingModel.provider == price_source,
                            AssetListingModel.provider_symbol == PriceSnapshotModel.provider_symbol,
                        ),
                        AssetAliasModel.external_id == PriceSnapshotModel.provider_symbol,
                    ),
                )
                .group_by(PriceSnapshotModel.listing_id)
            )
        ).all()
        price_by_listing: dict[str, datetime] = dict(
            (listing_id, timestamp) for listing_id, timestamp in valid_price_rows
        )
        for listing in listings:
            asset_aliases = aliases_by_asset[listing.asset_id]
            provider_symbol = listing.provider_symbol
            direct_provider_selected = listing.provider is price_source
            has_direct_identity = (
                direct_provider_selected
                and isinstance(provider_symbol, str)
                and bool(provider_symbol)
                and provider_symbol == provider_symbol.strip()
            )
            scoped_aliases = tuple(
                alias
                for alias in asset_aliases
                if alias.listing_id == listing.id
                and bool(alias.external_id)
                and alias.external_id == alias.external_id.strip()
            )
            legacy_aliases = tuple(
                alias
                for alias in asset_aliases
                if alias.listing_id is None
                and bool(alias.external_id)
                and alias.external_id == alias.external_id.strip()
            )
            has_alias_identity = not direct_provider_selected and (
                len(scoped_aliases) == 1
                or (
                    not scoped_aliases
                    and len(legacy_aliases) == 1
                    and (
                        provider is AssetAliasProvider.coingecko
                        or listing_counts[listing.asset_id] == 1
                    )
                )
            )
            if has_direct_identity or has_alias_identity:
                continue
            listings_by_asset[listing.asset_id].append(
                UnresolvedAssetListing(
                    listing_id=listing.id,
                    symbol=listing.symbol,
                    provider=listing.provider,
                    provider_symbol=listing.provider_symbol,
                    exchange=listing.exchange,
                    mic=listing.mic,
                    currency=listing.currency,
                    base_priority=listing.base_priority,
                    health_state=(
                        health_by_listing[listing.id].state.value
                        if listing.id in health_by_listing
                        else None
                    ),
                    last_valid_price_at=price_by_listing.get(listing.id),
                )
            )
        return tuple(
            UnresolvedAssetAlias(
                asset_id=asset.id,
                symbol=asset.symbol,
                asset_type=asset.asset_type,
                currency=asset.currency,
                isin=asset.isin,
                listings=tuple(listings_by_asset[asset.id]),
            )
            for asset in assets
            if listings_by_asset[asset.id]
        )

    async def health_summary(
        self, provider: AssetAliasProvider, *, as_of: datetime
    ) -> dict[str, object]:
        source = PriceSource(provider.value)
        rows = tuple(
            await self.session.scalars(
                select(MarketDataListingHealthModel).where(
                    MarketDataListingHealthModel.provider == source
                )
            )
        )
        price_range = (
            await self.session.execute(
                select(
                    func.min(PriceSnapshotModel.timestamp),
                    func.max(PriceSnapshotModel.timestamp),
                )
                .join(AssetListingModel, AssetListingModel.id == PriceSnapshotModel.listing_id)
                .outerjoin(
                    AssetAliasModel,
                    and_(
                        AssetAliasModel.listing_id == AssetListingModel.id,
                        AssetAliasModel.provider == provider,
                    ),
                )
                .where(
                    PriceSnapshotModel.source == source,
                    PriceSnapshotModel.price > 0,
                    PriceSnapshotModel.currency == AssetListingModel.currency,
                    PriceSnapshotModel.provider_symbol.is_not(None),
                    func.length(func.btrim(PriceSnapshotModel.provider_symbol)) > 0,
                    or_(
                        and_(
                            AssetListingModel.provider == source,
                            AssetListingModel.provider_symbol == PriceSnapshotModel.provider_symbol,
                        ),
                        AssetAliasModel.external_id == PriceSnapshotModel.provider_symbol,
                    ),
                    PriceSnapshotModel.timestamp <= as_of,
                )
            )
        ).one()
        unresolved = await self.list_unresolved(provider)
        states = {state.value: 0 for state in MarketDataHealthState}
        for row in rows:
            states[row.state.value] += 1
        return {
            "provider": provider.value,
            "asOf": as_of.isoformat(),
            "totalSuccesses": sum(row.total_successes for row in rows),
            "totalFailures": sum(row.total_failures for row in rows),
            "healthStateCounts": states,
            "retryCooldownCount": sum(
                row.retry_after is not None and row.retry_after > as_of for row in rows
            ),
            "activeLeaseCount": sum(
                row.lease_expires_at is not None and row.lease_expires_at > as_of for row in rows
            ),
            "unresolvedListingCount": sum(len(asset.listings) for asset in unresolved),
            "currencyConflictCount": sum(
                row.last_failure_reason is not None
                and row.last_failure_reason.value == "currency_conflict"
                for row in rows
            ),
            "identityConflictCount": sum(
                row.last_failure_reason is not None
                and row.last_failure_reason.value == "provider_identity_conflict"
                for row in rows
            ),
            "oldestValidPriceAgeSeconds": (
                int((as_of - price_range[0]).total_seconds())
                if price_range[0] is not None
                else None
            ),
            "latestValidPriceAgeSeconds": (
                int((as_of - price_range[1]).total_seconds())
                if price_range[1] is not None
                else None
            ),
        }


class AssetAliasWriterRepository:
    """Helpers assume one active writer-owned SERIALIZABLE attempt."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_transaction_serializable(self) -> None:
        await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))

    async def acquire_identity_locks(self, scopes: tuple[str, ...]) -> None:
        for scope in scopes:
            await self.session.execute(select(func.pg_advisory_xact_lock(advisory_lock_id(scope))))

    async def load_asset(self, asset_id: str) -> AssetModel | None:
        return await self.session.scalar(
            select(AssetModel)
            .where(AssetModel.id == asset_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_listing(self, listing_id: str) -> AssetListingModel | None:
        return await self.session.scalar(
            select(AssetListingModel)
            .where(AssetListingModel.id == listing_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_asset_provider_aliases(
        self,
        asset_id: str,
        provider: AssetAliasProvider,
    ) -> tuple[AssetAliasModel, ...]:
        return tuple(
            await self.session.scalars(
                select(AssetAliasModel)
                .where(
                    AssetAliasModel.asset_id == asset_id,
                    AssetAliasModel.provider == provider,
                )
                .order_by(AssetAliasModel.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    async def load_provider_external_alias(
        self,
        provider: AssetAliasProvider,
        external_id: str,
    ) -> AssetAliasModel | None:
        return await self.session.scalar(
            select(AssetAliasModel)
            .where(
                AssetAliasModel.provider == provider,
                AssetAliasModel.external_id == external_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_alias_by_id(self, alias_id: str) -> AssetAliasModel | None:
        return await self.session.scalar(
            select(AssetAliasModel)
            .where(AssetAliasModel.id == alias_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def add_alias(self, row: AssetAliasModel) -> None:
        self.session.add(row)

    def add_audit(self, row: AssetAliasAuditModel) -> None:
        self.session.add(row)

    async def flush(self) -> None:
        await self.session.flush()

    async def reload_alias(self, alias_id: str) -> AssetAliasModel | None:
        return await self.session.scalar(
            select(AssetAliasModel)
            .where(AssetAliasModel.id == alias_id)
            .execution_options(populate_existing=True)
        )

    async def load_provider_listings(
        self, provider: PriceSource, provider_symbol: str
    ) -> tuple[AssetListingModel, ...]:
        return tuple(
            await self.session.scalars(
                select(AssetListingModel)
                .where(
                    AssetListingModel.provider == provider,
                    AssetListingModel.provider_symbol == provider_symbol,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    def add_listing(self, row: AssetListingModel) -> None:
        self.session.add(row)


__all__ = [
    "AssetAliasReadRepository",
    "AssetAliasWriterRepository",
    "advisory_lock_id",
    "asset_provider_lock_scope",
    "provider_external_lock_scope",
]
