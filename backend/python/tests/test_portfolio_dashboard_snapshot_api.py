from __future__ import annotations

import ast
from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.router import legacy_router
from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.main import create_app
from app.modules.dashboard_snapshot.api import router as dashboard_snapshot_router
from app.modules.dashboard_snapshot.authorized_service import (
    AuthorizedDashboardSnapshotService,
    ReadAuthorizedDashboardSnapshotResult,
)
from app.modules.dashboard_snapshot.projection import build_dashboard_snapshot_view
from app.modules.portfolio_snapshot.aggregate_models import MultiAccountPortfolioView
from app.modules.portfolio_snapshot.aggregation import build_multi_account_portfolio_view
from app.modules.portfolio_snapshot.models import (
    AccountType,
    AssetType,
    PortfolioAccountView,
    PortfolioPositionView,
    PortfolioSnapshotView,
    PortfolioSummaryView,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.portfolio_snapshot.multi_account_api import (
    router as multi_account_portfolio_snapshot_router,
)
from app.modules.portfolio_snapshot.multi_account_service import (
    AuthorizedMultiAccountPortfolioSnapshotService,
    ExactAccountSnapshotSelection,
    ReadAuthorizedMultiAccountPortfolioSnapshotCommand,
    ReadAuthorizedMultiAccountPortfolioSnapshotResult,
)

SNAPSHOT_AT = datetime(2032, 8, 2)
PRICE_AT = datetime(2032, 8, 1, 12, 30, 0, 123000)
PORTFOLIO_PATH = "/api/v1/portfolio/snapshot"
DASHBOARD_PATH = "/api/v1/dashboard/snapshot"
REQUEST = {
    "timestamp": "2032-08-02T00:00:00.000",
    "granularity": "day",
    "currency": "EUR",
    "calculationVersion": 1,
    "accounts": [
        {"accountId": "account-a", "snapshotId": "account-a-snapshot"},
        {"accountId": "account-b"},
    ],
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
    "netDepositsByCurrency",
    "realizedPnlByCurrency",
    "unrealizedPnlByCurrency",
    "feesByCurrency",
    "taxesByCurrency",
    "calculatedAt",
    "createdAt",
    "updatedAt",
    "passwordHash",
}


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="user-1", email="user@example.com", name="User")


def _view(account_id: str, value: str, cost: str) -> PortfolioSnapshotView:
    money_value = Decimal(value).quantize(Decimal("0.000001"))
    money_cost = Decimal(cost).quantize(Decimal("0.000001"))
    position = PortfolioPositionView(
        listing_id="shared-listing",
        asset_id="shared-asset",
        symbol="AAA",
        name="Asset",
        asset_type=AssetType.stock,
        quantity=Decimal("1.0000000000"),
        price_per_unit=Decimal(value).quantize(Decimal("0.0000000001")),
        price_currency="USD",
        price_timestamp=PRICE_AT,
        value=money_value,
        value_currency="EUR",
        cost_basis=Decimal(cost).quantize(Decimal("0.0000000001")),
        cost_currency="EUR",
        unrealized_pnl=money_value - money_cost,
        allocation_pct=Decimal("100.0000"),
        native_value=Decimal(value).quantize(Decimal("0.0000000001")),
        native_value_currency="USD",
        native_cost_basis=Decimal(cost).quantize(Decimal("0.0000000001")),
        native_cost_currency="USD",
    )
    return PortfolioSnapshotView(
        snapshot_id=f"{account_id}-snapshot",
        account=PortfolioAccountView(
            account_id=account_id,
            name=f"{account_id} name",
            account_type=AccountType.broker,
            currency="CZK" if account_id == "account-a" else "USD",
        ),
        timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        currency="EUR",
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        summary=PortfolioSummaryView(
            cash_value=Decimal("0.000000"),
            investment_value=money_value,
            investment_cost_basis=money_cost,
            liabilities_value=Decimal("0.000000"),
            total_value=money_value,
            net_deposits_value=Decimal("0.000000"),
            realized_pnl_value=Decimal("0.000000"),
            unrealized_pnl_value=money_value - money_cost,
            fees_value=Decimal("0.000000"),
            taxes_value=Decimal("0.000000"),
            position_count=1,
        ),
        positions=(position,),
    )


def _portfolio() -> MultiAccountPortfolioView:
    return build_multi_account_portfolio_view(
        (
            _view("account-a", "60", "50"),
            _view("account-b", "40", "30"),
        )
    )


def _client(settings: Settings) -> tuple[TestClient, AsyncSession]:
    app = create_app(settings)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = session_override
    app.dependency_overrides[get_current_principal] = _principal
    return TestClient(app), session


def _audit_no_leakage(value: object) -> None:
    if isinstance(value, dict):
        assert LEAKED_FIELDS.isdisjoint(value)
        for child in value.values():
            _audit_no_leakage(child)
    elif isinstance(value, list):
        for child in value:
            _audit_no_leakage(child)
    else:
        assert not isinstance(value, float)


def test_both_exact_post_routes_are_registered_and_require_auth(
    test_settings: Settings,
) -> None:
    app = create_app(test_settings)
    paths = app.openapi()["paths"]

    assert set(paths[PORTFOLIO_PATH]) == {"post"}
    assert set(paths[DASHBOARD_PATH]) == {"post"}
    assert paths[PORTFOLIO_PATH]["post"]["security"] == [{"InternalSessionToken": []}]
    assert paths[DASHBOARD_PATH]["post"]["security"] == [{"InternalSessionToken": []}]
    with TestClient(app) as client:
        portfolio = client.post(PORTFOLIO_PATH, json=REQUEST)
        dashboard = client.post(DASHBOARD_PATH, json=REQUEST)
    assert portfolio.status_code == dashboard.status_code == 401
    assert portfolio.json()["error"]["code"] == "authentication_required"
    assert dashboard.json()["error"]["code"] == "authentication_required"


def test_portfolio_adapter_maps_command_once_and_serializes_aliases(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio = _portfolio()
    read = AsyncMock(
        return_value=ReadAuthorizedMultiAccountPortfolioSnapshotResult(portfolio=portfolio)
    )
    monkeypatch.setattr(AuthorizedMultiAccountPortfolioSnapshotService, "read", read)
    client, _ = _client(test_settings)

    response = client.post(PORTFOLIO_PATH, json=REQUEST)

    assert response.status_code == 200
    read.assert_awaited_once()
    assert read.await_args is not None
    command = read.await_args.args[0]
    assert command == ReadAuthorizedMultiAccountPortfolioSnapshotCommand(
        principal=_principal(),
        timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        currency="EUR",
        calculation_version=1,
        accounts=(
            ExactAccountSnapshotSelection("account-a", "account-a-snapshot"),
            ExactAccountSnapshotSelection("account-b"),
        ),
    )
    payload = response.json()
    assert payload["timestamp"] == "2032-08-02T00:00:00.000"
    assert payload["calculationVersion"] == 1
    assert payload["summary"]["investmentValue"] == "100.000000"
    assert payload["summary"]["accountCount"] == 2
    assert payload["accounts"][0]["snapshotId"] == "account-a-snapshot"
    assert payload["accounts"][0]["positions"][0]["allocationPct"] == "100.0000"
    assert payload["accounts"][0]["positions"][0]["priceTimestamp"] == ("2032-08-01T12:30:00.123")
    _audit_no_leakage(payload)


def test_dashboard_adapter_maps_command_once_and_serializes_global_allocations(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    portfolio = _portfolio()
    dashboard = build_dashboard_snapshot_view(portfolio)
    read = AsyncMock(return_value=ReadAuthorizedDashboardSnapshotResult(dashboard=dashboard))
    monkeypatch.setattr(AuthorizedDashboardSnapshotService, "read", read)
    client, _ = _client(test_settings)

    response = client.post(DASHBOARD_PATH, json=REQUEST)

    assert response.status_code == 200
    read.assert_awaited_once()
    assert read.await_args is not None
    assert read.await_args.args[0] == ReadAuthorizedMultiAccountPortfolioSnapshotCommand(
        principal=_principal(),
        timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        currency="EUR",
        calculation_version=1,
        accounts=(
            ExactAccountSnapshotSelection("account-a", "account-a-snapshot"),
            ExactAccountSnapshotSelection("account-b"),
        ),
    )
    payload = response.json()
    assert payload["timestamp"] == "2032-08-02T00:00:00.000"
    assert payload["summary"]["assetsValue"] == "100.000000"
    assert [position["allocationPct"] for position in payload["topPositions"]] == [
        "60.0",
        "40.0",
    ]
    assert payload["assetTypeAllocations"][0]["allocationPct"] == "100"
    assert "priceCurrency" not in payload["topPositions"][0]
    assert "nativeValue" not in payload["topPositions"][0]
    _audit_no_leakage(payload)


@pytest.mark.parametrize(
    "body",
    [
        {**REQUEST, "extra": True},
        {key: value for key, value in REQUEST.items() if key != "timestamp"},
        {key: value for key, value in REQUEST.items() if key != "calculationVersion"},
        {key: value for key, value in REQUEST.items() if key != "accounts"},
        {**REQUEST, "accounts": []},
        {
            **REQUEST,
            "accounts": [{"accountId": "account-a", "unexpected": "value"}],
        },
    ],
)
@pytest.mark.parametrize("path", [PORTFOLIO_PATH, DASHBOARD_PATH])
def test_invalid_request_shape_returns_422(
    path: str,
    body: dict[str, object],
    test_settings: Settings,
) -> None:
    client, _ = _client(test_settings)

    response = client.post(path, json=body)

    assert response.status_code == 422


@pytest.mark.parametrize("path", [PORTFOLIO_PATH, DASHBOARD_PATH])
def test_new_snapshot_paths_are_post_only(path: str, test_settings: Settings) -> None:
    client, _ = _client(test_settings)

    response = client.get(path)

    assert response.status_code == 405


def test_legacy_and_existing_single_account_routes_remain_registered(
    test_settings: Settings,
) -> None:
    app = create_app(test_settings)
    paths = app.openapi()["paths"]
    legacy_includes = tuple(
        cast(object, getattr(route, "original_router", None)) for route in legacy_router.routes
    )

    assert "/api/v1/portfolio" in paths
    assert "/api/v1/portfolio/accounts/{account_id}/snapshot" in paths
    assert PORTFOLIO_PATH in paths
    assert DASHBOARD_PATH in paths
    assert all(router is not multi_account_portfolio_snapshot_router for router in legacy_includes)
    assert all(router is not dashboard_snapshot_router for router in legacy_includes)


def test_openapi_exposes_only_the_two_intended_new_routes(test_settings: Settings) -> None:
    paths = create_app(test_settings).openapi()["paths"]
    snapshot_posts = {
        path for path, methods in paths.items() if path.endswith("/snapshot") and "post" in methods
    }

    assert snapshot_posts == {PORTFOLIO_PATH, DASHBOARD_PATH}


def test_api_adapters_are_thin_and_contain_no_financial_operations() -> None:
    module_root = Path(__file__).parents[1] / "app" / "modules"
    for path in (
        module_root / "portfolio_snapshot" / "multi_account_api.py",
        module_root / "dashboard_snapshot" / "api.py",
    ):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert {
            "HoldingModel",
            "PriceSnapshotModel",
            "ExchangeRateModel",
            "PortfolioSnapshotReader",
            "build_multi_account_portfolio_view",
            "build_dashboard_snapshot_view",
        }.isdisjoint(imports)
        for forbidden in ("float(", "round(", "datetime.now", "latest", "fallback"):
            assert forbidden not in source
