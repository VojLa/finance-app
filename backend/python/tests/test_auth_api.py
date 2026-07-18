from fastapi.testclient import TestClient

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.main import create_app


def test_auth_me_requires_bearer_token(test_settings: Settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_auth_me_returns_database_backed_principal(test_settings: Settings) -> None:
    app = create_app(test_settings)
    app.dependency_overrides[get_current_principal] = lambda: AuthenticatedPrincipal(
        user_id="user-1",
        email="user@example.com",
        name="Test User",
        session_id="session-1",
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.json() == {
        "id": "user-1",
        "email": "user@example.com",
        "name": "Test User",
    }


def test_openapi_declares_bearer_security(test_settings: Settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        schema = client.get("/openapi.json").json()

    operation = schema["paths"]["/api/v1/auth/me"]["get"]
    security_schemes = schema["components"]["securitySchemes"]
    assert operation["security"] == [{"InternalSessionToken": []}]
    assert security_schemes["InternalSessionToken"]["scheme"] == "bearer"
