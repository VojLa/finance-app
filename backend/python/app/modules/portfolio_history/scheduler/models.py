"""Non-financial scheduler decisions returned to the orchestration boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class PortfolioHistoryScheduleAction(StrEnum):
    capture_enqueued = "capture_enqueued"
    capture_retry_enqueued = "capture_retry_enqueued"
    capture_completed = "capture_completed"
    rebuild_enqueued = "rebuild_enqueued"
    rebuild_boundary_required = "rebuild_boundary_required"
    deferred_dirty = "deferred_dirty"
    deferred_building = "deferred_building"
    deferred_active_job = "deferred_active_job"
    deferred_failed_job = "deferred_failed_job"
    invalid_schedule = "invalid_schedule"


@dataclass(frozen=True, slots=True)
class PortfolioHistoryScheduleDecision:
    user_id: str
    action: PortfolioHistoryScheduleAction
    capture_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PortfolioHistorySchedulerTickResult:
    lock_acquired: bool
    decisions: tuple[PortfolioHistoryScheduleDecision, ...]


__all__ = [
    "PortfolioHistoryScheduleAction",
    "PortfolioHistoryScheduleDecision",
    "PortfolioHistorySchedulerTickResult",
]
