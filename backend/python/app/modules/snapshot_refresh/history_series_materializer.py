"""Pure adaptation of frozen history replay evidence into one snapshot series.

The history builder's valuation FX is selected at each representative timestamp.
Historical financial metrics, however, must retain their event-date FX selection.
That latter evidence is deliberately supplied separately here: it must never be
inferred from a valuation rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.modules.portfolio_history.builder.market import SelectedHistoricalPrice
from app.modules.portfolio_history_rebuild.models import AccountReplayState
from app.modules.portfolio_history_rebuild.repository import FrozenPortfolioReplayInput
from app.modules.snapshot_refresh.metric_evidence import (
    build_complete_historical_metric_evidence,
)
from app.modules.snapshot_refresh.series_executor import (
    ExecuteSnapshotSeriesCommand,
    SnapshotSeriesAccountEvidence,
    SnapshotSeriesPoint,
    SnapshotSeriesTarget,
)
from app.modules.snapshots.account_projection import (
    AccountSnapshotProjectionInput,
    AccountSnapshotProjectionStateError,
    CashBalanceEvidence,
    CurrencyAmount,
    LiabilityBalanceEvidence,
    SelectedExchangeRateEvidence,
    SelectedPriceEvidence,
    SnapshotHoldingEvidence,
    build_account_snapshot_projection,
)
from app.modules.snapshots.evidence_service import (
    CompleteAccountSnapshotEvidence,
    ExactSnapshotMetric,
    SnapshotMetricUnsupportedReason,
    UnsupportedSnapshotMetric,
)
from app.modules.snapshots.financial_metrics import (
    AccountSnapshotEvidenceStateError,
    SelectedHistoricalRate,
)

_SOURCE = SnapshotSource.holdings_recalculation
_GRANULARITY = SnapshotGranularity.minute


class SnapshotHistorySeriesMaterializationError(ValueError):
    """Frozen replay and market evidence cannot form one complete series."""


@dataclass(frozen=True, slots=True)
class FrozenHistorySeriesValuationRate:
    """One selected valuation-FX observation for one account/output coordinate."""

    account_id: str
    timestamp: datetime
    output_currency: str
    evidence: SelectedExchangeRateEvidence


@dataclass(frozen=True, slots=True)
class FrozenHistorySeriesMetricRate:
    """Event-date FX evidence for one historical metric and output currency.

    This is intentionally not derived from ``FrozenHistorySeriesValuationRate``:
    a snapshot valuation rate is selected as-of the representative timestamp,
    while this rate is selected as-of the underlying financial event.
    """

    account_id: str
    output_currency: str
    rate_id: str
    evidence_id: str
    base_currency: str
    quote_currency: str
    rate: Decimal
    event_at: datetime
    timestamp: datetime


@dataclass(frozen=True, slots=True)
class FrozenHistorySeriesPoint:
    """Replay states at one selected representative timestamp."""

    timestamp: datetime
    account_states: tuple[AccountReplayState, ...]


@dataclass(frozen=True, slots=True)
class HistorySnapshotSeriesMaterializationInput:
    """All frozen facts needed to create one complete snapshot-series command."""

    job_id: str
    replay_scope: FrozenPortfolioReplayInput
    targets: tuple[SnapshotSeriesTarget, ...]
    points: tuple[FrozenHistorySeriesPoint, ...]
    prices: tuple[SelectedHistoricalPrice, ...]
    valuation_rates: tuple[FrozenHistorySeriesValuationRate, ...]
    metric_rates: tuple[FrozenHistorySeriesMetricRate, ...]
    calculation_version: int
    calculated_at: datetime
    created_at: datetime
    causal_at: datetime | None = None


def _fail() -> SnapshotHistorySeriesMaterializationError:
    return SnapshotHistorySeriesMaterializationError(
        "Frozen history evidence cannot produce a complete snapshot series."
    )


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
        raise _fail()
    return value


def _currency(value: object) -> str:
    value = _text(value)
    if len(value) != 3 or not value.isascii() or not value.isalpha() or value != value.upper():
        raise _fail()
    return value


def _timestamp(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is not None or value.microsecond % 1_000:
        raise _fail()
    return value


def _minute_timestamp(value: object) -> datetime:
    timestamp = _timestamp(value)
    if timestamp.second or timestamp.microsecond:
        raise _fail()
    return timestamp


def _canonical_targets(value: object) -> tuple[SnapshotSeriesTarget, ...]:
    if not isinstance(value, tuple) or not value:
        raise _fail()
    by_user: dict[str, SnapshotSeriesTarget] = {}
    for target in value:
        if not isinstance(target, SnapshotSeriesTarget) or not isinstance(
            target.account_ids, tuple
        ):
            raise _fail()
        user_id = _text(target.user_id)
        account_ids = tuple(sorted(_text(account_id) for account_id in target.account_ids))
        if not account_ids or len(account_ids) != len(set(account_ids)) or user_id in by_user:
            raise _fail()
        by_user[user_id] = SnapshotSeriesTarget(
            user_id=user_id,
            output_currency=_currency(target.output_currency),
            account_ids=account_ids,
        )
    return tuple(by_user[user_id] for user_id in sorted(by_user))


def _states(
    point: FrozenHistorySeriesPoint,
    *,
    account_ids: set[str],
) -> dict[str, AccountReplayState]:
    if not isinstance(point, FrozenHistorySeriesPoint) or not isinstance(
        point.account_states, tuple
    ):
        raise _fail()
    result: dict[str, AccountReplayState] = {}
    for state in point.account_states:
        if not isinstance(state, AccountReplayState) or state.account_id in result:
            raise _fail()
        result[state.account_id] = state
    if set(result) != account_ids:
        raise _fail()
    return result


def _valuation(
    *,
    account_id: str,
    state: AccountReplayState,
    timestamp: datetime,
    output_currency: str,
    replay_scope: FrozenPortfolioReplayInput,
    prices: tuple[SelectedHistoricalPrice, ...],
    valuation_rates: tuple[FrozenHistorySeriesValuationRate, ...],
    calculation_version: int,
):
    account = next((item for item in replay_scope.accounts if item.account_id == account_id), None)
    if account is None:
        raise _fail()
    listings = {item.listing_id: item for item in account.listing_identities}
    holdings: list[SnapshotHoldingEvidence] = []
    for holding in state.holdings:
        listing = listings.get(holding.listing_id)
        if listing is None:
            raise _fail()
        holdings.append(
            SnapshotHoldingEvidence(
                holding_id=f"history-holding:{account_id}:{holding.listing_id}",
                account_id=account_id,
                asset_id=holding.asset_id,
                listing_id=holding.listing_id,
                listing_asset_id=listing.asset_id,
                symbol=holding.symbol,
                asset_type=holding.asset_type,
                quantity=holding.quantity,
                average_buy_price=holding.avg_buy_price,
                cost_currency=holding.currency,
                cost_basis_by_currency=(
                    None
                    if holding.cost_basis_by_currency is None
                    else tuple(
                        CurrencyAmount(currency=currency, amount=amount)
                        for currency, amount in holding.cost_basis_by_currency
                    )
                ),
            )
        )
    selected_prices = tuple(
        SelectedPriceEvidence(
            price_id=item.price_id,
            asset_id=item.observation.asset_id,
            listing_id=item.observation.listing_id,
            symbol=item.listing.symbol,
            price=item.observation.price,
            currency=item.observation.currency,
            source=item.observation.provider,
            timestamp=item.observation.observed_at,
        )
        for item in prices
        if item.account_id == account_id and item.through == timestamp
    )
    if any(item.timestamp > timestamp for item in selected_prices):
        raise _fail()
    selected_rates = tuple(
        item.evidence
        for item in valuation_rates
        if item.account_id == account_id
        and item.timestamp == timestamp
        and item.output_currency == output_currency
    )
    if any(item.timestamp > timestamp for item in selected_rates):
        raise _fail()
    cash = tuple(
        CashBalanceEvidence(
            balance_id=f"history-cash:{account_id}:{item.currency}",
            account_id=account_id,
            currency=item.currency,
            amount=item.amount,
            timestamp=state.through or timestamp,
        )
        for item in state.cash_by_currency
    )
    liabilities = (
        ()
        if state.liability is None
        else (
            LiabilityBalanceEvidence(
                liability_id=state.liability.balance_id,
                account_id=account_id,
                currency=state.liability.currency,
                amount=state.liability.total_outstanding,
                timestamp=state.liability.effective_at,
            ),
        )
    )
    try:
        return build_account_snapshot_projection(
            AccountSnapshotProjectionInput(
                account_id=account_id,
                account_type=state.account_type,
                account_currency=state.account_currency,
                output_currency=output_currency,
                snapshot_timestamp=timestamp,
                granularity=_GRANULARITY,
                source=_SOURCE,
                calculation_version=calculation_version,
                holdings=tuple(holdings),
                prices=selected_prices,
                exchange_rates=selected_rates,
                cash_balances=cash,
                liabilities=liabilities,
            )
        )
    except AccountSnapshotProjectionStateError as exc:
        raise _fail() from exc


def _metric_rates(
    *,
    account_id: str,
    output_currency: str,
    as_of: datetime,
    rates: tuple[FrozenHistorySeriesMetricRate, ...],
) -> tuple[SelectedHistoricalRate, ...]:
    result: list[SelectedHistoricalRate] = []
    for item in rates:
        if (
            item.account_id != account_id
            or item.output_currency != output_currency
            or _timestamp(item.event_at) > as_of
        ):
            continue
        result.append(
            SelectedHistoricalRate(
                rate_id=item.rate_id,
                evidence_id=item.evidence_id,
                base_currency=item.base_currency,
                quote_currency=item.quote_currency,
                rate=item.rate,
                timestamp=_timestamp(item.timestamp),
            )
        )
    return tuple(result)


def _complete_evidence(
    *,
    account_id: str,
    state: AccountReplayState,
    timestamp: datetime,
    output_currency: str,
    replay_scope: FrozenPortfolioReplayInput,
    valuation_rates: tuple[FrozenHistorySeriesValuationRate, ...],
    prices: tuple[SelectedHistoricalPrice, ...],
    metric_rates: tuple[FrozenHistorySeriesMetricRate, ...],
    calculation_version: int,
) -> CompleteAccountSnapshotEvidence:
    valuation = _valuation(
        account_id=account_id,
        state=state,
        timestamp=timestamp,
        output_currency=output_currency,
        replay_scope=replay_scope,
        prices=prices,
        valuation_rates=valuation_rates,
        calculation_version=calculation_version,
    )
    account = next(item for item in replay_scope.accounts if item.account_id == account_id)
    try:
        complete_metrics = build_complete_historical_metric_evidence(
            account_id=account_id,
            account_type=state.account_type,
            roots=account.roots,
            as_of=timestamp,
            valuation=valuation,
            historical_rates=_metric_rates(
                account_id=account_id,
                output_currency=output_currency,
                as_of=timestamp,
                rates=metric_rates,
            ),
        )
    except AccountSnapshotEvidenceStateError as exc:
        raise _fail() from exc
    metric_evidence = complete_metrics.evidence
    metrics = complete_metrics.metrics
    net_deposits = (
        UnsupportedSnapshotMetric(
            SnapshotMetricUnsupportedReason.external_cash_flow_classification_unavailable
        )
        if metric_evidence.has_asset_transfer
        else ExactSnapshotMetric(metrics.net_deposits_value, metrics.net_deposits_by_currency)
    )
    realized_pnl = (
        UnsupportedSnapshotMetric(SnapshotMetricUnsupportedReason.realized_pnl_evidence_unavailable)
        if (
            metric_evidence.has_asset_transfer
            or metric_evidence.has_missing_anycoin_realized_pnl
            or valuation.investment_cost_basis is None
        )
        else ExactSnapshotMetric(metrics.realized_pnl_value, metrics.realized_pnl_by_currency)
    )
    if valuation.investment_cost_basis is None:
        unrealized_pnl: ExactSnapshotMetric | UnsupportedSnapshotMetric = UnsupportedSnapshotMetric(
            SnapshotMetricUnsupportedReason.cost_basis_evidence_unavailable
        )
    else:
        if metrics.unrealized_pnl_value is None:
            raise _fail()
        unrealized_pnl = ExactSnapshotMetric(
            metrics.unrealized_pnl_value,
            metrics.unrealized_pnl_by_currency,
        )
    price_ids = tuple(
        sorted(
            item.price_id
            for item in prices
            if item.account_id == account_id and item.through == timestamp
        )
    )
    return CompleteAccountSnapshotEvidence(
        valuation=valuation,
        net_deposits=net_deposits,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        fees=ExactSnapshotMetric(metrics.fees_value, metrics.fees_by_currency),
        taxes=ExactSnapshotMetric(metrics.taxes_value, metrics.taxes_by_currency),
        selected_price_ids=price_ids,
        selected_snapshot_exchange_rate_ids=tuple(
            sorted(item.rate_id for item in valuation.exchange_rates)
        ),
        selected_historical_exchange_rate_ids=metrics.selected_historical_rate_ids,
        consumed_historical_exchange_rates=metrics.consumed_historical_exchange_rates,
        selected_liability_balance_id=(
            None if state.liability is None else state.liability.balance_id
        ),
        selected_liability_effective_at=(
            None if state.liability is None else state.liability.effective_at
        ),
    )


def materialize_history_snapshot_series(
    value: HistorySnapshotSeriesMaterializationInput,
) -> ExecuteSnapshotSeriesCommand:
    """Build one complete, deterministic series command without any I/O.

    Every requested account receives native-currency evidence plus evidence in
    each affected user's output currency.  The executor can therefore stage
    shared accounts for several users atomically in the same generation.
    """

    if not isinstance(value, HistorySnapshotSeriesMaterializationInput):
        raise _fail()
    job_id = _text(value.job_id)
    if not isinstance(value.replay_scope, FrozenPortfolioReplayInput):
        raise _fail()
    targets = _canonical_targets(value.targets)
    account_by_id = {account.account_id: account for account in value.replay_scope.accounts}
    if len(account_by_id) != len(value.replay_scope.accounts):
        raise _fail()
    target_account_ids = {account_id for target in targets for account_id in target.account_ids}
    if not target_account_ids <= set(account_by_id):
        raise _fail()
    if (
        not isinstance(value.points, tuple)
        or not value.points
        or not isinstance(value.calculation_version, int)
        or isinstance(value.calculation_version, bool)
        or value.calculation_version <= 0
    ):
        raise _fail()
    calculated_at = _timestamp(value.calculated_at)
    created_at = _timestamp(value.created_at)
    points: list[SnapshotSeriesPoint] = []
    timestamps: set[datetime] = set()
    for point in sorted(value.points, key=lambda item: item.timestamp):
        timestamp = _minute_timestamp(point.timestamp)
        if timestamp in timestamps:
            raise _fail()
        timestamps.add(timestamp)
        states = _states(point, account_ids=set(account_by_id))
        account_evidence: list[SnapshotSeriesAccountEvidence] = []
        for account_id in sorted(target_account_ids):
            state = states[account_id]
            account = account_by_id[account_id]
            if (
                state.account_type is not account.account_type
                or state.account_currency != account.account_currency
            ):
                raise _fail()
            output_currencies = {state.account_currency}
            output_currencies.update(
                target.output_currency for target in targets if account_id in target.account_ids
            )
            for output_currency in sorted(output_currencies):
                account_evidence.append(
                    SnapshotSeriesAccountEvidence(
                        account_id=account_id,
                        account_currency=state.account_currency,
                        evidence=_complete_evidence(
                            account_id=account_id,
                            state=state,
                            timestamp=timestamp,
                            output_currency=output_currency,
                            replay_scope=value.replay_scope,
                            valuation_rates=value.valuation_rates,
                            prices=value.prices,
                            metric_rates=value.metric_rates,
                            calculation_version=value.calculation_version,
                        ),
                        canonical_revision=account.canonical_revision.last_revision,
                        investment_revision=(
                            None
                            if account.canonical_revision.holding_revision is None
                            else account.canonical_revision.last_investment_revision
                        ),
                        holding_revision=account.canonical_revision.holding_revision,
                    )
                )
        points.append(
            SnapshotSeriesPoint(
                timestamp=timestamp,
                granularity=_GRANULARITY,
                source=_SOURCE,
                calculation_version=value.calculation_version,
                calculated_at=calculated_at,
                created_at=created_at,
                is_recalculated=False,
                account_evidence=tuple(
                    sorted(
                        account_evidence,
                        key=lambda item: (item.account_id, item.evidence.valuation.currency),
                    )
                ),
            )
        )
    return ExecuteSnapshotSeriesCommand(
        job_id=job_id,
        targets=targets,
        points=tuple(sorted(points, key=lambda item: item.timestamp)),
        causal_at=_timestamp(value.causal_at or created_at),
    )


__all__ = [
    "FrozenHistorySeriesMetricRate",
    "FrozenHistorySeriesPoint",
    "FrozenHistorySeriesValuationRate",
    "HistorySnapshotSeriesMaterializationInput",
    "SnapshotHistorySeriesMaterializationError",
    "materialize_history_snapshot_series",
]
