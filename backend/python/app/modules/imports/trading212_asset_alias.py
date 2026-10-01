"""Closed Trading 212 fixture identity map for automatic market aliases."""

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
from app.modules.asset_aliases.identity import canonical_external_id
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
from app.modules.market_data.yahoo_exchange_mapping import suggest_yahoo_symbol


@dataclass(frozen=True, slots=True)
class _Identity:
    isin: str
    symbol: str
    currency: str
    yahoo_symbol: str
    twelve_data_mic: str


def _identity(
    isin: str,
    symbol: str,
    currency: str,
    yahoo_symbol: str,
    twelve_data_mic: str,
) -> _Identity:
    return _Identity(isin, symbol, currency, yahoo_symbol, twelve_data_mic)


_IDENTITIES = {
    (item.isin, item.symbol, item.currency): item
    for item in (
        _identity("US0378331005", "AAPL", "USD", "AAPL", "XNAS"),
        _identity("US0231351067", "AMZN", "USD", "AMZN", "XNAS"),
        _identity("IE00BMD8KM66", "BB3M", "USD", "BB3M.L", "XLON"),
        _identity("US0886061086", "BHP", "USD", "BHP", "XNYS"),
        _identity("CA13321L1085", "CCJ", "USD", "CCJ", "XNYS"),
        _identity("IE00B4K48X80", "EUNK", "EUR", "EUNK.DE", "XETR"),
        _identity("US02079K1079", "GOOG", "USD", "GOOG", "XNAS"),
        _identity("US46222L1089", "IONQ", "USD", "IONQ", "XNYS"),
        _identity("US02209S1033", "MO", "USD", "MO", "XNYS"),
        _identity("US5949181045", "MSFT", "USD", "MSFT", "XNAS"),
        _identity("US62914V1061", "NIO", "USD", "NIO", "XNYS"),
        _identity("US67066G1040", "NVDA", "USD", "NVDA", "XNAS"),
        _identity("US7561091049", "O", "USD", "O", "XNYS"),
        _identity("DE000PAG9113", "P911", "EUR", "P911.DE", "XETR"),
        _identity("US26740W1099", "QBTS", "USD", "QBTS", "XNYS"),
        _identity("US76655K1034", "RGTI", "USD", "RGTI", "XNAS"),
        _identity("US8552441094", "SBUX", "USD", "SBUX", "XNAS"),
        _identity("CA82509L1076", "SHOP", "USD", "SHOP", "XNAS"),
        _identity("US88160R1014", "TSLA", "USD", "TSLA", "XNAS"),
        _identity("US8740391003", "TSM", "USD", "TSM", "XNYS"),
        _identity("IE00BFMXXD54", "VUAA", "EUR", "VUAA.MI", "XMIL"),
        _identity("IE00B3XXRP09", "VUSA", "GBP", "VUSA.L", "XLON"),
        _identity("IE00BK5BQT80", "VWCE", "EUR", "VWCE.DE", "XETR"),
        _identity("IE00BSPLC413", "ZPRV", "EUR", "ZPRV.DE", "XETR"),
    )
}


@dataclass(frozen=True, slots=True)
class OnboardTrading212AssetAliasesCommand:
    account_id: str
    batch_ids: tuple[str, ...]
    source: ImportSource
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OnboardTrading212AssetAliasesResult:
    aliases: tuple[OnboardAssetAliasResult, ...]


@dataclass(frozen=True, slots=True)
class _PostedAsset:
    movement_id: str
    source_symbol: str | None
    source_asset_type: AssetType | None
    asset_id: str | None
    asset_symbol: str | None
    asset_type: AssetType | None
    asset_currency: str | None
    asset_isin: str | None
    listing_id: str | None
    listing_asset_id: str | None
    listing_symbol: str | None
    listing_provider: PriceSource | None
    listing_provider_symbol: str | None
    listing_exchange: str | None
    listing_currency: str | None


class _Repository(Protocol):
    async def set_transaction_read_only(self) -> None: ...

    async def list_posted_assets(
        self,
        *,
        account_id: str,
        batch_ids: tuple[str, ...],
        source: ImportSource,
    ) -> tuple[_PostedAsset, ...]: ...


class _Writer(Protocol):
    async def write(self, command: OnboardAssetAliasCommand) -> OnboardAssetAliasResult: ...


class Trading212AssetAliasRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_transaction_read_only(self) -> None:
        await self.session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )

    async def list_posted_assets(
        self,
        *,
        account_id: str,
        batch_ids: tuple[str, ...],
        source: ImportSource,
    ) -> tuple[_PostedAsset, ...]:
        rows = await self.session.execute(
            select(InvestmentMovementModel, AssetModel, AssetListingModel)
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
            .order_by(InvestmentMovementModel.event_id, InvestmentMovementModel.id)
        )
        return tuple(
            _PostedAsset(
                movement_id=movement.id,
                source_symbol=movement.source_symbol,
                source_asset_type=movement.source_asset_type,
                asset_id=movement.asset_id,
                asset_symbol=None if asset is None else asset.symbol,
                asset_type=None if asset is None else asset.asset_type,
                asset_currency=None if asset is None else asset.currency,
                asset_isin=None if asset is None else asset.isin,
                listing_id=None if listing is None else listing.id,
                listing_asset_id=None if listing is None else listing.asset_id,
                listing_symbol=None if listing is None else listing.symbol,
                listing_provider=None if listing is None else listing.provider,
                listing_provider_symbol=None if listing is None else listing.provider_symbol,
                listing_exchange=None if listing is None else listing.exchange,
                listing_currency=None if listing is None else listing.currency,
            )
            for movement, asset, listing in rows.all()
        )


def _validate_command(
    value: object,
) -> OnboardTrading212AssetAliasesCommand:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, OnboardTrading212AssetAliasesCommand)
        or not value.account_id
        or value.account_id != value.account_id.strip()
        or not isinstance(value.batch_ids, tuple)
        or not value.batch_ids
        or value.batch_ids != tuple(sorted(set(value.batch_ids)))
        or any(not item or item != item.strip() for item in value.batch_ids)
        or not isinstance(value.source, ImportSource)
        or not isinstance(value.created_at, datetime)
        or value.created_at.tzinfo is not None
        or precision is None
        or value.created_at.microsecond % (10 ** (6 - precision))
    ):
        raise AssetAliasConflictError()
    return value


def _alias_command(
    row: _PostedAsset,
    *,
    created_at: datetime,
    source_policy: MarketEvidenceSourcePolicy,
) -> OnboardAssetAliasCommand:
    if row.asset_isin is None or row.asset_symbol is None or row.listing_currency is None:
        raise AssetAliasConflictError()
    identity = _IDENTITIES.get((row.asset_isin, row.asset_symbol, row.listing_currency))
    if (
        identity is None
        or row.asset_id is None
        or row.source_symbol != identity.symbol
        or row.asset_type is None
        or row.source_asset_type is not row.asset_type
        or row.asset_currency != identity.currency
        or row.listing_id is None
        or row.listing_asset_id != row.asset_id
        or row.listing_symbol != identity.symbol
        or row.listing_provider is not PriceSource.broker
        or row.listing_provider_symbol != identity.symbol
        or row.listing_exchange != ImportSource.trading212.value
    ):
        raise AssetAliasConflictError()
    price_source = source_policy.price_source_for(row.asset_type)
    if price_source is PriceSource.yahoo_finance:
        provider = AssetAliasProvider.yahoo_finance
        external_id = identity.yahoo_symbol
        if (
            suggest_yahoo_symbol(symbol=identity.symbol, mic=identity.twelve_data_mic)
            != external_id
        ):
            raise AssetAliasConflictError()
    elif price_source is PriceSource.twelve_data:
        provider = AssetAliasProvider.twelve_data
        external_id = canonical_external_id(
            provider,
            '{"symbol":"' + identity.symbol + '","mic_code":"' + identity.twelve_data_mic + '"}',
        )
    else:
        raise AssetAliasConflictError()
    return OnboardAssetAliasCommand(
        actor="system:trading212-import",
        asset_id=row.asset_id,
        listing_id=(row.listing_id if provider is AssetAliasProvider.yahoo_finance else None),
        provider=provider,
        external_id=external_id,
        expected_symbol=identity.symbol,
        expected_asset_type=row.asset_type,
        expected_currency=identity.currency,
        expected_isin=identity.isin,
        created_at=created_at,
    )


class Trading212AssetAliasService:
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
        self.repository = repository or Trading212AssetAliasRepository(session)
        self.writer = writer or AssetAliasWriter(session)

    async def onboard(
        self, command: OnboardTrading212AssetAliasesCommand
    ) -> OnboardTrading212AssetAliasesResult:
        canonical = _validate_command(command)
        if self.session.in_transaction():
            raise AssetAliasConflictError()
        if canonical.source is not ImportSource.trading212:
            return OnboardTrading212AssetAliasesResult(aliases=())
        async with self.session.begin():
            await self.repository.set_transaction_read_only()
            rows = await self.repository.list_posted_assets(
                account_id=canonical.account_id,
                batch_ids=canonical.batch_ids,
                source=canonical.source,
            )
        if self.session.in_transaction():
            await self.session.rollback()
            raise AssetAliasConflictError()
        commands: dict[tuple[str, str | None], OnboardAssetAliasCommand] = {}
        for row in rows:
            alias = _alias_command(
                row,
                created_at=canonical.created_at,
                source_policy=self.source_policy,
            )
            key = (alias.asset_id, alias.listing_id)
            current = commands.get(key)
            if current is not None and current != alias:
                raise AssetAliasConflictError()
            commands[key] = alias
        results: list[OnboardAssetAliasResult] = []
        for key in sorted(commands, key=lambda item: (item[0], item[1] or "")):
            results.append(await self.writer.write(commands[key]))
            if self.session.in_transaction():
                await self.session.rollback()
                raise AssetAliasConflictError()
        return OnboardTrading212AssetAliasesResult(aliases=tuple(results))


__all__ = [
    "OnboardTrading212AssetAliasesCommand",
    "OnboardTrading212AssetAliasesResult",
    "Trading212AssetAliasRepository",
    "Trading212AssetAliasService",
]
