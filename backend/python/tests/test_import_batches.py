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
from app.modules.accounts.access import AccountNotFoundError
from app.modules.imports.models import (
    ImportBatchResponse,
    ImportPostResponse,
    ImportSnapshotRefreshStatus,
)
from app.modules.imports.post_processing_service import ImportBatchPostProcessingService
from app.modules.imports.posting_service import (
    ImportBatchPostStateError,
)
from app.modules.imports.service import ImportBatchNotFoundError, ImportBatchService


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


def _post_response() -> ImportPostResponse:
    return ImportPostResponse(
        batch_id="batch-a",
        status=ImportStatus.completed,
        rows_total=2,
        rows_imported=1,
        rows_skipped=1,
        completed_at=datetime(2026, 7, 25, 12),
        replayed=False,
        snapshot_refresh_status=ImportSnapshotRefreshStatus.created,
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
        ("post", "/api/v1/accounts/account-a/imports/batch-a/post", None),
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
        ("post", "/api/v1/accounts/account-a/imports/batch-a/post", None),
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
        "/api/v1/accounts/{account_id}/imports/{batch_id}/classify",
        "/api/v1/accounts/{account_id}/imports/{batch_id}/deduplicate",
        "/api/v1/accounts/{account_id}/imports/{batch_id}/file",
        "/api/v1/accounts/{account_id}/imports/{batch_id}/normalize",
        "/api/v1/accounts/{account_id}/imports/{batch_id}/parse",
        "/api/v1/accounts/{account_id}/imports/{batch_id}/post",
    ]


def test_post_import_batch_endpoint_is_thin_and_stable(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    post_batch = AsyncMock(return_value=_post_response())
    monkeypatch.setattr(ImportBatchPostProcessingService, "post_batch", post_batch)

    with _client(test_settings) as client:
        response = client.post("/api/v1/accounts/account-a/imports/batch-a/post")

    assert response.status_code == 200
    assert response.json() == {
        "batch_id": "batch-a",
        "status": "completed",
        "rows_total": 2,
        "rows_imported": 1,
        "rows_skipped": 1,
        "completed_at": "2026-07-25T12:00:00",
        "replayed": False,
        "snapshot_refresh_status": "created",
    }
    assert post_batch.await_args is not None
    command = post_batch.await_args.args[0]
    assert command.principal.user_id == "user-a"
    assert command.account_id == "account-a"
    assert command.batch_id == "batch-a"


@pytest.mark.parametrize(
    "snapshot_status",
    (
        ImportSnapshotRefreshStatus.unavailable,
        ImportSnapshotRefreshStatus.conflict,
    ),
)
def test_post_import_batch_reports_known_post_processing_failure_as_http_200(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    snapshot_status: ImportSnapshotRefreshStatus,
) -> None:
    result = _post_response().model_copy(update={"snapshot_refresh_status": snapshot_status})
    monkeypatch.setattr(
        ImportBatchPostProcessingService,
        "post_batch",
        AsyncMock(return_value=result),
    )

    with _client(test_settings) as client:
        response = client.post("/api/v1/accounts/account-a/imports/batch-a/post")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["snapshot_refresh_status"] == snapshot_status.value


def test_post_import_batch_openapi_contract(test_settings: Settings) -> None:
    schema = create_app(test_settings).openapi()
    operation = schema["paths"]["/api/v1/accounts/{account_id}/imports/{batch_id}/post"]["post"]

    assert operation["security"] == [{"InternalSessionToken": []}]
    assert "requestBody" not in operation
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ImportPostResponse"
    }
    assert (
        "snapshot_refresh_status"
        in schema["components"]["schemas"]["ImportPostResponse"]["required"]
    )


def test_import_post_response_rejects_internal_post_processing_fields() -> None:
    payload = _post_response().model_dump()
    for field in (
        "user_id",
        "account_id",
        "transaction_rows_imported",
        "investment_event_rows_imported",
        "holding_ids",
        "account_snapshot_ids",
        "net_worth_snapshot_id",
        "lineage",
        "exchange_rates",
    ):
        with pytest.raises(ValueError):
            ImportPostResponse.model_validate(payload | {field: "internal"})


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (AccountNotFoundError(), 404, "account_not_found"),
        (ImportBatchNotFoundError(), 404, "import_batch_not_found"),
        (ImportBatchPostStateError(), 409, "import_post_batch_state_invalid"),
    ],
)
def test_post_import_batch_maps_domain_failures(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    status_code: int,
    code: str,
) -> None:
    monkeypatch.setattr(
        ImportBatchPostProcessingService,
        "post_batch",
        AsyncMock(side_effect=error),
    )

    with _client(test_settings) as client:
        response = client.post("/api/v1/accounts/account-a/imports/batch-a/post")

    assert response.status_code == status_code
    assert response.json()["error"]["code"] == code


def test_classify_openapi_and_authentication_contract(test_settings: Settings) -> None:
    app = create_app(test_settings)
    operation = app.openapi()["paths"]["/api/v1/accounts/{account_id}/imports/{batch_id}/classify"][
        "post"
    ]
    assert "requestBody" not in operation
    assert operation["security"] == [{"InternalSessionToken": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ImportClassifyResponse"
    }
    with TestClient(app) as client:
        missing = client.post("/api/v1/accounts/account-a/imports/batch-a/classify")
        invalid = client.post(
            "/api/v1/accounts/account-a/imports/batch-a/classify",
            headers={"Authorization": "Bearer invalid"},
        )
    assert (missing.status_code, missing.json()["error"]["code"]) == (
        401,
        "authentication_required",
    )
    assert (invalid.status_code, invalid.json()["error"]["code"]) == (
        401,
        "invalid_session_token",
    )
