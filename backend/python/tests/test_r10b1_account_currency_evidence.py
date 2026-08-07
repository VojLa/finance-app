from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import cast

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
from app.modules.snapshots.account_projection import (
    AccountSnapshotProjectionInput,
    AccountSnapshotProjectionStateError,
    ExchangeRateConsumptionRole,
    SelectedExchangeRateEvidence,
    SelectedPriceEvidence,
    SnapshotHoldingEvidence,
    build_account_snapshot_projection,
    convert_currency_amount,
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

SNAPSHOT_AT = datetime(2036, 2, 3, 12)
EVENT_AT = datetime(2036, 1, 5, 9)


def _rate(
    rate_id: str,
    base: str,
    value: str,
    *,
    timestamp: datetime = SNAPSHOT_AT,
) -> SelectedExchangeRateEvidence:
    return SelectedExchangeRateEvidence(
        rate_id=rate_id,
        base_currency=base,
        quote_currency="CZK",
        rate=Decimal(value),
        source=ExchangeRateSource.cnb,
        timestamp=timestamp,
    )


def _mixed_valuation():
    return build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id="account-eur",
            account_type=AccountType.broker,
            account_currency="EUR",
            output_currency="EUR",
            snapshot_timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.manual_recalculation,
            calculation_version=1,
            holdings=(
                SnapshotHoldingEvidence(
                    holding_id="holding-1",
                    account_id="account-eur",
                    asset_id="asset-1",
                    listing_id="listing-1",
                    listing_asset_id="asset-1",
                    symbol="AAPL",
                    asset_type=AssetType.stock,
                    quantity=Decimal("2"),
                    average_buy_price=Decimal("80"),
                    cost_currency="EUR",
                ),
            ),
            prices=(
                SelectedPriceEvidence(
                    price_id="price-1",
                    asset_id="asset-1",
                    listing_id="listing-1",
                    symbol="AAPL",
                    price=Decimal("100"),
                    currency="USD",
                    source=PriceSource.twelve_data,
                    timestamp=SNAPSHOT_AT,
                ),
            ),
            exchange_rates=(
                _rate("eur-czk", "EUR", "25.00000000"),
                _rate("usd-czk", "USD", "23.00000000"),
            ),
            cash_balances=(),
            liabilities=(),
        )
    )


def test_mixed_native_account_uses_one_exact_czk_pivot_boundary() -> None:
    valuation = _mixed_valuation()

    assert valuation.currency == "EUR"
    assert valuation.investment_value == Decimal("184.000000")
    assert valuation.investment_cost_basis == Decimal("160.000000")
    assert valuation.total_value == Decimal("184.000000")
    assert valuation.items[0].value == Decimal("184.000000")
    assert valuation.items[0].cost_basis == Decimal("160.000000")
    assert valuation.items[0].cost_currency == "EUR"
    assert {rate.rate_id: rate.roles for rate in valuation.exchange_rates} == {
        "eur-czk": (ExchangeRateConsumptionRole.pivot_target,),
        "usd-czk": (ExchangeRateConsumptionRole.pivot_source,),
    }


def test_pivot_lineage_is_canonical_without_a_derived_provider_identity() -> None:
    valuation = _mixed_valuation()
    zero = ExactSnapshotMetric(Decimal(0), ())
    persistence = build_account_snapshot_persistence_projection(
        CompleteAccountSnapshotEvidence(
            valuation=valuation,
            net_deposits=zero,
            realized_pnl=zero,
            unrealized_pnl=ExactSnapshotMetric(Decimal("24.000000"), None),
            fees=zero,
            taxes=zero,
            selected_price_ids=("price-1",),
            selected_snapshot_exchange_rate_ids=("eur-czk", "usd-czk"),
            selected_historical_exchange_rate_ids=(),
        ),
        AccountSnapshotPersistenceMetadata(
            calculated_at=SNAPSHOT_AT,
            created_at=SNAPSHOT_AT,
            is_recalculated=True,
        ),
    )

    audit = persistence.snapshot.exchange_rates.to_json()
    assert audit["version"] == 2
    snapshot_rates = cast(list[dict[str, object]], audit["snapshotRates"])
    assert [(row["rateId"], row["from"], row["to"], row["roles"]) for row in snapshot_rates] == [
        ("eur-czk", "EUR", "CZK", ["pivot_target"]),
        ("usd-czk", "USD", "CZK", ["pivot_source"]),
    ]
    assert all(row["to"] == "CZK" for row in snapshot_rates)


def test_historical_metric_uses_event_date_source_and_target_pivot_legs() -> None:
    valuation = build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id="account-eur",
            account_type=AccountType.broker,
            account_currency="EUR",
            output_currency="EUR",
            snapshot_timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.manual_recalculation,
            calculation_version=1,
            holdings=(),
            prices=(),
            exchange_rates=(),
            cash_balances=(),
            liabilities=(),
        )
    )
    metrics = build_financial_metrics(
        valuation=valuation,
        historical_evidence=(
            HistoricalMetricEvidence(
                evidence_id="deposit-1",
                timestamp=EVENT_AT,
                kind=HistoricalMetricKind.net_deposit,
                currency="USD",
                amount=Decimal("10.000000"),
            ),
            HistoricalMetricEvidence(
                evidence_id="realized-1",
                timestamp=EVENT_AT,
                kind=HistoricalMetricKind.realized_pnl,
                currency="USD",
                amount=Decimal("-4.000000"),
            ),
            HistoricalMetricEvidence(
                evidence_id="fee-1",
                timestamp=EVENT_AT,
                kind=HistoricalMetricKind.fee,
                currency="USD",
                amount=Decimal("2.000000"),
            ),
            HistoricalMetricEvidence(
                evidence_id="tax-1",
                timestamp=EVENT_AT,
                kind=HistoricalMetricKind.tax,
                currency="USD",
                amount=Decimal("1.000000"),
            ),
        ),
        historical_rates=tuple(
            rate
            for evidence_id in ("deposit-1", "realized-1", "fee-1", "tax-1")
            for rate in (
                SelectedHistoricalRate(
                    rate_id="event-eur-czk",
                    evidence_id=evidence_id,
                    base_currency="EUR",
                    quote_currency="CZK",
                    rate=Decimal("20.00000000"),
                    timestamp=EVENT_AT,
                ),
                SelectedHistoricalRate(
                    rate_id="event-usd-czk",
                    evidence_id=evidence_id,
                    base_currency="USD",
                    quote_currency="CZK",
                    rate=Decimal("18.00000000"),
                    timestamp=EVENT_AT,
                ),
            )
        ),
    )

    assert metrics.net_deposits_value == Decimal("9.000000")
    assert metrics.realized_pnl_value == Decimal("-3.600000")
    assert metrics.fees_value == Decimal("1.800000")
    assert metrics.taxes_value == Decimal("0.900000")
    assert len(metrics.consumed_historical_exchange_rates) == 8
    assert {
        (rate.rate_id, rate.timestamp, rate.role)
        for rate in metrics.consumed_historical_exchange_rates
    } == {
        ("event-eur-czk", EVENT_AT, ExchangeRateConsumptionRole.pivot_target),
        ("event-usd-czk", EVENT_AT, ExchangeRateConsumptionRole.pivot_source),
    }


def test_nonrepresentable_pivot_result_fails_closed_without_rounding() -> None:
    with pytest.raises(AccountSnapshotProjectionStateError):
        convert_currency_amount(
            Decimal("1.000000"),
            base_currency="CZK",
            output_currency="EUR",
            rates={("EUR", "CZK"): Decimal("3.00000000")},
            numeric=MONEY,
        )
