"""Pure deterministic AccountSnapshot valuation projection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal, InvalidOperation, localcontext
from enum import StrEnum

from sqlalchemy import Numeric

from app.db.models.common import MONEY, PERCENTAGE, QUANTITY, RATE, TIMESTAMP
from app.db.models.enums import (
    AccountType,
    AssetType,
    ExchangeRateSource,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.snapshots.calculation import (
    DerivedSnapshotCalculationError,
    multiply_derived_snapshot_values,
    round_derived_snapshot_value,
)

_ERROR_MESSAGE = "Account snapshot evidence cannot produce an exact valuation."
_CASH_ACCOUNT_TYPES = {
    AccountType.bank,
    AccountType.cash,
    AccountType.savings,
    AccountType.credit_card,
}
_INVESTMENT_ACCOUNT_TYPES = {
    AccountType.broker,
    AccountType.exchange,
    AccountType.crypto_wallet,
}
_LIABILITY_ACCOUNT_TYPES = {
    AccountType.loan,
    AccountType.mortgage,
}


class AccountSnapshotProjectionStateError(ValueError):
    """Raised when supplied evidence cannot produce one exact account valuation."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


class ExchangeRateConsumptionRole(StrEnum):
    direct = "direct"
    pivot_source = "pivot_source"
    pivot_target = "pivot_target"


@dataclass(frozen=True, slots=True)
class SnapshotHoldingEvidence:
    holding_id: str
    account_id: str
    asset_id: str
    listing_id: str
    listing_asset_id: str
    symbol: str
    asset_type: AssetType
    quantity: Decimal
    average_buy_price: Decimal | None
    cost_currency: str
    cost_basis_by_currency: tuple[CurrencyAmount, ...] | None


@dataclass(frozen=True, slots=True)
class SelectedPriceEvidence:
    price_id: str
    asset_id: str
    listing_id: str
    symbol: str
    price: Decimal
    currency: str
    source: PriceSource
    timestamp: datetime
    requested_listing_id: str | None = None


@dataclass(frozen=True, slots=True)
class SelectedExchangeRateEvidence:
    rate_id: str
    base_currency: str
    quote_currency: str
    rate: Decimal
    source: ExchangeRateSource
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class CashBalanceEvidence:
    balance_id: str
    account_id: str
    currency: str
    amount: Decimal
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class LiabilityBalanceEvidence:
    liability_id: str
    account_id: str
    currency: str
    amount: Decimal
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class AccountSnapshotProjectionInput:
    account_id: str
    account_type: AccountType
    account_currency: str
    output_currency: str
    snapshot_timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    calculation_version: int
    holdings: tuple[SnapshotHoldingEvidence, ...]
    prices: tuple[SelectedPriceEvidence, ...]
    exchange_rates: tuple[SelectedExchangeRateEvidence, ...]
    cash_balances: tuple[CashBalanceEvidence, ...]
    liabilities: tuple[LiabilityBalanceEvidence, ...]
    event_cost_basis_by_listing: tuple[tuple[str, Decimal | None], ...] | None = None


@dataclass(frozen=True, slots=True)
class CurrencyAmount:
    currency: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class ConsumedExchangeRate:
    rate_id: str
    base_currency: str
    quote_currency: str
    rate: Decimal
    source: ExchangeRateSource
    timestamp: datetime
    roles: tuple[ExchangeRateConsumptionRole, ...]


@dataclass(frozen=True, slots=True)
class CurrencyConversionLeg:
    base_currency: str
    quote_currency: str
    role: ExchangeRateConsumptionRole


@dataclass(frozen=True, slots=True)
class ExpectedAccountSnapshotItem:
    asset_id: str
    listing_id: str
    symbol: str
    quantity: Decimal
    price_per_unit: Decimal
    price_currency: str
    price_source: PriceSource
    price_timestamp: datetime
    native_value: Decimal
    value_currency: str
    value: Decimal
    native_cost_basis: Decimal | None
    native_cost_currency: str | None
    native_cost_basis_by_currency: tuple[CurrencyAmount, ...] | None
    average_buy_price: Decimal | None
    average_buy_price_currency: str | None
    cost_basis: Decimal | None
    cost_currency: str | None
    allocation_pct: Decimal


@dataclass(frozen=True, slots=True)
class ExpectedAccountSnapshotValuation:
    account_id: str
    timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    currency: str
    calculation_version: int
    cash_value: Decimal
    investment_value: Decimal
    investment_cost_basis: Decimal | None
    liabilities_value: Decimal
    total_value: Decimal
    cash_value_by_currency: tuple[CurrencyAmount, ...]
    investment_value_by_currency: tuple[CurrencyAmount, ...]
    investment_cost_basis_by_currency: tuple[CurrencyAmount, ...] | None
    liabilities_value_by_currency: tuple[CurrencyAmount, ...]
    exchange_rates: tuple[ConsumedExchangeRate, ...]
    items: tuple[ExpectedAccountSnapshotItem, ...]


def _fail() -> AccountSnapshotProjectionStateError:
    return AccountSnapshotProjectionStateError()


def _enum[EnumT](value: object, enum_type: type[EnumT]) -> EnumT:
    if not isinstance(value, enum_type):
        raise _fail()
    return value


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    currency = _nonblank(value)
    if currency != currency.upper():
        raise _fail()
    return currency


def _exact(value: object, numeric: Numeric, *, positive: bool = False) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail()
    precision, scale = numeric.precision, numeric.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical numeric type must define precision and scale.")
    quantum = Decimal(1).scaleb(-scale)
    try:
        with localcontext() as context:
            context.prec = max(precision * 3, 84)
            scaled = value.quantize(quantum)
    except InvalidOperation as exc:
        raise _fail() from exc
    if (
        value != scaled
        or abs(value) >= Decimal(10) ** (precision - scale)
        or (positive and value <= 0)
    ):
        raise _fail()
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


def _calculated(
    operation: str,
    left: Decimal,
    right: Decimal,
    numeric: Numeric,
) -> Decimal:
    if operation == "multiply":
        try:
            return multiply_derived_snapshot_values(left, right, numeric)
        except DerivedSnapshotCalculationError as exc:
            raise _fail() from exc
    precision = max(
        value
        for value in (MONEY.precision, QUANTITY.precision, RATE.precision, numeric.precision)
        if value is not None
    )
    with localcontext() as context:
        context.prec = max(precision * 4, 112)
        if operation == "add":
            result = left + right
        elif operation == "subtract":
            result = left - right
        elif operation == "divide":
            result = left / right
        else:
            raise RuntimeError("Unsupported snapshot calculation.")
    return _exact(result, numeric)


def convert_currency_amount(
    amount: Decimal,
    *,
    base_currency: str,
    output_currency: str,
    rates: Mapping[tuple[str, str], Decimal],
    numeric: Numeric,
) -> tuple[Decimal, tuple[CurrencyConversionLeg, ...]]:
    """Convert once at high precision using one direct market observation."""

    base = _currency(base_currency)
    output = _currency(output_currency)
    if not isinstance(amount, Decimal) or not amount.is_finite():
        raise _fail()
    exact_amount = amount
    if base == output:
        if rates:
            raise _fail()
        try:
            return round_derived_snapshot_value(exact_amount, numeric), ()
        except DerivedSnapshotCalculationError as exc:
            raise _fail() from exc

    direct_pair = (base, output)
    direct_rate = rates.get(direct_pair)
    if direct_rate is None or set(rates) != {direct_pair}:
        raise _fail()
    return (
        _calculated("multiply", exact_amount, direct_rate, numeric),
        (
            CurrencyConversionLeg(
                base_currency=direct_pair[0],
                quote_currency=direct_pair[1],
                role=ExchangeRateConsumptionRole.direct,
            ),
        ),
    )


def _sum(values: list[Decimal], numeric: Numeric) -> Decimal:
    total = Decimal(0)
    for value in values:
        total = _calculated("add", total, value, numeric)
    return total


def _allocation_percentages(values: tuple[Decimal, ...], total: Decimal) -> tuple[Decimal, ...]:
    """Project positive values to exact PERCENTAGE units with deterministic remainders."""

    if not values or total <= 0 or any(value <= 0 for value in values):
        raise _fail()
    try:
        with localcontext() as context:
            context.prec = 112
            scale = PERCENTAGE.scale
            if scale is None:
                raise RuntimeError("Canonical percentage type must define a scale.")
            quantum = Decimal(1).scaleb(-scale)
            target = Decimal(100).quantize(quantum)
            exact = tuple(value / total * Decimal(100) for value in values)
            floored = tuple(value.quantize(quantum, rounding=ROUND_FLOOR) for value in exact)
            residual_units = int((target - sum(floored, Decimal(0))) / quantum)
    except (InvalidOperation, OverflowError, ZeroDivisionError) as exc:
        raise _fail() from exc
    if residual_units < 0 or residual_units > len(values):
        raise _fail()
    recipients = {
        index
        for index, _remainder in sorted(
            enumerate(tuple(value - floor for value, floor in zip(exact, floored, strict=True))),
            key=lambda item: (item[1].copy_negate(), item[0]),
        )[:residual_units]
    }
    result = tuple(
        _exact(floor + (quantum if index in recipients else Decimal(0)), PERCENTAGE)
        for index, floor in enumerate(floored)
    )
    if _sum(list(result), PERCENTAGE) != target:
        raise _fail()
    return result


def _breakdown(
    amounts: dict[str, Decimal],
    numeric: Numeric,
) -> tuple[CurrencyAmount, ...]:
    return tuple(
        CurrencyAmount(currency=currency, amount=_exact(amount, numeric))
        for currency, amount in sorted(amounts.items())
    )


def _add_breakdown(
    amounts: dict[str, Decimal],
    *,
    currency: str,
    amount: Decimal,
    numeric: Numeric,
) -> None:
    amounts[currency] = _calculated(
        "add",
        amounts.get(currency, Decimal(0)),
        amount,
        numeric,
    )


def _validate_account_shape(evidence: AccountSnapshotProjectionInput) -> tuple[str, str]:
    account_id = _nonblank(evidence.account_id)
    account_type = _enum(evidence.account_type, AccountType)
    account_currency = _currency(evidence.account_currency)
    output_currency = _currency(evidence.output_currency)
    _enum(evidence.granularity, SnapshotGranularity)
    _enum(evidence.source, SnapshotSource)
    _aligned_timestamp(evidence.snapshot_timestamp, evidence.granularity)
    if (
        not isinstance(evidence.calculation_version, int)
        or isinstance(evidence.calculation_version, bool)
        or evidence.calculation_version <= 0
    ):
        raise _fail()

    if account_type in _CASH_ACCOUNT_TYPES:
        invalid = bool(evidence.holdings or evidence.prices or evidence.liabilities)
    elif account_type in _INVESTMENT_ACCOUNT_TYPES:
        invalid = bool(evidence.liabilities)
    elif account_type in _LIABILITY_ACCOUNT_TYPES:
        invalid = bool(
            evidence.holdings
            or evidence.prices
            or evidence.cash_balances
            or len(evidence.liabilities) != 1
            or _currency(evidence.liabilities[0].currency) != account_currency
        )
    else:
        raise _fail()
    if invalid:
        raise _fail()
    return account_id, output_currency


def _validate_holdings(
    evidence: AccountSnapshotProjectionInput,
    *,
    account_id: str,
) -> dict[str, SnapshotHoldingEvidence]:
    holdings: dict[str, SnapshotHoldingEvidence] = {}
    holding_ids: set[str] = set()
    for holding in evidence.holdings:
        holding_id = _nonblank(holding.holding_id)
        listing_id = _nonblank(holding.listing_id)
        asset_id = _nonblank(holding.asset_id)
        if (
            holding_id in holding_ids
            or listing_id in holdings
            or _nonblank(holding.account_id) != account_id
            or _nonblank(holding.listing_asset_id) != asset_id
        ):
            raise _fail()
        holding_ids.add(holding_id)
        _currency(holding.symbol)
        _enum(holding.asset_type, AssetType)
        _exact(holding.quantity, QUANTITY, positive=True)
        average = (
            None
            if holding.average_buy_price is None
            else _exact(holding.average_buy_price, QUANTITY, positive=True)
        )
        quote_currency = _currency(holding.cost_currency)
        component_currencies: list[str] = []
        if holding.cost_basis_by_currency is not None:
            for component in holding.cost_basis_by_currency:
                if not isinstance(component, CurrencyAmount):
                    raise _fail()
                component_currencies.append(_currency(component.currency))
                _exact(component.amount, QUANTITY, positive=True)
        if (
            (average is None) != (holding.cost_basis_by_currency is None)
            or (
                holding.cost_basis_by_currency is not None
                and (
                    not component_currencies
                    or component_currencies != sorted(component_currencies)
                    or len(set(component_currencies)) != len(component_currencies)
                )
            )
            or holding.cost_currency != quote_currency
        ):
            raise _fail()
        holdings[listing_id] = holding
    return holdings


def _validate_prices(
    evidence: AccountSnapshotProjectionInput,
    *,
    holdings: dict[str, SnapshotHoldingEvidence],
) -> dict[str, SelectedPriceEvidence]:
    prices: dict[str, SelectedPriceEvidence] = {}
    price_ids: dict[str, SelectedPriceEvidence] = {}
    for price in evidence.prices:
        price_id = _nonblank(price.price_id)
        listing_id = _nonblank(price.listing_id)
        requested_listing_id = (
            listing_id
            if price.requested_listing_id is None
            else _nonblank(price.requested_listing_id)
        )
        timestamp = _timestamp(price.timestamp)
        holding = holdings.get(requested_listing_id)
        if (
            requested_listing_id in prices
            or holding is None
            or timestamp > evidence.snapshot_timestamp
            or _nonblank(price.asset_id) != holding.asset_id
            or _currency(price.symbol) != holding.symbol
        ):
            raise _fail()
        previous = price_ids.get(price_id)
        if previous is not None and replace(
            previous, requested_listing_id=None, symbol=""
        ) != replace(price, requested_listing_id=None, symbol=""):
            raise _fail()
        # Provider quote currency is price lineage; Holding.cost_currency is
        # acquisition lineage. Each is converted independently below.
        price_ids[price_id] = price
        _exact(price.price, QUANTITY, positive=True)
        _currency(price.currency)
        _enum(price.source, PriceSource)
        prices[requested_listing_id] = price
    if prices.keys() != holdings.keys():
        raise _fail()
    return prices


def _validate_rates(
    evidence: AccountSnapshotProjectionInput,
) -> dict[tuple[str, str], SelectedExchangeRateEvidence]:
    rates: dict[tuple[str, str], SelectedExchangeRateEvidence] = {}
    rate_ids: set[str] = set()
    for rate in evidence.exchange_rates:
        rate_id = _nonblank(rate.rate_id)
        pair = (_currency(rate.base_currency), _currency(rate.quote_currency))
        timestamp = _timestamp(rate.timestamp)
        if (
            rate_id in rate_ids
            or pair in rates
            or pair[0] == pair[1]
            or timestamp > evidence.snapshot_timestamp
        ):
            raise _fail()
        rate_ids.add(rate_id)
        _exact(rate.rate, RATE, positive=True)
        _enum(rate.source, ExchangeRateSource)
        rates[pair] = rate
    return rates


def _convert(
    amount: Decimal,
    *,
    base_currency: str,
    output_currency: str,
    rates: dict[tuple[str, str], SelectedExchangeRateEvidence],
    consumed: dict[tuple[str, str], set[ExchangeRateConsumptionRole]],
    numeric: Numeric,
) -> Decimal:
    required_pairs = () if base_currency == output_currency else ((base_currency, output_currency),)
    selected = {pair: rate.rate for pair in required_pairs if (rate := rates.get(pair)) is not None}
    converted, legs = convert_currency_amount(
        amount,
        base_currency=base_currency,
        output_currency=output_currency,
        rates=selected,
        numeric=numeric,
    )
    for leg in legs:
        pair = (leg.base_currency, leg.quote_currency)
        consumed.setdefault(pair, set()).add(leg.role)
    return converted


def _raw_items(
    holdings: dict[str, SnapshotHoldingEvidence],
    prices: dict[str, SelectedPriceEvidence],
    rates: dict[tuple[str, str], SelectedExchangeRateEvidence],
    consumed: dict[tuple[str, str], set[ExchangeRateConsumptionRole]],
    *,
    output_currency: str,
    event_cost_basis_by_listing: dict[str, Decimal | None] | None,
) -> tuple[
    list[ExpectedAccountSnapshotItem],
    dict[str, Decimal],
    dict[str, Decimal] | None,
]:
    items: list[ExpectedAccountSnapshotItem] = []
    values_by_currency: dict[str, Decimal] = {}
    costs_by_currency: dict[str, Decimal] | None = {}
    for listing_id, holding in sorted(holdings.items()):
        price = prices[listing_id]
        price_currency = _currency(price.currency)
        native_value = _calculated("multiply", holding.quantity, price.price, QUANTITY)
        value = _convert(
            native_value,
            base_currency=price_currency,
            output_currency=output_currency,
            rates=rates,
            consumed=consumed,
            numeric=MONEY,
        )
        converted_costs: list[Decimal] = []
        if holding.cost_basis_by_currency is None:
            costs_by_currency = None
            cost_basis = None
        else:
            for component in holding.cost_basis_by_currency:
                component_currency = _currency(component.currency)
                component_amount = _exact(component.amount, QUANTITY, positive=True)
                if event_cost_basis_by_listing is None:
                    converted_costs.append(
                        _convert(
                            component_amount,
                            base_currency=component_currency,
                            output_currency=output_currency,
                            rates=rates,
                            consumed=consumed,
                            numeric=MONEY,
                        )
                    )
                if costs_by_currency is not None:
                    _add_breakdown(
                        costs_by_currency,
                        currency=component_currency,
                        amount=component_amount,
                        numeric=QUANTITY,
                    )
            cost_basis = (
                _sum(converted_costs, MONEY)
                if event_cost_basis_by_listing is None
                else event_cost_basis_by_listing[listing_id]
            )
        _add_breakdown(
            values_by_currency,
            currency=price_currency,
            amount=native_value,
            numeric=QUANTITY,
        )
        if holding.cost_basis_by_currency is None:
            native_cost = None
            native_cost_currency = None
        elif len(holding.cost_basis_by_currency) == 1:
            native_cost = holding.cost_basis_by_currency[0].amount
            native_cost_currency = holding.cost_basis_by_currency[0].currency
        else:
            native_cost = cost_basis
            native_cost_currency = output_currency
        items.append(
            ExpectedAccountSnapshotItem(
                asset_id=holding.asset_id,
                listing_id=listing_id,
                symbol=holding.symbol,
                quantity=holding.quantity,
                price_per_unit=price.price,
                price_currency=price_currency,
                price_source=price.source,
                price_timestamp=price.timestamp,
                native_value=native_value,
                value_currency=price_currency,
                value=value,
                native_cost_basis=native_cost,
                native_cost_currency=native_cost_currency,
                native_cost_basis_by_currency=holding.cost_basis_by_currency,
                average_buy_price=holding.average_buy_price,
                average_buy_price_currency=(
                    None if holding.average_buy_price is None else holding.cost_currency
                ),
                cost_basis=cost_basis,
                cost_currency=None if cost_basis is None else output_currency,
                allocation_pct=Decimal(0),
            )
        )
    return items, values_by_currency, costs_by_currency


def _balances(
    evidence: AccountSnapshotProjectionInput,
    *,
    account_id: str,
    output_currency: str,
    rates: dict[tuple[str, str], SelectedExchangeRateEvidence],
    consumed: dict[tuple[str, str], set[ExchangeRateConsumptionRole]],
) -> tuple[Decimal, tuple[CurrencyAmount, ...], Decimal, tuple[CurrencyAmount, ...]]:
    cash_by_currency: dict[str, Decimal] = {}
    cash_ids: set[str] = set()
    cash_currencies: set[str] = set()
    cash_converted: list[Decimal] = []
    for balance in evidence.cash_balances:
        balance_id = _nonblank(balance.balance_id)
        currency = _currency(balance.currency)
        timestamp = _timestamp(balance.timestamp)
        if (
            balance_id in cash_ids
            or currency in cash_currencies
            or _nonblank(balance.account_id) != account_id
            or timestamp > evidence.snapshot_timestamp
        ):
            raise _fail()
        cash_ids.add(balance_id)
        cash_currencies.add(currency)
        amount = _exact(balance.amount, MONEY)
        cash_by_currency[currency] = amount
        cash_converted.append(
            _convert(
                amount,
                base_currency=currency,
                output_currency=output_currency,
                rates=rates,
                consumed=consumed,
                numeric=MONEY,
            )
        )

    liabilities_by_currency: dict[str, Decimal] = {}
    liability_ids: set[str] = set()
    liability_currencies: set[str] = set()
    liabilities_converted: list[Decimal] = []
    for liability in evidence.liabilities:
        liability_id = _nonblank(liability.liability_id)
        currency = _currency(liability.currency)
        timestamp = _timestamp(liability.timestamp)
        if (
            liability_id in liability_ids
            or currency in liability_currencies
            or _nonblank(liability.account_id) != account_id
            or timestamp > evidence.snapshot_timestamp
        ):
            raise _fail()
        liability_ids.add(liability_id)
        liability_currencies.add(currency)
        amount = _exact(liability.amount, MONEY)
        if amount < 0:
            raise _fail()
        liabilities_by_currency[currency] = amount
        liabilities_converted.append(
            _convert(
                amount,
                base_currency=currency,
                output_currency=output_currency,
                rates=rates,
                consumed=consumed,
                numeric=MONEY,
            )
        )

    return (
        _sum(cash_converted, MONEY),
        _breakdown(cash_by_currency, MONEY),
        _sum(liabilities_converted, MONEY),
        _breakdown(liabilities_by_currency, MONEY),
    )


def build_account_snapshot_projection(
    evidence: AccountSnapshotProjectionInput,
) -> ExpectedAccountSnapshotValuation:
    """Calculate one exact account valuation from complete selected evidence."""

    if not isinstance(evidence, AccountSnapshotProjectionInput):
        raise _fail()
    account_id, output_currency = _validate_account_shape(evidence)
    holdings = _validate_holdings(evidence, account_id=account_id)
    event_costs: dict[str, Decimal | None] | None = None
    if evidence.event_cost_basis_by_listing is not None:
        event_costs = {}
        for listing_id, cost in evidence.event_cost_basis_by_listing:
            if not isinstance(listing_id, str) or listing_id in event_costs:
                raise _fail()
            event_costs[_nonblank(listing_id)] = (
                None if cost is None else _exact(cost, MONEY, positive=True)
            )
        if set(event_costs) != set(holdings) or any(
            (event_costs[listing_id] is None) != (holding.cost_basis_by_currency is None)
            for listing_id, holding in holdings.items()
        ):
            raise _fail()
    prices = _validate_prices(evidence, holdings=holdings)
    rates = _validate_rates(evidence)
    consumed: dict[tuple[str, str], set[ExchangeRateConsumptionRole]] = {}

    items, investment_by_currency, costs_by_currency = _raw_items(
        holdings,
        prices,
        rates,
        consumed,
        output_currency=output_currency,
        event_cost_basis_by_listing=event_costs,
    )
    investment_value = _sum([item.value for item in items], MONEY)
    known_costs = [item.cost_basis for item in items if item.cost_basis is not None]
    investment_cost_basis = (
        _sum([_exact(cost, MONEY) for cost in known_costs], MONEY)
        if len(known_costs) == len(items)
        else None
    )
    if items:
        allocations = _allocation_percentages(tuple(item.value for item in items), investment_value)
        items = [
            replace(
                item,
                allocation_pct=allocation,
            )
            for item, allocation in zip(items, allocations, strict=True)
        ]

    cash_value, cash_breakdown, liabilities_value, liabilities_breakdown = _balances(
        evidence,
        account_id=account_id,
        output_currency=output_currency,
        rates=rates,
        consumed=consumed,
    )
    if set(consumed) != set(rates):
        raise _fail()
    total_value = _calculated(
        "subtract",
        _calculated("add", cash_value, investment_value, MONEY),
        liabilities_value,
        MONEY,
    )
    consumed_rates = tuple(
        ConsumedExchangeRate(
            rate_id=rates[pair].rate_id,
            base_currency=pair[0],
            quote_currency=pair[1],
            rate=rates[pair].rate,
            source=rates[pair].source,
            timestamp=rates[pair].timestamp,
            roles=tuple(sorted(consumed[pair], key=lambda role: role.value)),
        )
        for pair in sorted(consumed)
    )
    return ExpectedAccountSnapshotValuation(
        account_id=account_id,
        timestamp=evidence.snapshot_timestamp,
        granularity=evidence.granularity,
        source=evidence.source,
        currency=output_currency,
        calculation_version=evidence.calculation_version,
        cash_value=cash_value,
        investment_value=investment_value,
        investment_cost_basis=investment_cost_basis,
        liabilities_value=liabilities_value,
        total_value=total_value,
        cash_value_by_currency=cash_breakdown,
        investment_value_by_currency=_breakdown(investment_by_currency, QUANTITY),
        investment_cost_basis_by_currency=(
            None if costs_by_currency is None else _breakdown(costs_by_currency, QUANTITY)
        ),
        liabilities_value_by_currency=liabilities_breakdown,
        exchange_rates=consumed_rates,
        items=tuple(items),
    )
