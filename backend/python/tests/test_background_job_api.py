from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.background_jobs import BackgroundJobModel
from app.db.models.enums import BackgroundJobKind, BackgroundJobStatus
from app.main import create_app
from app.modules.accounts.access import AccountNotFoundError
from app.modules.jobs.models import ImportJobResponse
from app.modules.jobs.repository import BackgroundJobRepository
from app.modules.jobs.service import EnqueueImportJobResult

_PATH = "/api/v1/accounts/account-a/imports/jobs"


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="user-a", email="user-a@example.test")


def _job() -> BackgroundJobModel:
    now = datetime(2026, 8, 10, 12)
    return cast(
        BackgroundJobModel,
        SimpleNamespace(
            id="job-a",
            account_id="account-a",
            kind=BackgroundJobKind.import_workflow,
            status=BackgroundJobStatus.queued,
            progress={
                "schema_version": 1,
                "phase": "queued",
                "completed_units": 0,
                "total_units": 7,
                "completed_batches": 0,
                "total_batches": 1,
            },
            result=None,
            error_code=None,
            error_message=None,
            attempt_count=0,
            max_attempts=5,
            manual_retry_count=0,
            run_after=now,
            started_at=None,
            finished_at=None,
            created_at=now,
            updated_at=now,
            # Durable internals deliberately must never be serialized.
            payload={"schema_version": 1, "batch_ids": ["batch-a"]},
            checkpoint={"schema_version": 1, "phase": "queued", "completed_batch_ids": []},
            lease_owner="worker-a",
            lease_version=9,
            lease_expires_at=now,
        ),
    )


def _response() -> ImportJobResponse:
    from app.modules.jobs.service import BackgroundJobService

    return BackgroundJobService.public_response(_job())


def _client(test_settings: Settings) -> TestClient:
    app = create_app(test_settings)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_current_principal] = _principal
    app.dependency_overrides[get_db_session] = session_override
    return TestClient(app)


def test_start_import_job_returns_202_and_replays_the_same_public_job(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.jobs.service import BackgroundJobService

    enqueue = AsyncMock(
        side_effect=[
            EnqueueImportJobResult(job=_job(), created=True),
            EnqueueImportJobResult(job=_job(), created=False),
        ]
    )
    monkeypatch.setattr(BackgroundJobService, "enqueue_import_job", enqueue)

    with _client(test_settings) as client:
        first = client.post(_PATH, json={"batch_ids": ["batch-a"]})
        replay = client.post(_PATH, json={"batch_ids": ["batch-a"]})

    assert first.status_code == replay.status_code == 202
    assert first.json()["id"] == replay.json()["id"] == "job-a"
    assert enqueue.await_count == 2


def test_get_import_job_returns_only_the_safe_public_contract(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.jobs.service import BackgroundJobService

    get = AsyncMock(return_value=_response())
    monkeypatch.setattr(BackgroundJobService, "get_import_job", get)

    with _client(test_settings) as client:
        response = client.get(f"{_PATH}/job-a")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "job-a"
    assert not (
        {"payload", "checkpoint", "lease_owner", "lease_version", "lease_expires_at"} & body.keys()
    )


def test_retry_endpoint_returns_the_same_public_job(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.jobs.service import BackgroundJobService

    retry = AsyncMock(return_value=_response())
    monkeypatch.setattr(BackgroundJobService, "retry_import_job", retry)

    with _client(test_settings) as client:
        response = client.post(f"{_PATH}/job-a/retry")

    assert response.status_code == 200
    assert response.json()["id"] == "job-a"
    retry.assert_awaited_once()


def test_get_hides_foreign_account_and_missing_or_foreign_job_with_the_same_404_body(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def access(*, account_id: str, **_: object) -> None:
        if account_id == "foreign-account":
            raise AccountNotFoundError()

    monkeypatch.setattr("app.modules.jobs.service.require_account_access", access)
    monkeypatch.setattr(BackgroundJobRepository, "get_owned", AsyncMock(return_value=None))

    with _client(test_settings) as client:
        foreign_account = client.get("/api/v1/accounts/foreign-account/imports/jobs/job-a")
        missing_or_foreign_job = client.get(f"{_PATH}/job-a")

    assert foreign_account.status_code == missing_or_foreign_job.status_code == 404
    assert (
        {
            key: value
            for key, value in foreign_account.json()["error"].items()
            if key != "request_id"
        }
        == {
            key: value
            for key, value in missing_or_foreign_job.json()["error"].items()
            if key != "request_id"
        }
        == {
            "code": "background_job_not_found",
            "message": "The background job was not found.",
        }
    )


@pytest.mark.parametrize(
    "batch_ids",
    [[], ["batch-b", "batch-a"], ["batch-a", "batch-a"]],
)
def test_start_import_job_rejects_invalid_durable_payload_at_http_boundary(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    batch_ids: list[str],
) -> None:
    from app.modules.jobs.service import BackgroundJobService

    enqueue = AsyncMock()
    monkeypatch.setattr(BackgroundJobService, "enqueue_import_job", enqueue)

    with _client(test_settings) as client:
        response = client.post(_PATH, json={"batch_ids": batch_ids})

    assert response.status_code == 422
    enqueue.assert_not_awaited()


def test_background_job_openapi_exposes_202_and_hides_durable_internals(
    test_settings: Settings,
) -> None:
    schema = create_app(test_settings).openapi()
    operation = schema["paths"]["/api/v1/accounts/{account_id}/imports/jobs"]["post"]
    response_schema = operation["responses"]["202"]["content"]["application/json"]["schema"]
    assert response_schema == {"$ref": "#/components/schemas/ImportJobResponse"}
    status_operation = schema["paths"]["/api/v1/accounts/{account_id}/imports/jobs/{job_id}"]["get"]
    retry_operation = schema["paths"]["/api/v1/accounts/{account_id}/imports/jobs/{job_id}/retry"][
        "post"
    ]
    assert "requestBody" not in retry_operation
    assert status_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ImportJobResponse"
    }
    assert retry_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ImportJobResponse"
    }
    assert operation["security"] == status_operation["security"] == retry_operation["security"]
    properties = schema["components"]["schemas"]["ImportJobResponse"]["properties"]
    assert not (
        {"payload", "checkpoint", "lease_owner", "lease_version", "lease_expires_at"}
        & properties.keys()
    )
