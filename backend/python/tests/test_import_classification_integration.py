from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import delete, func, select
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
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.accounts.access import AccountAccessDeniedError, AccountNotFoundError
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
        await session.execute(
            delete(ImportRowModel).where(ImportRowModel.import_batch_id == "classify-db-batch")
        )
        await session.execute(
            delete(ImportBatchModel).where(ImportBatchModel.id == "classify-db-batch")
        )
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id == "classify-db-account")
        )
        await session.execute(delete(AccountModel).where(AccountModel.id == "classify-db-account"))
        await session.execute(delete(UserModel).where(UserModel.id == "classify-db-user"))
        session.add(
            UserModel(
                id="classify-db-user",
                email="classify@example.com",
                name="Classify",
                password_hash=None,
                base_currency="EUR",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            AccountModel(
                id="classify-db-account",
                name="Classify",
                type=AccountType.bank,
                currency="EUR",
                color=None,
                notes=None,
                is_archived=False,
                archived_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            AccountMemberModel(
                id="classify-db-member",
                account_id="classify-db-account",
                user_id="classify-db-user",
                role=AccountMemberRole.owner,
                relation_type=AccountRelationType.owner,
                invited_by_id=None,
                accepted_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            ImportBatchModel(
                id="classify-db-batch",
                user_id="classify-db-user",
                account_id="classify-db-account",
                source=ImportSource.manual,
                filename="rows.csv",
                file_size=1,
                file_encoding="utf-8",
                checksum="a" * 64,
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
                id="classify-db-row",
                import_batch_id="classify-db-batch",
                row_number=2,
                raw_data={
                    "Date": "2026-07-23",
                    "Amount": "10",
                    "Currency": "EUR",
                    "Type": "income",
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
        await session.commit()
    await engine.dispose()


async def _scenario() -> dict:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    principal = AuthenticatedPrincipal(
        user_id="classify-db-user", email="classify@example.com", name="Classify"
    )
    async with AsyncSession(engine) as session:
        await ImportNormalizationService(session).normalize_batch(
            principal=principal, account_id="classify-db-account", batch_id="classify-db-batch"
        )
    async with AsyncSession(engine) as session:
        await ImportDeduplicationService(session).deduplicate_batch(
            principal=principal, account_id="classify-db-account", batch_id="classify-db-batch"
        )
    async with AsyncSession(engine) as session:
        response = await ImportClassificationService(session).classify_batch(
            principal=principal, account_id="classify-db-account", batch_id="classify-db-batch"
        )
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


async def _seed_prepared(prefix: str, memberships: list[tuple[str, AccountMemberRole]]) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    account_id, batch_id = f"{prefix}-account", f"{prefix}-batch"
    user_ids = [user_id for user_id, _ in memberships]
    async with AsyncSession(engine) as session:
        await session.execute(
            delete(ImportRowModel).where(ImportRowModel.import_batch_id == batch_id)
        )
        await session.execute(delete(ImportBatchModel).where(ImportBatchModel.id == batch_id))
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id == account_id)
        )
        await session.execute(delete(AccountModel).where(AccountModel.id == account_id))
        if user_ids:
            await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        for user_id in user_ids:
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
        session.add(
            AccountModel(
                id=account_id,
                name=prefix,
                type=AccountType.bank,
                currency="EUR",
                color=None,
                notes=None,
                is_archived=False,
                archived_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        for user_id, role in memberships:
            session.add(
                AccountMemberModel(
                    id=f"{prefix}-{role.value}-member",
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
        session.add(
            ImportBatchModel(
                id=batch_id,
                user_id=user_ids[0],
                account_id=account_id,
                source=ImportSource.manual,
                filename="prepared.csv",
                file_size=1,
                file_encoding="utf-8",
                checksum=(prefix[0] * 64),
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
                id=f"{prefix}-row",
                import_batch_id=batch_id,
                row_number=2,
                raw_data={"fixture": prefix},
                normalized_data={
                    "schema_version": 1,
                    "source": "manual",
                    "date": "2026-07-24",
                    "amount": "10",
                    "currency": "EUR",
                    "type": "income",
                    "deduplication": {"schema_version": 1, "status": "unique"},
                },
                validation_errors=None,
                deduplication_key=(prefix[-1] * 64),
                status=ImportRowStatus.pending,
                error_message=None,
                created_transaction_id=None,
                created_investment_event_id=None,
                created_at=now,
            )
        )
        await session.commit()
    await engine.dispose()


def _principal_for(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=user_id, email=f"{user_id}@example.com", name=user_id)


async def _reload(prefix: str) -> tuple[ImportBatchModel, ImportRowModel]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        batch = await session.get(ImportBatchModel, f"{prefix}-batch")
        row = await session.get(ImportRowModel, f"{prefix}-row")
        assert batch is not None and row is not None
        session.expunge(batch)
        session.expunge(row)
    await engine.dispose()
    return batch, row


async def _assert_no_posting() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        counts = [
            int(await session.scalar(select(func.count()).select_from(model)) or 0)
            for model in (TransactionModel, InvestmentEventModel, InvestmentMovementModel)
        ]
    await engine.dispose()
    assert counts == [0, 0, 0]


def test_concurrent_classify_requests_are_serialized_and_idempotent() -> None:
    prefix, user_id = "classify-concurrent", "classify-concurrent-owner"

    async def scenario() -> None:
        await _seed_prepared(prefix, [(user_id, AccountMemberRole.owner)])
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL), pool_size=2)

        async def classify_once():
            async with AsyncSession(engine) as session:
                return await ImportClassificationService(session).classify_batch(
                    principal=_principal_for(user_id),
                    account_id=f"{prefix}-account",
                    batch_id=f"{prefix}-batch",
                )

        first, second = await asyncio.wait_for(
            asyncio.gather(classify_once(), classify_once()), timeout=15
        )
        await engine.dispose()
        assert first == second
        assert first.status is ImportStatus.processing and first.rows_classified == 1
        batch, row = await _reload(prefix)
        assert batch.status is ImportStatus.processing
        assert batch.rows_imported == 0 and batch.completed_at is None
        assert row.status is ImportRowStatus.pending
        assert row.normalized_data is not None
        assert row.normalized_data["deduplication"] == {"schema_version": 1, "status": "unique"}
        assert row.normalized_data["posting_intent"]["target"] == "transaction"
        assert row.normalized_data["amount"] == "10"
        await _assert_no_posting()

    asyncio.run(scenario())


def test_commit_failure_rolls_back_and_clean_retry_succeeds() -> None:
    prefix, user_id = "classify-rollback", "classify-rollback-owner"

    async def scenario() -> None:
        await _seed_prepared(prefix, [(user_id, AccountMemberRole.owner)])
        before_batch, before_row = await _reload(prefix)
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            with (
                patch.object(
                    session, "commit", side_effect=RuntimeError("controlled commit failure")
                ),
                pytest.raises(RuntimeError, match="controlled commit failure"),
            ):
                await ImportClassificationService(session).classify_batch(
                    principal=_principal_for(user_id),
                    account_id=f"{prefix}-account",
                    batch_id=f"{prefix}-batch",
                )
        failed_batch, failed_row = await _reload(prefix)
        assert failed_row.normalized_data == before_row.normalized_data
        assert failed_row.status is before_row.status
        assert failed_row.validation_errors == before_row.validation_errors
        assert failed_row.error_message == before_row.error_message
        assert failed_batch.rows_skipped == before_batch.rows_skipped
        await _assert_no_posting()
        async with AsyncSession(engine) as session:
            response = await ImportClassificationService(session).classify_batch(
                principal=_principal_for(user_id),
                account_id=f"{prefix}-account",
                batch_id=f"{prefix}-batch",
            )
        await engine.dispose()
        assert response.rows_classified == 1
        retried_batch, retried_row = await _reload(prefix)
        assert retried_batch.status is ImportStatus.processing
        assert retried_row.normalized_data is not None
        assert retried_row.normalized_data["posting_intent"]["target"] == "transaction"
        assert retried_row.normalized_data["amount"] == "10"
        await _assert_no_posting()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        (AccountMemberRole.owner, True),
        (AccountMemberRole.admin, True),
        (AccountMemberRole.editor, True),
        (AccountMemberRole.viewer, False),
    ],
)
def test_postgresql_authorization_roles(role: AccountMemberRole, allowed: bool) -> None:
    prefix, user_id = f"classify-role-{role.value}", f"classify-role-{role.value}-user"

    async def scenario() -> None:
        await _seed_prepared(prefix, [(user_id, role)])
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            service = ImportClassificationService(session)
            if allowed:
                result = await service.classify_batch(
                    principal=_principal_for(user_id),
                    account_id=f"{prefix}-account",
                    batch_id=f"{prefix}-batch",
                )
                assert result.rows_classified == 1
            else:
                with pytest.raises(AccountAccessDeniedError):
                    await service.classify_batch(
                        principal=_principal_for(user_id),
                        account_id=f"{prefix}-account",
                        batch_id=f"{prefix}-batch",
                    )
        await engine.dispose()
        _, row = await _reload(prefix)
        assert (
            row.normalized_data is not None and "posting_intent" in row.normalized_data
        ) is allowed
        await _assert_no_posting()

    asyncio.run(scenario())


def test_non_member_and_foreign_account_path_are_rejected_without_mutation() -> None:
    prefix = "classify-boundary"
    owner, outsider = "classify-boundary-owner", "classify-boundary-outsider"

    async def scenario() -> None:
        await _seed_prepared(
            prefix, [(owner, AccountMemberRole.owner), (outsider, AccountMemberRole.viewer)]
        )
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            member = await session.scalar(
                select(AccountMemberModel).where(AccountMemberModel.user_id == outsider)
            )
            assert member is not None
            await session.delete(member)
            await session.commit()
        async with AsyncSession(engine) as session:
            with pytest.raises(AccountNotFoundError):
                await ImportClassificationService(session).classify_batch(
                    principal=_principal_for(outsider),
                    account_id=f"{prefix}-account",
                    batch_id=f"{prefix}-batch",
                )
        async with AsyncSession(engine) as session:
            with pytest.raises(AccountNotFoundError):
                await ImportClassificationService(session).classify_batch(
                    principal=_principal_for(owner),
                    account_id="classify-db-account",
                    batch_id=f"{prefix}-batch",
                )
        await engine.dispose()
        _, row = await _reload(prefix)
        assert row.status is ImportRowStatus.pending
        assert row.normalized_data is not None and "posting_intent" not in row.normalized_data
        await _assert_no_posting()

    asyncio.run(scenario())
