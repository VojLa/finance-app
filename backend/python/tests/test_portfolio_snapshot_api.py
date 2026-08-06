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
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.main import create_app
from app.modules.portfolio_snapshot.api_models import PortfolioCurrencyAmountResponse
from app.modules.portfolio_snapshot.authorized_service import (
    AuthorizedPortfolioSnapshotService,
    ReadAuthorizedPortfolioSnapshotResult,
)
from app.modules.portfolio_snapshot.models import (
    AccountType,
    AssetType,
    PortfolioAccountView,
    PortfolioCurrencyAmount,
    PortfolioPositionView,
    PortfolioSnapshotView,
    PortfolioSummaryView,
    SnapshotGranularity,
    SnapshotSource,
)

SNAPSHOT_AT = datetime(2032, 8, 2)
PRICE_AT = datetime(2032, 8, 1, 12, 30, 0, 123000)
PATH = "/api/v1/portfolio/accounts/account-1/snapshot"
QUERY = {
    "timestamp": "2032-08-02T00:00:00.000",
    "granularity": "day",
    "currency": "EUR",
    "calculationVersion": "1",
}


def test_currency_amount_response_forbids_extra_fields_and_serializes_decimal() -> None:
    response = PortfolioCurrencyAmountResponse(
        currency="EUR",
        amount=Decimal("-1.250000"),
    )

    assert response.model_dump(mode="json", by_alias=True) == {
        "currency": "EUR",
        "amount": "-1.250000",
    }
    with pytest.raises(ValidationError):
        PortfolioCurrencyAmountResponse.model_validate(
            {"currency": "EUR", "amount": "1.000000", "extra": True}
        )


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-1",
        email="user@example.com",
        name="User",
    )


def _view() -> PortfolioSnapshotView:
    position = PortfolioPositionView(
        listing_id="listing-1",
        asset_id="asset-1",
        symbol="AAA",
        name="Asset",
        asset_type=AssetType.stock,
        quantity=Decimal("2.0000000000"),
        price_per_unit=Decimal("50.0000000000"),
        price_currency="USD",
        price_timestamp=PRICE_AT,
        value=Decimal("100.000000"),
        value_currency="EUR",
        cost_basis=Decimal("80.0000000000"),
        cost_currency="EUR",
        unrealized_pnl=Decimal("20.0000000000"),
        allocation_pct=Decimal("100.0000"),
        native_value=Decimal("100.0000000000"),
        native_value_currency="USD",
        native_cost_basis=Decimal("80.0000000000"),
        native_cost_currency="USD",
    )
    return PortfolioSnapshotView(
        snapshot_id="snapshot-1",
        account=PortfolioAccountView(
            account_id="account-1",
            name="Broker",
            account_type=AccountType.broker,
            currency="EUR",
        ),
        timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        currency="EUR",
        source=SnapshotSource.manual_recalculation,
        calculation_version=1,
        summary=PortfolioSummaryView(
            cash_value=Decimal("10.000000"),
            cash_by_currency=(
                PortfolioCurrencyAmount("CZK", Decimal("250.000000")),
                PortfolioCurrencyAmount("EUR", Decimal("10.000000")),
            ),
            investment_value=Decimal("100.000000"),
            investment_cost_basis=Decimal("80.000000"),
            liabilities_value=Decimal("0.000000"),
            total_value=Decimal("110.000000"),
            net_deposits_value=Decimal("0.000000"),
            net_deposits_by_currency=(),
            realized_pnl_value=Decimal("0.000000"),
            unrealized_pnl_value=Decimal("20.000000"),
            fees_value=Decimal("0.000000"),
            taxes_value=Decimal("0.000000"),
            position_count=1,
        ),
        positions=(position,),
    )


def _client(
    settings: Settings,
) -> tuple[TestClient, AsyncSession]:
    app = create_app(settings)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = session_override
    app.dependency_overrides[get_current_principal] = _principal
    return TestClient(app), session


def test_endpoint_contract_is_registered_and_requires_auth(test_settings: Settings) -> None:
    app = create_app(test_settings)
    operation = app.openapi()["paths"]["/api/v1/portfolio/accounts/{account_id}/snapshot"]["get"]

    assert operation["tags"] == ["portfolio-snapshot"]
    assert operation["security"] == [{"InternalSessionToken": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PortfolioSnapshotResponse"
    }
    parameters = {(item["name"], item["in"], item["required"]) for item in operation["parameters"]}
    assert parameters == {
        ("account_id", "path", True),
        ("timestamp", "query", True),
        ("granularity", "query", True),
        ("currency", "query", True),
        ("calculationVersion", "query", True),
        ("snapshotId", "query", False),
    }

    with TestClient(app) as client:
        response = client.get(PATH, params=QUERY)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_thin_adapter_maps_exact_command_and_serializes_public_view(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read = AsyncMock(return_value=ReadAuthorizedPortfolioSnapshotResult(view=_view()))
    monkeypatch.setattr(AuthorizedPortfolioSnapshotService, "read", read)
    client, _ = _client(test_settings)

    with client:
        response = client.get(
            PATH,
            params={**QUERY, "snapshotId": "snapshot-1"},
        )

    assert response.status_code == 200
    assert read.await_args is not None
    command = read.await_args.args[0]
    assert command.principal == _principal()
    assert command.account_id == "account-1"
    assert command.timestamp == SNAPSHOT_AT
    assert command.granularity is SnapshotGranularity.day
    assert command.currency == "EUR"
    assert command.calculation_version == 1
    assert command.required_snapshot_id == "snapshot-1"
    assert response.json() == {
        "snapshotId": "snapshot-1",
        "account": {
            "accountId": "account-1",
            "name": "Broker",
            "accountType": "broker",
            "currency": "EUR",
        },
        "timestamp": "2032-08-02T00:00:00.000",
        "granularity": "day",
        "currency": "EUR",
        "source": "manual_recalculation",
        "calculationVersion": 1,
        "summary": {
            "cashValue": "10.000000",
            "cashByCurrency": [
                {"currency": "CZK", "amount": "250.000000"},
                {"currency": "EUR", "amount": "10.000000"},
            ],
            "investmentValue": "100.000000",
            "investmentCostBasis": "80.000000",
            "liabilitiesValue": "0.000000",
            "totalValue": "110.000000",
            "netDepositsValue": "0.000000",
            "netDepositsByCurrency": [],
            "realizedPnlValue": "0.000000",
            "unrealizedPnlValue": "20.000000",
            "feesValue": "0.000000",
            "taxesValue": "0.000000",
            "positionCount": 1,
        },
        "positions": [
            {
                "listingId": "listing-1",
                "assetId": "asset-1",
                "symbol": "AAA",
                "name": "Asset",
                "assetType": "stock",
                "quantity": "2.0000000000",
                "pricePerUnit": "50.0000000000",
                "priceCurrency": "USD",
                "priceTimestamp": "2032-08-01T12:30:00.123",
                "value": "100.000000",
                "valueCurrency": "EUR",
                "costBasis": "80.0000000000",
                "costCurrency": "EUR",
                "unrealizedPnl": "20.0000000000",
                "allocationPct": "100.0000",
                "nativeValue": "100.0000000000",
                "nativeValueCurrency": "USD",
                "nativeCostBasis": "80.0000000000",
                "nativeCostCurrency": "USD",
            }
        ],
    }


def test_response_has_no_binary_financial_floats_or_internal_evidence(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        AuthorizedPortfolioSnapshotService,
        "read",
        AsyncMock(return_value=ReadAuthorizedPortfolioSnapshotResult(view=_view())),
    )
    client, _ = _client(test_settings)

    with client:
        response = client.get(PATH, params=QUERY)

    payload = response.json()
    forbidden = {
        "userId",
        "membershipId",
        "role",
        "relationType",
        "selectedItemIds",
        "selectedSnapshotId",
        "priceId",
        "priceSource",
        "exchangeRateId",
        "exchangeRates",
        "historicalRateIds",
        "snapshotRates",
        "cashValueByCurrency",
        "investmentValueByCurrency",
        "investmentCostBasisByCurrency",
        "realizedPnlByCurrency",
        "unrealizedPnlByCurrency",
        "feesByCurrency",
        "taxesByCurrency",
        "calculatedAt",
        "createdAt",
    }

    def walk(value: object) -> None:
        if isinstance(value, dict):
            assert forbidden.isdisjoint(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        else:
            assert not isinstance(value, float)

    walk(payload)


@pytest.mark.parametrize(
    "params",
    [
        {},
        {**QUERY, "timestamp": "not-a-timestamp"},
        {**QUERY, "granularity": "latest"},
        {**QUERY, "calculationVersion": "true"},
    ],
)
def test_invalid_query_format_returns_422(
    test_settings: Settings,
    params: dict[str, str],
) -> None:
    client, _ = _client(test_settings)

    with client:
        response = client.get(PATH, params=params)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_legacy_portfolio_route_remains_and_new_route_has_no_legacy_alias(
    test_settings: Settings,
) -> None:
    app = create_app(test_settings)
    schema_paths = set(app.openapi()["paths"])

    assert "/api/v1/portfolio" in schema_paths
    assert "/api/v1/portfolio/accounts/{account_id}/snapshot" in schema_paths
    assert list(schema_paths).count("/api/v1/portfolio/accounts/{account_id}/snapshot") == 1
    with TestClient(app) as client:
        legacy_portfolio = client.get("/portfolio")
        absent_alias = client.get("/portfolio/accounts/account-1/snapshot", params=QUERY)
    assert legacy_portfolio.status_code == 401
    assert absent_alias.status_code == 404


def test_http_adapter_has_no_lower_layer_dependencies_or_sql() -> None:
    source_path = Path(__file__).parents[1] / "app" / "modules" / "portfolio_snapshot" / "api.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    source = source_path.read_text(encoding="utf-8")

    assert {
        "AccountSnapshotModel",
        "AccountSnapshotItemModel",
        "HoldingModel",
        "PriceSnapshotModel",
        "ExchangeRateModel",
        "PortfolioSnapshotRepository",
        "PortfolioSnapshotReader",
        "require_account_access",
        "select",
    }.isdisjoint(imported)
    assert "sqlalchemy.select" not in source
