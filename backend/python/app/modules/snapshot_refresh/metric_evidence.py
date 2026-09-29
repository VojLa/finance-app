"""Pure historical financial-metric evidence for snapshot-series refreshes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.db.models.common import MONEY
from app.db.models.enums import (
    AccountType,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    TransactionClassification,
    TransactionType,
)
from app.modules.holdings.persistence_projection import HoldingPersistenceMovement
from app.modules.portfolio_history_rebuild.models import (
    InvestmentEventRoot,
    ReplayRoot,
    TransactionRoot,
)
from app.modules.portfolio_history_rebuild.ordering import root_timestamp
from app.modules.snapshots.account_projection import ExpectedAccountSnapshotValuation
from app.modules.snapshots.financial_metrics import (
    AccountSnapshotEvidenceStateError,
    ExactFinancialMetrics,
    HistoricalMetricEvidence,
    HistoricalMetricKind,
    SelectedHistoricalRate,
    build_financial_metrics,
    canonical_currency,
    canonical_timestamp,
    exact_money,
)
from app.shared.canonical_arithmetic import CanonicalArithmeticError, canonical_rounded


@dataclass(frozen=True, slots=True)
class HistoricalMetricEvidenceBuild:
    """Metric roots and legacy completeness flags through one exact timestamp."""

    historical_evidence: tuple[HistoricalMetricEvidence, ...]
    has_asset_transfer: bool
    has_missing_anycoin_realized_pnl: bool


@dataclass(frozen=True, slots=True)
class CompleteHistoricalMetricEvidence:
    """Canonical metric result plus the evidence-completeness facts that qualify it."""

    evidence: HistoricalMetricEvidenceBuild
    metrics: ExactFinancialMetrics


def _fail() -> AccountSnapshotEvidenceStateError:
    return AccountSnapshotEvidenceStateError()


def _identifier(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _asset_transfer_net_deposit(
    *,
    event: InvestmentEventRoot,
    movement: HoldingPersistenceMovement,
) -> HistoricalMetricEvidence | None:
    """Classify a valued external asset transfer with legacy snapshot semantics."""

    valuation = (movement.price_per_unit, movement.value_amount, movement.value_currency)
    if all(value is None for value in valuation):
        return None
    if any(value is None for value in valuation):
        raise _fail()
    assert movement.price_per_unit is not None
    assert movement.value_amount is not None
    assert movement.value_currency is not None
    try:
        amount = exact_money(canonical_rounded(movement.value_amount, MONEY))
    except CanonicalArithmeticError as exc:
        raise _fail() from exc
    if movement.price_per_unit <= 0 or amount <= 0:
        raise _fail()
    if movement.direction not in {MovementDirection.incoming, MovementDirection.outgoing}:
        raise _fail()
    return HistoricalMetricEvidence(
        evidence_id=f"transfer:{_identifier(movement.movement_id)}",
        timestamp=event.event_date,
        kind=HistoricalMetricKind.net_deposit,
        currency=canonical_currency(movement.value_currency),
        amount=(amount if movement.direction is MovementDirection.incoming else -amount),
    )


def _events_through(
    *,
    account_id: str,
    roots: tuple[ReplayRoot, ...],
    as_of: datetime,
) -> tuple[InvestmentEventRoot, ...]:
    if not isinstance(roots, tuple):
        raise _fail()
    events: list[InvestmentEventRoot] = []
    for root in roots:
        if not isinstance(root.eligible, bool):
            raise _fail()
        try:
            timestamp = root_timestamp(root)
        except ValueError as exc:
            raise _fail() from exc
        if timestamp > as_of or not root.eligible:
            continue
        if getattr(root, "account_id", None) != account_id:
            raise _fail()
        if isinstance(root, InvestmentEventRoot):
            events.append(root)
    return tuple(events)


def build_historical_metric_evidence(
    *,
    account_id: str,
    account_type: AccountType,
    roots: tuple[ReplayRoot, ...],
    as_of: datetime,
) -> HistoricalMetricEvidenceBuild:
    """Derive stable metric evidence from frozen roots without I/O.

    The retained flags intentionally match the legacy snapshot evidence service:
    an unvalued asset transfer makes external cash-flow and realized-P/L metrics
    unsupported, while a qualifying AnyCoin disposal without realized P/L makes
    only realized P/L unsupported.
    """

    canonical_account_id = _identifier(account_id)
    if not isinstance(account_type, AccountType):
        raise _fail()
    canonical_as_of = canonical_timestamp(as_of)
    events = _events_through(
        account_id=canonical_account_id,
        roots=roots,
        as_of=canonical_as_of,
    )
    event_by_id: dict[str, InvestmentEventRoot] = {}
    grouped: dict[str, list[HoldingPersistenceMovement]] = {}
    for event in events:
        event_id = _identifier(event.event_id)
        if (
            event_id in event_by_id
            or event.account_id != canonical_account_id
            or canonical_timestamp(event.event_date) > canonical_as_of
            or (event.realized_pnl is None) != (event.realized_pnl_currency is None)
            or (event.source is not None and not isinstance(event.source, ImportSource))
        ):
            raise _fail()
        event_by_id[event_id] = event
        grouped[event_id] = []

    metrics: list[HistoricalMetricEvidence] = []
    if account_type in {
        AccountType.broker,
        AccountType.exchange,
        AccountType.crypto_wallet,
    }:
        for root in roots:
            if not isinstance(root.eligible, bool):
                raise _fail()
            if (
                not isinstance(root, TransactionRoot)
                or root.timestamp > canonical_as_of
                or not root.eligible
            ):
                continue
            amount = exact_money(root.amount)
            supported_cash_flow = (
                (
                    root.transaction_type is TransactionType.transfer
                    and root.classification is TransactionClassification.investment_transfer
                )
                or (
                    root.transaction_type is TransactionType.income
                    and root.classification is TransactionClassification.real_income
                    and amount > 0
                )
                or (
                    root.transaction_type is TransactionType.expense
                    and root.classification is TransactionClassification.real_expense
                    and amount < 0
                )
            )
            if (
                root.account_id != canonical_account_id
                or canonical_timestamp(root.timestamp) > canonical_as_of
                or not supported_cash_flow
                or amount == 0
            ):
                raise _fail()
            metrics.append(
                HistoricalMetricEvidence(
                    evidence_id=f"transaction:{_identifier(root.transaction_id)}",
                    timestamp=root.timestamp,
                    kind=HistoricalMetricKind.net_deposit,
                    currency=canonical_currency(root.currency),
                    amount=amount,
                )
            )
    movement_ids: set[str] = set()
    for event in events:
        for movement in event.movements:
            movement_id = _identifier(movement.movement_id)
            if (
                movement_id in movement_ids
                or movement.event_id != event.event_id
                or movement.account_id != canonical_account_id
                or movement.quantity <= 0
            ):
                raise _fail()
            movement_ids.add(movement_id)
            grouped[event.event_id].append(movement)
            if movement.kind not in {
                InvestmentMovementKind.asset,
                InvestmentMovementKind.cash,
                InvestmentMovementKind.fee,
                InvestmentMovementKind.tax,
            }:
                raise _fail()
            if movement.kind is InvestmentMovementKind.asset:
                continue
            currency = canonical_currency(movement.currency)
            amount = exact_money(movement.quantity)
            if movement.value_amount is not None and (
                exact_money(movement.value_amount) != amount
                or canonical_currency(movement.value_currency) != currency
            ):
                raise _fail()
            if movement.kind in {InvestmentMovementKind.fee, InvestmentMovementKind.tax}:
                if movement.direction is not MovementDirection.outgoing:
                    raise _fail()
                metrics.append(
                    HistoricalMetricEvidence(
                        evidence_id=f"movement:{movement_id}",
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
                expected_direction = (
                    MovementDirection.incoming
                    if event.event_type is InvestmentEventType.cash_deposit
                    else MovementDirection.outgoing
                )
                if movement.direction is not expected_direction:
                    raise _fail()
                metrics.append(
                    HistoricalMetricEvidence(
                        evidence_id=f"deposit:{movement_id}",
                        timestamp=event.event_date,
                        kind=HistoricalMetricKind.net_deposit,
                        currency=currency,
                        amount=(
                            amount if expected_direction is MovementDirection.incoming else -amount
                        ),
                    )
                )

    has_asset_transfer = False
    has_missing_anycoin_realized_pnl = False
    for event in events:
        event_movements = grouped[event.event_id]
        assets = [
            movement
            for movement in event_movements
            if movement.kind is InvestmentMovementKind.asset
        ]
        cash_movements = [
            movement for movement in event_movements if movement.kind is InvestmentMovementKind.cash
        ]
        fees = [
            movement for movement in event_movements if movement.kind is InvestmentMovementKind.fee
        ]
        taxes = [
            movement for movement in event_movements if movement.kind is InvestmentMovementKind.tax
        ]
        if not event_movements or len(fees) > 1 or len(taxes) > 1:
            raise _fail()
        if event.event_type is InvestmentEventType.trade:
            if (
                len(assets) != 1
                or len(cash_movements) != 1
                or assets[0].direction is cash_movements[0].direction
            ):
                raise _fail()
        elif event.event_type in {
            InvestmentEventType.cash_deposit,
            InvestmentEventType.cash_withdrawal,
            InvestmentEventType.interest,
            InvestmentEventType.dividend,
        }:
            if assets or len(cash_movements) != 1:
                raise _fail()
        elif event.event_type is InvestmentEventType.currency_conversion:
            if (
                assets
                or len(cash_movements) != 2
                or {movement.direction for movement in cash_movements}
                != {MovementDirection.incoming, MovementDirection.outgoing}
            ):
                raise _fail()
        elif event.event_type is InvestmentEventType.fee:
            if assets or cash_movements or len(fees) != 1:
                raise _fail()
        elif event.event_type is not InvestmentEventType.asset_transfer:
            raise _fail()

        if event.event_type is InvestmentEventType.asset_transfer:
            if len(assets) != 1 or cash_movements or fees or taxes:
                raise _fail()
            transfer_metric = _asset_transfer_net_deposit(event=event, movement=assets[0])
            if transfer_metric is None:
                has_asset_transfer = True
            else:
                metrics.append(transfer_metric)

        if event.realized_pnl is not None:
            if (
                event.event_type is not InvestmentEventType.trade
                or len(assets) != 1
                or assets[0].direction is not MovementDirection.outgoing
            ):
                raise _fail()
            try:
                amount = exact_money(canonical_rounded(event.realized_pnl, MONEY))
            except CanonicalArithmeticError as exc:
                raise _fail() from exc
            metrics.append(
                HistoricalMetricEvidence(
                    evidence_id=f"realized:{event.event_id}",
                    timestamp=event.event_date,
                    kind=HistoricalMetricKind.realized_pnl,
                    currency=canonical_currency(event.realized_pnl_currency),
                    amount=amount,
                )
            )
        elif (
            event.source is ImportSource.anycoin
            and event.event_type is InvestmentEventType.trade
            and len(assets) == 1
            and assets[0].direction is MovementDirection.outgoing
        ):
            has_missing_anycoin_realized_pnl = True

    return HistoricalMetricEvidenceBuild(
        historical_evidence=tuple(
            sorted(metrics, key=lambda item: (item.timestamp, item.evidence_id))
        ),
        has_asset_transfer=has_asset_transfer,
        has_missing_anycoin_realized_pnl=has_missing_anycoin_realized_pnl,
    )


def build_complete_historical_metric_evidence(
    *,
    account_id: str,
    account_type: AccountType,
    roots: tuple[ReplayRoot, ...],
    as_of: datetime,
    valuation: ExpectedAccountSnapshotValuation,
    historical_rates: tuple[SelectedHistoricalRate, ...],
) -> CompleteHistoricalMetricEvidence:
    """Call the canonical metric calculator using frozen-root evidence only."""

    canonical_account_id = _identifier(account_id)
    if not isinstance(valuation, ExpectedAccountSnapshotValuation) or (
        valuation.account_id != canonical_account_id
    ):
        raise _fail()
    evidence = build_historical_metric_evidence(
        account_id=canonical_account_id,
        account_type=account_type,
        roots=roots,
        as_of=as_of,
    )
    return CompleteHistoricalMetricEvidence(
        evidence=evidence,
        metrics=build_financial_metrics(
            valuation=valuation,
            historical_evidence=evidence.historical_evidence,
            historical_rates=historical_rates,
        ),
    )


__all__ = [
    "CompleteHistoricalMetricEvidence",
    "HistoricalMetricEvidenceBuild",
    "build_complete_historical_metric_evidence",
    "build_historical_metric_evidence",
]
