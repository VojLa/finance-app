"""PostgreSQL proof that import-event portfolio history is publication-fenced."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.db.models.accounts import AccountModel
from app.db.models.background_jobs import BackgroundJobModel
from app.db.models.canonical_lineage import DailySnapshotBaselineModel
from app.db.models.enums import (
    AccountType,
    BackgroundJobKind,
    BackgroundJobStatus,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.publication_targets import ImportJobPublicationTargetModel
from app.db.models.snapshots import NetWorthSnapshotModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.portfolio_history.repository import PortfolioHistoryRepository

DATABASE_URL = os.getenv("DATABASE_URL")
NOW = datetime(2034, 2, 3, 10, 15)

pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _job(
    job_id: str,
    user_id: str,
    account_id: str,
    status: BackgroundJobStatus,
) -> dict[str, object]:
    running = status is BackgroundJobStatus.running
    terminal = status in (BackgroundJobStatus.completed, BackgroundJobStatus.failed)
    return {
        "id": job_id,
        "user_id": user_id,
        "account_id": account_id,
        "kind": BackgroundJobKind.import_workflow,
        "status": status,
        "idempotency_key": job_id,
        "payload": {"schema_version": 1, "batch_ids": [job_id]},
        "checkpoint": {"schema_version": 1, "phase": "queued", "completed_batch_ids": []},
        "progress": {"schema_version": 1, "phase": "queued"},
        "result": {} if status is BackgroundJobStatus.completed else None,
        "error_code": "provider_failed" if status is BackgroundJobStatus.failed else None,
        "error_message": "Provider evidence could not be acquired."
        if status is BackgroundJobStatus.failed
        else None,
        "attempt_count": 1 if running else 0,
        "manual_retry_count": 0,
        "max_attempts": 5,
        "run_after": NOW,
        "lease_owner": "history-worker" if running else None,
        "lease_version": 1 if running else 0,
        "lease_expires_at": NOW + timedelta(minutes=5) if running else None,
        "lease_heartbeat_at": NOW if running else None,
        "started_at": NOW if running else None,
        "finished_at": NOW if terminal else None,
        "created_at": NOW,
        "updated_at": NOW,
    }


async def _snapshot(
    engine: AsyncEngine,
    *,
    snapshot_id: str,
    user_id: str,
    timestamp: datetime,
    source: SnapshotSource,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            insert(NetWorthSnapshotModel).values(
                id=snapshot_id,
                user_id=user_id,
                timestamp=timestamp,
                granularity=SnapshotGranularity.minute,
                source=source,
                currency="CZK",
                cash_value=Decimal("0"),
                portfolio_value=Decimal("0"),
                liabilities_value=Decimal("0"),
                total_net_worth=Decimal("0"),
                is_recalculated=False,
                calculated_at=timestamp,
                calculation_version=1,
                created_at=timestamp,
                cash_value_by_currency={},
                portfolio_value_by_currency={},
                liabilities_value_by_currency={},
                total_net_worth_by_currency={},
                exchange_rates={},
            )
        )


async def _anchor(
    engine: AsyncEngine,
    *,
    job_id: str,
    user_id: str,
    snapshot_id: str,
    bucket: datetime,
    published_at: datetime | None,
) -> None:
    async with engine.begin() as connection:
        await connection.execute(
            insert(ImportJobPublicationTargetModel).values(
                job_id=job_id, user_id=user_id, bucket=bucket, published_at=published_at
            )
        )
        await connection.execute(
            insert(DailySnapshotBaselineModel).values(
                id=f"history-baseline-{snapshot_id}",
                user_id=user_id,
                net_worth_snapshot_id=snapshot_id,
                timestamp=bucket,
                granularity=SnapshotGranularity.minute,
                currency="CZK",
                calculation_version=1,
                source=SnapshotSource.import_event,
                created_at=bucket,
                background_job_id=job_id,
            )
        )


@pytest.mark.integration
async def test_history_excludes_unpublished_failed_and_orphan_import_events() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex
    user_id, account_id = f"history-user-{suffix}", f"history-account-{suffix}"
    running_job, failed_job, completed_job = (
        f"history-running-{suffix}",
        f"history-failed-{suffix}",
        f"history-completed-{suffix}",
    )
    visible_id = f"history-prior-{suffix}"
    completed_id = f"history-completed-snapshot-{suffix}"
    try:
        async with engine.begin() as connection:
            await connection.execute(
                insert(UserModel).values(
                    id=user_id,
                    email=f"{user_id}@example.test",
                    name="History publication test",
                    password_hash=None,
                    base_currency="CZK",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await connection.execute(
                insert(AccountModel).values(
                    id=account_id,
                    name="History publication account",
                    type=AccountType.broker,
                    currency="CZK",
                    color=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                    notes=None,
                )
            )
            for job_id, status in (
                (running_job, BackgroundJobStatus.running),
                (failed_job, BackgroundJobStatus.failed),
                (completed_job, BackgroundJobStatus.completed),
            ):
                await connection.execute(
                    insert(BackgroundJobModel).values(**_job(job_id, user_id, account_id, status))
                )

        prior_at = NOW - timedelta(minutes=4)
        running_at, failed_at, orphan_at, completed_at = (
            NOW - timedelta(minutes=3),
            NOW - timedelta(minutes=2),
            NOW - timedelta(minutes=1),
            NOW,
        )
        await _snapshot(
            engine,
            snapshot_id=visible_id,
            user_id=user_id,
            timestamp=prior_at,
            source=SnapshotSource.scheduled,
        )
        await _snapshot(
            engine,
            snapshot_id=f"history-running-snapshot-{suffix}",
            user_id=user_id,
            timestamp=running_at,
            source=SnapshotSource.import_event,
        )
        await _snapshot(
            engine,
            snapshot_id=f"history-failed-snapshot-{suffix}",
            user_id=user_id,
            timestamp=failed_at,
            source=SnapshotSource.import_event,
        )
        await _snapshot(
            engine,
            snapshot_id=f"history-orphan-{suffix}",
            user_id=user_id,
            timestamp=orphan_at,
            source=SnapshotSource.import_event,
        )
        await _snapshot(
            engine,
            snapshot_id=completed_id,
            user_id=user_id,
            timestamp=completed_at,
            source=SnapshotSource.import_event,
        )
        await _anchor(
            engine,
            job_id=running_job,
            user_id=user_id,
            snapshot_id=f"history-running-snapshot-{suffix}",
            bucket=running_at,
            published_at=None,
        )
        await _anchor(
            engine,
            job_id=failed_job,
            user_id=user_id,
            snapshot_id=f"history-failed-snapshot-{suffix}",
            bucket=failed_at,
            published_at=failed_at,
        )
        await _anchor(
            engine,
            job_id=completed_job,
            user_id=user_id,
            snapshot_id=completed_id,
            bucket=completed_at,
            published_at=completed_at,
        )

        async with sessions() as session:
            points = await PortfolioHistoryRepository(session).load_candidate_points(
                user_id=user_id,
                currency="CZK",
                start=None,
                end=NOW,
            )
        assert tuple(point.snapshot_id for point in points) == (visible_id, completed_id)
    finally:
        async with engine.begin() as connection:
            await connection.execute(
                delete(DailySnapshotBaselineModel).where(
                    DailySnapshotBaselineModel.user_id == user_id
                )
            )
            await connection.execute(
                delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id == user_id)
            )
            await connection.execute(
                delete(ImportJobPublicationTargetModel).where(
                    ImportJobPublicationTargetModel.user_id == user_id
                )
            )
            await connection.execute(
                delete(BackgroundJobModel).where(BackgroundJobModel.account_id == account_id)
            )
            await connection.execute(delete(AccountModel).where(AccountModel.id == account_id))
            await connection.execute(delete(UserModel).where(UserModel.id == user_id))
        await engine.dispose()
