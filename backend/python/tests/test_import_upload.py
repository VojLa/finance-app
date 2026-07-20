from collections.abc import AsyncIterator
from hashlib import sha256
from pathlib import Path
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
from app.db.models.enums import ImportStatus
from app.main import create_app
from app.modules.imports.models import ImportUploadResponse
from app.modules.imports.service import ImportBatchService, ImportUploadMismatchError
from app.modules.imports.storage import LocalImportStorage


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="user-a", email="user-a@example.com", name="User A")


async def _chunks(content: bytes) -> AsyncIterator[bytes]:
    midpoint = len(content) // 2
    yield content[:midpoint]
    yield content[midpoint:]


def _client(test_settings: Settings) -> TestClient:
    app = create_app(test_settings)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_current_principal] = _principal
    app.dependency_overrides[get_db_session] = session_override
    return TestClient(app)


def test_upload_requires_authentication(test_settings: Settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.put(
            "/api/v1/accounts/account-a/imports/batch-a/file",
            content=b"data",
            headers={"Content-Type": "application/octet-stream"},
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_upload_rejects_invalid_authentication(test_settings: Settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.put(
            "/api/v1/accounts/account-a/imports/batch-a/file",
            content=b"data",
            headers={
                "Authorization": "Bearer invalid",
                "Content-Type": "application/octet-stream",
            },
        )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session_token"


def test_upload_endpoint_forwards_stream_and_principal(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload = AsyncMock(
        return_value=ImportUploadResponse(
            batch_id="batch-a",
            size=4,
            checksum=sha256(b"data").hexdigest(),
            stored=True,
            idempotent=False,
        )
    )
    monkeypatch.setattr(ImportBatchService, "upload_file", upload)

    with _client(test_settings) as client:
        response = client.put(
            "/api/v1/accounts/account-a/imports/batch-a/file",
            content=b"data",
            headers={"Content-Type": "application/octet-stream"},
        )

    assert response.status_code == 200
    assert response.json()["batch_id"] == "batch-a"
    assert upload.await_args is not None
    assert upload.await_args.kwargs["principal"].user_id == "user-a"
    assert upload.await_args.kwargs["account_id"] == "account-a"
    assert upload.await_args.kwargs["batch_id"] == "batch-a"
    assert upload.await_args.kwargs["content_type"] == "application/octet-stream"


@pytest.mark.asyncio
async def test_local_storage_is_atomic_and_idempotent(tmp_path: Path) -> None:
    storage = LocalImportStorage(tmp_path)
    content = b"account import content"

    checksum = sha256(content).hexdigest()
    first = await storage.store(
        batch_id="batch-a",
        chunks=_chunks(content),
        max_bytes=100,
        expected_size=len(content),
        expected_checksum=checksum,
    )
    second = await storage.store(
        batch_id="batch-a",
        chunks=_chunks(content),
        max_bytes=100,
        expected_size=len(content),
        expected_checksum=checksum,
    )

    assert first.created is True
    assert second.created is False
    assert first.size == len(content)
    assert first.checksum == sha256(content).hexdigest()
    assert storage.path_for("batch-a").read_bytes() == content
    assert not list(storage.path_for("batch-a").parent.glob("upload-*"))


@pytest.mark.asyncio
async def test_upload_verifies_registered_checksum_and_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"verified import"
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    service = ImportBatchService(session, storage=LocalImportStorage(tmp_path))
    batch = SimpleNamespace(
        id="batch-a",
        file_size=len(content),
        checksum=sha256(content).hexdigest(),
        status=ImportStatus.pending,
    )
    monkeypatch.setattr(
        "app.modules.imports.service.require_account_access",
        AsyncMock(),
    )
    monkeypatch.setattr(
        service.repository,
        "get_for_account",
        AsyncMock(return_value=batch),
    )

    result = await service.upload_file(
        principal=_principal(),
        account_id="account-a",
        batch_id="batch-a",
        content_type="application/octet-stream",
        chunks=_chunks(content),
    )

    assert result.stored is True
    assert result.idempotent is False
    assert result.size == len(content)
    assert result.checksum == sha256(content).hexdigest()


@pytest.mark.asyncio
async def test_checksum_mismatch_removes_new_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"wrong content"
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    storage = LocalImportStorage(tmp_path)
    service = ImportBatchService(session, storage=storage)
    batch = SimpleNamespace(
        id="batch-a",
        file_size=len(content),
        checksum="0" * 64,
        status=ImportStatus.pending,
    )
    monkeypatch.setattr(
        "app.modules.imports.service.require_account_access",
        AsyncMock(),
    )
    monkeypatch.setattr(
        service.repository,
        "get_for_account",
        AsyncMock(return_value=batch),
    )

    with pytest.raises(ImportUploadMismatchError):
        await service.upload_file(
            principal=_principal(),
            account_id="account-a",
            batch_id="batch-a",
            content_type="application/octet-stream",
            chunks=_chunks(content),
        )

    assert not storage.path_for("batch-a").exists()


def test_upload_openapi_declares_binary_body_and_security(test_settings: Settings) -> None:
    schema = create_app(test_settings).openapi()
    operation = schema["paths"]["/api/v1/accounts/{account_id}/imports/{batch_id}/file"]["put"]

    assert operation["security"] == [{"InternalSessionToken": []}]
    assert "200" in operation["responses"]
    assert operation["requestBody"] == {
        "required": True,
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
    }
    assert {parameter["name"] for parameter in operation["parameters"]} == {
        "account_id",
        "batch_id",
    }
    assert schema["paths"]["/api/v1/health/live"]["get"].get("security") is None
