from dataclasses import replace
from datetime import datetime
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
    TransactionClassification,
    TransactionType,
)
from app.modules.fx.models import ExchangeRateObservation
from app.modules.holdings.persistence_projection import (
    ExpectedPersistedHoldingPlan,
    HoldingPersistenceMovement,
)
from app.modules.market_data.history.models import (
    HistoricalExchangeRateProviderCapability,
    HistoricalExchangeRateRangeRequirement,
    HistoricalPriceProviderCapability,
    HistoricalPriceRangeRequirement,
    HistoricalProviderGranularity,
    HistoricalTimeSeriesInterval,
)
from app.modules.market_data.policy import DEFAULT_MARKET_EVIDENCE_POLICY
from app.modules.market_data.source_policy import (
    CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
)
from app.modules.portfolio_history.builder.market import HistoricalMarketAcquirer
from app.modules.portfolio_history_rebuild.models import (
    AccountReplayState,
    CurrencyAmount,
    InvestmentEventRoot,
    ReplayMetrics,
    TransactionRoot,
)
from app.modules.portfolio_history_rebuild.repository import (
    FrozenAccountReplayInput,
    FrozenCanonicalRevision,
    FrozenListingIdentity,
    FrozenPortfolioReplayInput,
)
from app.modules.prices.models import PriceObservation
from app.modules.snapshot_refresh.history_series_bridge import (
    build_history_snapshot_series_materialization_input,
)
from app.modules.snapshot_refresh.history_series_materializer import (
    SnapshotHistorySeriesMaterializationError,
    materialize_history_snapshot_series,
)
from app.modules.snapshots.evidence_service import ExactSnapshotMetric

_EVENT_AT = datetime(2025, 1, 2, 10, 0)
_POINT_AT = datetime(2025, 1, 3, 12, 0)
_ACCOUNT_ID = "account"


def _scope() -> FrozenPortfolioReplayInput:
    event = InvestmentEventRoot(
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
    return FrozenPortfolioReplayInput(
        user_id="owner",
        base_currency="EUR",
        accounts=(
            FrozenAccountReplayInput(
                account_id=_ACCOUNT_ID,
                account_name="Cash account",
                account_type=AccountType.cash,
                account_currency="USD",
                canonical_revision=FrozenCanonicalRevision(
                    last_revision=1,
                    last_investment_revision=1,
                    holding_revision=None,
                ),
                canonical_manifest=(),
                listing_identities=(),
                roots=(event,),
                earliest_event_at=_EVENT_AT,
            ),
        ),
        earliest_event_at=_EVENT_AT,
        scope_hash="scope",
    )


def _states() -> dict[datetime, dict[str, AccountReplayState]]:
    return {
        _POINT_AT: {
            _ACCOUNT_ID: AccountReplayState(
                account_id=_ACCOUNT_ID,
                account_type=AccountType.cash,
                account_currency="USD",
                active=True,
                cash_by_currency=(CurrencyAmount(currency="USD", amount=Decimal("10.000000")),),
            )
        }
    }


def _card_scope() -> FrozenPortfolioReplayInput:
    cashback_at = _EVENT_AT.replace(hour=11)
    roots = (
        TransactionRoot(
            transaction_id="card-debit",
            account_id=_ACCOUNT_ID,
            timestamp=_EVENT_AT,
            amount=Decimal("-12.000000"),
            currency="USD",
            transaction_type=TransactionType.expense,
            classification=TransactionClassification.real_expense,
            eligible=True,
        ),
        TransactionRoot(
            transaction_id="cashback",
            account_id=_ACCOUNT_ID,
            timestamp=cashback_at,
            amount=Decimal("4.000000"),
            currency="USD",
            transaction_type=TransactionType.income,
            classification=TransactionClassification.real_income,
            eligible=True,
        ),
    )
    return FrozenPortfolioReplayInput(
        user_id="owner",
        base_currency="EUR",
        accounts=(
            FrozenAccountReplayInput(
                account_id=_ACCOUNT_ID,
                account_name="Trading account",
                account_type=AccountType.broker,
                account_currency="USD",
                canonical_revision=FrozenCanonicalRevision(
                    last_revision=2,
                    last_investment_revision=0,
                    holding_revision=0,
                ),
                canonical_manifest=(),
                listing_identities=(),
                roots=roots,
                earliest_event_at=_EVENT_AT,
            ),
        ),
        earliest_event_at=_EVENT_AT,
        scope_hash="card-scope",
    )


def _card_states() -> dict[datetime, dict[str, AccountReplayState]]:
    return {
        _POINT_AT: {
            _ACCOUNT_ID: AccountReplayState(
                account_id=_ACCOUNT_ID,
                account_type=AccountType.broker,
                account_currency="USD",
                active=True,
                cash_by_currency=(CurrencyAmount("USD", Decimal("-8.000000")),),
                metrics=ReplayMetrics(net_deposits=(CurrencyAmount("USD", Decimal("-8.000000")),)),
            )
        }
    }


class _FxProvider:
    capability = HistoricalExchangeRateProviderCapability(
        source=ExchangeRateSource.twelve_data,
        supported_intervals=(
            HistoricalTimeSeriesInterval.thirty_minutes,
            HistoricalTimeSeriesInterval.daily,
        ),
    )

    def __init__(self) -> None:
        self.requirements: list[HistoricalExchangeRateRangeRequirement] = []

    async def fetch_range(
        self,
        requirement: HistoricalExchangeRateRangeRequirement,
    ) -> tuple[ExchangeRateObservation, ...]:
        self.requirements.append(requirement)
        return tuple(
            ExchangeRateObservation(
                from_currency=requirement.from_currency,
                to_currency=requirement.to_currency,
                provider=requirement.provider,
                rate=Decimal("0.80000000"),
                effective_at=timestamp,
            )
            for timestamp in requirement.requested_at
        )


class _SharedPriceProvider:
    capability = HistoricalPriceProviderCapability(
        source=PriceSource.yahoo_finance,
        native_granularity=HistoricalProviderGranularity.daily,
        supports_subdaily_backfill=False,
        supported_intervals=(HistoricalTimeSeriesInterval.daily,),
    )

    def __init__(self) -> None:
        self.requirements: list[HistoricalPriceRangeRequirement] = []

    async def fetch_range(
        self, requirement: HistoricalPriceRangeRequirement
    ) -> tuple[PriceObservation, ...]:
        self.requirements.append(requirement)
        return tuple(
            PriceObservation(
                asset_id=requirement.asset_id,
                listing_id=requirement.listing_id,
                provider=requirement.provider,
                provider_symbol=requirement.provider_symbol,
                price=Decimal("100.000000"),
                currency=requirement.listing_currency,
                observed_at=timestamp,
            )
            for timestamp in requirement.requested_at
        )


@pytest.mark.asyncio
async def test_shared_evidence_listing_keeps_each_original_holding_listing() -> None:
    evidence_listing_id = "btc-yahoo-usd"

    account_id = "account"
    listing_ids = ("btc-exchange-a", "btc-exchange-b")
    account = FrozenAccountReplayInput(
        account_id=account_id,
        account_name=account_id,
        account_type=AccountType.broker,
        account_currency="USD",
        canonical_revision=FrozenCanonicalRevision(
            last_revision=1,
            last_investment_revision=1,
            holding_revision=1,
        ),
        canonical_manifest=(),
        listing_identities=tuple(
            FrozenListingIdentity(
                listing_id=listing_id,
                evidence_listing_id=evidence_listing_id,
                asset_id="btc",
                symbol="BTC",
                name="Bitcoin",
                asset_type=AssetType.crypto.value,
                currency="USD",
                price_currency="USD",
                provider=PriceSource.yahoo_finance,
                provider_symbol="BTC-USD",
            )
            for listing_id in listing_ids
        ),
        roots=(),
        earliest_event_at=_EVENT_AT,
    )

    scope = FrozenPortfolioReplayInput(
        user_id="owner",
        base_currency="USD",
        accounts=(account,),
        earliest_event_at=_EVENT_AT,
        scope_hash="shared-evidence",
    )
    states = {
        _POINT_AT: {
            account_id: AccountReplayState(
                account_id=account_id,
                account_type=AccountType.broker,
                account_currency="USD",
                active=True,
                holdings=tuple(
                    ExpectedPersistedHoldingPlan(
                        account_id=account_id,
                        asset_id="btc",
                        listing_id=listing_id,
                        symbol="BTC",
                        name="Bitcoin",
                        asset_type=AssetType.crypto,
                        quantity=Decimal("1"),
                        avg_buy_price=Decimal("90"),
                        currency="USD",
                        current_price=None,
                        current_value=None,
                        unrealized_pnl=None,
                        realized_pnl=None,
                        cost_basis_by_currency=(("USD", Decimal("90")),),
                    )
                    for listing_id in listing_ids
                ),
            )
        }
    }
    provider = _SharedPriceProvider()

    selection = await HistoricalMarketAcquirer(
        price_providers={PriceSource.yahoo_finance: provider},
        fx_providers={},
        source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
        evidence_policy=DEFAULT_MARKET_EVIDENCE_POLICY,
    ).acquire(
        scope=scope,
        states=states,
        requested_at=(_POINT_AT,),
        subdaily_at=(),
    )

    assert len(provider.requirements) == 1
    assert provider.requirements[0].listing_id == evidence_listing_id
    assert [(item.account_id, item.listing.listing_id) for item in selection.prices] == [
        (account_id, "btc-exchange-a"),
        (account_id, "btc-exchange-b"),
    ]
    assert len({item.price_id for item in selection.prices}) == 1
    assert {item.observation.listing_id for item in selection.prices} == {evidence_listing_id}


@pytest.mark.asyncio
async def test_acquires_native_base_and_event_metric_fx_once_per_pair_interval_timestamps() -> None:
    provider = _FxProvider()
    selection = await HistoricalMarketAcquirer(
        price_providers={},
        fx_providers={ExchangeRateSource.twelve_data: provider},
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        evidence_policy=DEFAULT_MARKET_EVIDENCE_POLICY,
    ).acquire(
        scope=_scope(),
        states=_states(),
        requested_at=(_POINT_AT,),
        subdaily_at=(_POINT_AT,),
    )

    assert selection.provider_call_count == 2
    assert [
        (item.from_currency, item.to_currency, item.interval, item.requested_at)
        for item in provider.requirements
    ] == [
        ("USD", "EUR", HistoricalTimeSeriesInterval.daily, (_EVENT_AT,)),
        ("USD", "EUR", HistoricalTimeSeriesInterval.thirty_minutes, (_POINT_AT,)),
    ]
    assert [(item.output_currency, item.through) for item in selection.snapshot_rates] == [
        ("EUR", _POINT_AT)
    ]
    assert [
        (item.output_currency, item.evidence_id, item.event_at) for item in selection.metric_rates
    ] == [("EUR", "deposit:deposit-movement", _EVENT_AT)]
    assert selection.metric_rates[0].observation.effective_at == _EVENT_AT


@pytest.mark.asyncio
async def test_trading_card_metrics_request_fx_at_each_transaction_timestamp() -> None:
    provider = _FxProvider()
    scope = _card_scope()
    states = _card_states()
    selection = await HistoricalMarketAcquirer(
        price_providers={},
        fx_providers={ExchangeRateSource.twelve_data: provider},
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        evidence_policy=DEFAULT_MARKET_EVIDENCE_POLICY,
    ).acquire(
        scope=scope,
        states=states,
        requested_at=(_POINT_AT,),
        subdaily_at=(_POINT_AT,),
    )

    cashback_at = _EVENT_AT.replace(hour=11)
    assert [
        (item.from_currency, item.to_currency, item.interval, item.requested_at)
        for item in provider.requirements
    ] == [
        (
            "USD",
            "EUR",
            HistoricalTimeSeriesInterval.daily,
            (_EVENT_AT, cashback_at),
        ),
        ("USD", "EUR", HistoricalTimeSeriesInterval.thirty_minutes, (_POINT_AT,)),
    ]
    assert [(item.evidence_id, item.event_at) for item in selection.metric_rates] == [
        ("transaction:card-debit", _EVENT_AT),
        ("transaction:cashback", cashback_at),
    ]

    value = build_history_snapshot_series_materialization_input(
        job_id="card-history-job",
        replay_scope=scope,
        states=states,
        market=selection,
        calculation_version=1,
        calculated_at=_POINT_AT,
        created_at=_POINT_AT,
    )
    command = materialize_history_snapshot_series(value)
    by_currency = {
        item.evidence.valuation.currency: item.evidence
        for item in command.points[0].account_evidence
    }
    assert by_currency["USD"].valuation.cash_value == Decimal("-8.000000")
    usd_deposits = by_currency["USD"].net_deposits
    eur_deposits = by_currency["EUR"].net_deposits
    eur_fees = by_currency["EUR"].fees
    eur_taxes = by_currency["EUR"].taxes
    eur_realized_pnl = by_currency["EUR"].realized_pnl
    assert isinstance(usd_deposits, ExactSnapshotMetric)
    assert isinstance(eur_deposits, ExactSnapshotMetric)
    assert isinstance(eur_fees, ExactSnapshotMetric)
    assert isinstance(eur_taxes, ExactSnapshotMetric)
    assert isinstance(eur_realized_pnl, ExactSnapshotMetric)
    assert usd_deposits.value == Decimal("-8.000000")
    assert eur_deposits.value == Decimal("-6.400000")
    assert eur_fees.value == Decimal("0.000000")
    assert eur_taxes.value == Decimal("0.000000")
    assert eur_realized_pnl.value == Decimal("0.000000")


@pytest.mark.asyncio
async def test_event_metric_and_subdaily_snapshot_at_same_time_keep_distinct_fx_roles() -> None:
    provider = _FxProvider()
    original = _card_scope()
    account = original.accounts[0]
    debit = replace(cast(TransactionRoot, account.roots[0]), timestamp=_POINT_AT)
    scope = replace(
        original,
        accounts=(replace(account, roots=(debit,), earliest_event_at=_POINT_AT),),
        earliest_event_at=_POINT_AT,
    )
    states = {
        _POINT_AT: {
            _ACCOUNT_ID: AccountReplayState(
                account_id=_ACCOUNT_ID,
                account_type=AccountType.broker,
                account_currency="USD",
                active=True,
                cash_by_currency=(CurrencyAmount("USD", Decimal("-12.000000")),),
                metrics=ReplayMetrics(net_deposits=(CurrencyAmount("USD", Decimal("-12.000000")),)),
            )
        }
    }

    selection = await HistoricalMarketAcquirer(
        price_providers={},
        fx_providers={ExchangeRateSource.twelve_data: provider},
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        evidence_policy=DEFAULT_MARKET_EVIDENCE_POLICY,
    ).acquire(
        scope=scope,
        states=states,
        requested_at=(_POINT_AT,),
        subdaily_at=(_POINT_AT,),
    )

    assert len(selection.snapshot_rates) == 1
    assert len(selection.metric_rates) == 1
    assert selection.snapshot_rates[0].observation.effective_at == _POINT_AT
    assert selection.metric_rates[0].observation.effective_at == _POINT_AT
    assert selection.snapshot_rates[0].rate_id == selection.metric_rates[0].rate_id

    value = build_history_snapshot_series_materialization_input(
        job_id="same-time-fx-roles",
        replay_scope=scope,
        states=states,
        market=selection,
        calculation_version=1,
        calculated_at=_POINT_AT,
        created_at=_POINT_AT,
    )
    command = materialize_history_snapshot_series(value)
    assert len(command.points) == 1


@pytest.mark.asyncio
async def test_bridge_supplies_materializer_with_native_base_and_event_date_metric_fx() -> None:
    provider = _FxProvider()
    scope = _scope()
    states = _states()
    market = await HistoricalMarketAcquirer(
        price_providers={},
        fx_providers={ExchangeRateSource.twelve_data: provider},
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        evidence_policy=DEFAULT_MARKET_EVIDENCE_POLICY,
    ).acquire(
        scope=scope,
        states=states,
        requested_at=(_POINT_AT,),
        subdaily_at=(_POINT_AT,),
    )

    value = build_history_snapshot_series_materialization_input(
        job_id="history-job",
        replay_scope=scope,
        states=states,
        market=market,
        calculation_version=1,
        calculated_at=_POINT_AT,
        created_at=_POINT_AT,
    )
    command = materialize_history_snapshot_series(value)

    assert command.targets[0].user_id == "owner"
    assert command.targets[0].output_currency == "EUR"
    by_currency = {
        item.evidence.valuation.currency: item.evidence
        for item in command.points[0].account_evidence
    }
    assert set(by_currency) == {"EUR", "USD"}
    assert by_currency["EUR"].valuation.cash_value == Decimal("8.000000")
    assert by_currency["EUR"].selected_snapshot_exchange_rate_ids == (
        market.snapshot_rates[0].rate_id,
    )
    assert by_currency["EUR"].selected_historical_exchange_rate_ids == (
        market.metric_rates[0].rate_id,
    )
    assert by_currency["EUR"].consumed_historical_exchange_rates[0].timestamp == _EVENT_AT


@pytest.mark.asyncio
async def test_bridge_fails_closed_in_the_materializer_when_metric_evidence_is_missing() -> None:
    provider = _FxProvider()
    scope = _scope()
    states = _states()
    market = await HistoricalMarketAcquirer(
        price_providers={},
        fx_providers={ExchangeRateSource.twelve_data: provider},
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        evidence_policy=DEFAULT_MARKET_EVIDENCE_POLICY,
    ).acquire(
        scope=scope,
        states=states,
        requested_at=(_POINT_AT,),
        subdaily_at=(_POINT_AT,),
    )
    value = build_history_snapshot_series_materialization_input(
        job_id="history-job",
        replay_scope=scope,
        states=states,
        market=replace(market, metric_rates=()),
        calculation_version=1,
        calculated_at=_POINT_AT,
        created_at=_POINT_AT,
    )

    with pytest.raises(SnapshotHistorySeriesMaterializationError):
        materialize_history_snapshot_series(value)


@pytest.mark.asyncio
async def test_closed_position_requests_acquisition_fx_without_snapshot_cost_fx() -> None:
    def trade(event_id: str, *, incoming: bool, at: datetime) -> InvestmentEventRoot:
        return InvestmentEventRoot(
            event_id=event_id,
            account_id=_ACCOUNT_ID,
            event_type=InvestmentEventType.trade,
            event_date=at,
            movements=(
                HoldingPersistenceMovement(
                    movement_id=f"{event_id}-asset",
                    event_id=event_id,
                    account_id=_ACCOUNT_ID,
                    kind=InvestmentMovementKind.asset,
                    direction=(
                        MovementDirection.incoming if incoming else MovementDirection.outgoing
                    ),
                    quantity=Decimal("1"),
                    currency="USD",
                    asset_id="asset",
                    listing_id="listing",
                    listing_asset_id="asset",
                    source_symbol="ABC",
                    source_asset_type=AssetType.stock,
                    price_per_unit=Decimal("100"),
                    value_amount=Decimal("100"),
                    value_currency="USD",
                    listing_currency="USD",
                ),
                HoldingPersistenceMovement(
                    movement_id=f"{event_id}-cash",
                    event_id=event_id,
                    account_id=_ACCOUNT_ID,
                    kind=InvestmentMovementKind.cash,
                    direction=(
                        MovementDirection.outgoing if incoming else MovementDirection.incoming
                    ),
                    quantity=Decimal("100"),
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

    original = _scope()
    account = original.accounts[0]
    sold_at = _EVENT_AT.replace(hour=11)
    scope = replace(
        original,
        accounts=(
            replace(
                account,
                account_type=AccountType.broker,
                roots=(
                    trade("buy", incoming=True, at=_EVENT_AT),
                    trade("sell", incoming=False, at=sold_at),
                ),
                canonical_revision=FrozenCanonicalRevision(
                    last_revision=2,
                    last_investment_revision=2,
                    holding_revision=0,
                ),
            ),
        ),
    )
    states = {
        _POINT_AT: {
            _ACCOUNT_ID: AccountReplayState(
                account_id=_ACCOUNT_ID,
                account_type=AccountType.broker,
                account_currency="USD",
                active=True,
            )
        }
    }
    provider = _FxProvider()
    market = await HistoricalMarketAcquirer(
        price_providers={},
        fx_providers={ExchangeRateSource.twelve_data: provider},
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
        evidence_policy=DEFAULT_MARKET_EVIDENCE_POLICY,
    ).acquire(
        scope=scope,
        states=states,
        requested_at=(_POINT_AT,),
        subdaily_at=(_POINT_AT,),
    )

    assert market.snapshot_rates == ()
    assert [(item.evidence_id, item.event_at) for item in market.metric_rates] == [
        ("cost:buy-asset", _EVENT_AT)
    ]
    assert [
        (item.from_currency, item.to_currency, item.requested_at) for item in provider.requirements
    ] == [("USD", "EUR", (_EVENT_AT,))]
    value = build_history_snapshot_series_materialization_input(
        job_id="closed-cost",
        replay_scope=scope,
        states=states,
        market=market,
        calculation_version=1,
        calculated_at=_POINT_AT,
        created_at=_POINT_AT,
    )
    command = materialize_history_snapshot_series(value)
    eur_evidence = next(
        item.evidence
        for item in command.points[0].account_evidence
        if item.evidence.valuation.currency == "EUR"
    )
    assert eur_evidence.valuation.investment_cost_basis == Decimal(0)
    assert eur_evidence.selected_historical_exchange_rate_ids == (market.metric_rates[0].rate_id,)
