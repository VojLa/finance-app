from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert, select, update
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
from app.modules.jobs.repository import BackgroundJobRepository

DATABASE_URL = os.getenv("DATABASE_URL")
NOW = datetime(2030, 1, 1, 12, 0, 0)


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_expired_exhausted_job_is_failed_and_graceful_release_restores_attempt() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    user_id, account_id = f"recovery-user-{suffix}", f"recovery-account-{suffix}"
    exhausted_id, released_id = f"exhausted-{suffix}", f"released-{suffix}"
    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(UserModel).values(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    name="Recovery",
                    password_hash=None,
                    base_currency="CZK",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await connection.execute(
                insert(AccountModel).values(
                    id=account_id,
                    name="Recovery",
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
            for job_id in (exhausted_id, released_id):
                await connection.execute(
                    insert(BackgroundJobModel).values(
                        id=job_id,
                        user_id=user_id,
                        account_id=account_id,
                        kind=BackgroundJobKind.import_workflow,
                        status=BackgroundJobStatus.queued,
                        idempotency_key=job_id,
                        payload={"batch_ids": [job_id]},
                        checkpoint={},
                        progress={},
                        result=None,
                        error_code=None,
                        error_message=None,
                        attempt_count=0,
                        manual_retry_count=0,
                        max_attempts=5,
                        run_after=NOW,
                        lease_owner=None,
                        lease_version=0,
                        lease_expires_at=None,
                        lease_heartbeat_at=None,
                        started_at=None,
                        finished_at=None,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
            await connection.execute(
                update(BackgroundJobModel)
                .where(BackgroundJobModel.id == exhausted_id)
                .values(
                    status=BackgroundJobStatus.running,
                    attempt_count=5,
                    lease_owner="dead-worker",
                    lease_version=1,
                    lease_expires_at=NOW - timedelta(seconds=1),
                    lease_heartbeat_at=NOW - timedelta(minutes=5),
                    started_at=NOW - timedelta(minutes=5),
                )
            )

        async with sessions() as session:
            claimed = await BackgroundJobRepository(session).claim_next(
                worker_id="recovery-worker", now=NOW, lease_duration=timedelta(minutes=5)
            )
            await session.commit()
        assert claimed is not None and claimed.job.id == released_id

        async with engine.connect() as connection:
            exhausted = (
                await connection.execute(
                    select(
                        BackgroundJobModel.status,
                        BackgroundJobModel.lease_owner,
                        BackgroundJobModel.finished_at,
                    ).where(BackgroundJobModel.id == exhausted_id)
                )
            ).one()
            assert exhausted == (BackgroundJobStatus.failed, None, NOW)

        async with sessions() as session:
            await BackgroundJobRepository(session).release(lease=claimed.lease, now=NOW)
            await session.commit()
        async with engine.connect() as connection:
            released = (
                await connection.execute(
                    select(BackgroundJobModel.status, BackgroundJobModel.attempt_count).where(
                        BackgroundJobModel.id == released_id
                    )
                )
            ).one()
            assert released == (BackgroundJobStatus.queued, 0)
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(AccountModel).where(AccountModel.id == account_id))
            await connection.execute(delete(UserModel).where(UserModel.id == user_id))
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_concurrent_manual_retry_requeues_failed_job_exactly_once() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    user_id, account_id = f"retry-user-{suffix}", f"retry-account-{suffix}"
    job_id = f"retry-job-{suffix}"
    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(UserModel).values(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    name="Retry",
                    password_hash=None,
                    base_currency="CZK",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await connection.execute(
                insert(AccountModel).values(
                    id=account_id,
                    name="Retry",
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
                    id=job_id,
                    user_id=user_id,
                    account_id=account_id,
                    kind=BackgroundJobKind.import_workflow,
                    status=BackgroundJobStatus.failed,
                    idempotency_key=job_id,
                    payload={"batch_ids": [job_id]},
                    checkpoint={},
                    progress={},
                    result=None,
                    error_code="background_job_attempts_exhausted",
                    error_message="Background processing exhausted retries.",
                    attempt_count=5,
                    manual_retry_count=0,
                    max_attempts=5,
                    run_after=NOW,
                    lease_owner=None,
                    lease_version=1,
                    lease_expires_at=None,
                    lease_heartbeat_at=None,
                    started_at=NOW - timedelta(minutes=5),
                    finished_at=NOW,
                    created_at=NOW - timedelta(minutes=10),
                    updated_at=NOW,
                )
            )

        async def retry_once() -> bool:
            async with sessions() as session:
                retried = await BackgroundJobRepository(session).retry_failed(
                    user_id=user_id,
                    account_id=account_id,
                    job_id=job_id,
                    now=NOW + timedelta(minutes=1),
                )
                await session.commit()
                assert retried is not None
                return retried.retried

        outcomes = await asyncio.gather(retry_once(), retry_once())
        assert sorted(outcomes) == [False, True]

        async with engine.connect() as connection:
            retried_row = (
                await connection.execute(
                    select(
                        BackgroundJobModel.status,
                        BackgroundJobModel.attempt_count,
                        BackgroundJobModel.manual_retry_count,
                        BackgroundJobModel.error_code,
                        BackgroundJobModel.started_at,
                        BackgroundJobModel.finished_at,
                    ).where(BackgroundJobModel.id == job_id)
                )
            ).one()
            assert retried_row == (BackgroundJobStatus.queued, 0, 1, None, None, None)
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(AccountModel).where(AccountModel.id == account_id))
            await connection.execute(delete(UserModel).where(UserModel.id == user_id))
        await engine.dispose()
