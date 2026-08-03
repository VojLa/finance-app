from __future__ import annotations

import ast
import inspect
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal, getcontext, setcontext
from itertools import permutations
from pathlib import Path
from typing import Any, cast

import pytest

from app.modules.dashboard_snapshot.models import (
    DashboardAccountCard,
    DashboardAssetTypeAllocation,
    DashboardSnapshotSummary,
    DashboardSnapshotView,
    DashboardTopPosition,
)
from app.modules.dashboard_snapshot.projection import (
    DashboardSnapshotProjectionError,
    build_dashboard_snapshot_view,
)
from app.modules.portfolio_snapshot.aggregate_models import MultiAccountPortfolioView
from app.modules.portfolio_snapshot.aggregation import build_multi_account_portfolio_view
from app.modules.portfolio_snapshot.models import (
    AccountType,
    AssetType,
    PortfolioPositionView,
    PortfolioSnapshotItemSource,
    PortfolioSnapshotSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.portfolio_snapshot.projection import build_portfolio_snapshot_view

TIMESTAMP = datetime(2032, 8, 2)
CREATED_AT = datetime(2032, 8, 2, 0, 0, 0, 123000)
MODULE_DIR = Path(__file__).parents[1] / "app" / "modules" / "dashboard_snapshot"
PRODUCTION_FILES = (MODULE_DIR / "models.py", MODULE_DIR / "projection.py")
ERROR_MESSAGE = "Portfolio snapshot evidence cannot produce a complete dashboard view."


def _money(value: str | int) -> Decimal:
    return Decimal(value).quantize(Decimal("0.000001"))


def _quantity(value: str | int) -> Decimal:
    return Decimal(value).quantize(Decimal("0.0000000001"))


def _item(
    account_id: str,
    *,
    value: str = "100",
    cost: str = "80",
    allocation: str = "100.0000",
    ordinal: int = 1,
    asset_type: AssetType = AssetType.stock,
    symbol: str = "AAA",
    output_currency: str = "EUR",
) -> PortfolioSnapshotItemSource:
    money_value = _money(value)
    quantity_value = _quantity(value)
    cost_value = _quantity(cost)
    return PortfolioSnapshotItemSource(
        item_id=f"{account_id}-item-{ordinal}",
        listing_id=f"{account_id}-listing-{ordinal}",
        asset_id=f"{account_id}-asset-{ordinal}",
        symbol=symbol,
        name=f"{symbol} asset",
        asset_type=asset_type,
        quantity=_quantity("1"),
        price_per_unit=quantity_value,
        price_currency="USD",
        price_timestamp=TIMESTAMP,
        value=money_value,
        value_currency=output_currency,
        cost_basis=cost_value,
        cost_currency=output_currency,
        unrealized_pnl=quantity_value - cost_value,
        allocation_pct=Decimal(allocation),
        native_value=quantity_value,
        native_value_currency="USD",
        native_cost_basis=cost_value,
        native_cost_currency="USD",
    )


def _source(
    account_id: str,
    *,
    account_name: str | None = None,
    snapshot_id: str | None = None,
    account_type: AccountType = AccountType.broker,
    account_currency: str = "CZK",
    output_currency: str = "EUR",
    value: str = "100",
    cost: str = "80",
    cash: str = "10",
    asset_type: AssetType = AssetType.stock,
    symbol: str = "AAA",
    items: tuple[PortfolioSnapshotItemSource, ...] | None = None,
    empty: bool = False,
    snapshot_source: SnapshotSource = SnapshotSource.manual_recalculation,
) -> PortfolioSnapshotSource:
    liability = account_type in {
        AccountType.credit_card,
        AccountType.loan,
        AccountType.mortgage,
    }
    cash_only = account_type in {
        AccountType.bank,
        AccountType.cash,
        AccountType.savings,
    }
    if items is None:
        items = (
            ()
            if liability or cash_only or empty
            else (
                _item(
                    account_id,
                    value=value,
                    cost=cost,
                    asset_type=asset_type,
                    symbol=symbol,
                    output_currency=output_currency,
                ),
            )
        )
    investment = sum((item.value for item in items), Decimal(0))
    investment_cost = sum((item.cost_basis for item in items), Decimal(0))
    cash_value = _money("0" if liability else cash)
    liabilities = _money("25" if liability else "0")
    structural_zero = liability or cash_only
    return PortfolioSnapshotSource(
        snapshot_id=snapshot_id or f"{account_id}-snapshot",
        account_id=account_id,
        account_name=account_name or f"{account_id} name",
        account_type=account_type,
        account_currency=account_currency,
        output_currency=output_currency,
        timestamp=TIMESTAMP,
        granularity=SnapshotGranularity.day,
        source=snapshot_source,
        calculation_version=1,
        calculated_at=CREATED_AT,
        created_at=CREATED_AT,
        cash_value=cash_value,
        investment_value=investment,
        investment_cost_basis=investment_cost,
        liabilities_value=liabilities,
        total_value=cash_value + investment - liabilities,
        net_deposits_value=_money("0" if structural_zero else "70"),
        realized_pnl_value=_money("0" if structural_zero else "5"),
        unrealized_pnl_value=investment - investment_cost,
        fees_value=_money("0" if structural_zero else "2"),
        taxes_value=_money("0" if structural_zero else "1"),
        items=items,
    )


def _portfolio(*sources: PortfolioSnapshotSource) -> MultiAccountPortfolioView:
    views = tuple(build_portfolio_snapshot_view(source) for source in sources)
    return build_multi_account_portfolio_view(views)


def _dashboard(*sources: PortfolioSnapshotSource) -> DashboardSnapshotView:
    return build_dashboard_snapshot_view(_portfolio(*sources))


def test_full_pipeline_projects_exact_dashboard_summary() -> None:
    portfolio = _portfolio(
        _source("broker", value="60", cost="50", cash="10"),
        _source("exchange", account_type=AccountType.exchange, value="40", cost="30", cash="5"),
        _source("loan", account_type=AccountType.loan),
    )

    result = build_dashboard_snapshot_view(portfolio)

    assert result.timestamp == TIMESTAMP
    assert result.granularity is SnapshotGranularity.day
    assert result.currency == "EUR"
    assert result.calculation_version == 1
    assert result.summary == DashboardSnapshotSummary(
        total_value=_money("90"),
        assets_value=_money("115"),
        liabilities_value=_money("25"),
        cash_value=_money("15"),
        investment_value=_money("100"),
        investment_cost_basis=_money("80"),
        unrealized_pnl_value=_money("20"),
        realized_pnl_value=_money("10"),
        net_deposits_value=_money("140"),
        fees_value=_money("4"),
        taxes_value=_money("2"),
        account_count=3,
        investment_account_count=2,
        liability_account_count=1,
        position_count=2,
    )


@pytest.mark.parametrize(
    ("account_type", "investment_count", "liability_count"),
    [
        (AccountType.broker, 1, 0),
        (AccountType.exchange, 1, 0),
        (AccountType.crypto_wallet, 1, 0),
        (AccountType.bank, 0, 0),
        (AccountType.cash, 0, 0),
        (AccountType.savings, 0, 0),
        (AccountType.credit_card, 0, 1),
        (AccountType.loan, 0, 1),
        (AccountType.mortgage, 0, 1),
    ],
)
def test_supported_account_types_are_classified_exactly(
    account_type: AccountType,
    investment_count: int,
    liability_count: int,
) -> None:
    result = _dashboard(_source("account", account_type=account_type))

    assert result.summary.investment_account_count == investment_count
    assert result.summary.liability_account_count == liability_count


def test_liability_only_dashboard_has_no_investment_presentations() -> None:
    result = _dashboard(
        _source("loan", account_type=AccountType.loan),
        _source("mortgage", account_type=AccountType.mortgage),
    )

    assert result.summary.assets_value == _money("0")
    assert result.summary.liabilities_value == _money("50")
    assert result.summary.total_value == _money("-50")
    assert result.asset_type_allocations == ()
    assert result.top_positions == ()


def test_empty_investment_dashboard_has_no_allocations_or_top_positions() -> None:
    result = _dashboard(_source("empty", empty=True))

    assert result.summary.investment_value == _money("0")
    assert result.summary.position_count == 0
    assert result.asset_type_allocations == ()
    assert result.top_positions == ()


def test_account_cards_copy_exact_account_scoped_values() -> None:
    portfolio = _portfolio(
        _source(
            "broker",
            account_name="Broker Alpha",
            account_currency="CZK",
            value="60",
            cost="50",
            cash="12",
        )
    )

    result = build_dashboard_snapshot_view(portfolio)

    assert result.accounts == (
        DashboardAccountCard(
            account_id="broker",
            snapshot_id="broker-snapshot",
            name="Broker Alpha",
            account_type=AccountType.broker,
            account_currency="CZK",
            output_currency="EUR",
            total_value=_money("72"),
            cash_value=_money("12"),
            investment_value=_money("60"),
            liabilities_value=_money("0"),
            unrealized_pnl_value=_money("10"),
            position_count=1,
        ),
    )


def test_different_account_currencies_and_snapshot_sources_are_preserved_upstream() -> None:
    portfolio = _portfolio(
        _source(
            "broker",
            account_currency="CZK",
            snapshot_source=SnapshotSource.import_event,
            value="60",
            cost="50",
        ),
        _source(
            "exchange",
            account_type=AccountType.exchange,
            account_currency="USD",
            snapshot_source=SnapshotSource.price_refresh,
            value="40",
            cost="30",
        ),
    )

    result = build_dashboard_snapshot_view(portfolio)

    assert [card.account_currency for card in result.accounts] == ["CZK", "USD"]
    assert {account.source for account in portfolio.accounts} == {
        SnapshotSource.import_event,
        SnapshotSource.price_refresh,
    }
    assert not hasattr(result.accounts[0], "source")


def test_account_cards_use_canonical_sort_order() -> None:
    sources = (
        _source("loan", account_name="A", account_type=AccountType.loan),
        _source("broker-z", account_name="Z", value="50", cost="40"),
        _source(
            "crypto",
            account_name="A",
            account_type=AccountType.crypto_wallet,
            value="25",
            cost="20",
        ),
        _source("broker-a", account_name="A", value="25", cost="20"),
    )

    result = _dashboard(*sources)

    assert [card.account_id for card in result.accounts] == [
        "broker-a",
        "broker-z",
        "crypto",
        "loan",
    ]


def test_asset_type_allocations_group_values_and_unique_accounts() -> None:
    first_items = (
        _item("first", value="30", cost="20", allocation="50.0000", ordinal=1),
        _item(
            "first",
            value="30",
            cost="20",
            allocation="50.0000",
            ordinal=2,
            symbol="BBB",
        ),
    )
    result = _dashboard(
        _source("first", items=first_items),
        _source("second", value="40", cost="30"),
    )

    assert result.asset_type_allocations == (
        DashboardAssetTypeAllocation(
            asset_type=AssetType.stock,
            value=_money("100"),
            allocation_pct=Decimal("100.0000"),
            position_count=3,
            account_count=2,
        ),
    )


def test_asset_type_allocations_sort_by_value_then_asset_type() -> None:
    result = _dashboard(
        _source("stock", value="50", cost="40", asset_type=AssetType.stock),
        _source("crypto", value="25", cost="20", asset_type=AssetType.crypto),
        _source("bond", value="25", cost="20", asset_type=AssetType.bond),
    )

    assert [allocation.asset_type for allocation in result.asset_type_allocations] == [
        AssetType.stock,
        AssetType.bond,
        AssetType.crypto,
    ]
    assert [allocation.allocation_pct for allocation in result.asset_type_allocations] == [
        Decimal("50.0000"),
        Decimal("25.0000"),
        Decimal("25.0000"),
    ]


def test_global_position_allocations_do_not_reuse_account_local_percentages() -> None:
    result = _dashboard(
        _source("sixty", value="60", cost="50"),
        _source("forty", value="40", cost="30"),
    )

    assert [position.account_id for position in result.top_positions] == ["sixty", "forty"]
    assert [position.allocation_pct for position in result.top_positions] == [
        Decimal("60.0000"),
        Decimal("40.0000"),
    ]


def test_top_positions_include_all_account_scoped_positions() -> None:
    result = _dashboard(
        _source("first", value="60", cost="45", symbol="AAA"),
        _source("second", value="40", cost="35", symbol="BBB"),
    )

    assert result.top_positions == (
        DashboardTopPosition(
            account_id="first",
            listing_id="first-listing-1",
            asset_id="first-asset-1",
            symbol="AAA",
            name="AAA asset",
            asset_type=AssetType.stock,
            value=_money("60"),
            value_currency="EUR",
            unrealized_pnl=_quantity("15"),
            allocation_pct=Decimal("60.0000"),
        ),
        DashboardTopPosition(
            account_id="second",
            listing_id="second-listing-1",
            asset_id="second-asset-1",
            symbol="BBB",
            name="BBB asset",
            asset_type=AssetType.stock,
            value=_money("40"),
            value_currency="EUR",
            unrealized_pnl=_quantity("5"),
            allocation_pct=Decimal("40.0000"),
        ),
    )


def test_same_asset_in_two_accounts_remains_two_account_scoped_positions() -> None:
    first_item = replace(
        _item("first", value="60", cost="50"),
        listing_id="shared-listing",
        asset_id="shared-asset",
    )
    second_item = replace(
        _item("second", value="40", cost="30"),
        listing_id="shared-listing",
        asset_id="shared-asset",
    )

    result = _dashboard(
        _source("first", items=(first_item,)),
        _source("second", items=(second_item,)),
    )

    assert len(result.top_positions) == 2
    assert {position.account_id for position in result.top_positions} == {"first", "second"}
    assert {position.listing_id for position in result.top_positions} == {"shared-listing"}
    assert {position.asset_id for position in result.top_positions} == {"shared-asset"}


def test_top_positions_sort_by_value_then_unrealized_pnl() -> None:
    result = _dashboard(
        _source("lower-pnl", value="50", cost="45"),
        _source("higher-pnl", value="50", cost="40"),
    )

    assert [position.account_id for position in result.top_positions] == [
        "higher-pnl",
        "lower-pnl",
    ]


def test_every_input_permutation_produces_same_dashboard() -> None:
    views = tuple(
        build_portfolio_snapshot_view(source)
        for source in (
            _source("stock", value="50", cost="40"),
            _source("crypto", value="30", cost="20", asset_type=AssetType.crypto),
            _source("loan", account_type=AccountType.loan),
        )
    )
    expected = build_dashboard_snapshot_view(build_multi_account_portfolio_view(views))

    assert all(
        build_dashboard_snapshot_view(build_multi_account_portfolio_view(permutation)) == expected
        for permutation in permutations(views)
    )


def test_projection_does_not_mutate_portfolio_input() -> None:
    portfolio = _portfolio(_source("first"), _source("second", empty=True))
    original = deepcopy(portfolio)

    build_dashboard_snapshot_view(portfolio)

    assert portfolio == original


def test_all_dashboard_contracts_are_frozen() -> None:
    result = _dashboard(_source("account"))

    for target, field, value in (
        (result, "currency", "USD"),
        (result.summary, "account_count", 2),
        (result.accounts[0], "name", "changed"),
        (result.asset_type_allocations[0], "position_count", 2),
        (result.top_positions[0], "symbol", "CHANGED"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(cast(Any, target), field, value)


@pytest.mark.parametrize("value", [None, object(), (), []])
def test_invalid_top_level_input_fails_closed(value: object) -> None:
    with pytest.raises(DashboardSnapshotProjectionError, match=f"^{ERROR_MESSAGE}$"):
        build_dashboard_snapshot_view(cast(Any, value))


@pytest.mark.parametrize("account_type", [AccountType.bank, AccountType.cash, AccountType.savings])
def test_cash_account_type_builds_cash_only_dashboard_card(account_type: AccountType) -> None:
    result = _dashboard(_source("account", account_type=account_type, cash="10"))

    assert result.summary.cash_value == _money("10")
    assert result.summary.investment_account_count == 0
    assert result.summary.liability_account_count == 0
    assert result.accounts[0].cash_value == _money("10")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("currency", "usd"),
        ("currency", "EURO"),
        ("calculation_version", True),
        ("calculation_version", 0),
        ("calculation_version", 2_147_483_648),
        ("granularity", "day"),
        ("timestamp", datetime(2032, 8, 2, tzinfo=UTC)),
        ("timestamp", datetime(2032, 8, 2, 0, 0, 0, 1)),
        ("timestamp", datetime(2032, 8, 2, 1)),
    ],
)
def test_corrupt_exact_metadata_fails_closed(field: str, value: object) -> None:
    portfolio = _portfolio(_source("account"))
    corrupt = replace(cast(Any, portfolio), **{field: value})

    with pytest.raises(DashboardSnapshotProjectionError):
        build_dashboard_snapshot_view(cast(Any, corrupt))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_count", 0),
        ("account_count", True),
        ("position_count", -1),
        ("position_count", 2),
    ],
)
def test_corrupt_aggregate_counts_fail_closed(field: str, value: object) -> None:
    portfolio = _portfolio(_source("account"))
    corrupt = replace(
        portfolio,
        summary=replace(cast(Any, portfolio.summary), **{field: value}),
    )

    with pytest.raises(DashboardSnapshotProjectionError):
        build_dashboard_snapshot_view(cast(Any, corrupt))


@pytest.mark.parametrize("identity", ["account", "snapshot"])
def test_duplicate_account_or_snapshot_identity_fails_closed(identity: str) -> None:
    portfolio = _portfolio(_source("first"), _source("second"))
    first, second = portfolio.accounts
    duplicate = (
        replace(second, account=first.account)
        if identity == "account"
        else replace(second, snapshot_id=first.snapshot_id)
    )

    with pytest.raises(DashboardSnapshotProjectionError):
        build_dashboard_snapshot_view(replace(portfolio, accounts=(first, duplicate)))


@pytest.mark.parametrize(
    "value",
    [
        "10.000000",
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("0.0000001"),
        Decimal("1000000000000.000000"),
    ],
)
def test_invalid_aggregate_money_fails_closed(value: object) -> None:
    portfolio = _portfolio(_source("account"))
    corrupt = replace(
        portfolio,
        summary=replace(portfolio.summary, cash_value=cast(Any, value)),
    )

    with pytest.raises(DashboardSnapshotProjectionError):
        build_dashboard_snapshot_view(corrupt)


def test_total_assets_liabilities_invariant_fails_closed() -> None:
    portfolio = _portfolio(_source("account"))
    corrupt = replace(
        portfolio,
        summary=replace(portfolio.summary, total_value=_money("999")),
    )

    with pytest.raises(DashboardSnapshotProjectionError):
        build_dashboard_snapshot_view(corrupt)


def test_dashboard_maps_upstream_unrealized_value_without_recalculation() -> None:
    portfolio = _portfolio(_source("account"))
    corrupt = replace(
        portfolio,
        summary=replace(portfolio.summary, unrealized_pnl_value=_money("999")),
    )

    result = build_dashboard_snapshot_view(corrupt)

    assert result.summary.unrealized_pnl_value == _money("999")


@pytest.mark.parametrize("presentation", ["asset allocation", "top positions"])
def test_position_sum_must_match_aggregate_investment(presentation: str) -> None:
    portfolio = _portfolio(_source("account"))
    corrupt_summary = replace(
        portfolio.summary,
        investment_value=_money("101"),
        investment_cost_basis=_money("81"),
        total_value=_money("111"),
    )

    with pytest.raises(DashboardSnapshotProjectionError):
        build_dashboard_snapshot_view(replace(portfolio, summary=corrupt_summary))
    assert presentation


def test_nonrepresentable_global_position_percentage_fails_closed() -> None:
    portfolio = _portfolio(
        _source("one", value="1", cost="1"),
        _source("two", value="2", cost="2"),
    )

    with pytest.raises(DashboardSnapshotProjectionError):
        build_dashboard_snapshot_view(portfolio)


def test_account_position_count_must_match_positions_tuple() -> None:
    portfolio = _portfolio(_source("account"))
    account = portfolio.accounts[0]
    corrupt = replace(
        account,
        summary=replace(account.summary, position_count=0),
    )

    with pytest.raises(DashboardSnapshotProjectionError):
        build_dashboard_snapshot_view(replace(portfolio, accounts=(corrupt,)))


@pytest.mark.parametrize("field", ["value_currency", "cost_currency"])
def test_position_output_currency_must_match_portfolio(field: str) -> None:
    portfolio = _portfolio(_source("account"))
    account = portfolio.accounts[0]
    position = replace(cast(Any, account.positions[0]), **{field: "USD"})
    corrupt = replace(account, positions=(position,))

    with pytest.raises(DashboardSnapshotProjectionError):
        build_dashboard_snapshot_view(replace(portfolio, accounts=(corrupt,)))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("listing_id", ""),
        ("asset_id", " asset "),
        ("symbol", ""),
        ("name", " "),
        ("asset_type", "stock"),
        ("value", Decimal("-1.000000")),
        ("value", Decimal("1.0000001")),
        ("unrealized_pnl", Decimal("0.00000000001")),
    ],
)
def test_corrupt_position_evidence_fails_closed(field: str, value: object) -> None:
    portfolio = _portfolio(_source("account"))
    account = portfolio.accounts[0]
    position = replace(cast(Any, account.positions[0]), **{field: value})

    with pytest.raises(DashboardSnapshotProjectionError):
        build_dashboard_snapshot_view(
            replace(portfolio, accounts=(replace(account, positions=(position,)),))
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("account_id", ""),
        ("name", " name "),
        ("currency", "czk"),
        ("account_type", "broker"),
    ],
)
def test_corrupt_account_metadata_fails_closed(field: str, value: object) -> None:
    portfolio = _portfolio(_source("account"))
    account_view = portfolio.accounts[0]
    account = replace(cast(Any, account_view.account), **{field: value})

    with pytest.raises(DashboardSnapshotProjectionError):
        build_dashboard_snapshot_view(
            replace(portfolio, accounts=(replace(account_view, account=account),))
        )


def test_invalid_account_or_position_container_fails_closed() -> None:
    portfolio = _portfolio(_source("account"))
    account = portfolio.accounts[0]
    corrupt_accounts = replace(portfolio, accounts=cast(Any, [account]))
    corrupt_positions = replace(
        portfolio,
        accounts=(replace(account, positions=cast(Any, list(account.positions))),),
    )

    for corrupt in (corrupt_accounts, corrupt_positions):
        with pytest.raises(DashboardSnapshotProjectionError):
            build_dashboard_snapshot_view(corrupt)


def test_error_contract_is_stable_generic_and_contains_no_evidence() -> None:
    error = DashboardSnapshotProjectionError()

    assert str(error) == ERROR_MESSAGE
    for forbidden in (
        "account-123",
        "snapshot-123",
        "listing-123",
        "asset-123",
        "AAA",
        "EUR",
        "2032",
        "100.000000",
    ):
        assert forbidden not in str(error)


def test_projection_does_not_change_ambient_decimal_context() -> None:
    portfolio = _portfolio(
        _source("sixty", value="60", cost="50"),
        _source("forty", value="40", cost="30"),
    )
    before = getcontext().copy()
    try:
        getcontext().prec = 7
        configured = getcontext().copy()

        result = build_dashboard_snapshot_view(portfolio)

        assert result.top_positions[0].allocation_pct == Decimal("60.0000")
        assert repr(getcontext()) == repr(configured)
    finally:
        setcontext(before)


def test_projection_is_synchronous_with_one_pure_input() -> None:
    signature = inspect.signature(build_dashboard_snapshot_view)

    assert not inspect.iscoroutinefunction(build_dashboard_snapshot_view)
    assert tuple(signature.parameters) == ("portfolio",)
    assert signature.return_annotation == "DashboardSnapshotView"


def test_decimal_values_and_tuple_outputs_are_preserved() -> None:
    result = _dashboard(
        _source("sixty", value="60", cost="50"),
        _source("forty", value="40", cost="30"),
    )

    assert isinstance(result.summary.total_value, Decimal)
    assert result.summary.total_value.as_tuple().exponent == -6
    assert isinstance(result.accounts, tuple)
    assert isinstance(result.asset_type_allocations, tuple)
    assert isinstance(result.top_positions, tuple)
    assert [position.allocation_pct for position in result.top_positions] == [
        Decimal("60.0000"),
        Decimal("40.0000"),
    ]


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
        "PortfolioSnapshotReader",
        "AuthorizedPortfolioSnapshotService",
    }
    forbidden_text = (
        "app.modules.portfolio.",
        "float(",
        "round(",
        "datetime.now",
        "uuid",
        "latest",
        "fallback",
        "open(",
        "print(",
        "daily_change",
        "weekly_change",
        "monthly_change",
        "performance",
        "yield",
        "interest",
        "benchmark",
        "trend",
    )
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
        assert all(forbidden not in source.lower() for forbidden in forbidden_text)


def test_result_contract_shapes_are_exact() -> None:
    result = _dashboard(_source("account"))

    assert type(result) is DashboardSnapshotView
    assert type(result.summary) is DashboardSnapshotSummary
    assert type(result.accounts[0]) is DashboardAccountCard
    assert type(result.asset_type_allocations[0]) is DashboardAssetTypeAllocation
    assert type(result.top_positions[0]) is DashboardTopPosition


def test_corrupt_exact_member_types_fail_closed() -> None:
    portfolio = _portfolio(_source("account"))
    account = portfolio.accounts[0]
    corrupt_values = (
        replace(portfolio, summary=cast(Any, object())),
        replace(portfolio, accounts=(cast(Any, object()),)),
        replace(
            portfolio,
            accounts=(replace(account, account=cast(Any, object())),),
        ),
        replace(
            portfolio,
            accounts=(replace(account, summary=cast(Any, object())),),
        ),
        replace(
            portfolio,
            accounts=(replace(account, positions=(cast(PortfolioPositionView, object()),)),),
        ),
    )

    for corrupt in corrupt_values:
        with pytest.raises(DashboardSnapshotProjectionError):
            build_dashboard_snapshot_view(corrupt)


def test_dashboard_models_do_not_expose_history_or_source_metadata() -> None:
    result = _dashboard(_source("account"))

    assert not hasattr(result, "history")
    assert not hasattr(result, "performance")
    assert not hasattr(result.accounts[0], "source")
    assert not hasattr(result.top_positions[0], "price_source")
    assert not hasattr(result.top_positions[0], "native_value")
