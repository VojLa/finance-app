"""Transactional persistence for exact listing/provider health.

Every writer method requires a transaction started by its caller. The acquisition
lease must be committed before the provider request begins. Failure outcomes use a
separate caller-owned transaction; success may be finalized inside the evidence
writer transaction so lease fencing and evidence publication are atomic.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assets import AssetAliasModel, AssetListingModel
from app.db.models.enums import AssetAliasProvider, MarketDataFailureReason, PriceSource
from app.db.models.market_health import MarketDataListingHealthModel


def health_id(listing_id: str, provider: PriceSource) -> str:
    """Stable primary key for one exact listing/provider identity."""
    payload = "\0".join(("market_data_health", listing_id, provider.value))
    return sha256(payload.encode("utf-8")).hexdigest()


def _advisory_key(scope: str) -> int:
    return int.from_bytes(sha256(scope.encode("utf-8")).digest()[:8], "big", signed=True)


class MarketDataHealthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def require_transaction(self) -> None:
        if not self.session.in_transaction():
            raise RuntimeError("health writes require a caller-owned transaction")

    async def lock_provider_and_listing(self, listing_id: str, provider: PriceSource) -> None:
        """Provider first, listing second, for every writer to avoid deadlocks."""
        self.require_transaction()
        for scope in (
            "\0".join(("market_data_health:provider", provider.value)),
            "\0".join(("market_data_health:listing", listing_id, provider.value)),
        ):
            await self.session.execute(select(func.pg_advisory_xact_lock(_advisory_key(scope))))

    async def validate_identity(
        self, listing_id: str, provider: PriceSource, provider_symbol: str | None
    ) -> bool:
        """Require a persisted, exact listing-scoped provider mapping.

        A conflicting direct listing identity and alias fails closed. A missing
        symbol is accepted only by the recording path for its permanent failure.
        """
        self.require_transaction()
        listing = await self.session.scalar(
            select(AssetListingModel)
            .where(AssetListingModel.id == listing_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if listing is None:
            return False
        direct = listing.provider == provider
        alias_provider = AssetAliasProvider._value2member_map_.get(provider.value)
        aliases: tuple[AssetAliasModel, ...] = ()
        if alias_provider is not None:
            aliases = tuple(
                await self.session.scalars(
                    select(AssetAliasModel)
                    .where(
                        AssetAliasModel.asset_id == listing.asset_id,
                        AssetAliasModel.provider == alias_provider,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
        if direct:
            return listing.provider_symbol == provider_symbol
        scoped = tuple(alias for alias in aliases if alias.listing_id == listing_id)
        legacy = tuple(alias for alias in aliases if alias.listing_id is None)
        if len(scoped) == 1:
            return scoped[0].external_id == provider_symbol
        if scoped or len(legacy) != 1:
            return False
        listing_count = await self.session.scalar(
            select(func.count(AssetListingModel.id)).where(
                AssetListingModel.asset_id == listing.asset_id
            )
        )
        return (provider is PriceSource.coingecko or listing_count == 1) and legacy[
            0
        ].external_id == provider_symbol

    async def locked_row(
        self, listing_id: str, provider: PriceSource
    ) -> MarketDataListingHealthModel | None:
        self.require_transaction()
        return await self.session.scalar(
            select(MarketDataListingHealthModel)
            .where(
                MarketDataListingHealthModel.listing_id == listing_id,
                MarketDataListingHealthModel.provider == provider,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def provider_retry_after(self, provider: PriceSource, now: datetime) -> datetime | None:
        """Maximum future provider-wide rate-limit deadline; caller holds provider lock."""
        self.require_transaction()
        return await self.session.scalar(
            select(func.max(MarketDataListingHealthModel.retry_after)).where(
                MarketDataListingHealthModel.provider == provider,
                MarketDataListingHealthModel.last_failure_reason
                == MarketDataFailureReason.rate_limit,
                MarketDataListingHealthModel.retry_after > now,
            )
        )

    def add(self, row: MarketDataListingHealthModel) -> None:
        self.require_transaction()
        self.session.add(row)

    async def flush(self) -> None:
        self.require_transaction()
        await self.session.flush()
