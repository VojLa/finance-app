from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    ImportRowStatus,
    TransactionClassification,
    TransactionType,
)
from app.db.models.imports import ImportBatchModel, ImportLogModel, ImportRowModel
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.imports.deduplication import ImportDeduplicationService
from app.modules.imports.transaction_posting import ImportTransactionPostingWriter

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")

SECRET = "r2-raiffeisenbank-integration-secret-32-characters"
FIXTURES = Path(__file__).parent / "fixtures" / "imports" / "raiffeisenbank"


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


def _headers(user_id: str, *, binary: bool = False) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {_token(user_id)}"}
    if binary:
        headers["Content-Type"] = "application/octet-stream"
    return headers


def _settings() -> Settings:
    assert DATABASE_URL is not None
    return Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        log_level="ERROR",
        log_json=False,
        internal_auth_secret=SECRET,
        _env_file=None,
    )


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=8)


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    user_ids = [f"{prefix}-owner", f"{prefix}-foreign"]
    account_ids = [f"{prefix}-account", f"{prefix}-foreign-account", f"{prefix}-concurrent"]
    async with AsyncSession(engine) as session:
        batch_ids = select(ImportBatchModel.id).where(ImportBatchModel.account_id.in_(account_ids))
        snapshot_ids = select(AccountSnapshotModel.id).where(
            AccountSnapshotModel.account_id.in_(account_ids)
        )
        await session.execute(
            delete(AccountSnapshotItemModel).where(
                AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids)
            )
        )
        await session.execute(
            delete(AccountSnapshotModel).where(AccountSnapshotModel.account_id.in_(account_ids))
        )
        await session.execute(
            delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id.in_(user_ids))
        )
        await session.execute(
            delete(TransactionModel).where(TransactionModel.account_id.in_(account_ids))
        )
        await session.execute(
            delete(ImportLogModel).where(ImportLogModel.import_batch_id.in_(batch_ids))
        )
        await session.execute(
            delete(ImportRowModel).where(ImportRowModel.import_batch_id.in_(batch_ids))
        )
        await session.execute(delete(ImportBatchModel).where(ImportBatchModel.id.in_(batch_ids)))
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
        )
        await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        await session.commit()
    await engine.dispose()


async def _seed(prefix: str, *, include_concurrent: bool = True) -> None:
    await _cleanup(prefix)
    engine = _engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        for suffix in ("owner", "foreign"):
            session.add(
                UserModel(
                    id=f"{prefix}-{suffix}",
                    email=f"{prefix}-{suffix}@example.com",
                    name=f"{prefix}-{suffix}",
                    password_hash=None,
                    base_currency="CZK",
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()
        specs = [
            (f"{prefix}-account", f"{prefix}-owner"),
            (f"{prefix}-foreign-account", f"{prefix}-foreign"),
        ]
        if include_concurrent:
            specs.insert(1, (f"{prefix}-concurrent", f"{prefix}-owner"))
        for account_id, _ in specs:
            session.add(
                AccountModel(
                    id=account_id,
                    name=account_id,
                    type=AccountType.bank,
                    currency="CZK",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.flush()
        for index, (account_id, user_id) in enumerate(specs):
            session.add(
                AccountMemberModel(
                    id=f"{prefix}-member-{index}",
                    account_id=account_id,
                    user_id=user_id,
                    role=AccountMemberRole.owner,
                    relation_type=AccountRelationType.owner,
                    invited_by_id=None,
                    accepted_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        await session.commit()
    await engine.dispose()


def _variant(content: bytes, variant: str) -> bytes:
    if variant == "bom":
        return b"\xef\xbb\xbf" + content
    if variant == "reordered":
        lines = content.decode().splitlines()
        return ("\n".join([lines[0], *reversed(lines[1:])]) + "\n").encode()
    return content


def _create_and_prepare(
    client: TestClient,
    *,
    user_id: str,
    account_id: str,
    content: bytes,
    filename: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    checksum = hashlib.sha256(content).hexdigest()
    created = client.post(
        f"/api/v1/accounts/{account_id}/imports",
        headers=_headers(user_id),
        json={
            "source": "raiffeisenbank",
            "filename": filename,
            "file_size": len(content),
            "file_encoding": None,
            "checksum": checksum,
        },
    )
    assert created.status_code == 201, created.text
    batch_id = created.json()["id"]
    uploaded = client.put(
        f"/api/v1/accounts/{account_id}/imports/{batch_id}/file",
        headers=_headers(user_id, binary=True),
        content=content,
    )
    assert uploaded.status_code == 200, uploaded.text
    base = f"/api/v1/accounts/{account_id}/imports/{batch_id}"
    parsed = client.post(f"{base}/parse", headers=_headers(user_id))
    normalized = client.post(f"{base}/normalize", headers=_headers(user_id))
    assert parsed.status_code == normalized.status_code == 200
    return batch_id, parsed.json(), normalized.json()


def _finish(
    client: TestClient,
    *,
    user_id: str,
    account_id: str,
    batch_id: str,
) -> dict[str, Any]:
    base = f"/api/v1/accounts/{account_id}/imports/{batch_id}"
    deduplicated = client.post(f"{base}/deduplicate", headers=_headers(user_id))
    classified = client.post(f"{base}/classify", headers=_headers(user_id))
    posted = client.post(f"{base}/post", headers=_headers(user_id))
    assert deduplicated.status_code == classified.status_code == posted.status_code == 200
    return {
        "deduplicated": deduplicated.json(),
        "classified": classified.json(),
        "posted": posted.json(),
    }


async def _rows(batch_id: str) -> list[ImportRowModel]:
    engine = _engine()
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


async def _transactions(account_id: str) -> list[TransactionModel]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        values = list(
            (
                await session.scalars(
                    select(TransactionModel)
                    .where(TransactionModel.account_id == account_id)
                    .order_by(TransactionModel.date, TransactionModel.external_id)
                )
            ).all()
        )
        for value in values:
            session.expunge(value)
    await engine.dispose()
    return values


def test_raiffeisenbank_fixtures_post_exact_transactions_and_deduplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = "r2-rb-source"
    asyncio.run(_seed(prefix))
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path))
    app = create_app(_settings())
    owner = f"{prefix}-owner"
    account = f"{prefix}-account"
    foreign = f"{prefix}-foreign"
    foreign_account = f"{prefix}-foreign-account"
    main = (FIXTURES / "account_statement.csv").read_bytes()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            first_id, parsed, normalized = _create_and_prepare(
                client,
                user_id=owner,
                account_id=account,
                content=main,
                filename="account-statement.csv",
            )
            first = _finish(client, user_id=owner, account_id=account, batch_id=first_id)
            replay = client.post(
                f"/api/v1/accounts/{account}/imports/{first_id}/post",
                headers=_headers(owner),
            )
            assert parsed == {
                "batch_id": first_id,
                "status": "processing",
                "rows_total": 3,
                "rows_pending": 3,
                "rows_failed": 0,
            }
            assert normalized["rows_normalized"] == 3
            assert first["deduplicated"]["rows_unique"] == 3
            assert first["deduplicated"]["rows_duplicate"] == 0
            assert first["classified"]["rows_classified"] == 3
            assert first["posted"]["rows_imported"] == 3
            assert first["posted"]["rows_skipped"] == 0
            assert replay.status_code == 200
            assert replay.json()["replayed"] is True

            second_id, _, _ = _create_and_prepare(
                client,
                user_id=owner,
                account_id=account,
                content=_variant(main, "bom"),
                filename="renamed-account-statement.csv",
            )
            second = _finish(client, user_id=owner, account_id=account, batch_id=second_id)
            assert second["deduplicated"]["rows_unique"] == 0
            assert second["deduplicated"]["rows_duplicate"] == 3
            assert second["posted"]["rows_imported"] == 0

            third_id, _, _ = _create_and_prepare(
                client,
                user_id=owner,
                account_id=account,
                content=_variant(main, "reordered"),
                filename="reordered-account-statement.csv",
            )
            third = _finish(client, user_id=owner, account_id=account, batch_id=third_id)
            assert third["deduplicated"]["rows_duplicate"] == 3
            assert third["posted"]["rows_imported"] == 0

            foreign_id, _, _ = _create_and_prepare(
                client,
                user_id=foreign,
                account_id=foreign_account,
                content=main,
                filename="foreign-account-statement.csv",
            )
            foreign_result = _finish(
                client,
                user_id=foreign,
                account_id=foreign_account,
                batch_id=foreign_id,
            )
            assert foreign_result["posted"]["rows_imported"] == 3
            hidden = client.get(
                f"/api/v1/accounts/{foreign_account}/imports/{foreign_id}",
                headers=_headers(owner),
            )
            assert hidden.status_code == 404

            card = (FIXTURES / "card_statement.csv").read_bytes()
            card_id, card_parsed, card_normalized = _create_and_prepare(
                client,
                user_id=owner,
                account_id=account,
                content=card,
                filename="card-statement.csv",
            )
            card_result = _finish(client, user_id=owner, account_id=account, batch_id=card_id)
            assert card_parsed["rows_total"] == 3
            assert card_normalized["rows_normalized"] == 2
            assert card_normalized["rows_needs_review"] == 1
            assert card_result["classified"]["rows_classified"] == 2
            assert card_result["posted"]["rows_imported"] == 2
            assert card_result["posted"]["rows_skipped"] == 1

            issues = (FIXTURES / "account_statement_issues.csv").read_bytes()
            issues_id, issues_parsed, issues_normalized = _create_and_prepare(
                client,
                user_id=owner,
                account_id=account,
                content=issues,
                filename="account-statement-issues.csv",
            )
            issue_result = _finish(
                client,
                user_id=owner,
                account_id=account,
                batch_id=issues_id,
            )
            assert issues_parsed["rows_total"] == 6
            assert issues_parsed["rows_pending"] == 4
            assert issues_parsed["rows_failed"] == 2
            assert issues_normalized["rows_normalized"] == 3
            assert issues_normalized["rows_needs_review"] == 1
            assert issue_result["classified"]["rows_classified"] == 1
            assert issue_result["classified"]["rows_needs_review"] == 3
            assert issue_result["classified"]["rows_failed"] == 2
            assert issue_result["posted"]["rows_imported"] == 1
            assert issue_result["posted"]["rows_skipped"] == 5

        account_transactions = asyncio.run(_transactions(account))
        first_transactions = [
            transaction
            for transaction in account_transactions
            if transaction.import_batch_id == first_id
        ]
        assert len(first_transactions) == 3
        assert {transaction.amount for transaction in first_transactions} == {
            Decimal("-123.450000"),
            Decimal("-50.000000"),
            Decimal("10000.000000"),
        }
        assert {transaction.external_id for transaction in first_transactions} == {
            "RB-FAKE-IN-001",
            "RB-FAKE-OUT-001",
            "RB-FAKE-FEE-001",
        }
        assert all(transaction.counterparty is not None for transaction in first_transactions)
        assert all(
            transaction.classification
            in {
                TransactionClassification.real_income,
                TransactionClassification.real_expense,
            }
            for transaction in first_transactions
        )
        assert all(
            transaction.type in {TransactionType.income, TransactionType.expense}
            for transaction in first_transactions
        )
        assert len(asyncio.run(_transactions(foreign_account))) == 3
        assert asyncio.run(_idle_in_transaction_count()) == 0
    finally:
        asyncio.run(_cleanup(prefix))


def test_concurrent_duplicate_processing_selects_one_account_scoped_winner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = "r2-rb-concurrent"
    asyncio.run(_seed(prefix))
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path))
    app = create_app(_settings())
    owner = f"{prefix}-owner"
    account = f"{prefix}-concurrent"
    main = (FIXTURES / "account_statement.csv").read_bytes()
    try:
        with TestClient(app) as client:
            first_id, _, _ = _create_and_prepare(
                client,
                user_id=owner,
                account_id=account,
                content=main,
                filename="first.csv",
            )
            second_id, _, _ = _create_and_prepare(
                client,
                user_id=owner,
                account_id=account,
                content=_variant(main, "bom"),
                filename="second.csv",
            )

            async def concurrent_deduplicate() -> tuple[Any, Any]:
                principal = AuthenticatedPrincipal(
                    user_id=owner,
                    email=f"{owner}@example.com",
                    name=owner,
                )
                engine = _engine()

                async def run(batch_id: str):
                    async with AsyncSession(engine) as session:
                        return await ImportDeduplicationService(session).deduplicate_batch(
                            principal=principal,
                            account_id=account,
                            batch_id=batch_id,
                        )

                try:
                    return await asyncio.gather(run(first_id), run(second_id))
                finally:
                    await engine.dispose()

            responses = asyncio.run(concurrent_deduplicate())
            assert sorted(response.rows_unique for response in responses) == [0, 3]
            assert sorted(response.rows_duplicate for response in responses) == [0, 3]
            for batch_id in (first_id, second_id):
                base = f"/api/v1/accounts/{account}/imports/{batch_id}"
                assert client.post(f"{base}/classify", headers=_headers(owner)).status_code == 200
                assert client.post(f"{base}/post", headers=_headers(owner)).status_code == 200

        assert len(asyncio.run(_transactions(account))) == 3
    finally:
        asyncio.run(_cleanup(prefix))


def test_posting_rollback_retry_and_counterparty_corruption_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix = "r2-rb-rollback"
    asyncio.run(_seed(prefix))
    monkeypatch.setenv("IMPORT_STORAGE_ROOT", str(tmp_path))
    app = create_app(_settings())
    owner = f"{prefix}-owner"
    account = f"{prefix}-account"
    content = (FIXTURES / "account_statement.csv").read_bytes()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            batch_id, _, _ = _create_and_prepare(
                client,
                user_id=owner,
                account_id=account,
                content=content,
                filename="rollback.csv",
            )
            base = f"/api/v1/accounts/{account}/imports/{batch_id}"
            assert client.post(f"{base}/deduplicate", headers=_headers(owner)).status_code == 200
            assert client.post(f"{base}/classify", headers=_headers(owner)).status_code == 200
            original = ImportTransactionPostingWriter.post_row
            calls = 0

            async def fail_second(self, *, account_id: str, batch: Any, row: Any):
                nonlocal calls
                calls += 1
                result = await original(self, account_id=account_id, batch=batch, row=row)
                if calls == 2:
                    raise RuntimeError("controlled Raiffeisenbank rollback")
                return result

            with patch.object(ImportTransactionPostingWriter, "post_row", fail_second):
                failed = client.post(f"{base}/post", headers=_headers(owner))
            assert failed.status_code == 500
            assert asyncio.run(_transactions(account)) == []
            assert all(
                row.status is ImportRowStatus.pending for row in asyncio.run(_rows(batch_id))
            )

            retried = client.post(f"{base}/post", headers=_headers(owner))
            assert retried.status_code == 200
            assert retried.json()["rows_imported"] == 3
            transactions = asyncio.run(_transactions(account))
            assert len(transactions) == 3
            corrupted_id = transactions[0].id

            async def corrupt() -> None:
                engine = _engine()
                async with AsyncSession(engine) as session:
                    transaction = await session.get(TransactionModel, corrupted_id)
                    assert transaction is not None
                    transaction.counterparty = "corrupted counterparty"
                    await session.commit()
                await engine.dispose()

            asyncio.run(corrupt())
            corrupted = client.post(f"{base}/post", headers=_headers(owner))
            assert corrupted.status_code == 409
            assert corrupted.json()["error"]["code"] == "import_post_state_invalid"
            assert (
                asyncio.run(
                    _count_transactions(account_id=account, external_id=transactions[0].external_id)
                )
                == 1
            )
    finally:
        asyncio.run(_cleanup(prefix))


async def _count_transactions(*, account_id: str, external_id: str | None) -> int:
    engine = _engine()
    async with AsyncSession(engine) as session:
        count = await session.scalar(
            select(func.count())
            .select_from(TransactionModel)
            .where(
                TransactionModel.account_id == account_id,
                TransactionModel.external_id == external_id,
            )
        )
    await engine.dispose()
    return int(count or 0)


async def _idle_in_transaction_count() -> int:
    engine = _engine()
    async with AsyncSession(engine) as session:
        count = await session.scalar(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND state = 'idle in transaction'"
            )
        )
    await engine.dispose()
    return int(count or 0)
