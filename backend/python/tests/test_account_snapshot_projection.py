from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest

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
    CashBalanceEvidence,
    CurrencyAmount,
    LiabilityBalanceEvidence,
    SelectedExchangeRateEvidence,
    SelectedPriceEvidence,
    SnapshotHoldingEvidence,
    build_account_snapshot_projection,
)

SNAPSHOT_AT = datetime(2026, 7, 27, 10, 15)


def _holding(
    *,
    holding_id: str = "holding",
    account_id: str = "account",
    asset_id: str = "asset",
    listing_id: str = "listing",
    listing_asset_id: str | None = None,
    symbol: str = "VWCE",
    quantity: Decimal = Decimal("2"),
    average_buy_price: Decimal = Decimal("80"),
    cost_currency: str = "EUR",
) -> SnapshotHoldingEvidence:
    return SnapshotHoldingEvidence(
        holding_id=holding_id,
        account_id=account_id,
        asset_id=asset_id,
        listing_id=listing_id,
        listing_asset_id=listing_asset_id or asset_id,
        symbol=symbol,
        asset_type=AssetType.etf,
        quantity=quantity,
        average_buy_price=average_buy_price,
        cost_currency=cost_currency,
    )


def _price(
    *,
    price_id: str = "price",
    asset_id: str = "asset",
    listing_id: str = "listing",
    symbol: str = "VWCE",
    price: Decimal = Decimal("100"),
    currency: str = "EUR",
    source: PriceSource = PriceSource.broker,
    timestamp: datetime = datetime(2026, 7, 27, 10, 0),
) -> SelectedPriceEvidence:
    return SelectedPriceEvidence(
        price_id=price_id,
        asset_id=asset_id,
        listing_id=listing_id,
        symbol=symbol,
        price=price,
        currency=currency,
        source=source,
        timestamp=timestamp,
    )


def _rate(
    base: str,
    *,
    quote: str = "CZK",
    value: Decimal = Decimal("25"),
    rate_id: str | None = None,
    timestamp: datetime = datetime(2026, 7, 27, 9, 0),
) -> SelectedExchangeRateEvidence:
    return SelectedExchangeRateEvidence(
        rate_id=rate_id or f"rate-{base}-{quote}",
        base_currency=base,
        quote_currency=quote,
        rate=value,
        source=ExchangeRateSource.ecb,
        timestamp=timestamp,
    )


def _cash(
    currency: str = "CZK",
    amount: Decimal = Decimal("1000"),
    *,
    balance_id: str | None = None,
    account_id: str = "account",
    timestamp: datetime = datetime(2026, 7, 27, 10, 0),
) -> CashBalanceEvidence:
    return CashBalanceEvidence(
        balance_id=balance_id or f"cash-{currency}",
        account_id=account_id,
        currency=currency,
        amount=amount,
        timestamp=timestamp,
    )


def _liability(
    currency: str = "CZK",
    amount: Decimal = Decimal("500"),
    *,
    liability_id: str | None = None,
    account_id: str = "account",
    timestamp: datetime = datetime(2026, 7, 27, 10, 0),
) -> LiabilityBalanceEvidence:
    return LiabilityBalanceEvidence(
        liability_id=liability_id or f"liability-{currency}",
        account_id=account_id,
        currency=currency,
        amount=amount,
        timestamp=timestamp,
    )


def _input(**changes: Any) -> AccountSnapshotProjectionInput:
    evidence = AccountSnapshotProjectionInput(
        account_id="account",
        account_type=AccountType.broker,
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
        liabilities=(),
    )
    return replace(evidence, **changes)


def _one_holding(**changes: Any):
    holding = changes.pop("holding", _holding())
    price = changes.pop("price", _price())
    rates = changes.pop("exchange_rates", (_rate("EUR"),))
    return build_account_snapshot_projection(
        _input(
            holdings=(holding,),
            prices=(price,),
            exchange_rates=rates,
            **changes,
        )
    )


def test_one_holding_projects_exact_physical_item_and_totals() -> None:
    result = _one_holding()
    assert result.account_id == "account"
    assert result.currency == "CZK"
    assert result.investment_value == Decimal("5000")
    assert result.investment_cost_basis == Decimal("4000")
    assert result.total_value == Decimal("5000")
    assert result.investment_value_by_currency == (
        CurrencyAmount(currency="EUR", amount=Decimal("200")),
    )
    assert result.investment_cost_basis_by_currency == (
        CurrencyAmount(currency="EUR", amount=Decimal("160")),
    )
    item = result.items[0]
    assert (
        item.asset_id,
        item.listing_id,
        item.symbol,
        item.quantity,
        item.price_per_unit,
    ) == ("asset", "listing", "VWCE", Decimal("2"), Decimal("100"))
    assert (
        item.native_value,
        item.value_currency,
        item.value,
        item.native_cost_basis,
        item.native_cost_currency,
        item.cost_basis,
        item.cost_currency,
        item.allocation_pct,
    ) == (
        Decimal("200"),
        "EUR",
        Decimal("5000"),
        Decimal("160"),
        "EUR",
        Decimal("4000"),
        "CZK",
        Decimal("100"),
    )


def test_foreign_price_and_cost_currencies_use_only_direct_rates() -> None:
    result = _one_holding(
        holding=_holding(cost_currency="USD", average_buy_price=Decimal("50")),
        price=_price(currency="EUR", price=Decimal("100")),
        exchange_rates=(
            _rate("USD", value=Decimal("23")),
            _rate("EUR", value=Decimal("25")),
        ),
    )
    assert result.items[0].value == Decimal("5000")
    assert result.items[0].cost_basis == Decimal("2300")
    assert [(rate.base_currency, rate.quote_currency) for rate in result.exchange_rates] == [
        ("EUR", "CZK"),
        ("USD", "CZK"),
    ]


def test_multiple_holdings_are_listing_sorted_and_allocated_on_zero_to_one_hundred_scale() -> None:
    first = _holding(listing_id="listing-b", holding_id="holding-b")
    first_price = _price(listing_id="listing-b", price_id="price-b", price=Decimal("300"))
    second = _holding(
        listing_id="listing-a",
        holding_id="holding-a",
        asset_id="asset-a",
        symbol="BTC",
        quantity=Decimal("1"),
        average_buy_price=Decimal("50"),
    )
    second_price = _price(
        listing_id="listing-a",
        price_id="price-a",
        asset_id="asset-a",
        symbol="BTC",
        price=Decimal("200"),
    )
    result = build_account_snapshot_projection(
        _input(
            holdings=(first, second),
            prices=(first_price, second_price),
            exchange_rates=(_rate("EUR"),),
        )
    )
    assert [item.listing_id for item in result.items] == ["listing-a", "listing-b"]
    assert [item.allocation_pct for item in result.items] == [
        Decimal("25"),
        Decimal("75"),
    ]
    assert sum((item.allocation_pct for item in result.items), Decimal(0)) == Decimal(100)


def test_same_asset_on_distinct_listings_remains_two_snapshot_items() -> None:
    holdings = (
        _holding(listing_id="listing-b", holding_id="holding-b"),
        _holding(listing_id="listing-a", holding_id="holding-a"),
    )
    prices = (
        _price(listing_id="listing-b", price_id="price-b"),
        _price(listing_id="listing-a", price_id="price-a"),
    )
    result = build_account_snapshot_projection(
        _input(
            holdings=holdings,
            prices=prices,
            exchange_rates=(_rate("EUR"),),
        )
    )
    assert [(item.asset_id, item.listing_id) for item in result.items] == [
        ("asset", "listing-a"),
        ("asset", "listing-b"),
    ]


def test_permuted_inputs_are_deterministic_frozen_and_not_mutated() -> None:
    holding_a = _holding(listing_id="a", holding_id="a")
    holding_b = _holding(
        listing_id="b",
        holding_id="b",
        asset_id="asset-b",
        symbol="BTC",
    )
    price_a = _price(listing_id="a", price_id="a")
    price_b = _price(listing_id="b", price_id="b", asset_id="asset-b", symbol="BTC")
    cash = (_cash("USD", Decimal("2")), _cash("CHF", Decimal("3")))
    rates = (
        _rate("USD", quote="EUR", value=Decimal("0.9")),
        _rate("CHF", quote="EUR", value=Decimal("1.05")),
    )
    evidence = _input(
        account_currency="USD",
        output_currency="EUR",
        holdings=(holding_b, holding_a),
        prices=(price_b, price_a),
        exchange_rates=rates,
        cash_balances=cash,
    )
    before = deepcopy(evidence)
    first = build_account_snapshot_projection(evidence)
    second = build_account_snapshot_projection(
        replace(
            evidence,
            holdings=tuple(reversed(evidence.holdings)),
            prices=tuple(reversed(evidence.prices)),
            exchange_rates=tuple(reversed(evidence.exchange_rates)),
            cash_balances=tuple(reversed(evidence.cash_balances)),
        )
    )
    assert first == second
    assert evidence == before
    with pytest.raises(FrozenInstanceError):
        cast(Any, evidence).account_id = "other"
    with pytest.raises(FrozenInstanceError):
        cast(Any, first).cash_value = Decimal(0)


@pytest.mark.parametrize(
    ("granularity", "timestamp"),
    [
        (SnapshotGranularity.minute, datetime(2026, 7, 27, 10, 15)),
        (SnapshotGranularity.hour, datetime(2026, 7, 27, 10, 0)),
        (SnapshotGranularity.day, datetime(2026, 7, 27)),
        (SnapshotGranularity.week, datetime(2026, 7, 27)),
        (SnapshotGranularity.month, datetime(2026, 8, 1)),
    ],
)
def test_snapshot_granularity_accepts_exact_utc_bucket_boundaries(
    granularity: SnapshotGranularity,
    timestamp: datetime,
) -> None:
    result = build_account_snapshot_projection(
        _input(granularity=granularity, snapshot_timestamp=timestamp)
    )
    assert result.timestamp == timestamp


@pytest.mark.parametrize(
    ("granularity", "timestamp"),
    [
        (SnapshotGranularity.minute, datetime(2026, 7, 27, 10, 15, 1)),
        (SnapshotGranularity.hour, datetime(2026, 7, 27, 10, 1)),
        (SnapshotGranularity.day, datetime(2026, 7, 27, 1)),
        (SnapshotGranularity.week, datetime(2026, 7, 28)),
        (SnapshotGranularity.month, datetime(2026, 8, 2)),
        (SnapshotGranularity.minute, datetime(2026, 7, 27, 10, 15, 0, 1000)),
        (SnapshotGranularity.minute, datetime(2026, 7, 27, 10, 15, tzinfo=UTC)),
    ],
)
def test_unaligned_subsecond_and_timezone_aware_snapshot_timestamps_fail(
    granularity: SnapshotGranularity,
    timestamp: datetime,
) -> None:
    with pytest.raises(AccountSnapshotProjectionStateError):
        build_account_snapshot_projection(
            _input(granularity=granularity, snapshot_timestamp=timestamp)
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"account_type": cast(AccountType, "unsupported")},
        {"granularity": cast(SnapshotGranularity, "unsupported")},
        {"source": cast(SnapshotSource, "unsupported")},
        {"calculation_version": cast(int, True)},
    ],
)
def test_invalid_snapshot_metadata_enum_and_version_fail(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(AccountSnapshotProjectionStateError):
        build_account_snapshot_projection(_input(**changes))


@pytest.mark.parametrize(
    "corruption",
    [
        "blank_account",
        "foreign_holding",
        "duplicate_listing",
        "duplicate_holding_id",
        "missing_asset",
        "relation_mismatch",
        "nonpositive_quantity",
        "malformed_average",
        "bad_cost_currency",
        "bad_account_currency",
        "bad_output_currency",
        "bad_version",
    ],
)
def test_holding_and_snapshot_identity_corruption_fails_complete_projection(
    corruption: str,
) -> None:
    holding = _holding()
    holdings = (holding,)
    changes: dict[str, Any] = {
        "holdings": holdings,
        "prices": (_price(),),
        "exchange_rates": (_rate("EUR"),),
    }
    if corruption == "blank_account":
        changes["account_id"] = " "
    elif corruption == "foreign_holding":
        changes["holdings"] = (replace(holding, account_id="other"),)
    elif corruption == "duplicate_listing":
        changes["holdings"] = (holding, replace(holding, holding_id="other"))
        changes["prices"] = (_price(),)
    elif corruption == "duplicate_holding_id":
        changes["holdings"] = (
            holding,
            _holding(listing_id="other", holding_id=holding.holding_id),
        )
        changes["prices"] = (
            _price(),
            _price(listing_id="other", price_id="other"),
        )
    elif corruption == "missing_asset":
        changes["holdings"] = (replace(holding, asset_id=""),)
    elif corruption == "relation_mismatch":
        changes["holdings"] = (replace(holding, listing_asset_id="other"),)
    elif corruption == "nonpositive_quantity":
        changes["holdings"] = (replace(holding, quantity=Decimal(0)),)
    elif corruption == "malformed_average":
        changes["holdings"] = (replace(holding, average_buy_price=cast(Decimal, 1.5)),)
    elif corruption == "bad_cost_currency":
        changes["holdings"] = (replace(holding, cost_currency="eur"),)
    elif corruption == "bad_account_currency":
        changes["account_currency"] = "czk"
    elif corruption == "bad_output_currency":
        changes["output_currency"] = "eur"
    else:
        changes["calculation_version"] = 0
    with pytest.raises(AccountSnapshotProjectionStateError):
        build_account_snapshot_projection(_input(**changes))


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "duplicate_listing",
        "duplicate_id",
        "future",
        "asset_mismatch",
        "listing_mismatch",
        "symbol_mismatch",
        "invalid_source",
        "zero",
        "negative",
        "float",
        "nan",
        "over_scale",
        "overflow",
    ],
)
def test_price_evidence_fail_closed_matrix(corruption: str) -> None:
    holding = _holding()
    price = _price()
    prices: tuple[SelectedPriceEvidence, ...] = (price,)
    if corruption == "missing":
        prices = ()
    elif corruption == "duplicate_listing":
        prices = (price, replace(price, price_id="second"))
    elif corruption == "duplicate_id":
        prices = (
            price,
            _price(
                listing_id="other",
                asset_id="other",
                symbol="BTC",
                price_id=price.price_id,
            ),
        )
    elif corruption == "future":
        prices = (replace(price, timestamp=datetime(2026, 7, 27, 10, 16)),)
    elif corruption == "asset_mismatch":
        prices = (replace(price, asset_id="other"),)
    elif corruption == "listing_mismatch":
        prices = (replace(price, listing_id="other"),)
    elif corruption == "symbol_mismatch":
        prices = (replace(price, symbol="OTHER"),)
    elif corruption == "invalid_source":
        prices = (replace(price, source=cast(PriceSource, "unknown")),)
    elif corruption == "zero":
        prices = (replace(price, price=Decimal(0)),)
    elif corruption == "negative":
        prices = (replace(price, price=Decimal("-1")),)
    elif corruption == "float":
        prices = (replace(price, price=cast(Decimal, 1.5)),)
    elif corruption == "nan":
        prices = (replace(price, price=Decimal("NaN")),)
    elif corruption == "over_scale":
        prices = (replace(price, price=Decimal("1.00000000001")),)
    else:
        prices = (replace(price, price=Decimal("1000000000000000000")),)
    with pytest.raises(AccountSnapshotProjectionStateError):
        build_account_snapshot_projection(
            _input(
                holdings=(holding,),
                prices=prices,
                exchange_rates=(_rate("EUR"),),
            )
        )


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 7, 27, 10, 0, 0, 1),
        datetime(2026, 7, 27, 10, 0, tzinfo=UTC),
    ],
)
def test_price_timestamp_must_be_canonical_naive_millisecond_precision(
    timestamp: datetime,
) -> None:
    with pytest.raises(AccountSnapshotProjectionStateError):
        _one_holding(price=replace(_price(), timestamp=timestamp))


def test_same_currency_values_require_no_fx_evidence() -> None:
    result = _one_holding(
        holding=_holding(cost_currency="CZK", average_buy_price=Decimal("80")),
        price=_price(currency="CZK", price=Decimal("100")),
        exchange_rates=(),
    )
    assert result.exchange_rates == ()
    assert result.investment_value == Decimal("200")


def test_empty_mixed_currency_account_requires_no_synthetic_fx_rate() -> None:
    result = build_account_snapshot_projection(
        _input(account_currency="USD", output_currency="EUR")
    )

    assert (
        result.currency,
        result.cash_value,
        result.investment_value,
        result.investment_cost_basis,
        result.liabilities_value,
        result.total_value,
        result.exchange_rates,
    ) == (
        "EUR",
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        Decimal(0),
        (),
    )


def test_account_currency_difference_alone_does_not_require_fx() -> None:
    result = _one_holding(
        account_currency="USD",
        output_currency="EUR",
        holding=_holding(cost_currency="EUR"),
        price=_price(currency="EUR"),
        exchange_rates=(),
    )

    assert result.currency == "EUR"
    assert result.investment_value == Decimal("200")
    assert result.investment_cost_basis == Decimal("160")
    assert result.exchange_rates == ()


def test_mixed_currency_broker_converts_actual_native_evidence_to_output_currency() -> None:
    result = build_account_snapshot_projection(
        _input(
            account_currency="USD",
            output_currency="EUR",
            holdings=(_holding(cost_currency="USD", average_buy_price=Decimal("80")),),
            prices=(_price(currency="USD", price=Decimal("100")),),
            cash_balances=(_cash("USD", Decimal("50")),),
            exchange_rates=(_rate("USD", quote="EUR", value=Decimal("0.9")),),
        )
    )

    assert (
        result.currency,
        result.cash_value,
        result.investment_value,
        result.investment_cost_basis,
        result.total_value,
    ) == (
        "EUR",
        Decimal("45"),
        Decimal("180"),
        Decimal("144"),
        Decimal("225"),
    )
    assert result.cash_value_by_currency == (CurrencyAmount(currency="USD", amount=Decimal("50")),)
    assert result.investment_value_by_currency == (
        CurrencyAmount(currency="USD", amount=Decimal("200")),
    )
    assert result.investment_cost_basis_by_currency == (
        CurrencyAmount(currency="USD", amount=Decimal("160")),
    )
    item = result.items[0]
    assert (
        item.native_value,
        item.value_currency,
        item.value,
        item.native_cost_basis,
        item.native_cost_currency,
        item.cost_basis,
        item.cost_currency,
    ) == (
        Decimal("200"),
        "USD",
        Decimal("180"),
        Decimal("160"),
        "USD",
        Decimal("144"),
        "EUR",
    )
    assert [(rate.base_currency, rate.quote_currency) for rate in result.exchange_rates] == [
        ("USD", "EUR")
    ]


def test_mixed_currency_broker_requires_each_actual_native_pair_in_sorted_order() -> None:
    result = build_account_snapshot_projection(
        _input(
            account_currency="USD",
            output_currency="EUR",
            holdings=(_holding(cost_currency="USD"),),
            prices=(_price(currency="GBP"),),
            cash_balances=(_cash("CHF", Decimal("10")),),
            exchange_rates=(
                _rate("USD", quote="EUR", value=Decimal("0.9")),
                _rate("CHF", quote="EUR", value=Decimal("1.05")),
                _rate("GBP", quote="EUR", value=Decimal("1.2")),
            ),
        )
    )

    assert result.investment_value == Decimal("240")
    assert result.investment_cost_basis == Decimal("144")
    assert result.cash_value == Decimal("10.5")
    assert [(rate.base_currency, rate.quote_currency) for rate in result.exchange_rates] == [
        ("CHF", "EUR"),
        ("GBP", "EUR"),
        ("USD", "EUR"),
    ]


@pytest.mark.parametrize(
    "rates",
    [
        (),
        (_rate("EUR", quote="USD", value=Decimal("1.1")),),
        (
            _rate("USD", quote="CZK", value=Decimal("20")),
            _rate("CZK", quote="EUR", value=Decimal("0.04")),
        ),
        (
            _rate("USD", quote="EUR", value=Decimal("0.9")),
            _rate("GBP", quote="EUR", value=Decimal("1.2")),
        ),
    ],
)
def test_mixed_currency_broker_rejects_missing_reverse_chained_and_extra_rates(
    rates: tuple[SelectedExchangeRateEvidence, ...],
) -> None:
    with pytest.raises(AccountSnapshotProjectionStateError):
        build_account_snapshot_projection(
            _input(
                account_currency="USD",
                output_currency="EUR",
                cash_balances=(_cash("USD", Decimal("100")),),
                exchange_rates=rates,
            )
        )


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "wrong_direction",
        "duplicate_pair",
        "duplicate_id",
        "future",
        "zero",
        "negative",
        "float",
        "nan",
        "over_scale",
        "overflow",
        "unused",
        "same_currency_row",
    ],
)
def test_fx_evidence_fail_closed_matrix(corruption: str) -> None:
    rate = _rate("EUR")
    rates: tuple[SelectedExchangeRateEvidence, ...] = (rate,)
    if corruption == "missing":
        rates = ()
    elif corruption == "wrong_direction":
        rates = (_rate("CZK", quote="EUR"),)
    elif corruption == "duplicate_pair":
        rates = (rate, replace(rate, rate_id="other"))
    elif corruption == "duplicate_id":
        rates = (rate, _rate("USD", rate_id=rate.rate_id))
    elif corruption == "future":
        rates = (replace(rate, timestamp=datetime(2026, 7, 27, 10, 16)),)
    elif corruption == "zero":
        rates = (replace(rate, rate=Decimal(0)),)
    elif corruption == "negative":
        rates = (replace(rate, rate=Decimal("-1")),)
    elif corruption == "float":
        rates = (replace(rate, rate=cast(Decimal, 1.5)),)
    elif corruption == "nan":
        rates = (replace(rate, rate=Decimal("Infinity")),)
    elif corruption == "over_scale":
        rates = (replace(rate, rate=Decimal("1.000000001")),)
    elif corruption == "overflow":
        rates = (replace(rate, rate=Decimal("10000000000")),)
    elif corruption == "unused":
        rates = (rate, _rate("USD"))
    elif corruption == "same_currency_row":
        rates = (_rate("CZK", quote="CZK"), rate)
    with pytest.raises(AccountSnapshotProjectionStateError):
        _one_holding(exchange_rates=rates)


@pytest.mark.parametrize(
    "rate",
    [
        replace(_rate("EUR"), timestamp=datetime(2026, 7, 27, 9, 0, 0, 1)),
        replace(_rate("EUR"), timestamp=datetime(2026, 7, 27, 9, 0, tzinfo=UTC)),
        replace(_rate("EUR"), source=cast(ExchangeRateSource, "unsupported")),
        replace(_rate("EUR"), base_currency="eur"),
        replace(_rate("EUR"), quote_currency="czk"),
    ],
)
def test_fx_timestamp_source_and_currency_must_be_canonical(
    rate: SelectedExchangeRateEvidence,
) -> None:
    with pytest.raises(AccountSnapshotProjectionStateError):
        _one_holding(exchange_rates=(rate,))


def test_cash_evidence_supports_multiple_currencies_zero_and_negative_without_reclassification() -> (
    None
):
    result = build_account_snapshot_projection(
        _input(
            account_type=AccountType.bank,
            cash_balances=(
                _cash("USD", Decimal("-10")),
                _cash("CZK", Decimal("0")),
            ),
            exchange_rates=(_rate("USD", value=Decimal("20")),),
        )
    )
    assert result.cash_value == Decimal("-200")
    assert result.liabilities_value == Decimal(0)
    assert result.cash_value_by_currency == (
        CurrencyAmount(currency="CZK", amount=Decimal(0)),
        CurrencyAmount(currency="USD", amount=Decimal("-10")),
    )
    assert result.total_value == Decimal("-200")


def test_cash_account_converts_native_balances_to_distinct_output_currency() -> None:
    result = build_account_snapshot_projection(
        _input(
            account_type=AccountType.cash,
            account_currency="USD",
            output_currency="EUR",
            cash_balances=(
                _cash("USD", Decimal("100")),
                _cash("EUR", Decimal("20")),
            ),
            exchange_rates=(_rate("USD", quote="EUR", value=Decimal("0.9")),),
        )
    )

    assert result.currency == "EUR"
    assert result.cash_value == Decimal("110")
    assert result.cash_value_by_currency == (
        CurrencyAmount(currency="EUR", amount=Decimal("20")),
        CurrencyAmount(currency="USD", amount=Decimal("100")),
    )


def test_liability_account_uses_positive_magnitude_and_subtracts_it() -> None:
    result = build_account_snapshot_projection(
        _input(
            account_type=AccountType.loan,
            liabilities=(_liability("CZK", Decimal("300")),),
        )
    )
    assert result.liabilities_value == Decimal("300")
    assert result.total_value == Decimal("-300")
    assert result.items == ()
    assert result.exchange_rates == ()


def test_mixed_currency_liability_converts_scalar_and_preserves_native_breakdown() -> None:
    result = build_account_snapshot_projection(
        _input(
            account_type=AccountType.loan,
            account_currency="USD",
            output_currency="EUR",
            liabilities=(_liability("USD", Decimal("100")),),
            exchange_rates=(_rate("USD", quote="EUR", value=Decimal("0.9")),),
        )
    )

    assert result.currency == "EUR"
    assert result.liabilities_value == Decimal("90")
    assert result.total_value == Decimal("-90")
    assert result.liabilities_value_by_currency == (
        CurrencyAmount(currency="USD", amount=Decimal("100")),
    )
    assert [(rate.base_currency, rate.quote_currency) for rate in result.exchange_rates] == [
        ("USD", "EUR")
    ]


@pytest.mark.parametrize(
    "rates",
    [
        (),
        (_rate("EUR", quote="USD", value=Decimal("1.1")),),
        (
            _rate("USD", quote="CZK", value=Decimal("20")),
            _rate("CZK", quote="EUR", value=Decimal("0.04")),
        ),
    ],
)
def test_mixed_currency_liability_rejects_missing_reverse_and_chained_rates(
    rates: tuple[SelectedExchangeRateEvidence, ...],
) -> None:
    with pytest.raises(AccountSnapshotProjectionStateError):
        build_account_snapshot_projection(
            _input(
                account_type=AccountType.loan,
                account_currency="USD",
                output_currency="EUR",
                liabilities=(_liability("USD", Decimal("100")),),
                exchange_rates=rates,
            )
        )


def test_liability_currency_must_equal_persisted_account_currency() -> None:
    with pytest.raises(AccountSnapshotProjectionStateError):
        build_account_snapshot_projection(
            _input(
                account_type=AccountType.loan,
                account_currency="USD",
                output_currency="EUR",
                liabilities=(_liability("GBP", Decimal("100")),),
                exchange_rates=(_rate("GBP", quote="EUR", value=Decimal("1.2")),),
            )
        )


@pytest.mark.parametrize(
    "account_type",
    [AccountType.credit_card, AccountType.loan, AccountType.mortgage],
)
def test_liability_accounts_accept_explicit_zero_observation(
    account_type: AccountType,
) -> None:
    result = build_account_snapshot_projection(
        _input(
            account_type=account_type,
            liabilities=(_liability("CZK", Decimal(0)),),
        )
    )
    assert result.liabilities_value == Decimal(0)
    assert result.total_value == Decimal(0)
    assert result.liabilities_value_by_currency == (
        CurrencyAmount(currency="CZK", amount=Decimal(0)),
    )
    assert result.items == ()


def test_liability_maximum_money_boundary_negates_exactly() -> None:
    result = build_account_snapshot_projection(
        _input(
            account_type=AccountType.mortgage,
            liabilities=(_liability("CZK", Decimal("999999999999.999999")),),
        )
    )
    assert result.liabilities_value == Decimal("999999999999.999999")
    assert result.total_value == Decimal("-999999999999.999999")


@pytest.mark.parametrize(
    "balance",
    [
        replace(_cash(), amount=cast(Decimal, 1.5)),
        replace(_cash(), amount=Decimal("NaN")),
        replace(_cash(), amount=Decimal("0.0000001")),
        replace(_cash(), amount=Decimal("1000000000000")),
        replace(_cash(), currency="czk"),
        replace(_cash(), timestamp=datetime(2026, 7, 27, 10, 16)),
        replace(_cash(), timestamp=datetime(2026, 7, 27, 10, 0, 0, 1)),
    ],
)
def test_malformed_cash_evidence_fails_closed(balance: CashBalanceEvidence) -> None:
    with pytest.raises(AccountSnapshotProjectionStateError):
        build_account_snapshot_projection(
            _input(account_type=AccountType.bank, cash_balances=(balance,))
        )


@pytest.mark.parametrize(
    "liability",
    [
        replace(_liability(), amount=cast(Decimal, 1.5)),
        replace(_liability(), amount=Decimal("Infinity")),
        replace(_liability(), amount=Decimal("0.0000001")),
        replace(_liability(), amount=Decimal("1000000000000")),
        replace(_liability(), currency="czk"),
        replace(_liability(), timestamp=datetime(2026, 7, 27, 10, 16)),
        replace(_liability(), timestamp=datetime(2026, 7, 27, 10, 0, tzinfo=UTC)),
    ],
)
def test_malformed_liability_evidence_fails_closed(
    liability: LiabilityBalanceEvidence,
) -> None:
    with pytest.raises(AccountSnapshotProjectionStateError):
        build_account_snapshot_projection(
            _input(account_type=AccountType.loan, liabilities=(liability,))
        )


@pytest.mark.parametrize(
    "evidence",
    [
        _input(account_type=AccountType.bank, holdings=(_holding(),), prices=(_price(),)),
        _input(account_type=AccountType.broker, liabilities=(_liability(),)),
        _input(account_type=AccountType.loan, cash_balances=(_cash(),)),
        _input(account_type=AccountType.loan, holdings=(_holding(),), prices=(_price(),)),
        _input(account_type=AccountType.loan, liabilities=(_liability(amount=Decimal("-1")),)),
        _input(account_type=AccountType.loan, liabilities=(_liability("USD"),)),
        _input(
            account_type=AccountType.loan,
            liabilities=(_liability(),),
            exchange_rates=(_rate("USD"),),
        ),
        _input(account_type=AccountType.loan, liabilities=(_liability(account_id="other"),)),
        _input(account_type=AccountType.bank, cash_balances=(_cash(account_id="other"),)),
        _input(
            account_type=AccountType.bank,
            cash_balances=(_cash(), replace(_cash(), balance_id="other")),
        ),
        _input(
            account_type=AccountType.loan,
            liabilities=(_liability(), replace(_liability(), liability_id="other")),
        ),
    ],
)
def test_cash_liability_and_account_type_boundary_fails_closed(
    evidence: AccountSnapshotProjectionInput,
) -> None:
    with pytest.raises(AccountSnapshotProjectionStateError):
        build_account_snapshot_projection(evidence)


def test_cash_investment_and_liability_formula_components_are_exact() -> None:
    investment = _one_holding(cash_balances=(_cash("CZK", Decimal("1000")),))
    assert (
        investment.cash_value,
        investment.investment_value,
        investment.liabilities_value,
        investment.total_value,
    ) == (Decimal("1000"), Decimal("5000"), Decimal(0), Decimal("6000"))

    empty = build_account_snapshot_projection(_input())
    assert (
        empty.cash_value,
        empty.investment_value,
        empty.investment_cost_basis,
        empty.liabilities_value,
        empty.total_value,
        empty.items,
    ) == (Decimal(0), Decimal(0), Decimal(0), Decimal(0), Decimal(0), ())


def test_exact_money_output_boundary_is_accepted_without_rounding() -> None:
    maximum = Decimal("999999999999.999999")
    result = _one_holding(
        holding=_holding(
            quantity=Decimal("1"),
            average_buy_price=maximum,
            cost_currency="CZK",
        ),
        price=_price(price=maximum, currency="CZK"),
        exchange_rates=(),
    )
    assert result.items[0].native_value == maximum
    assert result.items[0].value == maximum
    assert result.items[0].cost_basis == maximum
    assert result.investment_value == maximum


@pytest.mark.parametrize(
    "evidence",
    [
        _input(
            holdings=(
                _holding(
                    quantity=Decimal("999999999999999999.9999999999"),
                    average_buy_price=Decimal("1"),
                ),
            ),
            prices=(
                _price(
                    price=Decimal("2"),
                ),
            ),
            exchange_rates=(_rate("EUR"),),
        ),
        _input(
            holdings=(
                _holding(
                    quantity=Decimal("999999999999.999999"),
                    average_buy_price=Decimal("1"),
                ),
            ),
            prices=(_price(price=Decimal("1")),),
            exchange_rates=(_rate("EUR", value=Decimal("2")),),
        ),
        _input(
            account_type=AccountType.bank,
            cash_balances=(
                _cash("CZK", Decimal("999999999999.999999")),
                _cash("USD", Decimal("1")),
            ),
            exchange_rates=(_rate("USD", value=Decimal("1")),),
        ),
    ],
)
def test_multiplication_conversion_and_aggregate_overflow_fail_without_partial_output(
    evidence: AccountSnapshotProjectionInput,
) -> None:
    with pytest.raises(AccountSnapshotProjectionStateError):
        build_account_snapshot_projection(evidence)


def test_nonrepresentable_allocation_fails_without_rounding_or_remainder_adjustment() -> None:
    holdings = (
        _holding(listing_id="a", holding_id="a", quantity=Decimal("1")),
        _holding(
            listing_id="b",
            holding_id="b",
            asset_id="asset-b",
            symbol="BTC",
            quantity=Decimal("1"),
        ),
    )
    prices = (
        _price(listing_id="a", price_id="a", price=Decimal("1")),
        _price(
            listing_id="b",
            price_id="b",
            asset_id="asset-b",
            symbol="BTC",
            price=Decimal("2"),
        ),
    )
    with pytest.raises(AccountSnapshotProjectionStateError):
        build_account_snapshot_projection(
            _input(
                holdings=holdings,
                prices=prices,
                exchange_rates=(_rate("EUR"),),
            )
        )


def test_deferred_physical_fields_are_not_silently_zeroed_or_exposed() -> None:
    result = build_account_snapshot_projection(_input())
    for field in (
        "net_deposits_value",
        "realized_pnl_value",
        "unrealized_pnl_value",
        "fees_value",
        "taxes_value",
        "is_recalculated",
        "calculated_at",
        "created_at",
        "id",
    ):
        assert not hasattr(result, field)


def test_builder_rejects_untyped_input_and_creates_no_persistence_model() -> None:
    with pytest.raises(AccountSnapshotProjectionStateError):
        build_account_snapshot_projection(cast(AccountSnapshotProjectionInput, {}))
    assert "Model" not in type(build_account_snapshot_projection(_input())).__name__
