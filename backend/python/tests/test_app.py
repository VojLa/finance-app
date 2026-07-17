from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app


def test_create_app_returns_fastapi_instance(test_settings: Settings) -> None:
    assert isinstance(create_app(test_settings), FastAPI)


def test_root_returns_service_metadata(test_settings: Settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "finance-app-backend"
    assert payload["version"] == "0.1.0"
    assert "/api/v1/health/live" in payload["endpoints"]


def test_openapi_schema_is_available(test_settings: Settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Finance App Backend"


def test_docs_can_be_disabled(test_settings: Settings) -> None:
    settings = test_settings.model_copy(update={"docs_enabled": False})

    with TestClient(create_app(settings)) as client:
        root_response = client.get("/")
        openapi_response = client.get("/openapi.json")

    assert "/docs" not in root_response.json()["endpoints"]
    assert "/openapi.json" not in root_response.json()["endpoints"]
    assert openapi_response.status_code == 404
