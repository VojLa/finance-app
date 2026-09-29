"""Transactional history invalidation after canonical publication effects."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.background_jobs import ImportJobBatchModel
from app.db.models.canonical_lineage import AccountCanonicalChangeModel
from app.db.models.enums import SnapshotSeriesJobKind
from app.db.models.ledger import InvestmentEventModel
from app.db.models.snapshot_series_jobs import (
    SnapshotSeriesDirtyStateModel as PortfolioHistoryDirtyStateModel,
)
from app.db.models.snapshot_series_jobs import (
    SnapshotSeriesScheduleStateModel as PortfolioHistoryScheduleStateModel,
)
from app.db.models.transactions import TransactionModel
from app.modules.canonical_state.service import CanonicalChangeKind, RecordedCanonicalChange
from app.modules.market_data.source_policy import (
    MarketEvidenceSourcePolicy,
    validate_market_evidence_source_policy,
)
from app.modules.portfolio_history.invalidation.models import (
    CanonicalInvalidationEffect,
    HistoryDirtyReason,
    PortfolioHistoryInvalidationResult,
)
from app.modules.portfolio_history.invalidation.repository import (
    PortfolioHistoryInvalidationRepository,
)
from app.modules.portfolio_history.jobs.service import PortfolioHistoryJobService
from app.modules.portfolio_history.lattice import HistoryResolution, history_bucket
from app.modules.portfolio_history.scheduler.service import DEFAULT_HISTORY_JOB_MAX_ATTEMPTS
from app.modules.portfolio_history_rebuild.repository import PortfolioHistoryReplayRepository

# R12 import posting creates only Transaction and InvestmentEvent canonical
# roots. LiabilityBalance has no importBatchId/provenance column and is written
# only through the manual liability boundary; guessing it from timestamps would
# violate exact import publication lineage. Its writer needs the same generic
# invalidation service, not an unsafe R12 resolver heuristic.
R12_IMPORT_LINKED_KINDS = frozenset(
    (CanonicalChangeKind.transaction, CanonicalChangeKind.investment_event)
)


class PortfolioHistoryInvalidationStateError(RuntimeError):
    """The exact canonical/member invalidation boundary is inconsistent."""


class PortfolioHistoryInvalidationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: PortfolioHistoryInvalidationRepository | None = None,
        jobs: PortfolioHistoryJobService | None = None,
        source_policy: MarketEvidenceSourcePolicy | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or PortfolioHistoryInvalidationRepository(session)
        self.jobs = jobs or PortfolioHistoryJobService(session)
        self.source_policy = (
            None if source_policy is None else validate_market_evidence_source_policy(source_policy)
        )
        self._generation_locked_users: set[str] = set()

    async def lock_generation_users(self, user_ids: tuple[str, ...]) -> None:
        if (
            not self.session.in_transaction()
            or user_ids != tuple(sorted(set(user_ids)))
            or not user_ids
            or any(not user_id or user_id != user_id.strip() for user_id in user_ids)
        ):
            raise PortfolioHistoryInvalidationStateError(
                "Portfolio history generation lock scope is invalid."
            )
        await self.repository.lock_generation_users(user_ids)
        self._generation_locked_users.update(user_ids)

    async def lock_current_memberships(
        self, account_ids: tuple[str, ...]
    ) -> tuple[tuple[str, str], ...]:
        if (
            not self.session.in_transaction()
            or account_ids != tuple(sorted(set(account_ids)))
            or not account_ids
            or any(not account_id or account_id != account_id.strip() for account_id in account_ids)
        ):
            raise PortfolioHistoryInvalidationStateError(
                "Canonical history membership lock scope is invalid."
            )
        memberships = await self.repository.lock_current_memberships(account_ids)
        if memberships != tuple(sorted(set(memberships))):
            raise PortfolioHistoryInvalidationStateError(
                "Canonical history membership lock result is invalid."
            )
        return memberships

    async def invalidate_recorded_changes(
        self,
        *,
        changes: tuple[RecordedCanonicalChange, ...],
        locked_memberships: tuple[tuple[str, str], ...],
        now: datetime,
    ) -> PortfolioHistoryInvalidationResult:
        if (
            type(changes) is not tuple
            or any(type(change) is not RecordedCanonicalChange for change in changes)
            or changes != tuple(sorted(changes, key=lambda item: (item.account_id, item.revision)))
            or len({(item.account_id, item.revision) for item in changes}) != len(changes)
        ):
            raise PortfolioHistoryInvalidationStateError(
                "Recorded canonical history changes are invalid."
            )
        effects = tuple(
            CanonicalInvalidationEffect(
                account_id=change.account_id,
                canonical_revision=change.revision,
                kind=change.kind,
                entity_id=change.entity_id,
                financial_timestamp=change.financial_timestamp,
            )
            for change in changes
        )
        return await self.invalidate_current_members(
            effects=effects,
            locked_memberships=locked_memberships,
            reason=HistoryDirtyReason.canonical_change,
            scope_dirty=False,
            now=now,
        )

    async def resolve_r12_import_effects(
        self,
        *,
        job_id: str,
        affected_account_ids: tuple[str, ...],
        batch_ids: tuple[str, ...],
    ) -> tuple[CanonicalInvalidationEffect, ...]:
        if (
            not self.session.in_transaction()
            or not job_id
            or affected_account_ids != tuple(sorted(set(affected_account_ids)))
            or not affected_account_ids
            or batch_ids != tuple(sorted(set(batch_ids)))
            or not batch_ids
        ):
            raise PortfolioHistoryInvalidationStateError(
                "R12 history invalidation manifest is invalid."
            )
        queries = (
            (
                CanonicalChangeKind.transaction,
                select(AccountCanonicalChangeModel, TransactionModel.date)
                .join(
                    TransactionModel,
                    TransactionModel.id == AccountCanonicalChangeModel.entity_id,
                )
                .join(
                    ImportJobBatchModel,
                    ImportJobBatchModel.batch_id == TransactionModel.import_batch_id,
                )
                .where(
                    ImportJobBatchModel.job_id == job_id,
                    ImportJobBatchModel.batch_id.in_(batch_ids),
                    AccountCanonicalChangeModel.kind == CanonicalChangeKind.transaction.value,
                    AccountCanonicalChangeModel.account_id.in_(affected_account_ids),
                    TransactionModel.account_id == AccountCanonicalChangeModel.account_id,
                ),
            ),
            (
                CanonicalChangeKind.investment_event,
                select(AccountCanonicalChangeModel, InvestmentEventModel.date)
                .join(
                    InvestmentEventModel,
                    InvestmentEventModel.id == AccountCanonicalChangeModel.entity_id,
                )
                .join(
                    ImportJobBatchModel,
                    ImportJobBatchModel.batch_id == InvestmentEventModel.import_batch_id,
                )
                .where(
                    ImportJobBatchModel.job_id == job_id,
                    ImportJobBatchModel.batch_id.in_(batch_ids),
                    AccountCanonicalChangeModel.kind == CanonicalChangeKind.investment_event.value,
                    AccountCanonicalChangeModel.account_id.in_(affected_account_ids),
                    InvestmentEventModel.account_id == AccountCanonicalChangeModel.account_id,
                ),
            ),
        )
        effects: list[CanonicalInvalidationEffect] = []
        identities: set[tuple[str, int]] = set()
        for expected_kind, statement in queries:
            rows = tuple(
                await self.session.execute(
                    statement.order_by(
                        AccountCanonicalChangeModel.account_id,
                        AccountCanonicalChangeModel.revision,
                    )
                    .with_for_update(of=AccountCanonicalChangeModel)
                    .execution_options(populate_existing=True)
                )
            )
            for row, entity_financial_timestamp in rows:
                if row.financial_timestamp != entity_financial_timestamp:
                    raise PortfolioHistoryInvalidationStateError(
                        "R12 canonical invalidation timestamp lineage is inconsistent."
                    )
                effect = CanonicalInvalidationEffect(
                    account_id=row.account_id,
                    canonical_revision=row.revision,
                    kind=expected_kind,
                    entity_id=row.entity_id,
                    financial_timestamp=row.financial_timestamp,
                )
                identity = (effect.account_id, effect.canonical_revision)
                if identity in identities or row.kind != expected_kind.value:
                    raise PortfolioHistoryInvalidationStateError(
                        "R12 canonical invalidation lineage is ambiguous."
                    )
                identities.add(identity)
                effects.append(effect)
        return tuple(sorted(effects, key=lambda item: (item.account_id, item.canonical_revision)))

    async def invalidate_current_members(
        self,
        *,
        effects: tuple[CanonicalInvalidationEffect, ...],
        locked_memberships: tuple[tuple[str, str], ...],
        reason: HistoryDirtyReason,
        scope_dirty: bool,
        now: datetime,
        initiating_user_id: str | None = None,
        requested_by_background_job_id: str | None = None,
    ) -> PortfolioHistoryInvalidationResult:
        if (
            not self.session.in_transaction()
            or type(effects) is not tuple
            or any(type(effect) is not CanonicalInvalidationEffect for effect in effects)
            or effects
            != tuple(sorted(effects, key=lambda item: (item.account_id, item.canonical_revision)))
            or len({(item.account_id, item.canonical_revision) for item in effects}) != len(effects)
            or locked_memberships != tuple(sorted(set(locked_memberships)))
            or type(reason) is not HistoryDirtyReason
            or reason.value < 1
            or type(scope_dirty) is not bool
            or type(now) is not datetime
            or now.tzinfo is not None
            or now.microsecond % 1_000
            or (requested_by_background_job_id is None) != (initiating_user_id is None)
        ):
            raise PortfolioHistoryInvalidationStateError(
                "Canonical history invalidation input is invalid."
            )
        members_by_account: defaultdict[str, set[str]] = defaultdict(set)
        for account_id, user_id in locked_memberships:
            if not account_id or not user_id:
                raise PortfolioHistoryInvalidationStateError(
                    "Canonical history membership is invalid."
                )
            members_by_account[account_id].add(user_id)
        effects_by_user: defaultdict[str, list[CanonicalInvalidationEffect]] = defaultdict(list)
        for effect in effects:
            for user_id in sorted(members_by_account[effect.account_id]):
                effects_by_user[user_id].append(effect)
        user_ids = tuple(sorted(effects_by_user))
        await self.repository.lock_users(user_ids)
        affected_users: list[str] = []
        receipt_count = 0
        job_count = 0
        for user_id in user_ids:
            missing = await self.repository.missing_effects(
                user_id=user_id, effects=tuple(effects_by_user[user_id])
            )
            if not missing:
                continue
            dirty_from = min(effect.financial_timestamp for effect in missing)
            schedule = await self.repository.lock_schedule(user_id)
            if schedule is None:
                schedule = PortfolioHistoryScheduleStateModel(
                    user_id=user_id,
                    enabled=True,
                    timezone="Europe/Prague",
                    cadence_minutes=30,
                    next_capture_at=history_bucket(now, HistoryResolution.minutes_30).end,
                    last_captured_bucket=None,
                    last_dirty_epoch=0,
                    updated_at=now,
                )
                self.session.add(schedule)
            elif schedule.timezone != "Europe/Prague" or schedule.cadence_minutes != 30:
                raise PortfolioHistoryInvalidationStateError(
                    "Portfolio history schedule policy is inconsistent."
                )
            dirty = await self.repository.lock_dirty(user_id)
            epoch = max(schedule.last_dirty_epoch, 0 if dirty is None else dirty.dirty_epoch) + 1
            schedule.last_dirty_epoch = epoch
            schedule.enabled = True
            schedule.updated_at = now
            if dirty is None:
                dirty = PortfolioHistoryDirtyStateModel(
                    user_id=user_id,
                    dirty_from=dirty_from,
                    dirty_epoch=epoch,
                    scope_dirty=scope_dirty,
                    reason_mask=reason.value,
                    requested_at=now,
                    updated_at=now,
                )
                self.session.add(dirty)
            else:
                dirty.dirty_epoch = epoch
                dirty.dirty_from = min(dirty.dirty_from, dirty_from)
                dirty.scope_dirty = dirty.scope_dirty or scope_dirty
                dirty.reason_mask |= reason.value
                dirty.requested_at = min(dirty.requested_at, now)
                dirty.updated_at = now
            await self.session.flush()
            inserted = await self.repository.insert_receipts(
                user_id=user_id,
                effects=missing,
                first_dirty_epoch=epoch,
                invalidated_at=now,
            )
            if inserted != len(missing):
                raise PortfolioHistoryInvalidationStateError(
                    "Canonical history invalidation replay raced its durable receipt."
                )
            await self.jobs.enqueue(
                actor_user_id=user_id,
                kind=SnapshotSeriesJobKind.rebuild,
                payload={"dirty_epoch": epoch, "dirty_from": dirty.dirty_from},
                max_attempts=DEFAULT_HISTORY_JOB_MAX_ATTEMPTS,
                now=now,
                requested_by_background_job_id=(
                    requested_by_background_job_id if user_id == initiating_user_id else None
                ),
            )
            affected_users.append(user_id)
            receipt_count += inserted
            job_count += 1
        return PortfolioHistoryInvalidationResult(
            affected_users=tuple(affected_users),
            inserted_receipts=receipt_count,
            enqueued_jobs=job_count,
        )

    async def invalidate_scope_users(
        self,
        *,
        user_ids: tuple[str, ...],
        now: datetime,
    ) -> PortfolioHistoryInvalidationResult:
        if (
            not self.session.in_transaction()
            or user_ids != tuple(sorted(set(user_ids)))
            or not user_ids
            or any(not user_id or user_id != user_id.strip() for user_id in user_ids)
            or not set(user_ids).issubset(self._generation_locked_users)
            or self.source_policy is None
            or type(now) is not datetime
            or now.tzinfo is not None
            or now.microsecond % 1_000
        ):
            raise PortfolioHistoryInvalidationStateError(
                "Portfolio history scope invalidation input is invalid."
            )
        await self.session.flush()
        await self.repository.lock_users(user_ids)
        affected_users: list[str] = []
        job_count = 0
        for user_id in user_ids:
            replay = await PortfolioHistoryReplayRepository(
                self.session,
                source_policy=self.source_policy,
            ).load_frozen_scope_in_current_transaction(user_id=user_id)
            dirty = await self.repository.lock_dirty(user_id)
            publication_replay_from = await self.repository.lock_publication_replay_from(user_id)
            boundaries = tuple(
                value
                for value in (
                    None if dirty is None else dirty.dirty_from,
                    publication_replay_from,
                    replay.earliest_event_at,
                )
                if value is not None
            )
            if replay.earliest_event_at is None:
                if dirty is None and publication_replay_from is None:
                    continue
            if not boundaries:
                raise PortfolioHistoryInvalidationStateError(
                    "Portfolio history scope boundary is unavailable."
                )
            await self._mark_dirty(
                user_id=user_id,
                dirty=dirty,
                dirty_from=min(boundaries),
                reason=HistoryDirtyReason.scope_change,
                scope_dirty=True,
                now=now,
            )
            affected_users.append(user_id)
            job_count += 1
        return PortfolioHistoryInvalidationResult(
            affected_users=tuple(affected_users),
            inserted_receipts=0,
            enqueued_jobs=job_count,
        )

    async def _mark_dirty(
        self,
        *,
        user_id: str,
        dirty: PortfolioHistoryDirtyStateModel | None,
        dirty_from: datetime,
        reason: HistoryDirtyReason,
        scope_dirty: bool,
        now: datetime,
    ) -> int:
        schedule = await self.repository.lock_schedule(user_id)
        if schedule is None:
            schedule = PortfolioHistoryScheduleStateModel(
                user_id=user_id,
                enabled=True,
                timezone="Europe/Prague",
                cadence_minutes=30,
                next_capture_at=history_bucket(now, HistoryResolution.minutes_30).end,
                last_captured_bucket=None,
                last_dirty_epoch=0,
                updated_at=now,
            )
            self.session.add(schedule)
        elif schedule.timezone != "Europe/Prague" or schedule.cadence_minutes != 30:
            raise PortfolioHistoryInvalidationStateError(
                "Portfolio history schedule policy is inconsistent."
            )
        epoch = max(schedule.last_dirty_epoch, 0 if dirty is None else dirty.dirty_epoch) + 1
        schedule.last_dirty_epoch = epoch
        schedule.enabled = True
        schedule.updated_at = now
        if dirty is None:
            dirty = PortfolioHistoryDirtyStateModel(
                user_id=user_id,
                dirty_from=dirty_from,
                dirty_epoch=epoch,
                scope_dirty=scope_dirty,
                reason_mask=reason.value,
                requested_at=now,
                updated_at=now,
            )
            self.session.add(dirty)
        else:
            dirty.dirty_epoch = epoch
            dirty.dirty_from = min(dirty.dirty_from, dirty_from)
            dirty.scope_dirty = dirty.scope_dirty or scope_dirty
            dirty.reason_mask |= reason.value
            dirty.requested_at = min(dirty.requested_at, now)
            dirty.updated_at = now
        await self.session.flush()
        await self.jobs.enqueue(
            actor_user_id=user_id,
            kind=SnapshotSeriesJobKind.rebuild,
            payload={"dirty_epoch": epoch, "dirty_from": dirty.dirty_from},
            max_attempts=DEFAULT_HISTORY_JOB_MAX_ATTEMPTS,
            now=now,
        )
        return epoch


__all__ = [
    "R12_IMPORT_LINKED_KINDS",
    "PortfolioHistoryInvalidationService",
    "PortfolioHistoryInvalidationStateError",
]
