from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from collections.abc import Coroutine
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
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
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.imports.normalization import ImportNormalizationService, ImportNormalizeStateError

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "step-5d-internal-auth-secret-32-characters"

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _run[T](awaitable: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(awaitable)


def _encode(value: object) -> str:
    return (
        base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )


def _token(user_id: str, *, expires_in: int = 300) -> str:
    now = int(time.time())
    header = _encode({"alg": "HS256", "typ": "JWT"})
    payload = _encode(
        {
            "sub": user_id,
            "iss": "finance-app-next",
            "aud": "finance-app-python",
            "iat": now,
            "exp": now + expires_in,
        }
    )
    signature = hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def _headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(user_id)}"}


def _principal(user_id: str = "norm-owner") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=user_id, email=f"{user_id}@example.com", name=user_id)


async def _seed() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    user_ids = ["norm-owner", "norm-admin", "norm-editor", "norm-viewer", "norm-foreign"]
    account_ids = ["norm-active", "norm-foreign-account", "norm-archived"]
    batch_ids = [
        "norm-owner-batch",
        "norm-admin-batch",
        "norm-editor-batch",
        "norm-viewer-batch",
        "norm-foreign-batch",
        "norm-archived-batch",
        "norm-concurrent-batch",
        "norm-rollback-batch",
        "norm-trading212-batch",
        "norm-trading212-review-batch",
        "norm-trading212-rollback-batch",
    ]
    async with AsyncSession(engine) as session:
        await session.execute(
            delete(ImportRowModel).where(ImportRowModel.import_batch_id.in_(batch_ids))
        )
        await session.execute(delete(ImportBatchModel).where(ImportBatchModel.id.in_(batch_ids)))
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
        )
        await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        for user_id in user_ids:
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
            ("norm-active", False),
            ("norm-foreign-account", False),
            ("norm-archived", True),
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
        for member_id, user_id, account_id, role in [
            ("norm-member-owner", "norm-owner", "norm-active", AccountMemberRole.owner),
            ("norm-member-admin", "norm-admin", "norm-active", AccountMemberRole.admin),
            ("norm-member-editor", "norm-editor", "norm-active", AccountMemberRole.editor),
            ("norm-member-viewer", "norm-viewer", "norm-active", AccountMemberRole.viewer),
            (
                "norm-member-foreign",
                "norm-foreign",
                "norm-foreign-account",
                AccountMemberRole.owner,
            ),
            ("norm-member-archived", "norm-owner", "norm-archived", AccountMemberRole.owner),
        ]:
            session.add(
                AccountMemberModel(
                    id=member_id,
                    account_id=account_id,
                    user_id=user_id,
                    role=role,
                    relation_type=AccountRelationType.owner,
                    invited_by_id=None,
                    accepted_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        batches = [
            ("norm-owner-batch", "norm-active", "norm-owner"),
            ("norm-admin-batch", "norm-active", "norm-owner"),
            ("norm-editor-batch", "norm-active", "norm-owner"),
            ("norm-viewer-batch", "norm-active", "norm-owner"),
            ("norm-foreign-batch", "norm-foreign-account", "norm-foreign"),
            ("norm-archived-batch", "norm-archived", "norm-owner"),
            ("norm-concurrent-batch", "norm-active", "norm-owner"),
            ("norm-rollback-batch", "norm-active", "norm-owner"),
            ("norm-trading212-batch", "norm-active", "norm-owner"),
            ("norm-trading212-review-batch", "norm-active", "norm-owner"),
            ("norm-trading212-rollback-batch", "norm-active", "norm-owner"),
        ]
        for index, (batch_id, account_id, user_id) in enumerate(batches):
            session.add(
                ImportBatchModel(
                    id=batch_id,
                    user_id=user_id,
                    account_id=account_id,
                    source=(
                        ImportSource.trading212
                        if batch_id.startswith("norm-trading212-")
                        else ImportSource.manual
                    ),
                    filename=f"{batch_id}.csv",
                    file_size=10,
                    file_encoding="utf-8",
                    checksum=hashlib.sha256(f"{batch_id}-{index}".encode()).hexdigest(),
                    status=ImportStatus.processing,
                    rows_total=1,
                    rows_imported=0,
                    rows_skipped=0,
                    created_at=now,
                    completed_at=None,
                    retain_until=None,
                    raw_data_purged_at=None,
                )
            )
            session.add(
                ImportRowModel(
                    id=f"{batch_id}-row",
                    import_batch_id=batch_id,
                    row_number=2,
                    raw_data=(
                        {"Action": "Transfer"}
                        if batch_id == "norm-trading212-review-batch"
                        else (
                            {
                                "Action": "Market buy",
                                "Time": "2026-07-20T10:00:00Z",
                                "Ticker": "VWCE",
                                "No. of shares": "2",
                                "Total": "201",
                                "Currency (Total)": "EUR",
                                "ID": f"{batch_id}-trade",
                            }
                            if batch_id.startswith("norm-trading212-")
                            else {"Date": "2026-07-20", "Amount": "10.50", "Currency": "eur"}
                        )
                    ),
                    normalized_data=None,
                    validation_errors=None,
                    deduplication_key=None,
                    status=ImportRowStatus.pending,
                    error_message=None,
                    created_transaction_id=None,
                    created_investment_event_id=None,
                    created_at=now,
                )
            )
        owner_batch = await session.get(ImportBatchModel, "norm-owner-batch")
        assert owner_batch is not None
        owner_batch.rows_total = 4
        session.add(
            ImportRowModel(
                id="norm-owner-invalid",
                import_batch_id="norm-owner-batch",
                row_number=3,
                raw_data={"Date": "bad", "Amount": "10", "Currency": "EUR"},
                normalized_data=None,
                validation_errors=None,
                deduplication_key=None,
                status=ImportRowStatus.pending,
                error_message=None,
                created_transaction_id=None,
                created_investment_event_id=None,
                created_at=now,
            )
        )
        session.add(
            ImportRowModel(
                id="norm-owner-failed",
                import_batch_id="norm-owner-batch",
                row_number=4,
                raw_data={"parser": "unchanged"},
                normalized_data=None,
                validation_errors=[{"code": "parse"}],
                deduplication_key=None,
                status=ImportRowStatus.failed,
                error_message="Parser failure",
                created_transaction_id=None,
                created_investment_event_id=None,
                created_at=now,
            )
        )
        session.add(
            ImportRowModel(
                id="norm-owner-currency",
                import_batch_id="norm-owner-batch",
                row_number=5,
                raw_data={"Date": "2026-07-20", "Amount": "2", "Currency": "../USD"},
                normalized_data=None,
                validation_errors=None,
                deduplication_key=None,
                status=ImportRowStatus.pending,
                error_message=None,
                created_transaction_id=None,
                created_investment_event_id=None,
                created_at=now,
            )
        )
        await session.commit()
    await engine.dispose()


async def _rows(batch_id: str) -> list[ImportRowModel]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        rows = list(
            (
                await session.scalars(
                    select(ImportRowModel)
                    .where(ImportRowModel.import_batch_id == batch_id)
                    .order_by(ImportRowModel.row_number)
                )
            ).all()
        )
        for row in rows:
            session.expunge(row)
    await engine.dispose()
    return rows


async def _batch_counters(batch_id: str) -> tuple[int, int, int]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        batch = await session.get(ImportBatchModel, batch_id)
        assert batch is not None
        rows_total = batch.rows_total
        rows_imported = batch.rows_imported
        rows_skipped = batch.rows_skipped
    await engine.dispose()
    assert rows_total is not None and rows_imported is not None and rows_skipped is not None
    return rows_total, rows_imported, rows_skipped


async def _normalize_batch(batch_id: str):
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        response = await ImportNormalizationService(session).normalize_batch(
            principal=_principal(), account_id="norm-active", batch_id=batch_id
        )
    await engine.dispose()
    return response


async def _concurrent() -> list[object]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL), pool_size=2)

    async def once() -> object:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            try:
                return await ImportNormalizationService(session).normalize_batch(
                    principal=_principal(),
                    account_id="norm-active",
                    batch_id="norm-concurrent-batch",
                )
            except Exception as exc:
                return exc

    results = list(await asyncio.gather(once(), once()))
    await engine.dispose()
    return results


async def _rollback() -> tuple[list[ImportRowModel], list[ImportRowModel]]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        service = ImportNormalizationService(session)
        with (
            patch.object(session, "commit", side_effect=RuntimeError("controlled commit failure")),
            pytest.raises(RuntimeError),
        ):
            await service.normalize_batch(
                principal=_principal(), account_id="norm-active", batch_id="norm-rollback-batch"
            )
    failed = await _rows("norm-rollback-batch")
    async with AsyncSession(engine) as session:
        await ImportNormalizationService(session).normalize_batch(
            principal=_principal(), account_id="norm-active", batch_id="norm-rollback-batch"
        )
    retried = await _rows("norm-rollback-batch")
    await engine.dispose()
    return failed, retried


async def _normalize_trading212_batch() -> None:
    response = await _normalize_batch("norm-trading212-batch")
    assert response.rows_normalized == 1


async def _trading212_rollback() -> tuple[
    list[ImportRowModel], tuple[int, int, int], list[ImportRowModel]
]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        with (
            patch.object(session, "commit", side_effect=RuntimeError("controlled commit failure")),
            pytest.raises(RuntimeError),
        ):
            await ImportNormalizationService(session).normalize_batch(
                principal=_principal(),
                account_id="norm-active",
                batch_id="norm-trading212-rollback-batch",
            )
    await engine.dispose()
    failed = await _rows("norm-trading212-rollback-batch")
    counters = await _batch_counters("norm-trading212-rollback-batch")
    response = await _normalize_batch("norm-trading212-rollback-batch")
    assert response.rows_normalized == 1
    retried = await _rows("norm-trading212-rollback-batch")
    return failed, counters, retried


def test_normalization_endpoint_and_postgresql_contract() -> None:
    assert DATABASE_URL is not None
    _run(_seed())
    settings = Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        log_level="ERROR",
        log_json=False,
        internal_auth_secret=SECRET,
        _env_file=None,
    )
    with TestClient(create_app(settings)) as client:
        path = "/api/v1/accounts/norm-active/imports/norm-owner-batch/normalize"
        missing = client.post(path)
        invalid = client.post(path, headers={"Authorization": "Bearer invalid"})
        expired = client.post(
            path, headers={"Authorization": f"Bearer {_token('norm-owner', expires_in=-60)}"}
        )
        assert (missing.status_code, missing.json()["error"]["code"]) == (
            401,
            "authentication_required",
        )
        assert (invalid.status_code, invalid.json()["error"]["code"]) == (
            401,
            "invalid_session_token",
        )
        assert (expired.status_code, expired.json()["error"]["code"]) == (
            401,
            "expired_session_token",
        )
        for user_id, batch_id in [
            ("norm-admin", "norm-admin-batch"),
            ("norm-editor", "norm-editor-batch"),
        ]:
            assert (
                client.post(
                    f"/api/v1/accounts/norm-active/imports/{batch_id}/normalize",
                    headers=_headers(user_id),
                ).status_code
                == 200
            )
        assert (
            client.post(
                "/api/v1/accounts/norm-active/imports/norm-viewer-batch/normalize",
                headers=_headers("norm-viewer"),
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/accounts/norm-foreign-account/imports/norm-foreign-batch/normalize",
                headers=_headers("norm-owner"),
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/accounts/norm-archived/imports/norm-archived-batch/normalize",
                headers=_headers("norm-owner"),
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/v1/accounts/norm-active/imports/norm-foreign-batch/normalize",
                headers=_headers("norm-owner"),
            ).status_code
            == 404
        )
        first = client.post(path, headers=_headers("norm-owner"))
        assert first.status_code == 200
        assert first.json() == {
            "batch_id": "norm-owner-batch",
            "status": "processing",
            "rows_total": 4,
            "rows_normalized": 1,
            "rows_needs_review": 2,
            "rows_failed": 1,
        }
        second = client.post(path, headers=_headers("norm-owner"))
        assert (second.status_code, second.json()["error"]["code"]) == (
            409,
            "import_normalize_state_invalid",
        )

    rows = _run(_rows("norm-owner-batch"))
    valid, invalid_date, parser_failed, invalid_currency = rows
    assert valid.status is ImportRowStatus.pending and valid.normalized_data is not None
    assert valid.deduplication_key and len(valid.deduplication_key) == 64
    assert valid.raw_data == {"Date": "2026-07-20", "Amount": "10.50", "Currency": "eur"}
    assert valid.created_transaction_id is None and valid.created_investment_event_id is None
    for row in [invalid_date, invalid_currency]:
        assert row.status is ImportRowStatus.needs_review
        assert row.normalized_data is None and row.deduplication_key is None
        assert row.validation_errors and row.error_message
    assert parser_failed.status is ImportRowStatus.failed
    assert parser_failed.raw_data == {"parser": "unchanged"}
    assert parser_failed.validation_errors == [{"code": "parse"}]
    assert parser_failed.error_message == "Parser failure"

    concurrent = _run(_concurrent())
    assert sum(not isinstance(result, Exception) for result in concurrent) == 1
    assert sum(isinstance(result, ImportNormalizeStateError) for result in concurrent) == 1
    concurrent_rows = _run(_rows("norm-concurrent-batch"))
    assert concurrent_rows[0].normalized_data is not None
    failed, retried = _run(_rollback())
    assert failed[0].normalized_data is None and failed[0].deduplication_key is None
    assert failed[0].status is ImportRowStatus.pending
    assert retried[0].normalized_data is not None and retried[0].deduplication_key is not None


def test_trading212_normalization_persists_schema_v2_without_posting() -> None:
    assert DATABASE_URL is not None
    _run(_seed())
    _run(_normalize_trading212_batch())
    row = _run(_rows("norm-trading212-batch"))[0]
    assert row.status is ImportRowStatus.pending
    assert row.normalized_data is not None
    assert row.normalized_data["schema_version"] == 2
    assert row.normalized_data["action"] == "buy"
    assert row.deduplication_key and len(row.deduplication_key) == 64
    assert row.created_transaction_id is None and row.created_investment_event_id is None


def test_trading212_invalid_row_persists_structured_review_transition() -> None:
    assert DATABASE_URL is not None
    _run(_seed())

    response = _run(_normalize_batch("norm-trading212-review-batch"))
    row = _run(_rows("norm-trading212-review-batch"))[0]

    assert response.rows_normalized == 0
    assert response.rows_needs_review == 1
    assert response.rows_failed == 0
    assert row.status is ImportRowStatus.needs_review
    assert row.normalized_data is None and row.deduplication_key is None
    assert row.validation_errors == [
        {
            "field": "action",
            "code": "unsupported_action",
            "message": "The Trading212 action is not supported.",
        },
        {"field": "date", "code": "required", "message": "Date is required."},
    ]
    assert _run(_batch_counters("norm-trading212-review-batch")) == (1, 0, 1)


def test_trading212_normalization_rollback_leaves_no_partial_rows_and_retries() -> None:
    assert DATABASE_URL is not None
    _run(_seed())

    failed, counters, retried = _run(_trading212_rollback())

    assert failed[0].status is ImportRowStatus.pending
    assert failed[0].normalized_data is None and failed[0].deduplication_key is None
    assert counters == (1, 0, 0)
    assert retried[0].status is ImportRowStatus.pending
    assert retried[0].normalized_data is not None
    assert retried[0].normalized_data["schema_version"] == 2
    assert retried[0].deduplication_key is not None
