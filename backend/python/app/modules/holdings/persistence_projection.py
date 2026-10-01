"""Exact pure Holding persistence projection from canonical investment events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from app.db.models.common import MONEY, QUANTITY
from app.db.models.enums import (
    AssetType,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
)
from app.modules.holdings.projection import (
    HoldingProjectionMovement,
    HoldingProjectionStateError,
    build_holding_projection,
)
from app.shared.canonical_arithmetic import (
    CanonicalArithmeticError,
    canonical_ratio,
    canonical_rounded,
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
    listing_currency: str | None = None


@dataclass(frozen=True, slots=True)
class HoldingPersistenceEvent:
    event_id: str
    account_id: str
    event_type: InvestmentEventType
    event_date: datetime
    external_id: str | None
    movements: tuple[HoldingPersistenceMovement, ...]
    source: ImportSource | None = None
    realized_pnl: Decimal | None = None
    realized_pnl_currency: str | None = None


@dataclass(frozen=True, slots=True)
class ExpectedRealizedPnlPlan:
    event_id: str
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class ExpectedPersistedHoldingPlan:
    account_id: str
    asset_id: str
    listing_id: str
    symbol: str
    name: str | None
    asset_type: AssetType
    quantity: Decimal
    avg_buy_price: Decimal | None
    currency: str
    current_price: Decimal | None
    current_value: Decimal | None
    unrealized_pnl: Decimal | None
    realized_pnl: Decimal | None
    cost_basis_by_currency: tuple[tuple[str, Decimal], ...] | None = None


@dataclass(frozen=True, slots=True)
class HoldingPersistenceProjection:
    account_id: str
    holdings: tuple[ExpectedPersistedHoldingPlan, ...]
    realized_pnl: tuple[ExpectedRealizedPnlPlan, ...] = ()


@dataclass(frozen=True, slots=True)
class OpenCostBasisMovement:
    """One canonical position change with acquisition cost already converted at its event."""

    event_id: str
    movement_id: str
    event_date: datetime
    listing_id: str
    direction: MovementDirection
    quantity: Decimal
    settlement_amount: Decimal | None = None
    settlement_currency: str | None = None
    converted_amount: Decimal | None = None


@dataclass(frozen=True, slots=True)
class OpenCostBasisPosition:
    listing_id: str
    quantity: Decimal
    native_cost_basis: tuple[tuple[str, Decimal], ...] | None
    converted_cost_basis: Decimal | None


@dataclass(slots=True)
class _CostPosition:
    asset_id: str
    symbol: str
    asset_type: AssetType
    quantity: Decimal
    average: Decimal | None
    currency: str
    cost_basis: dict[str, Decimal] | None


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
    if (
        not isinstance(value, str)
        or len(value) != 3
        or not value.isascii()
        or not value.isalpha()
        or value != value.upper()
    ):
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


def _basis(movement: HoldingPersistenceMovement) -> tuple[Decimal, str, Decimal, str]:
    _exact(movement.quantity, positive=True)
    price = _exact(movement.price_per_unit, positive=True)
    value = _exact(movement.value_amount, positive=True)
    quote_currency = _currency(movement.listing_currency)
    settlement_currency = _currency(movement.value_currency)
    return price, quote_currency, value, settlement_currency


def _validate_value_if_present(movement: HoldingPersistenceMovement) -> None:
    values = (
        movement.price_per_unit,
        movement.value_amount,
        movement.value_currency,
    )
    if all(value is None for value in values):
        return
    _basis(movement)


def _optional_basis(
    movement: HoldingPersistenceMovement,
) -> tuple[Decimal, str, Decimal, str] | None:
    values = (
        movement.price_per_unit,
        movement.value_amount,
        movement.value_currency,
    )
    if all(value is None for value in values):
        return None
    return _basis(movement)


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
        _, _, settlement_value, settlement_currency = _basis(asset)
        if (
            _exact(cash_leg.quantity, positive=True) != settlement_value
            or _currency(cash_leg.currency) != settlement_currency
            or cash_leg.asset_id is not None
            or cash_leg.listing_id is not None
        ):
            raise _fail()
        if any(_currency(fee.currency) != settlement_currency for fee in fees):
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
    basis = _optional_basis(movement)
    quote_currency = _currency(movement.listing_currency)
    if basis is not None and basis[1] != quote_currency:
        raise _fail()
    position = positions.get(movement.listing_id)
    if position is None:
        positions[movement.listing_id] = _CostPosition(
            asset_id=movement.asset_id,
            symbol=movement.source_symbol,
            asset_type=movement.source_asset_type,
            quantity=movement.quantity,
            average=None if basis is None else basis[0],
            currency=quote_currency,
            cost_basis=(None if basis is None else {basis[3]: basis[2]}),
        )
        return
    if (
        position.asset_id != movement.asset_id
        or position.symbol != movement.source_symbol
        or position.asset_type is not movement.source_asset_type
        or position.currency != quote_currency
    ):
        raise _fail()
    new_quantity = _exact(position.quantity + movement.quantity, positive=True)
    if basis is None or position.average is None or position.cost_basis is None:
        position.quantity = new_quantity
        position.average = None
        position.cost_basis = None
        return
    price, _, settlement_value, settlement_currency = basis
    try:
        quote_cost = canonical_rounded(
            (position.quantity * position.average) + (movement.quantity * price),
            QUANTITY,
        )
    except CanonicalArithmeticError as exc:
        raise _fail() from exc
    try:
        position.average = canonical_ratio(quote_cost, new_quantity, QUANTITY)
    except CanonicalArithmeticError as exc:
        raise _fail() from exc
    position.quantity = new_quantity
    existing_settlement = position.cost_basis.get(settlement_currency, Decimal(0))
    try:
        position.cost_basis[settlement_currency] = canonical_rounded(
            existing_settlement + settlement_value,
            QUANTITY,
        )
    except CanonicalArithmeticError as exc:
        raise _fail() from exc


def _dispose(
    positions: dict[str, _CostPosition],
    movement: HoldingPersistenceMovement,
) -> Decimal | None:
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
    if movement.price_per_unit is not None:
        _, quote_currency, _, _ = _basis(movement)
        if quote_currency != position.currency:
            raise _fail()
    original_quantity = position.quantity
    try:
        disposed_cost = (
            None
            if position.average is None
            else canonical_rounded(movement.quantity * position.average, QUANTITY)
        )
    except CanonicalArithmeticError as exc:
        raise _fail() from exc
    remaining = _exact(original_quantity - movement.quantity)
    if remaining == 0:
        del positions[movement.listing_id]
    else:
        if position.cost_basis is not None:
            scaled_cost_basis: dict[str, Decimal] = {}
            for currency, amount in position.cost_basis.items():
                try:
                    remaining_amount = canonical_rounded(
                        amount * remaining / original_quantity,
                        QUANTITY,
                    )
                except (CanonicalArithmeticError, InvalidOperation, ZeroDivisionError) as exc:
                    raise _fail() from exc
                if remaining_amount <= 0:
                    raise _fail()
                scaled_cost_basis[currency] = remaining_amount
            position.cost_basis = scaled_cost_basis
        position.quantity = remaining
    return disposed_cost


def project_open_event_cost_basis(
    movements: tuple[OpenCostBasisMovement, ...],
) -> tuple[OpenCostBasisPosition, ...]:
    """Replay native and event-converted open principal with identical disposal ratios."""

    positions: dict[str, tuple[Decimal, dict[str, Decimal] | None, Decimal | None]] = {}
    seen: set[str] = set()
    precision = QUANTITY.precision
    if precision is None:
        raise RuntimeError("Canonical QUANTITY must define precision.")
    with localcontext() as context:
        context.prec = max(precision * 3, 84)
        for movement in sorted(
            movements, key=lambda item: (item.event_date, item.event_id, item.movement_id)
        ):
            if (
                not isinstance(movement, OpenCostBasisMovement)
                or not movement.event_id
                or not movement.movement_id
                or not movement.listing_id
                or movement.movement_id in seen
                or not isinstance(movement.event_date, datetime)
                or movement.event_date.tzinfo is not None
            ):
                raise _fail()
            seen.add(movement.movement_id)
            quantity = _exact(movement.quantity, positive=True)
            previous = positions.get(movement.listing_id)
            if movement.direction is MovementDirection.incoming:
                known = movement.settlement_amount is not None
                if known != (movement.settlement_currency is not None) or known != (
                    movement.converted_amount is not None
                ):
                    raise _fail()
                native_amount: Decimal | None = None
                currency: str | None = None
                acquired_converted: Decimal | None = None
                if known:
                    native_amount = _exact(movement.settlement_amount, positive=True)
                    currency = _currency(movement.settlement_currency)
                    assert movement.converted_amount is not None
                    try:
                        acquired_converted = canonical_rounded(movement.converted_amount, MONEY)
                    except CanonicalArithmeticError as exc:
                        raise _fail() from exc
                    if acquired_converted != movement.converted_amount or acquired_converted <= 0:
                        raise _fail()
                if previous is None:
                    if known:
                        assert currency is not None and native_amount is not None
                        assert acquired_converted is not None
                        positions[movement.listing_id] = (
                            quantity,
                            {currency: native_amount},
                            acquired_converted,
                        )
                    else:
                        positions[movement.listing_id] = (quantity, None, None)
                    continue
                old_quantity, old_native, old_converted = previous
                new_quantity = _exact(old_quantity + quantity, positive=True)
                if not known or old_native is None or old_converted is None:
                    positions[movement.listing_id] = (new_quantity, None, None)
                    continue
                assert currency is not None and native_amount is not None
                assert acquired_converted is not None
                updated_native = dict(old_native)
                try:
                    updated_native[currency] = canonical_rounded(
                        updated_native.get(currency, Decimal(0)) + native_amount, QUANTITY
                    )
                    updated_converted = canonical_rounded(old_converted + acquired_converted, MONEY)
                except CanonicalArithmeticError as exc:
                    raise _fail() from exc
                positions[movement.listing_id] = (new_quantity, updated_native, updated_converted)
            elif movement.direction is MovementDirection.outgoing:
                if (
                    previous is None
                    or movement.settlement_amount is not None
                    or movement.settlement_currency is not None
                    or movement.converted_amount is not None
                ):
                    raise _fail()
                old_quantity, old_native, old_converted = previous
                remaining = _exact(old_quantity - quantity)
                if remaining < 0:
                    raise _fail()
                if remaining == 0:
                    del positions[movement.listing_id]
                    continue
                try:
                    native = (
                        None
                        if old_native is None
                        else {
                            currency: canonical_rounded(amount * remaining / old_quantity, QUANTITY)
                            for currency, amount in old_native.items()
                        }
                    )
                    remaining_converted = (
                        None
                        if old_converted is None
                        else canonical_rounded(old_converted * remaining / old_quantity, MONEY)
                    )
                except (CanonicalArithmeticError, InvalidOperation, ZeroDivisionError) as exc:
                    raise _fail() from exc
                if native is not None and any(amount <= 0 for amount in native.values()):
                    raise _fail()
                if remaining_converted is not None and remaining_converted <= 0:
                    raise _fail()
                positions[movement.listing_id] = (remaining, native, remaining_converted)
            else:
                raise _fail()
    return tuple(
        OpenCostBasisPosition(
            listing_id=listing_id,
            quantity=quantity,
            native_cost_basis=None if native is None else tuple(sorted(native.items())),
            converted_cost_basis=converted,
        )
        for listing_id, (quantity, native, converted) in sorted(positions.items())
    )


def _expected_anycoin_realized_pnl(
    event: HoldingPersistenceEvent,
    asset: HoldingPersistenceMovement,
    disposed_cost: Decimal | None,
) -> ExpectedRealizedPnlPlan | None:
    if disposed_cost is None:
        # Quantity can still be projected when an earlier transfer has no
        # acquisition basis. Realized P/L must remain explicitly unknown.
        if event.realized_pnl is not None or event.realized_pnl_currency is not None:
            raise _fail()
        return None
    _, quote_currency, proceeds, settlement_currency = _basis(asset)
    if quote_currency != settlement_currency:
        raise _fail()
    try:
        amount = canonical_rounded(proceeds - disposed_cost, QUANTITY)
    except CanonicalArithmeticError as exc:
        raise _fail() from exc
    return ExpectedRealizedPnlPlan(
        event_id=event.event_id,
        amount=amount,
        currency=settlement_currency,
    )


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
            or (event.source is not None and not isinstance(event.source, ImportSource))
            or (event.realized_pnl is None) != (event.realized_pnl_currency is None)
        ):
            raise _fail()
        if event.realized_pnl is not None:
            _exact(event.realized_pnl)
            _currency(event.realized_pnl_currency)
        event_ids.add(event.event_id)
        base_movements.extend(_base_movement(event, movement) for movement in event.movements)
    quantity_projection = build_holding_projection(
        account_id=account_id,
        movements=tuple(base_movements),
    )

    ordered = sorted(events, key=lambda event: (event.event_date, event.event_id))
    positions: dict[str, _CostPosition] = {}
    realized_pnl: list[ExpectedRealizedPnlPlan] = []
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
                    disposed_cost = _dispose(positions, asset)
                    if event.source is ImportSource.anycoin:
                        expected_realized_pnl = _expected_anycoin_realized_pnl(
                            event,
                            asset,
                            disposed_cost,
                        )
                        if expected_realized_pnl is not None:
                            realized_pnl.append(expected_realized_pnl)
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
            avg_buy_price=(
                None if position.average is None else _exact(position.average, positive=True)
            ),
            currency=position.currency,
            current_price=None,
            current_value=None,
            unrealized_pnl=None,
            realized_pnl=None,
            cost_basis_by_currency=(
                None if position.cost_basis is None else tuple(sorted(position.cost_basis.items()))
            ),
        )
        for listing_id, position in sorted(positions.items())
        if (
            expected_by_listing[listing_id].asset_id == position.asset_id
            and expected_by_listing[listing_id].quantity == position.quantity
        )
    )
    if len(holdings) != len(positions):
        raise _fail()
    return HoldingPersistenceProjection(
        account_id=account_id,
        holdings=holdings,
        realized_pnl=tuple(realized_pnl),
    )


def build_holding_delta_projection(
    *,
    account_id: str,
    baseline_holdings: tuple[ExpectedPersistedHoldingPlan, ...],
    events: tuple[HoldingPersistenceEvent, ...],
) -> HoldingPersistenceProjection:
    """Advance exact baseline positions using only later canonical events."""

    if not isinstance(account_id, str) or not account_id or account_id != account_id.strip():
        raise _fail()
    positions: dict[str, _CostPosition] = {}
    for holding in baseline_holdings:
        if (
            not isinstance(holding, ExpectedPersistedHoldingPlan)
            or holding.account_id != account_id
            or not holding.asset_id
            or not holding.listing_id
            or not holding.symbol
            or holding.listing_id in positions
            or not isinstance(holding.asset_type, AssetType)
        ):
            raise _fail()
        quantity = _exact(holding.quantity, positive=True)
        average = (
            None if holding.avg_buy_price is None else _exact(holding.avg_buy_price, positive=True)
        )
        currency = _currency(holding.currency)
        cost_basis: dict[str, Decimal] | None = None
        if holding.cost_basis_by_currency is not None:
            cost_basis = {}
            for component_currency, component_amount in holding.cost_basis_by_currency:
                currency_key = _currency(component_currency)
                if currency_key in cost_basis:
                    raise _fail()
                cost_basis[currency_key] = _exact(component_amount, positive=True)
            if tuple(cost_basis.items()) != holding.cost_basis_by_currency or tuple(
                cost_basis
            ) != tuple(sorted(cost_basis)):
                raise _fail()
        if (average is None) != (cost_basis is None):
            raise _fail()
        positions[holding.listing_id] = _CostPosition(
            asset_id=holding.asset_id,
            symbol=holding.symbol,
            asset_type=holding.asset_type,
            quantity=quantity,
            average=average,
            currency=currency,
            cost_basis=cost_basis,
        )
        if cost_basis == {}:
            raise _fail()

    event_ids: set[str] = set()
    ordered = sorted(events, key=lambda event: (event.event_date, event.event_id))
    for event in ordered:
        if (
            not isinstance(event, HoldingPersistenceEvent)
            or event.account_id != account_id
            or not event.event_id
            or event.event_id in event_ids
            or not isinstance(event.event_type, InvestmentEventType)
            or not event.movements
        ):
            raise _fail()
        event_ids.add(event.event_id)
        for movement in event.movements:
            _base_movement(event, movement)
        asset = _validate_event_shape(event)
        if asset is None:
            continue
        if event.event_type in {
            InvestmentEventType.trade,
            InvestmentEventType.asset_transfer,
        }:
            if asset.direction is MovementDirection.incoming:
                _acquire(positions, asset)
            else:
                _dispose(positions, asset)

    holdings = tuple(
        ExpectedPersistedHoldingPlan(
            account_id=account_id,
            asset_id=position.asset_id,
            listing_id=listing_id,
            symbol=position.symbol,
            name=None,
            asset_type=position.asset_type,
            quantity=position.quantity,
            avg_buy_price=position.average,
            currency=position.currency,
            current_price=None,
            current_value=None,
            unrealized_pnl=None,
            realized_pnl=None,
            cost_basis_by_currency=(
                None if position.cost_basis is None else tuple(sorted(position.cost_basis.items()))
            ),
        )
        for listing_id, position in sorted(positions.items())
    )
    return HoldingPersistenceProjection(account_id=account_id, holdings=holdings)
