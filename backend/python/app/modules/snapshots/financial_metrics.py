"""Pure exact historical metrics for one account snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from enum import StrEnum

from app.db.models.common import MONEY, RATE, TIMESTAMP
from app.modules.snapshots.account_projection import (
    CurrencyAmount,
    ExpectedAccountSnapshotValuation,
)

_ERROR_MESSAGE = "Persisted evidence cannot produce a complete account snapshot."


class AccountSnapshotEvidenceStateError(ValueError):
    """Raised when persisted evidence is incomplete, ambiguous, or corrupt."""

    def __init__(self) -> None:
        super().__init__(_ERROR_MESSAGE)


class HistoricalMetricKind(StrEnum):
    net_deposit = "net_deposit"
    realized_pnl = "realized_pnl"
    fee = "fee"
    tax = "tax"


@dataclass(frozen=True, slots=True)
class HistoricalMetricEvidence:
    evidence_id: str
    timestamp: datetime
    kind: HistoricalMetricKind
    currency: str
    amount: Decimal


@dataclass(frozen=True, slots=True)
class SelectedHistoricalRate:
    rate_id: str
    evidence_id: str
    base_currency: str
    quote_currency: str
    rate: Decimal
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class ExactFinancialMetrics:
    net_deposits_value: Decimal
    realized_pnl_value: Decimal
    unrealized_pnl_value: Decimal
    fees_value: Decimal
    taxes_value: Decimal
    net_deposits_by_currency: tuple[CurrencyAmount, ...]
    realized_pnl_by_currency: tuple[CurrencyAmount, ...]
    unrealized_pnl_by_currency: tuple[CurrencyAmount, ...] | None
    fees_by_currency: tuple[CurrencyAmount, ...]
    taxes_by_currency: tuple[CurrencyAmount, ...]
    selected_historical_rate_ids: tuple[str, ...]


def _fail() -> AccountSnapshotEvidenceStateError:
    return AccountSnapshotEvidenceStateError()


def canonical_currency(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or value != value.upper():
        raise _fail()
    return value


def canonical_timestamp(value: object) -> datetime:
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


def exact_money(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail()
    precision, scale = MONEY.precision, MONEY.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical MONEY must define precision and scale.")
    try:
        with localcontext() as context:
            context.prec = max(precision * 4, 84)
            scaled = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise _fail() from exc
    if value != scaled or abs(value) >= Decimal(10) ** (precision - scale):
        raise _fail()
    return value


def exact_rate(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail()
    precision, scale = RATE.precision, RATE.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical RATE must define precision and scale.")
    try:
        with localcontext() as context:
            context.prec = max(precision * 4, 84)
            scaled = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise _fail() from exc
    if value != scaled or value <= 0 or abs(value) >= Decimal(10) ** (precision - scale):
        raise _fail()
    return value


def _calculated(left: Decimal, right: Decimal, *, multiply: bool) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 112
            result = left * right if multiply else left + right
    except (InvalidOperation, OverflowError) as exc:
        raise _fail() from exc
    return exact_money(result)


def _breakdown(values: dict[str, Decimal]) -> tuple[CurrencyAmount, ...]:
    return tuple(
        CurrencyAmount(currency=currency, amount=exact_money(amount))
        for currency, amount in sorted(values.items())
    )


def build_financial_metrics(
    *,
    valuation: ExpectedAccountSnapshotValuation,
    historical_evidence: tuple[HistoricalMetricEvidence, ...],
    historical_rates: tuple[SelectedHistoricalRate, ...],
) -> ExactFinancialMetrics:
    """Aggregate lifetime flows and current unrealized P/L without I/O."""

    if not isinstance(valuation, ExpectedAccountSnapshotValuation):
        raise _fail()
    output_currency = canonical_currency(valuation.currency)
    evidence_by_id: dict[str, HistoricalMetricEvidence] = {}
    for item in historical_evidence:
        if (
            not isinstance(item, HistoricalMetricEvidence)
            or not item.evidence_id
            or item.evidence_id != item.evidence_id.strip()
            or item.evidence_id in evidence_by_id
            or not isinstance(item.kind, HistoricalMetricKind)
        ):
            raise _fail()
        canonical_timestamp(item.timestamp)
        canonical_currency(item.currency)
        exact_money(item.amount)
        if item.kind in {HistoricalMetricKind.fee, HistoricalMetricKind.tax} and item.amount <= 0:
            raise _fail()
        evidence_by_id[item.evidence_id] = item

    rate_by_evidence: dict[str, SelectedHistoricalRate] = {}
    used_rate_ids: set[str] = set()
    for selected in historical_rates:
        if (
            not isinstance(selected, SelectedHistoricalRate)
            or not selected.rate_id
            or selected.rate_id != selected.rate_id.strip()
            or selected.evidence_id in rate_by_evidence
        ):
            raise _fail()
        metric_item = evidence_by_id.get(selected.evidence_id)
        if (
            metric_item is None
            or canonical_currency(selected.base_currency) != metric_item.currency
            or canonical_currency(selected.quote_currency) != output_currency
            or canonical_timestamp(selected.timestamp) > metric_item.timestamp
        ):
            raise _fail()
        exact_rate(selected.rate)
        rate_by_evidence[selected.evidence_id] = selected
        used_rate_ids.add(selected.rate_id)

    native: dict[HistoricalMetricKind, dict[str, Decimal]] = {
        kind: {} for kind in HistoricalMetricKind
    }
    converted: dict[HistoricalMetricKind, Decimal] = {
        kind: Decimal(0) for kind in HistoricalMetricKind
    }
    for item in sorted(historical_evidence, key=lambda value: (value.timestamp, value.evidence_id)):
        bucket = native[item.kind]
        bucket[item.currency] = _calculated(
            bucket.get(item.currency, Decimal(0)),
            item.amount,
            multiply=False,
        )
        if item.currency == output_currency:
            if item.evidence_id in rate_by_evidence:
                raise _fail()
            output_amount = item.amount
        else:
            selected_rate = rate_by_evidence.get(item.evidence_id)
            if selected_rate is None:
                raise _fail()
            output_amount = _calculated(item.amount, selected_rate.rate, multiply=True)
        converted[item.kind] = _calculated(
            converted[item.kind],
            output_amount,
            multiply=False,
        )
    if set(rate_by_evidence) != {
        item.evidence_id for item in historical_evidence if item.currency != output_currency
    }:
        raise _fail()

    unrealized = _calculated(
        valuation.investment_value,
        -valuation.investment_cost_basis,
        multiply=False,
    )
    native_unrealized: dict[str, Decimal] = {}
    native_available = True
    for valuation_item in valuation.items:
        if valuation_item.value_currency != valuation_item.native_cost_currency:
            native_available = False
            break
        native_unrealized[valuation_item.value_currency] = _calculated(
            native_unrealized.get(valuation_item.value_currency, Decimal(0)),
            _calculated(
                valuation_item.native_value,
                -valuation_item.native_cost_basis,
                multiply=False,
            ),
            multiply=False,
        )

    return ExactFinancialMetrics(
        net_deposits_value=converted[HistoricalMetricKind.net_deposit],
        realized_pnl_value=converted[HistoricalMetricKind.realized_pnl],
        unrealized_pnl_value=unrealized,
        fees_value=converted[HistoricalMetricKind.fee],
        taxes_value=converted[HistoricalMetricKind.tax],
        net_deposits_by_currency=_breakdown(native[HistoricalMetricKind.net_deposit]),
        realized_pnl_by_currency=_breakdown(native[HistoricalMetricKind.realized_pnl]),
        unrealized_pnl_by_currency=(_breakdown(native_unrealized) if native_available else None),
        fees_by_currency=_breakdown(native[HistoricalMetricKind.fee]),
        taxes_by_currency=_breakdown(native[HistoricalMetricKind.tax]),
        selected_historical_rate_ids=tuple(sorted(used_rate_ids)),
    )
