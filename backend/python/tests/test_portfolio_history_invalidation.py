import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models.snapshot_series_jobs import (
    SnapshotSeriesDirtyStateModel,
    SnapshotSeriesRebuildJobModel,
    SnapshotSeriesScheduleStateModel,
)
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.canonical_state.service import CanonicalChangeKind
from app.modules.market_data.source_policy import (
    CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
    MarketEvidenceSourcePolicy,
)
from app.modules.portfolio_history.invalidation.models import (
    CanonicalInvalidationEffect,
    HistoryDirtyReason,
)
from app.modules.portfolio_history.invalidation.repository import (
    PortfolioHistoryInvalidationRepository,
    invalidation_lock_id,
)
from app.modules.portfolio_history.invalidation.service import (
    R12_IMPORT_LINKED_KINDS,
    PortfolioHistoryInvalidationService,
    PortfolioHistoryInvalidationStateError,
)
from app.modules.portfolio_history.jobs.service import PortfolioHistoryJobService

AT = datetime(2031, 4, 5, 10)
DATABASE_URL = os.getenv("DATABASE_URL")


def test_canonical_invalidation_effect_is_exact_and_millisecond_bounded() -> None:
    effect = CanonicalInvalidationEffect(
        account_id="account-a",
        canonical_revision=1,
        kind=CanonicalChangeKind.transaction,
        entity_id="transaction-a",
        financial_timestamp=AT,
    )
    assert effect.financial_timestamp == AT

    for timestamp in (AT.replace(tzinfo=UTC), AT.replace(microsecond=1)):
        with pytest.raises(ValueError, match="effect is invalid"):
            CanonicalInvalidationEffect(
                account_id="account-a",
                canonical_revision=1,
                kind=CanonicalChangeKind.transaction,
                entity_id="transaction-a",
                financial_timestamp=timestamp,
            )


def test_r12_resolver_never_guesses_unlinked_liability_provenance() -> None:
    assert R12_IMPORT_LINKED_KINDS == {
        CanonicalChangeKind.transaction,
        CanonicalChangeKind.investment_event,
    }
    assert CanonicalChangeKind.liability_balance not in R12_IMPORT_LINKED_KINDS


def test_invalidation_advisory_lock_is_stable_and_user_scoped() -> None:
    assert invalidation_lock_id("user-a") == invalidation_lock_id("user-a")
    assert invalidation_lock_id("user-a") != invalidation_lock_id("user-b")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_policy",
    [CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY, LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY],
)
async def test_scope_invalidation_uses_explicit_source_policy_and_reenables_schedule(
    source_policy: MarketEvidenceSourcePolicy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []
    session = AsyncMock()
    session.in_transaction = Mock(return_value=True)
    dirty = SimpleNamespace(
        dirty_from=AT - timedelta(days=2),
        dirty_epoch=3,
        scope_dirty=False,
        reason_mask=1,
        requested_at=AT,
        updated_at=AT,
    )
    schedule = SimpleNamespace(
        enabled=False,
        timezone="Europe/Prague",
        cadence_minutes=30,
        last_dirty_epoch=3,
        policy_version=1,
        updated_at=AT,
    )
    repository = SimpleNamespace(
        lock_generation_users=AsyncMock(
            side_effect=lambda users: calls.append(("generation", users))
        ),
        lock_users=AsyncMock(side_effect=lambda users: calls.append(("invalidation", users))),
        lock_dirty=AsyncMock(return_value=dirty),
        lock_publication_replay_from=AsyncMock(return_value=AT - timedelta(days=5)),
        lock_schedule=AsyncMock(return_value=schedule),
    )
    jobs = SimpleNamespace(enqueue=AsyncMock())

    class _Replay:
        def __init__(self, _session: object, *, source_policy: object) -> None:
            calls.append(("policy", source_policy))

        async def load_frozen_scope_in_current_transaction(self, *, user_id: str) -> object:
            assert user_id == "user-a"
            return SimpleNamespace(earliest_event_at=AT - timedelta(days=4))

    monkeypatch.setattr(
        "app.modules.portfolio_history.invalidation.service.PortfolioHistoryReplayRepository",
        _Replay,
    )
    service = PortfolioHistoryInvalidationService(
        session,
        repository=cast(PortfolioHistoryInvalidationRepository, repository),
        jobs=cast(PortfolioHistoryJobService, jobs),
        source_policy=source_policy,
    )
    await service.lock_generation_users(("user-a",))
    result = await service.invalidate_scope_users(user_ids=("user-a",), now=AT)

    assert result.affected_users == ("user-a",)
    assert (result.inserted_receipts, result.enqueued_jobs) == (0, 1)
    assert calls[:3] == [
        ("generation", ("user-a",)),
        ("invalidation", ("user-a",)),
        ("policy", source_policy),
    ]
    assert dirty.dirty_epoch == 4
    assert dirty.dirty_from == AT - timedelta(days=5)
    assert dirty.scope_dirty is True
    assert dirty.reason_mask == 3
    assert schedule.enabled is True
    assert schedule.last_dirty_epoch == 4
    jobs.enqueue.assert_awaited_once()


@pytest.mark.asyncio
async def test_scope_invalidation_requires_explicit_policy_and_generation_lock() -> None:
    session = AsyncMock()
    session.in_transaction = Mock(return_value=True)
    service = PortfolioHistoryInvalidationService(session)

    with pytest.raises(PortfolioHistoryInvalidationStateError):
        await service.invalidate_scope_users(user_ids=("user-a",), now=AT)


@pytest.mark.asyncio
async def test_clean_period_keeps_dirty_epoch_monotonic() -> None:
    session = AsyncMock()
    session.add = Mock()
    session.in_transaction = Mock(return_value=True)
    schedule = SimpleNamespace(
        enabled=True,
        timezone="Europe/Prague",
        cadence_minutes=30,
        last_dirty_epoch=1,
        updated_at=AT,
    )
    repository = SimpleNamespace(lock_schedule=AsyncMock(return_value=schedule))
    jobs = SimpleNamespace(enqueue=AsyncMock())
    service = PortfolioHistoryInvalidationService(
        session,
        repository=cast(PortfolioHistoryInvalidationRepository, repository),
        jobs=cast(PortfolioHistoryJobService, jobs),
        source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    )

    epoch = await service._mark_dirty(
        user_id="user-a",
        dirty=None,
        dirty_from=AT,
        reason=HistoryDirtyReason.canonical_change,
        scope_dirty=False,
        now=AT,
    )

    assert epoch == 2
    assert schedule.last_dirty_epoch == 2
    created_dirty = session.add.call_args.args[0]
    assert created_dirty.dirty_epoch == 2
    assert jobs.enqueue.await_args.kwargs["payload"]["dirty_epoch"] == 2


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required")
async def test_clean_persisted_cursor_advances_to_next_epoch() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    user_id = "snapshot-series-monotonic-epoch-user"
    try:
        async with sessions() as session, session.begin():
            await session.execute(delete(UserModel).where(UserModel.id == user_id))
            session.add(
                UserModel(
                    id=user_id,
                    email="snapshot-series-epoch@example.test",
                    name=None,
                    password_hash=None,
                    base_currency="CZK",
                    created_at=AT,
                    updated_at=AT,
                )
            )
            await session.flush()
            session.add(
                SnapshotSeriesScheduleStateModel(
                    user_id=user_id,
                    enabled=True,
                    timezone="Europe/Prague",
                    cadence_minutes=30,
                    next_capture_at=AT + timedelta(minutes=30),
                    last_captured_bucket=None,
                    last_dirty_epoch=7,
                    updated_at=AT,
                )
            )
        async with sessions() as session, session.begin():
            service = PortfolioHistoryInvalidationService(
                session,
                source_policy=CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
            )
            epoch = await service._mark_dirty(
                user_id=user_id,
                dirty=None,
                dirty_from=AT,
                reason=HistoryDirtyReason.scope_change,
                scope_dirty=True,
                now=AT,
            )
            assert epoch == 8
        async with sessions() as session:
            schedule = await session.scalar(
                select(SnapshotSeriesScheduleStateModel).where(
                    SnapshotSeriesScheduleStateModel.user_id == user_id
                )
            )
            dirty = await session.scalar(
                select(SnapshotSeriesDirtyStateModel).where(
                    SnapshotSeriesDirtyStateModel.user_id == user_id
                )
            )
            job = await session.scalar(
                select(SnapshotSeriesRebuildJobModel).where(
                    SnapshotSeriesRebuildJobModel.user_id == user_id
                )
            )
            assert schedule is not None and schedule.last_dirty_epoch == 8
            assert dirty is not None and dirty.dirty_epoch == 8
            assert job is not None and job.payload["dirty_epoch"] == 8
    finally:
        async with sessions() as session, session.begin():
            await session.execute(delete(UserModel).where(UserModel.id == user_id))
        await engine.dispose()
