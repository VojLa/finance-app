"""Pure exact projection into the physical AccountSnapshot row contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from uuid import UUID, uuid5

from sqlalchemy import Numeric

from app.db.models.common import MONEY, PERCENTAGE, QUANTITY, RATE, TIMESTAMP
from app.db.models.enums import (
    ExchangeRateSource,
    LiabilityBalanceSource,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.snapshots.account_projection import (
    ConsumedExchangeRate,
    CurrencyAmount,
    ExchangeRateConsumptionRole,
    ExpectedAccountSnapshotItem,
    ExpectedAccountSnapshotValuation,
    convert_currency_amount,
)
from app.modules.snapshots.calculation import (
    DerivedSnapshotCalculationError,
    multiply_derived_snapshot_values,
)
from app.modules.snapshots.evidence_service import (
    CompleteAccountSnapshotEvidence,
    ExactSnapshotMetric,
    SnapshotMetricUnsupportedReason,
    UnsupportedSnapshotMetric,
)
from app.modules.snapshots.financial_metrics import ConsumedHistoricalExchangeRate

_ERROR_MESSAGE = "Account snapshot evidence is not physically persistable."
_SNAPSHOT_ID_NAMESPACE = UUID("63a292f7-4329-5bae-acd7-5a7bde53a01c")
_ITEM_ID_NAMESPACE = UUID("2c260800-5e2a-54c6-9596-4fb1827b867d")
_POSTGRES_INTEGER_MAX = 2_147_483_647
_LEGACY_GENERATION_ID = "legacy-snapshot-generation:3u0001"


class AccountSnapshotPersistenceProjectionError(ValueError):
    """Raised when exact evidence cannot populate every physical snapshot field."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


@dataclass(frozen=True, slots=True)
class CanonicalJsonObject:
    """Deeply immutable ordered JSON object with an explicit materialization boundary."""

    entries: tuple[tuple[str, object], ...]

    def to_json(self) -> dict[str, object]:
        return {key: _json_value(value) for key, value in self.entries}


@dataclass(frozen=True, slots=True)
class AccountSnapshotPersistenceMetadata:
    calculated_at: datetime
    created_at: datetime
    is_recalculated: bool
    generation_id: str = _LEGACY_GENERATION_ID


@dataclass(frozen=True, slots=True)
class ExpectedAccountSnapshotRow:
    id: str
    account_id: str
    timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    currency: str
    cash_value: Decimal
    investment_value: Decimal
    investment_cost_basis: Decimal | None
    liabilities_value: Decimal
    total_value: Decimal
    is_recalculated: bool
    calculated_at: datetime
    calculation_version: int
    created_at: datetime
    net_deposits_value: Decimal | None
    realized_pnl_value: Decimal | None
    unrealized_pnl_value: Decimal | None
    fees_value: Decimal
    taxes_value: Decimal
    cash_value_by_currency: CanonicalJsonObject
    investment_value_by_currency: CanonicalJsonObject
    investment_cost_basis_by_currency: CanonicalJsonObject | None
    liabilities_value_by_currency: CanonicalJsonObject
    net_deposits_by_currency: CanonicalJsonObject | None
    realized_pnl_by_currency: CanonicalJsonObject | None
    unrealized_pnl_by_currency: CanonicalJsonObject | None
    fees_by_currency: CanonicalJsonObject
    taxes_by_currency: CanonicalJsonObject
    exchange_rates: CanonicalJsonObject
    generation_id: str = _LEGACY_GENERATION_ID

    def model_values(self) -> dict[str, object]:
        return {
            "id": self.id,
            "account_id": self.account_id,
            "timestamp": self.timestamp,
            "granularity": self.granularity,
            "source": self.source,
            "currency": self.currency,
            "cash_value": self.cash_value,
            "investment_value": self.investment_value,
            "investment_cost_basis": self.investment_cost_basis,
            "liabilities_value": self.liabilities_value,
            "total_value": self.total_value,
            "is_recalculated": self.is_recalculated,
            "calculated_at": self.calculated_at,
            "calculation_version": self.calculation_version,
            "created_at": self.created_at,
            "net_deposits_value": self.net_deposits_value,
            "realized_pnl_value": self.realized_pnl_value,
            "unrealized_pnl_value": self.unrealized_pnl_value,
            "fees_value": self.fees_value,
            "taxes_value": self.taxes_value,
            "cash_value_by_currency": self.cash_value_by_currency.to_json(),
            "investment_value_by_currency": self.investment_value_by_currency.to_json(),
            "investment_cost_basis_by_currency": (
                None
                if self.investment_cost_basis_by_currency is None
                else self.investment_cost_basis_by_currency.to_json()
            ),
            "liabilities_value_by_currency": self.liabilities_value_by_currency.to_json(),
            "net_deposits_by_currency": (
                None
                if self.net_deposits_by_currency is None
                else self.net_deposits_by_currency.to_json()
            ),
            "realized_pnl_by_currency": (
                None
                if self.realized_pnl_by_currency is None
                else self.realized_pnl_by_currency.to_json()
            ),
            "unrealized_pnl_by_currency": (
                None
                if self.unrealized_pnl_by_currency is None
                else self.unrealized_pnl_by_currency.to_json()
            ),
            "fees_by_currency": self.fees_by_currency.to_json(),
            "taxes_by_currency": self.taxes_by_currency.to_json(),
            "exchange_rates": self.exchange_rates.to_json(),
            "generation_id": self.generation_id,
        }


@dataclass(frozen=True, slots=True)
class ExpectedAccountSnapshotItemRow:
    id: str
    snapshot_id: str
    asset_id: str | None
    listing_id: str
    symbol: str
    quantity: Decimal
    price_per_unit: Decimal
    price_currency: str | None
    price_source: PriceSource | None
    price_timestamp: datetime | None
    value: Decimal
    cost_basis: Decimal | None
    cost_currency: str | None
    allocation_pct: Decimal
    created_at: datetime
    native_value: Decimal | None
    value_currency: str | None
    native_cost_basis: Decimal | None
    native_cost_currency: str | None
    native_cost_basis_by_currency: CanonicalJsonObject | None
    average_buy_price: Decimal | None
    average_buy_price_currency: str | None

    def model_values(self) -> dict[str, object]:
        return {
            "id": self.id,
            "snapshot_id": self.snapshot_id,
            "asset_id": self.asset_id,
            "listing_id": self.listing_id,
            "symbol": self.symbol,
            "quantity": self.quantity,
            "price_per_unit": self.price_per_unit,
            "price_currency": self.price_currency,
            "price_source": self.price_source,
            "price_timestamp": self.price_timestamp,
            "value": self.value,
            "cost_basis": self.cost_basis,
            "cost_currency": self.cost_currency,
            "allocation_pct": self.allocation_pct,
            "created_at": self.created_at,
            "native_value": self.native_value,
            "value_currency": self.value_currency,
            "native_cost_basis": self.native_cost_basis,
            "native_cost_currency": self.native_cost_currency,
            "native_cost_basis_by_currency": (
                None
                if self.native_cost_basis_by_currency is None
                else self.native_cost_basis_by_currency.to_json()
            ),
            "average_buy_price": self.average_buy_price,
            "average_buy_price_currency": self.average_buy_price_currency,
        }


@dataclass(frozen=True, slots=True)
class AccountSnapshotPersistenceAudit:
    selected_price_ids: tuple[str, ...]
    selected_snapshot_exchange_rate_ids: tuple[str, ...]
    selected_historical_exchange_rate_ids: tuple[str, ...]
    selected_liability_balance_id: str | None = None
    selected_liability_effective_at: datetime | None = None
    selected_liability_source: LiabilityBalanceSource | None = None


@dataclass(frozen=True, slots=True)
class ExpectedAccountSnapshotPersistence:
    snapshot: ExpectedAccountSnapshotRow
    items: tuple[ExpectedAccountSnapshotItemRow, ...]
    audit: AccountSnapshotPersistenceAudit


def _fail() -> AccountSnapshotPersistenceProjectionError:
    return AccountSnapshotPersistenceProjectionError()


def _json_value(value: object) -> object:
    if isinstance(value, CanonicalJsonObject):
        return value.to_json()
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if value is None or isinstance(value, str | int | bool):
        return value
    raise _fail()


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    result = _nonblank(value)
    if result != result.upper():
        raise _fail()
    return result


def _enum[EnumT](value: object, enum_type: type[EnumT]) -> EnumT:
    if not isinstance(value, enum_type):
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


def _exact(
    value: object,
    numeric: Numeric,
    *,
    positive: bool = False,
    nonnegative: bool = False,
) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail()
    precision, scale = numeric.precision, numeric.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical numeric types must define precision and scale.")
    try:
        with localcontext() as context:
            context.prec = max(precision * 4, 112)
            scaled = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise _fail() from exc
    if (
        value != scaled
        or abs(value) >= Decimal(10) ** (precision - scale)
        or (positive and value <= 0)
        or (nonnegative and value < 0)
    ):
        raise _fail()
    return value


def _calculated(operation: str, left: Decimal, right: Decimal, numeric: Numeric) -> Decimal:
    if operation == "multiply":
        try:
            return multiply_derived_snapshot_values(left, right, numeric)
        except DerivedSnapshotCalculationError as exc:
            raise _fail() from exc
    try:
        with localcontext() as context:
            context.prec = 112
            if operation == "add":
                result = left + right
            elif operation == "subtract":
                result = left - right
            else:
                raise RuntimeError(f"Unsupported arithmetic operation: {operation}")
    except (InvalidOperation, OverflowError) as exc:
        raise _fail() from exc
    return _exact(result, numeric)


def _sum(values: tuple[Decimal, ...], numeric: Numeric) -> Decimal:
    result = Decimal(0)
    for value in values:
        result = _calculated("add", result, value, numeric)
    return result


def _decimal_string(value: Decimal, numeric: Numeric) -> str:
    exact = _exact(value, numeric)
    scale = numeric.scale
    if scale is None:
        raise RuntimeError("Canonical numeric types must define a scale.")
    return format(exact, f".{scale}f")


def _breakdown(
    value: object,
    *,
    numeric: Numeric,
    converted_value: Decimal | None,
    output_currency: str,
    allow_none: bool = False,
    nonnegative: bool = False,
) -> CanonicalJsonObject | None:
    if value is None:
        if allow_none:
            return None
        raise _fail()
    if converted_value is None:
        raise _fail()
    if not isinstance(value, tuple):
        raise _fail()
    amounts: dict[str, Decimal] = {}
    for item in value:
        if not isinstance(item, CurrencyAmount):
            raise _fail()
        currency = _currency(item.currency)
        if currency in amounts:
            raise _fail()
        amounts[currency] = _exact(item.amount, numeric, nonnegative=nonnegative)
    if not amounts and converted_value != 0:
        raise _fail()
    # Native portfolio breakdowns intentionally retain QUANTITY precision.
    # They can therefore differ from an output MONEY scalar after the latter's
    # explicit derived rounding boundary.
    if (
        numeric is MONEY
        and set(amounts) == {output_currency}
        and amounts[output_currency] != converted_value
    ):
        raise _fail()
    return CanonicalJsonObject(
        tuple(
            (currency, _decimal_string(amount, numeric))
            for currency, amount in sorted(amounts.items())
        )
    )


def _metric(
    value: object,
    *,
    output_currency: str,
    allow_none_breakdown: bool = False,
    nonnegative: bool = False,
    unsupported_reason: SnapshotMetricUnsupportedReason | None = None,
) -> tuple[Decimal | None, CanonicalJsonObject | None]:
    if isinstance(value, UnsupportedSnapshotMetric):
        if unsupported_reason is None or value.reason is not unsupported_reason:
            raise _fail()
        return None, None
    if not isinstance(value, ExactSnapshotMetric):
        raise _fail()
    exact_value = _exact(value.value, MONEY, nonnegative=nonnegative)
    breakdown = _breakdown(
        value.breakdown,
        numeric=MONEY,
        converted_value=exact_value,
        output_currency=output_currency,
        allow_none=allow_none_breakdown,
        nonnegative=nonnegative,
    )
    return exact_value, breakdown


def _stable_ids(values: object, *, expected_count: int | None = None) -> tuple[str, ...]:
    if not isinstance(values, tuple):
        raise _fail()
    result = tuple(sorted(_nonblank(value) for value in values))
    if len(set(result)) != len(result) or (
        expected_count is not None and len(result) != expected_count
    ):
        raise _fail()
    return result


def _snapshot_id(valuation: ExpectedAccountSnapshotValuation, generation_id: str) -> str:
    identity: tuple[str, ...] = (
        valuation.account_id,
        valuation.timestamp.isoformat(timespec="milliseconds"),
        valuation.currency,
        valuation.granularity.value,
    )
    if generation_id != _LEGACY_GENERATION_ID:
        identity = (*identity, generation_id)
    payload = "\0".join(identity)
    return str(uuid5(_SNAPSHOT_ID_NAMESPACE, payload))


def _item_id(snapshot_id: str, listing_id: str) -> str:
    return str(uuid5(_ITEM_ID_NAMESPACE, f"{snapshot_id}\0{listing_id}"))


def _exchange_rates(
    valuation: ExpectedAccountSnapshotValuation,
    *,
    selected_snapshot_ids: tuple[str, ...],
    historical_ids: tuple[str, ...],
    historical_rates: tuple[ConsumedHistoricalExchangeRate, ...],
) -> CanonicalJsonObject:
    rates: list[tuple[tuple[str, str, str], CanonicalJsonObject]] = []
    rate_ids: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for rate in valuation.exchange_rates:
        if not isinstance(rate, ConsumedExchangeRate):
            raise _fail()
        rate_id = _nonblank(rate.rate_id)
        base = _currency(rate.base_currency)
        quote = _currency(rate.quote_currency)
        pair = (base, quote)
        timestamp = _timestamp(rate.timestamp)
        source = _enum(rate.source, ExchangeRateSource)
        exact_rate = _exact(rate.rate, RATE, positive=True)
        roles = tuple(_enum(role, ExchangeRateConsumptionRole) for role in rate.roles)
        expected_role = (
            ExchangeRateConsumptionRole.direct
            if quote == valuation.currency
            else ExchangeRateConsumptionRole.pivot_target
            if base == valuation.currency
            else ExchangeRateConsumptionRole.pivot_source
        )
        if rate_id in rate_ids or pair in pairs or base == quote or roles != (expected_role,):
            raise _fail()
        rate_ids.add(rate_id)
        pairs.add(pair)
        rates.append(
            (
                (base, quote, rate_id),
                CanonicalJsonObject(
                    (
                        ("rateId", rate_id),
                        ("from", base),
                        ("to", quote),
                        ("rate", _decimal_string(exact_rate, RATE)),
                        ("timestamp", timestamp.isoformat(timespec="milliseconds")),
                        ("source", source.value),
                        ("roles", tuple(role.value for role in roles)),
                    )
                ),
            )
        )
    if rate_ids != set(selected_snapshot_ids):
        raise _fail()
    historical_entries: list[tuple[tuple[str, str, str, str], CanonicalJsonObject]] = []
    historical_rate_ids: set[str] = set()
    historical_keys: set[tuple[str, str, str]] = set()
    for consumed in historical_rates:
        if not isinstance(consumed, ConsumedHistoricalExchangeRate):
            raise _fail()
        rate_id = _nonblank(consumed.rate_id)
        evidence_id = _nonblank(consumed.evidence_id)
        base = _currency(consumed.base_currency)
        quote = _currency(consumed.quote_currency)
        exact_historical_rate = _exact(consumed.rate, RATE, positive=True)
        timestamp = _timestamp(consumed.timestamp)
        role = _enum(consumed.role, ExchangeRateConsumptionRole)
        key = (evidence_id, base, quote)
        expected_role = (
            ExchangeRateConsumptionRole.direct
            if quote == valuation.currency
            else ExchangeRateConsumptionRole.pivot_target
            if base == valuation.currency
            else ExchangeRateConsumptionRole.pivot_source
        )
        if key in historical_keys or base == quote or role is not expected_role:
            raise _fail()
        historical_keys.add(key)
        historical_rate_ids.add(rate_id)
        historical_entries.append(
            (
                (evidence_id, base, quote, rate_id),
                CanonicalJsonObject(
                    (
                        ("rateId", rate_id),
                        ("evidenceId", evidence_id),
                        ("from", base),
                        ("to", quote),
                        ("rate", _decimal_string(exact_historical_rate, RATE)),
                        ("timestamp", timestamp.isoformat(timespec="milliseconds")),
                        ("role", role.value),
                    )
                ),
            )
        )
    if historical_rates and historical_rate_ids != set(historical_ids):
        raise _fail()
    uses_pivot = any(
        rate.roles != (ExchangeRateConsumptionRole.direct,) for rate in valuation.exchange_rates
    ) or any(rate.role is not ExchangeRateConsumptionRole.direct for rate in historical_rates)
    snapshot_entries = tuple(item for _, item in sorted(rates))
    if not uses_pivot:
        snapshot_entries = tuple(
            CanonicalJsonObject(tuple(entry for entry in item.entries if entry[0] != "roles"))
            for item in snapshot_entries
        )
    return CanonicalJsonObject(
        (
            ("version", 2 if uses_pivot else 1),
            ("snapshotRates", snapshot_entries),
            ("historicalRateIds", historical_ids),
            *(
                (
                    (
                        "historicalRates",
                        tuple(item for _, item in sorted(historical_entries)),
                    ),
                )
                if uses_pivot
                else ()
            ),
        ),
    )


def _items(
    valuation: ExpectedAccountSnapshotValuation,
    *,
    snapshot_id: str,
    created_at: datetime,
) -> tuple[ExpectedAccountSnapshotItemRow, ...]:
    rows: list[ExpectedAccountSnapshotItemRow] = []
    listing_ids: set[str] = set()
    values: list[Decimal] = []
    costs: list[Decimal] = []
    allocations: list[Decimal] = []
    for item in valuation.items:
        if not isinstance(item, ExpectedAccountSnapshotItem):
            raise _fail()
        asset_id = _nonblank(item.asset_id)
        listing_id = _nonblank(item.listing_id)
        symbol = _currency(item.symbol)
        price_currency = _currency(item.price_currency)
        value_currency = _currency(item.value_currency)
        price_source = _enum(item.price_source, PriceSource)
        price_timestamp = _timestamp(item.price_timestamp)
        quantity = _exact(item.quantity, QUANTITY, positive=True)
        price_per_unit = _exact(item.price_per_unit, QUANTITY, positive=True)
        native_value = _exact(item.native_value, QUANTITY, positive=True)
        value = _exact(item.value, MONEY, positive=True)
        cost_values = (
            item.cost_basis,
            item.cost_currency,
            item.native_cost_basis,
            item.native_cost_currency,
            item.native_cost_basis_by_currency,
            item.average_buy_price,
            item.average_buy_price_currency,
        )
        cost_complete = all(cost is not None for cost in cost_values)
        if not cost_complete and any(cost is not None for cost in cost_values):
            raise _fail()
        cost_currency: str | None = None
        native_cost_currency: str | None = None
        native_cost_basis: Decimal | None = None
        average_buy_price: Decimal | None = None
        average_buy_price_currency: str | None = None
        native_cost_breakdown: CanonicalJsonObject | None = None
        cost_basis: Decimal | None = None
        component_entries: list[tuple[str, object]] = []
        component_currencies: set[str] = set()
        if cost_complete:
            cost_currency = _currency(item.cost_currency)
            native_cost_currency = _currency(item.native_cost_currency)
            native_cost_basis = _exact(item.native_cost_basis, QUANTITY, positive=True)
            average_buy_price = _exact(item.average_buy_price, QUANTITY, positive=True)
            average_buy_price_currency = _currency(item.average_buy_price_currency)
            if not isinstance(item.native_cost_basis_by_currency, tuple):
                raise _fail()
            for component in item.native_cost_basis_by_currency:
                if not isinstance(component, CurrencyAmount):
                    raise _fail()
                component_currency = _currency(component.currency)
                component_amount = _exact(component.amount, QUANTITY, positive=True)
                if component_currency in component_currencies:
                    raise _fail()
                component_currencies.add(component_currency)
                component_entries.append(
                    (component_currency, _decimal_string(component_amount, QUANTITY))
                )
            if not component_entries or tuple(
                currency for currency, _ in component_entries
            ) != tuple(sorted(component_currencies)):
                raise _fail()
            native_cost_breakdown = CanonicalJsonObject(tuple(component_entries))
            cost_basis = _exact(item.cost_basis, MONEY, positive=True)
        allocation_pct = _exact(item.allocation_pct, PERCENTAGE, positive=True)
        # The price/value pair and average/cost pair are separately coherent;
        # their native currencies need not be equal.
        if (
            listing_id in listing_ids
            or price_timestamp > valuation.timestamp
            or price_currency != value_currency
            or _calculated("multiply", quantity, price_per_unit, QUANTITY) != native_value
            or (cost_complete and cost_currency != valuation.currency)
            or (
                cost_complete
                and len(component_entries) == 1
                and (
                    component_entries[0][0] != native_cost_currency
                    or not isinstance(item.native_cost_basis_by_currency, tuple)
                    or item.native_cost_basis_by_currency[0].amount != native_cost_basis
                )
            )
            or (
                cost_complete
                and len(component_entries) > 1
                and (native_cost_currency != cost_currency or native_cost_basis != cost_basis)
            )
        ):
            raise _fail()
        listing_ids.add(listing_id)
        values.append(value)
        if cost_basis is not None:
            costs.append(cost_basis)
        allocations.append(allocation_pct)
        rows.append(
            ExpectedAccountSnapshotItemRow(
                id=_item_id(snapshot_id, listing_id),
                snapshot_id=snapshot_id,
                asset_id=asset_id,
                listing_id=listing_id,
                symbol=symbol,
                quantity=quantity,
                price_per_unit=price_per_unit,
                price_currency=price_currency,
                price_source=price_source,
                price_timestamp=price_timestamp,
                value=value,
                cost_basis=cost_basis,
                cost_currency=cost_currency,
                allocation_pct=allocation_pct,
                created_at=created_at,
                native_value=native_value,
                value_currency=value_currency,
                native_cost_basis=native_cost_basis,
                native_cost_currency=native_cost_currency,
                native_cost_basis_by_currency=native_cost_breakdown,
                average_buy_price=average_buy_price,
                average_buy_price_currency=average_buy_price_currency,
            )
        )
    if rows:
        if (
            _sum(tuple(values), MONEY) != valuation.investment_value
            or (
                valuation.investment_cost_basis is not None
                and (
                    len(costs) != len(rows)
                    or _sum(tuple(costs), MONEY) != valuation.investment_cost_basis
                )
            )
            or (valuation.investment_cost_basis is None and len(costs) == len(rows))
            or _sum(tuple(allocations), PERCENTAGE) != Decimal(100)
        ):
            raise _fail()
    elif valuation.investment_value != 0 or valuation.investment_cost_basis != 0:
        raise _fail()
    return tuple(sorted(rows, key=lambda row: (row.listing_id, row.id)))


def _liability_audit(
    evidence: CompleteAccountSnapshotEvidence,
    *,
    valuation: ExpectedAccountSnapshotValuation,
    items: tuple[ExpectedAccountSnapshotItemRow, ...],
    price_ids: tuple[str, ...],
    snapshot_rate_ids: tuple[str, ...],
    historical_rate_ids: tuple[str, ...],
    metrics: tuple[tuple[Decimal | None, CanonicalJsonObject | None], ...],
    liability_breakdown: CanonicalJsonObject,
) -> tuple[str | None, datetime | None, LiabilityBalanceSource | None]:
    balance_id = evidence.selected_liability_balance_id
    effective_at = evidence.selected_liability_effective_at
    source = evidence.selected_liability_source
    values = (balance_id, effective_at, source)
    if all(value is None for value in values):
        if (
            valuation.liabilities_value != 0
            or valuation.liabilities_value_by_currency
            or liability_breakdown != CanonicalJsonObject(())
        ):
            raise _fail()
        return None, None, None
    if any(value is None for value in values):
        raise _fail()
    selected_id = _nonblank(balance_id)
    selected_at = _timestamp(effective_at)
    selected_source = _enum(source, LiabilityBalanceSource)
    native_breakdown = valuation.liabilities_value_by_currency
    if (
        not isinstance(native_breakdown, tuple)
        or len(native_breakdown) != 1
        or not isinstance(native_breakdown[0], CurrencyAmount)
    ):
        raise _fail()
    native_currency = _currency(native_breakdown[0].currency)
    native_amount = _exact(native_breakdown[0].amount, MONEY, nonnegative=True)
    if liability_breakdown != CanonicalJsonObject(
        ((native_currency, _decimal_string(native_amount, MONEY)),)
    ):
        raise _fail()

    if native_currency == valuation.currency:
        valid_conversion = (
            not valuation.exchange_rates
            and not snapshot_rate_ids
            and native_amount == valuation.liabilities_value
        )
    else:
        rates: dict[tuple[str, str], Decimal] = {}
        role_by_pair: dict[
            tuple[str, str],
            tuple[ExchangeRateConsumptionRole, ...],
        ] = {}
        for rate in valuation.exchange_rates:
            if not isinstance(rate, ConsumedExchangeRate):
                raise _fail()
            pair = (_currency(rate.base_currency), _currency(rate.quote_currency))
            if pair in rates:
                raise _fail()
            rates[pair] = _exact(rate.rate, RATE, positive=True)
            role_by_pair[pair] = rate.roles
        try:
            converted, legs = convert_currency_amount(
                native_amount,
                base_currency=native_currency,
                output_currency=valuation.currency,
                rates=rates,
                numeric=MONEY,
            )
        except ValueError as exc:
            raise _fail() from exc
        valid_conversion = (
            snapshot_rate_ids == tuple(sorted(rate.rate_id for rate in valuation.exchange_rates))
            and converted == valuation.liabilities_value
            and role_by_pair
            == {(leg.base_currency, leg.quote_currency): (leg.role,) for leg in legs}
        )
    if (
        selected_at > valuation.timestamp
        or items
        or price_ids
        or historical_rate_ids
        or valuation.cash_value != 0
        or valuation.investment_value != 0
        or valuation.investment_cost_basis != 0
        or valuation.total_value != -valuation.liabilities_value
        or not valid_conversion
        or any(value != 0 or breakdown != CanonicalJsonObject(()) for value, breakdown in metrics)
    ):
        raise _fail()
    return selected_id, selected_at, selected_source


def build_account_snapshot_persistence_projection(
    evidence: CompleteAccountSnapshotEvidence,
    metadata: AccountSnapshotPersistenceMetadata,
) -> ExpectedAccountSnapshotPersistence:
    """Map exact 5I-B evidence to complete immutable physical row plans."""

    try:
        if not isinstance(evidence, CompleteAccountSnapshotEvidence) or not isinstance(
            metadata, AccountSnapshotPersistenceMetadata
        ):
            raise _fail()
        valuation = evidence.valuation
        if not isinstance(valuation, ExpectedAccountSnapshotValuation):
            raise _fail()
        account_id = _nonblank(valuation.account_id)
        timestamp = _timestamp(valuation.timestamp)
        granularity = _enum(valuation.granularity, SnapshotGranularity)
        source = _enum(valuation.source, SnapshotSource)
        currency = _currency(valuation.currency)
        calculated_at = _timestamp(metadata.calculated_at)
        created_at = _timestamp(metadata.created_at)
        if (
            not isinstance(metadata.is_recalculated, bool)
            or metadata.is_recalculated is not (source is SnapshotSource.manual_recalculation)
            or not isinstance(valuation.calculation_version, int)
            or isinstance(valuation.calculation_version, bool)
            or not 0 < valuation.calculation_version <= _POSTGRES_INTEGER_MAX
        ):
            raise _fail()

        cash_value = _exact(valuation.cash_value, MONEY)
        investment_value = _exact(valuation.investment_value, MONEY, nonnegative=True)
        investment_cost_basis = (
            None
            if valuation.investment_cost_basis is None
            else _exact(
                valuation.investment_cost_basis,
                MONEY,
                nonnegative=True,
            )
        )
        liabilities_value = _exact(valuation.liabilities_value, MONEY, nonnegative=True)
        total_value = _exact(valuation.total_value, MONEY)
        if (
            _calculated(
                "subtract",
                _calculated("add", cash_value, investment_value, MONEY),
                liabilities_value,
                MONEY,
            )
            != total_value
        ):
            raise _fail()

        net_deposits, net_deposits_breakdown = _metric(
            evidence.net_deposits,
            output_currency=currency,
            unsupported_reason=(
                SnapshotMetricUnsupportedReason.external_cash_flow_classification_unavailable
            ),
        )
        realized_pnl, realized_pnl_breakdown = _metric(
            evidence.realized_pnl,
            output_currency=currency,
            unsupported_reason=SnapshotMetricUnsupportedReason.realized_pnl_evidence_unavailable,
        )
        unrealized_pnl, unrealized_pnl_breakdown = _metric(
            evidence.unrealized_pnl,
            output_currency=currency,
            allow_none_breakdown=True,
            unsupported_reason=SnapshotMetricUnsupportedReason.cost_basis_evidence_unavailable,
        )
        fees, fees_breakdown = _metric(
            evidence.fees,
            output_currency=currency,
            nonnegative=True,
        )
        taxes, taxes_breakdown = _metric(
            evidence.taxes,
            output_currency=currency,
            nonnegative=True,
        )
        if (
            (investment_cost_basis is None) != (unrealized_pnl is None)
            or (
                investment_cost_basis is not None
                and unrealized_pnl is not None
                and _calculated(
                    "subtract",
                    investment_value,
                    investment_cost_basis,
                    MONEY,
                )
                != unrealized_pnl
            )
            or (net_deposits is not None and net_deposits_breakdown is None)
            or (realized_pnl is not None and realized_pnl_breakdown is None)
            or fees is None
            or taxes is None
            or fees_breakdown is None
            or taxes_breakdown is None
        ):
            raise _fail()

        snapshot_price_ids = _stable_ids(
            evidence.selected_price_ids,
            expected_count=len(valuation.items),
        )
        snapshot_rate_ids = _stable_ids(evidence.selected_snapshot_exchange_rate_ids)
        historical_rate_ids = _stable_ids(evidence.selected_historical_exchange_rate_ids)
        exchange_rates = _exchange_rates(
            valuation,
            selected_snapshot_ids=snapshot_rate_ids,
            historical_ids=historical_rate_ids,
            historical_rates=evidence.consumed_historical_exchange_rates,
        )
        generation_id = _nonblank(metadata.generation_id)
        snapshot_id = _snapshot_id(valuation, generation_id)
        items = _items(
            valuation,
            snapshot_id=snapshot_id,
            created_at=created_at,
        )
        liability_breakdown = _breakdown(
            valuation.liabilities_value_by_currency,
            numeric=MONEY,
            converted_value=liabilities_value,
            output_currency=currency,
            nonnegative=True,
        )
        if liability_breakdown is None:
            raise _fail()
        liability_balance_id, liability_effective_at, liability_source = _liability_audit(
            evidence,
            valuation=valuation,
            items=items,
            price_ids=snapshot_price_ids,
            snapshot_rate_ids=snapshot_rate_ids,
            historical_rate_ids=historical_rate_ids,
            metrics=(
                (net_deposits, net_deposits_breakdown),
                (realized_pnl, realized_pnl_breakdown),
                (unrealized_pnl, unrealized_pnl_breakdown),
                (fees, fees_breakdown),
                (taxes, taxes_breakdown),
            ),
            liability_breakdown=liability_breakdown,
        )

        cash_breakdown = _breakdown(
            valuation.cash_value_by_currency,
            numeric=MONEY,
            converted_value=cash_value,
            output_currency=currency,
        )
        investment_breakdown = _breakdown(
            valuation.investment_value_by_currency,
            numeric=QUANTITY,
            converted_value=investment_value,
            output_currency=currency,
            nonnegative=True,
        )
        cost_breakdown = _breakdown(
            valuation.investment_cost_basis_by_currency,
            numeric=QUANTITY,
            converted_value=investment_cost_basis,
            output_currency=currency,
            allow_none=True,
            nonnegative=True,
        )
        if (
            cash_breakdown is None
            or investment_breakdown is None
            or (investment_cost_basis is None) != (cost_breakdown is None)
        ):
            raise _fail()

        snapshot = ExpectedAccountSnapshotRow(
            id=snapshot_id,
            account_id=account_id,
            timestamp=timestamp,
            granularity=granularity,
            source=source,
            currency=currency,
            cash_value=cash_value,
            investment_value=investment_value,
            investment_cost_basis=investment_cost_basis,
            liabilities_value=liabilities_value,
            total_value=total_value,
            is_recalculated=metadata.is_recalculated,
            calculated_at=calculated_at,
            calculation_version=valuation.calculation_version,
            created_at=created_at,
            net_deposits_value=net_deposits,
            realized_pnl_value=realized_pnl,
            unrealized_pnl_value=unrealized_pnl,
            fees_value=fees,
            taxes_value=taxes,
            cash_value_by_currency=cash_breakdown,
            investment_value_by_currency=investment_breakdown,
            investment_cost_basis_by_currency=cost_breakdown,
            liabilities_value_by_currency=liability_breakdown,
            net_deposits_by_currency=net_deposits_breakdown,
            realized_pnl_by_currency=realized_pnl_breakdown,
            unrealized_pnl_by_currency=unrealized_pnl_breakdown,
            fees_by_currency=fees_breakdown,
            taxes_by_currency=taxes_breakdown,
            exchange_rates=exchange_rates,
            generation_id=generation_id,
        )
        return ExpectedAccountSnapshotPersistence(
            snapshot=snapshot,
            items=items,
            audit=AccountSnapshotPersistenceAudit(
                selected_price_ids=snapshot_price_ids,
                selected_snapshot_exchange_rate_ids=snapshot_rate_ids,
                selected_historical_exchange_rate_ids=historical_rate_ids,
                selected_liability_balance_id=liability_balance_id,
                selected_liability_effective_at=liability_effective_at,
                selected_liability_source=liability_source,
            ),
        )
    except AccountSnapshotPersistenceProjectionError:
        raise
    except (InvalidOperation, OverflowError, TypeError, ValueError) as exc:
        raise _fail() from exc
