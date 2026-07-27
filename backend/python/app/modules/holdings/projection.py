"""Deterministic holding-quantity projection from canonical investment movements."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from app.db.models.common import QUANTITY, TIMESTAMP
from app.db.models.enums import (
    AssetType,
    InvestmentMovementKind,
    MovementDirection,
)

_ERROR_MESSAGE = "Canonical investment movements cannot be projected into holdings."


class HoldingProjectionStateError(ValueError):
    """Raised when canonical movement history cannot produce an exact projection."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


@dataclass(frozen=True, slots=True)
class HoldingProjectionMovement:
    """Complete pure input required from a persisted movement and its listing relation."""

    movement_id: str
    event_id: str
    account_id: str
    event_date: datetime
    kind: InvestmentMovementKind
    direction: MovementDirection
    quantity: Decimal
    currency: str
    asset_id: str | None
    listing_id: str | None
    listing_asset_id: str | None
    source_symbol: str | None
    source_asset_type: AssetType | None


@dataclass(frozen=True, slots=True)
class ExpectedHoldingPlan:
    """Exactly derivable Holding fields for one physical account/listing identity."""

    account_id: str
    asset_id: str
    listing_id: str
    symbol: str
    asset_type: AssetType
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class HoldingProjection:
    """Immutable expected holding-quantity projection for one account."""

    account_id: str
    holdings: tuple[ExpectedHoldingPlan, ...]


@dataclass(slots=True)
class _Position:
    asset_id: str
    symbol: str
    asset_type: AssetType
    quantity: Decimal


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise HoldingProjectionStateError()
    return value


def _canonical_currency(value: object) -> str:
    currency = _nonblank(value)
    if currency != currency.upper():
        raise HoldingProjectionStateError()
    return currency


def _exact_quantity(value: object) -> Decimal:
    if not isinstance(value, Decimal):
        raise HoldingProjectionStateError()
    precision = QUANTITY.precision
    scale = QUANTITY.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical QUANTITY must define precision and scale.")
    quantum = Decimal(1).scaleb(-scale)
    try:
        scaled = value.quantize(quantum)
    except InvalidOperation as exc:
        raise HoldingProjectionStateError() from exc
    limit = Decimal(10) ** (precision - scale)
    if not value.is_finite() or value != scaled or abs(value) >= limit:
        raise HoldingProjectionStateError()
    return value


def _exact_event_date(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or precision is None
        or not 0 <= precision <= 6
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise HoldingProjectionStateError()
    return value


def _linked_identity(
    movement: HoldingProjectionMovement,
) -> tuple[str, str, str, AssetType]:
    asset_id = _nonblank(movement.asset_id)
    listing_id = _nonblank(movement.listing_id)
    listing_asset_id = _nonblank(movement.listing_asset_id)
    symbol = _canonical_currency(movement.source_symbol)
    if listing_asset_id != asset_id or not isinstance(movement.source_asset_type, AssetType):
        raise HoldingProjectionStateError()
    return asset_id, listing_id, symbol, movement.source_asset_type


def _validate_non_asset_identity(movement: HoldingProjectionMovement) -> None:
    values = (movement.asset_id, movement.listing_id, movement.listing_asset_id)
    linked = any(value is not None for value in values)
    if linked:
        _linked_identity(movement)
    elif movement.source_symbol is not None or movement.source_asset_type is not None:
        raise HoldingProjectionStateError()


def _validate_movement(movement: HoldingProjectionMovement, *, account_id: str) -> None:
    _nonblank(movement.movement_id)
    _nonblank(movement.event_id)
    if _nonblank(movement.account_id) != account_id:
        raise HoldingProjectionStateError()
    _exact_event_date(movement.event_date)
    if not isinstance(movement.kind, InvestmentMovementKind) or not isinstance(
        movement.direction, MovementDirection
    ):
        raise HoldingProjectionStateError()
    quantity = _exact_quantity(movement.quantity)
    if quantity <= 0:
        raise HoldingProjectionStateError()
    currency = _canonical_currency(movement.currency)

    if movement.kind is InvestmentMovementKind.asset:
        _, _, symbol, _ = _linked_identity(movement)
        if currency != symbol:
            raise HoldingProjectionStateError()
    elif movement.kind is InvestmentMovementKind.cash:
        _validate_non_asset_identity(movement)
    elif movement.kind in {
        InvestmentMovementKind.fee,
        InvestmentMovementKind.tax,
    }:
        if movement.direction is not MovementDirection.outgoing:
            raise HoldingProjectionStateError()
        if any(
            value is not None
            for value in (
                movement.asset_id,
                movement.listing_id,
                movement.listing_asset_id,
                movement.source_symbol,
                movement.source_asset_type,
            )
        ):
            raise HoldingProjectionStateError()
    else:
        raise HoldingProjectionStateError()


def build_holding_projection(
    *,
    account_id: str,
    movements: tuple[HoldingProjectionMovement, ...],
) -> HoldingProjection:
    """Build an exact quantity-only projection without I/O or input mutation."""

    canonical_account_id = _nonblank(account_id)
    movement_ids: set[str] = set()
    for movement in movements:
        _validate_movement(movement, account_id=canonical_account_id)
        if movement.movement_id in movement_ids:
            raise HoldingProjectionStateError()
        movement_ids.add(movement.movement_id)

    ordered = sorted(
        movements,
        key=lambda movement: (
            movement.event_date,
            movement.event_id,
            movement.movement_id,
        ),
    )
    positions: dict[str, _Position] = {}
    precision = QUANTITY.precision
    if precision is None:
        raise RuntimeError("Canonical QUANTITY must define precision.")
    with localcontext() as context:
        context.prec = max(precision * 2, 64)
        for movement in ordered:
            if movement.kind is not InvestmentMovementKind.asset:
                continue
            asset_id, listing_id, symbol, asset_type = _linked_identity(movement)
            position = positions.get(listing_id)
            if position is None:
                position = _Position(
                    asset_id=asset_id,
                    symbol=symbol,
                    asset_type=asset_type,
                    quantity=Decimal(0),
                )
                positions[listing_id] = position
            elif (
                position.asset_id != asset_id
                or position.symbol != symbol
                or position.asset_type is not asset_type
            ):
                raise HoldingProjectionStateError()

            effect = (
                movement.quantity
                if movement.direction is MovementDirection.incoming
                else -movement.quantity
            )
            position.quantity = _exact_quantity(position.quantity + effect)
            if position.quantity < 0:
                raise HoldingProjectionStateError()

    holdings = tuple(
        ExpectedHoldingPlan(
            account_id=canonical_account_id,
            asset_id=position.asset_id,
            listing_id=listing_id,
            symbol=position.symbol,
            asset_type=position.asset_type,
            quantity=position.quantity,
        )
        for listing_id, position in sorted(positions.items())
        if position.quantity != 0
    )
    return HoldingProjection(account_id=canonical_account_id, holdings=holdings)
