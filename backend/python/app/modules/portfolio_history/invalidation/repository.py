"""PostgreSQL persistence for immutable history invalidation receipts."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from hashlib import sha256

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel
from app.db.models.canonical_lineage import (
    DailySnapshotBaselineModel,
    UserReadModelPublicationModel,
)
from app.db.models.snapshot_series_jobs import (
    SnapshotSeriesCanonicalInvalidationModel as PortfolioHistoryCanonicalInvalidationModel,
)
from app.db.models.snapshot_series_jobs import (
    SnapshotSeriesDirtyStateModel as PortfolioHistoryDirtyStateModel,
)
from app.db.models.snapshot_series_jobs import (
    SnapshotSeriesScheduleStateModel as PortfolioHistoryScheduleStateModel,
)
from app.modules.portfolio_history.invalidation.models import CanonicalInvalidationEffect

_LOOKUP_CHUNK = 1_000


def invalidation_lock_id(user_id: str) -> int:
    digest = sha256(f"portfolio-history-invalidation\0{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def generation_lock_id(user_id: str) -> int:
    digest = sha256(f"snapshot-series-publication\0{user_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def _chunks(values: tuple[tuple[str, int], ...]) -> Iterable[tuple[tuple[str, int], ...]]:
    for offset in range(0, len(values), _LOOKUP_CHUNK):
        yield values[offset : offset + _LOOKUP_CHUNK]


class PortfolioHistoryInvalidationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_users(self, user_ids: tuple[str, ...]) -> None:
        for user_id in user_ids:
            await self.session.execute(
                select(func.pg_advisory_xact_lock(invalidation_lock_id(user_id)))
            )

    async def lock_generation_users(self, user_ids: tuple[str, ...]) -> None:
        for user_id in user_ids:
            await self.session.execute(
                select(func.pg_advisory_xact_lock(generation_lock_id(user_id)))
            )

    async def lock_current_memberships(
        self, account_ids: tuple[str, ...]
    ) -> tuple[tuple[str, str], ...]:
        rows = await self.session.execute(
            select(AccountMemberModel.account_id, AccountMemberModel.user_id)
            .where(
                AccountMemberModel.account_id.in_(account_ids),
                AccountMemberModel.accepted_at.is_not(None),
            )
            .order_by(AccountMemberModel.account_id, AccountMemberModel.user_id)
            .with_for_update(of=AccountMemberModel)
            .execution_options(populate_existing=True)
        )
        return tuple((account_id, user_id) for account_id, user_id in rows)

    async def missing_effects(
        self, *, user_id: str, effects: tuple[CanonicalInvalidationEffect, ...]
    ) -> tuple[CanonicalInvalidationEffect, ...]:
        identities = tuple((effect.account_id, effect.canonical_revision) for effect in effects)
        existing: set[tuple[str, int]] = set()
        for chunk in _chunks(identities):
            rows = await self.session.execute(
                select(
                    PortfolioHistoryCanonicalInvalidationModel.account_id,
                    PortfolioHistoryCanonicalInvalidationModel.canonical_revision,
                ).where(
                    PortfolioHistoryCanonicalInvalidationModel.user_id == user_id,
                    tuple_(
                        PortfolioHistoryCanonicalInvalidationModel.account_id,
                        PortfolioHistoryCanonicalInvalidationModel.canonical_revision,
                    ).in_(chunk),
                )
            )
            existing.update((account_id, revision) for account_id, revision in rows)
        return tuple(
            effect
            for effect in effects
            if (effect.account_id, effect.canonical_revision) not in existing
        )

    async def lock_dirty(self, user_id: str) -> PortfolioHistoryDirtyStateModel | None:
        return await self.session.scalar(
            select(PortfolioHistoryDirtyStateModel)
            .where(PortfolioHistoryDirtyStateModel.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def insert_receipts(
        self,
        *,
        user_id: str,
        effects: tuple[CanonicalInvalidationEffect, ...],
        first_dirty_epoch: int,
        invalidated_at: datetime,
    ) -> int:
        if not effects:
            return 0
        rows = [
            {
                "userId": user_id,
                "accountId": effect.account_id,
                "canonicalRevision": effect.canonical_revision,
                "kind": effect.kind.value,
                "entityId": effect.entity_id,
                "financialTimestamp": effect.financial_timestamp,
                "firstDirtyEpoch": first_dirty_epoch,
                "invalidatedAt": invalidated_at,
                "resolvedAt": None,
                "resolvedSnapshotGenerationId": None,
            }
            for effect in effects
        ]
        inserted = tuple(
            await self.session.scalars(
                insert(PortfolioHistoryCanonicalInvalidationModel)
                .values(rows)
                .on_conflict_do_nothing(index_elements=("userId", "accountId", "canonicalRevision"))
                .returning(PortfolioHistoryCanonicalInvalidationModel.canonical_revision)
            )
        )
        return len(inserted)

    async def lock_schedule(self, user_id: str) -> PortfolioHistoryScheduleStateModel | None:
        return await self.session.scalar(
            select(PortfolioHistoryScheduleStateModel)
            .where(PortfolioHistoryScheduleStateModel.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def lock_publication_replay_from(self, user_id: str) -> datetime | None:
        publication = await self.session.scalar(
            select(UserReadModelPublicationModel)
            .where(UserReadModelPublicationModel.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if publication is None:
            return None
        replay_from = await self.session.scalar(
            select(func.min(DailySnapshotBaselineModel.timestamp)).where(
                DailySnapshotBaselineModel.generation_id == publication.generation_id,
                DailySnapshotBaselineModel.user_id == user_id,
            )
        )
        if replay_from is None:
            raise RuntimeError("Published snapshot series is missing its baseline coverage.")
        return replay_from


__all__ = ["PortfolioHistoryInvalidationRepository", "invalidation_lock_id"]
