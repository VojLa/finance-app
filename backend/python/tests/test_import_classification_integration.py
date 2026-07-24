from __future__ import annotations

import asyncio
import os
from copy import deepcopy
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
from app.modules.imports.classification_service import (
    ImportClassificationService,
    ImportClassifyStateError,
)
from app.modules.imports.deduplication import ImportDeduplicationService
from app.modules.imports.normalization import ImportNormalizationService
from app.modules.imports.service import ImportBatchNotFoundError

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


async def _seed_raw(
    prefix: str,
    source: ImportSource,
    rows: list[dict[str, str]],
) -> str:
    user_id = f"{prefix}-owner"
    await _seed_prepared(prefix, [(user_id, AccountMemberRole.owner)])
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    async with AsyncSession(engine) as session:
        await session.execute(
            delete(ImportRowModel).where(ImportRowModel.import_batch_id == f"{prefix}-batch")
        )
        batch = await session.get(ImportBatchModel, f"{prefix}-batch")
        assert batch is not None
        batch.source = source
        batch.rows_total = len(rows)
        for index, raw_data in enumerate(rows, start=2):
            session.add(
                ImportRowModel(
                    id=f"{prefix}-row-{index}",
                    import_batch_id=f"{prefix}-batch",
                    row_number=index,
                    raw_data=raw_data,
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
    return user_id


async def _run_workflow(prefix: str, user_id: str):
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    principal = _principal_for(user_id)
    async with AsyncSession(engine) as session:
        await ImportNormalizationService(session).normalize_batch(
            principal=principal,
            account_id=f"{prefix}-account",
            batch_id=f"{prefix}-batch",
        )
    async with AsyncSession(engine) as session:
        await ImportDeduplicationService(session).deduplicate_batch(
            principal=principal,
            account_id=f"{prefix}-account",
            batch_id=f"{prefix}-batch",
        )
    async with AsyncSession(engine) as session:
        response = await ImportClassificationService(session).classify_batch(
            principal=principal,
            account_id=f"{prefix}-account",
            batch_id=f"{prefix}-batch",
        )
    await engine.dispose()
    return response


async def _reload_rows(prefix: str) -> list[ImportRowModel]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        rows = list(
            (
                await session.scalars(
                    select(ImportRowModel)
                    .where(ImportRowModel.import_batch_id == f"{prefix}-batch")
                    .order_by(ImportRowModel.row_number)
                )
            ).all()
        )
        for row in rows:
            session.expunge(row)
    await engine.dispose()
    return rows


async def _reload_batch_and_rows(
    prefix: str,
) -> tuple[ImportBatchModel, list[ImportRowModel]]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        batch = await session.get(ImportBatchModel, f"{prefix}-batch")
        rows = list(
            (
                await session.scalars(
                    select(ImportRowModel)
                    .where(ImportRowModel.import_batch_id == f"{prefix}-batch")
                    .order_by(ImportRowModel.row_number)
                )
            ).all()
        )
        assert batch is not None
        session.expunge(batch)
        for row in rows:
            session.expunge(row)
    await engine.dispose()
    return batch, rows


async def _normalize(prefix: str, user_id: str):
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        response = await ImportNormalizationService(session).normalize_batch(
            principal=_principal_for(user_id),
            account_id=f"{prefix}-account",
            batch_id=f"{prefix}-batch",
        )
    await engine.dispose()
    return response


async def _deduplicate(prefix: str, user_id: str):
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        response = await ImportDeduplicationService(session).deduplicate_batch(
            principal=_principal_for(user_id),
            account_id=f"{prefix}-account",
            batch_id=f"{prefix}-batch",
        )
    await engine.dispose()
    return response


async def _classify(prefix: str, user_id: str):
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        response = await ImportClassificationService(session).classify_batch(
            principal=_principal_for(user_id),
            account_id=f"{prefix}-account",
            batch_id=f"{prefix}-batch",
        )
    await engine.dispose()
    return response


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


def test_non_member_is_rejected_without_mutation() -> None:
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
        await engine.dispose()
        _, row = await _reload(prefix)
        assert row.status is ImportRowStatus.pending
        assert row.normalized_data is not None and "posting_intent" not in row.normalized_data
        await _assert_no_posting()

    asyncio.run(scenario())


def test_foreign_account_batch_path_uses_account_scoped_not_found() -> None:
    account_a = "classify-foreign-a"
    account_b = "classify-foreign-b"
    owner_a = "classify-foreign-owner-a"
    writer_b = "classify-foreign-writer-b"

    async def scenario() -> None:
        await _seed_prepared(account_a, [(owner_a, AccountMemberRole.owner)])
        await _seed_prepared(account_b, [(writer_b, AccountMemberRole.editor)])
        before_batch, before_rows = await _reload_batch_and_rows(account_a)
        assert len(before_rows) == 1
        before_row = before_rows[0]
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            with pytest.raises(ImportBatchNotFoundError):
                await ImportClassificationService(session).classify_batch(
                    principal=_principal_for(writer_b),
                    account_id=f"{account_b}-account",
                    batch_id=f"{account_a}-batch",
                )
        await engine.dispose()

        after_batch, after_rows = await _reload_batch_and_rows(account_a)
        assert len(after_rows) == 1
        after_row = after_rows[0]
        assert after_batch.status is before_batch.status
        assert after_batch.rows_total == before_batch.rows_total
        assert after_batch.rows_imported == before_batch.rows_imported
        assert after_batch.rows_skipped == before_batch.rows_skipped
        assert after_batch.completed_at == before_batch.completed_at
        assert after_row.status is before_row.status
        assert after_row.normalized_data == before_row.normalized_data
        assert after_row.deduplication_key == before_row.deduplication_key
        assert after_row.validation_errors == before_row.validation_errors
        assert after_row.error_message == before_row.error_message
        assert after_row.normalized_data is not None
        assert "posting_intent" not in after_row.normalized_data
        await _assert_no_posting()

    asyncio.run(scenario())


def test_provider_normalize_deduplicate_classify_matrix() -> None:
    async def scenario() -> None:
        rb_prefix = "classify-provider-rb"
        rb_user = await _seed_raw(
            rb_prefix,
            ImportSource.raiffeisenbank,
            [
                {
                    "Datum": "24.07.2026",
                    "Částka": "10",
                    "Měna": "EUR",
                    "Typ": "Převod",
                }
            ],
        )
        rb_response = await _run_workflow(rb_prefix, rb_user)
        rb_row = (await _reload_rows(rb_prefix))[0]
        assert rb_response.rows_needs_review == 1
        assert rb_row.status is ImportRowStatus.needs_review
        assert rb_row.normalized_data is not None
        assert rb_row.normalized_data["posting_intent"]["target"] == "needs_review"

        t212_prefix = "classify-provider-t212"
        t212_user = await _seed_raw(
            t212_prefix,
            ImportSource.trading212,
            [
                {
                    "Action": "Market buy",
                    "Time": "2026-07-24T10:00:00Z",
                    "Ticker": "VWCE",
                    "No. of shares": "2",
                    "Total": "201",
                    "Currency (Total)": "EUR",
                    "ID": "provider-buy",
                }
            ],
        )
        await _run_workflow(t212_prefix, t212_user)
        t212_row = (await _reload_rows(t212_prefix))[0]
        assert t212_row.normalized_data is not None
        assert t212_row.normalized_data["posting_intent"]["target"] == "investment_event"
        assert t212_row.normalized_data["posting_intent"]["action"] == "buy"

        any_prefix = "classify-provider-anycoin"
        any_user = await _seed_raw(
            any_prefix,
            ImportSource.anycoin,
            [
                {
                    "Type": "trade payment",
                    "Order ID": "provider-order",
                    "Date": "2026-07-24T10:00:00Z",
                    "Amount": "-100",
                    "Currency": "EUR",
                },
                {
                    "Type": "trade fill",
                    "Order ID": "provider-order",
                    "Date": "2026-07-24T10:01:00Z",
                    "Amount": "0.01",
                    "Currency": "BTC",
                },
                {
                    "Type": "deposit",
                    "Date": "2026-07-24T11:00:00Z",
                    "Amount": "1",
                    "Currency": "ETH",
                },
                {
                    "Type": "withdrawal",
                    "Date": "2026-07-24T12:00:00Z",
                    "Amount": "1",
                    "Currency": "SOL",
                },
            ],
        )
        await _run_workflow(any_prefix, any_user)
        any_rows = await _reload_rows(any_prefix)
        payment, anchor, deposit, withdrawal = any_rows
        assert payment.status is ImportRowStatus.skipped
        assert payment.normalized_data is not None
        assert "posting_intent" not in payment.normalized_data
        assert anchor.normalized_data is not None
        assert anchor.normalized_data["posting_intent"]["order_id"] == "provider-order"
        assert deposit.normalized_data is not None
        assert deposit.normalized_data["posting_intent"]["asset_direction"] == "in"
        assert withdrawal.normalized_data is not None
        assert withdrawal.normalized_data["posting_intent"]["asset_direction"] == "out"
        await _assert_no_posting()

    asyncio.run(scenario())


def test_duplicate_loser_remains_non_postable_after_classification() -> None:
    prefix = "classify-duplicate-proof"

    async def scenario() -> None:
        raw = {
            "Date": "2026-07-25",
            "Amount": "42",
            "Currency": "EUR",
            "Type": "income",
            "Description": "same logical row",
        }
        user_id = await _seed_raw(prefix, ImportSource.manual, [raw, dict(raw)])
        await _normalize(prefix, user_id)
        _, normalized_rows = await _reload_batch_and_rows(prefix)
        assert len(normalized_rows) == 2
        loser_canonical = deepcopy(normalized_rows[1].normalized_data)
        assert loser_canonical is not None

        await _deduplicate(prefix, user_id)
        response = await _classify(prefix, user_id)
        assert response.rows_classified == 1
        assert response.rows_duplicate == 1

        batch, rows = await _reload_batch_and_rows(prefix)
        winner, loser = rows
        assert winner.status is ImportRowStatus.pending
        assert winner.normalized_data is not None
        assert winner.normalized_data["deduplication"] == {
            "schema_version": 1,
            "status": "unique",
        }
        assert winner.normalized_data["posting_intent"]["target"] == "transaction"
        assert winner.deduplication_key is not None
        assert winner.created_transaction_id is None
        assert winner.created_investment_event_id is None

        assert loser.status is ImportRowStatus.duplicate
        assert loser.normalized_data is not None
        assert loser.normalized_data["deduplication"] == {
            "schema_version": 1,
            "status": "duplicate",
        }
        assert "posting_intent" not in loser.normalized_data
        assert loser.deduplication_key is not None
        assert loser.created_transaction_id is None
        assert loser.created_investment_event_id is None
        loser_after = deepcopy(loser.normalized_data)
        loser_after.pop("deduplication")
        assert loser_after == loser_canonical
        assert batch.status is ImportStatus.processing
        assert batch.rows_imported == 0
        assert batch.completed_at is None
        await _assert_no_posting()

    asyncio.run(scenario())


def test_failed_and_normalization_review_rows_are_preserved() -> None:
    prefix = "classify-preserved-proof"

    async def scenario() -> None:
        user_id = await _seed_raw(
            prefix,
            ImportSource.manual,
            [
                {
                    "Date": "2026-07-25",
                    "Amount": "10",
                    "Currency": "EUR",
                    "Type": "income",
                },
                {"fixture": "parser failed"},
                {
                    "Amount": "20",
                    "Currency": "EUR",
                    "Type": "income",
                },
            ],
        )
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            failed = await session.get(ImportRowModel, f"{prefix}-row-3")
            assert failed is not None
            failed.status = ImportRowStatus.failed
            failed.validation_errors = [
                {
                    "field": "row",
                    "code": "parser_error",
                    "message": "Controlled parser failure.",
                }
            ]
            failed.error_message = "Row failed during parsing."
            await session.commit()
        await engine.dispose()

        await _normalize(prefix, user_id)
        await _deduplicate(prefix, user_id)
        _, before_rows = await _reload_batch_and_rows(prefix)
        successful_before, failed_before, review_before = before_rows
        assert successful_before.status is ImportRowStatus.pending
        assert failed_before.status is ImportRowStatus.failed
        assert review_before.status is ImportRowStatus.needs_review
        failed_snapshot = (
            failed_before.status,
            deepcopy(failed_before.normalized_data),
            failed_before.deduplication_key,
            deepcopy(failed_before.validation_errors),
            failed_before.error_message,
        )
        review_snapshot = (
            review_before.status,
            deepcopy(review_before.normalized_data),
            review_before.deduplication_key,
            deepcopy(review_before.validation_errors),
            review_before.error_message,
        )

        response = await _classify(prefix, user_id)
        assert response.model_dump() == {
            "batch_id": f"{prefix}-batch",
            "status": ImportStatus.processing,
            "rows_total": 3,
            "rows_classified": 1,
            "rows_needs_review": 1,
            "rows_duplicate": 0,
            "rows_skipped": 0,
            "rows_failed": 1,
        }
        batch, after_rows = await _reload_batch_and_rows(prefix)
        successful_after, failed_after, review_after = after_rows
        assert successful_after.normalized_data is not None
        assert successful_after.normalized_data["posting_intent"]["target"] == "transaction"
        assert (
            failed_after.status,
            failed_after.normalized_data,
            failed_after.deduplication_key,
            failed_after.validation_errors,
            failed_after.error_message,
        ) == failed_snapshot
        assert (
            review_after.status,
            review_after.normalized_data,
            review_after.deduplication_key,
            review_after.validation_errors,
            review_after.error_message,
        ) == review_snapshot
        assert batch.status is ImportStatus.processing
        assert batch.rows_total == 3
        assert batch.rows_imported == 0
        assert batch.rows_skipped == 2
        assert batch.completed_at is None
        await _assert_no_posting()

    asyncio.run(scenario())


def test_classify_before_deduplicate_returns_409_without_mutation() -> None:
    prefix = "classify-before-dedup-proof"

    async def scenario() -> None:
        user_id = await _seed_raw(
            prefix,
            ImportSource.manual,
            [
                {
                    "Date": "2026-07-25",
                    "Amount": "10",
                    "Currency": "EUR",
                    "Type": "income",
                }
            ],
        )
        await _normalize(prefix, user_id)
        before_batch, before_rows = await _reload_batch_and_rows(prefix)
        assert len(before_rows) == 1
        before_row = before_rows[0]
        assert before_row.normalized_data is not None
        assert "deduplication" not in before_row.normalized_data
        assert "posting_intent" not in before_row.normalized_data

        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            with pytest.raises(ImportClassifyStateError) as exc_info:
                await ImportClassificationService(session).classify_batch(
                    principal=_principal_for(user_id),
                    account_id=f"{prefix}-account",
                    batch_id=f"{prefix}-batch",
                )
        await engine.dispose()
        assert exc_info.value.code == "import_classify_state_invalid"
        assert exc_info.value.status_code == 409

        after_batch, after_rows = await _reload_batch_and_rows(prefix)
        assert len(after_rows) == 1
        after_row = after_rows[0]
        assert after_row.status is before_row.status
        assert after_row.normalized_data == before_row.normalized_data
        assert after_row.deduplication_key == before_row.deduplication_key
        assert after_row.validation_errors == before_row.validation_errors
        assert after_row.error_message == before_row.error_message
        assert after_row.normalized_data is not None
        assert "deduplication" not in after_row.normalized_data
        assert "posting_intent" not in after_row.normalized_data
        assert after_batch.rows_total == before_batch.rows_total
        assert after_batch.rows_imported == before_batch.rows_imported
        assert after_batch.rows_skipped == before_batch.rows_skipped
        assert after_batch.completed_at == before_batch.completed_at
        await _assert_no_posting()

    asyncio.run(scenario())


def test_successful_classify_repeat_is_database_idempotent() -> None:
    prefix = "classify-repeat-success"

    async def scenario() -> None:
        user_id = await _seed_raw(
            prefix,
            ImportSource.manual,
            [
                {
                    "Date": "2026-07-25",
                    "Amount": "-15",
                    "Currency": "EUR",
                    "Type": "expense",
                }
            ],
        )
        first = await _run_workflow(prefix, user_id)
        first_batch, first_rows = await _reload_batch_and_rows(prefix)
        assert len(first_rows) == 1
        first_row = first_rows[0]
        normalized_snapshot = deepcopy(first_row.normalized_data)
        assert normalized_snapshot is not None
        canonical_snapshot = deepcopy(normalized_snapshot)
        canonical_snapshot.pop("deduplication")
        canonical_snapshot.pop("posting_intent")
        intent_snapshot = deepcopy(normalized_snapshot["posting_intent"])

        second = await _classify(prefix, user_id)
        second_batch, second_rows = await _reload_batch_and_rows(prefix)
        assert len(second_rows) == 1
        second_row = second_rows[0]
        assert second == first
        assert second_row.normalized_data == normalized_snapshot
        assert second_row.normalized_data is not None
        assert second_row.normalized_data["posting_intent"] == intent_snapshot
        second_canonical = deepcopy(second_row.normalized_data)
        second_canonical.pop("deduplication")
        second_canonical.pop("posting_intent")
        assert second_canonical == canonical_snapshot
        assert second_row.status is first_row.status is ImportRowStatus.pending
        assert second_row.validation_errors == first_row.validation_errors
        assert second_row.error_message == first_row.error_message
        assert second_batch.status is first_batch.status is ImportStatus.processing
        assert second_batch.rows_total == first_batch.rows_total
        assert second_batch.rows_imported == first_batch.rows_imported == 0
        assert second_batch.rows_skipped == first_batch.rows_skipped
        assert second_batch.completed_at == first_batch.completed_at is None
        await _assert_no_posting()

    asyncio.run(scenario())


def test_classification_review_repeat_is_database_idempotent() -> None:
    prefix = "classify-repeat-review"

    async def scenario() -> None:
        user_id = await _seed_raw(
            prefix,
            ImportSource.manual,
            [
                {
                    "Date": "2026-07-25",
                    "Amount": "15",
                    "Currency": "EUR",
                    "Type": "transfer",
                }
            ],
        )
        first = await _run_workflow(prefix, user_id)
        first_batch, first_rows = await _reload_batch_and_rows(prefix)
        assert len(first_rows) == 1
        first_row = first_rows[0]
        assert first_row.status is ImportRowStatus.needs_review
        assert first_row.normalized_data is not None
        normalized_snapshot = deepcopy(first_row.normalized_data)
        intent_snapshot = deepcopy(normalized_snapshot["posting_intent"])
        errors_snapshot = deepcopy(first_row.validation_errors)
        message_snapshot = first_row.error_message
        assert intent_snapshot["target"] == "needs_review"
        assert message_snapshot == "Row requires classification review."

        second = await _classify(prefix, user_id)
        second_batch, second_rows = await _reload_batch_and_rows(prefix)
        assert len(second_rows) == 1
        second_row = second_rows[0]
        assert second == first
        assert second_row.status is ImportRowStatus.needs_review
        assert second_row.normalized_data == normalized_snapshot
        assert second_row.normalized_data is not None
        assert second_row.normalized_data["posting_intent"] == intent_snapshot
        assert second_row.validation_errors == errors_snapshot
        assert second_row.error_message == message_snapshot
        assert second_batch.status is first_batch.status is ImportStatus.processing
        assert second_batch.rows_total == first_batch.rows_total
        assert second_batch.rows_imported == first_batch.rows_imported == 0
        assert second_batch.rows_skipped == first_batch.rows_skipped
        assert second_batch.completed_at == first_batch.completed_at is None
        await _assert_no_posting()

    asyncio.run(scenario())
