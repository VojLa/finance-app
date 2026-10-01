from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
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
from app.modules.portfolio_history.api_models import PortfolioHistoryResponse
from app.modules.portfolio_history.lattice import (
    HistoryPublicRange,
    HistoryResolution,
    resolution_minutes,
)
from app.modules.portfolio_snapshot.history_contracts import (
    PortfolioHistoryReadState,
)
from app.modules.portfolio_snapshot.history_contracts import (
    PortfolioSnapshotHistoryUnavailableError as GenerationPortfolioHistoryUnavailableError,
)
from app.modules.portfolio_snapshot.history_reader import (
    PublishedPortfolioSnapshotHistoryReader,
)

PATH = "/api/v1/portfolio/history"
AT = datetime(2026, 8, 1, 0, 0, 0, 123000)


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-a",
        email="user-a@example.test",
        name="User A",
    )


def _preferred(history_range: HistoryPublicRange) -> int:
    resolution = {
        HistoryPublicRange.one_day: HistoryResolution.minutes_30,
        HistoryPublicRange.one_week: HistoryResolution.hours_2,
        HistoryPublicRange.one_month: HistoryResolution.hours_6,
        HistoryPublicRange.three_months: HistoryResolution.hours_12,
        HistoryPublicRange.six_months: HistoryResolution.day_1,
        HistoryPublicRange.one_year: HistoryResolution.day_1,
        HistoryPublicRange.five_years: HistoryResolution.days_4,
        HistoryPublicRange.ten_years: HistoryResolution.days_8,
        HistoryPublicRange.all: HistoryResolution.days_8,
    }[history_range]
    return resolution_minutes(resolution)


def _result(
    *,
    history_range: HistoryPublicRange = HistoryPublicRange.one_year,
    state: PortfolioHistoryReadState = PortfolioHistoryReadState.ready,
    published: bool = True,
    actual_resolution: int | None = None,
) -> SimpleNamespace:
    preferred = _preferred(history_range)
    actual = actual_resolution or preferred
    return SimpleNamespace(
        history=SimpleNamespace(
            range=history_range,
            state=state,
            currency="EUR",
            generation_id="generation-a" if published else None,
            publication_version=7 if published else None,
            covered_through=AT if published else None,
            preferred_resolution_minutes=preferred if published else None,
            resolutions=(actual,) if published else (),
            coverage=(
                SimpleNamespace(
                    resolution_minutes=actual,
                    start=AT - timedelta(milliseconds=1),
                    end=AT + timedelta(milliseconds=1),
                ),
            )
            if published
            else (),
            points=(
                SimpleNamespace(
                    timestamp=AT,
                    resolution_minutes=actual,
                    cash_value=Decimal("-50.000000"),
                    investment_value=Decimal("10000.000000"),
                    liabilities_value=Decimal("1000.000000"),
                    net_worth_value=Decimal("8950.000000"),
                ),
            )
            if published
            else (),
        )
    )


def _client(settings: Settings) -> TestClient:
    app = create_app(settings)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = session_override
    app.dependency_overrides[get_current_principal] = _principal
    return TestClient(app)


def test_response_model_serializes_contract_and_requires_one_selected_resolution() -> None:
    response = PortfolioHistoryResponse.model_validate(_result().history, from_attributes=True)
    assert response.model_dump(mode="json", by_alias=True, exclude_none=True) == {
        "range": "1Y",
        "state": "ready",
        "currency": "EUR",
        "generationId": "generation-a",
        "publicationVersion": 7,
        "coveredThrough": "2026-08-01T00:00:00.123",
        "preferredResolutionMinutes": 1440,
        "resolutions": [1440],
        "coverage": [
            {
                "resolutionMinutes": 1440,
                "start": "2026-08-01T00:00:00.122",
                "end": "2026-08-01T00:00:00.124",
            }
        ],
        "points": [
            {
                "timestamp": "2026-08-01T00:00:00.123",
                "resolutionMinutes": 1440,
                "cashValue": "-50.000000",
                "investmentValue": "10000.000000",
                "liabilitiesValue": "1000.000000",
                "netWorthValue": "8950.000000",
            }
        ],
    }
    with pytest.raises(ValidationError):
        PortfolioHistoryResponse.model_validate(
            _result(
                history_range=HistoryPublicRange.three_months,
                actual_resolution=1440,
            ).history,
            from_attributes=True,
        )
    with pytest.raises(ValidationError):
        PortfolioHistoryResponse.model_validate(
            {**response.model_dump(), "snapshotId": "forbidden"}
        )
    with pytest.raises(ValidationError):
        PortfolioHistoryResponse.model_validate({**response.model_dump(), "points": []})


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
                "$ref": "#/components/schemas/HistoryPublicRange",
                "default": "1Y",
            },
        },
        {
            "name": "accountId",
            "in": "query",
            "required": False,
            "schema": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "title": "Accountid",
            },
        },
    ]
    assert app.openapi()["components"]["schemas"]["HistoryPublicRange"]["enum"] == [
        "1D",
        "1W",
        "1M",
        "3M",
        "6M",
        "1Y",
        "5Y",
        "10Y",
        "ALL",
    ]
    with TestClient(app) as client:
        assert client.get(PATH).status_code == 401


@pytest.mark.parametrize("expected_range", tuple(HistoryPublicRange))
def test_adapter_maps_principal_and_all_public_ranges(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    expected_range: HistoryPublicRange,
) -> None:
    read = AsyncMock(
        return_value=PortfolioHistoryResponse.model_validate(
            _result(history_range=expected_range).history, from_attributes=True
        )
    )
    monkeypatch.setattr(PublishedPortfolioSnapshotHistoryReader, "read", read)
    query = (
        "" if expected_range is HistoryPublicRange.one_year else f"?range={expected_range.value}"
    )
    with _client(test_settings) as client:
        response = client.get(f"{PATH}{query}")
    assert response.status_code == 200
    assert response.json()["range"] == expected_range.value
    assert read.await_args is not None
    assert read.await_args.kwargs == {
        "principal": _principal(),
        "history_range": expected_range,
        "account_id": None,
    }


def test_adapter_passes_optional_selected_account_id(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read = AsyncMock(
        return_value=PortfolioHistoryResponse.model_validate(
            _result().history, from_attributes=True
        )
    )
    monkeypatch.setattr(PublishedPortfolioSnapshotHistoryReader, "read", read)
    with _client(test_settings) as client:
        response = client.get(f"{PATH}?accountId=account-a")
    assert response.status_code == 200
    assert read.await_args is not None
    assert read.await_args.kwargs == {
        "principal": _principal(),
        "history_range": HistoryPublicRange.one_year,
        "account_id": "account-a",
    }


def test_exact_json_has_no_internal_lineage(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        PublishedPortfolioSnapshotHistoryReader,
        "read",
        AsyncMock(
            return_value=PortfolioHistoryResponse.model_validate(
                _result().history, from_attributes=True
            )
        ),
    )
    with _client(test_settings) as client:
        response = client.get(PATH)
    assert response.status_code == 200
    assert response.json() == PortfolioHistoryResponse.model_validate(
        _result().history, from_attributes=True
    ).model_dump(mode="json", by_alias=True, exclude_none=True)
    for forbidden in ("userId", "snapshotId", "accountId", "provider", "source"):
        assert forbidden not in response.text


@pytest.mark.parametrize(
    "state",
    [
        PortfolioHistoryReadState.empty,
        PortfolioHistoryReadState.rebuilding,
        PortfolioHistoryReadState.failed,
    ],
)
def test_unpublished_states_omit_generation_metadata(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    state: PortfolioHistoryReadState,
) -> None:
    monkeypatch.setattr(
        PublishedPortfolioSnapshotHistoryReader,
        "read",
        AsyncMock(
            return_value=PortfolioHistoryResponse.model_validate(
                _result(state=state, published=False).history, from_attributes=True
            )
        ),
    )
    with _client(test_settings) as client:
        response = client.get(PATH)
    assert response.status_code == 200
    assert response.json() == {
        "range": "1Y",
        "state": state.value,
        "currency": "EUR",
        "resolutions": [],
        "coverage": [],
        "points": [],
    }


def test_invalid_range_and_unavailable_are_public_safe(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _client(test_settings) as client:
        invalid = client.get(f"{PATH}?range=YEAR")
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"

    monkeypatch.setattr(
        PublishedPortfolioSnapshotHistoryReader,
        "read",
        AsyncMock(side_effect=GenerationPortfolioHistoryUnavailableError()),
    )
    with _client(test_settings) as client:
        unavailable = client.get(PATH)
    assert unavailable.status_code == 409
    assert unavailable.json()["error"]["code"] == "portfolio_history_unavailable"
    assert unavailable.json()["error"]["message"] == "Portfolio history is unavailable."
