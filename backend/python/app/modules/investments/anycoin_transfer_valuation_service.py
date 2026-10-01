"""Automatic event-date valuation for canonical Anycoin BTC transfers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings
from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.canonical_lineage import (
    AccountCanonicalChangeModel,
    AccountCanonicalStateModel,
)
from app.db.models.common import QUANTITY, TIMESTAMP
from app.db.models.enums import (
    AssetAliasProvider,
    AssetType,
    ExchangeRateSource,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
)
from app.db.models.ledger import (
    InvestmentEventModel,
    InvestmentMovementModel,
    InvestmentMovementValuationEvidenceModel,
)
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.modules.holdings.rebuild_service import HoldingRebuildService
from app.modules.holdings.repository import HoldingRebuildRepository
from app.modules.investments.transfer_valuation import transfer_valuation_fingerprint
from app.modules.market_data.history.factory import create_local_free_historical_yahoo_providers
from app.modules.market_data.history.models import (
    HistoricalExchangeRateRangeRequirement,
    HistoricalExchangeRateSelection,
    HistoricalMarketEvidenceStateError,
    HistoricalPriceRangeRequirement,
    HistoricalPriceSelection,
    HistoricalTimeSeriesInterval,
)
from app.modules.market_data.history.providers import (
    HistoricalExchangeRateProvider,
    HistoricalPriceProvider,
)
from app.modules.market_data.history.selection import (
    select_historical_exchange_rates,
    select_historical_prices,
)
from app.modules.market_data.policy import DEFAULT_MARKET_EVIDENCE_POLICY
from app.modules.market_data.writer import (
    MarketEvidenceWriter,
    PersistMarketEvidenceCommand,
    exchange_rate_id,
    price_snapshot_id,
)
from app.shared.canonical_arithmetic import canonical_rounded

_EVIDENCE_NAMESPACE = UUID("80d8a2b5-b8d5-4f61-87f0-455e3fda6c3f")
_CALCULATION_VERSION = 1
_YAHOO_REFERENCE_SYMBOL = "BTC-USD"
_YAHOO_REFERENCE_EXCHANGE = "yahoo_crypto"


def _yahoo_reference_listing_id(asset_id: str) -> str:
    return f"{asset_id}-yahoo-btc-usd"


def _is_exact_yahoo_reference_listing(listing: AssetListingModel, *, asset_id: str) -> bool:
    return (
        listing.asset_id == asset_id
        and listing.symbol == _YAHOO_REFERENCE_SYMBOL
        and listing.exchange == _YAHOO_REFERENCE_EXCHANGE
        and listing.mic is None
        and listing.currency == "USD"
        and listing.provider is PriceSource.yahoo_finance
        and listing.provider_symbol == _YAHOO_REFERENCE_SYMBOL
    )


class AnycoinTransferValuationConflictError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ValueAnycoinTransfersCommand:
    account_id: str
    source: ImportSource
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ValueAnycoinTransfersResult:
    created_count: int
    replayed_count: int


@dataclass(frozen=True, slots=True)
class _Transfer:
    event_id: str
    movement_id: str
    occurred_at: datetime
    quantity: Decimal
    direction: MovementDirection
    asset_id: str
    listing_id: str
    canonical_revision: int


def _validate_command(value: object) -> ValueAnycoinTransfersCommand:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, ValueAnycoinTransfersCommand)
        or not value.account_id
        or value.account_id != value.account_id.strip()
        or not isinstance(value.source, ImportSource)
        or not isinstance(value.created_at, datetime)
        or value.created_at.tzinfo is not None
        or precision is None
        or value.created_at.microsecond % (10 ** (6 - precision))
    ):
        raise AnycoinTransferValuationConflictError("Anycoin valuation command is invalid.")
    return value


def require_same_day_selections(
    price_selections: tuple[HistoricalPriceSelection, ...],
    fx_selections: tuple[HistoricalExchangeRateSelection, ...],
) -> None:
    if any(
        selection.observation.observed_at.date() != selection.through.date()
        for selection in price_selections
    ):
        raise HistoricalMarketEvidenceStateError()


def _evidence_matches(
    row: InvestmentMovementValuationEvidenceModel,
    *,
    account_id: str,
    transfer: _Transfer,
    fingerprint: str,
    price: PriceSnapshotModel,
    rate: ExchangeRateModel,
    unit_price: Decimal,
    value_amount: Decimal,
    selection_interval: str,
) -> bool:
    return (
        row.account_id == account_id
        and row.movement_id == transfer.movement_id
        and row.revision == 1
        and row.canonical_revision == transfer.canonical_revision
        and row.effective_at == transfer.occurred_at
        and row.calculation_version == _CALCULATION_VERSION
        and row.selection_interval == selection_interval
        and row.input_fingerprint == fingerprint
        and row.price_snapshot_id == price.id
        and row.exchange_rate_id == rate.id
        and row.price_amount == price.price
        and row.price_currency == price.currency
        and row.price_source is price.source
        and row.price_timestamp == price.timestamp
        and row.fx_rate == rate.rate
        and row.fx_from_currency == rate.from_currency
        and row.fx_to_currency == rate.to_currency
        and row.fx_source is rate.source
        and row.fx_timestamp == rate.date
        and row.price_per_unit == unit_price
        and row.value_amount == value_amount
        and row.value_currency == "CZK"
    )


class AnycoinTransferValuationService:
    """Acquire evidence outside, then persist evidence and holdings atomically."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        price_provider: HistoricalPriceProvider | None = None,
        fx_provider: HistoricalExchangeRateProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        if (price_provider is None) != (fx_provider is None):
            raise AnycoinTransferValuationConflictError(
                "Anycoin valuation providers must be supplied together."
            )
        self.price_provider = price_provider
        self.fx_provider = fx_provider

    async def value(self, command: ValueAnycoinTransfersCommand) -> ValueAnycoinTransfersResult:
        canonical = _validate_command(command)
        if canonical.source is not ImportSource.anycoin:
            return ValueAnycoinTransfersResult(created_count=0, replayed_count=0)
        if self.session.in_transaction():
            raise AnycoinTransferValuationConflictError(
                "Anycoin transfer valuation requires an idle session."
            )

        async with self.session.begin():
            account = await self.session.get(AccountModel, canonical.account_id)
            state = await self.session.get(AccountCanonicalStateModel, canonical.account_id)
            if account is None or state is None:
                raise AnycoinTransferValuationConflictError(
                    "Anycoin canonical account state is unavailable."
                )
            captured_investment_revision = state.last_investment_revision
            rows = (
                await self.session.execute(
                    select(InvestmentEventModel, InvestmentMovementModel)
                    .join(
                        InvestmentMovementModel,
                        InvestmentMovementModel.event_id == InvestmentEventModel.id,
                    )
                    .where(
                        InvestmentEventModel.account_id == canonical.account_id,
                        InvestmentEventModel.source == ImportSource.anycoin,
                        InvestmentEventModel.type == InvestmentEventType.asset_transfer,
                        InvestmentEventModel.archived_at.is_(None),
                        InvestmentEventModel.deleted_at.is_(None),
                        InvestmentMovementModel.kind == InvestmentMovementKind.asset,
                    )
                    .order_by(InvestmentEventModel.date, InvestmentEventModel.id)
                )
            ).all()
            changes = {
                row.entity_id: row
                for row in (
                    await self.session.scalars(
                        select(AccountCanonicalChangeModel).where(
                            AccountCanonicalChangeModel.account_id == canonical.account_id,
                            AccountCanonicalChangeModel.kind == "investment_event",
                        )
                    )
                ).all()
            }
            transfers: list[_Transfer] = []
            asset_ids: set[str] = set()
            listing_ids: set[str] = set()
            for event, movement in rows:
                change = changes.get(event.id)
                if (
                    change is None
                    or change.financial_timestamp != event.date
                    or change.revision > state.last_investment_revision
                    or movement.asset_id is None
                    or movement.listing_id is None
                    or movement.direction
                    not in {MovementDirection.incoming, MovementDirection.outgoing}
                    or movement.currency != "BTC"
                    or movement.source_symbol != "BTC"
                    or movement.source_asset_type is not AssetType.crypto
                    or movement.quantity <= 0
                    or any(
                        item is not None
                        for item in (
                            movement.price_per_unit,
                            movement.value_amount,
                            movement.value_currency,
                        )
                    )
                ):
                    raise AnycoinTransferValuationConflictError(
                        "An Anycoin transfer has an invalid canonical shape."
                    )
                asset_ids.add(movement.asset_id)
                listing_ids.add(movement.listing_id)
                transfers.append(
                    _Transfer(
                        event_id=event.id,
                        movement_id=movement.id,
                        occurred_at=event.date,
                        quantity=movement.quantity,
                        direction=movement.direction,
                        asset_id=movement.asset_id,
                        listing_id=movement.listing_id,
                        canonical_revision=change.revision,
                    )
                )
            if not transfers:
                return ValueAnycoinTransfersResult(created_count=0, replayed_count=0)
            if len(asset_ids) != 1 or len(listing_ids) != 1:
                raise AnycoinTransferValuationConflictError(
                    "Anycoin valuation requires one exact BTC identity per account."
                )
            listing = await self.session.get(AssetListingModel, transfers[0].listing_id)
            asset = await self.session.get(AssetModel, transfers[0].asset_id)
            if (
                account.currency != "CZK"
                or listing is None
                or listing.currency != "CZK"
                or listing.asset_id != transfers[0].asset_id
                or listing.symbol != "BTC"
                or listing.provider is not PriceSource.exchange
                or listing.provider_symbol != "BTC"
                or listing.exchange != ImportSource.anycoin.value
                or asset is None
                or asset.symbol != "BTC"
                or asset.asset_type is not AssetType.crypto
                or asset.currency != "BTC"
            ):
                raise AnycoinTransferValuationConflictError(
                    "The exact Anycoin BTC market identity is unavailable."
                )
            yahoo_reference_listing = await self.session.scalar(
                select(AssetListingModel).where(
                    AssetListingModel.provider == PriceSource.yahoo_finance,
                    AssetListingModel.provider_symbol == _YAHOO_REFERENCE_SYMBOL,
                    AssetListingModel.currency == "USD",
                )
            )
            if yahoo_reference_listing is not None and not _is_exact_yahoo_reference_listing(
                yahoo_reference_listing,
                asset_id=transfers[0].asset_id,
            ):
                raise AnycoinTransferValuationConflictError(
                    "The exact Yahoo BTC-USD reference listing is unavailable."
                )
            yahoo_reference_listing_id = (
                _yahoo_reference_listing_id(transfers[0].asset_id)
                if yahoo_reference_listing is None
                else yahoo_reference_listing.id
            )

            existing_rows = list(
                (
                    await self.session.scalars(
                        select(InvestmentMovementValuationEvidenceModel).where(
                            InvestmentMovementValuationEvidenceModel.movement_id.in_(
                                tuple(transfer.movement_id for transfer in transfers)
                            )
                        )
                    )
                ).all()
            )
            existing_counts: dict[str, int] = {}
            for row in existing_rows:
                existing_counts[row.movement_id] = existing_counts.get(row.movement_id, 0) + 1
            if any(count != 1 for count in existing_counts.values()):
                raise AnycoinTransferValuationConflictError(
                    "Existing Anycoin transfer valuation lineage is invalid."
                )
            replayed_count = len(existing_counts)
            transfers = [
                transfer for transfer in transfers if transfer.movement_id not in existing_counts
            ]
            if not transfers:
                return ValueAnycoinTransfersResult(
                    created_count=0,
                    replayed_count=replayed_count,
                )

        requested_at = tuple(sorted({item.occurred_at for item in transfers}))
        price_provider = self.price_provider
        fx_provider = self.fx_provider
        if price_provider is None or fx_provider is None:
            price_provider, fx_provider = create_local_free_historical_yahoo_providers(
                self.settings
            )
        acquisition_error: Exception | None = None
        for interval in (
            HistoricalTimeSeriesInterval.thirty_minutes,
            HistoricalTimeSeriesInterval.daily,
        ):
            try:
                price_requirement = HistoricalPriceRangeRequirement(
                    asset_id=transfers[0].asset_id,
                    listing_id=yahoo_reference_listing_id,
                    listing_currency="USD",
                    provider=PriceSource.yahoo_finance,
                    provider_symbol=_YAHOO_REFERENCE_SYMBOL,
                    requested_at=requested_at,
                    interval=interval,
                )
                fx_requirement = HistoricalExchangeRateRangeRequirement(
                    from_currency="USD",
                    to_currency="CZK",
                    provider=ExchangeRateSource.yahoo_finance,
                    requested_at=requested_at,
                    interval=interval,
                )
                price_candidates, fx_candidates = await asyncio.gather(
                    price_provider.fetch_range(price_requirement),
                    fx_provider.fetch_range(fx_requirement),
                )
                price_selections = select_historical_prices(
                    price_requirement,
                    price_candidates,
                    policy=DEFAULT_MARKET_EVIDENCE_POLICY,
                )
                fx_selections = select_historical_exchange_rates(
                    fx_requirement,
                    fx_candidates,
                    policy=DEFAULT_MARKET_EVIDENCE_POLICY,
                )
                require_same_day_selections(price_selections, fx_selections)
                break
            except HistoricalMarketEvidenceStateError as exc:
                acquisition_error = exc
        else:
            raise HistoricalMarketEvidenceStateError() from acquisition_error

        prices_by_time = {item.through: item.observation for item in price_selections}
        rates_by_time = {item.through: item.observation for item in fx_selections}

        # The provider response has now proved the exact BTC-USD identity.  Only
        # now create its separate native-USD listing; a failed/unknown Yahoo
        # symbol therefore cannot leave a synthetic listing behind.
        async with self.session.begin():
            locked_asset = await self.session.scalar(
                select(AssetModel).where(AssetModel.id == transfers[0].asset_id).with_for_update()
            )
            if locked_asset is None:
                raise AnycoinTransferValuationConflictError(
                    "The Anycoin BTC asset disappeared during market acquisition."
                )
            persisted_reference = await self.session.scalar(
                select(AssetListingModel)
                .where(
                    AssetListingModel.provider == PriceSource.yahoo_finance,
                    AssetListingModel.provider_symbol == _YAHOO_REFERENCE_SYMBOL,
                    AssetListingModel.currency == "USD",
                )
                .with_for_update()
            )
            if persisted_reference is None:
                persisted_reference = AssetListingModel(
                    id=yahoo_reference_listing_id,
                    asset_id=transfers[0].asset_id,
                    symbol=_YAHOO_REFERENCE_SYMBOL,
                    exchange=_YAHOO_REFERENCE_EXCHANGE,
                    mic=None,
                    currency="USD",
                    country=None,
                    provider=PriceSource.yahoo_finance,
                    provider_symbol=_YAHOO_REFERENCE_SYMBOL,
                    is_primary=False,
                    created_at=canonical.created_at,
                    updated_at=canonical.created_at,
                    base_priority=0,
                )
                self.session.add(persisted_reference)
                await self.session.flush()
            if (
                persisted_reference.id != yahoo_reference_listing_id
                or not _is_exact_yahoo_reference_listing(
                    persisted_reference,
                    asset_id=transfers[0].asset_id,
                )
            ):
                raise AnycoinTransferValuationConflictError(
                    "The Yahoo BTC-USD reference listing changed during acquisition."
                )
            yahoo_alias = await self.session.scalar(
                select(AssetAliasModel)
                .where(
                    AssetAliasModel.provider == AssetAliasProvider.yahoo_finance,
                    AssetAliasModel.external_id == _YAHOO_REFERENCE_SYMBOL,
                )
                .with_for_update()
            )
            if yahoo_alias is not None:
                if yahoo_alias.asset_id != transfers[0].asset_id or yahoo_alias.listing_id not in {
                    None,
                    transfers[0].listing_id,
                    yahoo_reference_listing_id,
                }:
                    raise AnycoinTransferValuationConflictError(
                        "The Yahoo BTC-USD alias conflicts with its reference listing."
                    )
                yahoo_alias.listing_id = yahoo_reference_listing_id

        await MarketEvidenceWriter(self.session).write(
            PersistMarketEvidenceCommand(
                price_observations=tuple(
                    {
                        price_snapshot_id(item.observation): item.observation
                        for item in price_selections
                    }.values()
                ),
                exchange_rate_observations=tuple(
                    {
                        exchange_rate_id(item.observation): item.observation
                        for item in fx_selections
                    }.values()
                ),
                created_at=canonical.created_at,
            )
        )
        if self.session.in_transaction():
            raise AnycoinTransferValuationConflictError(
                "Market evidence writer left an active transaction."
            )

        created_count = 0
        async with self.session.begin():
            lock_repository = HoldingRebuildRepository(self.session)
            await lock_repository.lock_rebuild_scope(canonical.account_id)
            await lock_repository.lock_canonical_history_scopes(canonical.account_id)
            locked_state = await self.session.scalar(
                select(AccountCanonicalStateModel)
                .where(AccountCanonicalStateModel.account_id == canonical.account_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                locked_state is None
                or locked_state.last_investment_revision != captured_investment_revision
            ):
                raise AnycoinTransferValuationConflictError(
                    "Anycoin canonical history changed during market acquisition."
                )
            for transfer in transfers:
                movement = await self.session.get(
                    InvestmentMovementModel, transfer.movement_id, with_for_update=True
                )
                if (
                    movement is None
                    or movement.event_id != transfer.event_id
                    or movement.quantity != transfer.quantity
                    or movement.direction is not transfer.direction
                    or any(
                        item is not None
                        for item in (
                            movement.price_per_unit,
                            movement.value_amount,
                            movement.value_currency,
                        )
                    )
                ):
                    raise AnycoinTransferValuationConflictError(
                        "Canonical transfer changed during market acquisition."
                    )
                canonical_change = await self.session.scalar(
                    select(AccountCanonicalChangeModel)
                    .where(
                        AccountCanonicalChangeModel.account_id == canonical.account_id,
                        AccountCanonicalChangeModel.kind == "investment_event",
                        AccountCanonicalChangeModel.entity_id == transfer.event_id,
                    )
                    .with_for_update()
                )
                if (
                    canonical_change is None
                    or canonical_change.revision != transfer.canonical_revision
                    or canonical_change.financial_timestamp != transfer.occurred_at
                ):
                    raise AnycoinTransferValuationConflictError(
                        "Canonical transfer lineage changed during market acquisition."
                    )
                selected_price = prices_by_time[transfer.occurred_at]
                selected_rate = rates_by_time[transfer.occurred_at]
                selected_price_id = price_snapshot_id(selected_price)
                selected_rate_id = exchange_rate_id(selected_rate)
                price = await self.session.get(PriceSnapshotModel, selected_price_id)
                rate = await self.session.get(ExchangeRateModel, selected_rate_id)
                if (
                    price is None
                    or rate is None
                    or price.asset_id != transfer.asset_id
                    or price.listing_id != yahoo_reference_listing_id
                    or price.price != selected_price.price
                    or price.currency != "USD"
                    or price.source is not PriceSource.yahoo_finance
                    or price.timestamp != selected_price.observed_at
                    or rate.rate != selected_rate.rate
                    or rate.from_currency != "USD"
                    or rate.to_currency != "CZK"
                    or rate.source is not ExchangeRateSource.yahoo_finance
                    or rate.date != selected_rate.effective_at
                ):
                    raise AnycoinTransferValuationConflictError(
                        "Persisted market evidence differs from the selected observation."
                    )
                fingerprint = transfer_valuation_fingerprint(
                    movement=movement,
                    effective_at=transfer.occurred_at,
                    canonical_revision=transfer.canonical_revision,
                    price_snapshot_id=selected_price_id,
                    exchange_rate_id=selected_rate_id,
                    calculation_version=_CALCULATION_VERSION,
                    selection_interval=interval.value,
                )
                unit_price = canonical_rounded(price.price * rate.rate, QUANTITY)
                value_amount = canonical_rounded(transfer.quantity * unit_price, QUANTITY)
                existing = list(
                    (
                        await self.session.scalars(
                            select(InvestmentMovementValuationEvidenceModel)
                            .where(
                                InvestmentMovementValuationEvidenceModel.movement_id
                                == transfer.movement_id
                            )
                            .order_by(InvestmentMovementValuationEvidenceModel.revision)
                            .with_for_update()
                        )
                    ).all()
                )
                if existing:
                    if len(existing) != 1 or not _evidence_matches(
                        existing[0],
                        account_id=canonical.account_id,
                        transfer=transfer,
                        fingerprint=fingerprint,
                        price=price,
                        rate=rate,
                        unit_price=unit_price,
                        value_amount=value_amount,
                        selection_interval=interval.value,
                    ):
                        raise AnycoinTransferValuationConflictError(
                            "Existing Anycoin transfer valuation is not an exact replay."
                        )
                    replayed_count += 1
                    continue
                self.session.add(
                    InvestmentMovementValuationEvidenceModel(
                        id=str(uuid5(_EVIDENCE_NAMESPACE, fingerprint)),
                        account_id=canonical.account_id,
                        movement_id=transfer.movement_id,
                        revision=1,
                        canonical_revision=transfer.canonical_revision,
                        effective_at=transfer.occurred_at,
                        calculation_version=_CALCULATION_VERSION,
                        selection_interval=interval.value,
                        input_fingerprint=fingerprint,
                        price_snapshot_id=selected_price_id,
                        exchange_rate_id=selected_rate_id,
                        price_amount=price.price,
                        price_currency=price.currency,
                        price_source=price.source,
                        price_timestamp=price.timestamp,
                        fx_rate=rate.rate,
                        fx_from_currency=rate.from_currency,
                        fx_to_currency=rate.to_currency,
                        fx_source=rate.source,
                        fx_timestamp=rate.date,
                        price_per_unit=unit_price,
                        value_amount=value_amount,
                        value_currency="CZK",
                        created_at=canonical.created_at,
                    )
                )
                created_count += 1
            await self.session.flush()
            await HoldingRebuildService(self.session).rebuild(
                account_id=canonical.account_id,
                rebuilt_at=canonical.created_at,
            )
        return ValueAnycoinTransfersResult(
            created_count=created_count,
            replayed_count=replayed_count,
        )


__all__ = [
    "AnycoinTransferValuationConflictError",
    "AnycoinTransferValuationService",
    "ValueAnycoinTransfersCommand",
    "ValueAnycoinTransfersResult",
    "require_same_day_selections",
]
