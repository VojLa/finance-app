from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
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
from app.modules.imports.classification_service import ImportClassificationService
from app.modules.imports.deduplication import ImportDeduplicationService
from app.modules.imports.normalization import ImportNormalizationService

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


async def _seed() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        await session.execute(delete(ImportRowModel).where(ImportRowModel.import_batch_id == "classify-db-batch"))
        await session.execute(delete(ImportBatchModel).where(ImportBatchModel.id == "classify-db-batch"))
        await session.execute(delete(AccountMemberModel).where(AccountMemberModel.account_id == "classify-db-account"))
        await session.execute(delete(AccountModel).where(AccountModel.id == "classify-db-account"))
        await session.execute(delete(UserModel).where(UserModel.id == "classify-db-user"))
        session.add(UserModel(id="classify-db-user", email="classify@example.com", name="Classify", password_hash=None, base_currency="EUR", created_at=now, updated_at=now))
        session.add(AccountModel(id="classify-db-account", name="Classify", type=AccountType.bank, currency="EUR", color=None, notes=None, is_archived=False, archived_at=None, created_at=now, updated_at=now))
        session.add(AccountMemberModel(id="classify-db-member", account_id="classify-db-account", user_id="classify-db-user", role=AccountMemberRole.owner, relation_type=AccountRelationType.owner, invited_by_id=None, accepted_at=now, created_at=now, updated_at=now))
        session.add(ImportBatchModel(id="classify-db-batch", user_id="classify-db-user", account_id="classify-db-account", source=ImportSource.manual, filename="rows.csv", file_size=1, file_encoding="utf-8", checksum="a" * 64, status=ImportStatus.processing, rows_total=1, rows_imported=0, rows_skipped=0, created_at=now, completed_at=None, retain_until=None, raw_data_purged_at=None))
        session.add(ImportRowModel(id="classify-db-row", import_batch_id="classify-db-batch", row_number=2, raw_data={"Date": "2026-07-23", "Amount": "10", "Currency": "EUR", "Type": "income"}, normalized_data=None, validation_errors=None, deduplication_key=None, status=ImportRowStatus.pending, error_message=None, created_transaction_id=None, created_investment_event_id=None, created_at=now))
        await session.commit()
    await engine.dispose()


async def _scenario() -> dict:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    principal = AuthenticatedPrincipal(user_id="classify-db-user", email="classify@example.com", name="Classify")
    async with AsyncSession(engine) as session:
        await ImportNormalizationService(session).normalize_batch(principal=principal, account_id="classify-db-account", batch_id="classify-db-batch")
    async with AsyncSession(engine) as session:
        await ImportDeduplicationService(session).deduplicate_batch(principal=principal, account_id="classify-db-account", batch_id="classify-db-batch")
    async with AsyncSession(engine) as session:
        response = await ImportClassificationService(session).classify_batch(principal=principal, account_id="classify-db-account", batch_id="classify-db-batch")
        assert response.rows_classified == 1
    async with AsyncSession(engine) as session:
        row = await session.get(ImportRowModel, "classify-db-row")
        assert row is not None
        result = dict(row.normalized_data or {})
    await engine.dispose()
    return result


def test_manual_classification_persists_jsonb_after_new_session() -> None:
    asyncio.run(_seed())
    persisted = asyncio.run(_scenario())
    assert persisted["deduplication"] == {"schema_version": 1, "status": "unique"}
    assert persisted["posting_intent"]["target"] == "transaction"
    assert persisted["amount"] == "10"
