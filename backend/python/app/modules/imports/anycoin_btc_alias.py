"""Bounded source-policy-owned alias onboarding for canonical Anycoin BTC."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    AssetAliasProvider,
    AssetType,
    ImportSource,
    InvestmentMovementKind,
    PriceSource,
)
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.modules.asset_aliases.models import (
    AssetAliasConflictError,
    OnboardAssetAliasCommand,
    OnboardAssetAliasResult,
)
from app.modules.asset_aliases.service import AssetAliasWriter
from app.modules.market_data.source_policy import (
    MarketEvidenceSourcePolicy,
    validate_market_evidence_source_policy,
)

_SYMBOL = "BTC"


def _provider_identity(
    source_policy: MarketEvidenceSourcePolicy,
) -> tuple[AssetAliasProvider, str]:
    price_source = source_policy.price_source_for(AssetType.crypto)
    if price_source is PriceSource.coingecko:
        return AssetAliasProvider.coingecko, "bitcoin"
    if price_source is PriceSource.yahoo_finance:
        return AssetAliasProvider.yahoo_finance, "BTC-USD"
    raise AssetAliasConflictError()


@dataclass(frozen=True, slots=True)
class OnboardAnycoinBtcAliasCommand:
    account_id: str
    batch_ids: tuple[str, ...]
    source: ImportSource
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OnboardAnycoinBtcAliasResult:
    aliases: tuple[OnboardAssetAliasResult, ...]


@dataclass(frozen=True, slots=True)
class _PostedAssetMovement:
    movement_id: str
    source_symbol: str | None
    source_asset_type: AssetType | None
    asset_id: str | None
    listing_id: str | None
    asset_symbol: str | None
    asset_type: AssetType | None
    asset_currency: str | None
    asset_isin: str | None
    listing_asset_id: str | None
    listing_symbol: str | None
    listing_provider: PriceSource | None
    listing_provider_symbol: str | None
    listing_exchange: str | None
    listing_currency: str | None


class _Repository(Protocol):
    async def set_transaction_read_only(self) -> None: ...

    async def list_posted_asset_movements(
        self,
        *,
        account_id: str,
        batch_ids: tuple[str, ...],
        source: ImportSource,
    ) -> tuple[_PostedAssetMovement, ...]: ...


class _Writer(Protocol):
    async def write(
        self,
        command: OnboardAssetAliasCommand,
    ) -> OnboardAssetAliasResult: ...


class AnycoinBtcAliasRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_transaction_read_only(self) -> None:
        await self.session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )

    async def list_posted_asset_movements(
        self,
        *,
        account_id: str,
        batch_ids: tuple[str, ...],
        source: ImportSource,
    ) -> tuple[_PostedAssetMovement, ...]:
        result = await self.session.execute(
            select(
                InvestmentMovementModel,
                AssetModel,
                AssetListingModel,
            )
            .join(
                InvestmentEventModel,
                InvestmentEventModel.id == InvestmentMovementModel.event_id,
            )
            .outerjoin(AssetModel, AssetModel.id == InvestmentMovementModel.asset_id)
            .outerjoin(
                AssetListingModel,
                AssetListingModel.id == InvestmentMovementModel.listing_id,
            )
            .where(
                InvestmentEventModel.account_id == account_id,
                InvestmentEventModel.import_batch_id.in_(batch_ids),
                InvestmentEventModel.source == source,
                InvestmentEventModel.archived_at.is_(None),
                InvestmentEventModel.deleted_at.is_(None),
                InvestmentMovementModel.account_id == account_id,
                InvestmentMovementModel.kind == InvestmentMovementKind.asset,
            )
            .order_by(
                InvestmentMovementModel.event_id,
                InvestmentMovementModel.id,
            )
        )
        return tuple(
            _PostedAssetMovement(
                movement_id=movement.id,
                source_symbol=movement.source_symbol,
                source_asset_type=movement.source_asset_type,
                asset_id=movement.asset_id,
                listing_id=movement.listing_id,
                asset_symbol=None if asset is None else asset.symbol,
                asset_type=None if asset is None else asset.asset_type,
                asset_currency=None if asset is None else asset.currency,
                asset_isin=None if asset is None else asset.isin,
                listing_asset_id=None if listing is None else listing.asset_id,
                listing_symbol=None if listing is None else listing.symbol,
                listing_provider=None if listing is None else listing.provider,
                listing_provider_symbol=(None if listing is None else listing.provider_symbol),
                listing_exchange=None if listing is None else listing.exchange,
                listing_currency=None if listing is None else listing.currency,
            )
            for movement, asset, listing in result.all()
        )


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise AssetAliasConflictError()
    return value


def _timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or precision is None
        or not 0 <= precision <= 6
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise AssetAliasConflictError()
    return value


def _validate_command(value: object) -> OnboardAnycoinBtcAliasCommand:
    if (
        not isinstance(value, OnboardAnycoinBtcAliasCommand)
        or not isinstance(value.source, ImportSource)
        or not isinstance(value.batch_ids, tuple)
        or not value.batch_ids
        or value.batch_ids != tuple(sorted(value.batch_ids))
        or len(set(value.batch_ids)) != len(value.batch_ids)
    ):
        raise AssetAliasConflictError()
    _nonblank(value.account_id)
    for batch_id in value.batch_ids:
        _nonblank(batch_id)
    _timestamp(value.created_at)
    return value


def _currency(value: object) -> str:
    currency = _nonblank(value)
    if (
        len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
        or currency != currency.upper()
    ):
        raise AssetAliasConflictError()
    return currency


def _alias_command(
    movement: _PostedAssetMovement,
    *,
    created_at: datetime,
    source_policy: MarketEvidenceSourcePolicy,
) -> OnboardAssetAliasCommand | None:
    if movement.source_symbol != _SYMBOL:
        return None
    if (
        movement.source_asset_type is not AssetType.crypto
        or movement.asset_id is None
        or movement.listing_id is None
        or movement.asset_symbol != _SYMBOL
        or movement.asset_type is not AssetType.crypto
        or movement.asset_currency != _SYMBOL
        or movement.asset_isin is not None
        or movement.listing_asset_id != movement.asset_id
        or movement.listing_symbol != _SYMBOL
        or movement.listing_provider is not PriceSource.exchange
        or movement.listing_provider_symbol != _SYMBOL
        or movement.listing_exchange != ImportSource.anycoin.value
    ):
        raise AssetAliasConflictError()
    _nonblank(movement.movement_id)
    _nonblank(movement.asset_id)
    _nonblank(movement.listing_id)
    _currency(movement.listing_currency)
    provider, external_id = _provider_identity(source_policy)
    return OnboardAssetAliasCommand(
        actor="system:anycoin-import",
        asset_id=movement.asset_id,
        listing_id=(movement.listing_id if provider is AssetAliasProvider.yahoo_finance else None),
        provider=provider,
        external_id=external_id,
        expected_symbol=_SYMBOL,
        expected_asset_type=AssetType.crypto,
        expected_currency=_SYMBOL,
        expected_isin=None,
        created_at=created_at,
    )


class AnycoinBtcAliasService:
    """Onboard the one accepted source/provider identity before market acquisition."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        source_policy: MarketEvidenceSourcePolicy,
        repository: _Repository | None = None,
        writer: _Writer | None = None,
    ) -> None:
        self.session = session
        self.source_policy = validate_market_evidence_source_policy(source_policy)
        self.repository = repository or AnycoinBtcAliasRepository(session)
        self.writer = writer or AssetAliasWriter(session)

    async def onboard(
        self,
        command: OnboardAnycoinBtcAliasCommand,
    ) -> OnboardAnycoinBtcAliasResult:
        canonical = _validate_command(command)
        if self.session.in_transaction():
            raise AssetAliasConflictError()
        if canonical.source is not ImportSource.anycoin:
            return OnboardAnycoinBtcAliasResult(aliases=())

        async with self.session.begin():
            await self.repository.set_transaction_read_only()
            movements = await self.repository.list_posted_asset_movements(
                account_id=canonical.account_id,
                batch_ids=canonical.batch_ids,
                source=canonical.source,
            )
        if self.session.in_transaction():
            await self.session.rollback()
            raise AssetAliasConflictError()

        commands_by_asset: dict[str, OnboardAssetAliasCommand] = {}
        for movement in movements:
            alias = _alias_command(
                movement,
                created_at=canonical.created_at,
                source_policy=self.source_policy,
            )
            if alias is None:
                continue
            existing = commands_by_asset.get(alias.asset_id)
            if existing is not None and existing != alias:
                raise AssetAliasConflictError()
            commands_by_asset[alias.asset_id] = alias
        if len(commands_by_asset) > 1:
            raise AssetAliasConflictError()

        results: list[OnboardAssetAliasResult] = []
        for asset_id in sorted(commands_by_asset):
            results.append(await self.writer.write(commands_by_asset[asset_id]))
            if self.session.in_transaction():
                await self.session.rollback()
                raise AssetAliasConflictError()
        return OnboardAnycoinBtcAliasResult(aliases=tuple(results))


__all__ = [
    "AnycoinBtcAliasRepository",
    "AnycoinBtcAliasService",
    "OnboardAnycoinBtcAliasCommand",
    "OnboardAnycoinBtcAliasResult",
]
