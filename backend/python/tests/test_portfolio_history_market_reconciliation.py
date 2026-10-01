from datetime import datetime
from decimal import Decimal

from app.db.models.enums import ExchangeRateSource, PriceSource
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.modules.fx.models import ExchangeRateObservation
from app.modules.market_data.writer import exchange_rate_id, price_snapshot_id
from app.modules.portfolio_history.builder.executor import (
    _reconcile_historical_market_selection,
)
from app.modules.portfolio_history.builder.market import (
    HistoricalMarketSelection,
    SelectedHistoricalMetricRate,
    SelectedHistoricalPrice,
    SelectedHistoricalRate,
    SelectedHistoricalSnapshotRate,
)
from app.modules.portfolio_history_rebuild.repository import FrozenListingIdentity
from app.modules.prices.models import PriceObservation

AT = datetime(2026, 9, 29)


def test_persisted_market_evidence_remains_authoritative_after_provider_revision() -> None:
    fetched_price = PriceObservation(
        asset_id="asset-btc",
        listing_id="listing-btc",
        provider=PriceSource.yahoo_finance,
        provider_symbol="BTC-USD",
        price=Decimal("70000"),
        currency="USD",
        observed_at=AT,
    )
    persisted_price_observation = PriceObservation(
        asset_id="asset-btc",
        listing_id="listing-btc",
        provider=PriceSource.yahoo_finance,
        provider_symbol="BTC-USD",
        price=Decimal("69999"),
        currency="USD",
        observed_at=AT,
    )
    fetched_rate = ExchangeRateObservation(
        from_currency="USD",
        to_currency="CZK",
        provider=ExchangeRateSource.yahoo_finance,
        rate=Decimal("21.5"),
        effective_at=AT,
    )
    persisted_rate_observation = ExchangeRateObservation(
        from_currency="USD",
        to_currency="CZK",
        provider=ExchangeRateSource.yahoo_finance,
        rate=Decimal("21.4"),
        effective_at=AT,
    )
    listing = FrozenListingIdentity(
        listing_id="listing-btc",
        evidence_listing_id="listing-btc",
        asset_id="asset-btc",
        symbol="BTC",
        name="Bitcoin",
        asset_type="crypto",
        currency="CZK",
        price_currency="USD",
        provider=PriceSource.yahoo_finance,
        provider_symbol="BTC-USD",
    )
    fetched_price_id = price_snapshot_id(fetched_price)
    fetched_rate_id = exchange_rate_id(fetched_rate)
    selection = HistoricalMarketSelection(
        prices=(
            SelectedHistoricalPrice(
                account_id="account-1",
                through=AT,
                listing=listing,
                price_id=fetched_price_id,
                observation=fetched_price,
            ),
        ),
        rates=(
            SelectedHistoricalRate(
                account_id="account-1",
                through=AT,
                rate_id=fetched_rate_id,
                observation=fetched_rate,
                consumed=True,
            ),
        ),
        price_observations=(fetched_price,),
        rate_observations=(fetched_rate,),
        provider_call_count=2,
        snapshot_rates=(
            SelectedHistoricalSnapshotRate(
                account_id="account-1",
                through=AT,
                output_currency="CZK",
                rate_id=fetched_rate_id,
                observation=fetched_rate,
            ),
        ),
        metric_rates=(
            SelectedHistoricalMetricRate(
                account_id="account-1",
                evidence_id="cost:movement-1",
                event_at=AT,
                output_currency="CZK",
                rate_id=fetched_rate_id,
                observation=fetched_rate,
            ),
        ),
    )
    persisted_price = PriceSnapshotModel(
        id=price_snapshot_id(persisted_price_observation),
        asset_id="asset-btc",
        listing_id="listing-btc",
        price=persisted_price_observation.price,
        currency="USD",
        source=PriceSource.yahoo_finance,
        timestamp=AT,
        created_at=AT,
        provider_symbol="BTC-USD",
    )
    persisted_rate = ExchangeRateModel(
        id=exchange_rate_id(persisted_rate_observation),
        from_currency="USD",
        to_currency="CZK",
        rate=persisted_rate_observation.rate,
        date=AT,
        source=ExchangeRateSource.yahoo_finance,
        created_at=AT,
    )

    reconciled = _reconcile_historical_market_selection(
        selection,
        persisted_prices=(persisted_price,),
        persisted_rates=(persisted_rate,),
    )

    expected_price_id = price_snapshot_id(persisted_price_observation)
    expected_rate_id = exchange_rate_id(persisted_rate_observation)
    assert reconciled.price_observations == ()
    assert reconciled.prices[0].price_id == expected_price_id
    assert reconciled.prices[0].observation == persisted_price_observation
    assert reconciled.rate_observations == ()
    assert reconciled.rates[0].rate_id == expected_rate_id
    assert reconciled.snapshot_rates[0].rate_id == expected_rate_id
    assert reconciled.metric_rates[0].rate_id == expected_rate_id
