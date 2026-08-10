from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import (
    AccountModel,
    AccountType,
    BackgroundJobKind,
    BackgroundJobModel,
    BackgroundJobStatus,
    UserModel,
)
from app.db.url import normalize_database_url
from app.modules.jobs.repository import BackgroundJobLeaseLostError, BackgroundJobRepository

DATABASE_URL = os.getenv("DATABASE_URL")
NOW = datetime(2030, 1, 1, 12, 0, 0)
LEASE = timedelta(minutes=5)


def _job(job_id: str, user_id: str, account_id: str, *, run_after: datetime) -> dict[str, object]:
    return {
        "id": job_id,
        "user_id": user_id,
        "account_id": account_id,
        "kind": BackgroundJobKind.import_workflow,
        "status": BackgroundJobStatus.queued,
        "idempotency_key": job_id,
        "payload": {"schema_version": 1, "batch_ids": [f"batch-{job_id}"]},
        "checkpoint": {"schema_version": 1, "phase": "queued", "completed_batch_ids": []},
        "progress": {
            "schema_version": 1,
            "phase": "queued",
            "completed_units": 0,
            "total_units": 7,
            "completed_batches": 0,
            "total_batches": 1,
        },
        "result": None,
        "error_code": None,
        "error_message": None,
        "attempt_count": 0,
        "manual_retry_count": 0,
        "max_attempts": 5,
        "run_after": run_after,
        "lease_owner": None,
        "lease_version": 0,
        "lease_expires_at": None,
        "lease_heartbeat_at": None,
        "started_at": None,
        "finished_at": None,
        "created_at": NOW,
        "updated_at": NOW,
    }


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_claim_recovery_and_fencing_are_concurrency_safe() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    user_ids = [f"worker-user-a-{suffix}", f"worker-user-b-{suffix}"]
    account_ids = [f"worker-account-a-{suffix}", f"worker-account-b-{suffix}"]
    job_ids = [f"worker-job-a-{suffix}", f"worker-job-b-{suffix}"]
    try:
        async with engine.begin() as connection:
            for index in range(2):
                await connection.execute(
                    insert(UserModel).values(
                        id=user_ids[index],
                        email=f"{user_ids[index]}@example.test",
                        name="Worker test",
                        password_hash=None,
                        base_currency="CZK",
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
                await connection.execute(
                    insert(AccountModel).values(
                        id=account_ids[index],
                        name="Worker account",
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
                        **_job(job_ids[index], user_ids[index], account_ids[index], run_after=NOW)
                    )
                )

        barrier = asyncio.Barrier(2)

        async def claim(worker: str):
            async with sessions() as session:
                await barrier.wait()
                claimed = await BackgroundJobRepository(session).claim_next(
                    worker_id=worker,
                    now=NOW,
                    lease_duration=LEASE,
                )
                await session.commit()
                return claimed

        claimed = await asyncio.gather(claim("worker-a"), claim("worker-b"))
        assert all(item is not None for item in claimed)
        assert {item.job.id for item in claimed if item is not None} == set(job_ids)
        first = next(item for item in claimed if item is not None and item.job.id == job_ids[0])
        stale_lease = first.lease

        async with sessions() as session:
            assert (
                await BackgroundJobRepository(session).claim_next(
                    worker_id="worker-c",
                    now=NOW + timedelta(minutes=1),
                    lease_duration=LEASE,
                )
                is None
            )
            await session.commit()

        async with sessions() as session:
            reclaimed = await BackgroundJobRepository(session).claim_next(
                worker_id="worker-recovery",
                now=NOW + timedelta(minutes=6),
                lease_duration=LEASE,
            )
            assert reclaimed is not None
            assert reclaimed.job.id in job_ids
            assert reclaimed.lease.version == 2
            await session.commit()

        async with sessions() as session:
            with pytest.raises(BackgroundJobLeaseLostError):
                await BackgroundJobRepository(session).checkpoint(
                    lease=stale_lease,
                    checkpoint={"schema_version": 1},
                    progress={"schema_version": 1},
                    now=NOW + timedelta(minutes=6),
                )
            await session.rollback()

        async with engine.connect() as connection:
            attempts = list(
                (
                    await connection.scalars(
                        select(BackgroundJobModel.attempt_count)
                        .where(BackgroundJobModel.id.in_(job_ids))
                        .order_by(BackgroundJobModel.id)
                    )
                ).all()
            )
            assert sorted(attempts) == [1, 2]
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
            await connection.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        await engine.dispose()
