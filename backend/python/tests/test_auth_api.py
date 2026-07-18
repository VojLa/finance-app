import base64
import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.main import create_app


def _encode(value: object) -> str:
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _token(secret: str, *, subject: str = "user-1", expires_at: int | None = None) -> str:
    now = int(time.time())
    header = _encode({"alg": "HS256", "typ": "JWT"})
    payload = _encode(
        {
            "sub": subject,
            "iss": "finance-app-next",
            "aud": "finance-app-python",
            "iat": now - 10,
            "exp": expires_at if expires_at is not None else now + 300,
        }
    )
    signature = hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{header}.{payload}.{encoded_signature}"


def test_auth_me_requires_bearer_token(test_settings: Settings) -> None:
    app = create_app(test_settings)
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = AssertionError("database dependency must not run")

    async def fail_if_database_is_opened() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = fail_if_database_is_opened
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    session.scalar.assert_not_awaited()


def test_invalid_token_is_rejected_before_database_access(test_settings: Settings) -> None:
    app = create_app(test_settings)
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = AssertionError("database dependency must not run")

    async def fail_if_database_is_opened() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = fail_if_database_is_opened
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session_token"
    session.scalar.assert_not_awaited()


def test_expired_token_is_rejected_before_database_access(test_settings: Settings) -> None:
    assert test_settings.internal_auth_secret is not None
    app = create_app(test_settings)
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = AssertionError("database dependency must not run")

    async def fail_if_database_is_opened() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = fail_if_database_is_opened
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {_token(test_settings.internal_auth_secret, expires_at=0)}"
            },
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "expired_session_token"
    session.scalar.assert_not_awaited()


def test_unknown_token_subject_is_rejected(test_settings: Settings) -> None:
    assert test_settings.internal_auth_secret is not None
    app = create_app(test_settings)
    session = AsyncMock(spec=AsyncSession)
    session.scalar.return_value = None

    async def missing_user_session() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_db_session] = missing_user_session
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/auth/me",
            headers={
                "Authorization": f"Bearer {_token(test_settings.internal_auth_secret, subject='missing-user')}"
            },
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session_token"
    session.scalar.assert_awaited_once()


def test_missing_auth_configuration_returns_controlled_error() -> None:
    settings = Settings(environment="test", internal_auth_secret=None, _env_file=None)

    with TestClient(create_app(settings)) as client:
        response = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer configured-later"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "authentication_unavailable"


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
    assert security_schemes["InternalSessionToken"]["bearerFormat"] == "JWT"
    assert "security" not in schema["paths"]["/api/v1/health/live"]["get"]
    assert "security" not in schema["paths"]["/api/v1/health/ready"]["get"]
