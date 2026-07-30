from __future__ import annotations

import ast
import inspect
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from decimal import Decimal, getcontext, localcontext, setcontext
from itertools import permutations
from pathlib import Path
from typing import Any, cast

import pytest

from app.modules.portfolio_snapshot.aggregate_models import (
    MultiAccountPortfolioAccountView,
    MultiAccountPortfolioSummary,
    MultiAccountPortfolioView,
)
from app.modules.portfolio_snapshot.aggregation import (
    MultiAccountPortfolioProjectionError,
    build_multi_account_portfolio_view,
)
from app.modules.portfolio_snapshot.models import (
    AccountType,
    AssetType,
    PortfolioSnapshotItemSource,
    PortfolioSnapshotSource,
    PortfolioSnapshotView,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.portfolio_snapshot.projection import build_portfolio_snapshot_view

TIMESTAMP = datetime(2032, 8, 2)
CREATED_AT = datetime(2032, 8, 2, 0, 0, 0, 123000)
MODULE_DIR = Path(__file__).parents[1] / "app" / "modules" / "portfolio_snapshot"
PRODUCTION_FILES = (
    MODULE_DIR / "aggregate_models.py",
    MODULE_DIR / "aggregation.py",
)


def _item(
    account_id: str,
    *,
    output_currency: str = "EUR",
    listing_id: str = "listing-shared",
    asset_id: str = "asset-shared",
    symbol: str = "AAA",
) -> PortfolioSnapshotItemSource:
    return PortfolioSnapshotItemSource(
        item_id=f"{account_id}-item",
        listing_id=listing_id,
        asset_id=asset_id,
        symbol=symbol,
        name="Shared asset",
        asset_type=AssetType.stock,
        quantity=Decimal("2.0000000000"),
        price_per_unit=Decimal("50.0000000000"),
        price_currency="USD",
        price_timestamp=TIMESTAMP,
        value=Decimal("100.000000"),
        value_currency=output_currency,
        cost_basis=Decimal("80.0000000000"),
        cost_currency=output_currency,
        unrealized_pnl=Decimal("20.0000000000"),
        allocation_pct=Decimal("100.0000"),
        native_value=Decimal("100.0000000000"),
        native_value_currency="USD",
        native_cost_basis=Decimal("80.0000000000"),
        native_cost_currency="USD",
    )


def _source(
    account_id: str,
    *,
    snapshot_id: str | None = None,
    account_type: AccountType = AccountType.broker,
    account_currency: str = "CZK",
    output_currency: str = "EUR",
    timestamp: datetime = TIMESTAMP,
    granularity: SnapshotGranularity = SnapshotGranularity.day,
    source: SnapshotSource = SnapshotSource.manual_recalculation,
    calculation_version: int = 1,
    empty: bool = False,
    cash_value: Decimal | None = None,
) -> PortfolioSnapshotSource:
    liability = account_type in {
        AccountType.credit_card,
        AccountType.loan,
        AccountType.mortgage,
    }
    items = () if liability or empty else (_item(account_id, output_currency=output_currency),)
    investment = Decimal("0.000000") if not items else Decimal("100.000000")
    cost = Decimal("0.000000") if not items else Decimal("80.000000")
    cash = (
        cash_value
        if cash_value is not None
        else Decimal("0.000000")
        if liability
        else Decimal("10.000000")
    )
    liabilities = Decimal("25.000000") if liability else Decimal("0.000000")
    structural = liability
    return PortfolioSnapshotSource(
        snapshot_id=snapshot_id or f"{account_id}-snapshot",
        account_id=account_id,
        account_name=f"{account_id} name",
        account_type=account_type,
        account_currency=account_currency,
        output_currency=output_currency,
        timestamp=timestamp,
        granularity=granularity,
        source=source,
        calculation_version=calculation_version,
        calculated_at=CREATED_AT,
        created_at=CREATED_AT,
        cash_value=cash,
        investment_value=investment,
        investment_cost_basis=cost,
        liabilities_value=liabilities,
        total_value=cash + investment - liabilities,
        net_deposits_value=Decimal("0.000000") if structural else Decimal("70.000000"),
        realized_pnl_value=Decimal("0.000000") if structural else Decimal("5.000000"),
        unrealized_pnl_value=investment - cost,
        fees_value=Decimal("0.000000") if structural else Decimal("2.000000"),
        taxes_value=Decimal("0.000000") if structural else Decimal("1.000000"),
        items=items,
    )


def _view(account_id: str, **changes: Any) -> PortfolioSnapshotView:
    return build_portfolio_snapshot_view(_source(account_id, **changes))


def test_one_account_view_produces_identical_aggregate_summary() -> None:
    view = _view("account-a")

    result = build_multi_account_portfolio_view((view,))

    assert result.summary == MultiAccountPortfolioSummary(
        cash_value=view.summary.cash_value,
        investment_value=view.summary.investment_value,
        investment_cost_basis=view.summary.investment_cost_basis,
        liabilities_value=view.summary.liabilities_value,
        total_value=view.summary.total_value,
        net_deposits_value=view.summary.net_deposits_value,
        realized_pnl_value=view.summary.realized_pnl_value,
        unrealized_pnl_value=view.summary.unrealized_pnl_value,
        fees_value=view.summary.fees_value,
        taxes_value=view.summary.taxes_value,
        account_count=1,
        position_count=1,
    )
    assert result.accounts == (
        MultiAccountPortfolioAccountView(
            snapshot_id=view.snapshot_id,
            account=view.account,
            source=view.source,
            summary=view.summary,
            positions=view.positions,
        ),
    )


def test_two_investment_accounts_sum_exactly() -> None:
    result = build_multi_account_portfolio_view(
        (_view("account-a"), _view("account-b", account_currency="USD"))
    )

    assert result.summary.cash_value == Decimal("20.000000")
    assert result.summary.investment_value == Decimal("200.000000")
    assert result.summary.investment_cost_basis == Decimal("160.000000")
    assert result.summary.total_value == Decimal("220.000000")
    assert result.summary.net_deposits_value == Decimal("140.000000")
    assert result.summary.realized_pnl_value == Decimal("10.000000")
    assert result.summary.unrealized_pnl_value == Decimal("40.000000")
    assert result.summary.fees_value == Decimal("4.000000")
    assert result.summary.taxes_value == Decimal("2.000000")


def test_investment_and_liability_accounts_sum_exactly() -> None:
    result = build_multi_account_portfolio_view(
        (_view("broker"), _view("loan", account_type=AccountType.loan))
    )

    assert result.summary.cash_value == Decimal("10.000000")
    assert result.summary.investment_value == Decimal("100.000000")
    assert result.summary.liabilities_value == Decimal("25.000000")
    assert result.summary.total_value == Decimal("85.000000")
    assert result.summary.account_count == 2
    assert result.summary.position_count == 1


def test_empty_investment_account_is_supported() -> None:
    result = build_multi_account_portfolio_view((_view("empty", empty=True),))

    assert result.summary.investment_value == Decimal("0.000000")
    assert result.summary.position_count == 0
    assert result.accounts[0].positions == ()


def test_different_account_currencies_types_and_sources_are_supported() -> None:
    views = (
        _view(
            "broker",
            account_currency="CZK",
            source=SnapshotSource.manual_recalculation,
        ),
        _view(
            "exchange",
            account_type=AccountType.exchange,
            account_currency="USD",
            source=SnapshotSource.import_event,
        ),
        _view(
            "loan",
            account_type=AccountType.loan,
            account_currency="GBP",
            source=SnapshotSource.scheduled,
        ),
    )

    result = build_multi_account_portfolio_view(views)

    assert {account.account.currency for account in result.accounts} == {"CZK", "USD", "GBP"}
    assert {account.account.account_type for account in result.accounts} == {
        AccountType.broker,
        AccountType.exchange,
        AccountType.loan,
    }
    assert {account.source for account in result.accounts} == {
        SnapshotSource.manual_recalculation,
        SnapshotSource.import_event,
        SnapshotSource.scheduled,
    }


def test_equal_asset_listing_and_symbol_remain_account_scoped_positions() -> None:
    result = build_multi_account_portfolio_view((_view("account-a"), _view("account-b")))

    assert result.summary.position_count == 2
    assert len(result.accounts) == 2
    assert [account.positions[0].asset_id for account in result.accounts] == [
        "asset-shared",
        "asset-shared",
    ]
    assert [account.positions[0].listing_id for account in result.accounts] == [
        "listing-shared",
        "listing-shared",
    ]


def test_every_input_permutation_produces_same_canonical_result() -> None:
    views = (_view("account-c"), _view("account-a"), _view("account-b"))
    expected = build_multi_account_portfolio_view(views)

    assert all(
        build_multi_account_portfolio_view(permutation) == expected
        for permutation in permutations(views)
    )
    assert [account.account.account_id for account in expected.accounts] == [
        "account-a",
        "account-b",
        "account-c",
    ]


def test_original_views_are_not_mutated() -> None:
    views = (_view("account-b"), _view("account-a"))
    original = deepcopy(views)

    build_multi_account_portfolio_view(views)

    assert views == original


def test_output_dataclasses_are_frozen() -> None:
    result = build_multi_account_portfolio_view((_view("account-a"),))

    with pytest.raises(FrozenInstanceError):
        cast(Any, result).currency = "USD"
    with pytest.raises(FrozenInstanceError):
        cast(Any, result.summary).account_count = 2
    with pytest.raises(FrozenInstanceError):
        cast(Any, result.accounts[0]).snapshot_id = "changed"
    assert isinstance(result, MultiAccountPortfolioView)


def test_decimal_scale_and_counts_are_preserved_exactly() -> None:
    result = build_multi_account_portfolio_view(
        (_view("account-a"), _view("account-b", empty=True))
    )

    assert result.summary.cash_value == Decimal("20.000000")
    assert result.summary.cash_value.as_tuple().exponent == -6
    assert result.summary.account_count == len(result.accounts) == 2
    assert result.summary.position_count == sum(
        len(account.positions) for account in result.accounts
    )
    assert all(
        isinstance(value, Decimal)
        for value in (
            result.summary.cash_value,
            result.summary.investment_value,
            result.summary.total_value,
        )
    )


@pytest.mark.parametrize(
    "views",
    [
        (),
        [],
        (object(),),
    ],
)
def test_invalid_container_or_member_fails_closed(views: object) -> None:
    with pytest.raises(MultiAccountPortfolioProjectionError):
        build_multi_account_portfolio_view(cast(Any, views))


@pytest.mark.parametrize(
    "views",
    [
        (
            _view("account-a", snapshot_id="snapshot-a"),
            _view("account-a", snapshot_id="snapshot-b"),
        ),
        (
            _view("account-a", snapshot_id="snapshot-a"),
            _view("account-b", snapshot_id="snapshot-a"),
        ),
    ],
)
def test_duplicate_account_or_snapshot_identity_fails_closed(
    views: tuple[PortfolioSnapshotView, ...],
) -> None:
    with pytest.raises(MultiAccountPortfolioProjectionError):
        build_multi_account_portfolio_view(views)


@pytest.mark.parametrize(
    "changed",
    [
        {"timestamp": TIMESTAMP.replace(day=3)},
        {"granularity": SnapshotGranularity.hour},
        {"output_currency": "USD"},
        {"calculation_version": 2},
    ],
)
def test_different_exact_metadata_fails_closed(changed: dict[str, Any]) -> None:
    views = (_view("account-a"), _view("account-b", **changed))

    with pytest.raises(MultiAccountPortfolioProjectionError):
        build_multi_account_portfolio_view(views)


def test_corrupt_account_position_count_fails_closed() -> None:
    view = _view("account-a")
    corrupt = replace(
        view,
        summary=replace(view.summary, position_count=view.summary.position_count + 1),
    )

    with pytest.raises(MultiAccountPortfolioProjectionError):
        build_multi_account_portfolio_view((corrupt,))


def test_aggregate_money_overflow_fails_closed() -> None:
    views = (
        _view("account-a", empty=True, cash_value=Decimal("600000000000.000000")),
        _view("account-b", empty=True, cash_value=Decimal("600000000000.000000")),
    )

    with pytest.raises(MultiAccountPortfolioProjectionError):
        build_multi_account_portfolio_view(views)


@pytest.mark.parametrize(
    "value",
    [
        "10.000000",
        Decimal("NaN"),
        Decimal("0.0000001"),
    ],
)
def test_invalid_financial_value_fails_closed(value: object) -> None:
    view = _view("account-a")
    corrupt = replace(
        view,
        summary=replace(view.summary, cash_value=cast(Any, value)),
    )

    with pytest.raises(MultiAccountPortfolioProjectionError):
        build_multi_account_portfolio_view((corrupt,))


@pytest.mark.parametrize(
    "field",
    ["total_value", "unrealized_pnl_value"],
)
def test_aggregate_summary_invariant_mismatch_fails_closed(field: str) -> None:
    view = _view("account-a")
    summary = (
        replace(view.summary, total_value=Decimal("999.000000"))
        if field == "total_value"
        else replace(view.summary, unrealized_pnl_value=Decimal("999.000000"))
    )
    corrupt = replace(
        view,
        summary=summary,
    )

    with pytest.raises(MultiAccountPortfolioProjectionError):
        build_multi_account_portfolio_view((corrupt,))


def test_error_contract_is_stable_generic_and_contains_no_evidence() -> None:
    error = MultiAccountPortfolioProjectionError()

    assert str(error) == ("Portfolio snapshot views cannot produce a complete multi-account view.")
    for forbidden in (
        "account-a",
        "snapshot-a",
        "AAA",
        "2032",
        "EUR",
        "999.000000",
        "2 accounts",
    ):
        assert forbidden not in str(error)


def test_projection_does_not_change_ambient_decimal_context() -> None:
    views = (_view("account-a"), _view("account-b"))
    before = getcontext().copy()
    try:
        getcontext().prec = 7
        configured = getcontext().copy()

        build_multi_account_portfolio_view(views)

        assert repr(getcontext()) == repr(configured)
    finally:
        setcontext(before)


def test_projection_is_synchronous_with_one_pure_input() -> None:
    signature = inspect.signature(build_multi_account_portfolio_view)

    assert not inspect.iscoroutinefunction(build_multi_account_portfolio_view)
    assert tuple(signature.parameters) == ("views",)


def test_production_boundary_has_no_forbidden_dependencies_or_operations() -> None:
    forbidden_imports = {
        "sqlalchemy",
        "fastapi",
        "pydantic",
        "AsyncSession",
        "AccountModel",
        "AccountMemberModel",
        "AccountSnapshotModel",
        "AccountSnapshotItemModel",
        "HoldingModel",
        "PriceSnapshotModel",
        "ExchangeRateModel",
        "UserModel",
        "AuthenticatedPrincipal",
        "require_account_access",
        "PortfolioSnapshotReader",
        "AuthorizedPortfolioSnapshotService",
    }
    for path in PRODUCTION_FILES:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert forbidden_imports.isdisjoint(imported)
        assert "app.modules.portfolio." not in source
        for forbidden in (
            "float(",
            "round(",
            "datetime.now",
            "uuid",
            "latest",
            "fallback",
            "open(",
            "print(",
        ):
            assert forbidden not in source


def test_account_position_order_is_reused_without_global_sort() -> None:
    first = _view("account-a")
    second = _view("account-b")

    result = build_multi_account_portfolio_view((second, first))

    assert result.accounts[0].positions is first.positions
    assert result.accounts[1].positions is second.positions


def test_local_decimal_context_is_sufficient_for_exact_sum() -> None:
    with localcontext() as context:
        context.prec = 3
        result = build_multi_account_portfolio_view((_view("account-a"), _view("account-b")))

    assert result.summary.total_value == Decimal("220.000000")
