from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.shared.errors import NotFoundError


@pytest.fixture
def error_app(monkeypatch) -> FastAPI:
    async def no_database() -> None:
        return None

    monkeypatch.setattr("app.lifespan.connect_database", no_database)
    app = create_app()

    @app.get("/_test/items/{item_id}")
    def read_item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @app.get("/_test/missing")
    def missing() -> None:
        raise NotFoundError("Account was not found.")

    @app.get("/_test/internal")
    def internal() -> None:
        raise RuntimeError("secret database detail")

    return app


def assert_request_id(response) -> None:
    request_id = response.headers["X-Request-ID"]
    assert str(UUID(request_id)) == request_id
    assert response.json()["error"]["request_id"] == request_id


def test_validation_error_uses_standard_contract(error_app: FastAPI) -> None:
    with TestClient(error_app) as client:
        response = client.get("/_test/items/not-an-integer")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["message"] == "Request validation failed."
    assert_request_id(response)


def test_application_error_uses_standard_contract(error_app: FastAPI) -> None:
    with TestClient(error_app) as client:
        response = client.get("/_test/missing")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert response.json()["error"]["message"] == "Account was not found."
    assert_request_id(response)


def test_internal_error_does_not_expose_exception(error_app: FastAPI) -> None:
    with TestClient(error_app, raise_server_exceptions=False) as client:
        response = client.get("/_test/internal")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret database detail" not in response.text
    assert_request_id(response)
