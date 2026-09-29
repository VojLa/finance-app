from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.background_jobs import (
    BackgroundJobModel,
    ImportJobAffectedAccountModel,
    ImportJobBatchModel,
)
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    BackgroundJobKind,
    BackgroundJobStatus,
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    TransactionClassification,
)
from app.db.models.imports import (
    ImportBatchModel,
    ImportRowModel,
    ImportSourceOccurrenceModel,
)
from app.db.models.transactions import TransactionModel, TransactionPairModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.imports.classification import TransactionPostingIntent, classify_import_row
from app.modules.imports.classification_service import ImportClassificationService
from app.modules.imports.deduplication import ImportDeduplicationService
from app.modules.imports.parsers import parse_import_file
from app.modules.imports.posting_service import ImportBatchPostingService, PostImportBatchCommand
from app.modules.imports.raiffeisenbank import normalize_raiffeisenbank_import_row
from app.modules.imports.raiffeisenbank_card_multiset import raiffeisenbank_card_full_fingerprint
from app.modules.imports.raiffeisenbank_card_occurrence_repository import (
    RaiffeisenbankCardOccurrenceRepository,
)
from app.modules.imports.raiffeisenbank_reconciliation_repository import (
    RaiffeisenbankReconciliationRepository,
)
from app.modules.imports.raiffeisenbank_reconciliation_service import (
    RaiffeisenbankReconciliationService,
    ReconcileRaiffeisenbankJobCommand,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required"),
]

_FIXTURES = Path(__file__).parents[3] / "test_imports" / "RB"
_PYTHON_ROOT = Path(__file__).resolve().parents[1]
_BASELINE = _PYTHON_ROOT / "database" / "baseline" / "schema.sql"
_ALEMBIC = _PYTHON_ROOT / "alembic.ini"
_NOW = datetime(2026, 8, 20, 12)


async def _create_database() -> tuple[asyncpg.Connection, str, str]:
    assert DATABASE_URL is not None
    source_url = make_url(normalize_database_url(DATABASE_URL))
    database_name = f"finance_app_rb_occurrence_{uuid4().hex}"
    admin_url = source_url.set(drivername="postgresql", database="postgres")
    target_url = source_url.set(database=database_name)
    admin = await asyncpg.connect(admin_url.render_as_string(hide_password=False))
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    target_dsn = target_url.set(drivername="postgresql").render_as_string(hide_password=False)
    target = await asyncpg.connect(target_dsn)
    try:
        await target.execute(
            _BASELINE.read_text(encoding="utf-8").replace('CREATE SCHEMA "public";\n', "", 1)
        )
    finally:
        await target.close()
    migration_env = os.environ.copy()
    migration_env["DATABASE_URL"] = target_url.render_as_string(hide_password=False)
    try:
        for action in (("stamp", "3d0001base"), ("upgrade", "head")):
            subprocess.run(
                [sys.executable, "-m", "alembic", "-c", str(_ALEMBIC), *action],
                cwd=_PYTHON_ROOT,
                env=migration_env,
                check=True,
                capture_output=True,
                text=True,
            )
    except BaseException:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin.close()
        raise
    return admin, database_name, target_url.render_as_string(hide_password=False)


async def _drop_database(admin: asyncpg.Connection, database_name: str) -> None:
    try:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
    finally:
        await admin.close()


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(user_id=user_id, email=f"{user_id}@example.test", name=None)


def _running_job(*, job_id: str, user_id: str, account_id: str) -> BackgroundJobModel:
    return BackgroundJobModel(
        id=job_id,
        user_id=user_id,
        account_id=account_id,
        kind=BackgroundJobKind.import_workflow,
        status=BackgroundJobStatus.running,
        idempotency_key=f"{job_id}-key",
        payload={"batch_ids": ["placeholder"]},
        checkpoint={},
        progress={},
        result=None,
        error_code=None,
        error_message=None,
        attempt_count=1,
        manual_retry_count=0,
        max_attempts=3,
        run_after=_NOW,
        lease_owner="rb-occurrence-worker",
        lease_version=1,
        lease_expires_at=_NOW + timedelta(minutes=5),
        lease_heartbeat_at=_NOW,
        started_at=_NOW,
        finished_at=None,
        created_at=_NOW,
        updated_at=_NOW,
    )


async def _seed_card_manifest(database_url: str, prefix: str) -> tuple[str, str, tuple[str, str]]:
    user_id = f"{prefix}-user"
    account_id = f"{prefix}-credit"
    job_id = f"{prefix}-job"
    batch_ids = (f"{prefix}-credit-current", f"{prefix}-credit-history")
    engine = create_async_engine(normalize_database_url(database_url))
    try:
        async with AsyncSession(engine) as session:
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{prefix}@example.test",
                    name=None,
                    password_hash=None,
                    base_currency="CZK",
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            session.add(
                AccountModel(
                    id=account_id,
                    name="RB Credit CZK",
                    type=AccountType.credit_card,
                    currency="CZK",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            await session.flush()
            session.add(
                AccountMemberModel(
                    id=f"{prefix}-member",
                    account_id=account_id,
                    user_id=user_id,
                    role=AccountMemberRole.owner,
                    relation_type=AccountRelationType.owner,
                    invited_by_id=None,
                    accepted_at=_NOW,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            job = _running_job(job_id=job_id, user_id=user_id, account_id=account_id)
            job.payload = {"batch_ids": list(sorted(batch_ids))}
            session.add(job)
            for filename, batch_id in zip(("Credit.csv", "Credit 2.csv"), batch_ids, strict=True):
                raw_rows = parse_import_file(
                    ImportSource.raiffeisenbank,
                    (_FIXTURES / filename).read_bytes(),
                    encoding=None,
                )
                session.add(
                    ImportBatchModel(
                        id=batch_id,
                        user_id=user_id,
                        account_id=account_id,
                        source=ImportSource.raiffeisenbank,
                        filename=filename,
                        file_size=(_FIXTURES / filename).stat().st_size,
                        file_encoding="utf-8",
                        checksum=hashlib.sha256(filename.encode()).hexdigest(),
                        status=ImportStatus.processing,
                        rows_total=len(raw_rows),
                        rows_imported=0,
                        rows_skipped=0,
                        created_at=_NOW,
                        completed_at=None,
                        retain_until=None,
                        raw_data_purged_at=None,
                    )
                )
                # The normalized manifest FK is composite and SQLAlchemy has
                # no ORM relationship between these independent evidence
                # models, so make the referenced batch visible first.
                await session.flush()
                session.add(
                    ImportJobBatchModel(
                        job_id=job_id,
                        batch_id=batch_id,
                        user_id=user_id,
                        account_id=account_id,
                        created_at=_NOW,
                    )
                )
                for row in raw_rows:
                    normalized = normalize_raiffeisenbank_import_row(
                        account_id=account_id,
                        raw_data=row.raw_data,
                    )
                    assert normalized.data is not None and normalized.deduplication_key is not None
                    session.add(
                        ImportRowModel(
                            id=f"{batch_id}-row-{row.row_number}",
                            import_batch_id=batch_id,
                            row_number=row.row_number,
                            raw_data=row.raw_data,
                            normalized_data=normalized.data,
                            validation_errors=None,
                            deduplication_key=normalized.deduplication_key,
                            status=ImportRowStatus.pending,
                            error_message=None,
                            created_transaction_id=None,
                            created_investment_event_id=None,
                            created_at=_NOW,
                        )
                    )
            await session.commit()
    finally:
        await engine.dispose()
    return user_id, job_id, batch_ids


async def _deduplicate(
    database_url: str, *, user_id: str, account_id: str, batch_id: str, job_id: str
):
    engine = create_async_engine(normalize_database_url(database_url))
    try:
        async with AsyncSession(engine) as session:
            return await ImportDeduplicationService(session).deduplicate_batch(
                principal=_principal(user_id),
                account_id=account_id,
                batch_id=batch_id,
                job_id=job_id,
            )
    finally:
        await engine.dispose()


async def _classify_and_post(
    database_url: str, *, user_id: str, account_id: str, batch_id: str
) -> None:
    engine = create_async_engine(normalize_database_url(database_url))
    try:
        async with AsyncSession(engine) as session:
            await ImportClassificationService(session).classify_batch(
                principal=_principal(user_id), account_id=account_id, batch_id=batch_id
            )
        async with AsyncSession(engine) as session:
            await ImportBatchPostingService(session).post_batch(
                PostImportBatchCommand(
                    principal=_principal(user_id), account_id=account_id, batch_id=batch_id
                )
            )
    finally:
        await engine.dispose()


def _matching_basic_and_savings_rows() -> tuple[dict[str, str | None], dict[str, str | None]]:
    basic = parse_import_file(
        ImportSource.raiffeisenbank, (_FIXTURES / "Basic CZK.csv").read_bytes(), encoding=None
    )
    savings = parse_import_file(
        ImportSource.raiffeisenbank, (_FIXTURES / "Savings.csv").read_bytes(), encoding=None
    )
    basic_by_provider_id = {row.raw_data.get("Id transakce"): row.raw_data for row in basic}
    for row in savings:
        provider_id = row.raw_data.get("Id transakce")
        if provider_id and provider_id in basic_by_provider_id:
            return basic_by_provider_id[provider_id], row.raw_data
    raise AssertionError("Expected a reciprocal Basic/Savings fixture row.")


async def _seed_late_arrival_pair(database_url: str, prefix: str) -> tuple[str, str, str]:
    user_id = f"{prefix}-user"
    basic_id, savings_id = f"{prefix}-basic", f"{prefix}-savings"
    prior_job_id, current_job_id = f"{prefix}-prior-job", f"{prefix}-current-job"
    prior_batch_id, current_batch_id = f"{prefix}-prior-batch", f"{prefix}-current-batch"
    basic_raw, savings_raw = _matching_basic_and_savings_rows()
    engine = create_async_engine(normalize_database_url(database_url))
    try:
        async with AsyncSession(engine) as session:
            session.add(
                UserModel(
                    id=user_id,
                    email=f"{prefix}@example.test",
                    name=None,
                    password_hash=None,
                    base_currency="CZK",
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            for account_id, name, account_type in (
                (basic_id, "RB Basic", AccountType.bank),
                (savings_id, "RB Savings", AccountType.savings),
            ):
                session.add(
                    AccountModel(
                        id=account_id,
                        name=name,
                        type=account_type,
                        currency="CZK",
                        color=None,
                        notes=None,
                        is_archived=False,
                        archived_at=None,
                        created_at=_NOW,
                        updated_at=_NOW,
                    )
                )
            await session.flush()
            for account_id in (basic_id, savings_id):
                session.add(
                    AccountMemberModel(
                        id=f"{prefix}-member-{account_id}",
                        account_id=account_id,
                        user_id=user_id,
                        role=AccountMemberRole.owner,
                        relation_type=AccountRelationType.owner,
                        invited_by_id=None,
                        accepted_at=_NOW,
                        created_at=_NOW,
                        updated_at=_NOW,
                    )
                )
            session.add(
                BackgroundJobModel(
                    id=prior_job_id,
                    user_id=user_id,
                    account_id=basic_id,
                    kind=BackgroundJobKind.import_workflow,
                    status=BackgroundJobStatus.completed,
                    idempotency_key=f"{prior_job_id}-key",
                    payload={"batch_ids": [prior_batch_id]},
                    checkpoint={},
                    progress={},
                    result={"status": "completed"},
                    error_code=None,
                    error_message=None,
                    attempt_count=1,
                    manual_retry_count=0,
                    max_attempts=3,
                    run_after=_NOW,
                    lease_owner=None,
                    lease_version=1,
                    lease_expires_at=None,
                    lease_heartbeat_at=None,
                    started_at=_NOW,
                    finished_at=_NOW,
                    created_at=_NOW,
                    updated_at=_NOW,
                )
            )
            current_job = _running_job(
                job_id=current_job_id,
                user_id=user_id,
                account_id=savings_id,
            )
            current_job.payload = {"batch_ids": [current_batch_id]}
            session.add(current_job)
            await session.flush()
            for batch_id, account_id, raw in (
                (prior_batch_id, basic_id, basic_raw),
                (current_batch_id, savings_id, savings_raw),
            ):
                normalized = normalize_raiffeisenbank_import_row(
                    account_id=account_id,
                    raw_data=raw,
                )
                assert normalized.data is not None
                intent = classify_import_row(
                    source=ImportSource.raiffeisenbank,
                    normalized_data=normalized.data,
                )
                assert isinstance(intent, TransactionPostingIntent)
                transaction_id = f"{batch_id}-tx"
                session.add(
                    ImportBatchModel(
                        id=batch_id,
                        user_id=user_id,
                        account_id=account_id,
                        source=ImportSource.raiffeisenbank,
                        filename=f"{batch_id}.csv",
                        file_size=1,
                        file_encoding="utf-8",
                        checksum=hashlib.sha256(batch_id.encode()).hexdigest(),
                        status=ImportStatus.completed,
                        rows_total=1,
                        rows_imported=1,
                        rows_skipped=0,
                        created_at=_NOW,
                        completed_at=_NOW,
                        retain_until=None,
                        raw_data_purged_at=None,
                    )
                )
                await session.flush()
                session.add(
                    ImportJobBatchModel(
                        job_id=prior_job_id if batch_id == prior_batch_id else current_job_id,
                        batch_id=batch_id,
                        user_id=user_id,
                        account_id=account_id,
                        created_at=_NOW,
                    )
                )
                session.add(
                    TransactionModel(
                        id=transaction_id,
                        account_id=account_id,
                        import_batch_id=batch_id,
                        date=datetime.fromisoformat(intent.date),
                        booking_date=None,
                        amount=intent.amount,
                        currency=intent.currency,
                        reporting_amount=None,
                        reporting_currency=None,
                        type=intent.transaction_type,
                        classification=intent.transaction_classification,
                        description=normalized.data.get("description"),
                        note=None,
                        counterparty=normalized.data.get("counterparty"),
                        external_id=normalized.data.get("external_id"),
                        is_reviewed=False,
                        archived_at=None,
                        deleted_at=None,
                        category_id=None,
                        created_at=_NOW,
                        updated_at=_NOW,
                    )
                )
                session.add(
                    ImportRowModel(
                        id=f"{batch_id}-row",
                        import_batch_id=batch_id,
                        row_number=1,
                        raw_data=raw,
                        normalized_data=normalized.data,
                        validation_errors=None,
                        deduplication_key=normalized.deduplication_key,
                        status=ImportRowStatus.imported,
                        error_message=None,
                        created_transaction_id=transaction_id,
                        created_investment_event_id=None,
                        created_at=_NOW,
                    )
                )
            await session.commit()
    finally:
        await engine.dispose()
    return user_id, current_job_id, prior_job_id


@pytest.mark.asyncio
async def test_disposable_postgresql_card_manifest_multiset_posting_linkage_and_replay() -> None:
    admin, database_name, database_url = await _create_database()
    engine = create_async_engine(normalize_database_url(database_url))
    try:
        prefix = f"rb-card-multiset-{uuid4().hex}"
        user_id, job_id, batch_ids = await _seed_card_manifest(database_url, prefix)
        account_id = f"{prefix}-credit"

        first = await _deduplicate(
            database_url,
            user_id=user_id,
            account_id=account_id,
            batch_id=batch_ids[0],
            job_id=job_id,
        )
        second = await _deduplicate(
            database_url,
            user_id=user_id,
            account_id=account_id,
            batch_id=batch_ids[1],
            job_id=job_id,
        )
        assert (first.rows_total, first.rows_unique, first.rows_duplicate) == (1000, 1000, 0)
        assert (second.rows_total, second.rows_unique, second.rows_duplicate) == (1000, 984, 16)

        async with AsyncSession(engine) as session:
            assert await session.scalar(select(func.count()).select_from(ImportRowModel)) == 2_000
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ImportRowModel)
                    .where(ImportRowModel.status == ImportRowStatus.pending)
                )
                == 1_984
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ImportRowModel)
                    .where(ImportRowModel.status == ImportRowStatus.duplicate)
                )
                == 16
            )
            occurrences = tuple(
                await session.scalars(
                    select(ImportSourceOccurrenceModel).order_by(
                        ImportSourceOccurrenceModel.fingerprint_hash
                    )
                )
            )
            assert len(occurrences) == 1_984
            assert all(item.canonical_transaction_id is None for item in occurrences)
            rows = tuple(await session.scalars(select(ImportRowModel)))
            rows_by_fingerprint: dict[str, list[ImportRowModel]] = {}
            for row in rows:
                if row.import_batch_id in batch_ids:
                    rows_by_fingerprint.setdefault(
                        f"{row.import_batch_id}:{raiffeisenbank_card_full_fingerprint(raw_data=row.raw_data)}",
                        [],
                    ).append(row)
            within_file_repeats = {
                row.id
                for group in rows_by_fingerprint.values()
                for row in sorted(group, key=lambda value: value.row_number)[1:]
            }
            assert len(within_file_repeats) == 36
            amounts_by_row_id: dict[str, Decimal] = {}
            for row in rows:
                assert isinstance(row.normalized_data, dict)
                amounts_by_row_id[row.id] = Decimal(str(row.normalized_data["amount"]))
            assert sum(
                (-amounts_by_row_id[row_id] for row_id in within_file_repeats), Decimal()
            ) == Decimal("1751")

        for batch_id in batch_ids:
            await _classify_and_post(
                database_url, user_id=user_id, account_id=account_id, batch_id=batch_id
            )

        async with AsyncSession(engine) as session:
            assert await session.scalar(select(func.count()).select_from(TransactionModel)) == 1_984
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(ImportRowModel)
                    .where(ImportRowModel.status == ImportRowStatus.imported)
                )
                == 1_984
            )
            result = await RaiffeisenbankReconciliationService(session).reconcile(
                command=ReconcileRaiffeisenbankJobCommand(job_id, user_id, _NOW)
            )
            assert (result.pairs_created, result.pairs_replayed, result.pair_ids) == (0, 0, ())

        async with AsyncSession(engine) as session:
            linked = tuple(
                await session.scalars(
                    select(ImportSourceOccurrenceModel).where(
                        ImportSourceOccurrenceModel.canonical_transaction_id.is_not(None)
                    )
                )
            )
            assert len(linked) == 1_984
            assert len({item.canonical_transaction_id for item in linked}) == 1_984
            replay = await RaiffeisenbankReconciliationService(session).reconcile(
                command=ReconcileRaiffeisenbankJobCommand(job_id, user_id, _NOW)
            )
            assert (replay.pairs_created, replay.pairs_replayed, replay.pair_ids) == (0, 0, ())
    finally:
        await engine.dispose()
        await _drop_database(admin, database_name)


@pytest.mark.asyncio
async def test_disposable_postgresql_late_arrival_uses_only_current_and_completed_jobs() -> None:
    admin, database_name, database_url = await _create_database()
    engine = create_async_engine(normalize_database_url(database_url))
    try:
        prefix = f"rb-late-arrival-{uuid4().hex}"
        user_id, current_job_id, prior_job_id = await _seed_late_arrival_pair(database_url, prefix)
        async with AsyncSession(engine) as session:
            current, evidence = await RaiffeisenbankReconciliationRepository(
                session
            ).load_current_and_completed_evidence_for_update(
                current_job_id=current_job_id,
                user_id=user_id,
            )
            assert current.id == current_job_id
            assert {row.job.id for row in evidence} == {current_job_id, prior_job_id}
            result = await RaiffeisenbankReconciliationService(session).reconcile(
                command=ReconcileRaiffeisenbankJobCommand(current_job_id, user_id, _NOW)
            )
            assert (result.pairs_created, result.pairs_replayed) == (1, 0)
            assert result.affected_account_ids == (
                f"{prefix}-basic",
                f"{prefix}-savings",
            )

        async with AsyncSession(engine) as session:
            pairs = tuple(await session.scalars(select(TransactionPairModel)))
            assert len(pairs) == 1
            assert pairs[0].classification is TransactionClassification.internal_transfer
            assert pairs[0].background_job_id == current_job_id
            affected = tuple(await session.scalars(select(ImportJobAffectedAccountModel)))
            assert {(item.job_id, item.account_id) for item in affected} == {
                (current_job_id, f"{prefix}-basic"),
                (current_job_id, f"{prefix}-savings"),
            }
            replay = await RaiffeisenbankReconciliationService(session).reconcile(
                command=ReconcileRaiffeisenbankJobCommand(current_job_id, user_id, _NOW)
            )
            assert (replay.pairs_created, replay.pairs_replayed) == (0, 1)

            extra_batch_id = f"{prefix}-extra-manifest-batch"
            session.add(
                ImportBatchModel(
                    id=extra_batch_id,
                    user_id=user_id,
                    account_id=f"{prefix}-savings",
                    source=ImportSource.raiffeisenbank,
                    filename="unexpected.csv",
                    file_size=1,
                    file_encoding="utf-8",
                    checksum=hashlib.sha256(extra_batch_id.encode()).hexdigest(),
                    status=ImportStatus.processing,
                    rows_total=0,
                    rows_imported=0,
                    rows_skipped=0,
                    created_at=_NOW,
                    completed_at=None,
                    retain_until=None,
                    raw_data_purged_at=None,
                )
            )
            await session.flush()
            session.add(
                ImportJobBatchModel(
                    job_id=current_job_id,
                    batch_id=extra_batch_id,
                    user_id=user_id,
                    account_id=f"{prefix}-savings",
                    created_at=_NOW,
                )
            )
            await session.commit()

        async with AsyncSession(engine) as session:
            with pytest.raises(RuntimeError, match="manifest does not match"):
                await RaiffeisenbankCardOccurrenceRepository(
                    session
                ).load_manifested_card_rows_for_update(
                    job_id=current_job_id,
                    user_id=user_id,
                    account_id=f"{prefix}-savings",
                )
    finally:
        await engine.dispose()
        await _drop_database(admin, database_name)
