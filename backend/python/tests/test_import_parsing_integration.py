from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

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
    ImportRowStatus,
    ImportSource,
    ImportStatus,
)
from app.db.models.imports import ImportBatchModel, ImportLogModel, ImportRowModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.imports.processing import (
    PARSER_MAX_BYTES,
    ImportParserService,
    ImportParseStateError,
)
from app.modules.imports.storage import LocalImportStorage

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "step-5c-internal-auth-secret-32-characters"
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


def _headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.com",
        name=user_id,
    )


async def _seed(storage: LocalImportStorage) -> dict[str, bytes]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)

    def valid(label: str) -> bytes:
        return (f"Date,Description,Amount,Currency\n2026-01-01,{label},1000.00,CZK\n").encode()

    malformed = b"a,b,c\n1,2,3\n\n4,5,6,7\n8,9\n"
    contents = {
        "batch-owner": valid("Salary"),
        "batch-admin": valid("Admin"),
        "batch-editor": valid("Editor"),
        "batch-viewer": valid("Viewer"),
        "batch-foreign": valid("Foreign"),
        "batch-archived": valid("Archived"),
        "batch-malformed": malformed,
        "batch-missing": valid("Missing"),
        "batch-modified": valid("Modified"),
        "batch-unknown-codec": valid("UnknownCodec"),
        "batch-undecodable": b"a,b\n\xff,2\n",
        "batch-empty": b"",
        "batch-header-only": b"a,b\n",
        "batch-invalid-header": b"a,a\n1,2\n",
        "batch-oversized": b"oversized-metadata",
        "batch-concurrent": valid("Concurrent"),
        "batch-rollback": b"a,b\n1,2\n3,4\n",
    }
    async with AsyncSession(engine) as session:
        await session.execute(delete(ImportRowModel))
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
        memberships = [
            ("member-owner", "user-owner", "account-active", AccountMemberRole.owner),
            ("member-admin", "user-admin", "account-active", AccountMemberRole.admin),
            ("member-editor", "user-editor", "account-active", AccountMemberRole.editor),
            ("member-viewer", "user-viewer", "account-active", AccountMemberRole.viewer),
            ("member-foreign", "user-foreign", "account-foreign", AccountMemberRole.owner),
            ("member-archived", "user-owner", "account-archived", AccountMemberRole.owner),
        ]
        for index, (member_id, user_id, account_id, role) in enumerate(memberships):
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
        for batch_id, content in contents.items():
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
                    source=ImportSource.manual,
                    filename="fixture.csv",
                    file_size=(
                        PARSER_MAX_BYTES + 1 if batch_id == "batch-oversized" else len(content)
                    ),
                    file_encoding=("not-a-codec" if batch_id == "batch-unknown-codec" else "utf-8"),
                    checksum=(
                        hashlib.sha256(batch_id.encode()).hexdigest()
                        if batch_id == "batch-oversized"
                        else hashlib.sha256(content).hexdigest()
                    ),
                    status=ImportStatus.pending,
                    rows_total=None,
                    rows_imported=None,
                    rows_skipped=None,
                    created_at=now,
                    completed_at=None,
                    retain_until=None,
                    raw_data_purged_at=None,
                )
            )
        await session.commit()
    await engine.dispose()

    for batch_id, content in contents.items():
        if batch_id != "batch-missing":
            path = storage.path_for(batch_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            if batch_id == "batch-oversized":
                with path.open("wb") as oversized:
                    oversized.truncate(PARSER_MAX_BYTES + 1)
            else:
                path.write_bytes(b"X" * len(content) if batch_id == "batch-modified" else content)
    return contents


async def _batch_state(batch_id: str) -> tuple[ImportStatus, int, int, int]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        batch = await session.get(ImportBatchModel, batch_id)
        assert batch is not None
        row_count = await session.scalar(
            select(func.count())
            .select_from(ImportRowModel)
            .where(ImportRowModel.import_batch_id == batch_id)
        )
        log_count = await session.scalar(
            select(func.count())
            .select_from(ImportLogModel)
            .where(ImportLogModel.import_batch_id == batch_id)
        )
        result = (
            batch.status,
            int(batch.rows_total or 0),
            int(row_count or 0),
            int(log_count or 0),
        )
    await engine.dispose()
    return result


async def _concurrent_parse(storage: LocalImportStorage) -> list[object]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL), pool_size=2)

    async def parse_once() -> object:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            service = ImportParserService(session, storage=storage)
            try:
                return await service.parse_batch(
                    principal=_principal("user-owner"),
                    account_id="account-active",
                    batch_id="batch-concurrent",
                )
            except Exception as exc:  # returned for controlled-result assertions
                return exc

    results = await asyncio.gather(parse_once(), parse_once())
    await engine.dispose()
    return list(results)


async def _rollback_then_retry(storage: LocalImportStorage) -> tuple[int, int]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service = ImportParserService(session, storage=storage)
        original = service.repository.add_row
        calls = 0

        def fail_on_second(row: ImportRowModel) -> None:
            nonlocal calls
            calls += 1
            original(row)
            if calls == 2:
                raise RuntimeError("controlled row persistence failure")

        with (
            patch.object(service.repository, "add_row", side_effect=fail_on_second),
            pytest.raises(RuntimeError, match="controlled row persistence failure"),
        ):
            await service.parse_batch(
                principal=_principal("user-owner"),
                account_id="account-active",
                batch_id="batch-rollback",
            )

    async with AsyncSession(engine) as session:
        after_failure = int(
            await session.scalar(
                select(func.count())
                .select_from(ImportRowModel)
                .where(ImportRowModel.import_batch_id == "batch-rollback")
            )
            or 0
        )
        service = ImportParserService(session, storage=storage)
        response = await service.parse_batch(
            principal=_principal("user-owner"),
            account_id="account-active",
            batch_id="batch-rollback",
        )
        after_retry = response.rows_total
    await engine.dispose()
    return after_failure, after_retry


def test_parser_orchestration_against_postgresql(tmp_path: Path) -> None:
    assert DATABASE_URL is not None
    storage = LocalImportStorage(tmp_path)
    _run(_seed(storage))
    settings = Settings(
        environment="test",
        database_url=DATABASE_URL,
        log_level="ERROR",
        log_json=False,
        docs_enabled=True,
        internal_auth_secret=SECRET,
        _env_file=None,
    )

    os.environ["IMPORT_STORAGE_ROOT"] = str(tmp_path)
    with TestClient(create_app(settings)) as client:
        for user_id, batch_id in [
            ("user-owner", "batch-owner"),
            ("user-admin", "batch-admin"),
            ("user-editor", "batch-editor"),
        ]:
            response = client.post(
                f"/api/v1/accounts/account-active/imports/{batch_id}/parse",
                headers=_headers(user_id),
            )
            assert response.status_code == 200
            assert response.json()["status"] == "processing"

        viewer = client.post(
            "/api/v1/accounts/account-active/imports/batch-viewer/parse",
            headers=_headers("user-viewer"),
        )
        foreign = client.post(
            "/api/v1/accounts/account-foreign/imports/batch-foreign/parse",
            headers=_headers("user-owner"),
        )
        archived = client.post(
            "/api/v1/accounts/account-archived/imports/batch-archived/parse",
            headers=_headers("user-owner"),
        )
        cross_account = client.post(
            "/api/v1/accounts/account-active/imports/batch-foreign/parse",
            headers=_headers("user-owner"),
        )
        assert viewer.status_code == 403
        assert viewer.json()["error"]["code"] == "account_access_denied"
        for response, code in [
            (foreign, "account_not_found"),
            (archived, "account_not_found"),
            (cross_account, "import_batch_not_found"),
        ]:
            assert response.status_code == 404
            assert response.json()["error"]["code"] == code

        malformed = client.post(
            "/api/v1/accounts/account-active/imports/batch-malformed/parse",
            headers=_headers("user-owner"),
        )
        assert malformed.status_code == 200
        assert malformed.json() == {
            "batch_id": "batch-malformed",
            "status": "processing",
            "rows_total": 4,
            "rows_pending": 1,
            "rows_failed": 3,
        }

        missing = client.post(
            "/api/v1/accounts/account-active/imports/batch-missing/parse",
            headers=_headers("user-owner"),
        )
        modified = client.post(
            "/api/v1/accounts/account-active/imports/batch-modified/parse",
            headers=_headers("user-owner"),
        )
        assert missing.status_code == 409
        assert missing.json()["error"]["code"] == "import_file_missing"
        assert modified.status_code == 409
        assert modified.json()["error"]["code"] == "import_file_invalid"

        fatal_cases = [
            ("batch-unknown-codec", 422, "import_parse_failed"),
            ("batch-undecodable", 422, "import_parse_failed"),
            ("batch-empty", 422, "import_parse_failed"),
            ("batch-header-only", 422, "import_parse_failed"),
            ("batch-invalid-header", 422, "import_parse_failed"),
            ("batch-oversized", 413, "import_parse_file_too_large"),
        ]
        for batch_id, status_code, error_code in fatal_cases:
            response = client.post(
                f"/api/v1/accounts/account-active/imports/{batch_id}/parse",
                headers=_headers("user-owner"),
            )
            assert response.status_code == status_code
            assert response.json()["error"]["code"] == error_code

        second = client.post(
            "/api/v1/accounts/account-active/imports/batch-owner/parse",
            headers=_headers("user-owner"),
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "import_parse_state_invalid"

    async def assert_rows() -> None:
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            valid_rows = list(
                (
                    await session.scalars(
                        select(ImportRowModel)
                        .where(ImportRowModel.import_batch_id == "batch-owner")
                        .order_by(ImportRowModel.row_number)
                    )
                ).all()
            )
            assert len(valid_rows) == 1
            assert valid_rows[0].raw_data == {
                "Date": "2026-01-01",
                "Description": "Salary",
                "Amount": "1000.00",
                "Currency": "CZK",
            }
            assert valid_rows[0].normalized_data is None
            assert valid_rows[0].deduplication_key is None
            assert valid_rows[0].created_transaction_id is None
            assert valid_rows[0].created_investment_event_id is None

            malformed_rows = list(
                (
                    await session.scalars(
                        select(ImportRowModel)
                        .where(ImportRowModel.import_batch_id == "batch-malformed")
                        .order_by(ImportRowModel.row_number)
                    )
                ).all()
            )
            assert [row.row_number for row in malformed_rows] == [2, 3, 4, 5]
            assert [row.status for row in malformed_rows] == [
                ImportRowStatus.pending,
                ImportRowStatus.failed,
                ImportRowStatus.failed,
                ImportRowStatus.failed,
            ]
            assert all(row.validation_errors for row in malformed_rows[1:])
        await engine.dispose()

    _run(assert_rows())
    assert _run(_batch_state("batch-viewer")) == (ImportStatus.pending, 0, 0, 0)
    assert _run(_batch_state("batch-missing")) == (ImportStatus.failed, 0, 0, 1)
    assert _run(_batch_state("batch-modified")) == (ImportStatus.failed, 0, 0, 1)
    for batch_id in [
        "batch-unknown-codec",
        "batch-undecodable",
        "batch-empty",
        "batch-header-only",
        "batch-invalid-header",
        "batch-oversized",
    ]:
        assert _run(_batch_state(batch_id)) == (ImportStatus.failed, 0, 0, 1)

    concurrent = _run(_concurrent_parse(storage))
    assert sum(not isinstance(result, Exception) for result in concurrent) == 1
    assert sum(isinstance(result, ImportParseStateError) for result in concurrent) == 1
    assert _run(_batch_state("batch-concurrent")) == (ImportStatus.processing, 1, 1, 0)

    assert _run(_rollback_then_retry(storage)) == (0, 2)
    assert _run(_batch_state("batch-rollback")) == (ImportStatus.processing, 2, 2, 0)
