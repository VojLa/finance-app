from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.background_jobs import (
    BackgroundJobModel,
    ImportJobAffectedAccountModel,
)
from app.db.models.canonical_lineage import (
    AccountCanonicalStateModel,
    DailySnapshotBaselineAccountModel,
    DailySnapshotBaselineModel,
)
from app.db.models.enums import BackgroundJobKind, BackgroundJobStatus
from app.db.models.publication_targets import ImportJobPublicationTargetModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel


@dataclass(frozen=True, slots=True)
class ImportPublicationTarget:
    user_id: str
    bucket: datetime


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RuntimeError("Import publication target is invalid.")
    return value


def _bucket(value: datetime) -> datetime:
    if value.tzinfo is not None or value.second or value.microsecond:
        raise RuntimeError("Import publication target is invalid.")
    return value


def _lock_id(user_id: str) -> int:
    return int.from_bytes(
        sha256(f"import-publication:{user_id}".encode()).digest()[:8], "big", signed=True
    )


class ImportJobPublicationService:
    """Reserve one minute slot per member and freeze it once evidence exists."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def reserve(
        self,
        *,
        job_id: str,
        account_id: str,
        requested_bucket: datetime,
    ) -> tuple[ImportPublicationTarget, ...]:
        if self.session.in_transaction():
            raise RuntimeError("Import publication reservation requires an idle session.")
        canonical_job_id = _text(job_id)
        canonical_account_id = _text(account_id)
        bucket = _bucket(requested_bucket)
        async with self.session.begin():
            await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
            job = await self.session.scalar(
                select(BackgroundJobModel)
                .where(BackgroundJobModel.id == canonical_job_id)
                .with_for_update()
            )
            if (
                job is None
                or job.account_id != canonical_account_id
                or job.kind is not BackgroundJobKind.import_workflow
                or job.status is not BackgroundJobStatus.running
            ):
                raise RuntimeError("Import publication job is invalid.")
            affected_rows = tuple(
                (
                    await self.session.scalars(
                        select(ImportJobAffectedAccountModel)
                        .where(ImportJobAffectedAccountModel.job_id == canonical_job_id)
                        .order_by(ImportJobAffectedAccountModel.account_id)
                        .with_for_update()
                    )
                ).all()
            )
            affected_account_ids = (
                tuple(row.account_id for row in affected_rows)
                if affected_rows
                else (canonical_account_id,)
            )
            if (
                canonical_account_id not in affected_account_ids
                or len(set(affected_account_ids)) != len(affected_account_ids)
                or any(row.user_id != job.user_id for row in affected_rows)
            ):
                raise RuntimeError("Import publication affected accounts are invalid.")
            accounts = tuple(
                (
                    await self.session.scalars(
                        select(AccountModel)
                        .where(AccountModel.id.in_(affected_account_ids))
                        .order_by(AccountModel.id)
                        .with_for_update()
                    )
                ).all()
            )
            if tuple(account.id for account in accounts) != affected_account_ids:
                raise RuntimeError("Import publication account is invalid.")
            existing_targets = tuple(
                (
                    await self.session.scalars(
                        select(ImportJobPublicationTargetModel)
                        .where(ImportJobPublicationTargetModel.job_id == canonical_job_id)
                        .order_by(ImportJobPublicationTargetModel.user_id)
                        .with_for_update()
                    )
                ).all()
            )
            users = tuple(
                (
                    await self.session.scalars(
                        select(AccountMemberModel.user_id)
                        .where(AccountMemberModel.account_id.in_(affected_account_ids))
                        .distinct()
                        .order_by(AccountMemberModel.user_id)
                    )
                ).all()
            )
            if not users or len(users) != len(set(users)):
                raise RuntimeError("Import publication members are invalid.")
            removed = tuple(target for target in existing_targets if target.user_id not in users)
            if any(target.published_at is not None for target in removed):
                raise RuntimeError("Import publication membership is no longer valid.")
            if removed:
                removed_users = tuple(target.user_id for target in removed)
                await self.session.execute(
                    delete(DailySnapshotBaselineModel).where(
                        DailySnapshotBaselineModel.background_job_id == canonical_job_id,
                        DailySnapshotBaselineModel.user_id.in_(removed_users),
                    )
                )
                for target in removed:
                    await self.session.delete(target)
            targets: list[ImportPublicationTarget] = []
            for user_id in users:
                await self.session.execute(
                    select(text("pg_advisory_xact_lock(:lock_id)")).params(
                        lock_id=_lock_id(user_id)
                    )
                )
                existing = await self.session.get(
                    ImportJobPublicationTargetModel,
                    (canonical_job_id, user_id),
                )
                if existing is not None:
                    if existing.published_at is not None:
                        raise RuntimeError("Import publication target is already published.")
                    anchor = await self.session.scalar(
                        select(DailySnapshotBaselineModel).where(
                            DailySnapshotBaselineModel.background_job_id == canonical_job_id,
                            DailySnapshotBaselineModel.user_id == user_id,
                        )
                    )
                    # A job-linked anchor is the immutable publication
                    # boundary. Retargeting an unused row must not delete or
                    # be blocked by unrelated manual snapshot evidence.
                    if existing.bucket >= bucket:
                        targets.append(
                            ImportPublicationTarget(user_id=user_id, bucket=existing.bucket)
                        )
                        continue
                    if anchor is not None:
                        anchor_rows = tuple(
                            (
                                await self.session.scalars(
                                    select(DailySnapshotBaselineAccountModel)
                                    .where(
                                        DailySnapshotBaselineAccountModel.baseline_id == anchor.id
                                    )
                                    .order_by(DailySnapshotBaselineAccountModel.account_id)
                                    .with_for_update()
                                )
                            ).all()
                        )
                        anchor_account_ids = tuple(item.account_id for item in anchor_rows)
                        states = tuple(
                            (
                                await self.session.scalars(
                                    select(AccountCanonicalStateModel)
                                    .where(
                                        AccountCanonicalStateModel.account_id.in_(
                                            anchor_account_ids
                                        )
                                    )
                                    .order_by(AccountCanonicalStateModel.account_id)
                                    .with_for_update()
                                )
                            ).all()
                        )
                        revisions = {state.account_id: state.last_revision for state in states}
                        target_affected = set(
                            (
                                await self.session.scalars(
                                    select(AccountMemberModel.account_id).where(
                                        AccountMemberModel.user_id == user_id,
                                        AccountMemberModel.account_id.in_(affected_account_ids),
                                    )
                                )
                            ).all()
                        )
                        # An unpublished anchor freezes its bucket only while
                        # it still proves the account's current canonical
                        # boundary. A retry after a concurrent canonical post
                        # retires *only* this job's stale baseline/target and
                        # reacquires evidence in a later free minute.
                        if (
                            anchor_rows
                            and target_affected.issubset(anchor_account_ids)
                            and set(revisions) == set(anchor_account_ids)
                            and all(
                                revisions[item.account_id] == item.canonical_revision
                                for item in anchor_rows
                            )
                        ):
                            targets.append(
                                ImportPublicationTarget(user_id=user_id, bucket=existing.bucket)
                            )
                            continue
                        await self.session.delete(anchor)
                        # Keep the durable target's composite identity.  In
                        # particular, sessions used by the production worker
                        # may run with autoflush disabled: deleting and
                        # reinserting the same `(job_id, user_id)` in that
                        # session can otherwise flush in INSERT-before-DELETE
                        # order and violate the primary key.  The stale,
                        # job-linked anchor must be gone before the bucket
                        # moves, but the target itself is retargeted in place.
                        await self.session.flush()
                candidate = bucket
                while True:
                    occupied = await self.session.scalar(
                        select(ImportJobPublicationTargetModel.job_id).where(
                            ImportJobPublicationTargetModel.user_id == user_id,
                            ImportJobPublicationTargetModel.bucket == candidate,
                        )
                    )
                    visible_account_ids = tuple(
                        (
                            await self.session.scalars(
                                select(AccountMemberModel.account_id)
                                .where(AccountMemberModel.user_id == user_id)
                                .order_by(AccountMemberModel.account_id)
                            )
                        ).all()
                    )
                    existing_snapshot = await self.session.scalar(
                        select(NetWorthSnapshotModel.id).where(
                            NetWorthSnapshotModel.user_id == user_id,
                            NetWorthSnapshotModel.timestamp == candidate,
                        )
                    )
                    existing_account_snapshot = (
                        await self.session.scalar(
                            select(AccountSnapshotModel.id).where(
                                AccountSnapshotModel.account_id.in_(visible_account_ids),
                                AccountSnapshotModel.timestamp == candidate,
                            )
                        )
                        if visible_account_ids
                        else None
                    )
                    if (
                        occupied is None
                        and existing_snapshot is None
                        and existing_account_snapshot is None
                    ):
                        if existing is None:
                            await self.session.execute(
                                insert(ImportJobPublicationTargetModel).values(
                                    job_id=canonical_job_id,
                                    user_id=user_id,
                                    bucket=candidate,
                                    published_at=None,
                                )
                            )
                        else:
                            existing.bucket = candidate
                        targets.append(ImportPublicationTarget(user_id=user_id, bucket=candidate))
                        break
                    candidate += timedelta(minutes=1)
            return tuple(targets)
