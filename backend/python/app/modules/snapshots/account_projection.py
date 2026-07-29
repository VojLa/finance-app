"""Pure deterministic AccountSnapshot valuation projection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

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

_ERROR_MESSAGE = "Account snapshot evidence cannot produce an exact valuation."
_CASH_ACCOUNT_TYPES = {
    AccountType.bank,
    AccountType.cash,
    AccountType.savings,
}
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


class AccountSnapshotProjectionStateError(ValueError):
    """Raised when supplied evidence cannot produce one exact account valuation."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


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
    average_buy_price: Decimal
    cost_currency: str


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
    native_cost_basis: Decimal
    native_cost_currency: str
    cost_basis: Decimal
    cost_currency: str
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
    investment_cost_basis: Decimal
    liabilities_value: Decimal
    total_value: Decimal
    cash_value_by_currency: tuple[CurrencyAmount, ...]
    investment_value_by_currency: tuple[CurrencyAmount, ...]
    investment_cost_basis_by_currency: tuple[CurrencyAmount, ...]
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
    precision = max(
        value
        for value in (MONEY.precision, QUANTITY.precision, RATE.precision, numeric.precision)
        if value is not None
    )
    with localcontext() as context:
        context.prec = max(precision * 4, 112)
        if operation == "multiply":
            result = left * right
        elif operation == "add":
            result = left + right
        elif operation == "subtract":
            result = left - right
        elif operation == "divide":
            result = left / right
        else:
            raise RuntimeError("Unsupported snapshot calculation.")
    return _exact(result, numeric)


def _sum(values: list[Decimal], numeric: Numeric) -> Decimal:
    total = Decimal(0)
    for value in values:
        total = _calculated("add", total, value, numeric)
    return total


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
        _exact(holding.average_buy_price, QUANTITY, positive=True)
        _currency(holding.cost_currency)
        holdings[listing_id] = holding
    return holdings


def _validate_prices(
    evidence: AccountSnapshotProjectionInput,
    *,
    holdings: dict[str, SnapshotHoldingEvidence],
) -> dict[str, SelectedPriceEvidence]:
    prices: dict[str, SelectedPriceEvidence] = {}
    price_ids: set[str] = set()
    for price in evidence.prices:
        price_id = _nonblank(price.price_id)
        listing_id = _nonblank(price.listing_id)
        timestamp = _timestamp(price.timestamp)
        holding = holdings.get(listing_id)
        if (
            price_id in price_ids
            or listing_id in prices
            or holding is None
            or timestamp > evidence.snapshot_timestamp
            or _nonblank(price.asset_id) != holding.asset_id
            or _currency(price.symbol) != holding.symbol
        ):
            raise _fail()
        price_ids.add(price_id)
        _exact(price.price, QUANTITY, positive=True)
        _currency(price.currency)
        _enum(price.source, PriceSource)
        prices[listing_id] = price
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
    consumed: set[tuple[str, str]],
    numeric: Numeric,
) -> Decimal:
    if base_currency == output_currency:
        return _exact(amount, numeric)
    pair = (base_currency, output_currency)
    rate = rates.get(pair)
    if rate is None:
        raise _fail()
    consumed.add(pair)
    return _calculated("multiply", amount, rate.rate, numeric)


def _raw_items(
    holdings: dict[str, SnapshotHoldingEvidence],
    prices: dict[str, SelectedPriceEvidence],
    rates: dict[tuple[str, str], SelectedExchangeRateEvidence],
    consumed: set[tuple[str, str]],
    *,
    output_currency: str,
) -> tuple[
    list[ExpectedAccountSnapshotItem],
    dict[str, Decimal],
    dict[str, Decimal],
]:
    items: list[ExpectedAccountSnapshotItem] = []
    values_by_currency: dict[str, Decimal] = {}
    costs_by_currency: dict[str, Decimal] = {}
    for listing_id, holding in sorted(holdings.items()):
        price = prices[listing_id]
        price_currency = _currency(price.currency)
        cost_currency = _currency(holding.cost_currency)
        native_value = _calculated("multiply", holding.quantity, price.price, QUANTITY)
        native_cost = _calculated(
            "multiply",
            holding.quantity,
            holding.average_buy_price,
            QUANTITY,
        )
        value = _convert(
            native_value,
            base_currency=price_currency,
            output_currency=output_currency,
            rates=rates,
            consumed=consumed,
            numeric=MONEY,
        )
        cost_basis = _convert(
            native_cost,
            base_currency=cost_currency,
            output_currency=output_currency,
            rates=rates,
            consumed=consumed,
            numeric=QUANTITY,
        )
        _exact(cost_basis, MONEY)
        _add_breakdown(
            values_by_currency,
            currency=price_currency,
            amount=native_value,
            numeric=QUANTITY,
        )
        _add_breakdown(
            costs_by_currency,
            currency=cost_currency,
            amount=native_cost,
            numeric=QUANTITY,
        )
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
                native_cost_currency=cost_currency,
                cost_basis=cost_basis,
                cost_currency=output_currency,
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
    consumed: set[tuple[str, str]],
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
    prices = _validate_prices(evidence, holdings=holdings)
    rates = _validate_rates(evidence)
    consumed: set[tuple[str, str]] = set()

    items, investment_by_currency, costs_by_currency = _raw_items(
        holdings,
        prices,
        rates,
        consumed,
        output_currency=output_currency,
    )
    investment_value = _sum([item.value for item in items], MONEY)
    investment_cost_basis = _sum(
        [_exact(item.cost_basis, MONEY) for item in items],
        MONEY,
    )
    if items:
        items = [
            replace(
                item,
                allocation_pct=_exact(
                    _calculated(
                        "multiply",
                        _calculated("divide", item.value, investment_value, PERCENTAGE),
                        Decimal(100),
                        PERCENTAGE,
                    ),
                    PERCENTAGE,
                ),
            )
            for item in items
        ]
        if _sum([item.allocation_pct for item in items], PERCENTAGE) != Decimal(100):
            raise _fail()

    cash_value, cash_breakdown, liabilities_value, liabilities_breakdown = _balances(
        evidence,
        account_id=account_id,
        output_currency=output_currency,
        rates=rates,
        consumed=consumed,
    )
    if consumed != set(rates):
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
        investment_cost_basis_by_currency=_breakdown(costs_by_currency, QUANTITY),
        liabilities_value_by_currency=liabilities_breakdown,
        exchange_rates=consumed_rates,
        items=tuple(items),
    )
