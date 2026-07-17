from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from app.main import create_app


def test_response_contains_generated_request_id(monkeypatch) -> None:
    async def no_database() -> None:
        return None

    monkeypatch.setattr("app.lifespan.connect_database", no_database)

    with TestClient(create_app()) as client:
        response = client.get("/")

    request_id = response.headers["X-Request-ID"]
    assert str(UUID(request_id)) == request_id


def test_valid_request_id_is_propagated(monkeypatch) -> None:
    async def no_database() -> None:
        return None

    monkeypatch.setattr("app.lifespan.connect_database", no_database)
    request_id = str(uuid4())

    with TestClient(create_app()) as client:
        response = client.get("/", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id


def test_invalid_request_id_is_replaced(monkeypatch) -> None:
    async def no_database() -> None:
        return None

    monkeypatch.setattr("app.lifespan.connect_database", no_database)

    with TestClient(create_app()) as client:
        response = client.get("/", headers={"X-Request-ID": "not-a-uuid"})

    request_id = response.headers["X-Request-ID"]
    assert request_id != "not-a-uuid"
    assert str(UUID(request_id)) == request_id
