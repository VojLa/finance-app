import asyncio
from collections.abc import AsyncIterator
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import ImportStatus
from app.modules.accounts.access import AccountAccessDeniedError
from app.modules.imports.service import (
    ImportBatchNotFoundError,
    ImportBatchService,
    ImportUploadContentTypeError,
    ImportUploadMismatchError,
    ImportUploadStateError,
    ImportUploadTooLargeError,
)
from app.modules.imports.storage import ImportFileMismatchError, LocalImportStorage


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="user-a", email="user-a@example.com", name="User A")


async def _chunks(*chunks: bytes) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk


class _ForbiddenStream:
    def __aiter__(self) -> "_ForbiddenStream":
        return self

    async def __anext__(self) -> bytes:
        raise AssertionError("stream consumed")


def _service(tmp_path: Path) -> tuple[ImportBatchService, AsyncSession]:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    return ImportBatchService(session, storage=LocalImportStorage(tmp_path)), session


def _batch(content: bytes, *, status: ImportStatus = ImportStatus.pending) -> SimpleNamespace:
    return SimpleNamespace(
        id="batch-a",
        file_size=len(content),
        checksum=sha256(content).hexdigest(),
        status=status,
    )


@pytest.mark.parametrize(
    "batch_id", ["../../outside", "/absolute/path", "..\\outside", "batch/part"]
)
def test_storage_hashes_untrusted_batch_id(tmp_path: Path, batch_id: str) -> None:
    storage = LocalImportStorage(tmp_path)
    destination = storage.path_for(batch_id)

    assert destination.resolve().is_relative_to(tmp_path.resolve())
    assert destination.parent.name == sha256(batch_id.encode()).hexdigest()
    assert batch_id not in str(destination.relative_to(tmp_path))


@pytest.mark.asyncio
async def test_invalid_content_is_never_published(tmp_path: Path) -> None:
    storage = LocalImportStorage(tmp_path)
    content = b"invalid"

    with pytest.raises(ImportFileMismatchError):
        await storage.store(
            batch_id="batch-a",
            chunks=_chunks(content),
            max_bytes=100,
            expected_size=len(content),
            expected_checksum="0" * 64,
        )

    assert not storage.path_for("batch-a").exists()
    assert not list(tmp_path.rglob("upload-*"))


@pytest.mark.asyncio
async def test_invalid_retry_preserves_existing_valid_file(tmp_path: Path) -> None:
    storage = LocalImportStorage(tmp_path)
    valid = b"valid"
    checksum = sha256(valid).hexdigest()
    await storage.store(
        batch_id="batch-a",
        chunks=_chunks(valid),
        max_bytes=100,
        expected_size=len(valid),
        expected_checksum=checksum,
    )

    with pytest.raises(ImportFileMismatchError):
        await storage.store(
            batch_id="batch-a",
            chunks=_chunks(b"wrong"),
            max_bytes=100,
            expected_size=len(valid),
            expected_checksum=checksum,
        )

    assert storage.path_for("batch-a").read_bytes() == valid
    assert not list(tmp_path.rglob("upload-*"))


@pytest.mark.asyncio
async def test_existing_mismatched_destination_is_detected_and_preserved(tmp_path: Path) -> None:
    storage = LocalImportStorage(tmp_path)
    destination = storage.path_for("batch-a")
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"preexisting wrong bytes")
    valid = b"valid"

    result = await storage.store(
        batch_id="batch-a",
        chunks=_chunks(valid),
        max_bytes=100,
        expected_size=len(valid),
        expected_checksum=sha256(valid).hexdigest(),
    )

    assert result.created is False
    assert result.checksum == sha256(b"preexisting wrong bytes").hexdigest()
    assert destination.read_bytes() == b"preexisting wrong bytes"
    assert not list(tmp_path.rglob("upload-*"))


@pytest.mark.asyncio
async def test_service_rejects_existing_mismatched_destination_without_removing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    valid = b"valid"
    service, _session = _service(tmp_path)
    destination = service.storage.path_for("batch-a")
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"preexisting wrong bytes")
    monkeypatch.setattr("app.modules.imports.service.require_account_access", AsyncMock())
    monkeypatch.setattr(
        service.repository,
        "get_for_account",
        AsyncMock(return_value=_batch(valid)),
    )

    with pytest.raises(ImportUploadMismatchError):
        await service.upload_file(
            principal=_principal(),
            account_id="account-a",
            batch_id="batch-a",
            content_type="application/octet-stream",
            chunks=_chunks(valid),
        )

    assert destination.read_bytes() == b"preexisting wrong bytes"
    assert not list(tmp_path.rglob("upload-*"))


@pytest.mark.asyncio
async def test_stream_failure_cleans_temporary_file_and_allows_retry(tmp_path: Path) -> None:
    storage = LocalImportStorage(tmp_path)
    content = b"complete"

    async def broken() -> AsyncIterator[bytes]:
        yield b"partial"
        raise RuntimeError("stream failed")

    with pytest.raises(RuntimeError, match="stream failed"):
        await storage.store(
            batch_id="batch-a",
            chunks=broken(),
            max_bytes=100,
            expected_size=len(content),
            expected_checksum=sha256(content).hexdigest(),
        )

    assert not storage.path_for("batch-a").exists()
    assert not list(tmp_path.rglob("upload-*"))
    result = await storage.store(
        batch_id="batch-a",
        chunks=_chunks(content),
        max_bytes=100,
        expected_size=len(content),
        expected_checksum=sha256(content).hexdigest(),
    )
    assert result.created is True


@pytest.mark.asyncio
async def test_oversized_stream_stops_immediately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _session = _service(tmp_path)
    consumed: list[int] = []

    async def oversized() -> AsyncIterator[bytes]:
        for index, chunk in enumerate([b"123", b"456", b"must-not-be-consumed"]):
            consumed.append(index)
            yield chunk

    batch = _batch(b"12345")
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=batch))
    access = AsyncMock()
    monkeypatch.setattr("app.modules.imports.service.require_account_access", access)
    with pytest.raises(ImportUploadTooLargeError):
        await service.upload_file(
            principal=_principal(),
            account_id="account-a",
            batch_id="batch-a",
            content_type="application/octet-stream",
            chunks=oversized(),
        )

    assert consumed == [0, 1]
    assert not list(tmp_path.rglob("upload-*"))


@pytest.mark.asyncio
async def test_empty_file_and_process_restart_idempotence(tmp_path: Path) -> None:
    checksum = sha256(b"").hexdigest()
    first_storage = LocalImportStorage(tmp_path)
    first = await first_storage.store(
        batch_id="batch-empty",
        chunks=_chunks(b""),
        max_bytes=0,
        expected_size=0,
        expected_checksum=checksum,
    )
    second = await LocalImportStorage(tmp_path).store(
        batch_id="batch-empty",
        chunks=_chunks(b""),
        max_bytes=0,
        expected_size=0,
        expected_checksum=checksum,
    )

    assert first.created is True
    assert second.created is False
    assert second.size == 0
    assert second.checksum == checksum


@pytest.mark.asyncio
async def test_concurrent_identical_and_conflicting_uploads_are_safe(tmp_path: Path) -> None:
    valid = b"verified content"
    checksum = sha256(valid).hexdigest()
    storage = LocalImportStorage(tmp_path)

    identical = await asyncio.gather(
        storage.store(
            batch_id="same",
            chunks=_chunks(valid),
            max_bytes=100,
            expected_size=len(valid),
            expected_checksum=checksum,
        ),
        storage.store(
            batch_id="same",
            chunks=_chunks(valid),
            max_bytes=100,
            expected_size=len(valid),
            expected_checksum=checksum,
        ),
    )
    assert sorted(result.created for result in identical) == [False, True]
    assert storage.path_for("same").read_bytes() == valid

    conflicting = await asyncio.gather(
        storage.store(
            batch_id="conflict",
            chunks=_chunks(valid),
            max_bytes=100,
            expected_size=len(valid),
            expected_checksum=checksum,
        ),
        storage.store(
            batch_id="conflict",
            chunks=_chunks(b"invalid content"),
            max_bytes=100,
            expected_size=len(valid),
            expected_checksum=checksum,
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, BaseException) for result in conflicting) == 1
    assert sum(isinstance(result, ImportFileMismatchError) for result in conflicting) == 1
    assert storage.path_for("conflict").read_bytes() == valid
    assert not list(tmp_path.rglob("upload-*"))
    assert not list(tmp_path.rglob("publish.lock"))


@pytest.mark.parametrize(
    "content_type",
    [None, "text/csv", "text/plain", "multipart/form-data", "application/json"],
)
@pytest.mark.asyncio
async def test_invalid_content_type_does_not_consume_stream(
    tmp_path: Path,
    content_type: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _session = _service(tmp_path)
    monkeypatch.setattr(
        service.repository,
        "get_for_account",
        AsyncMock(return_value=_batch(b"data")),
    )
    monkeypatch.setattr("app.modules.imports.service.require_account_access", AsyncMock())

    with pytest.raises(ImportUploadContentTypeError):
        await service.upload_file(
            principal=_principal(),
            account_id="account-a",
            batch_id="batch-a",
            content_type=content_type,
            chunks=_ForbiddenStream(),
        )
    assert not tmp_path.exists() or not any(tmp_path.iterdir())


@pytest.mark.parametrize(
    "status",
    [
        ImportStatus.processing,
        ImportStatus.completed,
        ImportStatus.failed,
        ImportStatus.partially_completed,
        ImportStatus.cancelled,
    ],
)
@pytest.mark.asyncio
async def test_non_pending_state_does_not_consume_stream(
    tmp_path: Path,
    status: ImportStatus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _session = _service(tmp_path)
    monkeypatch.setattr(
        service.repository,
        "get_for_account",
        AsyncMock(return_value=_batch(b"data", status=status)),
    )
    monkeypatch.setattr("app.modules.imports.service.require_account_access", AsyncMock())

    with pytest.raises(ImportUploadStateError):
        await service.upload_file(
            principal=_principal(),
            account_id="account-a",
            batch_id="batch-a",
            content_type="application/octet-stream",
            chunks=_ForbiddenStream(),
        )


@pytest.mark.asyncio
async def test_authorization_and_lookup_precede_stream_and_filesystem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _session = _service(tmp_path)

    lookup = AsyncMock()
    monkeypatch.setattr(service.repository, "get_for_account", lookup)
    monkeypatch.setattr(
        "app.modules.imports.service.require_account_access",
        AsyncMock(side_effect=AccountAccessDeniedError()),
    )
    with pytest.raises(AccountAccessDeniedError):
        await service.upload_file(
            principal=_principal(),
            account_id="account-a",
            batch_id="batch-a",
            content_type="application/octet-stream",
            chunks=_ForbiddenStream(),
        )
    lookup.assert_not_awaited()
    assert not any(tmp_path.iterdir())

    monkeypatch.setattr("app.modules.imports.service.require_account_access", AsyncMock())
    lookup.return_value = None
    with pytest.raises(ImportBatchNotFoundError):
        await service.upload_file(
            principal=_principal(),
            account_id="account-a",
            batch_id="batch-a",
            content_type="application/octet-stream",
            chunks=_ForbiddenStream(),
        )
    assert not any(tmp_path.iterdir())
