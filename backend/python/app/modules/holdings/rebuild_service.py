"""Caller-transaction-owned atomic Holding rebuild writer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.common import QUANTITY, TIMESTAMP
from app.db.models.enums import AssetType
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.modules.holdings.persistence_projection import (
    ExpectedPersistedHoldingPlan,
    HoldingPersistenceEvent,
    HoldingPersistenceMovement,
    build_holding_persistence_projection,
)
from app.modules.holdings.repository import HoldingRebuildRepository

_ERROR_MESSAGE = "Canonical investment history cannot rebuild holdings."
_HOLDING_ID_NAMESPACE = UUID("9a39a6d8-7192-5f5c-b49a-e6e62a6ae907")


class HoldingRebuildStateError(ValueError):
    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


@dataclass(frozen=True, slots=True)
class HoldingCreatePlan:
    holding_id: str
    expected: ExpectedPersistedHoldingPlan
    rebuilt_at: datetime


@dataclass(frozen=True, slots=True)
class HoldingUpdatePlan:
    holding_id: str
    expected: ExpectedPersistedHoldingPlan
    rebuilt_at: datetime


@dataclass(frozen=True, slots=True)
class HoldingDeletePlan:
    holding_id: str
    listing_id: str


@dataclass(frozen=True, slots=True)
class HoldingRebuildPlan:
    account_id: str
    creates: tuple[HoldingCreatePlan, ...]
    updates: tuple[HoldingUpdatePlan, ...]
    deletes: tuple[HoldingDeletePlan, ...]


@dataclass(frozen=True, slots=True)
class HoldingRebuildResult:
    account_id: str
    created: int
    updated: int
    deleted: int
    total: int
    replayed: bool
    rebuilt_at: datetime | None


@dataclass(frozen=True, slots=True)
class CurrentHoldingState:
    holding_id: str
    account_id: str
    asset_id: str
    listing_id: str
    symbol: str
    name: str | None
    asset_type: AssetType
    quantity: Decimal
    avg_buy_price: Decimal
    currency: str
    current_price: Decimal | None
    current_value: Decimal | None
    unrealized_pnl: Decimal | None
    realized_pnl: Decimal | None
    calculated_at: datetime
    updated_at: datetime


def stable_holding_id(account_id: str, listing_id: str) -> str:
    if not _nonblank(account_id) or not _nonblank(listing_id):
        raise HoldingRebuildStateError()
    return str(uuid5(_HOLDING_ID_NAMESPACE, f"{account_id}\0{listing_id}"))


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise HoldingRebuildStateError()
    return value


def _currency(value: object) -> str:
    result = _nonblank(value)
    if result != result.upper():
        raise HoldingRebuildStateError()
    return result


def _exact_numeric(value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise HoldingRebuildStateError()
    precision, scale = QUANTITY.precision, QUANTITY.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical QUANTITY must define precision and scale.")
    try:
        scaled = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise HoldingRebuildStateError() from exc
    if not value.is_finite() or value != scaled or abs(value) >= Decimal(10) ** (precision - scale):
        raise HoldingRebuildStateError()
    return value


def _exact_timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or precision is None
        or not 0 <= precision <= 6
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise HoldingRebuildStateError()
    return value


def _optional_numeric(value: object) -> Decimal | None:
    return None if value is None else _exact_numeric(value)


def _validate_rebuilt_at(value: object) -> datetime:
    return _exact_timestamp(value)


def _validate_relation(
    *,
    asset_id: object,
    listing_id: object,
    source_symbol: object,
    source_asset_type: object,
    listings: dict[str, AssetListingModel],
    assets: dict[str, AssetModel],
) -> None:
    if asset_id is None and listing_id is None:
        return
    canonical_asset_id = _nonblank(asset_id)
    canonical_listing_id = _nonblank(listing_id)
    listing = listings.get(canonical_listing_id)
    asset = assets.get(canonical_asset_id)
    if (
        listing is None
        or asset is None
        or listing.asset_id != canonical_asset_id
        or source_symbol != listing.symbol
        or source_asset_type is not asset.asset_type
    ):
        raise HoldingRebuildStateError()


def adapt_persisted_history(
    *,
    account_id: str,
    events: list[InvestmentEventModel],
    movements: list[InvestmentMovementModel],
    listings: dict[str, AssetListingModel],
    assets: dict[str, AssetModel],
) -> tuple[HoldingPersistenceEvent, ...]:
    canonical_account_id = _nonblank(account_id)
    event_ids: set[str] = set()
    grouped: dict[str, list[InvestmentMovementModel]] = {}
    for movement in movements:
        movement_id = _nonblank(movement.id)
        event_id = _nonblank(movement.event_id)
        if movement.account_id != canonical_account_id:
            raise HoldingRebuildStateError()
        _validate_relation(
            asset_id=movement.asset_id,
            listing_id=movement.listing_id,
            source_symbol=movement.source_symbol,
            source_asset_type=movement.source_asset_type,
            listings=listings,
            assets=assets,
        )
        if any(existing.id == movement_id for existing in grouped.setdefault(event_id, [])):
            raise HoldingRebuildStateError()
        grouped[event_id].append(movement)

    result: list[HoldingPersistenceEvent] = []
    for event in events:
        event_id = _nonblank(event.id)
        if (
            event_id in event_ids
            or event.account_id != canonical_account_id
            or event.archived_at is not None
            or event.deleted_at is not None
        ):
            raise HoldingRebuildStateError()
        event_ids.add(event_id)
        event_movements = sorted(grouped.pop(event_id, []), key=lambda movement: movement.id)
        result.append(
            HoldingPersistenceEvent(
                event_id=event_id,
                account_id=event.account_id,
                event_type=event.type,
                event_date=event.date,
                external_id=event.external_id,
                movements=tuple(
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
                        listing_asset_id=(
                            listings[movement.listing_id].asset_id
                            if movement.listing_id in listings
                            else None
                        ),
                        source_symbol=movement.source_symbol,
                        source_asset_type=movement.source_asset_type,
                        price_per_unit=movement.price_per_unit,
                        value_amount=movement.value_amount,
                        value_currency=movement.value_currency,
                    )
                    for movement in event_movements
                ),
            )
        )
    if grouped:
        raise HoldingRebuildStateError()
    return tuple(result)


def validate_current_holdings(
    *,
    account_id: str,
    holdings: list[HoldingModel],
    listings: dict[str, AssetListingModel],
    assets: dict[str, AssetModel],
) -> tuple[CurrentHoldingState, ...]:
    canonical_account_id = _nonblank(account_id)
    ids: set[str] = set()
    listing_ids: set[str] = set()
    result: list[CurrentHoldingState] = []
    for holding in holdings:
        holding_id = _nonblank(holding.id)
        listing_id = _nonblank(holding.listing_id)
        asset_id = _nonblank(holding.asset_id)
        listing = listings.get(listing_id)
        asset = assets.get(asset_id)
        if (
            holding_id in ids
            or listing_id in listing_ids
            or holding.account_id != canonical_account_id
            or listing is None
            or asset is None
            or listing.asset_id != asset_id
            or holding.symbol != listing.symbol
            or holding.asset_type is not asset.asset_type
            or not isinstance(holding.name, (str, type(None)))
            or _exact_numeric(holding.quantity) <= 0
            or _exact_numeric(holding.avg_buy_price) <= 0
        ):
            raise HoldingRebuildStateError()
        ids.add(holding_id)
        listing_ids.add(listing_id)
        result.append(
            CurrentHoldingState(
                holding_id=holding_id,
                account_id=holding.account_id,
                asset_id=asset_id,
                listing_id=listing_id,
                symbol=_nonblank(holding.symbol),
                name=holding.name,
                asset_type=holding.asset_type,
                quantity=holding.quantity,
                avg_buy_price=holding.avg_buy_price,
                currency=_currency(holding.currency),
                current_price=_optional_numeric(holding.current_price),
                current_value=_optional_numeric(holding.current_value),
                unrealized_pnl=_optional_numeric(holding.unrealized_pnl),
                realized_pnl=_optional_numeric(holding.realized_pnl),
                calculated_at=_exact_timestamp(holding.calculated_at),
                updated_at=_exact_timestamp(holding.updated_at),
            )
        )
    return tuple(sorted(result, key=lambda item: (item.listing_id, item.holding_id)))


def _matches(current: CurrentHoldingState, expected: ExpectedPersistedHoldingPlan) -> bool:
    return (
        current.account_id == expected.account_id
        and current.asset_id == expected.asset_id
        and current.listing_id == expected.listing_id
        and current.symbol == expected.symbol
        and current.name == expected.name
        and current.asset_type is expected.asset_type
        and current.quantity == expected.quantity
        and current.avg_buy_price == expected.avg_buy_price
        and current.currency == expected.currency
        and current.current_price == expected.current_price
        and current.current_value == expected.current_value
        and current.unrealized_pnl == expected.unrealized_pnl
        and current.realized_pnl == expected.realized_pnl
    )


def build_holding_rebuild_plan(
    *,
    account_id: str,
    expected: tuple[ExpectedPersistedHoldingPlan, ...],
    current: tuple[CurrentHoldingState, ...],
    rebuilt_at: datetime,
) -> HoldingRebuildPlan:
    canonical_account_id = _nonblank(account_id)
    timestamp = _validate_rebuilt_at(rebuilt_at)
    expected_by_listing: dict[str, ExpectedPersistedHoldingPlan] = {}
    for item in expected:
        if item.account_id != canonical_account_id or item.listing_id in expected_by_listing:
            raise HoldingRebuildStateError()
        expected_by_listing[item.listing_id] = item
    current_by_listing = {item.listing_id: item for item in current}
    if len(current_by_listing) != len(current):
        raise HoldingRebuildStateError()

    creates: list[HoldingCreatePlan] = []
    updates: list[HoldingUpdatePlan] = []
    deletes: list[HoldingDeletePlan] = []
    existing_ids = {item.holding_id: item.listing_id for item in current}
    for listing_id, item in sorted(expected_by_listing.items()):
        existing = current_by_listing.get(listing_id)
        if existing is None:
            holding_id = stable_holding_id(canonical_account_id, listing_id)
            if holding_id in existing_ids and existing_ids[holding_id] != listing_id:
                raise HoldingRebuildStateError()
            creates.append(HoldingCreatePlan(holding_id, item, timestamp))
        elif not _matches(existing, item):
            updates.append(HoldingUpdatePlan(existing.holding_id, item, timestamp))
    for listing_id, current_item in sorted(current_by_listing.items()):
        if listing_id not in expected_by_listing:
            deletes.append(HoldingDeletePlan(current_item.holding_id, listing_id))
    return HoldingRebuildPlan(
        account_id=canonical_account_id,
        creates=tuple(creates),
        updates=tuple(updates),
        deletes=tuple(deletes),
    )


class HoldingRebuildService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = HoldingRebuildRepository(session)

    async def rebuild(
        self,
        *,
        account_id: str,
        rebuilt_at: datetime,
    ) -> HoldingRebuildResult:
        canonical_account_id = _nonblank(account_id)
        timestamp = _validate_rebuilt_at(rebuilt_at)
        await self.repository.lock_rebuild_scope(canonical_account_id)
        await self.repository.lock_canonical_history_scopes(canonical_account_id)
        events = await self.repository.load_active_events_for_update(canonical_account_id)
        movements = await self.repository.load_active_account_movements_for_update(
            canonical_account_id
        )
        holdings = await self.repository.lock_account_holdings(canonical_account_id)

        listing_ids = tuple(
            sorted(
                {
                    value
                    for value in (
                        *(movement.listing_id for movement in movements),
                        *(holding.listing_id for holding in holdings),
                    )
                    if isinstance(value, str) and value
                }
            )
        )
        asset_ids = tuple(
            sorted(
                {
                    value
                    for value in (
                        *(movement.asset_id for movement in movements),
                        *(holding.asset_id for holding in holdings),
                    )
                    if isinstance(value, str) and value
                }
            )
        )
        listing_models = await self.repository.load_listings_for_update(listing_ids)
        asset_models = await self.repository.load_assets_for_update(asset_ids)
        listings = {listing.id: listing for listing in listing_models}
        assets = {asset.id: asset for asset in asset_models}
        if len(listings) != len(listing_models) or len(assets) != len(asset_models):
            raise HoldingRebuildStateError()

        history = adapt_persisted_history(
            account_id=canonical_account_id,
            events=events,
            movements=movements,
            listings=listings,
            assets=assets,
        )
        projection = build_holding_persistence_projection(
            account_id=canonical_account_id,
            events=history,
        )
        current = validate_current_holdings(
            account_id=canonical_account_id,
            holdings=holdings,
            listings=listings,
            assets=assets,
        )
        plan = build_holding_rebuild_plan(
            account_id=canonical_account_id,
            expected=projection.holdings,
            current=current,
            rebuilt_at=timestamp,
        )
        create_ids = tuple(item.holding_id for item in plan.creates)
        if await self.repository.load_holdings_by_ids_for_update(create_ids):
            raise HoldingRebuildStateError()
        replayed = not (plan.creates or plan.updates or plan.deletes)
        if not replayed:
            by_id = {holding.id: holding for holding in holdings}
            for create in plan.creates:
                expected = create.expected
                self.repository.add_holding(
                    HoldingModel(
                        id=create.holding_id,
                        account_id=expected.account_id,
                        asset_id=expected.asset_id,
                        listing_id=expected.listing_id,
                        symbol=expected.symbol,
                        name=expected.name,
                        asset_type=expected.asset_type,
                        quantity=expected.quantity,
                        avg_buy_price=expected.avg_buy_price,
                        currency=expected.currency,
                        current_price=None,
                        current_value=None,
                        unrealized_pnl=None,
                        realized_pnl=None,
                        calculated_at=create.rebuilt_at,
                        updated_at=create.rebuilt_at,
                    )
                )
            for update in plan.updates:
                holding = by_id.get(update.holding_id)
                if holding is None:
                    raise HoldingRebuildStateError()
                expected = update.expected
                holding.asset_id = expected.asset_id
                holding.symbol = expected.symbol
                holding.name = expected.name
                holding.asset_type = expected.asset_type
                holding.quantity = expected.quantity
                holding.avg_buy_price = expected.avg_buy_price
                holding.currency = expected.currency
                holding.current_price = None
                holding.current_value = None
                holding.unrealized_pnl = None
                holding.realized_pnl = None
                holding.calculated_at = update.rebuilt_at
                holding.updated_at = update.rebuilt_at
            for deletion in plan.deletes:
                holding = by_id.get(deletion.holding_id)
                if holding is None or holding.listing_id != deletion.listing_id:
                    raise HoldingRebuildStateError()
                await self.repository.delete_holding(holding)
            await self.repository.flush()
        return HoldingRebuildResult(
            account_id=canonical_account_id,
            created=len(plan.creates),
            updated=len(plan.updates),
            deleted=len(plan.deletes),
            total=len(projection.holdings),
            replayed=replayed,
            rebuilt_at=None if replayed else timestamp,
        )
