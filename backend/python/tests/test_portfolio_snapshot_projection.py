import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from app.modules.portfolio_snapshot.models import (
    AccountType,
    AssetType,
    PortfolioSnapshotItemSource,
    PortfolioSnapshotSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.portfolio_snapshot.projection import (
    PortfolioSnapshotProjectionError,
    build_portfolio_snapshot_view,
)

_TIMESTAMP = datetime(2026, 7, 27, 10, 15)
_MODULE_DIR = Path(__file__).parents[1] / "app" / "modules" / "portfolio_snapshot"


def _item(
    *,
    item_id: str = "item-1",
    listing_id: str = "listing-1",
    asset_id: str = "asset-1",
    symbol: str = "AAA",
    name: str = "Alpha Asset",
    asset_type: AssetType = AssetType.stock,
    quantity: Decimal = Decimal("2"),
    price_per_unit: Decimal = Decimal("30"),
    price_currency: str = "USD",
    price_timestamp: datetime = datetime(2026, 7, 27, 10),
    value: Decimal = Decimal("60"),
    value_currency: str = "EUR",
    cost_basis: Decimal = Decimal("50"),
    cost_currency: str = "EUR",
    unrealized_pnl: Decimal = Decimal("10"),
    allocation_pct: Decimal = Decimal("60"),
    native_value: Decimal = Decimal("60"),
    native_value_currency: str = "USD",
    native_cost_basis: Decimal = Decimal("50"),
    native_cost_currency: str = "USD",
) -> PortfolioSnapshotItemSource:
    return PortfolioSnapshotItemSource(
        item_id=item_id,
        listing_id=listing_id,
        asset_id=asset_id,
        symbol=symbol,
        name=name,
        asset_type=asset_type,
        quantity=quantity,
        price_per_unit=price_per_unit,
        price_currency=price_currency,
        price_timestamp=price_timestamp,
        value=value,
        value_currency=value_currency,
        cost_basis=cost_basis,
        cost_currency=cost_currency,
        unrealized_pnl=unrealized_pnl,
        allocation_pct=allocation_pct,
        native_value=native_value,
        native_value_currency=native_value_currency,
        native_cost_basis=native_cost_basis,
        native_cost_currency=native_cost_currency,
    )


def _second_item() -> PortfolioSnapshotItemSource:
    return _item(
        item_id="item-2",
        listing_id="listing-2",
        asset_id="asset-2",
        symbol="BBB",
        name="Beta Asset",
        asset_type=AssetType.crypto,
        quantity=Decimal("4"),
        price_per_unit=Decimal("10"),
        price_currency="GBP",
        value=Decimal("40"),
        cost_basis=Decimal("30"),
        unrealized_pnl=Decimal("10"),
        allocation_pct=Decimal("40"),
        native_value=Decimal("40"),
        native_value_currency="GBP",
        native_cost_basis=Decimal("30"),
        native_cost_currency="GBP",
    )


def _source(
    *,
    snapshot_id: str = "snapshot-1",
    account_id: str = "account-1",
    account_name: str = "Primary broker",
    account_type: AccountType = AccountType.broker,
    account_currency: str = "CZK",
    output_currency: str = "EUR",
    timestamp: datetime = _TIMESTAMP,
    granularity: SnapshotGranularity = SnapshotGranularity.minute,
    source: SnapshotSource = SnapshotSource.manual_recalculation,
    calculation_version: int = 1,
    calculated_at: datetime = datetime(2026, 7, 27, 10, 15, 0, 123000),
    created_at: datetime = datetime(2026, 7, 27, 10, 15, 0, 456000),
    cash_value: Decimal = Decimal("10"),
    investment_value: Decimal = Decimal("100"),
    investment_cost_basis: Decimal = Decimal("80"),
    liabilities_value: Decimal = Decimal("0"),
    total_value: Decimal = Decimal("110"),
    net_deposits_value: Decimal = Decimal("70"),
    realized_pnl_value: Decimal = Decimal("5"),
    unrealized_pnl_value: Decimal = Decimal("20"),
    fees_value: Decimal = Decimal("2"),
    taxes_value: Decimal = Decimal("1"),
    items: tuple[PortfolioSnapshotItemSource, ...] | None = None,
) -> PortfolioSnapshotSource:
    return PortfolioSnapshotSource(
        snapshot_id=snapshot_id,
        account_id=account_id,
        account_name=account_name,
        account_type=account_type,
        account_currency=account_currency,
        output_currency=output_currency,
        timestamp=timestamp,
        granularity=granularity,
        source=source,
        calculation_version=calculation_version,
        calculated_at=calculated_at,
        created_at=created_at,
        cash_value=cash_value,
        investment_value=investment_value,
        investment_cost_basis=investment_cost_basis,
        liabilities_value=liabilities_value,
        total_value=total_value,
        net_deposits_value=net_deposits_value,
        realized_pnl_value=realized_pnl_value,
        unrealized_pnl_value=unrealized_pnl_value,
        fees_value=fees_value,
        taxes_value=taxes_value,
        items=items if items is not None else (_item(), _second_item()),
    )


def test_investment_snapshot_builds_exact_portfolio_view() -> None:
    view = build_portfolio_snapshot_view(_source())

    assert view.snapshot_id == "snapshot-1"
    assert view.account.account_id == "account-1"
    assert view.account.name == "Primary broker"
    assert view.account.account_type is AccountType.broker
    assert view.account.currency == "CZK"
    assert view.timestamp == _TIMESTAMP
    assert view.granularity is SnapshotGranularity.minute
    assert view.currency == "EUR"
    assert view.source is SnapshotSource.manual_recalculation
    assert view.calculation_version == 1
    assert tuple(getattr(view.summary, field.name) for field in fields(view.summary)) == (
        Decimal("10"),
        Decimal("100"),
        Decimal("80"),
        Decimal("0"),
        Decimal("110"),
        Decimal("70"),
        Decimal("5"),
        Decimal("20"),
        Decimal("2"),
        Decimal("1"),
        2,
    )
    assert [position.symbol for position in view.positions] == ["BBB", "AAA"]
    alpha = view.positions[1]
    assert tuple(getattr(alpha, field.name) for field in fields(alpha)) == (
        "listing-1",
        "asset-1",
        "AAA",
        "Alpha Asset",
        AssetType.stock,
        Decimal("2"),
        Decimal("30"),
        "USD",
        datetime(2026, 7, 27, 10),
        Decimal("60"),
        "EUR",
        Decimal("50"),
        "EUR",
        Decimal("10"),
        Decimal("60"),
        Decimal("60"),
        "USD",
        Decimal("50"),
        "USD",
    )


def test_mixed_currency_positions_preserve_native_fields_and_output_aggregates() -> None:
    view = build_portfolio_snapshot_view(_source())

    assert view.account.currency == "CZK"
    assert view.currency == "EUR"
    assert view.summary.investment_value == Decimal("100")
    assert view.summary.investment_cost_basis == Decimal("80")
    assert {position.price_currency for position in view.positions} == {"GBP", "USD"}
    assert {position.native_value_currency for position in view.positions} == {"GBP", "USD"}
    assert {position.native_cost_currency for position in view.positions} == {"GBP", "USD"}
    assert {position.value_currency for position in view.positions} == {"EUR"}
    assert {position.cost_currency for position in view.positions} == {"EUR"}


def test_position_permutation_produces_structurally_equal_view() -> None:
    source = _source()
    permuted = replace(source, items=tuple(reversed(source.items)))

    assert build_portfolio_snapshot_view(source) == build_portfolio_snapshot_view(permuted)


def test_inputs_are_not_mutated_and_outputs_are_frozen() -> None:
    source = _source()
    original = deepcopy(source)
    view = build_portfolio_snapshot_view(source)

    assert source == original
    with pytest.raises(FrozenInstanceError):
        cast(Any, view).currency = "USD"
    with pytest.raises(FrozenInstanceError):
        cast(Any, view.summary).total_value = Decimal("0")
    with pytest.raises(FrozenInstanceError):
        cast(Any, view.positions[0]).value = Decimal("0")


def test_financial_values_never_use_binary_float() -> None:
    view = build_portfolio_snapshot_view(_source())
    financial_values = (
        *(getattr(view.summary, field.name) for field in fields(view.summary)[:-1]),
        *(
            value
            for position in view.positions
            for value in (
                position.quantity,
                position.price_per_unit,
                position.value,
                position.cost_basis,
                position.unrealized_pnl,
                position.allocation_pct,
                position.native_value,
                position.native_cost_basis,
            )
        ),
    )
    assert all(isinstance(value, Decimal) for value in financial_values)

    for path in _MODULE_DIR.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "float"
            for node in ast.walk(tree)
        )


@pytest.mark.parametrize(
    "mutation",
    [
        {"investment_value": Decimal("101"), "total_value": Decimal("111")},
        {"investment_cost_basis": Decimal("81"), "unrealized_pnl_value": Decimal("19")},
        {"unrealized_pnl_value": Decimal("19")},
        {"total_value": Decimal("111")},
    ],
    ids=[
        "investment_value mismatch",
        "investment_cost_basis mismatch",
        "unrealized_pnl mismatch",
        "total_value mismatch",
    ],
)
def test_aggregate_mismatch_fails_closed(mutation: dict[str, object]) -> None:
    source = cast(
        PortfolioSnapshotSource,
        cast(Any, replace)(_source(), **mutation),
    )
    with pytest.raises(PortfolioSnapshotProjectionError):
        build_portfolio_snapshot_view(source)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda source: replace(
            source,
            items=(replace(source.items[0], value_currency="USD"), source.items[1]),
        ),
        lambda source: replace(
            source,
            items=(replace(source.items[0], cost_currency="USD"), source.items[1]),
        ),
        lambda source: replace(
            source,
            items=(replace(source.items[0], allocation_pct=Decimal("59")), source.items[1]),
        ),
        lambda source: replace(
            source,
            items=(
                replace(source.items[0], price_timestamp=datetime(2026, 7, 27, 10, 16)),
                source.items[1],
            ),
        ),
        lambda source: replace(
            source,
            items=(source.items[0], replace(source.items[1], item_id=source.items[0].item_id)),
        ),
        lambda source: replace(
            source,
            items=(
                source.items[0],
                replace(source.items[1], listing_id=source.items[0].listing_id),
            ),
        ),
        lambda source: replace(
            source,
            items=(replace(source.items[0], quantity=cast(Decimal, 2.0)), source.items[1]),
        ),
        lambda source: replace(
            source,
            items=(
                replace(source.items[0], price_per_unit=Decimal("30.00000000001")),
                source.items[1],
            ),
        ),
        lambda source: replace(
            source,
            items=(
                replace(source.items[0], native_value=Decimal("60.00000000001")),
                source.items[1],
            ),
        ),
    ],
    ids=[
        "wrong value currency",
        "wrong cost currency",
        "wrong allocation",
        "future price timestamp",
        "duplicate item ID",
        "duplicate listing ID",
        "malformed quantity",
        "malformed price",
        "malformed native value",
    ],
)
def test_item_mismatch_fails_closed(mutator: Any) -> None:
    with pytest.raises(PortfolioSnapshotProjectionError):
        build_portfolio_snapshot_view(mutator(_source()))


def test_empty_investment_account_builds_zero_position_view() -> None:
    source = _source(
        investment_value=Decimal("0"),
        investment_cost_basis=Decimal("0"),
        unrealized_pnl_value=Decimal("0"),
        total_value=Decimal("10"),
        items=(),
    )

    view = build_portfolio_snapshot_view(source)

    assert view.positions == ()
    assert view.summary.position_count == 0
    assert view.summary.investment_value == 0


def test_liability_snapshot_builds_summary_without_positions() -> None:
    source = _source(
        account_type=AccountType.loan,
        cash_value=Decimal("0"),
        investment_value=Decimal("0"),
        investment_cost_basis=Decimal("0"),
        liabilities_value=Decimal("25"),
        total_value=Decimal("-25"),
        net_deposits_value=Decimal("0"),
        realized_pnl_value=Decimal("0"),
        unrealized_pnl_value=Decimal("0"),
        fees_value=Decimal("0"),
        taxes_value=Decimal("0"),
        items=(),
    )

    view = build_portfolio_snapshot_view(source)

    assert view.positions == ()
    assert view.summary.liabilities_value == Decimal("25")
    assert view.summary.total_value == Decimal("-25")


@pytest.mark.parametrize(
    "account_type",
    [AccountType.bank, AccountType.cash, AccountType.savings],
)
def test_unsupported_presentation_account_type_fails_closed(
    account_type: AccountType,
) -> None:
    source = _source(
        account_type=account_type,
        investment_value=Decimal("0"),
        investment_cost_basis=Decimal("0"),
        unrealized_pnl_value=Decimal("0"),
        total_value=Decimal("10"),
        items=(),
    )
    with pytest.raises(PortfolioSnapshotProjectionError):
        build_portfolio_snapshot_view(source)


@pytest.mark.parametrize(
    "mutation",
    [
        {"snapshot_id": ""},
        {"snapshot_id": " snapshot-1 "},
        {"output_currency": "eur"},
        {"timestamp": datetime(2026, 7, 27, 10, 15, tzinfo=UTC)},
        {"created_at": datetime(2026, 7, 27, 10, 15, 0, 1)},
        {"timestamp": datetime(2026, 7, 27, 10, 15, 1)},
        {"calculation_version": 0},
        {"source": cast(SnapshotSource, "manual_recalculation")},
    ],
    ids=[
        "blank ID",
        "untrimmed ID",
        "lowercase currency",
        "timezone-aware datetime",
        "sub-millisecond datetime",
        "misaligned granularity",
        "invalid calculation version",
        "invalid source",
    ],
)
def test_invalid_metadata_fails_closed(mutation: dict[str, object]) -> None:
    source = cast(
        PortfolioSnapshotSource,
        cast(Any, replace)(_source(), **mutation),
    )
    with pytest.raises(PortfolioSnapshotProjectionError) as raised:
        build_portfolio_snapshot_view(source)
    assert str(raised.value) == "Portfolio snapshot evidence cannot produce a complete view."


def test_zero_value_position_requires_zero_allocation() -> None:
    zero = _item(
        quantity=Decimal("0"),
        price_per_unit=Decimal("30"),
        value=Decimal("0"),
        cost_basis=Decimal("0"),
        unrealized_pnl=Decimal("0"),
        allocation_pct=Decimal("0"),
        native_value=Decimal("0"),
        native_cost_basis=Decimal("0"),
    )
    source = _source(
        cash_value=Decimal("10"),
        investment_value=Decimal("0"),
        investment_cost_basis=Decimal("0"),
        total_value=Decimal("10"),
        net_deposits_value=Decimal("0"),
        realized_pnl_value=Decimal("0"),
        unrealized_pnl_value=Decimal("0"),
        fees_value=Decimal("0"),
        taxes_value=Decimal("0"),
        items=(zero,),
    )

    assert build_portfolio_snapshot_view(source).positions[0].allocation_pct == 0
    with pytest.raises(PortfolioSnapshotProjectionError):
        build_portfolio_snapshot_view(
            replace(source, items=(replace(zero, allocation_pct=Decimal("1")),))
        )


def test_projection_has_a_pure_import_and_call_boundary() -> None:
    path = _MODULE_DIR / "projection.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {
        "sqlalchemy",
        "app.db",
        "repository",
        "fastapi",
    }
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(
        module == forbidden or module.startswith(f"{forbidden}.")
        for module in imported
        for forbidden in forbidden_imports
    )

    forbidden_names = {
        "AsyncSession",
        "HoldingModel",
        "PriceSnapshotModel",
        "ExchangeRateModel",
        "FastAPI",
        "uuid",
    }
    assert not forbidden_names.intersection(
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "now"
        for node in ast.walk(tree)
    )
