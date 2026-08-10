import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.enums import ImportRowStatus, ImportSource, ImportStatus
from app.db.models.imports import ImportBatchModel
from app.main import create_app
from app.modules.imports.parsers import ImportParseError, parse_import_file
from app.modules.imports.processing import (
    ImportFileInvalidError,
    ImportFileMissingError,
    ImportParserService,
    ImportParseStateError,
)
from app.modules.imports.storage import LocalImportStorage


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="user-a", email="user-a@example.com", name="User A")


def _batch(content: bytes) -> ImportBatchModel:
    return ImportBatchModel(
        id="batch-a",
        user_id="user-a",
        account_id="account-a",
        source=ImportSource.raiffeisenbank,
        filename="history.csv",
        file_size=len(content),
        file_encoding="utf-8",
        checksum=sha256(content).hexdigest(),
        status=ImportStatus.pending,
        rows_total=None,
        rows_imported=None,
        rows_skipped=None,
        created_at=datetime(2026, 7, 20, 12, 0, 0),
        completed_at=None,
        retain_until=None,
        raw_data_purged_at=None,
    )


def test_parser_preserves_valid_blank_and_overflow_rows() -> None:
    content = b"date;amount\n2026-01-01;100\n;\n2026-01-02;200;extra\n"

    rows = parse_import_file(ImportSource.manual, content, encoding="utf-8")

    assert [row.row_number for row in rows] == [2, 3, 4]
    assert rows[0].raw_data == {"date": "2026-01-01", "amount": "100"}
    assert rows[0].error_message is None
    assert rows[1].error_message == "The row is blank."
    assert rows[2].error_message == "The row contains more values than the header defines."


@pytest.mark.parametrize(
    "content",
    [b"", b";\n1;2\n", b"a;a\n1;2\n"],
)
def test_parser_rejects_fatal_file_structure(content: bytes) -> None:
    with pytest.raises(ImportParseError):
        parse_import_file(ImportSource.manual, content, encoding="utf-8")


def test_parse_endpoint_requires_authentication(test_settings: Settings) -> None:
    with TestClient(create_app(test_settings)) as client:
        response = client.post("/api/v1/accounts/account-a/imports/batch-a/parse")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_parse_endpoint_forwards_principal_and_ids(
    test_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app(test_settings)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_current_principal] = _principal
    app.dependency_overrides[get_db_session] = session_override
    parse = AsyncMock(
        return_value={
            "batch_id": "batch-a",
            "status": "processing",
            "rows_total": 2,
            "rows_pending": 2,
            "rows_failed": 0,
        }
    )
    monkeypatch.setattr(ImportParserService, "parse_batch", parse)

    with TestClient(app) as client:
        response = client.post("/api/v1/accounts/account-a/imports/batch-a/parse")

    assert response.status_code == 200
    parse.assert_awaited_once()
    assert parse.await_args is not None
    call = parse.await_args.kwargs
    assert call["principal"].user_id == "user-a"
    assert call["account_id"] == "account-a"
    assert call["batch_id"] == "batch-a"


def test_parser_load_requires_existing_verified_file(tmp_path: Path) -> None:
    content = b"a,b\n1,2\n"
    service = ImportParserService(
        cast(AsyncSession, AsyncMock(spec=AsyncSession)),
        storage=LocalImportStorage(tmp_path),
    )
    batch = _batch(content)

    with pytest.raises(ImportFileMissingError):
        service._load_verified_file(
            batch_id=batch.id,
            expected_size=batch.file_size,
            expected_checksum=batch.checksum,
        )

    path = service.storage.path_for(batch.id)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"changed")
    with pytest.raises(ImportFileInvalidError):
        service._load_verified_file(
            batch_id=batch.id,
            expected_size=batch.file_size,
            expected_checksum=batch.checksum,
        )


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
def test_parser_rejects_non_pending_batch_before_storage_read(
    status: ImportStatus,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"a,b\n1,2\n"
    batch = _batch(content)
    batch.status = status
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    service = ImportParserService(session)
    monkeypatch.setattr(
        "app.modules.imports.processing.require_account_access",
        AsyncMock(),
    )
    service.repository.get_for_account = AsyncMock(return_value=batch)  # type: ignore[method-assign]
    service.repository.list_rows_for_update = AsyncMock(return_value=[])  # type: ignore[method-assign]
    load = AsyncMock()
    monkeypatch.setattr(service, "_load_verified_file", load)

    with pytest.raises(ImportParseStateError):
        asyncio.run(
            service.parse_batch(
                principal=_principal(),
                account_id="account-a",
                batch_id="batch-a",
            )
        )

    load.assert_not_awaited()


async def test_parser_offloads_verified_file_read_hash_and_csv_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"date;amount\n2026-01-01;100\n"
    batch = _batch(content)
    batch.source = ImportSource.manual
    storage = LocalImportStorage(tmp_path)
    path = storage.path_for(batch.id)
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    session_mock = AsyncMock(spec=AsyncSession)
    session = cast(AsyncSession, session_mock)
    service = ImportParserService(session, storage=storage)
    service.repository = cast(
        Any,
        SimpleNamespace(
            get_for_account=AsyncMock(side_effect=(batch, batch)),
            count_rows=AsyncMock(return_value=0),
            add_row=Mock(),
            add_log=Mock(),
        ),
    )
    monkeypatch.setattr(
        "app.modules.imports.processing.require_account_access",
        AsyncMock(),
    )
    offload = AsyncMock(side_effect=lambda function, *args, **kwargs: function(*args, **kwargs))
    monkeypatch.setattr("app.modules.imports.processing.asyncio.to_thread", offload)

    result = await service.parse_batch(
        principal=_principal(),
        account_id="account-a",
        batch_id="batch-a",
    )

    assert result.rows_total == result.rows_pending == 1
    offload.assert_awaited_once()
    assert offload.await_args is not None
    assert offload.await_args.args[0] == service._load_and_parse_verified_file
    session_mock.commit.assert_awaited_once()


async def test_parser_reconciles_exact_processing_replay_without_storage_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = _batch(b"date;amount\n2026-01-01;100\n")
    batch.status = ImportStatus.processing
    batch.rows_total = 2
    batch.rows_imported = 0
    batch.rows_skipped = 1
    rows = [
        SimpleNamespace(status=ImportRowStatus.pending),
        SimpleNamespace(status=ImportRowStatus.failed),
    ]
    session_mock = AsyncMock(spec=AsyncSession)
    session = cast(AsyncSession, session_mock)
    service = ImportParserService(session)
    service.repository = cast(
        Any,
        SimpleNamespace(
            get_for_account=AsyncMock(return_value=batch),
            list_rows_for_update=AsyncMock(return_value=rows),
        ),
    )
    monkeypatch.setattr(
        "app.modules.imports.processing.require_account_access",
        AsyncMock(),
    )
    load = Mock()
    monkeypatch.setattr(service, "_load_and_parse_verified_file", load)

    result = await service.parse_batch(
        principal=_principal(),
        account_id="account-a",
        batch_id="batch-a",
    )

    assert (result.status, result.rows_total, result.rows_pending, result.rows_failed) == (
        ImportStatus.processing,
        2,
        1,
        1,
    )
    load.assert_not_called()
    session_mock.rollback.assert_awaited_once()


async def test_parser_rejects_inexact_terminal_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = _batch(b"date;amount\n2026-01-01;100\n")
    batch.status = ImportStatus.completed
    batch.rows_total = 1
    batch.rows_imported = 1
    batch.rows_skipped = 0
    batch.completed_at = datetime(2026, 7, 20, 13)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    service = ImportParserService(session)
    service.repository = cast(
        Any,
        SimpleNamespace(
            get_for_account=AsyncMock(return_value=batch),
            list_rows_for_update=AsyncMock(
                return_value=[SimpleNamespace(status=ImportRowStatus.failed)]
            ),
        ),
    )
    monkeypatch.setattr(
        "app.modules.imports.processing.require_account_access",
        AsyncMock(),
    )

    with pytest.raises(ImportParseStateError):
        await service.parse_batch(
            principal=_principal(),
            account_id="account-a",
            batch_id="batch-a",
        )


async def test_parser_reconciles_exact_terminal_replay_without_storage_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = _batch(b"date;amount\n2026-01-01;100\n")
    batch.status = ImportStatus.partially_completed
    batch.rows_total = 2
    batch.rows_imported = 1
    batch.rows_skipped = 1
    batch.completed_at = datetime(2026, 7, 20, 13)
    session_mock = AsyncMock(spec=AsyncSession)
    service = ImportParserService(cast(AsyncSession, session_mock))
    service.repository = cast(
        Any,
        SimpleNamespace(
            get_for_account=AsyncMock(return_value=batch),
            list_rows_for_update=AsyncMock(
                return_value=[
                    SimpleNamespace(status=ImportRowStatus.imported),
                    SimpleNamespace(status=ImportRowStatus.needs_review),
                ]
            ),
        ),
    )
    monkeypatch.setattr(
        "app.modules.imports.processing.require_account_access",
        AsyncMock(),
    )
    load = Mock()
    monkeypatch.setattr(service, "_load_and_parse_verified_file", load)

    result = await service.parse_batch(
        principal=_principal(),
        account_id="account-a",
        batch_id="batch-a",
    )

    assert (result.status, result.rows_total, result.rows_pending, result.rows_failed) == (
        ImportStatus.processing,
        2,
        2,
        0,
    )
    load.assert_not_called()
    session_mock.rollback.assert_awaited_once()
