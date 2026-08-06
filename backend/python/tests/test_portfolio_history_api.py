from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from decimal import Decimal
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
from app.modules.portfolio_history.api_models import PortfolioHistoryPointResponse
from app.modules.portfolio_history.models import (
    PortfolioHistoryPoint,
    PortfolioHistoryRange,
    PortfolioHistoryView,
)
from app.modules.portfolio_history.service import (
    PortfolioHistoryUnavailableError,
    ReadPortfolioHistoryResult,
    SnapshotBackedPortfolioHistoryService,
)

PATH = "/api/v1/portfolio/history"
AT = datetime(2026, 8, 1, 0, 0, 0, 123000)


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-a",
        email="user-a@example.test",
        name="User A",
    )


def _result(
    *, points: tuple[PortfolioHistoryPoint, ...] | None = None
) -> ReadPortfolioHistoryResult:
    history_points = (
        (
            PortfolioHistoryPoint(
                timestamp=AT,
                cash_value=Decimal("-50.000000"),
                investment_value=Decimal("10000.000000"),
                liabilities_value=Decimal("1000.000000"),
                net_worth_value=Decimal("8950.000000"),
            ),
        )
        if points is None
        else points
    )
    return ReadPortfolioHistoryResult(
        history=PortfolioHistoryView(
            range=PortfolioHistoryRange.one_year,
            currency="EUR",
            points=history_points,
        ),
        selected_snapshot_ids=tuple(f"internal-{index}" for index in range(len(history_points))),
    )


def _client(settings: Settings) -> TestClient:
    app = create_app(settings)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = session_override
    app.dependency_overrides[get_current_principal] = _principal
    return TestClient(app)


def test_response_model_forbids_extra_and_serializes_exact_values() -> None:
    response = PortfolioHistoryPointResponse.model_validate(
        _result().history.points[0],
        from_attributes=True,
    )
    assert response.model_dump(mode="json", by_alias=True) == {
        "timestamp": "2026-08-01T00:00:00.123",
        "cashValue": "-50.000000",
        "investmentValue": "10000.000000",
        "liabilitiesValue": "1000.000000",
        "netWorthValue": "8950.000000",
    }
    with pytest.raises(ValidationError):
        PortfolioHistoryPointResponse.model_validate(
            {
                "timestamp": AT,
                "cashValue": "0.000000",
                "investmentValue": "0.000000",
                "liabilitiesValue": "0.000000",
                "netWorthValue": "0.000000",
                "snapshotId": "forbidden",
            }
        )


def test_endpoint_contract_auth_and_default_range(test_settings: Settings) -> None:
    app = create_app(test_settings)
    operation = app.openapi()["paths"][PATH]["get"]
    assert operation["tags"] == ["portfolio-history"]
    assert operation["security"] == [{"InternalSessionToken": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PortfolioHistoryResponse"
    }
    assert operation["parameters"] == [
        {
            "name": "range",
            "in": "query",
            "required": False,
            "schema": {
                "$ref": "#/components/schemas/PortfolioHistoryRange",
                "default": "1Y",
            },
        }
    ]
    with TestClient(app) as client:
        response = client.get(PATH)
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("query", "expected_range"),
    [
        ("", PortfolioHistoryRange.one_year),
        ("?range=1W", PortfolioHistoryRange.one_week),
        ("?range=1M", PortfolioHistoryRange.one_month),
        ("?range=3M", PortfolioHistoryRange.three_months),
        ("?range=6M", PortfolioHistoryRange.six_months),
        ("?range=1Y", PortfolioHistoryRange.one_year),
        ("?range=ALL", PortfolioHistoryRange.all),
    ],
)
def test_adapter_maps_exact_principal_and_range(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    query: str,
    expected_range: PortfolioHistoryRange,
) -> None:
    read = AsyncMock(return_value=_result())
    monkeypatch.setattr(SnapshotBackedPortfolioHistoryService, "read", read)
    client = _client(test_settings)
    with client:
        response = client.get(f"{PATH}{query}")
    assert response.status_code == 200
    assert read.await_args is not None
    command = read.await_args.args[0]
    assert command.principal == _principal()
    assert command.range is expected_range


def test_exact_public_json_has_no_internal_lineage(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SnapshotBackedPortfolioHistoryService,
        "read",
        AsyncMock(return_value=_result()),
    )
    client = _client(test_settings)
    with client:
        response = client.get(PATH)
    assert response.json() == {
        "range": "1Y",
        "currency": "EUR",
        "points": [
            {
                "timestamp": "2026-08-01T00:00:00.123",
                "cashValue": "-50.000000",
                "investmentValue": "10000.000000",
                "liabilitiesValue": "1000.000000",
                "netWorthValue": "8950.000000",
            }
        ],
    }
    serialized = response.text
    for forbidden in (
        "userId",
        "snapshotId",
        "accountId",
        "selectedAccountSnapshotIds",
        "exchangeRates",
        "provider",
        "source",
        "calculationVersion",
        "createdAt",
        "calculatedAt",
    ):
        assert forbidden not in serialized


def test_empty_history_is_200(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SnapshotBackedPortfolioHistoryService,
        "read",
        AsyncMock(return_value=_result(points=())),
    )
    client = _client(test_settings)
    with client:
        response = client.get(PATH)
    assert response.status_code == 200
    assert response.json() == {"range": "1Y", "currency": "EUR", "points": []}


def test_invalid_range_uses_safe_validation_error(test_settings: Settings) -> None:
    client = _client(test_settings)
    with client:
        response = client.get(f"{PATH}?range=YEAR")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_dependency_state_error_uses_generic_envelope(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        SnapshotBackedPortfolioHistoryService,
        "read",
        AsyncMock(side_effect=PortfolioHistoryUnavailableError()),
    )
    client = _client(test_settings)
    with client:
        response = client.get(PATH)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "portfolio_history_unavailable"
    assert response.json()["error"]["message"] == "Portfolio history is unavailable."
