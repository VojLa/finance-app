from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.enums import ImportRowStatus, ImportSource, ImportStatus
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.main import create_app
from app.modules.imports.parsers import ImportParseError, parse_import_file
from app.modules.imports.processing import (
    PARSER_MAX_BYTES,
    ImportParseFileTooLargeError,
    ImportParserService,
)
from app.modules.imports.storage import LocalImportStorage


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id="user-a", email="user-a@example.com", name="User A")


def _batch(content: bytes, *, encoding: str | None = "utf-8") -> ImportBatchModel:
    return ImportBatchModel(
        id="batch-a",
        user_id="user-a",
        account_id="account-a",
        source=ImportSource.manual,
        filename="rows.csv",
        file_size=len(content),
        file_encoding=encoding,
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


@pytest.mark.parametrize(
    ("source", "content"),
    [
        (ImportSource.raiffeisenbank, b"date;amount\n2026-01-01;100\n"),
        (ImportSource.trading212, b"date,amount\n2026-01-01,100\n"),
        (ImportSource.anycoin, b"date\tamount\n2026-01-01\t100\n"),
        (ImportSource.manual, b"date,amount\n2026-01-01,100\n"),
    ],
)
def test_registry_preserves_raw_rows_for_every_source(
    source: ImportSource,
    content: bytes,
) -> None:
    rows = parse_import_file(source, content, encoding=None)

    assert rows[0].raw_data == {"date": "2026-01-01", "amount": "100"}
    assert rows[0].row_number == 2
    assert rows[0].error_message is None


@pytest.mark.parametrize("delimiter", [",", ";", "\t"])
def test_parser_supports_required_delimiters(delimiter: str) -> None:
    content = f'name{delimiter}note\nA{delimiter}"one{delimiter}two"\n'.encode()

    rows = parse_import_file(ImportSource.manual, content, encoding="UTF_8")

    assert rows[0].raw_data == {"name": "A", "note": f"one{delimiter}two"}


def test_parser_accepts_bom_windows_encoding_and_multiline_values() -> None:
    bom = "name,note\nA,žluťoučký\n".encode("utf-8-sig")
    windows = "name;note\nA;Příliš žluťoučký\n".encode("cp1250")
    multiline = b'name,note\nA,"line one\nline two"\nB,last\n'

    assert parse_import_file(ImportSource.manual, bom, encoding="utf-8")[0].raw_data == {
        "name": "A",
        "note": "žluťoučký",
    }
    assert (
        parse_import_file(
            ImportSource.manual,
            windows,
            encoding="windows-1250",
        )[0].raw_data["note"]
        == "Příliš žluťoučký"
    )
    rows = parse_import_file(ImportSource.manual, multiline, encoding="utf-8")
    assert [row.row_number for row in rows] == [3, 4]
    assert rows[0].raw_data["note"] == "line one\nline two"


def test_parser_preserves_blank_missing_and_extra_columns_as_structured_issues() -> None:
    content = b"a,b,c\n\n1,2\n3,4,5,6\n7,8,\n"

    rows = parse_import_file(ImportSource.manual, content, encoding="utf-8")

    assert len(rows) == 4
    assert rows[0].validation_errors == {"code": "blank_row"}
    assert rows[1].raw_data == {"a": "1", "b": "2", "c": None}
    assert rows[1].validation_errors == {
        "code": "column_count_mismatch",
        "expected": 3,
        "actual": 2,
    }
    assert rows[2].raw_data["__extra_1"] == "6"
    assert rows[2].validation_errors == {
        "code": "column_count_mismatch",
        "expected": 3,
        "actual": 4,
    }
    assert rows[3].raw_data == {"a": "7", "b": "8", "c": ""}
    assert rows[3].validation_errors is None


def test_blank_line_inside_quoted_multiline_value_is_not_a_separate_record() -> None:
    content = b'a,b\n1,"first\n\nthird"\n2,last\n'

    rows = parse_import_file(ImportSource.manual, content, encoding="utf-8")

    assert len(rows) == 2
    assert rows[0].raw_data["b"] == "first\n\nthird"
    assert [row.row_number for row in rows] == [4, 5]


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"a,b\n",
        b"a,,c\n1,2,3\n",
        b"a,a\n1,2\n",
        b"one-column\nvalue\n",
        b'a,b\n"unterminated,2\n',
    ],
)
def test_parser_rejects_fatal_csv_structures(content: bytes) -> None:
    with pytest.raises(ImportParseError):
        parse_import_file(ImportSource.manual, content, encoding="utf-8")


@pytest.mark.parametrize("encoding", ["not-a-codec", "ascii"])
def test_parser_controls_encoding_failures(encoding: str) -> None:
    with pytest.raises(ImportParseError, match="could not be decoded"):
        parse_import_file(
            ImportSource.manual,
            "a,b\nž,2\n".encode(),
            encoding=encoding,
        )


def test_parser_is_deterministic() -> None:
    content = b"a;b\n1;2\n;\n3;4;5\n"

    assert parse_import_file(
        ImportSource.raiffeisenbank,
        content,
        encoding="utf-8",
    ) == parse_import_file(ImportSource.raiffeisenbank, content, encoding="utf-8")


def test_parser_preserves_raw_whitespace_without_value_coercion() -> None:
    rows = parse_import_file(
        ImportSource.manual,
        b"name,amount\n  Account name  , 001.00 \n",
        encoding="utf-8",
    )

    assert rows[0].raw_data == {"name": "  Account name  ", "amount": " 001.00 "}


def test_parse_openapi_and_invalid_authentication(test_settings: Settings) -> None:
    app = create_app(test_settings)
    operation = app.openapi()["paths"]["/api/v1/accounts/{account_id}/imports/{batch_id}/parse"][
        "post"
    ]

    assert operation["security"] == [{"InternalSessionToken": []}]
    assert operation.get("requestBody") is None
    assert {parameter["name"] for parameter in operation["parameters"]} == {
        "account_id",
        "batch_id",
    }
    assert "200" in operation["responses"]
    assert app.openapi()["paths"]["/api/v1/health/live"]["get"].get("security") is None

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/accounts/account-a/imports/batch-a/parse",
            headers={"Authorization": "Bearer invalid"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_session_token"


def test_parser_ceiling_is_checked_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ImportParserService(
        cast(AsyncSession, AsyncMock(spec=AsyncSession)),
        storage=LocalImportStorage(tmp_path),
    )
    path = service.storage.path_for("batch-a")
    path.parent.mkdir(parents=True)
    with path.open("wb") as oversized:
        oversized.truncate(PARSER_MAX_BYTES + 1)
    read = Mock(side_effect=AssertionError("file must not be read"))
    monkeypatch.setattr(Path, "read_bytes", read)

    with pytest.raises(ImportParseFileTooLargeError) as error:
        service._load_verified_file(
            batch_id="batch-a",
            expected_size=None,
            expected_checksum="0" * 64,
        )

    assert error.value.status_code == 413
    assert PARSER_MAX_BYTES == 67_108_864
    read.assert_not_called()


@pytest.mark.asyncio
async def test_successful_parse_persists_fields_and_counters_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"a,b\n1,2\n3\n"
    batch = _batch(content)
    path = LocalImportStorage(tmp_path).path_for(batch.id)
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    commit = cast(AsyncMock, session.commit)
    rollback = cast(AsyncMock, session.rollback)
    service = ImportParserService(session, storage=LocalImportStorage(tmp_path))
    get_batch = AsyncMock(side_effect=[batch, batch])
    monkeypatch.setattr(service.repository, "get_for_account", get_batch)
    monkeypatch.setattr(service.repository, "count_rows", AsyncMock(return_value=0))
    add_row = Mock()
    add_log = Mock()
    monkeypatch.setattr(service.repository, "add_row", add_row)
    monkeypatch.setattr(service.repository, "add_log", add_log)
    monkeypatch.setattr("app.modules.imports.processing.require_account_access", AsyncMock())

    response = await service.parse_batch(
        principal=_principal(),
        account_id="account-a",
        batch_id="batch-a",
    )

    rows = [call.args[0] for call in add_row.call_args_list]
    assert all(isinstance(row, ImportRowModel) for row in rows)
    assert [row.row_number for row in rows] == [2, 3]
    assert rows[0].status is ImportRowStatus.pending
    assert rows[0].normalized_data is None
    assert rows[0].deduplication_key is None
    assert rows[0].created_transaction_id is None
    assert rows[0].created_investment_event_id is None
    assert rows[1].status is ImportRowStatus.failed
    assert rows[1].validation_errors == {
        "code": "column_count_mismatch",
        "expected": 2,
        "actual": 1,
    }
    assert response.rows_total == 2
    assert response.rows_pending == 1
    assert response.rows_failed == 1
    assert batch.status is ImportStatus.processing
    assert batch.rows_imported == 0
    assert batch.rows_skipped == 1
    assert batch.completed_at is None
    commit.assert_awaited_once()
    rollback.assert_not_awaited()
    add_log.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["row", "log", "commit"])
async def test_parse_failures_roll_back(
    failure: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"a,b\n1\n"
    batch = _batch(content)
    path = LocalImportStorage(tmp_path).path_for(batch.id)
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    commit = cast(AsyncMock, session.commit)
    rollback = cast(AsyncMock, session.rollback)
    service = ImportParserService(session, storage=LocalImportStorage(tmp_path))
    monkeypatch.setattr(
        service.repository, "get_for_account", AsyncMock(side_effect=[batch, batch])
    )
    monkeypatch.setattr(service.repository, "count_rows", AsyncMock(return_value=0))
    monkeypatch.setattr("app.modules.imports.processing.require_account_access", AsyncMock())
    if failure == "row":
        monkeypatch.setattr(service.repository, "add_row", Mock(side_effect=RuntimeError("row")))
    elif failure == "log":
        monkeypatch.setattr(service.repository, "add_log", Mock(side_effect=RuntimeError("log")))
    else:
        commit.side_effect = RuntimeError("commit")

    with pytest.raises(RuntimeError, match=failure):
        await service.parse_batch(
            principal=_principal(),
            account_id="account-a",
            batch_id="batch-a",
        )

    rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_authorization_failure_prevents_lookup_and_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    service = ImportParserService(session)
    denied = AsyncMock(side_effect=RuntimeError("denied"))
    lookup = AsyncMock(side_effect=AssertionError("batch lookup must not run"))
    storage = Mock(side_effect=AssertionError("storage must not run"))
    monkeypatch.setattr("app.modules.imports.processing.require_account_access", denied)
    monkeypatch.setattr(service.repository, "get_for_account", lookup)
    monkeypatch.setattr(service, "_load_verified_file", storage)

    with pytest.raises(RuntimeError, match="denied"):
        await service.parse_batch(
            principal=_principal(),
            account_id="account-a",
            batch_id="batch-a",
        )

    lookup.assert_not_awaited()
    storage.assert_not_called()


@pytest.mark.asyncio
async def test_fatal_failure_log_error_rolls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    batch = _batch(b"a,b\n1,2\n")
    session = cast(AsyncSession, AsyncMock(spec=AsyncSession))
    rollback = cast(AsyncMock, session.rollback)
    service = ImportParserService(session)
    monkeypatch.setattr(service.repository, "get_for_account", AsyncMock(return_value=batch))
    monkeypatch.setattr(
        service.repository,
        "add_log",
        Mock(side_effect=RuntimeError("fatal log")),
    )

    with pytest.raises(RuntimeError, match="fatal log"):
        await service._record_fatal_failure(
            account_id="account-a",
            batch_id="batch-a",
            message="controlled failure",
        )

    rollback.assert_awaited_once()
