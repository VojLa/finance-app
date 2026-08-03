from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy import Integer, Numeric, inspect
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP

from app.db.models.enums import AccountType, SnapshotGranularity, SnapshotSource
from app.db.models.snapshots import NetWorthSnapshotModel
from app.modules.net_worth import (
    AccountNetWorthEvidence,
    CanonicalNetWorthJsonObject,
    ExpectedNetWorthProjection,
    ExpectedNetWorthSnapshotPersistence,
    NetWorthCurrencyAmount,
    NetWorthProjectionInput,
    NetWorthSnapshotPersistenceMetadata,
    NetWorthSnapshotPersistenceProjectionError,
    build_net_worth_projection,
    build_net_worth_snapshot_persistence_projection,
)
from app.modules.net_worth.evidence_service import (
    CompleteNetWorthEvidence,
    SelectedAccountSnapshotIdentity,
)

SNAPSHOT_AT = datetime(2032, 8, 2)
CALCULATED_AT = datetime(2032, 8, 2, 1, 2, 3, 456000)
CREATED_AT = datetime(2032, 8, 2, 1, 2, 4, 567000)
MONEY_MAX = Decimal("999999999999.999999")
QUANTITY_MAX = Decimal("999999999999999999.9999999999")


def _amount(currency: str, value: str | Decimal) -> NetWorthCurrencyAmount:
    return NetWorthCurrencyAmount(currency=currency, amount=Decimal(value))


def _investment(
    account_id: str = "broker-account",
    *,
    snapshot_id: str | None = None,
    account_type: AccountType = AccountType.broker,
    cash: Decimal = Decimal("100"),
    portfolio: Decimal = Decimal("400"),
    currency: str = "CZK",
    timestamp: datetime = SNAPSHOT_AT,
    granularity: SnapshotGranularity = SnapshotGranularity.day,
    cash_breakdown: tuple[NetWorthCurrencyAmount, ...] | None = None,
    portfolio_breakdown: tuple[NetWorthCurrencyAmount, ...] | None = None,
    liability_breakdown: tuple[NetWorthCurrencyAmount, ...] | None = (),
) -> AccountNetWorthEvidence:
    return AccountNetWorthEvidence(
        snapshot_id=snapshot_id or f"{account_id}-snapshot",
        account_id=account_id,
        account_type=account_type,
        account_currency=currency,
        snapshot_currency=currency,
        timestamp=timestamp,
        granularity=granularity,
        total_value=cash + portfolio,
        cash_value=cash,
        investment_value=portfolio,
        liabilities_value=Decimal(0),
        cash_value_by_currency=(
            (_amount(currency, cash),) if cash_breakdown is None and cash != 0 else cash_breakdown
        ),
        investment_value_by_currency=(
            (_amount(currency, portfolio),)
            if portfolio_breakdown is None and portfolio != 0
            else portfolio_breakdown
        ),
        liabilities_value_by_currency=liability_breakdown,
    )


def _liability(
    account_id: str = "loan-account",
    *,
    snapshot_id: str | None = None,
    account_type: AccountType = AccountType.loan,
    liability: Decimal = Decimal("250"),
    currency: str = "CZK",
    timestamp: datetime = SNAPSHOT_AT,
    granularity: SnapshotGranularity = SnapshotGranularity.day,
    liability_breakdown: tuple[NetWorthCurrencyAmount, ...] | None = None,
) -> AccountNetWorthEvidence:
    return AccountNetWorthEvidence(
        snapshot_id=snapshot_id or f"{account_id}-snapshot",
        account_id=account_id,
        account_type=account_type,
        account_currency=currency,
        snapshot_currency=currency,
        timestamp=timestamp,
        granularity=granularity,
        total_value=-liability,
        cash_value=Decimal(0),
        investment_value=Decimal(0),
        liabilities_value=liability,
        cash_value_by_currency=(),
        investment_value_by_currency=(),
        liabilities_value_by_currency=(
            (_amount(currency, liability),) if liability_breakdown is None else liability_breakdown
        ),
    )


def _evidence(
    *snapshots: AccountNetWorthEvidence,
    user_id: str = "user-1",
    timestamp: datetime = SNAPSHOT_AT,
    granularity: SnapshotGranularity = SnapshotGranularity.day,
    currency: str = "CZK",
    calculation_version: int = 1,
) -> CompleteNetWorthEvidence:
    projection = build_net_worth_projection(
        NetWorthProjectionInput(
            user_id=user_id,
            timestamp=timestamp,
            granularity=granularity,
            currency=currency,
            calculation_version=calculation_version,
            account_snapshots=tuple(snapshots),
        )
    )
    identities = tuple(
        SelectedAccountSnapshotIdentity(
            account_id=account.account_id,
            snapshot_id=account.snapshot_id,
        )
        for account in projection.accounts
    )
    return CompleteNetWorthEvidence(
        projection=projection,
        selected_account_ids=tuple(item.account_id for item in identities),
        selected_account_snapshot_ids=tuple(item.snapshot_id for item in identities),
        selected_identities=identities,
    )


def _metadata(
    *,
    source: SnapshotSource = SnapshotSource.manual_recalculation,
    calculated_at: datetime = CALCULATED_AT,
    created_at: datetime = CREATED_AT,
    is_recalculated: bool = True,
) -> NetWorthSnapshotPersistenceMetadata:
    return NetWorthSnapshotPersistenceMetadata(
        source=source,
        calculated_at=calculated_at,
        created_at=created_at,
        is_recalculated=is_recalculated,
    )


def _project(
    evidence: CompleteNetWorthEvidence | None = None,
    metadata: NetWorthSnapshotPersistenceMetadata | None = None,
) -> ExpectedNetWorthSnapshotPersistence:
    return build_net_worth_snapshot_persistence_projection(
        evidence or _evidence(_investment()),
        metadata or _metadata(),
    )


def _with_projection(
    evidence: CompleteNetWorthEvidence,
    **changes: object,
) -> CompleteNetWorthEvidence:
    projection = cast(
        ExpectedNetWorthProjection, cast(Any, replace)(evidence.projection, **changes)
    )
    return replace(evidence, projection=projection)


def test_empty_user_maps_every_physical_field_explicitly() -> None:
    result = _project(_evidence())
    row = result.snapshot

    assert row.user_id == "user-1"
    assert row.timestamp == SNAPSHOT_AT
    assert row.granularity is SnapshotGranularity.day
    assert row.source is SnapshotSource.manual_recalculation
    assert row.currency == "CZK"
    assert row.cash_value == 0
    assert row.portfolio_value == 0
    assert row.liabilities_value == 0
    assert row.total_net_worth == 0
    assert row.is_recalculated is True
    assert row.calculated_at == CALCULATED_AT
    assert row.calculation_version == 1
    assert row.created_at == CREATED_AT
    assert row.cash_value_by_currency == CanonicalNetWorthJsonObject(())
    assert row.portfolio_value_by_currency == CanonicalNetWorthJsonObject(())
    assert row.liabilities_value_by_currency == CanonicalNetWorthJsonObject(())
    assert row.total_net_worth_by_currency == CanonicalNetWorthJsonObject(())
    assert row.exchange_rates is None
    assert result.audit.selected_identities == ()


@pytest.mark.parametrize(
    "snapshot",
    [
        _investment(),
        _investment(
            account_type=AccountType.bank,
            portfolio=Decimal(0),
            portfolio_breakdown=(),
        ),
        _liability(),
        _investment(cash=Decimal("-10"), portfolio=Decimal("20")),
    ],
)
def test_investment_liability_and_negative_cash_mapping(
    snapshot: AccountNetWorthEvidence,
) -> None:
    evidence = _evidence(snapshot)
    result = _project(evidence)

    assert result.snapshot.cash_value == evidence.projection.cash_value
    assert result.snapshot.portfolio_value == evidence.projection.portfolio_value
    assert result.snapshot.liabilities_value == evidence.projection.liabilities_value
    assert result.snapshot.total_net_worth == evidence.projection.net_worth_value


def test_mixed_projection_maps_exact_aggregates() -> None:
    evidence = _evidence(
        _investment("broker"),
        _investment("crypto", account_type=AccountType.crypto_wallet),
        _liability("mortgage", account_type=AccountType.mortgage),
    )
    row = _project(evidence).snapshot

    assert row.cash_value == Decimal("200")
    assert row.portfolio_value == Decimal("800")
    assert row.liabilities_value == Decimal("250")
    assert row.total_net_worth == Decimal("750")


def test_deterministic_id_matches_physical_key_only() -> None:
    evidence = _evidence(_investment())
    baseline = _project(evidence)
    metadata_changed = _project(
        evidence,
        _metadata(
            source=SnapshotSource.scheduled,
            calculated_at=datetime(2040, 1, 1),
            created_at=datetime(2040, 1, 2),
            is_recalculated=False,
        ),
    )
    financially_changed = _project(_evidence(_investment(cash=Decimal("101"))))
    version_changed = _project(_evidence(_investment(), calculation_version=2))

    assert baseline.snapshot.id == "8f3d2938-dd30-5873-a416-4419a80e88f9"
    assert metadata_changed.snapshot.id == baseline.snapshot.id
    assert financially_changed.snapshot.id == baseline.snapshot.id
    assert version_changed.snapshot.id == baseline.snapshot.id


def test_input_permutation_does_not_change_identity_or_row() -> None:
    first = _project(_evidence(_investment("b"), _liability("a")))
    second = _project(_evidence(_liability("a"), _investment("b")))

    assert first == second


@pytest.mark.parametrize(
    "changed",
    [
        _evidence(_investment(), user_id="user-2"),
        _evidence(
            _investment(timestamp=datetime(2032, 8, 3)),
            timestamp=datetime(2032, 8, 3),
        ),
        _evidence(
            _investment(currency="EUR"),
            currency="EUR",
        ),
        _evidence(
            _investment(
                timestamp=datetime(2032, 8, 2, 1),
                granularity=SnapshotGranularity.hour,
            ),
            timestamp=datetime(2032, 8, 2, 1),
            granularity=SnapshotGranularity.hour,
        ),
    ],
)
def test_physical_key_changes_snapshot_id(changed: CompleteNetWorthEvidence) -> None:
    assert _project(changed).snapshot.id != _project().snapshot.id


def test_scheduled_and_manual_metadata_contracts() -> None:
    scheduled = _project(
        metadata=_metadata(
            source=SnapshotSource.scheduled,
            is_recalculated=False,
        )
    )
    manual = _project()

    assert scheduled.snapshot.source is SnapshotSource.scheduled
    assert scheduled.snapshot.is_recalculated is False
    assert manual.snapshot.source is SnapshotSource.manual_recalculation
    assert manual.snapshot.is_recalculated is True


@pytest.mark.parametrize(
    "metadata",
    [
        _metadata(is_recalculated=False),
        _metadata(source=SnapshotSource.scheduled),
        _metadata(calculated_at=datetime(2032, 8, 2, tzinfo=UTC)),
        _metadata(created_at=datetime(2032, 8, 2, 0, 0, 0, 1)),
        replace(_metadata(), source=cast(SnapshotSource, "scheduled")),
        replace(_metadata(), is_recalculated=cast(bool, 1)),
        cast(NetWorthSnapshotPersistenceMetadata, object()),
    ],
)
def test_invalid_metadata_fails_closed(
    metadata: NetWorthSnapshotPersistenceMetadata,
) -> None:
    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(metadata=metadata)


def test_money_boundaries_and_calculation_version_maximum() -> None:
    positive = _project(
        _evidence(
            _investment(
                cash=MONEY_MAX,
                portfolio=Decimal(0),
                portfolio_breakdown=(),
            ),
            calculation_version=2_147_483_647,
        )
    )
    negative = _project(
        _evidence(
            _investment(
                cash=-MONEY_MAX,
                portfolio=Decimal(0),
                portfolio_breakdown=(),
            )
        )
    )

    assert positive.snapshot.cash_value == MONEY_MAX
    assert positive.snapshot.calculation_version == 2_147_483_647
    assert negative.snapshot.total_net_worth == -MONEY_MAX


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cash_value", cast(Decimal, 1.0)),
        ("cash_value", Decimal("NaN")),
        ("cash_value", Decimal("Infinity")),
        ("cash_value", Decimal("0.0000001")),
        ("cash_value", Decimal("1000000000000")),
        ("portfolio_value", Decimal("-0.000001")),
        ("liabilities_value", Decimal("-0.000001")),
        ("net_worth_value", Decimal("1000000000000")),
        ("assets_value", Decimal("999")),
    ],
)
def test_corrupt_scalar_financial_values_fail_closed(field: str, value: Decimal) -> None:
    evidence = _evidence(_investment())
    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(_with_projection(evidence, **{field: value}))


@pytest.mark.parametrize("version", [0, cast(int, True), 2_147_483_648])
def test_invalid_calculation_version_fails_closed(version: int) -> None:
    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(_with_projection(_evidence(), calculation_version=version))


def test_breakdown_serialization_preserves_category_scales() -> None:
    evidence = _evidence(
        _investment(
            cash=Decimal("1.000001"),
            portfolio=Decimal("2.123456"),
            cash_breakdown=(_amount("USD", "1.000001"),),
            portfolio_breakdown=(_amount("USD", "0.1234567890"),),
        ),
        _liability(
            liability=Decimal("0.500001"),
            liability_breakdown=(_amount("CZK", "0.500001"),),
        ),
    )
    row = _project(evidence).snapshot
    values = row.model_values()

    assert values["cash_value_by_currency"] == {"USD": "1.000001"}
    assert values["portfolio_value_by_currency"] == {"USD": "0.1234567890"}
    assert values["liabilities_value_by_currency"] == {"CZK": "0.500001"}
    assert values["total_net_worth_by_currency"] == {
        "CZK": "-0.5000010000",
        "USD": "1.1234577890",
    }
    assert all(
        isinstance(amount, str)
        for name in (
            "cash_value_by_currency",
            "portfolio_value_by_currency",
            "liabilities_value_by_currency",
            "total_net_worth_by_currency",
        )
        for amount in cast(dict[str, object], values[name]).values()
    )


@pytest.mark.parametrize(
    ("field", "changes"),
    [
        (
            "cash_value_by_currency",
            {
                "cash_value_by_currency": None,
                "total_net_worth_by_currency": None,
            },
        ),
        (
            "portfolio_value_by_currency",
            {
                "portfolio_value_by_currency": None,
                "total_net_worth_by_currency": None,
            },
        ),
        ("liabilities_value_by_currency", {"liabilities_value_by_currency": None}),
        (
            "total_net_worth_by_currency",
            {
                "cash_value_by_currency": None,
                "total_net_worth_by_currency": None,
            },
        ),
    ],
)
def test_none_serializes_to_sql_null(field: str, changes: dict[str, object]) -> None:
    result = _project(_with_projection(_evidence(_investment()), **changes))

    assert result.snapshot.model_values()[field] is None


@pytest.mark.parametrize(
    "field",
    [
        "cash_value_by_currency",
        "portfolio_value_by_currency",
        "liabilities_value_by_currency",
        "total_net_worth_by_currency",
    ],
)
def test_exact_empty_serializes_to_empty_json(field: str) -> None:
    result = _project(_evidence())

    assert result.snapshot.model_values()[field] == {}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "cash_value_by_currency",
            (_amount("CZK", "1"), _amount("CZK", "2")),
        ),
        ("cash_value_by_currency", (_amount("czk", "1"),)),
        ("cash_value_by_currency", cast(Any, ("wrong",))),
        ("cash_value_by_currency", cast(Any, [_amount("CZK", "1")])),
        ("cash_value_by_currency", (_amount("CZK", "1.0000001"),)),
        ("cash_value_by_currency", (_amount("CZK", "1000000000000.000000"),)),
        ("portfolio_value_by_currency", (_amount("CZK", "0.12345678901"),)),
        ("portfolio_value_by_currency", (_amount("CZK", QUANTITY_MAX + Decimal(1)),)),
        ("portfolio_value_by_currency", (_amount("CZK", "-1.0000000000"),)),
        ("liabilities_value_by_currency", (_amount("CZK", "-1.000000"),)),
        ("total_net_worth_by_currency", (_amount("CZK", "0.12345678901"),)),
    ],
)
def test_malformed_breakdown_fails_closed(field: str, value: object) -> None:
    evidence = _evidence(_investment())
    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(_with_projection(evidence, **{field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cash_value_by_currency", ()),
        ("portfolio_value_by_currency", ()),
        ("total_net_worth_by_currency", ()),
        ("cash_value_by_currency", (_amount("CZK", "99.000000"),)),
        ("portfolio_value_by_currency", (_amount("CZK", "399.0000000000"),)),
        ("total_net_worth_by_currency", (_amount("CZK", "499.0000000000"),)),
    ],
)
def test_breakdown_scalar_consistency_fails_closed(field: str, value: object) -> None:
    evidence = _evidence(_investment())
    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(_with_projection(evidence, **{field: value}))


@pytest.mark.parametrize(
    "value",
    [
        (),
        (_amount("CZK", "249.000000"),),
    ],
)
def test_liability_breakdown_scalar_consistency_fails_closed(value: object) -> None:
    evidence = _evidence(_liability())
    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(_with_projection(evidence, liabilities_value_by_currency=value))


def test_breakdown_input_must_be_deterministically_sorted() -> None:
    evidence = _evidence(
        _investment(
            cash_breakdown=(
                _amount("CZK", "50"),
                _amount("USD", "2"),
            )
        )
    )
    reversed_breakdown = tuple(
        reversed(cast(tuple[Any, ...], evidence.projection.cash_value_by_currency))
    )

    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(_with_projection(evidence, cash_value_by_currency=reversed_breakdown))


def _multicurrency_evidence() -> CompleteNetWorthEvidence:
    return _evidence(
        _investment(
            cash_breakdown=(
                _amount("EUR", "1.000000"),
                _amount("USD", "2.000000"),
            ),
            portfolio_breakdown=(
                _amount("EUR", "0.1234567890"),
                _amount("USD", "3.0000000000"),
            ),
        ),
        _liability(
            liability_breakdown=(_amount("CZK", "250.000000"),),
        ),
    )


def test_forged_multicurrency_total_amount_fails_closed() -> None:
    evidence = _multicurrency_evidence()
    forged = (
        _amount("CZK", "-250.0000000000"),
        _amount("EUR", "1.1234567890"),
        _amount("USD", "6.0000000000"),
    )

    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(_with_projection(evidence, total_net_worth_by_currency=forged))


@pytest.mark.parametrize(
    "forged",
    [
        (
            _amount("CZK", "-250.0000000000"),
            _amount("EUR", "1.1234567890"),
        ),
        (
            _amount("CZK", "-250.0000000000"),
            _amount("EUR", "1.1234567890"),
            _amount("JPY", "1.0000000000"),
            _amount("USD", "5.0000000000"),
        ),
        (
            _amount("EUR", "1.1234567890"),
            _amount("JPY", "-250.0000000000"),
            _amount("USD", "5.0000000000"),
        ),
    ],
)
def test_forged_total_currency_set_fails_closed(
    forged: tuple[NetWorthCurrencyAmount, ...],
) -> None:
    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(
            _with_projection(
                _multicurrency_evidence(),
                total_net_worth_by_currency=forged,
            )
        )


def test_complete_native_categories_require_available_total() -> None:
    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(
            _with_projection(
                _multicurrency_evidence(),
                total_net_worth_by_currency=None,
            )
        )


def test_exact_empty_native_categories_require_exact_empty_total() -> None:
    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(
            _with_projection(
                _evidence(),
                total_net_worth_by_currency=None,
            )
        )


@pytest.mark.parametrize("cash", [Decimal("100"), Decimal(0)])
def test_unavailable_cash_requires_unavailable_total_even_when_cash_is_zero(
    cash: Decimal,
) -> None:
    evidence = _evidence(_investment(cash=cash))
    unavailable = _with_projection(
        evidence,
        cash_value_by_currency=None,
        total_net_worth_by_currency=None,
    )

    result = _project(unavailable)

    assert result.snapshot.cash_value_by_currency is None
    assert result.snapshot.total_net_worth_by_currency is None
    for forged in ((), (_amount("USD", "1.0000000000"),)):
        with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
            _project(
                _with_projection(
                    evidence,
                    cash_value_by_currency=None,
                    total_net_worth_by_currency=forged,
                )
            )


def test_unavailable_zero_portfolio_is_neutral_only_for_total_calculation() -> None:
    result = _project(_evidence(_investment(portfolio=Decimal(0))))

    assert result.snapshot.portfolio_value_by_currency is None
    assert result.snapshot.model_values()["total_net_worth_by_currency"] == {
        "CZK": "100.0000000000"
    }


def test_unavailable_zero_liability_is_neutral_only_for_total_calculation() -> None:
    result = _project(_evidence(_investment(liability_breakdown=None)))

    assert result.snapshot.liabilities_value_by_currency is None
    assert result.snapshot.model_values()["total_net_worth_by_currency"] == {
        "CZK": "500.0000000000"
    }


@pytest.mark.parametrize("category", ["portfolio", "liabilities"])
def test_unavailable_nonzero_category_requires_unavailable_total(category: str) -> None:
    if category == "portfolio":
        account = replace(_investment(), investment_value_by_currency=None)
        category_changes = {"portfolio_value_by_currency": None}
    else:
        account = replace(_liability(), liabilities_value_by_currency=None)
        category_changes = {"liabilities_value_by_currency": None}
    evidence = _evidence(account)

    result = _project(evidence)

    assert result.snapshot.total_net_worth_by_currency is None
    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(
            _with_projection(
                evidence,
                **category_changes,
                total_net_worth_by_currency=(_amount("USD", "1.0000000000"),),
            )
        )


def test_native_total_cancellation_preserves_exact_zero_currency_entry() -> None:
    evidence = _evidence(
        _investment(
            cash=Decimal(1),
            portfolio=Decimal(0),
            cash_breakdown=(_amount("CZK", "1.000000"),),
        ),
        _liability(
            liability=Decimal(1),
            liability_breakdown=(_amount("CZK", "1.000000"),),
        ),
    )

    assert _project(evidence).snapshot.model_values()["total_net_worth_by_currency"] == {
        "CZK": "0.0000000000"
    }


def test_native_total_quantity_intermediate_overflow_fails_closed() -> None:
    evidence = _evidence(_investment())
    forged = _with_projection(
        evidence,
        cash_value_by_currency=(_amount("USD", MONEY_MAX),),
        portfolio_value_by_currency=(_amount("USD", QUANTITY_MAX),),
        liabilities_value_by_currency=(),
        total_net_worth_by_currency=(_amount("USD", QUANTITY_MAX),),
    )

    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(forged)


def test_supplied_total_order_must_match_canonical_native_order() -> None:
    evidence = _multicurrency_evidence()
    supplied = cast(
        tuple[NetWorthCurrencyAmount, ...],
        evidence.projection.total_net_worth_by_currency,
    )

    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(
            _with_projection(
                evidence,
                total_net_worth_by_currency=tuple(reversed(supplied)),
            )
        )


def test_valid_lineage_is_preserved_only_in_ephemeral_audit() -> None:
    result = _project(_evidence(_liability("a"), _investment("b")))

    assert result.audit.selected_account_ids == ("a", "b")
    assert result.audit.selected_account_snapshot_ids == ("a-snapshot", "b-snapshot")
    assert tuple(result.snapshot.model_values()) == (
        "id",
        "user_id",
        "timestamp",
        "granularity",
        "source",
        "currency",
        "cash_value",
        "portfolio_value",
        "liabilities_value",
        "total_net_worth",
        "is_recalculated",
        "calculated_at",
        "calculation_version",
        "created_at",
        "cash_value_by_currency",
        "portfolio_value_by_currency",
        "liabilities_value_by_currency",
        "total_net_worth_by_currency",
        "exchange_rates",
    )
    assert result.snapshot.exchange_rates is None


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: replace(
            value,
            selected_account_ids=("wrong",),
        ),
        lambda value: replace(
            value,
            selected_account_snapshot_ids=("wrong",),
        ),
        lambda value: replace(
            value,
            selected_identities=(),
        ),
        lambda value: replace(
            value,
            selected_identities=(
                *value.selected_identities,
                SelectedAccountSnapshotIdentity(
                    account_id="extra",
                    snapshot_id="extra-snapshot",
                ),
            ),
        ),
        lambda value: replace(
            value,
            selected_identities=(
                value.selected_identities[0],
                value.selected_identities[0],
            ),
        ),
        lambda value: replace(
            value,
            selected_identities=(
                SelectedAccountSnapshotIdentity(
                    account_id="a",
                    snapshot_id="shared",
                ),
                SelectedAccountSnapshotIdentity(
                    account_id="b",
                    snapshot_id="shared",
                ),
            ),
        ),
        lambda value: replace(
            value,
            selected_identities=tuple(reversed(value.selected_identities)),
        ),
    ],
)
def test_lineage_corruption_fails_closed(
    mutate: Any,
) -> None:
    evidence = _evidence(_liability("a"), _investment("b"))
    with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
        _project(mutate(evidence))


def test_projection_account_count_and_contribution_corruption_fail_closed() -> None:
    evidence = _evidence(_investment())
    malformed_contribution = replace(
        evidence.projection.accounts[0],
        snapshot_id="wrong",
    )

    for projection in (
        replace(evidence.projection, account_count=2),
        replace(evidence.projection, accounts=(malformed_contribution,)),
        replace(evidence.projection, accounts=cast(Any, [evidence.projection.accounts[0]])),
        replace(evidence.projection, accounts=cast(Any, (object(),))),
    ):
        with pytest.raises(NetWorthSnapshotPersistenceProjectionError):
            _project(replace(evidence, projection=projection))


def test_model_contract_matches_all_and_only_physical_columns() -> None:
    result = _project()
    row_fields = {field.name for field in fields(result.snapshot)}
    model_columns = {attribute.key for attribute in inspect(NetWorthSnapshotModel).column_attrs}
    values = result.snapshot.model_values()
    model = NetWorthSnapshotModel(**values)

    assert row_fields == model_columns
    assert set(values) == model_columns
    assert model.id == result.snapshot.id
    assert model.total_net_worth == Decimal("500")


def test_physical_numeric_timestamp_json_and_nullability_contracts_match_model() -> None:
    table = NetWorthSnapshotModel.__table__
    for name in ("cashValue", "portfolioValue", "liabilitiesValue", "totalNetWorth"):
        column_type = table.c[name].type
        assert isinstance(column_type, Numeric)
        assert (column_type.precision, column_type.scale) == (18, 6)
        assert table.c[name].nullable is False
    for name in ("timestamp", "calculatedAt", "createdAt"):
        column_type = table.c[name].type
        assert isinstance(column_type, TIMESTAMP)
        assert column_type.precision == 3
        assert column_type.timezone is False
        assert table.c[name].nullable is False
    for name in (
        "cashValueByCurrency",
        "portfolioValueByCurrency",
        "liabilitiesValueByCurrency",
        "totalNetWorthByCurrency",
        "exchangeRates",
    ):
        assert isinstance(table.c[name].type, JSONB)
        assert table.c[name].nullable is True
    assert isinstance(table.c.calculationVersion.type, Integer)
    assert table.c.calculationVersion.nullable is False


def test_model_values_are_fresh_and_cannot_mutate_row_contract() -> None:
    result = _project()
    first = result.snapshot.model_values()
    second = result.snapshot.model_values()
    first_cash = cast(dict[str, object], first["cash_value_by_currency"])
    second_cash = cast(dict[str, object], second["cash_value_by_currency"])

    assert first is not second
    assert first_cash is not second_cash
    first_cash["CZK"] = "999.000000"
    assert second_cash == {"CZK": "100.000000"}
    assert result.snapshot.cash_value_by_currency == CanonicalNetWorthJsonObject(
        (("CZK", "100.000000"),)
    )


def test_inputs_and_outputs_are_frozen_deterministic_and_unmutated() -> None:
    evidence = _evidence(_investment())
    metadata = _metadata()
    original = deepcopy(evidence)
    first = _project(evidence, metadata)
    second = _project(evidence, metadata)

    assert first == second
    assert evidence == original
    with pytest.raises(FrozenInstanceError):
        cast(Any, first.snapshot).cash_value = Decimal(0)
    with pytest.raises(FrozenInstanceError):
        cast(Any, first.audit).selected_account_ids = ()
    with pytest.raises(FrozenInstanceError):
        cast(Any, first.snapshot.cash_value_by_currency).entries = ()


@pytest.mark.parametrize(
    ("evidence", "metadata"),
    [
        (cast(CompleteNetWorthEvidence, object()), _metadata()),
        (_evidence(), cast(NetWorthSnapshotPersistenceMetadata, object())),
        (replace(_evidence(), projection=cast(Any, object())), _metadata()),
    ],
)
def test_wrong_runtime_contract_uses_stable_generic_error(
    evidence: CompleteNetWorthEvidence,
    metadata: NetWorthSnapshotPersistenceMetadata,
) -> None:
    with pytest.raises(
        NetWorthSnapshotPersistenceProjectionError,
        match=r"^Net-worth evidence is not physically persistable\.$",
    ):
        build_net_worth_snapshot_persistence_projection(evidence, metadata)
