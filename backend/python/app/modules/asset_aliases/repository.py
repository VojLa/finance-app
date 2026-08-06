"""PostgreSQL reads, locks, and create-only persistence for AssetAlias."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256

from sqlalchemy import exists, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import AssetAliasProvider
from app.db.models.holdings import HoldingModel
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
                    ~exists(
                        select(AssetAliasModel.id).where(
                            AssetAliasModel.asset_id == AssetModel.id,
                            AssetAliasModel.provider == provider,
                        )
                    ),
                )
                .order_by(AssetModel.symbol, AssetModel.id)
            )
        )
        if not assets:
            return ()
        asset_ids = tuple(asset.id for asset in assets)
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
        for listing in listings:
            listings_by_asset[listing.asset_id].append(
                UnresolvedAssetListing(
                    listing_id=listing.id,
                    provider=listing.provider,
                    provider_symbol=listing.provider_symbol,
                    exchange=listing.exchange,
                    currency=listing.currency,
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
        )


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

    async def flush(self) -> None:
        await self.session.flush()

    async def reload_alias(self, alias_id: str) -> AssetAliasModel | None:
        return await self.session.scalar(
            select(AssetAliasModel)
            .where(AssetAliasModel.id == alias_id)
            .execution_options(populate_existing=True)
        )


__all__ = [
    "AssetAliasReadRepository",
    "AssetAliasWriterRepository",
    "advisory_lock_id",
    "asset_provider_lock_scope",
    "provider_external_lock_scope",
]
