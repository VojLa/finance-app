"""Pure per-user adaptation from retained-history evidence to snapshot series.

The retained-history builder and snapshot-series materializer deliberately use
different evidence shapes.  This bridge makes that boundary explicit without
performing persistence or provider I/O.  It only supports the one user frozen
by the history job; publication atomicity across different users is outside
this contract.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from app.modules.portfolio_history.builder.market import HistoricalMarketSelection
from app.modules.portfolio_history_rebuild.models import AccountReplayState
from app.modules.portfolio_history_rebuild.repository import FrozenPortfolioReplayInput
from app.modules.snapshot_refresh.history_series_materializer import (
    FrozenHistorySeriesMetricRate,
    FrozenHistorySeriesPoint,
    FrozenHistorySeriesValuationRate,
    HistorySnapshotSeriesMaterializationInput,
)
from app.modules.snapshot_refresh.series_executor import SnapshotSeriesTarget
from app.modules.snapshots.account_projection import SelectedExchangeRateEvidence


class HistorySnapshotSeriesBridgeError(ValueError):
    """Retained-history evidence cannot safely form a snapshot-series input."""


def _fail() -> HistorySnapshotSeriesBridgeError:
    return HistorySnapshotSeriesBridgeError(
        "Historical market evidence cannot produce a snapshot-series input."
    )


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
        raise _fail()
    return value


def _currency(value: object) -> str:
    currency = _text(value)
    if (
        len(currency) != 3
        or not currency.isascii()
        or not currency.isalpha()
        or currency != currency.upper()
    ):
        raise _fail()
    return currency


def _timestamp(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is not None or value.microsecond % 1_000:
        raise _fail()
    return value


def _valuation_rates(
    market: HistoricalMarketSelection,
) -> tuple[FrozenHistorySeriesValuationRate, ...]:
    values: dict[tuple[str, datetime, str, str, str], FrozenHistorySeriesValuationRate] = {}
    for item in market.snapshot_rates:
        account_id = _text(item.account_id)
        through = _timestamp(item.through)
        output_currency = _currency(item.output_currency)
        rate_id = _text(item.rate_id)
        observation = item.observation
        if (
            _currency(observation.from_currency) == output_currency
            or _currency(observation.to_currency) != output_currency
            or _timestamp(observation.effective_at) > through
        ):
            raise _fail()
        value = FrozenHistorySeriesValuationRate(
            account_id=account_id,
            timestamp=through,
            output_currency=output_currency,
            evidence=SelectedExchangeRateEvidence(
                rate_id=rate_id,
                base_currency=observation.from_currency,
                quote_currency=observation.to_currency,
                rate=observation.rate,
                source=observation.provider,
                timestamp=observation.effective_at,
            ),
        )
        key = (
            account_id,
            through,
            output_currency,
            observation.from_currency,
            observation.to_currency,
        )
        if key in values:
            raise _fail()
        values[key] = value
    return tuple(value for _, value in sorted(values.items()))


def _metric_rates(market: HistoricalMarketSelection) -> tuple[FrozenHistorySeriesMetricRate, ...]:
    values: dict[tuple[str, str, str, str, str], FrozenHistorySeriesMetricRate] = {}
    for item in market.metric_rates:
        account_id = _text(item.account_id)
        evidence_id = _text(item.evidence_id)
        event_at = _timestamp(item.event_at)
        output_currency = _currency(item.output_currency)
        rate_id = _text(item.rate_id)
        observation = item.observation
        if (
            _currency(observation.from_currency) == output_currency
            or _currency(observation.to_currency) != output_currency
            or _timestamp(observation.effective_at) > event_at
        ):
            raise _fail()
        value = FrozenHistorySeriesMetricRate(
            account_id=account_id,
            output_currency=output_currency,
            rate_id=rate_id,
            evidence_id=evidence_id,
            base_currency=observation.from_currency,
            quote_currency=observation.to_currency,
            rate=observation.rate,
            event_at=event_at,
            timestamp=observation.effective_at,
        )
        key = (
            account_id,
            output_currency,
            evidence_id,
            observation.from_currency,
            observation.to_currency,
        )
        if key in values:
            raise _fail()
        values[key] = value
    return tuple(value for _, value in sorted(values.items()))


def _points(
    states: Mapping[datetime, Mapping[str, AccountReplayState]],
    *,
    accounts: FrozenPortfolioReplayInput,
) -> tuple[FrozenHistorySeriesPoint, ...]:
    if not isinstance(states, Mapping) or not states:
        raise _fail()
    account_by_id = {account.account_id: account for account in accounts.accounts}
    if len(account_by_id) != len(accounts.accounts):
        raise _fail()
    result: list[FrozenHistorySeriesPoint] = []
    timestamps: set[datetime] = set()
    for timestamp, point_states in states.items():
        timestamp = _timestamp(timestamp)
        if timestamp in timestamps or not isinstance(point_states, Mapping):
            raise _fail()
        timestamps.add(timestamp)
        by_id: dict[str, AccountReplayState] = {}
        for account_id, state in point_states.items():
            account_id = _text(account_id)
            if (
                account_id in by_id
                or not isinstance(state, AccountReplayState)
                or state.account_id != account_id
            ):
                raise _fail()
            frozen = account_by_id.get(account_id)
            if (
                frozen is None
                or state.account_type is not frozen.account_type
                or state.account_currency != frozen.account_currency
            ):
                raise _fail()
            by_id[account_id] = state
        if set(by_id) != set(account_by_id):
            raise _fail()
        result.append(
            FrozenHistorySeriesPoint(
                timestamp=timestamp,
                account_states=tuple(by_id[account_id] for account_id in sorted(by_id)),
            )
        )
    return tuple(sorted(result, key=lambda item: item.timestamp))


def build_history_snapshot_series_materialization_input(
    *,
    job_id: str,
    replay_scope: FrozenPortfolioReplayInput,
    states: Mapping[datetime, Mapping[str, AccountReplayState]],
    market: HistoricalMarketSelection,
    calculation_version: int,
    calculated_at: datetime,
    created_at: datetime,
    causal_at: datetime | None = None,
) -> HistorySnapshotSeriesMaterializationInput:
    """Build the deterministic, one-user materializer input without any I/O."""

    if not isinstance(replay_scope, FrozenPortfolioReplayInput) or not isinstance(
        market, HistoricalMarketSelection
    ):
        raise _fail()
    account_ids = tuple(sorted(_text(account.account_id) for account in replay_scope.accounts))
    if not account_ids or len(account_ids) != len(set(account_ids)):
        raise _fail()
    return HistorySnapshotSeriesMaterializationInput(
        job_id=_text(job_id),
        replay_scope=replay_scope,
        targets=(
            SnapshotSeriesTarget(
                user_id=_text(replay_scope.user_id),
                output_currency=_currency(replay_scope.base_currency),
                account_ids=account_ids,
            ),
        ),
        points=_points(states, accounts=replay_scope),
        prices=tuple(
            sorted(
                market.prices,
                key=lambda item: (item.through, item.account_id, item.price_id),
            )
        ),
        valuation_rates=_valuation_rates(market),
        metric_rates=_metric_rates(market),
        calculation_version=calculation_version,
        calculated_at=_timestamp(calculated_at),
        created_at=_timestamp(created_at),
        causal_at=_timestamp(causal_at or created_at),
    )


__all__ = [
    "HistorySnapshotSeriesBridgeError",
    "build_history_snapshot_series_materialization_input",
]
