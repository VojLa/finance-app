from __future__ import annotations

from datetime import datetime
from decimal import Decimal, localcontext

import pytest

from app.db.models.common import MONEY
from app.db.models.enums import (
    AccountType,
    AssetType,
    ExchangeRateSource,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.net_worth.evidence_service import (
    CompleteNetWorthEvidence,
    SelectedAccountSnapshotIdentity,
)
from app.modules.net_worth.persistence_projection import (
    NetWorthSnapshotPersistenceMetadata,
    build_net_worth_snapshot_persistence_projection,
)
from app.modules.net_worth.projection import (
    AccountNetWorthEvidence,
    NetWorthCurrencyAmount,
    NetWorthProjectionInput,
    build_net_worth_projection,
)
from app.modules.snapshot_refresh.version import (
    CURRENT_COORDINATED_SNAPSHOT_CALCULATION_VERSION,
    current_coordinated_snapshot_calculation_version,
)
from app.modules.snapshots.account_projection import (
    AccountSnapshotProjectionInput,
    AccountSnapshotProjectionStateError,
    CurrencyAmount,
    SelectedExchangeRateEvidence,
    SelectedPriceEvidence,
    SnapshotHoldingEvidence,
    build_account_snapshot_projection,
    convert_currency_amount,
)
from app.modules.snapshots.calculation import (
    DerivedSnapshotCalculationError,
    multiply_derived_snapshot_values,
    round_derived_snapshot_value,
)
from app.modules.snapshots.evidence_service import (
    CompleteAccountSnapshotEvidence,
    ExactSnapshotMetric,
)
from app.modules.snapshots.financial_metrics import (
    HistoricalMetricEvidence,
    HistoricalMetricKind,
    SelectedHistoricalRate,
    build_financial_metrics,
)
from app.modules.snapshots.persistence_projection import (
    AccountSnapshotPersistenceMetadata,
    build_account_snapshot_persistence_projection,
)

SNAPSHOT_AT = datetime(2026, 8, 19, 12, 0)


def _valuation(*, output_currency: str = "CZK"):
    holding = SnapshotHoldingEvidence(
        holding_id="holding-vuaa",
        account_id="account-vuaa",
        asset_id="asset-vuaa",
        listing_id="listing-vuaa",
        listing_asset_id="asset-vuaa",
        symbol="VUAA",
        asset_type=AssetType.etf,
        quantity=Decimal("6.6328245400"),
        average_buy_price=Decimal("101.3813851776"),
        cost_currency="EUR",
        cost_basis_by_currency=(CurrencyAmount("EUR", Decimal("672.4507768348")),),
    )
    price = SelectedPriceEvidence(
        price_id="price-vuaa",
        asset_id="asset-vuaa",
        listing_id="listing-vuaa",
        symbol="VUAA",
        price=Decimal("128.0400000000"),
        currency="EUR",
        source=PriceSource.yahoo_finance,
        timestamp=SNAPSHOT_AT,
    )
    rates: tuple[SelectedExchangeRateEvidence, ...] = ()
    if output_currency != "EUR":
        rates = (
            SelectedExchangeRateEvidence(
                rate_id="rate-eur-czk",
                base_currency="EUR",
                quote_currency="CZK",
                rate=Decimal("24.17690000"),
                source=ExchangeRateSource.yahoo_finance,
                timestamp=SNAPSHOT_AT,
            ),
        )
    return build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id="account-vuaa",
            account_type=AccountType.broker,
            account_currency="EUR",
            output_currency=output_currency,
            snapshot_timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.manual_recalculation,
            calculation_version=2,
            holdings=(holding,),
            prices=(price,),
            exchange_rates=rates,
            cash_balances=(),
            liabilities=(),
        )
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (Decimal("1.2345675"), Decimal("1.234568")),
        (Decimal("1.2345685"), Decimal("1.234568")),
        (Decimal("-1.2345675"), Decimal("-1.234568")),
        (Decimal("-1.2345685"), Decimal("-1.234568")),
    ],
)
def test_derived_rounding_is_half_even_and_global_context_independent(
    raw: Decimal,
    expected: Decimal,
) -> None:
    with localcontext() as context:
        context.prec = 7
        assert round_derived_snapshot_value(raw, MONEY) == expected


def test_derived_rounding_rejects_nonzero_underflow_and_overflow() -> None:
    with pytest.raises(DerivedSnapshotCalculationError):
        round_derived_snapshot_value(Decimal("0.0000001"), MONEY)
    with pytest.raises(DerivedSnapshotCalculationError):
        multiply_derived_snapshot_values(Decimal("999999999999"), Decimal("1000000"), MONEY)
    with pytest.raises(AccountSnapshotProjectionStateError):
        convert_currency_amount(
            Decimal("0.0000001"),
            base_currency="EUR",
            output_currency="EUR",
            rates={},
            numeric=MONEY,
        )


def test_live_vuaa_snapshot_rounds_only_derived_boundaries() -> None:
    primary = _valuation()
    companion = _valuation(output_currency="EUR")

    assert primary.items[0].native_value == Decimal("849.2668541016")
    assert primary.items[0].value == primary.investment_value == Decimal("20532.639805")
    assert primary.items[0].cost_basis == primary.investment_cost_basis == Decimal("16257.775186")
    assert primary.investment_value_by_currency == (
        CurrencyAmount("EUR", Decimal("849.2668541016")),
    )
    assert primary.investment_cost_basis_by_currency == (
        CurrencyAmount("EUR", Decimal("672.4507768348")),
    )
    assert companion.items[0].value == Decimal("849.266854")
    assert companion.items[0].cost_basis == Decimal("672.450777")


def test_multi_component_costs_and_historical_metrics_use_money_boundaries() -> None:
    holding = SnapshotHoldingEvidence(
        holding_id="holding-mixed",
        account_id="account-mixed",
        asset_id="asset-mixed",
        listing_id="listing-mixed",
        listing_asset_id="asset-mixed",
        symbol="MIX",
        asset_type=AssetType.etf,
        quantity=Decimal("1.0000000000"),
        average_buy_price=Decimal("2.0000000000"),
        cost_currency="EUR",
        cost_basis_by_currency=(
            CurrencyAmount("EUR", Decimal("1.0000000001")),
            CurrencyAmount("USD", Decimal("1.0000000001")),
        ),
    )
    valuation = build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id="account-mixed",
            account_type=AccountType.broker,
            account_currency="CZK",
            output_currency="CZK",
            snapshot_timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.manual_recalculation,
            calculation_version=2,
            holdings=(holding,),
            prices=(
                SelectedPriceEvidence(
                    price_id="price-mixed",
                    asset_id="asset-mixed",
                    listing_id="listing-mixed",
                    symbol="MIX",
                    price=Decimal("3.0000000000"),
                    currency="EUR",
                    source=PriceSource.yahoo_finance,
                    timestamp=SNAPSHOT_AT,
                ),
            ),
            exchange_rates=(
                SelectedExchangeRateEvidence(
                    "rate-eur-czk",
                    "EUR",
                    "CZK",
                    Decimal("24.17690000"),
                    ExchangeRateSource.yahoo_finance,
                    SNAPSHOT_AT,
                ),
                SelectedExchangeRateEvidence(
                    "rate-usd-czk",
                    "USD",
                    "CZK",
                    Decimal("22.00000000"),
                    ExchangeRateSource.yahoo_finance,
                    SNAPSHOT_AT,
                ),
            ),
            cash_balances=(),
            liabilities=(),
        )
    )
    metrics = build_financial_metrics(
        valuation=valuation,
        historical_evidence=(
            HistoricalMetricEvidence(
                "deposit", SNAPSHOT_AT, HistoricalMetricKind.net_deposit, "EUR", Decimal("1.000001")
            ),
        ),
        historical_rates=(
            SelectedHistoricalRate(
                "historical-eur-czk",
                "deposit",
                "EUR",
                "CZK",
                Decimal("24.17690000"),
                SNAPSHOT_AT,
            ),
        ),
    )

    assert valuation.items[0].cost_basis == Decimal("46.176900")
    assert valuation.investment_cost_basis == Decimal("46.176900")
    assert metrics.net_deposits_value == Decimal("24.176924")


def test_persistence_preserves_native_quantity_breakdown_beside_money_scalars() -> None:
    valuation = _valuation()
    unrealized = valuation.investment_value - valuation.investment_cost_basis
    evidence = CompleteAccountSnapshotEvidence(
        valuation=valuation,
        net_deposits=ExactSnapshotMetric(Decimal(0), ()),
        realized_pnl=ExactSnapshotMetric(Decimal(0), ()),
        unrealized_pnl=ExactSnapshotMetric(unrealized, None),
        fees=ExactSnapshotMetric(Decimal(0), ()),
        taxes=ExactSnapshotMetric(Decimal(0), ()),
        selected_price_ids=("price-vuaa",),
        selected_snapshot_exchange_rate_ids=("rate-eur-czk",),
        selected_historical_exchange_rate_ids=(),
    )
    projection = build_account_snapshot_persistence_projection(
        evidence,
        AccountSnapshotPersistenceMetadata(
            calculated_at=SNAPSHOT_AT,
            created_at=SNAPSHOT_AT,
            is_recalculated=True,
        ),
    )

    assert projection.snapshot.investment_value == Decimal("20532.639805")
    assert projection.snapshot.investment_value_by_currency.to_json() == {"EUR": "849.2668541016"}
    assert projection.items[0].cost_basis == Decimal("16257.775186")
    assert projection.items[0].price_source is PriceSource.yahoo_finance
    assert projection.items[0].price_timestamp == SNAPSHOT_AT
    assert projection == build_account_snapshot_persistence_projection(
        evidence,
        AccountSnapshotPersistenceMetadata(
            calculated_at=SNAPSHOT_AT,
            created_at=SNAPSHOT_AT,
            is_recalculated=True,
        ),
    )


def test_net_worth_persistence_accepts_native_quantity_breakdown_and_replays() -> None:
    valuation = _valuation()
    net_worth = build_net_worth_projection(
        NetWorthProjectionInput(
            user_id="user-vuaa",
            timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.minute,
            currency="CZK",
            calculation_version=2,
            account_snapshots=(
                AccountNetWorthEvidence(
                    snapshot_id="account-snapshot-vuaa",
                    account_id="account-vuaa",
                    account_type=AccountType.broker,
                    account_currency="EUR",
                    snapshot_currency="CZK",
                    timestamp=SNAPSHOT_AT,
                    granularity=SnapshotGranularity.minute,
                    total_value=valuation.total_value,
                    cash_value=valuation.cash_value,
                    investment_value=valuation.investment_value,
                    liabilities_value=valuation.liabilities_value,
                    cash_value_by_currency=(),
                    investment_value_by_currency=(
                        NetWorthCurrencyAmount("EUR", Decimal("849.2668541016")),
                    ),
                    liabilities_value_by_currency=(),
                ),
            ),
        )
    )

    assert net_worth.portfolio_value_by_currency is not None
    evidence = CompleteNetWorthEvidence(
        projection=net_worth,
        selected_account_ids=("account-vuaa",),
        selected_account_snapshot_ids=("account-snapshot-vuaa",),
        selected_identities=(
            SelectedAccountSnapshotIdentity("account-vuaa", "account-snapshot-vuaa"),
        ),
    )
    metadata = NetWorthSnapshotPersistenceMetadata(
        source=SnapshotSource.manual_recalculation,
        calculated_at=SNAPSHOT_AT,
        created_at=SNAPSHOT_AT,
        is_recalculated=True,
    )
    first = build_net_worth_snapshot_persistence_projection(evidence, metadata)
    second = build_net_worth_snapshot_persistence_projection(evidence, metadata)

    assert first == second
    assert first.snapshot.portfolio_value == Decimal("20532.639805")
    assert first.snapshot.portfolio_value_by_currency is not None
    assert first.snapshot.portfolio_value_by_currency.to_json() == {"EUR": "849.2668541016"}


def test_current_coordinated_version_is_three() -> None:
    assert CURRENT_COORDINATED_SNAPSHOT_CALCULATION_VERSION == 3
    assert current_coordinated_snapshot_calculation_version() == 3
