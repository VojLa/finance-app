"""Pure canonical deltas applied to an immutable daily snapshot state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext

from app.db.models.common import MONEY, QUANTITY, TIMESTAMP
from app.db.models.enums import (
    AssetType,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    TransactionClassification,
    TransactionType,
)
from app.modules.holdings.persistence_projection import (
    ExpectedPersistedHoldingPlan,
    HoldingPersistenceEvent,
    HoldingPersistenceMovement,
    HoldingPersistenceProjection,
    build_holding_delta_projection,
)
from app.modules.portfolio_snapshot.models import (
    PortfolioCurrencyAmount,
    PortfolioPositionView,
)
from app.modules.snapshots.financial_metrics import (
    HistoricalMetricEvidence,
    HistoricalMetricKind,
)
from app.shared.canonical_arithmetic import CanonicalArithmeticError, canonical_rounded

_ERROR = "Canonical forward changes cannot produce an exact current state."
_TRANSFER_CLASSIFICATIONS = {
    TransactionClassification.internal_transfer,
    TransactionClassification.investment_transfer,
    TransactionClassification.cash_exchange,
    TransactionClassification.credit_card_payment,
    TransactionClassification.loan_repayment,
}


class CurrentDeltaProjectionError(ValueError):
    def __init__(self) -> None:
        super().__init__(_ERROR)


@dataclass(frozen=True, slots=True)
class CurrentTransaction:
    transaction_id: str
    account_id: str
    timestamp: datetime
    amount: Decimal
    currency: str
    transaction_type: TransactionType
    classification: TransactionClassification | None


@dataclass(frozen=True, slots=True)
class CurrentInvestmentEvent:
    event: HoldingPersistenceEvent
    realized_pnl: Decimal | None
    realized_pnl_currency: str | None


@dataclass(frozen=True, slots=True)
class CurrentInvestmentDelta:
    holdings: HoldingPersistenceProjection
    cash_by_currency: tuple[PortfolioCurrencyAmount, ...]
    historical_metrics: tuple[HistoricalMetricEvidence, ...]
    has_asset_transfer: bool


@dataclass(frozen=True, slots=True)
class CurrentInvestmentTransactionDelta:
    cash_by_currency: tuple[PortfolioCurrencyAmount, ...]
    historical_metrics: tuple[HistoricalMetricEvidence, ...]


def _fail() -> CurrentDeltaProjectionError:
    return CurrentDeltaProjectionError()


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
        raise _fail()
    return value


def _currency(value: object) -> str:
    result = _text(value)
    if len(result) != 3 or not result.isascii() or not result.isalpha() or result != result.upper():
        raise _fail()
    return result


def _timestamp(value: object) -> datetime:
    precision = TIMESTAMP.precision
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or precision is None
        or value.microsecond % (10 ** (6 - precision))
    ):
        raise _fail()
    return value


def _exact(value: object, *, quantity: bool = False, positive: bool = False) -> Decimal:
    numeric = QUANTITY if quantity else MONEY
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail()
    precision, scale = numeric.precision, numeric.scale
    if precision is None or scale is None:
        raise RuntimeError("Canonical numeric type must define precision and scale.")
    try:
        with localcontext() as context:
            context.prec = 112
            scaled = value.quantize(Decimal(1).scaleb(-scale))
    except InvalidOperation as exc:
        raise _fail() from exc
    if (
        value != scaled
        or abs(value) >= Decimal(10) ** (precision - scale)
        or (positive and value <= 0)
    ):
        raise _fail()
    return value


def _add(left: Decimal, right: Decimal) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 112
            return _exact(left + right)
    except (InvalidOperation, OverflowError) as exc:
        raise _fail() from exc


def _breakdown_map(
    values: tuple[PortfolioCurrencyAmount, ...],
) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for item in values:
        if (
            not isinstance(item, PortfolioCurrencyAmount)
            or item.currency in result
            or _currency(item.currency) != item.currency
        ):
            raise _fail()
        result[item.currency] = _exact(item.amount)
    if values != tuple(sorted(values, key=lambda item: item.currency)):
        raise _fail()
    return result


def _breakdown(values: dict[str, Decimal]) -> tuple[PortfolioCurrencyAmount, ...]:
    return tuple(
        PortfolioCurrencyAmount(currency=currency, amount=_exact(amount))
        for currency, amount in sorted(values.items())
    )


def _asset_transfer_net_deposit(
    *,
    event: HoldingPersistenceEvent,
    movement: HoldingPersistenceMovement,
) -> HistoricalMetricEvidence | None:
    price_per_unit = movement.price_per_unit
    value_amount = movement.value_amount
    value_currency = movement.value_currency
    valuation = (price_per_unit, value_amount, value_currency)
    if all(value is None for value in valuation):
        return None
    if any(value is None for value in valuation):
        raise _fail()
    assert price_per_unit is not None
    assert value_amount is not None
    assert value_currency is not None
    try:
        amount = _exact(canonical_rounded(value_amount, MONEY), positive=True)
    except CanonicalArithmeticError as exc:
        raise _fail() from exc
    _exact(price_per_unit, quantity=True, positive=True)
    direction = movement.direction
    if direction not in {MovementDirection.incoming, MovementDirection.outgoing}:
        raise _fail()
    return HistoricalMetricEvidence(
        evidence_id=f"transfer:{_text(movement.movement_id)}",
        timestamp=event.event_date,
        kind=HistoricalMetricKind.net_deposit,
        currency=_currency(value_currency),
        amount=amount if direction is MovementDirection.incoming else -amount,
    )


def add_currency_breakdowns(
    baseline: tuple[PortfolioCurrencyAmount, ...],
    delta: tuple[PortfolioCurrencyAmount, ...],
) -> tuple[PortfolioCurrencyAmount, ...]:
    values = _breakdown_map(baseline)
    for currency, amount in _breakdown_map(delta).items():
        values[currency] = _add(values.get(currency, Decimal("0.000000")), amount)
    return _breakdown(values)


def baseline_holding_seeds(
    *,
    account_id: str,
    positions: tuple[PortfolioPositionView, ...],
) -> tuple[ExpectedPersistedHoldingPlan, ...]:
    seeds: list[ExpectedPersistedHoldingPlan] = []
    listings: set[str] = set()
    for position in positions:
        if (
            not isinstance(position, PortfolioPositionView)
            or position.listing_id in listings
            or position.quantity <= 0
        ):
            raise _fail()
        listings.add(position.listing_id)
        quantity = _exact(position.quantity, quantity=True, positive=True)
        cost_values = (
            position.native_cost_basis,
            position.average_buy_price,
            position.average_buy_price_currency,
            position.native_cost_basis_by_currency,
            position.native_cost_currency,
            position.cost_basis,
            position.cost_currency,
            position.unrealized_pnl,
        )
        cost_complete = all(value is not None for value in cost_values)
        if not cost_complete and any(value is not None for value in cost_values):
            raise _fail()
        quote_currency = _currency(position.price_currency)
        average: Decimal | None = None
        components: tuple[tuple[str, Decimal], ...] | None = None
        if cost_complete:
            native_cost = _exact(position.native_cost_basis, quantity=True, positive=True)
            average = _exact(position.average_buy_price, quantity=True, positive=True)
            quote_currency = _currency(position.average_buy_price_currency)
            if not isinstance(position.native_cost_basis_by_currency, tuple):
                raise _fail()
            components = tuple(
                (_currency(item.currency), _exact(item.amount, quantity=True, positive=True))
                for item in position.native_cost_basis_by_currency
            )
            if not components or len({currency for currency, _ in components}) != len(components):
                raise _fail()
            if tuple(currency for currency, _ in components) != tuple(
                sorted(currency for currency, _ in components)
            ):
                raise _fail()
            if len(components) == 1:
                if components[0] != (_currency(position.native_cost_currency), native_cost):
                    raise _fail()
            elif _currency(position.native_cost_currency) != _currency(
                position.cost_currency
            ) or native_cost != _exact(position.cost_basis, quantity=True, positive=True):
                raise _fail()
        seeds.append(
            ExpectedPersistedHoldingPlan(
                account_id=_text(account_id),
                asset_id=_text(position.asset_id),
                listing_id=_text(position.listing_id),
                symbol=_text(position.symbol),
                name=_text(position.name),
                asset_type=AssetType(position.asset_type.value),
                quantity=quantity,
                avg_buy_price=average,
                currency=quote_currency,
                current_price=None,
                current_value=None,
                unrealized_pnl=None,
                realized_pnl=None,
                cost_basis_by_currency=components,
            )
        )
    return tuple(sorted(seeds, key=lambda item: item.listing_id))


def apply_cash_transactions(
    *,
    account_id: str,
    baseline: tuple[PortfolioCurrencyAmount, ...],
    transactions: tuple[CurrentTransaction, ...],
) -> tuple[PortfolioCurrencyAmount, ...]:
    values = _breakdown_map(baseline)
    transaction_ids: set[str] = set()
    for transaction in sorted(transactions, key=lambda item: (item.timestamp, item.transaction_id)):
        if (
            not isinstance(transaction, CurrentTransaction)
            or _text(transaction.account_id) != account_id
            or _text(transaction.transaction_id) in transaction_ids
            or not isinstance(transaction.transaction_type, TransactionType)
        ):
            raise _fail()
        transaction_ids.add(transaction.transaction_id)
        _timestamp(transaction.timestamp)
        amount = _exact(transaction.amount)
        currency = _currency(transaction.currency)
        if (
            amount == 0
            or (transaction.transaction_type is TransactionType.income and amount < 0)
            or (transaction.transaction_type is TransactionType.expense and amount > 0)
            or (
                transaction.transaction_type is TransactionType.transfer
                and transaction.classification not in _TRANSFER_CLASSIFICATIONS
            )
        ):
            raise _fail()
        values[currency] = _add(values.get(currency, Decimal("0.000000")), amount)
    return _breakdown(values)


def apply_investment_cash_transactions(
    *,
    account_id: str,
    baseline: tuple[PortfolioCurrencyAmount, ...],
    transactions: tuple[CurrentTransaction, ...],
) -> CurrentInvestmentTransactionDelta:
    """Apply explicit external investment cash flows without changing investment P/L metrics."""
    values = _breakdown_map(baseline)
    transaction_ids: set[str] = set()
    metrics: list[HistoricalMetricEvidence] = []
    for transaction in sorted(transactions, key=lambda item: (item.timestamp, item.transaction_id)):
        if (
            not isinstance(transaction, CurrentTransaction)
            or _text(transaction.account_id) != account_id
            or _text(transaction.transaction_id) in transaction_ids
            or transaction.transaction_type is not TransactionType.transfer
            or transaction.classification is not TransactionClassification.investment_transfer
        ):
            raise _fail()
        transaction_ids.add(transaction.transaction_id)
        timestamp = _timestamp(transaction.timestamp)
        amount = _exact(transaction.amount)
        currency = _currency(transaction.currency)
        if amount == 0:
            raise _fail()
        values[currency] = _add(values.get(currency, Decimal("0.000000")), amount)
        metrics.append(
            HistoricalMetricEvidence(
                evidence_id=f"transaction:{transaction.transaction_id}",
                timestamp=timestamp,
                kind=HistoricalMetricKind.net_deposit,
                currency=currency,
                amount=amount,
            )
        )
    return CurrentInvestmentTransactionDelta(
        cash_by_currency=_breakdown(values),
        historical_metrics=tuple(metrics),
    )


def apply_investment_events(
    *,
    account_id: str,
    baseline_positions: tuple[PortfolioPositionView, ...],
    baseline_cash: tuple[PortfolioCurrencyAmount, ...],
    events: tuple[CurrentInvestmentEvent, ...],
) -> CurrentInvestmentDelta:
    canonical_events = tuple(item.event for item in events)
    holdings = build_holding_delta_projection(
        account_id=account_id,
        baseline_holdings=baseline_holding_seeds(
            account_id=account_id,
            positions=baseline_positions,
        ),
        events=canonical_events,
    )
    cash = _breakdown_map(baseline_cash)
    metrics: list[HistoricalMetricEvidence] = []
    event_ids: set[str] = set()
    has_asset_transfer = False
    for current in sorted(events, key=lambda item: (item.event.event_date, item.event.event_id)):
        if not isinstance(current, CurrentInvestmentEvent):
            raise _fail()
        event = current.event
        event_id = _text(event.event_id)
        if event_id in event_ids:
            raise _fail()
        event_ids.add(event_id)
        if (current.realized_pnl is None) != (current.realized_pnl_currency is None):
            raise _fail()
        for movement in event.movements:
            if movement.kind is InvestmentMovementKind.asset:
                continue
            currency = _currency(movement.currency)
            amount = _exact(movement.quantity, positive=True)
            signed = amount if movement.direction is MovementDirection.incoming else -amount
            cash[currency] = _add(cash.get(currency, Decimal("0.000000")), signed)
            if movement.kind in {InvestmentMovementKind.fee, InvestmentMovementKind.tax}:
                if movement.direction is not MovementDirection.outgoing:
                    raise _fail()
                metrics.append(
                    HistoricalMetricEvidence(
                        evidence_id=f"movement:{movement.movement_id}",
                        timestamp=event.event_date,
                        kind=(
                            HistoricalMetricKind.fee
                            if movement.kind is InvestmentMovementKind.fee
                            else HistoricalMetricKind.tax
                        ),
                        currency=currency,
                        amount=amount,
                    )
                )
            elif event.event_type in {
                InvestmentEventType.cash_deposit,
                InvestmentEventType.cash_withdrawal,
            }:
                expected = (
                    MovementDirection.incoming
                    if event.event_type is InvestmentEventType.cash_deposit
                    else MovementDirection.outgoing
                )
                if movement.direction is not expected:
                    raise _fail()
                metrics.append(
                    HistoricalMetricEvidence(
                        evidence_id=f"deposit:{movement.movement_id}",
                        timestamp=event.event_date,
                        kind=HistoricalMetricKind.net_deposit,
                        currency=currency,
                        amount=amount if expected is MovementDirection.incoming else -amount,
                    )
                )
        if event.event_type is InvestmentEventType.asset_transfer:
            assets = tuple(
                movement
                for movement in event.movements
                if movement.kind is InvestmentMovementKind.asset
            )
            if len(assets) != 1:
                raise _fail()
            transfer_metric = _asset_transfer_net_deposit(event=event, movement=assets[0])
            if transfer_metric is None:
                has_asset_transfer = True
            else:
                metrics.append(transfer_metric)
        if current.realized_pnl is not None:
            metrics.append(
                HistoricalMetricEvidence(
                    evidence_id=f"realized:{event_id}",
                    timestamp=event.event_date,
                    kind=HistoricalMetricKind.realized_pnl,
                    currency=_currency(current.realized_pnl_currency),
                    amount=_exact(canonical_rounded(current.realized_pnl, MONEY)),
                )
            )
    return CurrentInvestmentDelta(
        holdings=holdings,
        cash_by_currency=_breakdown(cash),
        historical_metrics=tuple(
            sorted(metrics, key=lambda item: (item.timestamp, item.evidence_id))
        ),
        has_asset_transfer=has_asset_transfer,
    )
