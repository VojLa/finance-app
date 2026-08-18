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
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.background_jobs import BackgroundJobModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    BackgroundJobKind,
    BackgroundJobStatus,
    ImportLogEvent,
    ImportLogLevel,
    ImportStatus,
)
from app.db.models.imports import ImportBatchModel, ImportLogModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.imports.models import ImportBatchCreateRequest, ImportBatchResponse
from app.modules.imports.service import ImportBatchService
from app.modules.imports.storage import LocalImportStorage

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "step-5a-internal-auth-secret-32-characters"
USERS = ["user-owner", "user-admin", "user-editor", "user-viewer", "user-foreign"]
ACCOUNTS = ["account-active", "account-secondary", "account-foreign", "account-archived"]

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


def _payload(checksum_character: str, *, filename: str = "transactions.csv") -> dict[str, object]:
    return {
        "source": "raiffeisenbank",
        "filename": filename,
        "file_size": 18422,
        "file_encoding": " UTF-8 ",
        "checksum": checksum_character * 64,
    }


async def _seed() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        await session.execute(delete(BackgroundJobModel))
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
                    password_hash="must-not-leak" if user_id == "user-admin" else None,
                    base_currency="CZK",
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()
        for account_id, archived in [
            ("account-active", False),
            ("account-secondary", False),
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
            ("member-secondary", "user-owner", "account-secondary", AccountMemberRole.owner),
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
        await session.commit()
    await engine.dispose()


async def _batch(batch_id: str) -> ImportBatchModel | None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        value = await session.get(ImportBatchModel, batch_id)
        if value is not None:
            session.expunge(value)
    await engine.dispose()
    return value


async def _counts(*, user_id: str, account_id: str, checksum: str) -> tuple[int, int]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        batch_ids = select(ImportBatchModel.id).where(
            ImportBatchModel.user_id == user_id,
            ImportBatchModel.account_id == account_id,
            ImportBatchModel.checksum == checksum,
        )
        batches = await session.scalar(select(func.count()).select_from(batch_ids.subquery()))
        logs = await session.scalar(
            select(func.count())
            .select_from(ImportLogModel)
            .where(ImportLogModel.import_batch_id.in_(batch_ids))
        )
    await engine.dispose()
    return int(batches or 0), int(logs or 0)


async def _set_batch_status(batch_id: str, status: ImportStatus) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        batch = await session.get(ImportBatchModel, batch_id)
        assert batch is not None
        batch.status = status
        if status in {ImportStatus.completed, ImportStatus.partially_completed}:
            batch.rows_total = 2
            batch.rows_imported = 1
            batch.rows_skipped = 1
            batch.completed_at = datetime.now(UTC).replace(tzinfo=None)
        else:
            batch.rows_total = 0
            batch.rows_imported = 0
            batch.rows_skipped = 0
            batch.completed_at = None
        await session.commit()
    await engine.dispose()


async def _insert_import_job(
    *,
    job_id: str,
    user_id: str,
    batch_id: str,
    status: BackgroundJobStatus,
    payload: dict[str, object] | None = None,
) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        session.add(
            BackgroundJobModel(
                id=job_id,
                user_id=user_id,
                account_id="account-active",
                kind=BackgroundJobKind.import_workflow,
                status=status,
                idempotency_key=f"test-registration-{job_id}",
                payload=payload or {"schema_version": 1, "batch_ids": [batch_id]},
                checkpoint={"schema_version": 1, "phase": "queued", "completed_batch_ids": []},
                progress={
                    "schema_version": 1,
                    "phase": "queued",
                    "completed_units": 0,
                    "total_units": 7,
                    "completed_batches": 0,
                    "total_batches": 1,
                },
                result=(
                    {
                        "schema_version": 1,
                        "batch_ids": [batch_id],
                        "rows_total": 1,
                        "rows_imported": 1,
                        "rows_skipped": 0,
                        "snapshot_refresh_status": "created",
                        "completed_at": now.isoformat(),
                    }
                    if status is BackgroundJobStatus.completed
                    else None
                ),
                error_code="import_failed" if status is BackgroundJobStatus.failed else None,
                error_message=(
                    "Import processing failed safely."
                    if status is BackgroundJobStatus.failed
                    else None
                ),
                attempt_count=1,
                max_attempts=5,
                manual_retry_count=0,
                run_after=now,
                lease_owner=None,
                lease_version=0,
                lease_expires_at=None,
                lease_heartbeat_at=None,
                started_at=(
                    now
                    if status in {BackgroundJobStatus.completed, BackgroundJobStatus.failed}
                    else None
                ),
                finished_at=(
                    now
                    if status in {BackgroundJobStatus.completed, BackgroundJobStatus.failed}
                    else None
                ),
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    await engine.dispose()


async def _replay_state(*, batch_id: str) -> tuple[int, int, int, int, int]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        batches = await session.scalar(
            select(func.count())
            .select_from(ImportBatchModel)
            .where(ImportBatchModel.id == batch_id)
        )
        logs = await session.scalar(
            select(func.count())
            .select_from(ImportLogModel)
            .where(ImportLogModel.import_batch_id == batch_id)
        )
        rows = await session.scalar(
            select(func.count())
            .select_from(ImportRowModel)
            .where(ImportRowModel.import_batch_id == batch_id)
        )
        transactions = await session.scalar(
            select(func.count())
            .select_from(TransactionModel)
            .where(TransactionModel.import_batch_id == batch_id)
        )
        events = await session.scalar(
            select(func.count())
            .select_from(InvestmentEventModel)
            .where(InvestmentEventModel.import_batch_id == batch_id)
        )
    await engine.dispose()
    return (
        int(batches or 0),
        int(logs or 0),
        int(rows or 0),
        int(transactions or 0),
        int(events or 0),
    )


async def _logs(batch_id: str) -> list[ImportLogModel]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        result = await session.scalars(
            select(ImportLogModel).where(ImportLogModel.import_batch_id == batch_id)
        )
        values = list(result.all())
        for value in values:
            session.expunge(value)
    await engine.dispose()
    return values


async def _verify_atomic_rollbacks() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    principal = AuthenticatedPrincipal(
        user_id="user-owner", email="user-owner@example.com", name="Owner"
    )

    async def attempt(checksum: str, failure: str) -> None:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            service = ImportBatchService(session)
            rollback = AsyncMock(wraps=session.rollback)
            if failure == "log":
                with (
                    patch.object(
                        service.repository,
                        "add_log",
                        side_effect=RuntimeError("controlled log failure"),
                    ),
                    patch.object(session, "rollback", rollback),
                    pytest.raises(RuntimeError),
                ):
                    await service.create_batch(
                        principal=principal,
                        account_id="account-active",
                        payload=ImportBatchCreateRequest.model_validate(_payload(checksum)),
                    )
            else:
                with (
                    patch.object(
                        session,
                        "commit",
                        AsyncMock(side_effect=RuntimeError("controlled commit failure")),
                    ),
                    patch.object(session, "rollback", rollback),
                    pytest.raises(RuntimeError),
                ):
                    await service.create_batch(
                        principal=principal,
                        account_id="account-active",
                        payload=ImportBatchCreateRequest.model_validate(_payload(checksum)),
                    )
            rollback.assert_awaited_once()
        assert await _counts(
            user_id="user-owner", account_id="account-active", checksum=checksum * 64
        ) == (0, 0)

    await attempt("8", "log")
    await attempt("9", "commit")
    await engine.dispose()


async def _concurrent_create() -> list[object]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    principal = AuthenticatedPrincipal(
        user_id="user-owner", email="user-owner@example.com", name="Owner"
    )
    payload = ImportBatchCreateRequest.model_validate(_payload("7"))

    async def create() -> object:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            return await ImportBatchService(session).create_batch(
                principal=principal,
                account_id="account-active",
                payload=payload,
            )

    results = await asyncio.gather(create(), create(), return_exceptions=True)
    await engine.dispose()
    return list(results)


def test_import_batch_workflow_against_postgresql() -> None:
    _run(_seed())
    _run(_verify_atomic_rollbacks())
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
    with TestClient(app, raise_server_exceptions=False) as client:
        owner = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=_payload("a", filename="  transactions.csv  "),
        )
        assert owner.status_code == 201
        owner_response = owner.json()
        assert owner_response["status"] == "upload_required"
        assert owner_response["job"] is None
        owner_body = owner_response["batch"]
        assert owner_body is not None
        assert "user_id" not in owner_body
        assert owner_body["status"] == "pending"
        assert owner_body["filename"] == "transactions.csv"
        assert owner_body["file_encoding"] == "utf-8"
        persisted = _run(_batch(owner_body["id"]))
        assert persisted is not None
        assert persisted.user_id == "user-owner"
        assert persisted.account_id == "account-active"
        assert persisted.status is ImportStatus.pending
        assert persisted.rows_total is None
        assert persisted.rows_imported is None
        assert persisted.rows_skipped is None
        assert persisted.completed_at is None
        logs = _run(_logs(persisted.id))
        assert len(logs) == 1
        assert logs[0].level is ImportLogLevel.info
        assert logs[0].event is ImportLogEvent.started
        assert logs[0].message == "Import batch registered and awaiting processing."

        role_results = {}
        for user_id, checksum in [("user-admin", "b"), ("user-editor", "c")]:
            response = client.post(
                "/api/v1/accounts/account-active/imports",
                headers=_headers(user_id),
                json=_payload(checksum),
            )
            role_results[user_id] = response
            assert response.status_code == 201
        viewer = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-viewer"),
            json=_payload("d"),
        )
        assert viewer.status_code == 403
        assert viewer.json()["error"]["code"] == "account_access_denied"

        duplicate = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=_payload("a"),
        )
        assert duplicate.status_code == 201
        assert duplicate.json() == owner_response
        assert _run(
            _counts(user_id="user-owner", account_id="account-active", checksum="a" * 64)
        ) == (1, 1)

        different_user = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-admin"),
            json=_payload("a"),
        )
        assert different_user.status_code == 201
        different_account = client.post(
            "/api/v1/accounts/account-secondary/imports",
            headers=_headers("user-owner"),
            json=_payload("a"),
        )
        assert different_account.status_code == 201

        foreign_created = client.post(
            "/api/v1/accounts/account-foreign/imports",
            headers=_headers("user-foreign"),
            json=_payload("f"),
        )
        assert foreign_created.status_code == 201
        foreign_id = foreign_created.json()["batch"]["id"]

        for user_id in ["user-owner", "user-admin", "user-editor", "user-viewer"]:
            listing = client.get(
                "/api/v1/accounts/account-active/imports", headers=_headers(user_id)
            )
            assert listing.status_code == 200
            assert all(item["account_id"] == "account-active" for item in listing.json())
            assert foreign_id not in {item["id"] for item in listing.json()}
            persisted_rows = [_run(_batch(item["id"])) for item in listing.json()]
            ordering = [(row.created_at, row.id) for row in persisted_rows if row is not None]
            assert ordering == sorted(ordering, reverse=True)

        own_detail = client.get(
            f"/api/v1/accounts/account-active/imports/{owner_body['id']}",
            headers=_headers("user-viewer"),
        )
        assert own_detail.status_code == 200
        cross_detail = client.get(
            f"/api/v1/accounts/account-active/imports/{foreign_id}",
            headers=_headers("user-owner"),
        )
        assert cross_detail.status_code == 404
        assert cross_detail.json()["error"]["code"] == "import_batch_not_found"

        for account_id in ["missing-account", "account-foreign", "account-archived"]:
            hidden = client.get(
                f"/api/v1/accounts/{account_id}/imports",
                headers=_headers("user-owner"),
            )
            assert hidden.status_code == 404
            assert hidden.json()["error"]["code"] == "account_not_found"

        rejected_before = _run(
            _counts(user_id="user-viewer", account_id="account-active", checksum="d" * 64)
        )
        assert rejected_before == (0, 0)


def test_concurrent_duplicate_registration_is_controlled() -> None:
    _run(_seed())
    results = _run(_concurrent_create())
    successes = [result for result in results if isinstance(result, ImportBatchResponse)]
    assert len(successes) == 2
    assert {result.id for result in successes} == {successes[0].id}
    assert _run(_counts(user_id="user-owner", account_id="account-active", checksum="7" * 64)) == (
        1,
        1,
    )


@pytest.mark.parametrize(
    "terminal_status",
    [ImportStatus.completed, ImportStatus.partially_completed],
)
def test_exact_terminal_registration_returns_safe_conflict_without_mutation(
    terminal_status: ImportStatus,
) -> None:
    _run(_seed())
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
    payload = _payload("e" if terminal_status is ImportStatus.completed else "f")
    with TestClient(app, raise_server_exceptions=False) as client:
        created = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=payload,
        )
        assert created.status_code == 201
        batch_id = created.json()["batch"]["id"]
        _run(_set_batch_status(batch_id, terminal_status))
        before = _run(_replay_state(batch_id=batch_id))

        replay = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=payload,
        )
        mismatch = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=payload | {"filename": "different.csv"},
        )

    assert replay.status_code == 409
    assert {key: value for key, value in replay.json()["error"].items() if key != "request_id"} == {
        "code": "import_batch_already_imported",
        "message": "This import file has already been processed.",
    }
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "import_batch_exists"
    assert _run(_replay_state(batch_id=batch_id)) == before == (1, 1, 0, 0, 0)


def test_exact_processing_registration_reuses_the_canonical_batch_without_mutation() -> None:
    _run(_seed())
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
    payload = _payload("e")
    with TestClient(app, raise_server_exceptions=False) as client:
        created = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=payload,
        )
        assert created.status_code == 201
        batch_id = created.json()["batch"]["id"]
        _run(_set_batch_status(batch_id, ImportStatus.processing))
        before = _run(_replay_state(batch_id=batch_id))

        replay = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=payload,
        )

    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == "import_batch_not_reusable"
    assert _run(_replay_state(batch_id=batch_id)) == before == (1, 1, 0, 0, 0)


def test_job_aware_registration_recovery_fails_closed_on_real_postgresql() -> None:
    """Registration is the only public recovery decision point for one batch."""

    _run(_seed())
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

    def register(client: TestClient, checksum: str) -> tuple[dict[str, object], str]:
        payload = _payload(checksum, filename=f"recovery-{checksum}.csv")
        response = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=payload,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "upload_required"
        assert body["job"] is None
        assert body["batch"] is not None
        return payload, str(body["batch"]["id"])

    with TestClient(app, raise_server_exceptions=False) as client:
        failed_payload, failed_batch_id = register(client, "a")
        _run(_set_batch_status(failed_batch_id, ImportStatus.completed))
        _run(
            _insert_import_job(
                job_id="registration-failed-job",
                user_id="user-owner",
                batch_id=failed_batch_id,
                status=BackgroundJobStatus.failed,
            )
        )
        failed_replay = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=failed_payload,
        )
        assert failed_replay.status_code == 201
        assert failed_replay.json()["status"] == "resume_job"
        assert failed_replay.json()["batch"] is None
        assert failed_replay.json()["job"]["id"] == "registration-failed-job"
        assert not {"payload", "checkpoint", "lease_owner"} & failed_replay.json()["job"].keys()

        completed_payload, completed_batch_id = register(client, "b")
        _run(_set_batch_status(completed_batch_id, ImportStatus.completed))
        _run(
            _insert_import_job(
                job_id="registration-completed-job",
                user_id="user-owner",
                batch_id=completed_batch_id,
                status=BackgroundJobStatus.completed,
            )
        )
        completed_replay = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=completed_payload,
        )
        assert completed_replay.status_code == 409
        assert completed_replay.json()["error"]["code"] == "import_batch_already_imported"

        legacy_payload, legacy_batch_id = register(client, "c")
        _run(_set_batch_status(legacy_batch_id, ImportStatus.partially_completed))
        legacy_replay = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=legacy_payload,
        )
        assert legacy_replay.status_code == 409
        assert legacy_replay.json()["error"]["code"] == "import_batch_already_imported"

        pending_payload, pending_batch_id = register(client, "d")
        _run(_set_batch_status(pending_batch_id, ImportStatus.processing))
        processing_replay = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=pending_payload,
        )
        assert processing_replay.status_code == 409
        assert processing_replay.json()["error"]["code"] == "import_batch_not_reusable"

        corrupt_payload, corrupt_batch_id = register(client, "e")
        _run(_set_batch_status(corrupt_batch_id, ImportStatus.processing))
        _run(
            _insert_import_job(
                job_id="registration-corrupt-job",
                user_id="user-owner",
                batch_id=corrupt_batch_id,
                status=BackgroundJobStatus.queued,
                payload={"batch_ids": [corrupt_batch_id]},
            )
        )
        corrupt_replay = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=corrupt_payload,
        )
        assert corrupt_replay.status_code == 409
        assert corrupt_replay.json()["error"]["code"] == "import_batch_not_reusable"

        multiple_payload, multiple_batch_id = register(client, "f")
        _run(_set_batch_status(multiple_batch_id, ImportStatus.processing))
        for suffix in ("one", "two"):
            _run(
                _insert_import_job(
                    job_id=f"registration-multiple-{suffix}",
                    user_id="user-owner",
                    batch_id=multiple_batch_id,
                    status=BackgroundJobStatus.queued,
                )
            )
        multiple_replay = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=multiple_payload,
        )
        assert multiple_replay.status_code == 409
        assert multiple_replay.json()["error"]["code"] == "import_batch_not_reusable"

        foreign_payload, foreign_batch_id = register(client, "0")
        _run(_set_batch_status(foreign_batch_id, ImportStatus.processing))
        _run(
            _insert_import_job(
                job_id="registration-foreign-job",
                user_id="user-admin",
                batch_id=foreign_batch_id,
                status=BackgroundJobStatus.queued,
            )
        )
        foreign_replay = client.post(
            "/api/v1/accounts/account-active/imports",
            headers=_headers("user-owner"),
            json=foreign_payload,
        )
        assert foreign_replay.status_code == 409
        assert foreign_replay.json()["error"]["code"] == "import_batch_not_reusable"


def test_lost_registration_response_reuses_batch_for_upload_and_one_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _run(_seed())
    content = b"durable registration replay\n"
    checksum = hashlib.sha256(content).hexdigest()
    payload = {
        "source": "raiffeisenbank",
        "filename": "durable.csv",
        "file_size": len(content),
        "file_encoding": "utf-8",
        "checksum": checksum,
    }
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
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            first = client.post(
                "/api/v1/accounts/account-active/imports",
                headers=_headers("user-owner"),
                json=payload,
            )
            retry = client.post(
                "/api/v1/accounts/account-active/imports",
                headers=_headers("user-owner"),
                json=payload,
            )
            assert first.status_code == retry.status_code == 201
            assert first.json() == retry.json()
            assert first.json()["status"] == "upload_required"
            batch_id = first.json()["batch"]["id"]

            upload = client.put(
                f"/api/v1/accounts/account-active/imports/{batch_id}/file",
                headers={**_headers("user-owner"), "Content-Type": "application/octet-stream"},
                content=content,
            )
            assert upload.status_code == 200
            assert upload.json()["idempotent"] is False
            upload_replay = client.put(
                f"/api/v1/accounts/account-active/imports/{batch_id}/file",
                headers={**_headers("user-owner"), "Content-Type": "application/octet-stream"},
                content=content,
            )
            assert upload_replay.status_code == 200
            assert upload_replay.json()["idempotent"] is True
            assert storage.path_for(batch_id).read_bytes() == content

            first_job = client.post(
                "/api/v1/accounts/account-active/imports/jobs",
                headers=_headers("user-owner"),
                json={"batch_ids": [batch_id]},
            )
            replay_job = client.post(
                "/api/v1/accounts/account-active/imports/jobs",
                headers=_headers("user-owner"),
                json={"batch_ids": [batch_id]},
            )
            assert first_job.status_code == replay_job.status_code == 202
            assert first_job.json()["id"] == replay_job.json()["id"]

        async def counts() -> tuple[int, int, int, int, int, int]:
            assert DATABASE_URL is not None
            engine = create_async_engine(normalize_database_url(DATABASE_URL))
            async with AsyncSession(engine) as session:
                batches = await session.scalar(
                    select(func.count())
                    .select_from(ImportBatchModel)
                    .where(ImportBatchModel.id == batch_id)
                )
                logs = await session.scalar(
                    select(func.count())
                    .select_from(ImportLogModel)
                    .where(ImportLogModel.import_batch_id == batch_id)
                )
                jobs = await session.scalar(
                    select(func.count())
                    .select_from(BackgroundJobModel)
                    .where(BackgroundJobModel.id == first_job.json()["id"])
                )
                raw_rows = await session.scalar(
                    select(func.count())
                    .select_from(ImportRowModel)
                    .where(ImportRowModel.import_batch_id == batch_id)
                )
                transactions = await session.scalar(
                    select(func.count())
                    .select_from(TransactionModel)
                    .where(TransactionModel.import_batch_id == batch_id)
                )
                investment_events = await session.scalar(
                    select(func.count())
                    .select_from(InvestmentEventModel)
                    .where(InvestmentEventModel.import_batch_id == batch_id)
                )
            await engine.dispose()
            return (
                int(batches or 0),
                int(logs or 0),
                int(jobs or 0),
                int(raw_rows or 0),
                int(transactions or 0),
                int(investment_events or 0),
            )

        assert _run(counts()) == (1, 1, 1, 0, 0, 0)
    finally:
        storage.remove(batch_id) if "batch_id" in locals() else None
