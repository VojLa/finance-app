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
from app.modules.imports.deduplication import ImportDeduplicationService
from app.modules.imports.models import ImportDeduplicateResponse
from app.modules.imports.normalization import ImportNormalizationService

DATABASE_URL = os.getenv("DATABASE_URL")
SECRET = "step-5e-internal-auth-secret-32-characters"

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")

USER_IDS = ["step5e-owner", "step5e-viewer", "step5e-foreign"]
ACCOUNT_IDS = ["step5e-account", "step5e-other"]
BATCH_IDS = [
    "step5e-prior",
    "step5e-current",
    "step5e-viewer",
    "step5e-other",
    "step5e-older",
    "step5e-newer",
    "step5e-concurrent-a",
    "step5e-concurrent-b",
    "step5e-rollback",
    "step5e-trading212-a",
    "step5e-trading212-b",
    "step5e-trading212-other",
    "step5e-anycoin-a",
    "step5e-anycoin-b",
    "step5e-anycoin-other",
]


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


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id="step5e-owner",
        email="step5e-owner@example.com",
        name="Step 5E Owner",
    )


def _batch(
    batch_id: str,
    *,
    account_id: str = "step5e-account",
    user_id: str = "step5e-owner",
    source: ImportSource = ImportSource.manual,
    created_at: datetime,
    status: ImportStatus = ImportStatus.processing,
) -> ImportBatchModel:
    return ImportBatchModel(
        id=batch_id,
        user_id=user_id,
        account_id=account_id,
        source=source,
        filename=f"{batch_id}.csv",
        file_size=1,
        file_encoding="utf-8",
        checksum=hashlib.sha256(batch_id.encode()).hexdigest(),
        status=status,
        rows_total=1,
        rows_imported=1 if status is ImportStatus.completed else 0,
        rows_skipped=0,
        created_at=created_at,
        completed_at=created_at if status is ImportStatus.completed else None,
        retain_until=None,
        raw_data_purged_at=None,
    )


def _row(
    row_id: str,
    *,
    batch_id: str,
    row_number: int,
    key: str | None,
    status: ImportRowStatus = ImportRowStatus.pending,
) -> ImportRowModel:
    normalized = (
        None
        if status in {ImportRowStatus.failed, ImportRowStatus.needs_review}
        else {
            "schema_version": 1,
            "source": "manual",
            "date": "2026-07-23",
            "amount": "1",
            "currency": "EUR",
        }
    )
    return ImportRowModel(
        id=row_id,
        import_batch_id=batch_id,
        row_number=row_number,
        raw_data={"row": row_id},
        normalized_data=normalized,
        validation_errors=[{"code": "controlled"}] if normalized is None else None,
        deduplication_key=key,
        status=status,
        error_message="Controlled issue" if normalized is None else None,
        created_transaction_id=None,
        created_investment_event_id=None,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )


def _trading212_row(row_id: str, *, batch_id: str) -> ImportRowModel:
    return ImportRowModel(
        id=row_id,
        import_batch_id=batch_id,
        row_number=2,
        raw_data={
            "Action": "Market buy",
            "Time": "2026-07-23T10:00:00Z",
            "Ticker": "VWCE",
            "No. of shares": "2",
            "Total": "201",
            "Currency (Total)": "EUR",
            "ID": "provider-trade-1",
        },
        normalized_data=None,
        validation_errors=None,
        deduplication_key=None,
        status=ImportRowStatus.pending,
        error_message=None,
        created_transaction_id=None,
        created_investment_event_id=None,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )


async def _seed() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        await session.execute(delete(ImportBatchModel).where(ImportBatchModel.id.in_(BATCH_IDS)))
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(ACCOUNT_IDS))
        )
        await session.execute(delete(AccountModel).where(AccountModel.id.in_(ACCOUNT_IDS)))
        await session.execute(delete(UserModel).where(UserModel.id.in_(USER_IDS)))

        for user_id in USER_IDS:
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{user_id}@example.com",
                    name=user_id,
                    password_hash=None,
                    base_currency="EUR",
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()

        for account_id in ACCOUNT_IDS:
            session.add(
                AccountModel(
                    id=account_id,
                    name=account_id,
                    type=AccountType.bank,
                    currency="EUR",
                    color=None,
                    is_archived=False,
                    archived_at=None,
                    notes=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()

        for member_id, account_id, user_id, role in [
            ("step5e-member-owner", "step5e-account", "step5e-owner", AccountMemberRole.owner),
            ("step5e-member-viewer", "step5e-account", "step5e-viewer", AccountMemberRole.viewer),
            ("step5e-member-foreign", "step5e-other", "step5e-foreign", AccountMemberRole.owner),
        ]:
            session.add(
                AccountMemberModel(
                    id=member_id,
                    account_id=account_id,
                    user_id=user_id,
                    role=role,
                    relation_type=AccountRelationType.owner,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()

        batches = [
            _batch(
                "step5e-prior",
                created_at=now - timedelta(days=2),
                status=ImportStatus.completed,
            ),
            _batch("step5e-current", created_at=now - timedelta(days=1)),
            _batch("step5e-viewer", created_at=now),
            _batch(
                "step5e-other",
                account_id="step5e-other",
                user_id="step5e-foreign",
                created_at=now,
            ),
            _batch("step5e-older", source=ImportSource.anycoin, created_at=now),
            _batch(
                "step5e-newer",
                source=ImportSource.anycoin,
                created_at=now + timedelta(seconds=1),
            ),
            _batch(
                "step5e-concurrent-a",
                source=ImportSource.trading212,
                created_at=now,
            ),
            _batch(
                "step5e-concurrent-b",
                source=ImportSource.trading212,
                created_at=now,
            ),
            _batch(
                "step5e-rollback",
                created_at=now,
            ),
        ]
        session.add_all(batches)
        await session.flush()

        key_prior = "a" * 64
        key_within = "b" * 64
        rows = [
            _row(
                "step5e-prior-row",
                batch_id="step5e-prior",
                row_number=2,
                key=key_prior,
                status=ImportRowStatus.imported,
            ),
            _row(
                "step5e-current-prior",
                batch_id="step5e-current",
                row_number=2,
                key=key_prior,
            ),
            _row(
                "step5e-current-first",
                batch_id="step5e-current",
                row_number=3,
                key=key_within,
            ),
            _row(
                "step5e-current-second",
                batch_id="step5e-current",
                row_number=4,
                key=key_within,
            ),
            _row(
                "step5e-current-review",
                batch_id="step5e-current",
                row_number=5,
                key=None,
                status=ImportRowStatus.needs_review,
            ),
            _row(
                "step5e-current-failed",
                batch_id="step5e-current",
                row_number=6,
                key=None,
                status=ImportRowStatus.failed,
            ),
            _row(
                "step5e-viewer-row",
                batch_id="step5e-viewer",
                row_number=2,
                key="c" * 64,
            ),
            _row(
                "step5e-other-row",
                batch_id="step5e-other",
                row_number=2,
                key="d" * 64,
            ),
            _row(
                "step5e-older-row",
                batch_id="step5e-older",
                row_number=2,
                key=None,
            ),
            _row(
                "step5e-newer-row",
                batch_id="step5e-newer",
                row_number=2,
                key="e" * 64,
            ),
            _row(
                "step5e-concurrent-a-row",
                batch_id="step5e-concurrent-a",
                row_number=2,
                key="f" * 64,
            ),
            _row(
                "step5e-concurrent-b-row",
                batch_id="step5e-concurrent-b",
                row_number=2,
                key="f" * 64,
            ),
            _row(
                "step5e-rollback-row",
                batch_id="step5e-rollback",
                row_number=2,
                key=key_prior,
            ),
        ]
        rows[8].normalized_data = None
        session.add_all(rows)
        current = next(batch for batch in batches if batch.id == "step5e-current")
        current.rows_total = 5
        await session.commit()
    await engine.dispose()


async def _statuses(*batch_ids: str) -> dict[str, ImportRowStatus]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        rows = list(
            (
                await session.scalars(
                    select(ImportRowModel).where(ImportRowModel.import_batch_id.in_(batch_ids))
                )
            ).all()
        )
        result = {row.import_batch_id: row.status for row in rows}
    await engine.dispose()
    return result


async def _seed_trading212_normalization_candidates() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        batches = [
            _batch("step5e-trading212-a", source=ImportSource.trading212, created_at=now),
            _batch(
                "step5e-trading212-b",
                source=ImportSource.trading212,
                created_at=now + timedelta(seconds=1),
            ),
            _batch(
                "step5e-trading212-other",
                account_id="step5e-other",
                user_id="step5e-foreign",
                source=ImportSource.trading212,
                created_at=now,
            ),
        ]
        session.add_all(batches)
        session.add_all(
            [
                _trading212_row("step5e-trading212-a-row", batch_id="step5e-trading212-a"),
                _trading212_row("step5e-trading212-b-row", batch_id="step5e-trading212-b"),
                _trading212_row("step5e-trading212-other-row", batch_id="step5e-trading212-other"),
            ]
        )
        await session.commit()
    await engine.dispose()


def _anycoin_rows(
    batch_id: str, *, order_id: str, include_neutral: bool = False
) -> list[ImportRowModel]:
    now = datetime.now(UTC).replace(tzinfo=None)
    rows = [
        ImportRowModel(
            id=f"{batch_id}-payment",
            import_batch_id=batch_id,
            row_number=2,
            raw_data={
                "Type": "trade payment",
                "Order ID": order_id,
                "Date": "2026-07-23T10:00:00Z",
                "Amount": "-100",
                "Currency": "EUR",
                "Transaction ID": f"{order_id}-payment",
            },
            normalized_data=None,
            validation_errors=None,
            deduplication_key=None,
            status=ImportRowStatus.pending,
            error_message=None,
            created_transaction_id=None,
            created_investment_event_id=None,
            created_at=now,
        ),
        ImportRowModel(
            id=f"{batch_id}-fill",
            import_batch_id=batch_id,
            row_number=3,
            raw_data={
                "Type": "trade fill",
                "Order ID": order_id,
                "Date": "2026-07-23T10:01:00Z",
                "Amount": "0.01",
                "Currency": "BTC",
                "Transaction ID": f"{order_id}-fill",
            },
            normalized_data=None,
            validation_errors=None,
            deduplication_key=None,
            status=ImportRowStatus.pending,
            error_message=None,
            created_transaction_id=None,
            created_investment_event_id=None,
            created_at=now,
        ),
    ]
    if include_neutral:
        rows.append(
            ImportRowModel(
                id=f"{batch_id}-neutral",
                import_batch_id=batch_id,
                row_number=4,
                raw_data={
                    "Type": "payment block",
                    "Date": "2026-07-23",
                    "Amount": "1",
                    "Currency": "EUR",
                },
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
    return rows


async def _seed_anycoin_normalization_candidates() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        session.add_all(
            [
                _batch("step5e-anycoin-a", source=ImportSource.anycoin, created_at=now),
                _batch(
                    "step5e-anycoin-b",
                    source=ImportSource.anycoin,
                    created_at=now + timedelta(seconds=1),
                ),
                _batch(
                    "step5e-anycoin-other",
                    account_id="step5e-other",
                    user_id="step5e-foreign",
                    source=ImportSource.anycoin,
                    created_at=now,
                ),
            ]
        )
        for batch_id in ("step5e-anycoin-a", "step5e-anycoin-b", "step5e-anycoin-other"):
            batch_rows = _anycoin_rows(
                batch_id,
                order_id="anycoin-provider-order",
                include_neutral=batch_id == "step5e-anycoin-b",
            )
            session.add_all(batch_rows)
            batch = await session.get(ImportBatchModel, batch_id)
            assert batch is not None
            batch.rows_total = len(batch_rows)
        await session.commit()
    await engine.dispose()


async def _normalize_trading212_candidate(
    *, batch_id: str, account_id: str, principal: AuthenticatedPrincipal
) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        result = await ImportNormalizationService(session).normalize_batch(
            principal=principal, account_id=account_id, batch_id=batch_id
        )
    await engine.dispose()
    assert result.rows_normalized == 1


async def _trading212_rows() -> list[ImportRowModel]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        rows = list(
            (
                await session.scalars(
                    select(ImportRowModel)
                    .where(
                        ImportRowModel.id.in_(
                            (
                                "step5e-trading212-a-row",
                                "step5e-trading212-b-row",
                                "step5e-trading212-other-row",
                            )
                        )
                    )
                    .order_by(ImportRowModel.id)
                )
            ).all()
        )
        for row in rows:
            session.expunge(row)
    await engine.dispose()
    return rows


async def _make_older_candidate() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        row = await session.scalar(
            select(ImportRowModel).where(ImportRowModel.id == "step5e-older-row")
        )
        assert row is not None
        row.normalized_data = {
            "schema_version": 1,
            "source": "anycoin",
            "date": "2026-07-23",
            "amount": "1",
            "currency": "EUR",
        }
        row.deduplication_key = "e" * 64
        await session.commit()
    await engine.dispose()


async def _deduplicate(batch_id: str) -> ImportDeduplicateResponse:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL), pool_size=2)
    async with AsyncSession(engine) as session:
        result = await ImportDeduplicationService(session).deduplicate_batch(
            principal=_principal(),
            account_id="step5e-account",
            batch_id=batch_id,
        )
    await engine.dispose()
    return result


async def _deduplicate_concurrently() -> tuple[
    ImportDeduplicateResponse,
    ImportDeduplicateResponse,
]:
    first, second = await asyncio.gather(
        _deduplicate("step5e-concurrent-b"),
        _deduplicate("step5e-concurrent-a"),
    )
    return first, second


def test_duplicate_detection_postgresql_contract_and_ordering() -> None:
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
        base = "/api/v1/accounts/step5e-account/imports"
        viewer = client.post(
            f"{base}/step5e-viewer/deduplicate",
            headers=_headers("step5e-viewer"),
        )
        foreign = client.post(
            "/api/v1/accounts/step5e-other/imports/step5e-other/deduplicate",
            headers=_headers("step5e-owner"),
        )
        assert (viewer.status_code, viewer.json()["error"]["code"]) == (
            403,
            "account_access_denied",
        )
        assert (foreign.status_code, foreign.json()["error"]["code"]) == (
            404,
            "account_not_found",
        )

        current = client.post(
            f"{base}/step5e-current/deduplicate",
            headers=_headers("step5e-owner"),
        )
        assert current.status_code == 200
        assert current.json() == {
            "batch_id": "step5e-current",
            "status": "processing",
            "rows_total": 5,
            "rows_unique": 1,
            "rows_duplicate": 2,
            "rows_needs_review": 1,
            "rows_failed": 1,
        }

        newer = client.post(
            f"{base}/step5e-newer/deduplicate",
            headers=_headers("step5e-owner"),
        )
        assert newer.status_code == 200
        assert newer.json()["rows_unique"] == 1

    _run(_make_older_candidate())
    older_result = _run(_deduplicate("step5e-older"))
    assert older_result.rows_unique == 1
    assert _run(_statuses("step5e-older", "step5e-newer")) == {
        "step5e-older": ImportRowStatus.pending,
        "step5e-newer": ImportRowStatus.duplicate,
    }

    concurrent = _run(_deduplicate_concurrently())
    assert len(concurrent) == 2
    assert _run(_statuses("step5e-concurrent-a", "step5e-concurrent-b")) == {
        "step5e-concurrent-a": ImportRowStatus.pending,
        "step5e-concurrent-b": ImportRowStatus.duplicate,
    }


def test_duplicate_detection_rolls_back_and_retries() -> None:
    assert DATABASE_URL is not None
    _run(_seed())

    async def scenario() -> tuple[ImportRowStatus, ImportRowStatus]:
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            with (
                patch.object(
                    session,
                    "commit",
                    side_effect=RuntimeError("controlled commit failure"),
                ),
                pytest.raises(RuntimeError),
            ):
                await ImportDeduplicationService(session).deduplicate_batch(
                    principal=_principal(),
                    account_id="step5e-account",
                    batch_id="step5e-rollback",
                )
        failed = (await _statuses("step5e-rollback"))["step5e-rollback"]
        async with AsyncSession(engine) as session:
            await ImportDeduplicationService(session).deduplicate_batch(
                principal=_principal(),
                account_id="step5e-account",
                batch_id="step5e-rollback",
            )
        retried = (await _statuses("step5e-rollback"))["step5e-rollback"]
        await engine.dispose()
        return failed, retried

    assert _run(scenario()) == (
        ImportRowStatus.pending,
        ImportRowStatus.duplicate,
    )


def test_normalized_trading212_external_id_deduplicates_per_account_and_source() -> None:
    assert DATABASE_URL is not None
    _run(_seed())
    _run(_seed_trading212_normalization_candidates())
    owner = _principal()
    foreign = AuthenticatedPrincipal(
        user_id="step5e-foreign",
        email="step5e-foreign@example.com",
        name="Step 5E Foreign",
    )
    for batch_id, account_id, principal in [
        ("step5e-trading212-a", "step5e-account", owner),
        ("step5e-trading212-b", "step5e-account", owner),
        ("step5e-trading212-other", "step5e-other", foreign),
    ]:
        _run(
            _normalize_trading212_candidate(
                batch_id=batch_id, account_id=account_id, principal=principal
            )
        )

    normalized = {row.id: row for row in _run(_trading212_rows())}
    assert (
        normalized["step5e-trading212-a-row"].deduplication_key
        == normalized["step5e-trading212-b-row"].deduplication_key
    )
    assert (
        normalized["step5e-trading212-a-row"].deduplication_key
        != normalized["step5e-trading212-other-row"].deduplication_key
    )
    assert all(row.created_transaction_id is None for row in normalized.values())
    assert all(row.created_investment_event_id is None for row in normalized.values())

    result = _run(_deduplicate("step5e-trading212-b"))
    assert result.rows_unique == 0
    assert result.rows_duplicate == 1
    assert _run(_statuses("step5e-trading212-a", "step5e-trading212-b")) == {
        "step5e-trading212-a": ImportRowStatus.pending,
        "step5e-trading212-b": ImportRowStatus.duplicate,
    }

    async def deduplicate_other_account() -> ImportDeduplicateResponse:
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            response = await ImportDeduplicationService(session).deduplicate_batch(
                principal=foreign,
                account_id="step5e-other",
                batch_id="step5e-trading212-other",
            )
        await engine.dispose()
        return response

    assert _run(deduplicate_other_account()).rows_unique == 1
    assert _run(_statuses("step5e-trading212-other")) == {
        "step5e-trading212-other": ImportRowStatus.pending
    }


def test_normalized_anycoin_group_external_id_deduplicates_per_account_and_source() -> None:
    assert DATABASE_URL is not None
    _run(_seed())
    _run(_seed_anycoin_normalization_candidates())
    owner = _principal()
    foreign = AuthenticatedPrincipal(
        user_id="step5e-foreign",
        email="step5e-foreign@example.com",
        name="Step 5E Foreign",
    )
    for batch_id, account_id, principal in [
        ("step5e-anycoin-a", "step5e-account", owner),
        ("step5e-anycoin-b", "step5e-account", owner),
        ("step5e-anycoin-other", "step5e-other", foreign),
    ]:
        _run(
            _normalize_trading212_candidate(
                batch_id=batch_id, account_id=account_id, principal=principal
            )
        )

    async def anchors() -> dict[str, ImportRowModel]:
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            rows = list(
                (
                    await session.scalars(
                        select(ImportRowModel).where(
                            ImportRowModel.id.in_(
                                (
                                    "step5e-anycoin-a-fill",
                                    "step5e-anycoin-b-fill",
                                    "step5e-anycoin-other-fill",
                                )
                            )
                        )
                    )
                ).all()
            )
            for row in rows:
                session.expunge(row)
        await engine.dispose()
        return {row.import_batch_id: row for row in rows}

    before = _run(anchors())
    assert (
        before["step5e-anycoin-a"].deduplication_key == before["step5e-anycoin-b"].deduplication_key
    )
    assert (
        before["step5e-anycoin-a"].deduplication_key
        != before["step5e-anycoin-other"].deduplication_key
    )
    assert all(row.created_transaction_id is None for row in before.values())
    assert all(row.created_investment_event_id is None for row in before.values())

    result = _run(_deduplicate("step5e-anycoin-b"))
    assert result.rows_unique == 0 and result.rows_duplicate == 1
    after = _run(anchors())
    assert after["step5e-anycoin-a"].status is ImportRowStatus.pending
    assert after["step5e-anycoin-b"].status is ImportRowStatus.duplicate

    async def neutral_row() -> ImportRowModel:
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            row = await session.get(ImportRowModel, "step5e-anycoin-b-neutral")
            assert row is not None
            session.expunge(row)
        await engine.dispose()
        return row

    neutral = _run(neutral_row())
    assert neutral.status is ImportRowStatus.skipped
    assert neutral.normalized_data == {
        "schema_version": 2,
        "source": "anycoin",
        "kind": "neutral_row",
    }
    assert neutral.deduplication_key is None
    assert neutral.created_transaction_id is None and neutral.created_investment_event_id is None

    async def deduplicate_other() -> ImportDeduplicateResponse:
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            response = await ImportDeduplicationService(session).deduplicate_batch(
                principal=foreign, account_id="step5e-other", batch_id="step5e-anycoin-other"
            )
        await engine.dispose()
        return response

    assert _run(deduplicate_other()).rows_unique == 1
    assert _run(anchors())["step5e-anycoin-other"].status is ImportRowStatus.pending
