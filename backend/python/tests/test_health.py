from fastapi.testclient import TestClient

from app.api.routes import health as health_module
from app.config.settings import Settings
from app.main import create_app


def test_legacy_health_endpoint_remains_available(test_settings: Settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "finance-app-backend"}


def test_liveness_returns_200(test_settings: Settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "finance-app-backend"}


def test_readiness_returns_503_without_database(test_settings: Settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "dependencies": {"database": "unavailable"},
    }


def test_readiness_returns_200_when_database_is_available(
    monkeypatch,
    test_settings: Settings,
) -> None:
    class FakeEngine:
        async def dispose(self) -> None:
            return None

    class FakeDatabase:
        engine = FakeEngine()

    def fake_database(_settings: Settings) -> FakeDatabase:
        return FakeDatabase()

    async def database_is_available(_database: object) -> bool:
        return True

    monkeypatch.setattr("app.lifespan.create_database", fake_database)
    monkeypatch.setattr(health_module, "check_database", database_is_available)

    with TestClient(create_app(test_settings)) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "dependencies": {"database": "available"},
    }
