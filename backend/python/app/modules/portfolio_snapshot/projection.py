"""Pure deterministic projection from AccountSnapshot evidence to a portfolio view."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from app.modules.portfolio_snapshot.models import (
    AccountType,
    AssetType,
    PortfolioAccountView,
    PortfolioPositionView,
    PortfolioSnapshotItemSource,
    PortfolioSnapshotSource,
    PortfolioSnapshotView,
    PortfolioSummaryView,
    SnapshotGranularity,
    SnapshotSource,
)

_ERROR_MESSAGE = "Portfolio snapshot evidence cannot produce a complete view."
_POSTGRES_INTEGER_MAX = 2_147_483_647
_MONEY = (18, 6)
_QUANTITY = (28, 10)
_PERCENTAGE = (8, 4)
_INVESTMENT_ACCOUNT_TYPES = {
    AccountType.broker,
    AccountType.exchange,
    AccountType.crypto_wallet,
}
_LIABILITY_ACCOUNT_TYPES = {
    AccountType.credit_card,
    AccountType.loan,
    AccountType.mortgage,
}


class PortfolioSnapshotProjectionError(ValueError):
    """Raised when immutable snapshot evidence is incomplete or inconsistent."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


def _fail() -> PortfolioSnapshotProjectionError:
    return PortfolioSnapshotProjectionError()


def _enum[EnumT](value: object, enum_type: type[EnumT]) -> EnumT:
    if not isinstance(value, enum_type):
        raise _fail()
    return value


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    result = _text(value)
    if len(result) != 3 or any(character < "A" or character > "Z" for character in result):
        raise _fail()
    return result


def _timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or value.microsecond % 1_000 != 0
    ):
        raise _fail()
    return value


def _aligned_timestamp(value: object, granularity: SnapshotGranularity) -> datetime:
    timestamp = _timestamp(value)
    if granularity is SnapshotGranularity.minute:
        aligned = timestamp.second == 0 and timestamp.microsecond == 0
    elif granularity is SnapshotGranularity.hour:
        aligned = timestamp.minute == 0 and timestamp.second == 0 and timestamp.microsecond == 0
    elif granularity is SnapshotGranularity.day:
        aligned = timestamp.time() == datetime.min.time()
    elif granularity is SnapshotGranularity.week:
        aligned = timestamp.weekday() == 0 and timestamp.time() == datetime.min.time()
    elif granularity is SnapshotGranularity.month:
        aligned = timestamp.day == 1 and timestamp.time() == datetime.min.time()
    else:
        raise _fail()
    if not aligned:
        raise _fail()
    return timestamp


def _exact(
    value: object,
    numeric: tuple[int, int],
    *,
    nonnegative: bool = False,
) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail()
    precision, scale = numeric
    try:
        with localcontext() as context:
            context.prec = 112
            scaled = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise _fail() from exc
    if (
        value != scaled
        or abs(value) >= Decimal(10) ** (precision - scale)
        or (nonnegative and value < 0)
    ):
        raise _fail()
    return value


def _calculated(
    operation: str,
    left: Decimal,
    right: Decimal,
    numeric: tuple[int, int],
) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 112
            if operation == "add":
                result = left + right
            elif operation == "subtract":
                result = left - right
            elif operation == "multiply":
                result = left * right
            elif operation == "divide":
                result = left / right
            else:
                raise RuntimeError("Unsupported portfolio snapshot arithmetic.")
    except (InvalidOperation, OverflowError, ZeroDivisionError) as exc:
        raise _fail() from exc
    return _exact(result, numeric)


def _sum(values: tuple[Decimal, ...], numeric: tuple[int, int]) -> Decimal:
    result = Decimal(0)
    for value in values:
        result = _calculated("add", result, value, numeric)
    return result


def _validate_metadata(source: PortfolioSnapshotSource) -> tuple[str, datetime]:
    snapshot_id = _text(source.snapshot_id)
    _text(source.account_id)
    _text(source.account_name)
    _enum(source.account_type, AccountType)
    _currency(source.account_currency)
    _currency(source.output_currency)
    granularity = _enum(source.granularity, SnapshotGranularity)
    timestamp = _aligned_timestamp(source.timestamp, granularity)
    _enum(source.source, SnapshotSource)
    _timestamp(source.calculated_at)
    _timestamp(source.created_at)
    if (
        not isinstance(source.calculation_version, int)
        or isinstance(source.calculation_version, bool)
        or not 0 < source.calculation_version <= _POSTGRES_INTEGER_MAX
        or not isinstance(source.items, tuple)
    ):
        raise _fail()
    return snapshot_id, timestamp


def _validate_summary(source: PortfolioSnapshotSource) -> PortfolioSummaryView:
    cash_value = _exact(source.cash_value, _MONEY)
    investment_value = _exact(source.investment_value, _MONEY, nonnegative=True)
    investment_cost_basis = _exact(
        source.investment_cost_basis,
        _MONEY,
        nonnegative=True,
    )
    liabilities_value = _exact(source.liabilities_value, _MONEY, nonnegative=True)
    total_value = _exact(source.total_value, _MONEY)
    net_deposits_value = _exact(source.net_deposits_value, _MONEY)
    realized_pnl_value = _exact(source.realized_pnl_value, _MONEY)
    unrealized_pnl_value = _exact(source.unrealized_pnl_value, _MONEY)
    fees_value = _exact(source.fees_value, _MONEY, nonnegative=True)
    taxes_value = _exact(source.taxes_value, _MONEY, nonnegative=True)
    if (
        _calculated(
            "subtract",
            _calculated("add", cash_value, investment_value, _MONEY),
            liabilities_value,
            _MONEY,
        )
        != total_value
        or _calculated("subtract", investment_value, investment_cost_basis, _MONEY)
        != unrealized_pnl_value
    ):
        raise _fail()
    return PortfolioSummaryView(
        cash_value=cash_value,
        investment_value=investment_value,
        investment_cost_basis=investment_cost_basis,
        liabilities_value=liabilities_value,
        total_value=total_value,
        net_deposits_value=net_deposits_value,
        realized_pnl_value=realized_pnl_value,
        unrealized_pnl_value=unrealized_pnl_value,
        fees_value=fees_value,
        taxes_value=taxes_value,
        position_count=len(source.items),
    )


def _position(
    item: PortfolioSnapshotItemSource,
    *,
    output_currency: str,
    snapshot_timestamp: datetime,
) -> PortfolioPositionView:
    if not isinstance(item, PortfolioSnapshotItemSource):
        raise _fail()
    _text(item.item_id)
    listing_id = _text(item.listing_id)
    asset_id = _text(item.asset_id)
    symbol = _text(item.symbol)
    name = _text(item.name)
    asset_type = _enum(item.asset_type, AssetType)
    quantity = _exact(item.quantity, _QUANTITY, nonnegative=True)
    price_per_unit = _exact(item.price_per_unit, _QUANTITY, nonnegative=True)
    price_currency = _currency(item.price_currency)
    price_timestamp = _timestamp(item.price_timestamp)
    value = _exact(item.value, _MONEY, nonnegative=True)
    value_currency = _currency(item.value_currency)
    cost_basis = _exact(item.cost_basis, _QUANTITY, nonnegative=True)
    cost_currency = _currency(item.cost_currency)
    unrealized_pnl = _exact(item.unrealized_pnl, _QUANTITY)
    allocation_pct = _exact(item.allocation_pct, _PERCENTAGE, nonnegative=True)
    native_value = _exact(item.native_value, _QUANTITY, nonnegative=True)
    native_value_currency = _currency(item.native_value_currency)
    native_cost_basis = _exact(item.native_cost_basis, _QUANTITY, nonnegative=True)
    native_cost_currency = _currency(item.native_cost_currency)
    if (
        price_timestamp > snapshot_timestamp
        or value_currency != output_currency
        or cost_currency != output_currency
        or native_value_currency != price_currency
        or _calculated("multiply", quantity, price_per_unit, _QUANTITY) != native_value
        or _calculated("subtract", value, cost_basis, _QUANTITY) != unrealized_pnl
    ):
        raise _fail()
    return PortfolioPositionView(
        listing_id=listing_id,
        asset_id=asset_id,
        symbol=symbol,
        name=name,
        asset_type=asset_type,
        quantity=quantity,
        price_per_unit=price_per_unit,
        price_currency=price_currency,
        price_timestamp=price_timestamp,
        value=value,
        value_currency=value_currency,
        cost_basis=cost_basis,
        cost_currency=cost_currency,
        unrealized_pnl=unrealized_pnl,
        allocation_pct=allocation_pct,
        native_value=native_value,
        native_value_currency=native_value_currency,
        native_cost_basis=native_cost_basis,
        native_cost_currency=native_cost_currency,
    )


def _positions(
    source: PortfolioSnapshotSource,
    *,
    timestamp: datetime,
    summary: PortfolioSummaryView,
) -> tuple[PortfolioPositionView, ...]:
    item_ids: set[str] = set()
    listing_ids: set[str] = set()
    asset_listing_ids: set[tuple[str, str]] = set()
    projected: list[tuple[PortfolioSnapshotItemSource, PortfolioPositionView]] = []
    for item in source.items:
        if not isinstance(item, PortfolioSnapshotItemSource):
            raise _fail()
        item_id = _text(item.item_id)
        listing_id = _text(item.listing_id)
        asset_id = _text(item.asset_id)
        asset_listing_id = (asset_id, listing_id)
        if (
            item_id in item_ids
            or listing_id in listing_ids
            or asset_listing_id in asset_listing_ids
        ):
            raise _fail()
        item_ids.add(item_id)
        listing_ids.add(listing_id)
        asset_listing_ids.add(asset_listing_id)
        projected.append(
            (
                item,
                _position(
                    item,
                    output_currency=source.output_currency,
                    snapshot_timestamp=timestamp,
                ),
            )
        )

    positions = tuple(
        position
        for _, position in sorted(
            projected,
            key=lambda pair: (
                pair[1].asset_type.value,
                pair[1].symbol,
                pair[1].listing_id,
                pair[0].item_id,
            ),
        )
    )
    if (
        _sum(tuple(position.value for position in positions), _MONEY) != summary.investment_value
        or _sum(tuple(position.cost_basis for position in positions), _QUANTITY)
        != summary.investment_cost_basis
        or _sum(tuple(position.unrealized_pnl for position in positions), _QUANTITY)
        != summary.unrealized_pnl_value
    ):
        raise _fail()

    if summary.investment_value == 0:
        if any(position.allocation_pct != 0 for position in positions):
            raise _fail()
    else:
        for position in positions:
            expected = _calculated(
                "multiply",
                _calculated(
                    "divide",
                    position.value,
                    summary.investment_value,
                    _PERCENTAGE,
                ),
                Decimal(100),
                _PERCENTAGE,
            )
            if position.allocation_pct != expected or (
                position.value == 0 and position.allocation_pct != 0
            ):
                raise _fail()
        if _sum(tuple(position.allocation_pct for position in positions), _PERCENTAGE) != Decimal(
            100
        ):
            raise _fail()
    return positions


def _validate_account_type(
    source: PortfolioSnapshotSource,
    summary: PortfolioSummaryView,
    positions: tuple[PortfolioPositionView, ...],
) -> None:
    if source.account_type in _INVESTMENT_ACCOUNT_TYPES:
        return
    if source.account_type in _LIABILITY_ACCOUNT_TYPES:
        if (
            positions
            or summary.cash_value != 0
            or summary.investment_value != 0
            or summary.investment_cost_basis != 0
            or summary.net_deposits_value != 0
            or summary.realized_pnl_value != 0
            or summary.unrealized_pnl_value != 0
            or summary.fees_value != 0
            or summary.taxes_value != 0
        ):
            raise _fail()
        return
    raise _fail()


def build_portfolio_snapshot_view(source: PortfolioSnapshotSource) -> PortfolioSnapshotView:
    """Validate and rename one immutable AccountSnapshot graph for presentation."""

    if not isinstance(source, PortfolioSnapshotSource):
        raise _fail()
    snapshot_id, timestamp = _validate_metadata(source)
    summary = _validate_summary(source)
    positions = _positions(source, timestamp=timestamp, summary=summary)
    _validate_account_type(source, summary, positions)
    return PortfolioSnapshotView(
        snapshot_id=snapshot_id,
        account=PortfolioAccountView(
            account_id=source.account_id,
            name=source.account_name,
            account_type=source.account_type,
            currency=source.account_currency,
        ),
        timestamp=timestamp,
        granularity=source.granularity,
        currency=source.output_currency,
        source=source.source,
        calculation_version=source.calculation_version,
        summary=summary,
        positions=positions,
    )
