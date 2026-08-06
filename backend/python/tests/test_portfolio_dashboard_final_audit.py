"""Static and pure cross-boundary evidence for the final 5L audit."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.api.router import legacy_router
from app.config.settings import Settings
from app.main import create_app
from app.modules.dashboard_snapshot.api_models import (
    DashboardAccountCardResponse,
    DashboardAssetTypeAllocationResponse,
    DashboardSnapshotResponse,
    DashboardSnapshotSummaryResponse,
    DashboardTopPositionResponse,
)
from app.modules.dashboard_snapshot.models import (
    DashboardAccountCard,
    DashboardAssetTypeAllocation,
    DashboardSnapshotSummary,
    DashboardSnapshotView,
    DashboardTopPosition,
)
from app.modules.dashboard_snapshot.projection import build_dashboard_snapshot_view
from app.modules.portfolio_snapshot.aggregate_models import (
    MultiAccountPortfolioAccountView,
    MultiAccountPortfolioSummary,
    MultiAccountPortfolioView,
)
from app.modules.portfolio_snapshot.aggregation import build_multi_account_portfolio_view
from app.modules.portfolio_snapshot.api_models import (
    PortfolioCurrencyAmountResponse,
    PortfolioSnapshotAccountResponse,
    PortfolioSnapshotPositionResponse,
    PortfolioSnapshotResponse,
    PortfolioSnapshotSummaryResponse,
)
from app.modules.portfolio_snapshot.authorized_reader import (
    PortfolioSnapshotUnavailableError,
)
from app.modules.portfolio_snapshot.models import (
    AccountType,
    AssetType,
    PortfolioAccountView,
    PortfolioPositionView,
    PortfolioSnapshotItemSource,
    PortfolioSnapshotSource,
    PortfolioSnapshotView,
    PortfolioSummaryView,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.portfolio_snapshot.multi_account_api_models import (
    ExactAccountSnapshotRequest,
    ExactPortfolioSnapshotSetRequest,
    MultiAccountPortfolioAccountResponse,
    MultiAccountPortfolioResponse,
    MultiAccountPortfolioSummaryResponse,
)
from app.modules.portfolio_snapshot.multi_account_service import (
    ExactAccountSnapshotSelection,
    ReadAuthorizedMultiAccountPortfolioSnapshotCommand,
    ReadAuthorizedMultiAccountPortfolioSnapshotResult,
)
from app.modules.portfolio_snapshot.projection import (
    PortfolioSnapshotProjectionError,
    build_portfolio_snapshot_view,
)
from app.modules.portfolio_snapshot.reader import (
    CompletePortfolioSnapshotRead,
    ReadExactPortfolioSnapshotCommand,
)

ROOT = Path(__file__).parents[3]
APP = ROOT / "backend" / "python" / "app"
MODULES = APP / "modules"
AUDIT_REPORT = ROOT / "ChatGPT" / "audits" / "5L-final-audit.md"
SNAPSHOT_AT = datetime(2032, 8, 2)
CREATED_AT = datetime(2032, 8, 2, 0, 0, 0, 123000)
PRICE_AT = datetime(2032, 8, 1, 12, 30, 0, 123000)
LEGACY_PATH = "/api/v1/portfolio"
SINGLE_PATH = "/api/v1/portfolio/accounts/{account_id}/snapshot"
PORTFOLIO_PATH = "/api/v1/portfolio/snapshot"
DASHBOARD_PATH = "/api/v1/dashboard/snapshot"
FINANCIAL_FIELDS = {
    "cashValue",
    "investmentValue",
    "investmentCostBasis",
    "liabilitiesValue",
    "totalValue",
    "netDepositsValue",
    "realizedPnlValue",
    "unrealizedPnlValue",
    "feesValue",
    "taxesValue",
    "assetsValue",
    "quantity",
    "pricePerUnit",
    "value",
    "costBasis",
    "unrealizedPnl",
    "allocationPct",
    "nativeValue",
    "nativeCostBasis",
}
LEAKED_FIELDS = {
    "userId",
    "email",
    "membership",
    "member",
    "role",
    "relationType",
    "invitedBy",
    "selectedItemIds",
    "priceSource",
    "priceSnapshotId",
    "exchangeRateId",
    "exchangeRates",
    "cashValueByCurrency",
    "investmentValueByCurrency",
    "investmentCostBasisByCurrency",
    "realizedPnlByCurrency",
    "unrealizedPnlByCurrency",
    "feesByCurrency",
    "taxesByCurrency",
    "calculatedAt",
    "createdAt",
    "updatedAt",
    "passwordHash",
}
DASHBOARD_FORBIDDEN = {
    "cashByCurrency",
    "netDepositsByCurrency",
    "quantity",
    "pricePerUnit",
    "priceCurrency",
    "priceTimestamp",
    "costBasis",
    "costCurrency",
    "nativeValue",
    "nativeValueCurrency",
    "nativeCostBasis",
    "nativeCostCurrency",
    "source",
}


def _source(
    account_id: str,
    *,
    value: str = "60.000000",
    cost: str = "50.000000",
    account_type: AccountType = AccountType.broker,
    item_suffix: str = "a",
    asset_type: AssetType = AssetType.stock,
) -> PortfolioSnapshotSource:
    money_value = Decimal(value).quantize(Decimal("0.000001"))
    money_cost = Decimal(cost).quantize(Decimal("0.000001"))
    quantity_value = Decimal(value).quantize(Decimal("0.0000000001"))
    quantity_cost = Decimal(cost).quantize(Decimal("0.0000000001"))
    item = PortfolioSnapshotItemSource(
        item_id=f"{account_id}-item-{item_suffix}",
        listing_id=f"{account_id}-listing-{item_suffix}",
        asset_id=f"{account_id}-asset-{item_suffix}",
        symbol=f"ASSET-{item_suffix.upper()}",
        name=f"Asset {item_suffix.upper()}",
        asset_type=asset_type,
        quantity=Decimal("1.0000000000"),
        price_per_unit=quantity_value,
        price_currency="USD",
        price_timestamp=PRICE_AT,
        value=money_value,
        value_currency="EUR",
        cost_basis=quantity_cost,
        cost_currency="EUR",
        unrealized_pnl=quantity_value - quantity_cost,
        allocation_pct=Decimal("100.0000"),
        native_value=quantity_value,
        native_value_currency="USD",
        native_cost_basis=quantity_cost,
        native_cost_currency="USD",
    )
    return PortfolioSnapshotSource(
        snapshot_id=f"{account_id}-snapshot",
        account_id=account_id,
        account_name=f"{account_id} account",
        account_type=account_type,
        account_currency="CZK",
        output_currency="EUR",
        timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        calculated_at=CREATED_AT,
        created_at=CREATED_AT,
        cash_value=Decimal("0.000000"),
        cash_by_currency=(),
        investment_value=money_value,
        investment_cost_basis=money_cost,
        liabilities_value=Decimal("0.000000"),
        total_value=money_value,
        net_deposits_value=Decimal("0.000000"),
        net_deposits_by_currency=(),
        realized_pnl_value=Decimal("0.000000"),
        unrealized_pnl_value=money_value - money_cost,
        fees_value=Decimal("0.000000"),
        taxes_value=Decimal("0.000000"),
        items=(item,),
    )


def _liability_source(
    account_id: str,
    account_type: AccountType,
) -> PortfolioSnapshotSource:
    return PortfolioSnapshotSource(
        snapshot_id=f"{account_id}-snapshot",
        account_id=account_id,
        account_name=f"{account_id} account",
        account_type=account_type,
        account_currency="CZK",
        output_currency="EUR",
        timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        calculated_at=CREATED_AT,
        created_at=CREATED_AT,
        cash_value=Decimal("0.000000"),
        cash_by_currency=(),
        investment_value=Decimal("0.000000"),
        investment_cost_basis=Decimal("0.000000"),
        liabilities_value=Decimal("25.000000"),
        total_value=Decimal("-25.000000"),
        net_deposits_value=Decimal("0.000000"),
        net_deposits_by_currency=(),
        realized_pnl_value=Decimal("0.000000"),
        unrealized_pnl_value=Decimal("0.000000"),
        fees_value=Decimal("0.000000"),
        taxes_value=Decimal("0.000000"),
        items=(),
    )


def _empty_source(account_id: str) -> PortfolioSnapshotSource:
    source = _liability_source(account_id, AccountType.loan)
    return PortfolioSnapshotSource(
        snapshot_id=source.snapshot_id,
        account_id=source.account_id,
        account_name=source.account_name,
        account_type=AccountType.broker,
        account_currency=source.account_currency,
        output_currency=source.output_currency,
        timestamp=source.timestamp,
        granularity=source.granularity,
        source=source.source,
        calculation_version=source.calculation_version,
        calculated_at=source.calculated_at,
        created_at=source.created_at,
        cash_value=Decimal("0.000000"),
        cash_by_currency=(),
        investment_value=Decimal("0.000000"),
        investment_cost_basis=Decimal("0.000000"),
        liabilities_value=Decimal("0.000000"),
        total_value=Decimal("0.000000"),
        net_deposits_value=Decimal("0.000000"),
        net_deposits_by_currency=(),
        realized_pnl_value=Decimal("0.000000"),
        unrealized_pnl_value=Decimal("0.000000"),
        fees_value=Decimal("0.000000"),
        taxes_value=Decimal("0.000000"),
        items=(),
    )


def _views() -> tuple[PortfolioSnapshotView, PortfolioSnapshotView]:
    return (
        build_portfolio_snapshot_view(_source("account-a", value="60", cost="50")),
        build_portfolio_snapshot_view(_source("account-b", value="40", cost="30")),
    )


def _imports(path: Path) -> tuple[set[str], set[str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                modules.add(node.module)
            names.update(alias.asname or alias.name for alias in node.names)
    return modules, names


def _call_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def _session_call_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        receiver = node.func.value
        if (
            isinstance(receiver, ast.Attribute)
            and isinstance(receiver.value, ast.Name)
            and receiver.value.id == "self"
            and receiver.attr == "session"
        ):
            result.add(node.func.attr)
    return result


def _serialized_views() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    views = _views()
    multi = build_multi_account_portfolio_view(views)
    dashboard = build_dashboard_snapshot_view(multi)
    single_payload = PortfolioSnapshotResponse.model_validate(
        views[0],
        from_attributes=True,
    ).model_dump(mode="json", by_alias=True)
    multi_payload = MultiAccountPortfolioResponse.model_validate(
        multi,
        from_attributes=True,
    ).model_dump(mode="json", by_alias=True)
    dashboard_payload = DashboardSnapshotResponse.model_validate(
        dashboard,
        from_attributes=True,
    ).model_dump(mode="json", by_alias=True)
    return single_payload, multi_payload, dashboard_payload


def _audit_json(value: object, *, dashboard: bool = False) -> None:
    if isinstance(value, dict):
        assert LEAKED_FIELDS.isdisjoint(value)
        if dashboard:
            assert DASHBOARD_FORBIDDEN.isdisjoint(value)
        for key, child in value.items():
            if key in FINANCIAL_FIELDS:
                assert isinstance(child, str)
                Decimal(child)
            _audit_json(child, dashboard=dashboard)
    elif isinstance(value, list):
        for child in value:
            _audit_json(child, dashboard=dashboard)
    else:
        assert not isinstance(value, float)


def _assert_frozen_dataclass(model: type[object]) -> None:
    assert is_dataclass(model)
    params = cast(Any, model).__dataclass_params__
    assert params.frozen is True
    assert "__slots__" in model.__dict__


def test_exact_production_route_inventory(test_settings: Settings) -> None:
    paths = create_app(test_settings).openapi()["paths"]
    relevant = {
        (method.upper(), path)
        for path, operations in paths.items()
        for method in operations
        if path == LEGACY_PATH or "portfolio" in path or "dashboard/snapshot" in path
        if method in {"get", "post", "put", "patch", "delete"}
    }
    assert relevant == {
        ("GET", LEGACY_PATH),
        ("GET", SINGLE_PATH),
        ("POST", PORTFOLIO_PATH),
        ("POST", DASHBOARD_PATH),
    }


def test_legacy_route_is_preserved_only_in_legacy_router() -> None:
    included_prefixes = {cast(Any, route).original_router.prefix for route in legacy_router.routes}
    assert included_prefixes == {"/health", "/portfolio"}


@pytest.mark.parametrize(
    ("path", "method"),
    [
        (SINGLE_PATH, "get"),
        (PORTFOLIO_PATH, "post"),
        (DASHBOARD_PATH, "post"),
    ],
)
def test_snapshot_routes_have_one_method_and_authentication(
    path: str,
    method: str,
    test_settings: Settings,
) -> None:
    operation = create_app(test_settings).openapi()["paths"][path]
    assert set(operation) == {method}
    assert operation[method]["security"] == [{"InternalSessionToken": []}]


def test_snapshot_routes_reject_missing_authentication(test_settings: Settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        single = client.get(
            "/api/v1/portfolio/accounts/account-a/snapshot",
            params={
                "timestamp": "2032-08-02T00:00:00.000",
                "granularity": "day",
                "currency": "EUR",
                "calculationVersion": 1,
            },
        )
        portfolio = client.post(PORTFOLIO_PATH, json={})
        dashboard = client.post(DASHBOARD_PATH, json={})
    assert [response.status_code for response in (single, portfolio, dashboard)] == [401] * 3


def test_exact_request_models_forbid_extra_fields_and_have_exact_fields() -> None:
    assert set(ExactAccountSnapshotRequest.model_fields) == {"account_id", "snapshot_id"}
    assert set(ExactPortfolioSnapshotSetRequest.model_fields) == {
        "timestamp",
        "granularity",
        "currency",
        "calculation_version",
        "accounts",
    }
    assert ExactAccountSnapshotRequest.model_config["extra"] == "forbid"
    assert ExactPortfolioSnapshotSetRequest.model_config["extra"] == "forbid"
    with pytest.raises(ValueError):
        ExactPortfolioSnapshotSetRequest.model_validate(
            {
                "timestamp": "2032-08-02T00:00:00.000",
                "granularity": "day",
                "currency": "EUR",
                "calculationVersion": 1,
                "accounts": [{"accountId": "account-a"}],
                "extra": True,
            }
        )


@pytest.mark.parametrize(
    "relative",
    [
        "portfolio_snapshot/models.py",
        "portfolio_snapshot/projection.py",
        "portfolio_snapshot/aggregate_models.py",
        "portfolio_snapshot/aggregation.py",
        "dashboard_snapshot/models.py",
        "dashboard_snapshot/projection.py",
    ],
)
def test_pure_dependencies_exclude_framework_database_and_auth(relative: str) -> None:
    path = MODULES / relative
    modules, names = _imports(path)
    forbidden_modules = {"sqlalchemy", "fastapi", "pydantic"}
    forbidden_names = {
        "AsyncSession",
        "AuthenticatedPrincipal",
        "require_account_access",
        "AccountModel",
        "AccountMemberModel",
        "AccountSnapshotModel",
        "AccountSnapshotItemModel",
        "HoldingModel",
        "PriceSnapshotModel",
        "ExchangeRateModel",
    }
    assert all(not module.startswith(tuple(forbidden_modules)) for module in modules)
    assert forbidden_names.isdisjoint(names)


def test_persisted_reader_imports_only_allowed_orm_models() -> None:
    imported_models: set[str] = set()
    for filename in ("repository.py", "reader.py"):
        _, names = _imports(MODULES / "portfolio_snapshot" / filename)
        imported_models.update(name for name in names if name.endswith("Model"))
    assert imported_models == {
        "AccountModel",
        "AccountSnapshotModel",
        "AccountSnapshotItemModel",
        "AssetListingModel",
        "AssetModel",
    }


def test_persisted_reader_owns_no_transaction_write_or_lock() -> None:
    paths = (
        MODULES / "portfolio_snapshot" / "repository.py",
        MODULES / "portfolio_snapshot" / "reader.py",
    )
    calls = set().union(*(_session_call_names(path) for path in paths))
    source = "\n".join(path.read_text(encoding="utf-8").lower() for path in paths)
    assert {"begin", "commit", "rollback", "add", "delete", "update"}.isdisjoint(calls)
    assert "set transaction isolation level" not in source
    assert "for update" not in source
    assert "advisory" not in source


def test_shared_authorized_reader_has_exact_caller_transaction_boundary() -> None:
    path = MODULES / "portfolio_snapshot" / "authorized_reader.py"
    source = path.read_text(encoding="utf-8")
    calls = _call_names(path)
    assert {"begin", "commit", "rollback", "execute"}.isdisjoint(calls)
    assert source.count("await self.access_checker(") == 1
    assert source.count("await self.reader_factory(self.session).read(") == 1
    assert "include_archived=False" in source
    assert "for_update=False" in source
    for role in ("owner", "admin", "editor", "viewer"):
        assert f"AccountMemberRole.{role}" in source
    assert source.count("self.session.in_transaction() is not True") == 2


def test_only_transaction_owners_set_repeatable_read() -> None:
    owners = {
        MODULES / "portfolio_snapshot" / "authorized_service.py",
        MODULES / "portfolio_snapshot" / "multi_account_service.py",
    }
    discovered = {
        path
        for module in ("portfolio_snapshot", "dashboard_snapshot")
        for path in (MODULES / module).glob("*.py")
        if "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" in path.read_text(encoding="utf-8")
    }
    assert discovered == owners


@pytest.mark.parametrize(
    ("relative", "next_call"),
    [
        ("portfolio_snapshot/authorized_service.py", "self._authorized_reader().read"),
        ("portfolio_snapshot/multi_account_service.py", "self.authorized_reader_factory"),
    ],
)
def test_transaction_owner_sets_isolation_before_financial_work(
    relative: str,
    next_call: str,
) -> None:
    source = (MODULES / relative).read_text(encoding="utf-8")
    begin = source.index("async with self.session.begin():")
    isolation = source.index(
        'await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))',
        begin,
    )
    financial = source.index(next_call, isolation)
    assert begin < isolation < financial
    assert "await " not in source[begin:isolation].replace("await self.session", "")


def test_dashboard_service_owns_no_database_or_transaction() -> None:
    path = MODULES / "dashboard_snapshot" / "authorized_service.py"
    modules, names = _imports(path)
    calls = _call_names(path)
    assert all(not module.startswith("sqlalchemy") for module in modules)
    assert "AsyncSession" not in names
    assert {"begin", "commit", "rollback", "execute"}.isdisjoint(calls)


@pytest.mark.parametrize(
    "relative",
    [
        "portfolio_snapshot/api.py",
        "portfolio_snapshot/multi_account_api.py",
        "dashboard_snapshot/api.py",
    ],
)
def test_api_adapters_are_thin(relative: str) -> None:
    path = MODULES / relative
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules, names = _imports(path)
    assert {
        "PortfolioSnapshotReader",
        "require_account_access",
        "build_portfolio_snapshot_view",
        "build_multi_account_portfolio_view",
        "build_dashboard_snapshot_view",
        "HoldingModel",
        "PriceSnapshotModel",
        "ExchangeRateModel",
        "Decimal",
    }.isdisjoint(names)
    assert all(not module.endswith(".repository") for module in modules)
    assert not any(
        isinstance(child, ast.BinOp)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for statement in node.body
        for child in ast.walk(statement)
    )
    assert {"execute", "scalar", "scalars", "commit", "rollback", "begin"}.isdisjoint(
        _call_names(path)
    )


@pytest.mark.parametrize(
    "model",
    [
        PortfolioSnapshotItemSource,
        PortfolioSnapshotSource,
        PortfolioAccountView,
        PortfolioSummaryView,
        PortfolioPositionView,
        PortfolioSnapshotView,
        MultiAccountPortfolioSummary,
        MultiAccountPortfolioAccountView,
        MultiAccountPortfolioView,
        DashboardSnapshotSummary,
        DashboardAccountCard,
        DashboardAssetTypeAllocation,
        DashboardTopPosition,
        DashboardSnapshotView,
        ReadExactPortfolioSnapshotCommand,
        CompletePortfolioSnapshotRead,
        ExactAccountSnapshotSelection,
        ReadAuthorizedMultiAccountPortfolioSnapshotCommand,
        ReadAuthorizedMultiAccountPortfolioSnapshotResult,
    ],
)
def test_pure_and_application_contracts_are_frozen_and_slotted(
    model: type[object],
) -> None:
    _assert_frozen_dataclass(model)


@pytest.mark.parametrize(
    "account_type",
    [AccountType.broker, AccountType.exchange, AccountType.crypto_wallet],
)
def test_supported_investment_account_shapes(account_type: AccountType) -> None:
    view = build_portfolio_snapshot_view(
        _source(f"supported-{account_type.value}", account_type=account_type)
    )
    assert len(view.positions) == 1
    assert view.summary.liabilities_value == 0


@pytest.mark.parametrize(
    "account_type",
    [AccountType.credit_card, AccountType.loan, AccountType.mortgage],
)
def test_supported_liability_account_shapes(account_type: AccountType) -> None:
    view = build_portfolio_snapshot_view(
        _liability_source(f"supported-{account_type.value}", account_type)
    )
    assert view.positions == ()
    assert view.summary.liabilities_value == Decimal("25.000000")
    assert view.summary.total_value == Decimal("-25.000000")


@pytest.mark.parametrize(
    "account_type",
    [AccountType.bank, AccountType.cash, AccountType.savings],
)
def test_unsupported_account_shapes_fail_closed(account_type: AccountType) -> None:
    with pytest.raises(PortfolioSnapshotProjectionError):
        build_portfolio_snapshot_view(
            _source(f"unsupported-{account_type.value}", account_type=account_type)
        )


def test_liability_positions_fail_closed() -> None:
    with pytest.raises(PortfolioSnapshotProjectionError):
        build_portfolio_snapshot_view(_source("liability-position", account_type=AccountType.loan))


def test_empty_investment_produces_empty_dashboard_breakdowns() -> None:
    view = build_portfolio_snapshot_view(_empty_source("empty"))
    dashboard = build_dashboard_snapshot_view(build_multi_account_portfolio_view((view,)))
    assert dashboard.asset_type_allocations == ()
    assert dashboard.top_positions == ()


def test_single_and_multi_account_contributions_are_identical() -> None:
    views = _views()
    multi = build_multi_account_portfolio_view(tuple(reversed(views)))
    by_id = {account.account.account_id: account for account in multi.accounts}
    for view in views:
        account = by_id[view.account.account_id]
        assert account.snapshot_id == view.snapshot_id
        assert account.account == view.account
        assert account.source == view.source
        assert account.summary == view.summary
        assert account.positions == view.positions
        assert (
            multi.timestamp,
            multi.granularity,
            multi.currency,
            multi.calculation_version,
        ) == (
            view.timestamp,
            view.granularity,
            view.currency,
            view.calculation_version,
        )


def test_multi_summary_is_the_exact_sum_of_single_summaries() -> None:
    views = _views()
    multi = build_multi_account_portfolio_view(views)
    for name in (
        "cash_value",
        "investment_value",
        "investment_cost_basis",
        "liabilities_value",
        "total_value",
        "net_deposits_value",
        "realized_pnl_value",
        "unrealized_pnl_value",
        "fees_value",
        "taxes_value",
    ):
        assert getattr(multi.summary, name) == sum(
            (getattr(view.summary, name) for view in views),
            Decimal(0),
        )


def test_dashboard_summary_is_exactly_consistent_with_portfolio() -> None:
    portfolio = build_multi_account_portfolio_view(_views())
    dashboard = build_dashboard_snapshot_view(portfolio)
    assert dashboard.summary.total_value == portfolio.summary.total_value
    assert dashboard.summary.assets_value == (
        portfolio.summary.cash_value + portfolio.summary.investment_value
    )
    assert dashboard.summary.liabilities_value == portfolio.summary.liabilities_value
    assert dashboard.summary.investment_value == portfolio.summary.investment_value
    assert dashboard.summary.investment_cost_basis == portfolio.summary.investment_cost_basis
    assert dashboard.summary.unrealized_pnl_value == portfolio.summary.unrealized_pnl_value
    assert dashboard.summary.account_count == portfolio.summary.account_count
    assert dashboard.summary.position_count == portfolio.summary.position_count


def test_account_local_and_dashboard_global_allocations_are_distinct() -> None:
    portfolio = build_multi_account_portfolio_view(_views())
    dashboard = build_dashboard_snapshot_view(portfolio)
    assert [account.positions[0].allocation_pct for account in portfolio.accounts] == [
        Decimal("100.0000"),
        Decimal("100.0000"),
    ]
    assert [position.allocation_pct for position in dashboard.top_positions] == [
        Decimal("60"),
        Decimal("40"),
    ]


def test_input_permutations_are_deterministic_and_positions_remain_account_scoped() -> None:
    views = _views()
    first = build_multi_account_portfolio_view(views)
    second = build_multi_account_portfolio_view(tuple(reversed(views)))
    assert first == second
    assert build_dashboard_snapshot_view(first) == build_dashboard_snapshot_view(second)
    assert len(first.accounts) == 2
    assert sum(len(account.positions) for account in first.accounts) == 2


def test_public_response_models_have_exact_field_sets() -> None:
    assert set(PortfolioSnapshotResponse.model_fields) == {
        "snapshot_id",
        "account",
        "timestamp",
        "granularity",
        "currency",
        "source",
        "calculation_version",
        "summary",
        "positions",
    }
    assert set(MultiAccountPortfolioResponse.model_fields) == {
        "timestamp",
        "granularity",
        "currency",
        "calculation_version",
        "summary",
        "accounts",
    }
    assert set(DashboardSnapshotResponse.model_fields) == {
        "timestamp",
        "granularity",
        "currency",
        "calculation_version",
        "summary",
        "accounts",
        "asset_type_allocations",
        "top_positions",
    }
    assert set(DashboardTopPositionResponse.model_fields) == {
        "account_id",
        "listing_id",
        "asset_id",
        "symbol",
        "name",
        "asset_type",
        "value",
        "value_currency",
        "unrealized_pnl",
        "allocation_pct",
    }


@pytest.mark.parametrize(
    "model",
    [
        PortfolioSnapshotSummaryResponse,
        PortfolioSnapshotPositionResponse,
        MultiAccountPortfolioSummaryResponse,
        DashboardSnapshotSummaryResponse,
        DashboardAccountCardResponse,
        DashboardAssetTypeAllocationResponse,
        DashboardTopPositionResponse,
    ],
)
def test_every_decimal_response_field_has_an_explicit_serializer(
    model: type[BaseModel],
) -> None:
    decimal_fields = {
        name for name, field in model.model_fields.items() if field.annotation is Decimal
    }
    serialized_fields = {
        field
        for decorator in model.__pydantic_decorators__.field_serializers.values()
        for field in decorator.info.fields
    }
    assert decimal_fields
    assert decimal_fields <= serialized_fields


@pytest.mark.parametrize(
    "model",
    [
        PortfolioSnapshotResponse,
        PortfolioSnapshotPositionResponse,
        MultiAccountPortfolioResponse,
        DashboardSnapshotResponse,
    ],
)
def test_every_public_timestamp_has_an_explicit_serializer(
    model: type[BaseModel],
) -> None:
    timestamp_fields = {
        name for name, field in model.model_fields.items() if field.annotation is datetime
    }
    serialized_fields = {
        field
        for decorator in model.__pydantic_decorators__.field_serializers.values()
        for field in decorator.info.fields
    }
    assert timestamp_fields
    assert timestamp_fields <= serialized_fields


def test_public_json_uses_decimal_strings_milliseconds_and_no_leakage() -> None:
    single, multi, dashboard = _serialized_views()
    _audit_json(single)
    _audit_json(multi)
    _audit_json(dashboard, dashboard=True)
    assert single["timestamp"] == multi["timestamp"] == dashboard["timestamp"]
    assert single["timestamp"].endswith(".000")
    assert single["positions"][0]["priceTimestamp"].endswith(".123")
    assert "+" not in single["timestamp"] and not single["timestamp"].endswith("Z")


def test_public_nested_response_shapes_are_exact() -> None:
    assert set(PortfolioCurrencyAmountResponse.model_fields) == {
        "currency",
        "amount",
    }
    assert set(PortfolioSnapshotAccountResponse.model_fields) == {
        "account_id",
        "name",
        "account_type",
        "currency",
    }
    assert set(PortfolioSnapshotSummaryResponse.model_fields) == {
        "cash_value",
        "cash_by_currency",
        "investment_value",
        "investment_cost_basis",
        "liabilities_value",
        "total_value",
        "net_deposits_value",
        "net_deposits_by_currency",
        "realized_pnl_value",
        "unrealized_pnl_value",
        "fees_value",
        "taxes_value",
        "position_count",
    }
    assert set(MultiAccountPortfolioAccountResponse.model_fields) == {
        "snapshot_id",
        "account",
        "source",
        "summary",
        "positions",
    }
    assert set(MultiAccountPortfolioSummaryResponse.model_fields) == {
        "cash_value",
        "cash_by_currency",
        "investment_value",
        "investment_cost_basis",
        "liabilities_value",
        "total_value",
        "net_deposits_value",
        "net_deposits_by_currency",
        "realized_pnl_value",
        "unrealized_pnl_value",
        "fees_value",
        "taxes_value",
        "account_count",
        "position_count",
    }
    assert set(DashboardAssetTypeAllocationResponse.model_fields) == {
        "asset_type",
        "value",
        "allocation_pct",
        "position_count",
        "account_count",
    }


def test_stable_generic_error_contracts() -> None:
    access = PortfolioSnapshotUnavailableError()
    projection = PortfolioSnapshotProjectionError()
    assert (access.status_code, access.code, access.message) == (
        409,
        "portfolio_snapshot_unavailable",
        "The requested portfolio snapshot is unavailable.",
    )
    assert str(projection) == "Portfolio snapshot evidence cannot produce a complete view."


def test_no_latest_fallback_live_finance_or_implicit_discovery_dependencies() -> None:
    paths = (
        MODULES / "portfolio_snapshot" / "reader.py",
        MODULES / "portfolio_snapshot" / "authorized_reader.py",
        MODULES / "portfolio_snapshot" / "authorized_service.py",
        MODULES / "portfolio_snapshot" / "multi_account_service.py",
        MODULES / "dashboard_snapshot" / "authorized_service.py",
    )
    source = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for forbidden in (
        "HoldingModel",
        "PriceSnapshotModel",
        "ExchangeRateModel",
        "datetime.now",
        "uuid4",
        "float(",
        "round(",
        "ORDER BY timestamp DESC",
        "AccountMemberModel",
    ):
        assert forbidden not in source
    assert "latest" not in source.lower()
    assert "fallback" not in source.lower()


def test_audit_report_exists_with_every_required_section() -> None:
    report = AUDIT_REPORT.read_text(encoding="utf-8")
    required = {
        "Audit base SHA",
        "Audit HEAD SHA",
        "Production files changed",
        "Route inventory",
        "Dependency-boundary result",
        "Pure-boundary result",
        "Persisted-reader result",
        "Authorization result",
        "Transaction result",
        "PostgreSQL coherence result",
        "Read-only SQL result",
        "Cross-endpoint consistency result",
        "Decimal serialization result",
        "Leakage result",
        "Failure-contract result",
        "Determinism result",
        "Unit test result",
        "PostgreSQL test result",
        "Full backend result",
        "Frontend result",
        "Coverage",
        "Schema/migration result",
        "Known external risks",
        "Final verdict",
    }
    headings = {
        line.removeprefix("## ").strip() for line in report.splitlines() if line.startswith("## ")
    }
    assert required <= headings
    assert "Production files changed\n\nNone." in report
    assert "\nPASS\n" in report or "\nNOT READY\n" in report


def test_frozen_view_rejects_mutation() -> None:
    view = _views()[0]
    with pytest.raises((FrozenInstanceError, AttributeError)):
        cast(Any, view).currency = "USD"
    assert tuple(field.name for field in fields(view))[-1] == "positions"
