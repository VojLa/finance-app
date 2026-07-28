from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest

from app.db.models.enums import AccountType, SnapshotGranularity
from app.modules.net_worth import (
    AccountNetWorthEvidence,
    ExpectedNetWorthProjection,
    NetWorthAccountTypeAmount,
    NetWorthCurrencyAmount,
    NetWorthProjectionInput,
    NetWorthProjectionStateError,
    build_net_worth_projection,
)

NOW = datetime(2026, 7, 27)
MONEY_MAX = Decimal("999999999999.999999")
QUANTITY_AGGREGATE_PART = Decimal("600000000000000000.0000000000")


def _amount(currency: str, value: str | Decimal) -> NetWorthCurrencyAmount:
    return NetWorthCurrencyAmount(currency=currency, amount=Decimal(value))


def _investment(
    account_id: str = "broker-account",
    *,
    snapshot_id: str | None = None,
    account_type: AccountType = AccountType.broker,
    cash: Decimal = Decimal("100"),
    investment: Decimal = Decimal("400"),
    timestamp: datetime = NOW,
    granularity: SnapshotGranularity = SnapshotGranularity.day,
    account_currency: str = "CZK",
    snapshot_currency: str = "CZK",
    cash_breakdown: tuple[NetWorthCurrencyAmount, ...] | None = (_amount("CZK", "100"),),
    investment_breakdown: tuple[NetWorthCurrencyAmount, ...] | None = (_amount("CZK", "400"),),
    liability_breakdown: tuple[NetWorthCurrencyAmount, ...] | None = (),
) -> AccountNetWorthEvidence:
    return AccountNetWorthEvidence(
        snapshot_id=snapshot_id or f"{account_id}-snapshot",
        account_id=account_id,
        account_type=account_type,
        account_currency=account_currency,
        snapshot_currency=snapshot_currency,
        timestamp=timestamp,
        granularity=granularity,
        total_value=cash + investment,
        cash_value=cash,
        investment_value=investment,
        liabilities_value=Decimal(0),
        cash_value_by_currency=cash_breakdown,
        investment_value_by_currency=investment_breakdown,
        liabilities_value_by_currency=liability_breakdown,
    )


def _liability(
    account_id: str = "loan-account",
    *,
    snapshot_id: str | None = None,
    account_type: AccountType = AccountType.loan,
    liability: Decimal = Decimal("250"),
    timestamp: datetime = NOW,
    granularity: SnapshotGranularity = SnapshotGranularity.day,
    account_currency: str = "CZK",
    snapshot_currency: str = "CZK",
    cash_breakdown: tuple[NetWorthCurrencyAmount, ...] | None = (),
    investment_breakdown: tuple[NetWorthCurrencyAmount, ...] | None = (),
    liability_breakdown: tuple[NetWorthCurrencyAmount, ...] | None = (_amount("CZK", "250"),),
) -> AccountNetWorthEvidence:
    return AccountNetWorthEvidence(
        snapshot_id=snapshot_id or f"{account_id}-snapshot",
        account_id=account_id,
        account_type=account_type,
        account_currency=account_currency,
        snapshot_currency=snapshot_currency,
        timestamp=timestamp,
        granularity=granularity,
        total_value=-liability,
        cash_value=Decimal(0),
        investment_value=Decimal(0),
        liabilities_value=liability,
        cash_value_by_currency=cash_breakdown,
        investment_value_by_currency=investment_breakdown,
        liabilities_value_by_currency=liability_breakdown,
    )


def _input(
    *account_snapshots: AccountNetWorthEvidence,
    user_id: str = "user-1",
    timestamp: datetime = NOW,
    granularity: SnapshotGranularity = SnapshotGranularity.day,
    currency: str = "CZK",
    calculation_version: int = 1,
) -> NetWorthProjectionInput:
    return NetWorthProjectionInput(
        user_id=user_id,
        timestamp=timestamp,
        granularity=granularity,
        currency=currency,
        calculation_version=calculation_version,
        account_snapshots=account_snapshots,
    )


def test_empty_set_is_an_exact_zero_projection() -> None:
    result = build_net_worth_projection(_input())

    assert result.cash_value == Decimal(0)
    assert result.portfolio_value == Decimal(0)
    assert result.assets_value == Decimal(0)
    assert result.liabilities_value == Decimal(0)
    assert result.net_worth_value == Decimal(0)
    assert result.account_count == 0
    assert result.accounts == ()
    assert result.account_type_breakdown == ()
    assert result.cash_value_by_currency == ()
    assert result.portfolio_value_by_currency == ()
    assert result.liabilities_value_by_currency == ()
    assert result.total_net_worth_by_currency == ()


@pytest.mark.parametrize(
    "account_type",
    [AccountType.broker, AccountType.exchange, AccountType.crypto_wallet],
)
def test_one_investment_account_aggregates_cash_and_market_value(
    account_type: AccountType,
) -> None:
    result = build_net_worth_projection(_input(_investment(account_type=account_type)))

    assert result.cash_value == Decimal("100")
    assert result.portfolio_value == Decimal("400")
    assert result.assets_value == Decimal("500")
    assert result.liabilities_value == Decimal(0)
    assert result.net_worth_value == Decimal("500")
    assert result.accounts[0].net_value == Decimal("500")


@pytest.mark.parametrize(
    "account_type",
    [AccountType.credit_card, AccountType.loan, AccountType.mortgage],
)
def test_one_liability_account_preserves_positive_debt_and_negative_net(
    account_type: AccountType,
) -> None:
    result = build_net_worth_projection(_input(_liability(account_type=account_type)))

    assert result.assets_value == Decimal(0)
    assert result.liabilities_value == Decimal("250")
    assert result.net_worth_value == Decimal("-250")
    assert result.accounts[0].liabilities_value == Decimal("250")
    assert result.accounts[0].net_value == Decimal("-250")


def test_mixed_portfolio_matches_both_net_worth_formulas() -> None:
    result = build_net_worth_projection(
        _input(
            _investment(
                "broker",
                cash=Decimal("100000"),
                investment=Decimal("400000"),
                cash_breakdown=(_amount("CZK", "100000"),),
                investment_breakdown=(_amount("CZK", "400000"),),
            ),
            _investment(
                "crypto",
                account_type=AccountType.crypto_wallet,
                cash=Decimal(0),
                investment=Decimal("100000"),
                cash_breakdown=(),
                investment_breakdown=(_amount("CZK", "100000"),),
            ),
            _liability(
                "mortgage",
                account_type=AccountType.mortgage,
                liability=Decimal("250000"),
                liability_breakdown=(_amount("CZK", "250000"),),
            ),
            _liability(
                "card",
                account_type=AccountType.credit_card,
                liability=Decimal("20000"),
                liability_breakdown=(_amount("CZK", "20000"),),
            ),
        )
    )

    assert result.assets_value == Decimal("600000")
    assert result.liabilities_value == Decimal("270000")
    assert result.net_worth_value == Decimal("330000")
    assert sum((item.net_value for item in result.accounts), Decimal(0)) == Decimal("330000")


def test_explicit_zero_liability_remains_counted() -> None:
    result = build_net_worth_projection(
        _input(
            _liability(
                liability=Decimal(0),
                liability_breakdown=(_amount("CZK", "0"),),
            )
        )
    )

    assert result.account_count == 1
    assert result.liabilities_value == Decimal(0)
    assert result.net_worth_value == Decimal(0)
    assert result.accounts[0].net_value == Decimal(0)


def test_negative_investment_cash_reduces_assets_without_reclassification() -> None:
    result = build_net_worth_projection(
        _input(
            _investment(
                cash=Decimal("-100"),
                investment=Decimal("400"),
                cash_breakdown=(_amount("CZK", "-100"),),
            )
        )
    )

    assert result.cash_value == Decimal("-100")
    assert result.assets_value == Decimal("300")
    assert result.liabilities_value == Decimal(0)
    assert result.net_worth_value == Decimal("300")


@pytest.mark.parametrize(
    "snapshots",
    [
        (
            _investment("same", snapshot_id="snapshot-1"),
            _investment("same", snapshot_id="snapshot-2"),
        ),
        (
            _investment("account-1", snapshot_id="same-snapshot"),
            _investment("account-2", snapshot_id="same-snapshot"),
        ),
    ],
)
def test_duplicate_account_or_snapshot_identity_fails_closed(
    snapshots: tuple[AccountNetWorthEvidence, ...],
) -> None:
    with pytest.raises(
        NetWorthProjectionStateError,
        match=r"Account snapshots cannot produce a complete net worth projection\.",
    ):
        build_net_worth_projection(_input(*snapshots))


@pytest.mark.parametrize(
    "snapshot",
    [
        _investment(snapshot_currency="EUR"),
    ],
)
def test_currency_mismatch_fails_closed(snapshot: AccountNetWorthEvidence) -> None:
    with pytest.raises(NetWorthProjectionStateError):
        build_net_worth_projection(_input(snapshot))


def test_canonical_account_currency_may_differ_from_snapshot_output_currency() -> None:
    result = build_net_worth_projection(_input(_investment(account_currency="EUR")))

    assert result.currency == "CZK"


@pytest.mark.parametrize("account_currency", ["eur", "EU", " EUR"])
def test_malformed_account_currency_fails_closed(account_currency: str) -> None:
    with pytest.raises(NetWorthProjectionStateError):
        build_net_worth_projection(_input(_investment(account_currency=account_currency)))


@pytest.mark.parametrize(
    "snapshot",
    [
        _investment(timestamp=datetime(2026, 7, 26)),
        _investment(granularity=SnapshotGranularity.hour),
    ],
)
def test_timestamp_or_granularity_mismatch_fails_closed(
    snapshot: AccountNetWorthEvidence,
) -> None:
    with pytest.raises(NetWorthProjectionStateError):
        build_net_worth_projection(_input(snapshot))


@pytest.mark.parametrize(
    ("granularity", "timestamp"),
    [
        (SnapshotGranularity.minute, datetime(2026, 7, 27, 10, 20)),
        (SnapshotGranularity.hour, datetime(2026, 7, 27, 10)),
        (SnapshotGranularity.day, datetime(2026, 7, 27)),
        (SnapshotGranularity.week, datetime(2026, 7, 27)),
        (SnapshotGranularity.month, datetime(2026, 7, 1)),
    ],
)
def test_every_canonical_granularity_boundary_is_accepted(
    granularity: SnapshotGranularity,
    timestamp: datetime,
) -> None:
    snapshot = _investment(timestamp=timestamp, granularity=granularity)

    result = build_net_worth_projection(
        _input(snapshot, timestamp=timestamp, granularity=granularity)
    )

    assert result.timestamp == timestamp
    assert result.granularity is granularity


@pytest.mark.parametrize(
    "account_type",
    [AccountType.bank, AccountType.cash, AccountType.savings],
)
def test_physically_unsupported_account_types_fail_closed(
    account_type: AccountType,
) -> None:
    with pytest.raises(NetWorthProjectionStateError):
        build_net_worth_projection(_input(_investment(account_type=account_type)))


@pytest.mark.parametrize(
    "snapshot",
    [
        replace(_investment(), total_value=Decimal("499")),
        replace(_investment(), liabilities_value=Decimal("1")),
        replace(_liability(), cash_value=Decimal("1"), total_value=Decimal("-249")),
        replace(
            _liability(),
            investment_value=Decimal("1"),
            total_value=Decimal("-249"),
        ),
        replace(_liability(), liabilities_value=Decimal("-1"), total_value=Decimal("1")),
        replace(_investment(), investment_value=Decimal("-1"), total_value=Decimal("99")),
    ],
)
def test_corrupt_account_financial_invariants_fail_closed(
    snapshot: AccountNetWorthEvidence,
) -> None:
    with pytest.raises(NetWorthProjectionStateError):
        build_net_worth_projection(_input(snapshot))


@pytest.mark.parametrize(
    "projection_input",
    [
        _input(user_id=""),
        _input(user_id=" user "),
        _input(currency="czk"),
        _input(currency="CZ"),
        _input(currency="ČZK"),
        _input(timestamp=datetime(2026, 7, 27, 0, 0, 0, 1000)),
        _input(timestamp=datetime(2026, 7, 27, tzinfo=UTC)),
        _input(timestamp=datetime(2026, 7, 27, 0, 1)),
        _input(granularity=cast(SnapshotGranularity, "day")),
        _input(calculation_version=0),
        _input(calculation_version=cast(int, True)),
        _input(calculation_version=2_147_483_648),
        replace(_input(), account_snapshots=cast(Any, [])),
    ],
)
def test_invalid_command_contract_fails_closed(
    projection_input: NetWorthProjectionInput,
) -> None:
    with pytest.raises(NetWorthProjectionStateError):
        build_net_worth_projection(projection_input)


def test_exact_postgresql_integer_version_maximum_is_allowed() -> None:
    result = build_net_worth_projection(_input(calculation_version=2_147_483_647))
    assert result.calculation_version == 2_147_483_647


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cash_value", cast(Decimal, 1.5)),
        ("cash_value", Decimal("NaN")),
        ("cash_value", Decimal("Infinity")),
        ("cash_value", Decimal("0.0000001")),
        ("cash_value", Decimal("1000000000000")),
        ("investment_value", Decimal("-0.000001")),
        ("liabilities_value", Decimal("-0.000001")),
        ("total_value", Decimal("1000000000000")),
    ],
)
def test_invalid_money_values_fail_closed(field: str, value: Decimal) -> None:
    snapshot = cast(AccountNetWorthEvidence, cast(Any, replace)(_investment(), **{field: value}))
    with pytest.raises(NetWorthProjectionStateError):
        build_net_worth_projection(_input(snapshot))


def test_money_positive_and_negative_boundaries_are_exact() -> None:
    positive = build_net_worth_projection(
        _input(
            _investment(
                cash=MONEY_MAX,
                investment=Decimal(0),
                cash_breakdown=(_amount("CZK", MONEY_MAX),),
                investment_breakdown=(),
            )
        )
    )
    negative = build_net_worth_projection(
        _input(
            _liability(
                liability=MONEY_MAX,
                liability_breakdown=(_amount("CZK", MONEY_MAX),),
            )
        )
    )

    assert positive.net_worth_value == MONEY_MAX
    assert negative.net_worth_value == -MONEY_MAX


def test_aggregate_overflow_fails_even_when_each_account_is_representable() -> None:
    with pytest.raises(NetWorthProjectionStateError):
        build_net_worth_projection(
            _input(
                _investment(
                    "one",
                    cash=Decimal("600000000000"),
                    investment=Decimal(0),
                    cash_breakdown=None,
                    investment_breakdown=None,
                    liability_breakdown=None,
                ),
                _investment(
                    "two",
                    cash=Decimal("600000000000"),
                    investment=Decimal(0),
                    cash_breakdown=None,
                    investment_breakdown=None,
                    liability_breakdown=None,
                ),
            )
        )


def test_currency_breakdowns_are_aggregated_and_sorted_exactly() -> None:
    result = build_net_worth_projection(
        _input(
            _investment(
                "broker",
                cash_breakdown=(
                    _amount("USD", "2"),
                    _amount("CZK", "100"),
                ),
                investment_breakdown=(_amount("EUR", "10"),),
            ),
            _liability(
                "loan",
                liability=Decimal("250"),
                liability_breakdown=(_amount("CZK", "250"),),
            ),
        )
    )

    assert result.cash_value_by_currency == (
        _amount("CZK", "100"),
        _amount("USD", "2"),
    )
    assert result.portfolio_value_by_currency == (_amount("EUR", "10"),)
    assert result.liabilities_value_by_currency == (_amount("CZK", "250"),)
    assert result.total_net_worth_by_currency == (
        _amount("CZK", "-150"),
        _amount("EUR", "10"),
        _amount("USD", "2"),
    )


def test_portfolio_and_total_native_breakdowns_preserve_quantity_scale() -> None:
    result = build_net_worth_projection(
        _input(
            _investment(
                cash=Decimal(0),
                investment=Decimal("0.123456"),
                cash_breakdown=(),
                investment_breakdown=(_amount("USD", "0.1234567890"),),
            )
        )
    )

    assert result.portfolio_value_by_currency == (_amount("USD", "0.1234567890"),)
    assert result.total_net_worth_by_currency == (_amount("USD", "0.1234567890"),)


def test_mixed_native_net_worth_uses_exact_quantity_arithmetic() -> None:
    result = build_net_worth_projection(
        _input(
            _investment(
                cash=Decimal("1.000001"),
                investment=Decimal("2.123456"),
                cash_breakdown=(_amount("CZK", "1.000001"),),
                investment_breakdown=(_amount("CZK", "2.1234567890"),),
            ),
            _liability(
                liability=Decimal("0.500001"),
                liability_breakdown=(_amount("CZK", "0.500001"),),
            ),
        )
    )

    assert result.total_net_worth_by_currency == (_amount("CZK", "2.6234567890"),)


def test_portfolio_breakdown_rejects_quantity_over_scale() -> None:
    with pytest.raises(NetWorthProjectionStateError):
        build_net_worth_projection(
            _input(
                _investment(
                    investment_breakdown=(_amount("USD", "0.12345678901"),),
                )
            )
        )


def test_portfolio_breakdown_aggregate_overflow_fails_closed() -> None:
    with pytest.raises(NetWorthProjectionStateError):
        build_net_worth_projection(
            _input(
                _investment(
                    "one",
                    investment_breakdown=(_amount("USD", QUANTITY_AGGREGATE_PART),),
                ),
                _investment(
                    "two",
                    investment_breakdown=(_amount("USD", QUANTITY_AGGREGATE_PART),),
                ),
            )
        )


@pytest.mark.parametrize(
    "snapshot",
    [
        _investment(cash_breakdown=(_amount("CZK", "1.0000001"),)),
        _liability(liability_breakdown=(_amount("CZK", "250.0000001"),)),
    ],
)
def test_money_native_breakdowns_still_reject_scale_above_six(
    snapshot: AccountNetWorthEvidence,
) -> None:
    with pytest.raises(NetWorthProjectionStateError):
        build_net_worth_projection(_input(snapshot))


def test_unavailable_native_breakdown_remains_unavailable_not_empty() -> None:
    result = build_net_worth_projection(_input(_liability(liability_breakdown=None)))

    assert result.liabilities_value == Decimal("250")
    assert result.liabilities_value_by_currency is None
    assert result.total_net_worth_by_currency is None


def test_zero_unavailable_liability_is_neutral_without_becoming_empty() -> None:
    result = build_net_worth_projection(
        _input(
            _investment(
                cash=Decimal(0),
                investment=Decimal("0.123456"),
                cash_breakdown=(),
                investment_breakdown=(_amount("USD", "0.1234567890"),),
                liability_breakdown=None,
            )
        )
    )

    assert result.liabilities_value_by_currency is None
    assert result.total_net_worth_by_currency == (_amount("USD", "0.1234567890"),)


@pytest.mark.parametrize(
    "snapshot",
    [
        replace(
            _investment(),
            cash_value_by_currency=cast(
                Any,
                [_amount("CZK", "100")],
            ),
        ),
        replace(
            _investment(),
            cash_value_by_currency=(
                _amount("CZK", "100"),
                _amount("CZK", "100"),
            ),
        ),
        replace(
            _investment(),
            cash_value_by_currency=(_amount("czk", "100"),),
        ),
        replace(
            _investment(),
            investment_value_by_currency=(_amount("CZK", "-1"),),
        ),
        replace(
            _investment(),
            liabilities_value_by_currency=(_amount("CZK", "0"),),
        ),
        replace(
            _liability(),
            cash_value_by_currency=(_amount("CZK", "0"),),
        ),
        replace(
            _liability(),
            liabilities_value_by_currency=(_amount("CZK", "249"),),
        ),
    ],
)
def test_malformed_or_contradictory_breakdowns_fail_closed(
    snapshot: AccountNetWorthEvidence,
) -> None:
    with pytest.raises(NetWorthProjectionStateError):
        build_net_worth_projection(_input(snapshot))


def test_account_and_type_ordering_is_deterministic_under_input_permutation() -> None:
    snapshots = (
        _liability("z-card", account_type=AccountType.credit_card),
        _investment("b-exchange", account_type=AccountType.exchange),
        _investment("a-broker", account_type=AccountType.broker),
        _liability("m-loan", account_type=AccountType.loan),
    )
    first = build_net_worth_projection(_input(*snapshots))
    second = build_net_worth_projection(_input(*reversed(snapshots)))

    assert first == second
    assert [item.account_id for item in first.accounts] == [
        "a-broker",
        "b-exchange",
        "m-loan",
        "z-card",
    ]
    assert [item.account_type for item in first.account_type_breakdown] == [
        AccountType.broker,
        AccountType.credit_card,
        AccountType.exchange,
        AccountType.loan,
    ]


def test_account_type_breakdown_preserves_assets_liabilities_and_net() -> None:
    result = build_net_worth_projection(
        _input(
            _investment("broker-one"),
            _investment("broker-two", cash=Decimal("50"), investment=Decimal("50")),
            _liability("loan-one"),
        )
    )

    assert result.account_type_breakdown == (
        NetWorthAccountTypeAmount(
            account_type=AccountType.broker,
            assets_value=Decimal("600"),
            liabilities_value=Decimal(0),
            net_value=Decimal("600"),
        ),
        NetWorthAccountTypeAmount(
            account_type=AccountType.loan,
            assets_value=Decimal(0),
            liabilities_value=Decimal("250"),
            net_value=Decimal("-250"),
        ),
    )


def test_input_and_output_are_frozen_and_input_tuple_is_not_mutated() -> None:
    snapshots = (_investment("b"), _liability("a"))
    projection_input = _input(*snapshots)
    before = projection_input.account_snapshots
    result = build_net_worth_projection(projection_input)

    with pytest.raises(FrozenInstanceError):
        cast(Any, projection_input).currency = "EUR"
    with pytest.raises(FrozenInstanceError):
        cast(Any, snapshots[0]).cash_value = Decimal(0)
    with pytest.raises(FrozenInstanceError):
        cast(Any, result).net_worth_value = Decimal(0)
    with pytest.raises(FrozenInstanceError):
        cast(Any, result.accounts[0]).net_value = Decimal(0)
    assert projection_input.account_snapshots is before
    assert projection_input.account_snapshots == snapshots


def test_wrong_runtime_input_and_evidence_types_fail_closed() -> None:
    with pytest.raises(NetWorthProjectionStateError):
        build_net_worth_projection(cast(NetWorthProjectionInput, object()))
    with pytest.raises(NetWorthProjectionStateError):
        build_net_worth_projection(replace(_input(), account_snapshots=cast(Any, (object(),))))


def test_projection_returns_declared_immutable_result_contract() -> None:
    result = build_net_worth_projection(_input(_investment()))
    assert isinstance(result, ExpectedNetWorthProjection)
