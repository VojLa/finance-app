"""Exact pure Holding persistence projection from canonical investment events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from app.db.models.common import QUANTITY
from app.db.models.enums import (
    AssetType,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
)
from app.modules.holdings.projection import (
    HoldingProjectionMovement,
    HoldingProjectionStateError,
    build_holding_projection,
)


@dataclass(frozen=True, slots=True)
class HoldingPersistenceMovement:
    movement_id: str
    event_id: str
    account_id: str
    kind: InvestmentMovementKind
    direction: MovementDirection
    quantity: Decimal
    currency: str
    asset_id: str | None
    listing_id: str | None
    listing_asset_id: str | None
    source_symbol: str | None
    source_asset_type: AssetType | None
    price_per_unit: Decimal | None
    value_amount: Decimal | None
    value_currency: str | None


@dataclass(frozen=True, slots=True)
class HoldingPersistenceEvent:
    event_id: str
    account_id: str
    event_type: InvestmentEventType
    event_date: datetime
    external_id: str | None
    movements: tuple[HoldingPersistenceMovement, ...]


@dataclass(frozen=True, slots=True)
class ExpectedPersistedHoldingPlan:
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


@dataclass(frozen=True, slots=True)
class HoldingPersistenceProjection:
    account_id: str
    holdings: tuple[ExpectedPersistedHoldingPlan, ...]


@dataclass(slots=True)
class _CostPosition:
    asset_id: str
    symbol: str
    asset_type: AssetType
    quantity: Decimal
    average: Decimal
    currency: str


def _fail() -> HoldingProjectionStateError:
    return HoldingProjectionStateError()


def _exact(value: object, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal):
        raise _fail()
    precision, scale = QUANTITY.precision, QUANTITY.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical QUANTITY must define precision and scale.")
    try:
        scaled = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise _fail() from exc
    if (
        not value.is_finite()
        or value != scaled
        or abs(value) >= Decimal(10) ** (precision - scale)
        or (positive and value <= 0)
    ):
        raise _fail()
    return value


def _currency(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or value != value.upper():
        raise _fail()
    return value


def _base_movement(
    event: HoldingPersistenceEvent,
    movement: HoldingPersistenceMovement,
) -> HoldingProjectionMovement:
    if movement.event_id != event.event_id or movement.account_id != event.account_id:
        raise _fail()
    return HoldingProjectionMovement(
        movement_id=movement.movement_id,
        event_id=event.event_id,
        account_id=movement.account_id,
        event_date=event.event_date,
        kind=movement.kind,
        direction=movement.direction,
        quantity=movement.quantity,
        currency=movement.currency,
        asset_id=movement.asset_id,
        listing_id=movement.listing_id,
        listing_asset_id=movement.listing_asset_id,
        source_symbol=movement.source_symbol,
        source_asset_type=movement.source_asset_type,
    )


def _parts(
    event: HoldingPersistenceEvent,
) -> tuple[
    list[HoldingPersistenceMovement],
    list[HoldingPersistenceMovement],
    list[HoldingPersistenceMovement],
]:
    assets = [m for m in event.movements if m.kind is InvestmentMovementKind.asset]
    cash = [m for m in event.movements if m.kind is InvestmentMovementKind.cash]
    fees = [m for m in event.movements if m.kind is InvestmentMovementKind.fee]
    if any(m.kind is InvestmentMovementKind.tax for m in event.movements):
        raise _fail()
    if len(fees) > 1 or any(m.direction is not MovementDirection.outgoing for m in fees):
        raise _fail()
    for movement in (*cash, *fees):
        if (
            movement.price_per_unit is not None
            or _exact(movement.value_amount, positive=True)
            != _exact(movement.quantity, positive=True)
            or _currency(movement.value_currency) != _currency(movement.currency)
        ):
            raise _fail()
    return assets, cash, fees


def _basis(movement: HoldingPersistenceMovement) -> tuple[Decimal, str]:
    quantity = _exact(movement.quantity, positive=True)
    price = _exact(movement.price_per_unit, positive=True)
    value = _exact(movement.value_amount, positive=True)
    currency = _currency(movement.value_currency)
    calculated = _exact(value / quantity, positive=True)
    if calculated != price or _exact(price * quantity, positive=True) != value:
        raise _fail()
    return price, currency


def _validate_value_if_present(movement: HoldingPersistenceMovement) -> None:
    values = (
        movement.price_per_unit,
        movement.value_amount,
        movement.value_currency,
    )
    if all(value is None for value in values):
        return
    _basis(movement)


def _validate_event_shape(event: HoldingPersistenceEvent) -> HoldingPersistenceMovement | None:
    assets, cash, fees = _parts(event)
    event_type = event.event_type
    if event_type is InvestmentEventType.trade:
        if len(assets) != 1 or len(cash) != 1:
            raise _fail()
        asset, cash_leg = assets[0], cash[0]
        expected_cash_direction = (
            MovementDirection.outgoing
            if asset.direction is MovementDirection.incoming
            else MovementDirection.incoming
        )
        if cash_leg.direction is not expected_cash_direction:
            raise _fail()
        _, cost_currency = _basis(asset)
        if (
            _exact(cash_leg.quantity, positive=True) != asset.value_amount
            or _currency(cash_leg.currency) != cost_currency
            or cash_leg.asset_id is not None
            or cash_leg.listing_id is not None
        ):
            raise _fail()
        return asset
    if event_type is InvestmentEventType.asset_transfer:
        if len(assets) != 1 or cash:
            raise _fail()
        _validate_value_if_present(assets[0])
        return assets[0]
    if event_type is InvestmentEventType.dividend:
        if (
            assets
            or len(cash) != 1
            or cash[0].direction is not MovementDirection.incoming
            or cash[0].asset_id is None
            or cash[0].listing_id is None
        ):
            raise _fail()
        return None
    if event_type in {InvestmentEventType.interest, InvestmentEventType.cash_deposit}:
        if assets or len(cash) != 1 or cash[0].direction is not MovementDirection.incoming:
            raise _fail()
        return None
    if event_type is InvestmentEventType.cash_withdrawal:
        if assets or len(cash) != 1 or cash[0].direction is not MovementDirection.outgoing:
            raise _fail()
        return None
    if event_type is InvestmentEventType.currency_conversion:
        if (
            assets
            or len(cash) != 2
            or {movement.direction for movement in cash}
            != {MovementDirection.incoming, MovementDirection.outgoing}
        ):
            raise _fail()
        return None
    if event_type is InvestmentEventType.fee:
        if assets or cash or len(fees) != 1:
            raise _fail()
        return None
    if event_type in {
        InvestmentEventType.staking_reward,
        InvestmentEventType.airdrop,
        InvestmentEventType.adjustment,
    }:
        raise _fail()
    raise _fail()


def _acquire(
    positions: dict[str, _CostPosition],
    movement: HoldingPersistenceMovement,
) -> None:
    if (
        movement.asset_id is None
        or movement.listing_id is None
        or movement.source_symbol is None
        or movement.source_asset_type is None
    ):
        raise _fail()
    price, currency = _basis(movement)
    position = positions.get(movement.listing_id)
    if position is None:
        positions[movement.listing_id] = _CostPosition(
            asset_id=movement.asset_id,
            symbol=movement.source_symbol,
            asset_type=movement.source_asset_type,
            quantity=movement.quantity,
            average=price,
            currency=currency,
        )
        return
    if (
        position.asset_id != movement.asset_id
        or position.symbol != movement.source_symbol
        or position.asset_type is not movement.source_asset_type
        or position.currency != currency
    ):
        raise _fail()
    existing_cost = _exact(position.quantity * position.average)
    new_cost = _exact(existing_cost + _exact(movement.value_amount, positive=True))
    new_quantity = _exact(position.quantity + movement.quantity, positive=True)
    position.average = _exact(new_cost / new_quantity, positive=True)
    position.quantity = new_quantity


def _dispose(
    positions: dict[str, _CostPosition],
    movement: HoldingPersistenceMovement,
) -> None:
    if movement.listing_id is None:
        raise _fail()
    position = positions.get(movement.listing_id)
    if (
        position is None
        or position.asset_id != movement.asset_id
        or position.symbol != movement.source_symbol
        or position.asset_type is not movement.source_asset_type
        or movement.quantity > position.quantity
    ):
        raise _fail()
    remaining = _exact(position.quantity - movement.quantity)
    if remaining == 0:
        del positions[movement.listing_id]
    else:
        position.quantity = remaining


def build_holding_persistence_projection(
    *,
    account_id: str,
    events: tuple[HoldingPersistenceEvent, ...],
) -> HoldingPersistenceProjection:
    """Build every non-temporal Holding field only from exact canonical evidence."""

    if not isinstance(account_id, str) or not account_id or account_id != account_id.strip():
        raise _fail()
    event_ids: set[str] = set()
    base_movements: list[HoldingProjectionMovement] = []
    for event in events:
        if (
            event.account_id != account_id
            or not isinstance(event.event_id, str)
            or not event.event_id
            or event.event_id in event_ids
            or not isinstance(event.event_type, InvestmentEventType)
            or not event.movements
            or (event.external_id is not None and not isinstance(event.external_id, str))
        ):
            raise _fail()
        event_ids.add(event.event_id)
        base_movements.extend(_base_movement(event, movement) for movement in event.movements)
    quantity_projection = build_holding_projection(
        account_id=account_id,
        movements=tuple(base_movements),
    )

    ordered = sorted(events, key=lambda event: (event.event_date, event.event_id))
    positions: dict[str, _CostPosition] = {}
    precision = QUANTITY.precision
    if precision is None:
        raise RuntimeError("Canonical QUANTITY must define precision.")
    with localcontext() as context:
        context.prec = max(precision * 3, 84)
        for event in ordered:
            asset = _validate_event_shape(event)
            if asset is None:
                continue
            if event.event_type is InvestmentEventType.trade:
                if asset.direction is MovementDirection.incoming:
                    _acquire(positions, asset)
                else:
                    _dispose(positions, asset)
            elif event.event_type is InvestmentEventType.asset_transfer:
                if asset.direction is MovementDirection.incoming:
                    _acquire(positions, asset)
                else:
                    _dispose(positions, asset)

    expected_by_listing = {holding.listing_id: holding for holding in quantity_projection.holdings}
    if set(expected_by_listing) != set(positions):
        raise _fail()
    holdings = tuple(
        ExpectedPersistedHoldingPlan(
            account_id=account_id,
            asset_id=position.asset_id,
            listing_id=listing_id,
            symbol=position.symbol,
            name=None,
            asset_type=position.asset_type,
            quantity=position.quantity,
            avg_buy_price=_exact(position.average, positive=True),
            currency=position.currency,
            current_price=None,
            current_value=None,
            unrealized_pnl=None,
            realized_pnl=None,
        )
        for listing_id, position in sorted(positions.items())
        if (
            expected_by_listing[listing_id].asset_id == position.asset_id
            and expected_by_listing[listing_id].quantity == position.quantity
        )
    )
    if len(holdings) != len(positions):
        raise _fail()
    return HoldingPersistenceProjection(account_id=account_id, holdings=holdings)
