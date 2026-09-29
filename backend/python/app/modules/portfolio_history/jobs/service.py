"""Authorization and validation boundary for history-job enqueue/retry."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import SnapshotSeriesJobKind
from app.modules.portfolio_history.jobs.models import (
    PortfolioHistoryJobCheckpoint,
    PortfolioHistoryJobPayload,
    PortfolioHistoryJobProgress,
    canonical_history_job_idempotency_key,
    validate_history_payload,
)
from app.modules.portfolio_history.jobs.repository import (
    EnqueuedPortfolioHistoryJob,
    PortfolioHistoryJobRepository,
)


class PortfolioHistoryJobAuthorizationError(RuntimeError):
    pass


class PortfolioHistoryJobStateError(RuntimeError):
    pass


class PortfolioHistoryJobService:
    def __init__(
        self, session: AsyncSession, *, repository: PortfolioHistoryJobRepository | None = None
    ) -> None:
        self.session = session
        self.repository = repository or PortfolioHistoryJobRepository(session)

    async def enqueue(
        self,
        *,
        actor_user_id: str,
        kind: SnapshotSeriesJobKind,
        payload: object,
        max_attempts: int,
        now: datetime,
        requested_by_background_job_id: str | None = None,
    ) -> EnqueuedPortfolioHistoryJob:
        if not actor_user_id or actor_user_id != actor_user_id.strip() or now.tzinfo is not None:
            raise PortfolioHistoryJobAuthorizationError("History job authorization is invalid.")
        if not 1 <= max_attempts <= 20:
            raise PortfolioHistoryJobStateError("History job retry policy is invalid.")
        canonical: PortfolioHistoryJobPayload = validate_history_payload(kind, payload)
        checkpoint = PortfolioHistoryJobCheckpoint().model_dump(mode="json", exclude_none=True)
        progress = PortfolioHistoryJobProgress(
            phase=checkpoint["phase"], completed_units=0, total_units=1
        ).model_dump(mode="json")
        return await self.repository.enqueue(
            user_id=actor_user_id,
            kind=kind,
            idempotency_key=canonical_history_job_idempotency_key(
                user_id=actor_user_id, kind=kind, payload=canonical
            ),
            payload=canonical.model_dump(mode="json", exclude_none=True),
            checkpoint=checkpoint,
            progress=progress,
            max_attempts=max_attempts,
            now=now,
            requested_by_background_job_id=requested_by_background_job_id,
        )

    async def retry_failed(self, *, actor_user_id: str, job_id: str, now: datetime) -> None:
        if not actor_user_id or not job_id or now.tzinfo is not None:
            raise PortfolioHistoryJobAuthorizationError("History job authorization is invalid.")
        if (
            await self.repository.retry_failed(actor_user_id=actor_user_id, job_id=job_id, now=now)
            is None
        ):
            raise PortfolioHistoryJobStateError("History job cannot be retried.")

    async def retry_failed_scheduled_capture(
        self, *, actor_user_id: str, job_id: str, now: datetime
    ) -> None:
        if not actor_user_id or not job_id or now.tzinfo is not None:
            raise PortfolioHistoryJobAuthorizationError("History job authorization is invalid.")
        if (
            await self.repository.retry_failed_scheduled_capture(
                actor_user_id=actor_user_id,
                job_id=job_id,
                now=now,
            )
            is None
        ):
            raise PortfolioHistoryJobStateError("History capture job cannot be retried.")
