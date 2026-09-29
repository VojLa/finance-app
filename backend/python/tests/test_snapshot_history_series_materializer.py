import importlib
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.db.models.enums import (
    AccountType,
    AssetType,
    ExchangeRateSource,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
)
from app.modules.holdings.persistence_projection import (
    ExpectedPersistedHoldingPlan,
    HoldingPersistenceMovement,
)
from app.modules.portfolio_history.builder.market import SelectedHistoricalPrice
from app.modules.portfolio_history_rebuild.models import AccountReplayState, InvestmentEventRoot
from app.modules.portfolio_history_rebuild.repository import (
    FrozenAccountReplayInput,
    FrozenCanonicalRevision,
    FrozenListingIdentity,
    FrozenPortfolioReplayInput,
)
from app.modules.prices.models import PriceObservation
from app.modules.snapshot_refresh.history_series_materializer import (
    FrozenHistorySeriesMetricRate,
    FrozenHistorySeriesPoint,
    FrozenHistorySeriesValuationRate,
    HistorySnapshotSeriesMaterializationInput,
    SnapshotHistorySeriesMaterializationError,
    materialize_history_snapshot_series,
)
from app.modules.snapshot_refresh.series_executor import SnapshotSeriesTarget
from app.modules.snapshots.account_projection import SelectedExchangeRateEvidence
from app.modules.snapshots.evidence_service import ExactSnapshotMetric

_EVENT_AT = datetime(2025, 1, 2, 10, 0)
_POINT_AT = datetime(2025, 2, 3, 12, 0)
_ACCOUNT_ID = "shared-account"


def _root() -> InvestmentEventRoot:
    return InvestmentEventRoot(
        event_id="deposit-event",
        account_id=_ACCOUNT_ID,
        event_type=InvestmentEventType.cash_deposit,
        event_date=_EVENT_AT,
        movements=(
            HoldingPersistenceMovement(
                movement_id="deposit-movement",
                event_id="deposit-event",
                account_id=_ACCOUNT_ID,
                kind=InvestmentMovementKind.cash,
                direction=MovementDirection.incoming,
                quantity=Decimal("10.000000"),
                currency="USD",
                asset_id=None,
                listing_id=None,
                listing_asset_id=None,
                source_symbol=None,
                source_asset_type=None,
                price_per_unit=None,
                value_amount=None,
                value_currency=None,
            ),
        ),
        source=ImportSource.manual,
    )


def _input(*, metric_rates: tuple[FrozenHistorySeriesMetricRate, ...] | None = None):
    listing = FrozenListingIdentity(
        listing_id="listing-aapl",
        asset_id="asset-aapl",
        symbol="AAPL",
        name="Apple",
        asset_type=AssetType.stock.value,
        currency="USD",
        price_currency="USD",
        provider=PriceSource.yahoo_finance,
        provider_symbol="AAPL",
    )
    account = FrozenAccountReplayInput(
        account_id=_ACCOUNT_ID,
        account_name="Shared brokerage",
        account_type=AccountType.broker,
        account_currency="USD",
        canonical_revision=FrozenCanonicalRevision(
            last_revision=1,
            last_investment_revision=1,
            holding_revision=1,
        ),
        canonical_manifest=(),
        listing_identities=(listing,),
        roots=(_root(),),
        earliest_event_at=_EVENT_AT,
    )
    replay_scope = FrozenPortfolioReplayInput(
        user_id="owner",
        base_currency="EUR",
        accounts=(account,),
        earliest_event_at=_EVENT_AT,
        scope_hash="frozen-scope",
    )
    state = AccountReplayState(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.broker,
        account_currency="USD",
        active=True,
        holdings=(
            ExpectedPersistedHoldingPlan(
                account_id=_ACCOUNT_ID,
                asset_id="asset-aapl",
                listing_id="listing-aapl",
                symbol="AAPL",
                name="Apple",
                asset_type=AssetType.stock,
                quantity=Decimal("1.0000000000"),
                avg_buy_price=Decimal("80.0000000000"),
                currency="USD",
                current_price=None,
                current_value=None,
                unrealized_pnl=None,
                realized_pnl=None,
                cost_basis_by_currency=(("USD", Decimal("80.000000")),),
            ),
        ),
    )
    price = SelectedHistoricalPrice(
        account_id=_ACCOUNT_ID,
        through=_POINT_AT,
        listing=listing,
        price_id="aapl-usd-point-price",
        observation=PriceObservation(
            asset_id="asset-aapl",
            listing_id="listing-aapl",
            provider=PriceSource.yahoo_finance,
            provider_symbol="AAPL",
            price=Decimal("100.0000000000"),
            currency="USD",
            observed_at=_POINT_AT,
        ),
    )

    def valuation_rate(output: str, rate_id: str, rate: str) -> FrozenHistorySeriesValuationRate:
        return FrozenHistorySeriesValuationRate(
            account_id=_ACCOUNT_ID,
            timestamp=_POINT_AT,
            output_currency=output,
            evidence=SelectedExchangeRateEvidence(
                rate_id=rate_id,
                base_currency="USD",
                quote_currency=output,
                rate=Decimal(rate),
                source=ExchangeRateSource.yahoo_finance,
                timestamp=_POINT_AT,
            ),
        )

    supplied_metric_rates = metric_rates
    if supplied_metric_rates is None:
        supplied_metric_rates = (
            FrozenHistorySeriesMetricRate(
                account_id=_ACCOUNT_ID,
                output_currency="EUR",
                rate_id="usd-eur-event-rate",
                evidence_id="deposit:deposit-movement",
                base_currency="USD",
                quote_currency="EUR",
                rate=Decimal("0.7000000000"),
                event_at=_EVENT_AT,
                timestamp=_EVENT_AT,
            ),
            FrozenHistorySeriesMetricRate(
                account_id=_ACCOUNT_ID,
                output_currency="CZK",
                rate_id="usd-czk-event-rate",
                evidence_id="deposit:deposit-movement",
                base_currency="USD",
                quote_currency="CZK",
                rate=Decimal("18.0000000000"),
                event_at=_EVENT_AT,
                timestamp=_EVENT_AT,
            ),
        )
    return HistorySnapshotSeriesMaterializationInput(
        job_id="history-job",
        replay_scope=replay_scope,
        targets=(
            SnapshotSeriesTarget("user-czk", "CZK", (_ACCOUNT_ID,)),
            SnapshotSeriesTarget("user-eur", "EUR", (_ACCOUNT_ID,)),
        ),
        points=(FrozenHistorySeriesPoint(_POINT_AT, (state,)),),
        prices=(price,),
        valuation_rates=(
            valuation_rate("EUR", "usd-eur-valuation-rate", "0.8000000000"),
            valuation_rate("CZK", "usd-czk-valuation-rate", "20.0000000000"),
        ),
        metric_rates=supplied_metric_rates,
        calculation_version=1,
        calculated_at=_POINT_AT,
        created_at=_POINT_AT,
    )


def _evidence_by_currency(command):
    return {
        item.evidence.valuation.currency: item.evidence
        for item in command.points[0].account_evidence
    }


def test_materializes_native_and_all_shared_user_outputs_with_event_date_metrics() -> None:
    command = materialize_history_snapshot_series(_input())

    assert [target.user_id for target in command.targets] == ["user-czk", "user-eur"]
    assert [item.evidence.valuation.currency for item in command.points[0].account_evidence] == [
        "CZK",
        "EUR",
        "USD",
    ]
    evidence = _evidence_by_currency(command)
    assert {
        (
            item.canonical_revision,
            item.investment_revision,
            item.holding_revision,
        )
        for item in command.points[0].account_evidence
    } == {(1, 1, 1)}
    assert evidence["USD"].valuation.investment_value == Decimal("100.000000")
    assert evidence["EUR"].valuation.investment_value == Decimal("80.000000")
    assert evidence["CZK"].valuation.investment_value == Decimal("2000.000000")
    assert all(item.valuation.items for item in evidence.values())

    eur_deposits = evidence["EUR"].net_deposits
    assert isinstance(eur_deposits, ExactSnapshotMetric)
    assert eur_deposits.value == Decimal("7.000000")
    assert evidence["EUR"].selected_snapshot_exchange_rate_ids == ("usd-eur-valuation-rate",)
    assert evidence["EUR"].selected_historical_exchange_rate_ids == ("usd-eur-event-rate",)
    assert evidence["EUR"].consumed_historical_exchange_rates[0].timestamp == _EVENT_AT
    assert evidence["USD"].selected_historical_exchange_rate_ids == ()


def test_known_total_unrealized_pnl_allows_unavailable_native_breakdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materializer_module = importlib.import_module(
        "app.modules.snapshot_refresh.history_series_materializer"
    )
    original = materializer_module.build_complete_historical_metric_evidence

    def without_native_breakdown(**kwargs):
        result = original(**kwargs)
        return replace(
            result,
            metrics=replace(result.metrics, unrealized_pnl_by_currency=None),
        )

    monkeypatch.setattr(
        materializer_module,
        "build_complete_historical_metric_evidence",
        without_native_breakdown,
    )

    command = materialize_history_snapshot_series(_input())

    for evidence in _evidence_by_currency(command).values():
        assert isinstance(evidence.unrealized_pnl, ExactSnapshotMetric)
        assert evidence.unrealized_pnl.value is not None
        assert evidence.unrealized_pnl.breakdown is None


def test_fails_closed_when_event_date_metric_rate_is_missing() -> None:
    frozen = _input(metric_rates=())

    with pytest.raises(SnapshotHistorySeriesMaterializationError):
        materialize_history_snapshot_series(frozen)


def test_later_event_metric_rates_are_not_consumed_by_an_earlier_point() -> None:
    first = _input()
    later_rates = tuple(
        replace(
            item,
            rate_id=f"later-{item.rate_id}",
            evidence_id="deposit:future-movement",
            event_at=_POINT_AT + timedelta(days=1),
            timestamp=_POINT_AT - timedelta(days=1),
        )
        for item in first.metric_rates
    )

    command = materialize_history_snapshot_series(
        replace(first, metric_rates=first.metric_rates + later_rates)
    )

    evidence = _evidence_by_currency(command)
    assert evidence["EUR"].selected_historical_exchange_rate_ids == ("usd-eur-event-rate",)
    assert evidence["CZK"].selected_historical_exchange_rate_ids == ("usd-czk-event-rate",)
