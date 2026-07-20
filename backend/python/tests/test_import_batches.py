from collections.abc import AsyncIterator
from datetime import datetime
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.enums import ImportSource, ImportStatus
from app.main import create_app
from app.modules.imports.models import ImportBatchResponse
from app.modules.imports.service import ImportBatchService


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="user-a", email="user-a@example.com", name="User A")


def _batch() -> ImportBatchResponse:
    return ImportBatchResponse(
        id="batch-a",
        account_id="account-a",
        source=ImportSource.raiffeisenbank,
        filename="history.csv",
        file_size=1200,
        file_encoding="utf-8",
        checksum="a" * 64,
        status=ImportStatus.pending,
        rows_total=None,
        rows_imported=None,
        rows_skipped=None,
        created_at=datetime(2026, 7, 19, 18, 0, 0),
        completed_at=None,
    )


def _client(test_settings: Settings) -> TestClient:
    app = create_app(test_settings)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_current_principal] = _principal
    app.dependency_overrides[get_db_session] = session_override
    return TestClient(app)


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "post",
            "/api/v1/accounts/account-a/imports",
            {"source": "raiffeisenbank", "filename": "history.csv", "checksum": "a" * 64},
        ),
        ("get", "/api/v1/accounts/account-a/imports", None),
        ("get", "/api/v1/accounts/account-a/imports/batch-a", None),
    ],
)
def test_import_batch_endpoints_require_authentication(
    test_settings: Settings,
    method: str,
    path: str,
    payload: dict[str, str] | None,
) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.request(method, path, json=payload)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "post",
            "/api/v1/accounts/account-a/imports",
            {"source": "raiffeisenbank", "filename": "history.csv", "checksum": "a" * 64},
        ),
        ("get", "/api/v1/accounts/account-a/imports", None),
        ("get", "/api/v1/accounts/account-a/imports/batch-a", None),
    ],
)
def test_import_batch_endpoints_reject_invalid_authentication(
    test_settings: Settings,
    method: str,
    path: str,
    payload: dict[str, str] | None,
) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.request(
            method,
            path,
            json=payload,
            headers={"Authorization": "Bearer invalid"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session_token"


def test_create_import_batch_uses_authenticated_principal(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_batch = AsyncMock(return_value=_batch())
    monkeypatch.setattr(ImportBatchService, "create_batch", create_batch)

    with _client(test_settings) as client:
        response = client.post(
            "/api/v1/accounts/account-a/imports",
            json={
                "source": "raiffeisenbank",
                "filename": " history.csv ",
                "file_encoding": " UTF-8 ",
                "checksum": "A" * 64,
            },
        )

    assert response.status_code == 201
    assert create_batch.await_args is not None
    assert create_batch.await_args.kwargs["principal"].user_id == "user-a"
    assert create_batch.await_args.kwargs["account_id"] == "account-a"
    payload = create_batch.await_args.kwargs["payload"]
    assert payload.filename == "history.csv"
    assert payload.file_encoding == "utf-8"
    assert payload.checksum == "a" * 64


@pytest.mark.parametrize(
    "payload",
    [
        {"source": "raiffeisenbank", "filename": "", "checksum": "a" * 64},
        {"source": "raiffeisenbank", "filename": "../secret.csv", "checksum": "a" * 64},
        {"source": "raiffeisenbank", "filename": "C:\\temp\\data.csv", "checksum": "a" * 64},
        {"source": "raiffeisenbank", "filename": "a.csv", "file_size": -1, "checksum": "a" * 64},
        {"source": "raiffeisenbank", "filename": "a.csv", "checksum": "bad"},
        {"source": "raiffeisenbank", "filename": "a.csv", "checksum": "g" * 64},
        {"source": "unknown", "filename": "a.csv", "checksum": "a" * 64},
        {"source": "raiffeisenbank", "filename": "a.csv", "checksum": "a" * 64, "user_id": "x"},
    ],
)
def test_create_import_batch_rejects_invalid_payload(
    test_settings: Settings,
    payload: dict[str, object],
) -> None:
    with _client(test_settings) as client:
        response = client.post("/api/v1/accounts/account-a/imports", json=payload)

    assert response.status_code == 422


def test_import_batch_openapi_contract(test_settings: Settings) -> None:
    schema = create_app(test_settings).openapi()
    operations = [
        schema["paths"]["/api/v1/accounts/{account_id}/imports"]["post"],
        schema["paths"]["/api/v1/accounts/{account_id}/imports"]["get"],
        schema["paths"]["/api/v1/accounts/{account_id}/imports/{batch_id}"]["get"],
    ]
    for operation in operations:
        assert operation["security"] == [{"InternalSessionToken": []}]
    assert "201" in operations[0]["responses"]
    assert schema["paths"]["/api/v1/health/live"]["get"].get("security") is None
    assert sorted(path for path in schema["paths"] if "import" in path) == [
        "/api/v1/accounts/{account_id}/imports",
        "/api/v1/accounts/{account_id}/imports/{batch_id}",
        "/api/v1/accounts/{account_id}/imports/{batch_id}/file",
        "/api/v1/accounts/{account_id}/imports/{batch_id}/parse",
    ]
