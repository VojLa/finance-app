"""Conservative caller-owned resolution of canonical assets and provider listings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Final
from uuid import uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.common import TIMESTAMP
from app.db.models.enums import AssetType, PriceSource
from app.modules.imports.investment_posting_plan import InvestmentAssetResolutionPlan
from app.modules.imports.posting_common import ImportPostStateError, bounded_optional_text

_PROVIDER_EXCHANGES: Final = {
    PriceSource.broker: "trading212",
    PriceSource.exchange: "anycoin",
}


@dataclass(frozen=True, slots=True)
class ResolvedInvestmentAsset:
    asset: AssetModel
    listing: AssetListingModel
    asset_created: bool
    listing_created: bool


def advisory_lock_id(scope: str) -> int:
    """Return the repository-standard signed PostgreSQL advisory lock identifier."""
    return int.from_bytes(sha256(scope.encode()).digest()[:8], "big", signed=True)


def _required_upper(value: object) -> str:
    canonical = bounded_optional_text(value)
    if canonical is None or not canonical or canonical != canonical.strip():
        raise ImportPostStateError()
    if canonical != canonical.upper():
        raise ImportPostStateError()
    return canonical


def _optional_upper(value: object) -> str | None:
    if value is None:
        return None
    return _required_upper(value)


def _current_updated_at(now: datetime | None = None) -> datetime:
    """Return a naive UTC timestamp exactly representable by canonical TIMESTAMP."""
    current = now or datetime.now(UTC)
    current = current.replace(tzinfo=None)
    precision = TIMESTAMP.precision
    if precision is None or not 0 <= precision <= 6:
        raise RuntimeError("Canonical TIMESTAMP precision must be between zero and six")
    unit = 10 ** (6 - precision)
    return current.replace(microsecond=current.microsecond - (current.microsecond % unit))


def _validated_plan(plan: object) -> InvestmentAssetResolutionPlan:
    if not isinstance(plan, InvestmentAssetResolutionPlan):
        raise ImportPostStateError()
    symbol = _required_upper(plan.symbol)
    provider_symbol = _required_upper(plan.provider_symbol)
    if provider_symbol != symbol:
        raise ImportPostStateError()
    exchange = bounded_optional_text(plan.exchange)
    if (
        exchange is None
        or not exchange
        or exchange != exchange.strip()
        or not isinstance(plan.asset_type, AssetType)
        or not isinstance(plan.provider, PriceSource)
        or _PROVIDER_EXCHANGES.get(plan.provider) != exchange
    ):
        raise ImportPostStateError()
    if plan.provider is PriceSource.exchange and plan.asset_type is not AssetType.crypto:
        raise ImportPostStateError()
    isin = _optional_upper(plan.isin)
    name = bounded_optional_text(plan.name)
    listing_currency_hint = _optional_upper(plan.listing_currency_hint)
    asset_currency_hint = _optional_upper(plan.asset_currency_hint)
    return InvestmentAssetResolutionPlan(
        symbol=symbol,
        isin=isin,
        name=name,
        asset_type=plan.asset_type,
        provider=plan.provider,
        provider_symbol=provider_symbol,
        exchange=exchange,
        listing_currency_hint=listing_currency_hint,
        asset_currency_hint=asset_currency_hint,
    )


def _lock_ids(plan: InvestmentAssetResolutionPlan) -> tuple[int, ...]:
    scopes = [f"assets:provider:{plan.provider.value}:{plan.provider_symbol}"]
    if plan.isin is not None:
        scopes.append(f"assets:isin:{plan.isin}")
    return tuple(sorted({advisory_lock_id(scope) for scope in scopes}))


def _asset_is_compatible(asset: AssetModel, plan: InvestmentAssetResolutionPlan) -> bool:
    if plan.isin is not None and asset.isin is not None and asset.isin != plan.isin:
        return False
    if plan.asset_type is not AssetType.other and asset.asset_type is not plan.asset_type:
        return False
    if plan.asset_currency_hint is not None and asset.currency != plan.asset_currency_hint:
        return False
    return not (plan.provider is PriceSource.exchange and asset.asset_type is not AssetType.crypto)


def _listing_is_compatible(
    listing: AssetListingModel,
    asset: AssetModel,
    plan: InvestmentAssetResolutionPlan,
) -> bool:
    if (
        listing.provider is not plan.provider
        or listing.provider_symbol != plan.provider_symbol
        or listing.symbol != plan.symbol
        or listing.exchange != plan.exchange
        or (
            plan.listing_currency_hint is not None
            and listing.currency != plan.listing_currency_hint
        )
    ):
        return False
    return _asset_is_compatible(asset, plan)


def validate_resolved_investment_asset(
    *,
    plan: InvestmentAssetResolutionPlan,
    asset: AssetModel,
    listing: AssetListingModel,
) -> None:
    """Validate an already persisted B2 identity without any lookup or mutation."""
    canonical_plan = _validated_plan(plan)
    if listing.asset_id != asset.id or not _listing_is_compatible(listing, asset, canonical_plan):
        raise ImportPostStateError()


class ImportInvestmentAssetResolver:
    """Resolve B1 asset evidence inside a transaction owned by the caller."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _acquire_locks(self, plan: InvestmentAssetResolutionPlan) -> None:
        for lock_id in _lock_ids(plan):
            await self.session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    async def _provider_candidates(
        self, plan: InvestmentAssetResolutionPlan
    ) -> list[tuple[AssetListingModel, AssetModel]]:
        conditions = [
            AssetListingModel.provider == plan.provider,
            AssetListingModel.provider_symbol == plan.provider_symbol,
        ]
        if plan.listing_currency_hint is not None:
            conditions.append(AssetListingModel.currency == plan.listing_currency_hint)
        result = await self.session.execute(
            select(AssetListingModel, AssetModel)
            .join(AssetModel, AssetModel.id == AssetListingModel.asset_id)
            .where(*conditions)
            .order_by(AssetListingModel.id, AssetModel.id)
            .with_for_update()
        )
        return [(listing, asset) for listing, asset in result.all()]

    async def _isin_candidates(self, isin: str) -> list[AssetModel]:
        result = await self.session.scalars(
            select(AssetModel)
            .where(AssetModel.isin == isin)
            .order_by(AssetModel.id)
            .with_for_update()
        )
        return list(result.all())

    async def _identity_candidates(
        self,
        *,
        plan: InvestmentAssetResolutionPlan,
    ) -> tuple[
        list[tuple[AssetListingModel, AssetModel]], list[tuple[AssetListingModel, AssetModel]]
    ]:
        assert plan.listing_currency_hint is not None
        provider_result = await self.session.execute(
            select(AssetListingModel, AssetModel)
            .join(AssetModel, AssetModel.id == AssetListingModel.asset_id)
            .where(
                AssetListingModel.provider == plan.provider,
                AssetListingModel.provider_symbol == plan.provider_symbol,
                AssetListingModel.currency == plan.listing_currency_hint,
            )
            .order_by(AssetListingModel.id, AssetModel.id)
            .with_for_update()
        )
        market_result = await self.session.execute(
            select(AssetListingModel, AssetModel)
            .join(AssetModel, AssetModel.id == AssetListingModel.asset_id)
            .where(
                and_(
                    AssetListingModel.symbol == plan.symbol,
                    AssetListingModel.exchange == plan.exchange,
                    AssetListingModel.currency == plan.listing_currency_hint,
                )
            )
            .order_by(AssetListingModel.id, AssetModel.id)
            .with_for_update()
        )
        return (
            [(listing, asset) for listing, asset in provider_result.all()],
            [(listing, asset) for listing, asset in market_result.all()],
        )

    async def _create_listing(
        self,
        *,
        plan: InvestmentAssetResolutionPlan,
        asset: AssetModel,
        asset_created: bool,
        updated_at: datetime | None = None,
    ) -> ResolvedInvestmentAsset:
        if plan.listing_currency_hint is None or plan.asset_currency_hint is None:
            raise ImportPostStateError()
        provider_candidates, market_candidates = await self._identity_candidates(plan=plan)
        if len(provider_candidates) > 1 or len(market_candidates) > 1:
            raise ImportPostStateError()
        provider_candidate = provider_candidates[0] if provider_candidates else None
        market_candidate = market_candidates[0] if market_candidates else None
        if provider_candidate is not None or market_candidate is not None:
            if provider_candidate is None or market_candidate is None:
                raise ImportPostStateError()
            provider_listing, provider_asset = provider_candidate
            market_listing, market_asset = market_candidate
            if (
                provider_listing.id != market_listing.id
                or provider_asset.id != market_asset.id
                or provider_asset.id != asset.id
                or not _listing_is_compatible(provider_listing, provider_asset, plan)
            ):
                raise ImportPostStateError()
            return ResolvedInvestmentAsset(
                asset=provider_asset,
                listing=provider_listing,
                asset_created=False,
                listing_created=False,
            )

        listing = AssetListingModel(
            id=str(uuid4()),
            asset_id=asset.id,
            symbol=plan.symbol,
            exchange=plan.exchange,
            mic=None,
            currency=plan.listing_currency_hint,
            country=None,
            provider=plan.provider,
            provider_symbol=plan.provider_symbol,
            is_primary=False,
            updated_at=updated_at or _current_updated_at(),
        )
        self.session.add(listing)
        await self.session.flush()
        return ResolvedInvestmentAsset(
            asset=asset,
            listing=listing,
            asset_created=asset_created,
            listing_created=True,
        )

    async def resolve(
        self,
        *,
        plan: InvestmentAssetResolutionPlan,
    ) -> ResolvedInvestmentAsset:
        canonical_plan = _validated_plan(plan)
        await self._acquire_locks(canonical_plan)

        provider_candidates = await self._provider_candidates(canonical_plan)
        if len(provider_candidates) > 1:
            raise ImportPostStateError()
        if provider_candidates:
            listing, asset = provider_candidates[0]
            if not _listing_is_compatible(listing, asset, canonical_plan):
                raise ImportPostStateError()
            return ResolvedInvestmentAsset(
                asset=asset,
                listing=listing,
                asset_created=False,
                listing_created=False,
            )

        if canonical_plan.isin is not None:
            isin_candidates = await self._isin_candidates(canonical_plan.isin)
            if len(isin_candidates) > 1:
                raise ImportPostStateError()
            if isin_candidates:
                asset = isin_candidates[0]
                if not _asset_is_compatible(asset, canonical_plan):
                    raise ImportPostStateError()
                return await self._create_listing(
                    plan=canonical_plan,
                    asset=asset,
                    asset_created=False,
                )

        if (
            canonical_plan.listing_currency_hint is None
            or canonical_plan.asset_currency_hint is None
        ):
            raise ImportPostStateError()
        provider_identities, market_identities = await self._identity_candidates(
            plan=canonical_plan
        )
        if provider_identities or market_identities:
            raise ImportPostStateError()
        now = _current_updated_at()
        asset = AssetModel(
            id=str(uuid4()),
            symbol=canonical_plan.symbol,
            isin=canonical_plan.isin,
            name=canonical_plan.name,
            asset_type=canonical_plan.asset_type,
            currency=canonical_plan.asset_currency_hint,
            updated_at=now,
        )
        self.session.add(asset)
        return await self._create_listing(
            plan=canonical_plan,
            asset=asset,
            asset_created=True,
            updated_at=now,
        )
