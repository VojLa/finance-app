from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.models import (
    AccountModel,
    AccountType,
    BackgroundJobKind,
    BackgroundJobModel,
    BackgroundJobStatus,
    UserModel,
)
from app.db.url import normalize_database_url
from app.modules.jobs.repository import BackgroundJobRepository

DATABASE_URL = os.getenv("DATABASE_URL")
NOW = datetime(2030, 1, 1, 12, 0, 0)


def _job_values(
    *,
    job_id: str,
    user_id: str,
    account_id: str,
    idempotency_key: str,
    status: BackgroundJobStatus = BackgroundJobStatus.queued,
    **overrides: object,
) -> dict[str, object]:
    values: dict[str, object] = {
        "id": job_id,
        "user_id": user_id,
        "account_id": account_id,
        "kind": BackgroundJobKind.import_workflow,
        "status": status,
        "idempotency_key": idempotency_key,
        "payload": {"schema_version": 1, "batch_ids": ["batch-a"]},
        "checkpoint": {},
        "progress": {},
        "result": None,
        "error_code": None,
        "error_message": None,
        "attempt_count": 0,
        "manual_retry_count": 0,
        "max_attempts": 5,
        "run_after": NOW,
        "lease_owner": None,
        "lease_version": 0,
        "lease_expires_at": None,
        "lease_heartbeat_at": None,
        "started_at": None,
        "finished_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return values


async def _expect_constraint(
    engine: AsyncEngine,
    values: dict[str, object],
) -> None:
    async with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            await connection.execute(insert(BackgroundJobModel).values(**values))


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_background_job_schema_enforces_lifecycle_and_idempotency() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    suffix = uuid4().hex
    user_id = f"background-job-user-{suffix}"
    account_id = f"background-job-account-{suffix}"

    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(UserModel).values(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    name="Background job schema test",
                    password_hash=None,
                    base_currency="CZK",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await connection.execute(
                insert(AccountModel).values(
                    id=account_id,
                    name="Background job account",
                    type=AccountType.bank,
                    currency="CZK",
                    color=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                    notes=None,
                )
            )
            await connection.execute(
                insert(BackgroundJobModel).values(
                    **_job_values(
                        job_id=f"queued-{suffix}",
                        user_id=user_id,
                        account_id=account_id,
                        idempotency_key="queued",
                    )
                )
            )
            await connection.execute(
                insert(BackgroundJobModel).values(
                    **_job_values(
                        job_id=f"retry-{suffix}",
                        user_id=user_id,
                        account_id=account_id,
                        idempotency_key="retry",
                        status=BackgroundJobStatus.retry_wait,
                    )
                )
            )
            await connection.execute(
                insert(BackgroundJobModel).values(
                    **_job_values(
                        job_id=f"running-{suffix}",
                        user_id=user_id,
                        account_id=account_id,
                        idempotency_key="running",
                        status=BackgroundJobStatus.running,
                        lease_owner="worker-1",
                        lease_version=1,
                        lease_expires_at=NOW + timedelta(minutes=1),
                        lease_heartbeat_at=NOW,
                        started_at=NOW,
                    )
                )
            )
            await connection.execute(
                insert(BackgroundJobModel).values(
                    **_job_values(
                        job_id=f"completed-{suffix}",
                        user_id=user_id,
                        account_id=account_id,
                        idempotency_key="completed",
                        status=BackgroundJobStatus.completed,
                        result={"snapshot_refresh_status": "created"},
                        finished_at=NOW,
                    )
                )
            )
            await connection.execute(
                insert(BackgroundJobModel).values(
                    **_job_values(
                        job_id=f"failed-{suffix}",
                        user_id=user_id,
                        account_id=account_id,
                        idempotency_key="failed",
                        status=BackgroundJobStatus.failed,
                        error_code="import_failed",
                        error_message="The import could not be completed.",
                        finished_at=NOW,
                    )
                )
            )

        await _expect_constraint(
            engine,
            _job_values(
                job_id=f"empty-payload-{suffix}",
                user_id=user_id,
                account_id=account_id,
                idempotency_key="empty-payload",
                payload={},
            ),
        )
        await _expect_constraint(
            engine,
            _job_values(
                job_id=f"queued-result-{suffix}",
                user_id=user_id,
                account_id=account_id,
                idempotency_key="queued-result",
                result={"not": "finished"},
            ),
        )
        await _expect_constraint(
            engine,
            _job_values(
                job_id=f"attempt-overflow-{suffix}",
                user_id=user_id,
                account_id=account_id,
                idempotency_key="attempt-overflow",
                attempt_count=6,
                max_attempts=5,
            ),
        )
        await _expect_constraint(
            engine,
            _job_values(
                job_id=f"running-without-lease-{suffix}",
                user_id=user_id,
                account_id=account_id,
                idempotency_key="running-without-lease",
                status=BackgroundJobStatus.running,
            ),
        )
        await _expect_constraint(
            engine,
            _job_values(
                job_id=f"failed-without-error-{suffix}",
                user_id=user_id,
                account_id=account_id,
                idempotency_key="failed-without-error",
                status=BackgroundJobStatus.failed,
                finished_at=NOW,
            ),
        )
        await _expect_constraint(
            engine,
            _job_values(
                job_id=f"second-running-{suffix}",
                user_id=user_id,
                account_id=account_id,
                idempotency_key="second-running",
                status=BackgroundJobStatus.running,
                lease_owner="worker-2",
                lease_version=1,
                lease_expires_at=NOW + timedelta(minutes=1),
                lease_heartbeat_at=NOW,
            ),
        )

        async with engine.connect() as connection:
            index_rows = await connection.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE schemaname = 'public' AND tablename = 'BackgroundJob'"
                )
            )
            indexes = {str(row[0]): str(row[1]) for row in index_rows}
            assert "BackgroundJob_claim_idx" in indexes
            assert "retry_wait" in indexes["BackgroundJob_claim_idx"]
            assert "BackgroundJob_expiredLease_idx" in indexes
            assert "BackgroundJob_one_running_per_account_key" in indexes
            assert (
                "WHERE (status = 'running'" in indexes["BackgroundJob_one_running_per_account_key"]
            )

        sessions = async_sessionmaker(engine, expire_on_commit=False)
        barrier = asyncio.Barrier(2)

        async def enqueue_identical() -> tuple[str, bool]:
            async with sessions() as session:
                await barrier.wait()
                result = await BackgroundJobRepository(session).enqueue_import_job(
                    user_id=user_id,
                    account_id=account_id,
                    idempotency_key="concurrent-replay",
                    payload={"schema_version": 1, "batch_ids": ["batch-a"]},
                    checkpoint={},
                    progress={},
                    max_attempts=5,
                    now=NOW,
                )
                await session.commit()
                return result.job.id, result.created

        concurrent = await asyncio.gather(enqueue_identical(), enqueue_identical())
        assert {job_id for job_id, _ in concurrent} == {concurrent[0][0]}
        assert sorted(created for _, created in concurrent) == [False, True]
        async with engine.connect() as connection:
            count = await connection.scalar(
                select(text("count(*)"))
                .select_from(BackgroundJobModel)
                .where(
                    BackgroundJobModel.user_id == user_id,
                    BackgroundJobModel.account_id == account_id,
                    BackgroundJobModel.idempotency_key == "concurrent-replay",
                )
            )
            assert count == 1
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(AccountModel).where(AccountModel.id == account_id))
            await connection.execute(delete(UserModel).where(UserModel.id == user_id))
        await engine.dispose()
