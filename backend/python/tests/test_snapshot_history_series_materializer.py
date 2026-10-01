import importlib
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast

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
    OpenCostBasisMovement,
    project_open_event_cost_basis,
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
from app.modules.snapshots.account_projection import CurrencyAmount, SelectedExchangeRateEvidence
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


def _buy_root() -> InvestmentEventRoot:
    return InvestmentEventRoot(
        event_id="buy-event",
        account_id=_ACCOUNT_ID,
        event_type=InvestmentEventType.trade,
        event_date=_EVENT_AT,
        movements=(
            HoldingPersistenceMovement(
                movement_id="buy-asset",
                event_id="buy-event",
                account_id=_ACCOUNT_ID,
                kind=InvestmentMovementKind.asset,
                direction=MovementDirection.incoming,
                quantity=Decimal("1.0000000000"),
                currency="USD",
                asset_id="asset-aapl",
                listing_id="listing-aapl",
                listing_asset_id="asset-aapl",
                source_symbol="AAPL",
                source_asset_type=AssetType.stock,
                price_per_unit=Decimal("80.0000000000"),
                value_amount=Decimal("80.0000000000"),
                value_currency="USD",
                listing_currency="USD",
            ),
            HoldingPersistenceMovement(
                movement_id="buy-cash",
                event_id="buy-event",
                account_id=_ACCOUNT_ID,
                kind=InvestmentMovementKind.cash,
                direction=MovementDirection.outgoing,
                quantity=Decimal("80.0000000000"),
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
        evidence_listing_id="listing-aapl",
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
        roots=(_root(), _buy_root()),
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
            FrozenHistorySeriesMetricRate(
                account_id=_ACCOUNT_ID,
                output_currency="EUR",
                rate_id="usd-eur-event-rate",
                evidence_id="cost:buy-asset",
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
                evidence_id="cost:buy-asset",
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
    assert evidence["USD"].valuation.investment_cost_basis == Decimal("80.000000")
    assert evidence["EUR"].valuation.investment_cost_basis == Decimal("56.000000")
    assert evidence["CZK"].valuation.investment_cost_basis == Decimal("1440.000000")
    assert evidence["EUR"].valuation.items[0].cost_basis == Decimal("56.000000")
    assert evidence["EUR"].valuation.investment_cost_basis_by_currency == (
        CurrencyAmount("USD", Decimal("80.000000")),
    )
    assert all(item.valuation.items for item in evidence.values())

    eur_deposits = evidence["EUR"].net_deposits
    assert isinstance(eur_deposits, ExactSnapshotMetric)
    assert eur_deposits.value == Decimal("7.000000")
    assert evidence["EUR"].selected_snapshot_exchange_rate_ids == ("usd-eur-valuation-rate",)
    assert evidence["EUR"].selected_historical_exchange_rate_ids == ("usd-eur-event-rate",)
    assert evidence["EUR"].consumed_historical_exchange_rates[0].timestamp == _EVENT_AT
    assert evidence["USD"].selected_historical_exchange_rate_ids == ()


def test_cost_basis_stays_fixed_when_only_snapshot_fx_changes() -> None:
    first = _input()
    later = _POINT_AT + timedelta(days=1)
    second_price = replace(
        first.prices[0],
        through=later,
        observation=replace(first.prices[0].observation, observed_at=later),
    )
    second_rates = tuple(
        replace(
            item,
            timestamp=later,
            evidence=replace(
                item.evidence,
                rate=Decimal("0.9000000000")
                if item.output_currency == "EUR"
                else Decimal("25.0000000000"),
                timestamp=later,
                rate_id=f"later-{item.evidence.rate_id}",
            ),
        )
        for item in first.valuation_rates
    )
    command = materialize_history_snapshot_series(
        replace(
            first,
            points=(
                first.points[0],
                FrozenHistorySeriesPoint(later, first.points[0].account_states),
            ),
            prices=(*first.prices, second_price),
            valuation_rates=first.valuation_rates + second_rates,
        )
    )
    by_point = [
        {item.evidence.valuation.currency: item.evidence for item in point.account_evidence}
        for point in command.points
    ]
    assert [point["EUR"].valuation.investment_value for point in by_point] == [
        Decimal("80.000000"),
        Decimal("90.000000"),
    ]
    assert [point["EUR"].valuation.investment_cost_basis for point in by_point] == [
        Decimal("56.000000"),
        Decimal("56.000000"),
    ]
    assert [point["CZK"].valuation.investment_cost_basis for point in by_point] == [
        Decimal("1440.000000"),
        Decimal("1440.000000"),
    ]
    assert [cast(ExactSnapshotMetric, point["EUR"].unrealized_pnl).value for point in by_point] == [
        Decimal("24.000000"),
        Decimal("34.000000"),
    ]


def test_open_cost_replay_scales_converted_and_native_basis_on_disposal() -> None:
    buy_usd = OpenCostBasisMovement(
        "buy-usd",
        "asset-usd",
        _EVENT_AT,
        "listing",
        MovementDirection.incoming,
        Decimal("4"),
        Decimal("100"),
        "USD",
        Decimal("1800"),
    )
    sell_one = OpenCostBasisMovement(
        "sell-one",
        "sale-one",
        _EVENT_AT + timedelta(days=1),
        "listing",
        MovementDirection.outgoing,
        Decimal("1"),
    )
    buy_eur = OpenCostBasisMovement(
        "buy-eur",
        "asset-eur",
        _EVENT_AT + timedelta(days=2),
        "listing",
        MovementDirection.incoming,
        Decimal("1"),
        Decimal("50"),
        "EUR",
        Decimal("1250"),
    )
    sell_two = OpenCostBasisMovement(
        "sell-two",
        "sale-two",
        _EVENT_AT + timedelta(days=3),
        "listing",
        MovementDirection.outgoing,
        Decimal("2"),
    )
    close = OpenCostBasisMovement(
        "close",
        "sale-close",
        _EVENT_AT + timedelta(days=4),
        "listing",
        MovementDirection.outgoing,
        Decimal("2"),
    )
    assert project_open_event_cost_basis((buy_usd, sell_one))[0].converted_cost_basis == Decimal(
        "1350.000000"
    )
    open_position = project_open_event_cost_basis((buy_usd, sell_one, buy_eur, sell_two))[0]
    assert open_position.quantity == Decimal("2")
    assert open_position.native_cost_basis == (
        ("EUR", Decimal("25.0000000000")),
        ("USD", Decimal("37.5000000000")),
    )
    assert open_position.converted_cost_basis == Decimal("1300.000000")
    assert project_open_event_cost_basis((buy_usd, sell_one, buy_eur, sell_two, close)) == ()


def test_missing_acquisition_rate_fails_closed() -> None:
    frozen = _input()
    with pytest.raises(SnapshotHistorySeriesMaterializationError):
        materialize_history_snapshot_series(
            replace(
                frozen,
                metric_rates=tuple(
                    item for item in frozen.metric_rates if item.evidence_id != "cost:buy-asset"
                ),
            )
        )


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
