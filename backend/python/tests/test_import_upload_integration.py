import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import AsyncIterator, Coroutine
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    ImportSource,
    ImportStatus,
)
from app.db.models.imports import ImportBatchModel, ImportLogModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.imports.service import ImportBatchService, ImportUploadMismatchError
from app.modules.imports.storage import LocalImportStorage

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "step-5b-internal-auth-secret-32-characters"
USERS = ["user-owner", "user-admin", "user-editor", "user-viewer", "user-foreign"]
ACCOUNTS = ["account-active", "account-foreign", "account-archived"]

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _encode(value: object) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )


def _token(user_id: str) -> str:
    now = int(time.time())
    header = _encode({"alg": "HS256", "typ": "JWT"})
    payload = _encode(
        {
            "sub": user_id,
            "iss": "finance-app-next",
            "aud": "finance-app-python",
            "iat": now,
            "exp": now + 300,
        }
    )
    signature = hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _headers(user_id: str, content_type: str = "application/octet-stream") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}", "Content-Type": content_type}


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


async def _seed() -> dict[str, bytes]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    batches = {
        "batch-owner": b"owner raw import\n",
        "batch-admin": b"admin raw import\n",
        "batch-editor": b"editor raw import\n",
        "batch-viewer": b"viewer raw import\n",
        "batch-foreign": b"foreign raw import\n",
        "batch-archived": b"archived raw import\n",
        "batch-completed": b"completed raw import\n",
        "batch-wrong": b"registered bytes",
        "batch-short": b"registered longer bytes",
        "batch-long": b"abc",
        "batch-empty": b"",
        "batch-unknown": b"unknown sized import",
        "batch-concurrent": b"concurrent verified bytes",
    }
    async with AsyncSession(engine) as session:
        await session.execute(delete(ImportLogModel))
        await session.execute(delete(ImportBatchModel))
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(ACCOUNTS))
        )
        await session.execute(delete(AccountModel).where(AccountModel.id.in_(ACCOUNTS)))
        await session.execute(delete(UserModel).where(UserModel.id.in_(USERS)))
        for user_id in USERS:
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{user_id}@example.com",
                    name=user_id,
                    password_hash=None,
                    base_currency="CZK",
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()
        for account_id, archived in [
            ("account-active", False),
            ("account-foreign", False),
            ("account-archived", True),
        ]:
            session.add(
                AccountModel(
                    id=account_id,
                    name=account_id,
                    type=AccountType.bank,
                    currency="CZK",
                    color=None,
                    notes=None,
                    is_archived=archived,
                    archived_at=now if archived else None,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()
        for index, (member_id, user_id, account_id, role) in enumerate(
            [
                ("member-owner", "user-owner", "account-active", AccountMemberRole.owner),
                ("member-admin", "user-admin", "account-active", AccountMemberRole.admin),
                ("member-editor", "user-editor", "account-active", AccountMemberRole.editor),
                ("member-viewer", "user-viewer", "account-active", AccountMemberRole.viewer),
                ("member-foreign", "user-foreign", "account-foreign", AccountMemberRole.owner),
                ("member-archived", "user-owner", "account-archived", AccountMemberRole.owner),
            ]
        ):
            timestamp = now + timedelta(milliseconds=index)
            session.add(
                AccountMemberModel(
                    id=member_id,
                    account_id=account_id,
                    user_id=user_id,
                    role=role,
                    relation_type=AccountRelationType.owner,
                    invited_by_id=None,
                    accepted_at=timestamp,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        await session.flush()
        for batch_id, content in batches.items():
            if batch_id == "batch-foreign":
                account_id, user_id = "account-foreign", "user-foreign"
            elif batch_id == "batch-archived":
                account_id, user_id = "account-archived", "user-owner"
            else:
                account_id, user_id = "account-active", "user-owner"
            session.add(
                ImportBatchModel(
                    id=batch_id,
                    user_id=user_id,
                    account_id=account_id,
                    source=ImportSource.raiffeisenbank,
                    filename="fixture.csv",
                    file_size=None if batch_id == "batch-unknown" else len(content),
                    file_encoding="utf-8",
                    checksum=_digest(content),
                    status=(
                        ImportStatus.completed
                        if batch_id == "batch-completed"
                        else ImportStatus.pending
                    ),
                    rows_total=None,
                    rows_imported=None,
                    rows_skipped=None,
                    created_at=now,
                    completed_at=now if batch_id == "batch-completed" else None,
                    retain_until=None,
                    raw_data_purged_at=None,
                )
            )
        await session.commit()
    await engine.dispose()
    return batches


async def _database_state() -> tuple[dict[str, ImportStatus], int, int]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        rows = await session.execute(select(ImportBatchModel.id, ImportBatchModel.status))
        statuses: dict[str, ImportStatus] = {batch_id: status for batch_id, status in rows.tuples()}
        batches = await session.scalar(select(func.count()).select_from(ImportBatchModel))
        logs = await session.scalar(select(func.count()).select_from(ImportLogModel))
    await engine.dispose()
    return statuses, int(batches or 0), int(logs or 0)


async def _chunks(content: bytes) -> AsyncIterator[bytes]:
    midpoint = len(content) // 2
    yield content[:midpoint]
    yield b""
    yield content[midpoint:]


async def _concurrent_uploads(storage_root: Path, content: bytes) -> list[object]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    principal = AuthenticatedPrincipal(
        user_id="user-owner", email="user-owner@example.com", name="Owner"
    )

    async def upload(payload: bytes) -> object:
        async with AsyncSession(engine) as session:
            return await ImportBatchService(
                session,
                storage=LocalImportStorage(storage_root),
            ).upload_file(
                principal=principal,
                account_id="account-active",
                batch_id="batch-concurrent",
                content_type="application/octet-stream",
                chunks=_chunks(payload),
            )

    results = await asyncio.gather(upload(content), upload(content), return_exceptions=True)
    await engine.dispose()
    return list(results)


def test_raw_upload_workflow_against_postgresql(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batches = _run(_seed())
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path))
    app = create_app(
        Settings(
            environment="test",
            database_url=DATABASE_URL,
            docs_enabled=True,
            log_level="ERROR",
            log_json=False,
            internal_auth_secret=SECRET,
            _env_file=None,
        )
    )
    storage = LocalImportStorage(tmp_path)
    initial_state = _run(_database_state())
    with TestClient(app, raise_server_exceptions=False) as client:
        for user_id, batch_id in [
            ("user-owner", "batch-owner"),
            ("user-admin", "batch-admin"),
            ("user-editor", "batch-editor"),
        ]:
            response = client.put(
                f"/api/v1/accounts/account-active/imports/{batch_id}/file",
                headers=_headers(user_id, "Application/Octet-Stream; charset=binary"),
                content=batches[batch_id],
            )
            assert response.status_code == 200
            assert response.json()["stored"] is True
            assert response.json()["idempotent"] is False
            assert response.json()["size"] == len(batches[batch_id])
            assert response.json()["checksum"] == _digest(batches[batch_id])
            assert storage.path_for(batch_id).read_bytes() == batches[batch_id]

        retry = client.put(
            "/api/v1/accounts/account-active/imports/batch-owner/file",
            headers=_headers("user-owner"),
            content=batches["batch-owner"],
        )
        assert retry.status_code == 200
        assert retry.json()["idempotent"] is True

        rejected = [
            client.put(
                "/api/v1/accounts/account-active/imports/batch-viewer/file",
                headers=_headers("user-viewer"),
                content=batches["batch-viewer"],
            ),
            client.put(
                "/api/v1/accounts/account-foreign/imports/batch-foreign/file",
                headers=_headers("user-owner"),
                content=batches["batch-foreign"],
            ),
            client.put(
                "/api/v1/accounts/account-archived/imports/batch-archived/file",
                headers=_headers("user-owner"),
                content=batches["batch-archived"],
            ),
        ]
        assert [response.status_code for response in rejected] == [403, 404, 404]
        assert not storage.path_for("batch-viewer").exists()
        assert not storage.path_for("batch-foreign").exists()
        assert not storage.path_for("batch-archived").exists()

        cross = client.put(
            "/api/v1/accounts/account-active/imports/batch-foreign/file",
            headers=_headers("user-owner"),
            content=batches["batch-foreign"],
        )
        assert cross.status_code == 404
        assert cross.json()["error"]["code"] == "import_batch_not_found"

        mismatch_cases = [
            ("batch-wrong", b"incorrect bytes!", 422, "import_upload_mismatch"),
            ("batch-short", b"short", 422, "import_upload_mismatch"),
            ("batch-long", b"abcd", 413, "import_upload_too_large"),
            ("batch-completed", batches["batch-completed"], 409, "import_upload_state_invalid"),
            ("missing-batch", b"missing", 404, "import_batch_not_found"),
        ]
        for batch_id, content, expected_status, code in mismatch_cases:
            response = client.put(
                f"/api/v1/accounts/account-active/imports/{batch_id}/file",
                headers=_headers("user-owner"),
                content=content,
            )
            assert response.status_code == expected_status
            assert response.json()["error"]["code"] == code
            assert not storage.path_for(batch_id).exists()

        wrong_type = client.put(
            "/api/v1/accounts/account-active/imports/batch-wrong/file",
            headers=_headers("user-owner", "text/csv"),
            content=batches["batch-wrong"],
        )
        assert wrong_type.status_code == 415
        assert wrong_type.json()["error"]["code"] == "import_upload_content_type_invalid"

        empty = client.put(
            "/api/v1/accounts/account-active/imports/batch-empty/file",
            headers=_headers("user-owner"),
            content=b"",
        )
        assert empty.status_code == 200
        assert empty.json()["size"] == 0
        unknown = client.put(
            "/api/v1/accounts/account-active/imports/batch-unknown/file",
            headers=_headers("user-owner"),
            content=batches["batch-unknown"],
        )
        assert unknown.status_code == 200

    assert _run(_database_state()) == initial_state
    assert not list(tmp_path.rglob("upload-*"))
    assert not list(tmp_path.rglob("publish.lock"))

    identical = _run(_concurrent_uploads(tmp_path, batches["batch-concurrent"]))
    assert len([result for result in identical if not isinstance(result, BaseException)]) == 2
    assert storage.path_for("batch-concurrent").read_bytes() == batches["batch-concurrent"]

    storage.remove("batch-concurrent")

    async def conflicting() -> list[object]:
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        principal = AuthenticatedPrincipal(
            user_id="user-owner", email="user-owner@example.com", name="Owner"
        )

        async def upload(payload: bytes) -> object:
            async with AsyncSession(engine) as session:
                return await ImportBatchService(
                    session,
                    storage=LocalImportStorage(tmp_path),
                ).upload_file(
                    principal=principal,
                    account_id="account-active",
                    batch_id="batch-concurrent",
                    content_type="application/octet-stream",
                    chunks=_chunks(payload),
                )

        results = await asyncio.gather(
            upload(batches["batch-concurrent"]),
            upload(b"invalid concurrent bytes"),
            return_exceptions=True,
        )
        await engine.dispose()
        return list(results)

    conflict_results = _run(conflicting())
    assert (
        len([result for result in conflict_results if not isinstance(result, BaseException)]) == 1
    )
    assert (
        len(
            [result for result in conflict_results if isinstance(result, ImportUploadMismatchError)]
        )
        == 1
    )
    assert storage.path_for("batch-concurrent").read_bytes() == batches["batch-concurrent"]
    assert not list(tmp_path.rglob("upload-*"))
