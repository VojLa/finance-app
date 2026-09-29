"""One explicit H3 dispatch boundary for all durable history job kinds."""

from __future__ import annotations

from app.db.models.enums import SnapshotSeriesJobKind
from app.modules.portfolio_history.jobs.models import PortfolioHistoryJobResult
from app.modules.portfolio_history.jobs.repository import ClaimedPortfolioHistoryJob
from app.modules.portfolio_history.jobs.worker import (
    CheckpointCallback,
    PermanentPortfolioHistoryJobError,
    PortfolioHistoryJobExecutor,
)


class PortfolioHistoryJobDispatchExecutor:
    """Dispatch only by persisted kind; concrete executors validate payloads."""

    def __init__(
        self,
        *,
        rebuild: PortfolioHistoryJobExecutor,
    ) -> None:
        self.rebuild = rebuild

    async def execute(
        self, claimed: ClaimedPortfolioHistoryJob, *, checkpoint: CheckpointCallback
    ) -> PortfolioHistoryJobResult:
        kind = claimed.job.kind
        if kind in {
            SnapshotSeriesJobKind.rebuild,
            SnapshotSeriesJobKind.capture,
        }:
            return await self.rebuild.execute(claimed, checkpoint=checkpoint)
        raise PermanentPortfolioHistoryJobError(
            code="history_job_kind_not_configured",
            message="This history job kind is not configured.",
        )


__all__ = ["PortfolioHistoryJobDispatchExecutor"]
