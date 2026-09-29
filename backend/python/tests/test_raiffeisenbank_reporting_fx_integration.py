from __future__ import annotations

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

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.background_jobs import BackgroundJobModel, ImportJobBatchModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    BackgroundJobKind,
    BackgroundJobStatus,
    ExchangeRateSource,
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    TransactionType,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.prices import ExchangeRateModel
from app.db.models.transactions import TransactionModel, TransactionReportingEvidenceModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.fx.models import ExchangeRateObservation
from app.modules.imports.raiffeisenbank_reporting_fx import (
    AcquireRaiffeisenbankReportingFxCommand,
    RaiffeisenbankReportingFxConflictError,
    RaiffeisenbankReportingFxService,
)
from app.modules.market_data.models import ExchangeRateRequirement
from app.modules.market_data.providers import ExchangeRateProviderRegistry
from app.modules.market_data.source_policy import LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY
from app.modules.market_data.writer import exchange_rate_id

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required"),
]
PYTHON_ROOT = Path(__file__).resolve().parents[1]
BASELINE = PYTHON_ROOT / "database" / "baseline" / "schema.sql"
ALEMBIC = PYTHON_ROOT / "alembic.ini"
CREATED_AT = datetime(2026, 8, 19, 22)


class _Provider:
    source = ExchangeRateSource.yahoo_finance

    def __init__(self, rates: dict[datetime, tuple[Decimal, datetime]]) -> None:
        self.rates = rates
        self.calls: list[tuple[ExchangeRateRequirement, ...]] = []

    async def fetch(self, requirement: ExchangeRateRequirement) -> ExchangeRateObservation:
        return (await self.fetch_many((requirement,)))[0]

    async def fetch_many(
        self,
        requirements: tuple[ExchangeRateRequirement, ...],
    ) -> tuple[ExchangeRateObservation, ...]:
        self.calls.append(requirements)
        return tuple(
            ExchangeRateObservation(
                requirement.from_currency,
                requirement.to_currency,
                self.source,
                self.rates[requirement.through][0],
                self.rates[requirement.through][1],
            )
            for requirement in requirements
        )


async def _seed(
    database_url: str,
    prefix: str,
    *,
    events: tuple[tuple[str, datetime, str, str], ...],
) -> tuple[str, str]:
    user_id = f"{prefix}-user"
    account_id = f"{prefix}-account"
    batch_id = f"{prefix}-batch"
    job_id = f"{prefix}-job"
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
                    created_at=CREATED_AT,
                    updated_at=CREATED_AT,
                )
            )
            session.add(
                AccountModel(
                    id=account_id,
                    name="RB EUR",
                    type=AccountType.bank,
                    currency="EUR",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=CREATED_AT,
                    updated_at=CREATED_AT,
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
                    accepted_at=CREATED_AT,
                    created_at=CREATED_AT,
                    updated_at=CREATED_AT,
                )
            )
            session.add(
                ImportBatchModel(
                    id=batch_id,
                    user_id=user_id,
                    account_id=account_id,
                    source=ImportSource.raiffeisenbank,
                    filename="RB EUR.csv",
                    file_size=100,
                    file_encoding="utf-8",
                    checksum="a" * 64,
                    status=ImportStatus.completed,
                    rows_total=len(events),
                    rows_imported=len(events),
                    rows_skipped=0,
                    created_at=CREATED_AT,
                    completed_at=CREATED_AT,
                    retain_until=None,
                    raw_data_purged_at=None,
                )
            )
            session.add(
                BackgroundJobModel(
                    id=job_id,
                    user_id=user_id,
                    account_id=account_id,
                    kind=BackgroundJobKind.import_workflow,
                    status=BackgroundJobStatus.running,
                    idempotency_key=f"{prefix}-key",
                    payload={"batch_ids": [batch_id]},
                    checkpoint={},
                    progress={},
                    result=None,
                    error_code=None,
                    error_message=None,
                    attempt_count=0,
                    manual_retry_count=0,
                    max_attempts=3,
                    run_after=CREATED_AT,
                    lease_owner=f"{prefix}-worker",
                    lease_version=1,
                    lease_expires_at=CREATED_AT + timedelta(minutes=5),
                    lease_heartbeat_at=CREATED_AT,
                    started_at=CREATED_AT,
                    finished_at=None,
                    created_at=CREATED_AT,
                    updated_at=CREATED_AT,
                )
            )
            await session.flush()
            session.add(
                ImportJobBatchModel(
                    job_id=job_id,
                    batch_id=batch_id,
                    user_id=user_id,
                    account_id=account_id,
                    created_at=CREATED_AT,
                )
            )
            for row_number, (suffix, event_at, amount, currency) in enumerate(events, start=1):
                transaction_id = f"{prefix}-tx-{suffix}"
                session.add(
                    TransactionModel(
                        id=transaction_id,
                        date=event_at,
                        booking_date=None,
                        amount=Decimal(amount),
                        currency=currency,
                        reporting_amount=None,
                        reporting_currency=None,
                        type=TransactionType.expense,
                        classification=None,
                        description="RB evidence",
                        note=None,
                        counterparty=None,
                        external_id=suffix,
                        is_reviewed=False,
                        archived_at=None,
                        deleted_at=None,
                        category_id=None,
                        account_id=account_id,
                        import_batch_id=batch_id,
                        created_at=CREATED_AT,
                        updated_at=CREATED_AT,
                    )
                )
                session.add(
                    ImportRowModel(
                        id=f"{prefix}-row-{suffix}",
                        import_batch_id=batch_id,
                        row_number=row_number,
                        raw_data={"source": "rb"},
                        normalized_data={"schema_version": 1},
                        validation_errors=None,
                        deduplication_key=f"{prefix}-{suffix}",
                        status=ImportRowStatus.imported,
                        error_message=None,
                        created_transaction_id=transaction_id,
                        created_investment_event_id=None,
                        created_at=CREATED_AT,
                    )
                )
            await session.commit()
    finally:
        await engine.dispose()
    return user_id, job_id


@pytest.mark.asyncio
async def test_disposable_postgresql_create_replay_lineage_and_atomic_conflict() -> None:
    assert DATABASE_URL is not None
    source_url = make_url(normalize_database_url(DATABASE_URL))
    database_name = f"finance_app_rb_reporting_fx_{uuid4().hex}"
    admin_url = source_url.set(drivername="postgresql", database="postgres")
    target_url = source_url.set(database=database_name)
    admin = await asyncpg.connect(admin_url.render_as_string(hide_password=False))
    target_database_url = target_url.render_as_string(hide_password=False)
    try:
        await admin.execute(f'CREATE DATABASE "{database_name}"')
        target = await asyncpg.connect(
            target_url.set(drivername="postgresql").render_as_string(hide_password=False)
        )
        try:
            await target.execute(
                BASELINE.read_text(encoding="utf-8").replace('CREATE SCHEMA "public";\n', "", 1)
            )
        finally:
            await target.close()
        migration_env = os.environ.copy()
        migration_env["DATABASE_URL"] = target_database_url
        for action in (("stamp", "3d0001base"), ("upgrade", "head")):
            subprocess.run(
                [sys.executable, "-m", "alembic", "-c", str(ALEMBIC), *action],
                cwd=PYTHON_ROOT,
                env=migration_env,
                check=True,
                capture_output=True,
                text=True,
            )

        first_at = datetime(2026, 1, 15, 14, 30)
        create_prefix = f"rbfx-create-{uuid4().hex}"
        create_transaction_id = f"{create_prefix}-tx-a"
        user_id, job_id = await _seed(
            target_database_url,
            create_prefix,
            events=(("a", first_at, "-10.005000", "EUR"),),
        )
        provider = _Provider({first_at: (Decimal("25.12345678"), datetime(2026, 1, 15))})
        engine = create_async_engine(normalize_database_url(target_database_url))
        try:
            async with AsyncSession(engine) as session:
                service = RaiffeisenbankReportingFxService(
                    session,
                    source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
                    fx_registry=ExchangeRateProviderRegistry((provider,)),
                )
                command = AcquireRaiffeisenbankReportingFxCommand(
                    job_id,
                    user_id,
                    "CZK",
                    (create_transaction_id,),
                    CREATED_AT,
                )
                created = await service.acquire(command)
                replayed = await service.acquire(command)
                assert not session.in_transaction()
                assert (created.rates_created, created.evidence_created) == (1, 1)
                assert (replayed.rates_replayed, replayed.evidence_replayed) == (1, 1)
                assert len(provider.calls) == 1
            async with AsyncSession(engine) as session:
                transaction = await session.get(TransactionModel, create_transaction_id)
                evidence = await session.get(
                    TransactionReportingEvidenceModel, create_transaction_id
                )
                assert transaction is not None and evidence is not None
                assert transaction.reporting_amount == Decimal("-251.360185")
                assert evidence.source_event_time == first_at
                assert evidence.background_job_id == job_id
                rate = await session.get(ExchangeRateModel, evidence.exchange_rate_id)
                assert rate is not None
                assert (rate.from_currency, rate.to_currency) == ("EUR", "CZK")
                assert rate.source is ExchangeRateSource.yahoo_finance
                assert rate.date == datetime(2026, 1, 15)

            conflict_first_at = datetime(2026, 1, 17, 14, 30)
            conflict_second_at = datetime(2026, 1, 18, 9)
            conflict_prefix = f"rbfx-conflict-{uuid4().hex}"
            conflict_user, conflict_job = await _seed(
                target_database_url,
                conflict_prefix,
                events=(
                    ("a", conflict_first_at, "-1.000000", "EUR"),
                    ("b", conflict_second_at, "-2.000000", "EUR"),
                ),
            )
            conflict_provider = _Provider(
                {
                    conflict_first_at: (
                        Decimal("25.00000000"),
                        datetime(2026, 1, 17),
                    ),
                    conflict_second_at: (
                        Decimal("25.10000000"),
                        datetime(2026, 1, 18),
                    ),
                }
            )
            conflicting_observation = ExchangeRateObservation(
                "EUR",
                "CZK",
                ExchangeRateSource.yahoo_finance,
                Decimal("25.10000000"),
                datetime(2026, 1, 18),
            )
            async with AsyncSession(engine) as session:
                session.add(
                    ExchangeRateModel(
                        id="foreign-rate-id",
                        from_currency="EUR",
                        to_currency="CZK",
                        rate=conflicting_observation.rate,
                        source=conflicting_observation.provider,
                        date=conflicting_observation.effective_at,
                        created_at=CREATED_AT,
                    )
                )
                await session.commit()
            first_observation = ExchangeRateObservation(
                "EUR",
                "CZK",
                ExchangeRateSource.yahoo_finance,
                Decimal("25.00000000"),
                datetime(2026, 1, 17),
            )
            first_rate_id = exchange_rate_id(first_observation)
            async with AsyncSession(engine) as session:
                with pytest.raises(RaiffeisenbankReportingFxConflictError):
                    await RaiffeisenbankReportingFxService(
                        session,
                        source_policy=LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
                        fx_registry=ExchangeRateProviderRegistry((conflict_provider,)),
                    ).acquire(
                        AcquireRaiffeisenbankReportingFxCommand(
                            conflict_job,
                            conflict_user,
                            "CZK",
                            (
                                f"{conflict_prefix}-tx-a",
                                f"{conflict_prefix}-tx-b",
                            ),
                            CREATED_AT,
                        )
                    )
            async with AsyncSession(engine) as session:
                assert await session.get(ExchangeRateModel, first_rate_id) is None
                assert (
                    await session.scalar(
                        select(func.count())
                        .select_from(TransactionReportingEvidenceModel)
                        .where(
                            TransactionReportingEvidenceModel.transaction_id.like(
                                f"{conflict_prefix}-tx-%"
                            )
                        )
                    )
                    == 0
                )
                conflict_rows = tuple(
                    await session.scalars(
                        select(TransactionModel).where(
                            TransactionModel.id.like(f"{conflict_prefix}-tx-%")
                        )
                    )
                )
                assert all(row.reporting_amount is None for row in conflict_rows)
        finally:
            await engine.dispose()
    finally:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin.close()
