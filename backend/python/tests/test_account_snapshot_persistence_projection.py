from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy import Numeric, inspect

from app.db.models.common import MONEY, PERCENTAGE, QUANTITY
from app.db.models.enums import (
    AccountType,
    AssetType,
    ExchangeRateSource,
    LiabilityBalanceSource,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.modules.snapshots import (
    AccountSnapshotPersistenceMetadata,
    AccountSnapshotPersistenceProjectionError,
    ExpectedAccountSnapshotPersistence,
    build_account_snapshot_persistence_projection,
)
from app.modules.snapshots.account_projection import (
    AccountSnapshotProjectionInput,
    CashBalanceEvidence,
    CurrencyAmount,
    ExpectedAccountSnapshotValuation,
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

SNAPSHOT_AT = datetime(2026, 7, 27, 10, 15)
CALCULATED_AT = datetime(2026, 7, 27, 10, 20, 0, 123000)
CREATED_AT = datetime(2026, 7, 27, 10, 21, 0, 456000)


def _holding(
    *,
    holding_id: str = "holding-1",
    asset_id: str = "asset-1",
    listing_id: str = "listing-1",
    symbol: str = "VWCE",
    quantity: Decimal = Decimal("2"),
    average_buy_price: Decimal = Decimal("80"),
    currency: str = "EUR",
) -> SnapshotHoldingEvidence:
    return SnapshotHoldingEvidence(
        holding_id=holding_id,
        account_id="account-1",
        asset_id=asset_id,
        listing_id=listing_id,
        listing_asset_id=asset_id,
        symbol=symbol,
        asset_type=AssetType.etf,
        quantity=quantity,
        average_buy_price=average_buy_price,
        cost_currency=currency,
    )


def _price(
    *,
    price_id: str = "price-1",
    asset_id: str = "asset-1",
    listing_id: str = "listing-1",
    symbol: str = "VWCE",
    price: Decimal = Decimal("100"),
    currency: str = "EUR",
) -> SelectedPriceEvidence:
    return SelectedPriceEvidence(
        price_id=price_id,
        asset_id=asset_id,
        listing_id=listing_id,
        symbol=symbol,
        price=price,
        currency=currency,
        source=PriceSource.broker,
        timestamp=datetime(2026, 7, 27, 10, 0),
    )


def _rate(
    currency: str,
    value: Decimal,
    *,
    rate_id: str | None = None,
) -> SelectedExchangeRateEvidence:
    return SelectedExchangeRateEvidence(
        rate_id=rate_id or f"rate-{currency.lower()}",
        base_currency=currency,
        quote_currency="CZK",
        rate=value,
        source=ExchangeRateSource.ecb,
        timestamp=datetime(2026, 7, 27, 9, 0),
    )


def _valuation(
    *,
    holdings: tuple[SnapshotHoldingEvidence, ...] | None = None,
    prices: tuple[SelectedPriceEvidence, ...] | None = None,
    rates: tuple[SelectedExchangeRateEvidence, ...] | None = None,
    cash: Decimal = Decimal("100"),
) -> ExpectedAccountSnapshotValuation:
    selected_holdings = holdings if holdings is not None else (_holding(),)
    selected_prices = prices if prices is not None else (_price(),)
    selected_rates = rates if rates is not None else (_rate("EUR", Decimal("25")),)
    return build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id="account-1",
            account_type=AccountType.broker,
            account_currency="CZK",
            output_currency="CZK",
            snapshot_timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.manual_recalculation,
            calculation_version=1,
            holdings=selected_holdings,
            prices=selected_prices,
            exchange_rates=selected_rates,
            cash_balances=(
                CashBalanceEvidence(
                    balance_id="cash-czk",
                    account_id="account-1",
                    currency="CZK",
                    amount=cash,
                    timestamp=SNAPSHOT_AT,
                ),
            ),
            liabilities=(),
        )
    )


def _liability_valuation(
    *,
    account_type: AccountType = AccountType.loan,
    amount: Decimal = Decimal("115.000000"),
) -> ExpectedAccountSnapshotValuation:
    return build_account_snapshot_projection(
        AccountSnapshotProjectionInput(
            account_id="account-1",
            account_type=account_type,
            account_currency="CZK",
            output_currency="CZK",
            snapshot_timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.minute,
            source=SnapshotSource.manual_recalculation,
            calculation_version=1,
            holdings=(),
            prices=(),
            exchange_rates=(),
            cash_balances=(),
            liabilities=(
                LiabilityBalanceEvidence(
                    liability_id="liability-balance-1",
                    account_id="account-1",
                    currency="CZK",
                    amount=amount,
                    timestamp=datetime(2026, 7, 27, 10, 0),
                ),
            ),
        )
    )


def _liability_evidence(
    *,
    account_type: AccountType = AccountType.loan,
    amount: Decimal = Decimal("115.000000"),
) -> CompleteAccountSnapshotEvidence:
    zero = ExactSnapshotMetric(Decimal(0), ())
    return CompleteAccountSnapshotEvidence(
        valuation=_liability_valuation(account_type=account_type, amount=amount),
        net_deposits=zero,
        realized_pnl=zero,
        unrealized_pnl=zero,
        fees=zero,
        taxes=zero,
        selected_price_ids=(),
        selected_snapshot_exchange_rate_ids=(),
        selected_historical_exchange_rate_ids=(),
        selected_liability_balance_id="liability-balance-1",
        selected_liability_effective_at=datetime(2026, 7, 27, 10, 0),
        selected_liability_source=LiabilityBalanceSource.statement,
    )


def _evidence(
    valuation: ExpectedAccountSnapshotValuation | None = None,
    *,
    price_ids: tuple[str, ...] = ("price-1",),
    net_deposits: object | None = None,
    realized_pnl: object | None = None,
    unrealized_pnl: object | None = None,
    fees: object | None = None,
    taxes: object | None = None,
    historical_rate_ids: tuple[str, ...] = ("historical-eur",),
) -> CompleteAccountSnapshotEvidence:
    selected = valuation or _valuation()
    unrealized = selected.investment_value - selected.investment_cost_basis
    return CompleteAccountSnapshotEvidence(
        valuation=selected,
        net_deposits=cast(
            Any,
            net_deposits
            if net_deposits is not None
            else ExactSnapshotMetric(Decimal("1000"), (CurrencyAmount("CZK", Decimal("1000")),)),
        ),
        realized_pnl=cast(
            Any,
            realized_pnl
            if realized_pnl is not None
            else ExactSnapshotMetric(Decimal("-50"), (CurrencyAmount("EUR", Decimal("-2")),)),
        ),
        unrealized_pnl=cast(
            Any,
            unrealized_pnl if unrealized_pnl is not None else ExactSnapshotMetric(unrealized, None),
        ),
        fees=cast(
            Any,
            fees
            if fees is not None
            else ExactSnapshotMetric(Decimal("10"), (CurrencyAmount("EUR", Decimal("0.4")),)),
        ),
        taxes=cast(
            Any,
            taxes
            if taxes is not None
            else ExactSnapshotMetric(Decimal("5"), (CurrencyAmount("CZK", Decimal("5")),)),
        ),
        selected_price_ids=price_ids,
        selected_snapshot_exchange_rate_ids=tuple(rate.rate_id for rate in selected.exchange_rates),
        selected_historical_exchange_rate_ids=historical_rate_ids,
    )


def _metadata(**changes: object) -> AccountSnapshotPersistenceMetadata:
    return cast(
        AccountSnapshotPersistenceMetadata,
        cast(Any, replace)(
            AccountSnapshotPersistenceMetadata(
                calculated_at=CALCULATED_AT,
                created_at=CREATED_AT,
                is_recalculated=True,
            ),
            **changes,
        ),
    )


def _project(
    evidence: CompleteAccountSnapshotEvidence | None = None,
    metadata: AccountSnapshotPersistenceMetadata | None = None,
) -> ExpectedAccountSnapshotPersistence:
    return build_account_snapshot_persistence_projection(
        evidence or _evidence(),
        metadata or _metadata(),
    )


def _two_holding_valuation() -> ExpectedAccountSnapshotValuation:
    return _valuation(
        holdings=(
            _holding(
                holding_id="holding-2",
                asset_id="asset-2",
                listing_id="listing-2",
                symbol="USDASSET",
                quantity=Decimal("1"),
                average_buy_price=Decimal("100"),
                currency="USD",
            ),
            _holding(
                quantity=Decimal("1"),
            ),
        ),
        prices=(
            _price(
                price_id="price-2",
                asset_id="asset-2",
                listing_id="listing-2",
                symbol="USDASSET",
                price=Decimal("125"),
                currency="USD",
            ),
            _price(),
        ),
        rates=(
            _rate("USD", Decimal("20")),
            _rate("EUR", Decimal("25")),
        ),
        cash=Decimal(0),
    )


def test_exact_investment_snapshot_maps_every_physical_field() -> None:
    result = _project()
    row = result.snapshot
    item = result.items[0]

    assert row.account_id == "account-1"
    assert row.timestamp == SNAPSHOT_AT
    assert row.granularity is SnapshotGranularity.minute
    assert row.source is SnapshotSource.manual_recalculation
    assert row.currency == "CZK"
    assert row.cash_value == Decimal("100")
    assert row.investment_value == Decimal("5000")
    assert row.investment_cost_basis == Decimal("4000")
    assert row.net_deposits_value == Decimal("1000")
    assert row.realized_pnl_value == Decimal("-50")
    assert row.unrealized_pnl_value == Decimal("1000")
    assert row.fees_value == Decimal("10")
    assert row.taxes_value == Decimal("5")
    assert row.liabilities_value == Decimal(0)
    assert row.total_value == Decimal("5100")
    assert row.is_recalculated is True
    assert row.calculated_at == CALCULATED_AT
    assert row.created_at == CREATED_AT
    assert row.calculation_version == 1

    assert item.snapshot_id == row.id
    assert item.asset_id == "asset-1"
    assert item.listing_id == "listing-1"
    assert item.symbol == "VWCE"
    assert item.quantity == Decimal("2")
    assert item.price_per_unit == Decimal("100")
    assert item.price_currency == "EUR"
    assert item.price_source is PriceSource.broker
    assert item.price_timestamp == datetime(2026, 7, 27, 10, 0)
    assert item.native_value == Decimal("200")
    assert item.value_currency == "EUR"
    assert item.value == Decimal("5000")
    assert item.native_cost_basis == Decimal("160")
    assert item.native_cost_currency == "EUR"
    assert item.cost_basis == Decimal("4000")
    assert item.cost_currency == "CZK"
    assert item.allocation_pct == Decimal("100")
    assert item.created_at == CREATED_AT


@pytest.mark.parametrize(
    "account_type",
    [AccountType.credit_card, AccountType.loan, AccountType.mortgage],
)
def test_liability_snapshot_maps_positive_liability_and_negative_total(
    account_type: AccountType,
) -> None:
    result = _project(_liability_evidence(account_type=account_type))

    assert result.items == ()
    assert result.snapshot.cash_value == Decimal(0)
    assert result.snapshot.investment_value == Decimal(0)
    assert result.snapshot.investment_cost_basis == Decimal(0)
    assert result.snapshot.liabilities_value == Decimal("115.000000")
    assert result.snapshot.total_value == Decimal("-115.000000")
    assert result.snapshot.net_deposits_value == Decimal(0)
    assert result.snapshot.realized_pnl_value == Decimal(0)
    assert result.snapshot.unrealized_pnl_value == Decimal(0)
    assert result.snapshot.fees_value == Decimal(0)
    assert result.snapshot.taxes_value == Decimal(0)
    assert result.snapshot.exchange_rates.to_json() == {
        "version": 1,
        "snapshotRates": [],
        "historicalRateIds": [],
    }
    assert result.audit.selected_price_ids == ()
    assert result.audit.selected_liability_balance_id == "liability-balance-1"
    assert result.audit.selected_liability_effective_at == datetime(2026, 7, 27, 10, 0)
    assert result.audit.selected_liability_source is LiabilityBalanceSource.statement


def test_fully_repaid_liability_is_distinct_from_missing_evidence() -> None:
    result = _project(_liability_evidence(amount=Decimal(0)))

    assert result.snapshot.liabilities_value == Decimal(0)
    assert result.snapshot.total_value == Decimal(0)
    assert result.items == ()
    assert result.audit.selected_liability_balance_id == "liability-balance-1"


def test_liability_physical_invariant_tamper_fails_closed() -> None:
    evidence = _liability_evidence()

    with pytest.raises(AccountSnapshotPersistenceProjectionError):
        _project(
            replace(
                evidence,
                valuation=replace(evidence.valuation, total_value=Decimal("115")),
            )
        )


def test_multiple_items_are_sorted_and_ids_are_deterministic() -> None:
    valuation = _two_holding_valuation()
    permuted = replace(
        valuation,
        items=tuple(reversed(valuation.items)),
        exchange_rates=tuple(reversed(valuation.exchange_rates)),
    )
    first = _project(
        _evidence(
            valuation,
            price_ids=("price-2", "price-1"),
            historical_rate_ids=("history-b", "history-a"),
        )
    )
    second = _project(
        _evidence(
            permuted,
            price_ids=("price-1", "price-2"),
            historical_rate_ids=("history-a", "history-b"),
        )
    )

    assert first == second
    assert [item.listing_id for item in first.items] == ["listing-1", "listing-2"]
    assert first.snapshot.id == "1889b306-724d-5732-b030-f25c5f9d07e5"
    assert [item.id for item in first.items] == [
        "e80d9076-f647-5c83-a05c-edde28e1adac",
        "9307cf70-d764-5b83-90f5-fbdc9d3ce904",
    ]
    assert first.audit.selected_price_ids == ("price-1", "price-2")
    assert first.audit.selected_historical_exchange_rate_ids == ("history-a", "history-b")


@pytest.mark.parametrize(
    "field_name",
    ["net_deposits", "realized_pnl", "unrealized_pnl", "fees", "taxes"],
)
def test_each_unsupported_metric_rejects_the_complete_projection(field_name: str) -> None:
    evidence = _evidence()
    corrupted = cast(
        CompleteAccountSnapshotEvidence,
        cast(Any, replace)(
            evidence,
            **{
                field_name: UnsupportedSnapshotMetric(
                    SnapshotMetricUnsupportedReason.fee_classification_unavailable
                )
            },
        ),
    )

    with pytest.raises(
        AccountSnapshotPersistenceProjectionError,
        match=r"Account snapshot evidence is not physically persistable\.",
    ):
        _project(corrupted)


def test_cash_account_evidence_with_structural_unrealized_zero_is_not_persistable() -> None:
    valuation = _valuation(holdings=(), prices=(), rates=(), cash=Decimal("75"))
    unsupported = UnsupportedSnapshotMetric(
        SnapshotMetricUnsupportedReason.external_cash_flow_classification_unavailable
    )
    evidence = _evidence(
        valuation,
        price_ids=(),
        historical_rate_ids=(),
        net_deposits=unsupported,
        realized_pnl=UnsupportedSnapshotMetric(
            SnapshotMetricUnsupportedReason.realized_pnl_evidence_unavailable
        ),
        unrealized_pnl=ExactSnapshotMetric(Decimal(0), ()),
        fees=UnsupportedSnapshotMetric(
            SnapshotMetricUnsupportedReason.fee_classification_unavailable
        ),
        taxes=UnsupportedSnapshotMetric(
            SnapshotMetricUnsupportedReason.tax_classification_unavailable
        ),
    )

    with pytest.raises(AccountSnapshotPersistenceProjectionError):
        _project(evidence)


def test_breakdowns_use_sorted_fixed_scale_decimal_strings() -> None:
    evidence = _evidence(
        net_deposits=ExactSnapshotMetric(
            Decimal("500"),
            (
                CurrencyAmount("USD", Decimal("-1.25")),
                CurrencyAmount("EUR", Decimal("20")),
            ),
        ),
        realized_pnl=ExactSnapshotMetric(
            Decimal("-50"),
            (CurrencyAmount("CZK", Decimal("-50")),),
        ),
    )
    row = _project(evidence).snapshot

    assert row.net_deposits_by_currency.to_json() == {
        "EUR": "20.000000",
        "USD": "-1.250000",
    }
    assert list(row.net_deposits_by_currency.to_json()) == ["EUR", "USD"]
    assert row.realized_pnl_by_currency.to_json() == {"CZK": "-50.000000"}
    assert row.unrealized_pnl_by_currency is None
    serialized = json.dumps(
        {
            "cash": row.cash_value_by_currency.to_json(),
            "investment": row.investment_value_by_currency.to_json(),
            "costBasis": row.investment_cost_basis_by_currency.to_json(),
            "netDeposits": row.net_deposits_by_currency.to_json(),
            "realizedPnl": row.realized_pnl_by_currency.to_json(),
            "unrealizedPnl": row.unrealized_pnl_by_currency,
            "fees": row.fees_by_currency.to_json(),
            "taxes": row.taxes_by_currency.to_json(),
            "exchangeRates": row.exchange_rates.to_json(),
        },
        sort_keys=True,
    )
    assert "Decimal" not in serialized
    assert "1.25E" not in serialized


@pytest.mark.parametrize(
    "breakdown",
    [
        (
            CurrencyAmount("EUR", Decimal("1")),
            CurrencyAmount("EUR", Decimal("2")),
        ),
        (CurrencyAmount("eur", Decimal("1")),),
        (CurrencyAmount("EUR", cast(Decimal, 1.0)),),
    ],
)
def test_malformed_metric_breakdown_fails_closed(
    breakdown: tuple[CurrencyAmount, ...],
) -> None:
    with pytest.raises(AccountSnapshotPersistenceProjectionError):
        _project(_evidence(net_deposits=ExactSnapshotMetric(Decimal(0), breakdown)))


def test_nonzero_metric_requires_native_breakdown() -> None:
    with pytest.raises(AccountSnapshotPersistenceProjectionError):
        _project(_evidence(net_deposits=ExactSnapshotMetric(Decimal("1"), ())))


def test_unavailable_unrealized_breakdown_remains_null_not_empty() -> None:
    row = _project().snapshot
    assert row.unrealized_pnl_by_currency is None
    assert row.model_values()["unrealized_pnl_by_currency"] is None


def test_exchange_rate_json_is_versioned_sorted_and_auditable() -> None:
    valuation = _two_holding_valuation()
    result = _project(
        _evidence(
            replace(valuation, exchange_rates=tuple(reversed(valuation.exchange_rates))),
            price_ids=("price-2", "price-1"),
            historical_rate_ids=("history-b", "history-a"),
        )
    )
    assert result.snapshot.exchange_rates.to_json() == {
        "version": 1,
        "snapshotRates": [
            {
                "rateId": "rate-eur",
                "from": "EUR",
                "to": "CZK",
                "rate": "25.00000000",
                "timestamp": "2026-07-27T09:00:00.000",
                "source": "ecb",
            },
            {
                "rateId": "rate-usd",
                "from": "USD",
                "to": "CZK",
                "rate": "20.00000000",
                "timestamp": "2026-07-27T09:00:00.000",
                "source": "ecb",
            },
        ],
        "historicalRateIds": ["history-a", "history-b"],
    }
    json.dumps(result.snapshot.exchange_rates.to_json())


def test_no_consumed_fx_still_has_versioned_empty_audit() -> None:
    valuation = _valuation(holdings=(), prices=(), rates=(), cash=Decimal(0))
    result = _project(_evidence(valuation, price_ids=(), historical_rate_ids=()))
    assert result.snapshot.exchange_rates.to_json() == {
        "version": 1,
        "snapshotRates": [],
        "historicalRateIds": [],
    }


@pytest.mark.parametrize(
    "mutator",
    [
        lambda valuation: replace(
            valuation,
            exchange_rates=(valuation.exchange_rates[0], valuation.exchange_rates[0]),
        ),
        lambda valuation: replace(
            valuation,
            exchange_rates=(replace(valuation.exchange_rates[0], base_currency="eur"),),
        ),
        lambda valuation: replace(
            valuation,
            exchange_rates=(replace(valuation.exchange_rates[0], rate=Decimal("0")),),
        ),
        lambda valuation: replace(
            valuation,
            exchange_rates=(
                replace(
                    valuation.exchange_rates[0],
                    timestamp=datetime(2026, 7, 27, 9, 0, 0, 1),
                ),
            ),
        ),
    ],
)
def test_malformed_consumed_rate_fails_closed(mutator: Any) -> None:
    valuation = mutator(_valuation())
    with pytest.raises(AccountSnapshotPersistenceProjectionError):
        _project(_evidence(valuation))


def test_rate_selection_time_is_not_re_evaluated_after_5i_b() -> None:
    valuation = _valuation()
    selected_later = replace(
        valuation.exchange_rates[0],
        timestamp=datetime(2026, 7, 27, 10, 16),
    )
    result = _project(_evidence(replace(valuation, exchange_rates=(selected_later,))))
    assert result.snapshot.exchange_rates.to_json() == {
        "historicalRateIds": ["historical-eur"],
        "snapshotRates": [
            {
                "from": "EUR",
                "rate": "25.00000000",
                "rateId": "rate-eur",
                "source": "ecb",
                "timestamp": "2026-07-27T10:16:00.000",
                "to": "CZK",
            }
        ],
        "version": 1,
    }


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda evidence: replace(
            evidence,
            valuation=replace(evidence.valuation, total_value=Decimal("999")),
        ),
        lambda evidence: replace(
            evidence,
            valuation=replace(
                evidence.valuation,
                items=(replace(evidence.valuation.items[0], value=Decimal("4999")),),
            ),
        ),
        lambda evidence: replace(
            evidence,
            valuation=replace(
                evidence.valuation,
                items=(replace(evidence.valuation.items[0], cost_basis=Decimal("3999")),),
            ),
        ),
        lambda evidence: replace(
            evidence,
            unrealized_pnl=ExactSnapshotMetric(Decimal("999"), None),
        ),
        lambda evidence: replace(
            evidence,
            valuation=replace(
                evidence.valuation,
                items=(replace(evidence.valuation.items[0], allocation_pct=Decimal("99")),),
            ),
        ),
        lambda evidence: replace(
            evidence,
            valuation=replace(
                evidence.valuation,
                items=(replace(evidence.valuation.items[0], value_currency="USD"),),
            ),
        ),
        lambda evidence: replace(
            evidence,
            valuation=replace(
                evidence.valuation,
                items=(evidence.valuation.items[0], evidence.valuation.items[0]),
                investment_value=evidence.valuation.investment_value * 2,
                investment_cost_basis=evidence.valuation.investment_cost_basis * 2,
                total_value=(
                    evidence.valuation.cash_value + evidence.valuation.investment_value * 2
                ),
            ),
            selected_price_ids=("price-1", "price-2"),
            unrealized_pnl=ExactSnapshotMetric(Decimal("2000"), None),
        ),
    ],
)
def test_cross_field_corruption_fails_closed(corrupt: Any) -> None:
    with pytest.raises(AccountSnapshotPersistenceProjectionError):
        _project(corrupt(_evidence()))


def test_all_output_items_use_the_generated_snapshot_identity() -> None:
    result = _project(
        _evidence(
            _two_holding_valuation(),
            price_ids=("price-1", "price-2"),
        )
    )
    assert {item.snapshot_id for item in result.items} == {result.snapshot.id}


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("cash_value", Decimal("1000000000000")),
        ("investment_value", Decimal("1000000000000")),
        ("investment_cost_basis", Decimal("1000000000000")),
        ("total_value", Decimal("1000000000000")),
    ],
)
def test_money_overflow_fails_closed(field_name: str, value: Decimal) -> None:
    evidence = _evidence()
    valuation = cast(
        ExpectedAccountSnapshotValuation,
        cast(Any, replace)(evidence.valuation, **{field_name: value}),
    )
    with pytest.raises(AccountSnapshotPersistenceProjectionError):
        _project(replace(evidence, valuation=valuation))


def test_maximum_money_is_exactly_serialized() -> None:
    maximum = Decimal("999999999999.999999")
    valuation = _valuation(holdings=(), prices=(), rates=(), cash=maximum)
    result = _project(_evidence(valuation, price_ids=(), historical_rate_ids=()))
    assert result.snapshot.cash_value == maximum
    assert result.snapshot.cash_value_by_currency.to_json() == {"CZK": "999999999999.999999"}


def test_quantity_overflow_and_percentage_over_scale_fail_closed() -> None:
    evidence = _evidence()
    overflow = replace(evidence.valuation.items[0], price_per_unit=Decimal("1E+18"))
    over_scale = replace(evidence.valuation.items[0], allocation_pct=Decimal("99.00001"))
    for item in (overflow, over_scale):
        with pytest.raises(AccountSnapshotPersistenceProjectionError):
            _project(replace(evidence, valuation=replace(evidence.valuation, items=(item,))))


def test_maximum_quantity_price_is_accepted_when_value_remains_money_exact() -> None:
    maximum = Decimal("999999999999999999")
    holding = _holding(quantity=Decimal("1"), average_buy_price=maximum)
    price = _price(price=maximum)
    valuation = _valuation(
        holdings=(holding,),
        prices=(price,),
        rates=(_rate("EUR", Decimal("0.00000100")),),
        cash=Decimal(0),
    )
    result = _project(_evidence(valuation))
    assert result.items[0].price_per_unit == maximum


@pytest.mark.parametrize(
    "metadata",
    [
        _metadata(calculated_at=datetime(2026, 7, 27, 10, 20, tzinfo=UTC)),
        _metadata(created_at=datetime(2026, 7, 27, 10, 20, 0, 1)),
        _metadata(is_recalculated=cast(bool, 1)),
    ],
)
def test_invalid_persistence_metadata_fails_closed(
    metadata: AccountSnapshotPersistenceMetadata,
) -> None:
    with pytest.raises(AccountSnapshotPersistenceProjectionError):
        _project(metadata=metadata)


def test_source_and_recalculation_flag_must_match_existing_project_rule() -> None:
    with pytest.raises(AccountSnapshotPersistenceProjectionError):
        _project(metadata=_metadata(is_recalculated=False))
    scheduled = replace(_evidence().valuation, source=SnapshotSource.scheduled)
    with pytest.raises(AccountSnapshotPersistenceProjectionError):
        _project(_evidence(scheduled), _metadata(is_recalculated=True))
    result = _project(_evidence(scheduled), _metadata(is_recalculated=False))
    assert result.snapshot.is_recalculated is False


@pytest.mark.parametrize("version", [0, -1, 2_147_483_648, True])
def test_invalid_calculation_version_fails_closed(version: object) -> None:
    evidence = _evidence()
    with pytest.raises(AccountSnapshotPersistenceProjectionError):
        _project(
            replace(
                evidence,
                valuation=replace(evidence.valuation, calculation_version=cast(int, version)),
            )
        )


def test_inputs_are_not_mutated_outputs_are_frozen_and_json_is_stable() -> None:
    evidence = _evidence()
    metadata = _metadata()
    original = deepcopy(evidence)
    first = _project(evidence, metadata)
    second = _project(evidence, metadata)

    assert first == second
    assert evidence == original
    assert json.dumps(first.snapshot.exchange_rates.to_json(), sort_keys=True) == json.dumps(
        second.snapshot.exchange_rates.to_json(), sort_keys=True
    )
    mutable_snapshot = cast(Any, first.snapshot)
    mutable_item = cast(Any, first.items[0])
    with pytest.raises(FrozenInstanceError):
        mutable_snapshot.cash_value = Decimal(0)
    with pytest.raises(FrozenInstanceError):
        mutable_item.value = Decimal(0)


def test_physical_row_contracts_match_all_and_only_sqlalchemy_columns() -> None:
    result = _project()
    snapshot_fields = {field.name for field in fields(result.snapshot)}
    item_fields = {field.name for field in fields(result.items[0])}
    snapshot_columns = {attribute.key for attribute in inspect(AccountSnapshotModel).column_attrs}
    item_columns = {attribute.key for attribute in inspect(AccountSnapshotItemModel).column_attrs}

    assert snapshot_fields == snapshot_columns
    assert item_fields == item_columns
    assert set(result.snapshot.model_values()) == snapshot_columns
    assert set(result.items[0].model_values()) == item_columns
    snapshot_model = AccountSnapshotModel(**result.snapshot.model_values())
    item_model = AccountSnapshotItemModel(**result.items[0].model_values())
    assert snapshot_model.net_deposits_value == Decimal("1000")
    assert item_model.snapshot_id == result.snapshot.id


def test_physical_numeric_and_nullability_contracts_match_models() -> None:
    snapshot_table = AccountSnapshotModel.__table__
    item_table = AccountSnapshotItemModel.__table__
    for name in (
        "cashValue",
        "investmentValue",
        "investmentCostBasis",
        "netDepositsValue",
        "realizedPnlValue",
        "unrealizedPnlValue",
        "feesValue",
        "taxesValue",
        "liabilitiesValue",
        "totalValue",
    ):
        numeric = cast(Numeric, snapshot_table.c[name].type)
        assert (numeric.precision, numeric.scale) == (MONEY.precision, MONEY.scale)
        assert snapshot_table.c[name].nullable is False
    for name in (
        "quantity",
        "pricePerUnit",
        "costBasis",
        "nativeValue",
        "nativeCostBasis",
    ):
        numeric = cast(Numeric, item_table.c[name].type)
        assert (numeric.precision, numeric.scale) == (QUANTITY.precision, QUANTITY.scale)
    allocation = cast(Numeric, item_table.c.allocationPct.type)
    assert (allocation.precision, allocation.scale) == (
        PERCENTAGE.precision,
        PERCENTAGE.scale,
    )
    assert item_table.c.assetId.nullable is True
    assert item_table.c.listingId.nullable is False
    assert snapshot_table.c.exchangeRates.nullable is True


def test_audit_metadata_is_not_invented_as_physical_columns() -> None:
    result = _project()
    values = result.snapshot.model_values()
    assert "selected_price_ids" not in values
    assert "selected_snapshot_exchange_rate_ids" not in values
    assert "selected_historical_exchange_rate_ids" not in values
    assert "liabilities_value_by_currency" not in values
