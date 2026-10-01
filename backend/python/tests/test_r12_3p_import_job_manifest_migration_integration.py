from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.background_jobs import (
    BackgroundJobModel,
    ImportJobBatchModel,
)
from app.db.models.enums import BackgroundJobStatus
from app.db.models.publication_targets import ImportJobPublicationTargetModel
from app.db.url import normalize_database_url
from app.modules.jobs.repository import BackgroundJobRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_SCHEMA = BACKEND_ROOT / "database" / "revisions" / "3o0001unkbasis" / "schema.sql"
PREVIOUS_REVISION = "3o0001unkbasis"
AT = datetime(2026, 8, 2, 12, 0, 0)


def _command(target_url: URL, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = target_url.render_as_string(hide_password=False)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *arguments],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


async def _create_pre_3p_database(prefix: str) -> tuple[asyncpg.Connection, URL]:
    assert DATABASE_URL is not None
    source_url = make_url(normalize_database_url(DATABASE_URL))
    database_name = f"finance_app_3p_manifest_{prefix}_{uuid4().hex}"
    admin_url = source_url.set(drivername="postgresql", database="postgres")
    target_url = source_url.set(database=database_name)
    admin = await asyncpg.connect(admin_url.render_as_string(hide_password=False))
    await admin.execute(f'CREATE DATABASE "{database_name}"')
    target = await asyncpg.connect(
        target_url.set(drivername="postgresql").render_as_string(hide_password=False)
    )
    schema = PREVIOUS_SCHEMA.read_text(encoding="utf-8").replace('CREATE SCHEMA "public";\n', "", 1)
    await target.execute(schema)
    await target.execute(
        "CREATE TABLE public.alembic_version ("
        "version_num varchar(32) NOT NULL, "
        "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
    )
    await target.execute(
        "INSERT INTO public.alembic_version (version_num) VALUES ($1)", PREVIOUS_REVISION
    )
    return admin, target_url


async def _drop_database(admin: asyncpg.Connection, target_url: URL) -> None:
    database_name = target_url.database
    assert database_name is not None and database_name.startswith("finance_app_3p_manifest_")
    await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
    await admin.close()


async def _seed_scoped_jobs(target_url: URL, *, prefix: str) -> None:
    connection = await asyncpg.connect(
        target_url.set(drivername="postgresql").render_as_string(hide_password=False)
    )
    try:
        accounts = ("queued", "running", "retry", "failed", "completed", "rb", "orphan")
        await connection.execute(
            """
            INSERT INTO "public"."User"
                ("id", "email", "name", "passwordHash", "baseCurrency", "createdAt", "updatedAt")
            VALUES ($1, $2, 'Migration owner', NULL, 'CZK', $3, $3)
            """,
            f"{prefix}-user",
            f"{prefix}@example.test",
            AT,
        )
        for account in accounts:
            account_id = f"{prefix}-{account}"
            await connection.execute(
                """
                INSERT INTO "public"."Account"
                    ("id", "name", "type", "currency", "color", "isArchived", "archivedAt",
                     "createdAt", "updatedAt", "notes")
                VALUES ($1, $2, 'bank'::"public"."AccountType", 'CZK', NULL, false, NULL,
                        $3, $3, NULL)
                """,
                account_id,
                account_id,
                AT,
            )
            if account != "orphan":
                await connection.execute(
                    """
                    INSERT INTO "public"."AccountMember"
                        ("id", "accountId", "userId", "role", "relationType", "invitedById",
                         "acceptedAt", "createdAt", "updatedAt")
                    VALUES ($1, $2, $3, 'owner'::"public"."AccountMemberRole",
                            'owner'::"public"."AccountRelationType", NULL, $4, $4, $4)
                    """,
                    f"{prefix}-member-{account}",
                    account_id,
                    f"{prefix}-user",
                    AT,
                )
            source = "raiffeisenbank" if account == "rb" else "trading212"
            status = "completed" if account == "completed" else "pending"
            completed_at = AT + timedelta(minutes=1) if account == "completed" else None
            await connection.execute(
                """
                INSERT INTO "public"."ImportBatch"
                    ("id", "userId", "accountId", "source", "filename", "fileSize", "fileEncoding",
                     "checksum", "status", "rowsTotal", "rowsImported", "rowsSkipped", "createdAt",
                     "completedAt", "retainUntil", "rawDataPurgedAt")
                VALUES ($1, $2, $3, $4::"public"."ImportSource", 'fixture.csv', 1, 'utf-8',
                        $5, $6::"public"."ImportStatus", $7, $7, $7, $8, $9, NULL, NULL)
                """,
                f"{prefix}-batch-{account}",
                f"{prefix}-user",
                account_id,
                source,
                (account * 64)[:64],
                status,
                0 if account == "completed" else None,
                AT,
                completed_at,
            )

        status_by_account = {
            "queued": "queued",
            "running": "running",
            "retry": "retry_wait",
            "failed": "failed",
            "completed": "completed",
            "rb": "failed",
            "orphan": "failed",
        }
        for account, status in status_by_account.items():
            phase = (
                "refreshing_snapshot"
                if account == "rb"
                else "completed"
                if account == "completed"
                else "queued"
            )
            completed_batch_ids = [f"{prefix}-batch-{account}"] if phase != "queued" else []
            total_units = 6 if account == "rb" else 9
            completed_units = total_units if phase != "queued" else 0
            is_terminal = status in {"failed", "completed"}
            await connection.execute(
                """
                INSERT INTO "public"."BackgroundJob"
                    ("id", "userId", "accountId", "kind", "status", "idempotencyKey", "payload",
                     "checkpoint", "progress", "result", "errorCode", "errorMessage", "attemptCount",
                     "manualRetryCount", "maxAttempts", "runAfter", "leaseOwner", "leaseVersion",
                     "leaseExpiresAt", "leaseHeartbeatAt", "startedAt", "finishedAt", "createdAt", "updatedAt")
                VALUES ($1, $2, $3, 'import_workflow'::"public"."BackgroundJobKind",
                        $4::"public"."BackgroundJobStatus", $5,
                        jsonb_build_object('schema_version', 1, 'batch_ids', to_jsonb(ARRAY[$6]::text[])),
                        jsonb_build_object('schema_version', 1, 'phase', $7::text,
                                           'completed_batch_ids', to_jsonb($8::text[])),
                        jsonb_build_object('schema_version', 1, 'phase', $7::text,
                                           'completed_units', $9::integer, 'total_units', $10::integer,
                                           'completed_batches', CASE WHEN $7::text = 'queued' THEN 0 ELSE 1 END,
                                           'total_batches', 1),
                        CASE WHEN $4 = 'completed' THEN '{"legacy": true}'::jsonb ELSE NULL END,
                        CASE WHEN $4::text = 'failed' THEN 'legacy_error' ELSE NULL END,
                        CASE WHEN $4::text = 'failed' THEN 'Legacy retry state.' ELSE NULL END,
                        CASE WHEN $4 = 'queued' THEN 0 ELSE 1 END, 0, 3, $12::timestamp,
                        CASE WHEN $4 = 'running' THEN 'legacy-worker' ELSE NULL END,
                        CASE WHEN $4 = 'queued' THEN 0 ELSE 1 END,
                        CASE WHEN $4 = 'running' THEN $13::timestamp ELSE NULL END,
                        CASE WHEN $4 = 'running' THEN $12::timestamp ELSE NULL END,
                        CASE WHEN $4 = 'running' THEN $12::timestamp ELSE NULL END,
                        CASE WHEN $11::boolean THEN $14::timestamp ELSE NULL END,
                        $12::timestamp, $12::timestamp)
                """,
                f"{prefix}-job-{account}",
                f"{prefix}-user",
                f"{prefix}-{account}",
                status,
                account,
                f"{prefix}-batch-{account}",
                phase,
                completed_batch_ids,
                completed_units,
                total_units,
                is_terminal,
                AT,
                AT - timedelta(seconds=1),
                AT + timedelta(minutes=1),
            )
    finally:
        await connection.close()


async def _seed_completion_publication(target_url: URL, *, prefix: str, job_id: str) -> None:
    connection = await asyncpg.connect(
        target_url.set(drivername="postgresql").render_as_string(hide_password=False)
    )
    account_id = f"{prefix}-queued"
    user_id = f"{prefix}-user"
    generation_id = f"{prefix}-generation"
    bucket = AT.replace(second=0, microsecond=0)
    try:
        await connection.execute(
            """
            INSERT INTO "public"."ImportJobPublicationTarget" ("jobId", "userId", "bucket", "publishedAt")
            VALUES ($1, $2, $3, NULL)
            """,
            job_id,
            user_id,
            bucket,
        )
        await connection.execute(
            """
            INSERT INTO "public"."AccountCanonicalState"
                ("accountId", "lastRevision", "lastInvestmentRevision", "holdingRevision", "updatedAt")
            VALUES ($1, 1, 1, 1, $2)
            ON CONFLICT ("accountId") DO UPDATE SET
                "lastRevision" = 1, "lastInvestmentRevision" = 1,
                "holdingRevision" = 1, "updatedAt" = EXCLUDED."updatedAt"
            """,
            account_id,
            AT,
        )
        await connection.execute(
            """
            INSERT INTO "public"."AccountCanonicalChange"
                ("accountId", "revision", "kind", "entityId", "financialTimestamp", "createdAt")
            VALUES ($1, 1, 'investment_event', $2, $3, $3)
            """,
            account_id,
            f"{prefix}-canonical-seed",
            bucket,
        )
        await connection.execute(
            """
            INSERT INTO "public"."SnapshotGeneration" ("id", "state", "createdAt", "publishedAt")
            VALUES ($1, 'published', $2, $2)
            """,
            generation_id,
            bucket,
        )
        await connection.execute(
            """
            INSERT INTO "public"."SnapshotGenerationTarget"
                ("generationId", "userId", "createdAt")
            VALUES ($1, $2, $3)
            """,
            generation_id,
            user_id,
            bucket,
        )
        await connection.execute(
            """
            INSERT INTO "public"."NetWorthSnapshot"
                ("id", "userId", "timestamp", "granularity", "source", "currency", "cashValue",
                 "portfolioValue", "liabilitiesValue", "totalNetWorth", "isRecalculated", "calculatedAt",
                 "calculationVersion", "createdAt", "generationId")
            VALUES ($1, $2, $3, 'minute'::"public"."SnapshotGranularity",
                    'import_event'::"public"."SnapshotSource", 'CZK', 0, 0, 0, 0, false, $3, 1, $3, $4)
            """,
            f"{prefix}-net-worth",
            user_id,
            bucket,
            generation_id,
        )
        await connection.execute(
            """
            INSERT INTO "public"."AccountSnapshot"
                ("id", "accountId", "timestamp", "granularity", "source", "currency", "cashValue",
                 "investmentValue", "investmentCostBasis", "liabilitiesValue", "totalValue",
                 "isRecalculated", "calculatedAt", "calculationVersion", "createdAt", "generationId")
            VALUES ($1, $2, $3, 'minute'::"public"."SnapshotGranularity",
                    'import_event'::"public"."SnapshotSource", 'CZK', 0, 0, NULL, 0, 0, false, $3, 1, $3, $4)
            """,
            f"{prefix}-account-snapshot",
            account_id,
            bucket,
            generation_id,
        )
        await connection.execute(
            """
            INSERT INTO "public"."PortfolioSnapshot"
                ("id", "userId", "generationId", "timestamp", "valuationTimestamp", "granularity",
                 "source", "currency", "cashValue", "investmentValue", "feesValue", "taxesValue",
                 "calculatedAt", "calculationVersion", "createdAt")
            VALUES ($1, $2, $3, $4, $4, 'minute'::"public"."SnapshotGranularity",
                    'import_event'::"public"."SnapshotSource", 'CZK', 0, 0, 0, 0, $4, 1, $4)
            """,
            f"{prefix}-portfolio-snapshot",
            user_id,
            generation_id,
            bucket,
        )
        await connection.execute(
            """
            INSERT INTO "public"."DailySnapshotBaseline"
                ("id", "userId", "netWorthSnapshotId", "timestamp", "granularity", "currency",
                 "calculationVersion", "source", "createdAt", "backgroundJobId", "generationId")
            VALUES ($1, $2, $3, $4, 'minute'::"public"."SnapshotGranularity", 'CZK', 1,
                    'import_event'::"public"."SnapshotSource", $4, $5, $6)
            """,
            f"{prefix}-baseline",
            user_id,
            f"{prefix}-net-worth",
            bucket,
            job_id,
            generation_id,
        )
        await connection.execute(
            """
            INSERT INTO "public"."DailySnapshotBaselineAccount"
                ("baselineId", "accountId", "accountType", "accountCurrency", "primarySnapshotId",
                 "presentationSnapshotId", "canonicalRevision", "investmentRevision", "holdingRevision",
                 "selectedLiabilityBalanceId", "generationId")
            VALUES ($1, $2, 'bank'::"public"."AccountType", 'CZK', $3, $3, 1, 1, 1, NULL, $4)
            """,
            f"{prefix}-baseline",
            account_id,
            f"{prefix}-account-snapshot",
            generation_id,
        )
    finally:
        await connection.close()


def test_pre_3p_noncompleted_import_jobs_receive_exact_manifest_and_remain_recoverable() -> None:
    async def scenario() -> None:
        admin, target_url = await _create_pre_3p_database("recovery")
        prefix = "r12-3p"
        try:
            await _seed_scoped_jobs(target_url, prefix=prefix)
            upgraded = _command(target_url, "upgrade", "head")
            assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr

            connection = await asyncpg.connect(
                target_url.set(drivername="postgresql").render_as_string(hide_password=False)
            )
            try:
                memberships = await connection.fetch(
                    """
                    SELECT "jobId", "batchId", "accountId"
                    FROM "public"."ImportJobBatch"
                    ORDER BY "jobId", "batchId"
                    """
                )
                assert {
                    (row["jobId"], row["batchId"], row["accountId"]) for row in memberships
                } == {
                    (f"{prefix}-job-{name}", f"{prefix}-batch-{name}", f"{prefix}-{name}")
                    for name in ("queued", "running", "retry", "failed", "rb", "orphan")
                }
                affected = await connection.fetch(
                    'SELECT "jobId", "accountId" FROM "public"."ImportJobAffectedAccount"'
                )
                assert {(row["jobId"], row["accountId"]) for row in affected} == {
                    (f"{prefix}-job-{name}", f"{prefix}-{name}")
                    for name in ("queued", "running", "retry", "failed", "rb")
                }
                assert (
                    await connection.fetchval(
                        'SELECT count(*) FROM "public"."ImportJobBatch" WHERE "jobId" = $1',
                        f"{prefix}-job-completed",
                    )
                    == 0
                )
                checkpoint = await connection.fetchrow(
                    'SELECT "checkpoint", "progress" FROM "public"."BackgroundJob" WHERE "id" = $1',
                    f"{prefix}-job-rb",
                )
                assert checkpoint is not None
                assert json.loads(checkpoint["checkpoint"]) == {
                    "schema_version": 1,
                    "phase": "posting",
                    "completed_batch_ids": [f"{prefix}-batch-rb"],
                }
                assert json.loads(checkpoint["progress"]) == {
                    "schema_version": 1,
                    "phase": "posting",
                    "completed_units": 5,
                    "total_units": 9,
                    "completed_batches": 1,
                    "total_batches": 1,
                }
            finally:
                await connection.close()

            engine = create_async_engine(
                normalize_database_url(target_url.render_as_string(hide_password=False))
            )
            try:
                async with AsyncSession(engine) as session:
                    repository = BackgroundJobRepository(session)
                    recovered = await repository.claim_next(
                        worker_id="recovery-worker",
                        now=AT + timedelta(minutes=2),
                        lease_duration=timedelta(minutes=1),
                    )
                    assert recovered is not None and recovered.job.id == f"{prefix}-job-running"
                    assert (
                        await session.get(
                            ImportJobBatchModel,
                            (f"{prefix}-job-running", f"{prefix}-batch-running"),
                        )
                        is not None
                    )
                    await repository.release(lease=recovered.lease, now=AT + timedelta(minutes=2))
                    retried = await repository.retry_failed(
                        user_id=f"{prefix}-user",
                        account_id=f"{prefix}-failed",
                        job_id=f"{prefix}-job-failed",
                        now=AT + timedelta(minutes=2),
                    )
                    assert retried is not None and retried.retried is True
                    await session.commit()

                await _seed_completion_publication(
                    target_url, prefix=prefix, job_id=f"{prefix}-job-queued"
                )
                async with AsyncSession(engine) as session:
                    repository = BackgroundJobRepository(session)
                    claimed = await repository.claim_next(
                        worker_id="completion-worker",
                        now=AT + timedelta(minutes=3),
                        lease_duration=timedelta(minutes=1),
                    )
                    assert claimed is not None and claimed.job.id == f"{prefix}-job-queued"
                    await session.commit()
                    await repository.complete(
                        lease=claimed.lease,
                        result={
                            "schema_version": 1,
                            "batch_ids": [f"{prefix}-batch-queued"],
                            "rows_total": 0,
                            "rows_imported": 0,
                            "rows_skipped": 0,
                            "snapshot_refresh_status": "created",
                            "completed_at": (AT + timedelta(minutes=3)).isoformat(),
                        },
                        progress={
                            "schema_version": 1,
                            "phase": "completed",
                            "completed_units": 9,
                            "total_units": 9,
                            "completed_batches": 1,
                            "total_batches": 1,
                        },
                        now=AT + timedelta(minutes=3),
                    )
                    await session.commit()
                    completed = await session.get(BackgroundJobModel, f"{prefix}-job-queued")
                    target = await session.get(
                        ImportJobPublicationTargetModel,
                        (f"{prefix}-job-queued", f"{prefix}-user"),
                    )
                    assert (
                        completed is not None and completed.status is BackgroundJobStatus.completed
                    )
                    assert target is not None and target.published_at == AT + timedelta(minutes=3)
                connection = await asyncpg.connect(
                    target_url.set(drivername="postgresql").render_as_string(hide_password=False)
                )
                try:
                    assert (
                        await connection.fetchval(
                            """
                            SELECT count(*) FROM "public"."SnapshotSeriesPointLink" link
                            JOIN "public"."DailySnapshotBaseline" baseline
                              ON baseline."id" = link."baselineId"
                             AND baseline."generationId" = link."generationId"
                             AND baseline."userId" = link."userId"
                            JOIN "public"."DailySnapshotBaselineAccount" child
                              ON child."baselineId" = baseline."id"
                             AND child."generationId" = baseline."generationId"
                            JOIN "public"."AccountSnapshot" account_snapshot
                              ON account_snapshot."id" = child."primarySnapshotId"
                             AND account_snapshot."generationId" = child."generationId"
                            JOIN "public"."NetWorthSnapshot" net_worth
                              ON net_worth."id" = link."netWorthSnapshotId"
                             AND net_worth."generationId" = link."generationId"
                            JOIN "public"."PortfolioSnapshot" portfolio
                              ON portfolio."id" = link."portfolioSnapshotId"
                             AND portfolio."generationId" = link."generationId"
                            JOIN "public"."SnapshotGenerationTarget" target
                              ON target."generationId" = link."generationId"
                             AND target."userId" = link."userId"
                            JOIN "public"."SnapshotGeneration" generation
                              ON generation."id" = target."generationId"
                            WHERE baseline."backgroundJobId" = $1
                              AND link."generationId" = $2
                              AND generation."state" = 'published'
                            """,
                            f"{prefix}-job-queued",
                            f"{prefix}-generation",
                        )
                        == 1
                    )
                finally:
                    await connection.close()
            finally:
                await engine.dispose()
            blocked = _command(target_url, "downgrade", PREVIOUS_REVISION)
            assert blocked.returncode != 0
            assert "Operator audit history must not be discarded by downgrade" in (
                blocked.stdout + blocked.stderr
            )
        finally:
            await _drop_database(admin, target_url)

    asyncio.run(scenario())


def test_pre_3p_noncompleted_cross_scope_payload_is_rejected_without_a_manifest() -> None:
    async def scenario() -> None:
        admin, target_url = await _create_pre_3p_database("foreign")
        try:
            connection = await asyncpg.connect(
                target_url.set(drivername="postgresql").render_as_string(hide_password=False)
            )
            try:
                await connection.execute(
                    """
                    INSERT INTO "public"."User"
                        ("id", "email", "name", "passwordHash", "baseCurrency", "createdAt", "updatedAt")
                    VALUES ('foreign-user', 'foreign@example.test', 'Foreign', NULL, 'CZK', $1, $1)
                    """,
                    AT,
                )
                for account in ("job-account", "batch-account"):
                    await connection.execute(
                        """
                        INSERT INTO "public"."Account"
                            ("id", "name", "type", "currency", "color", "isArchived", "archivedAt",
                             "createdAt", "updatedAt", "notes")
                        VALUES ($1, $1, 'bank'::"public"."AccountType", 'CZK', NULL, false, NULL, $2, $2, NULL)
                        """,
                        account,
                        AT,
                    )
                    await connection.execute(
                        """
                        INSERT INTO "public"."AccountMember"
                            ("id", "accountId", "userId", "role", "relationType", "invitedById",
                             "acceptedAt", "createdAt", "updatedAt")
                        VALUES ($1, $2, 'foreign-user', 'owner'::"public"."AccountMemberRole",
                                'owner'::"public"."AccountRelationType", NULL, $3, $3, $3)
                        """,
                        f"member-{account}",
                        account,
                        AT,
                    )
                await connection.execute(
                    """
                    INSERT INTO "public"."ImportBatch"
                        ("id", "userId", "accountId", "source", "filename", "fileSize", "fileEncoding",
                         "checksum", "status", "rowsTotal", "rowsImported", "rowsSkipped", "createdAt",
                         "completedAt", "retainUntil", "rawDataPurgedAt")
                    VALUES ('foreign-batch', 'foreign-user', 'batch-account',
                            'trading212'::"public"."ImportSource", 'foreign.csv', 1, 'utf-8',
                            repeat('a', 64), 'pending'::"public"."ImportStatus", NULL, NULL, NULL, $1,
                            NULL, NULL, NULL)
                    """,
                    AT,
                )
                await connection.execute(
                    """
                    INSERT INTO "public"."BackgroundJob"
                        ("id", "userId", "accountId", "kind", "status", "idempotencyKey", "payload",
                         "checkpoint", "progress", "result", "errorCode", "errorMessage", "attemptCount",
                         "manualRetryCount", "maxAttempts", "runAfter", "leaseOwner", "leaseVersion",
                         "leaseExpiresAt", "leaseHeartbeatAt", "startedAt", "finishedAt", "createdAt", "updatedAt")
                    VALUES ('foreign-job', 'foreign-user', 'job-account',
                            'import_workflow'::"public"."BackgroundJobKind",
                            'queued'::"public"."BackgroundJobStatus", 'foreign',
                            '{"schema_version": 1, "batch_ids": ["foreign-batch"]}'::jsonb,
                            '{"schema_version": 1, "phase": "queued", "completed_batch_ids": []}'::jsonb,
                            '{"schema_version": 1, "phase": "queued", "completed_units": 0,
                              "total_units": 9, "completed_batches": 0, "total_batches": 1}'::jsonb,
                            NULL, NULL, NULL, 0, 0, 3, $1, NULL, 0, NULL, NULL, NULL, NULL, $1, $1)
                    """,
                    AT,
                )
            finally:
                await connection.close()

            rejected = _command(target_url, "upgrade", "head")
            assert rejected.returncode != 0
            assert "payload batches do not prove one scoped import source" in (
                rejected.stdout + rejected.stderr
            )
            connection = await asyncpg.connect(
                target_url.set(drivername="postgresql").render_as_string(hide_password=False)
            )
            try:
                assert (
                    await connection.fetchval("SELECT to_regclass('public.\"ImportJobBatch\"')")
                    is None
                )
            finally:
                await connection.close()
        finally:
            await _drop_database(admin, target_url)

    asyncio.run(scenario())
