from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.main import create_app
from app.modules.portfolio.models import PortfolioSummary
from app.modules.portfolio.service import PortfolioService


async def _session_override() -> AsyncIterator[object]:
    yield object()


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="user-a",
        email="user-a@example.com",
        name="User A",
    )


def _summary() -> PortfolioSummary:
    return PortfolioSummary(
        display_currency="CZK",
        total_cost=0,
        accounts=[],
        holdings=[],
    )


def _client(test_settings: Settings) -> tuple[TestClient, object]:
    app = create_app(test_settings)
    session = object()

    async def session_override() -> AsyncIterator[object]:
        yield session

    app.dependency_overrides[get_current_principal] = _principal
    app.dependency_overrides[get_db_session] = session_override
    return TestClient(app), session


def test_portfolio_requires_authentication(test_settings: Settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/api/v1/portfolio")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_portfolio_uses_authenticated_user_scope(
    test_settings: Settings,
    monkeypatch,
) -> None:
    get_portfolio = AsyncMock(return_value=_summary())
    monkeypatch.setattr(PortfolioService, "get_portfolio", get_portfolio)
    client, _ = _client(test_settings)

    with client:
        response = client.get("/api/v1/portfolio")

    assert response.status_code == 200
    get_portfolio.assert_awaited_once_with(user_id="user-a", account_id=None)


def test_portfolio_checks_explicit_account_access(
    test_settings: Settings,
    monkeypatch,
) -> None:
    access_check = AsyncMock()
    get_portfolio = AsyncMock(return_value=_summary())
    monkeypatch.setattr("app.modules.portfolio.api.require_account_access", access_check)
    monkeypatch.setattr(PortfolioService, "get_portfolio", get_portfolio)
    client, session = _client(test_settings)

    with client:
        response = client.get("/api/v1/portfolio?account_id=account-a")

    assert response.status_code == 200
    access_check.assert_awaited_once()
    call = access_check.await_args.kwargs
    assert call["session"] is session
    assert call["principal"].user_id == "user-a"
    assert call["account_id"] == "account-a"
    get_portfolio.assert_awaited_once_with(user_id="user-a", account_id="account-a")


def test_portfolio_openapi_has_no_user_id_parameter(test_settings: Settings) -> None:
    schema = create_app(test_settings).openapi()
    operation = schema["paths"]["/api/v1/portfolio"]["get"]
    parameter_names = {parameter["name"] for parameter in operation.get("parameters", [])}

    assert "user_id" not in parameter_names
    assert "account_id" in parameter_names
    assert operation["security"] == [{"InternalSessionToken": []}]
