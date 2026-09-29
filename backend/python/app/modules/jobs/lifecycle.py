from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.db.models.enums import BackgroundJobStatus

MAX_AUTOMATIC_ATTEMPTS = 5
MAX_MANUAL_RETRIES = 20
RETRY_BASE_SECONDS = 5
RETRY_MAX_SECONDS = 300


class BackgroundJobLifecycleError(RuntimeError):
    """The persisted job state cannot make the requested transition."""


@dataclass(frozen=True, slots=True)
class LeaseIdentity:
    job_id: str
    owner: str
    version: int

    def __post_init__(self) -> None:
        if (
            not self.job_id
            or self.job_id != self.job_id.strip()
            or not self.owner
            or self.owner != self.owner.strip()
            or self.version <= 0
        ):
            raise BackgroundJobLifecycleError("The lease identity is invalid.")


def automatic_retry_at(*, now: datetime, attempt_count: int) -> datetime:
    if now.tzinfo is not None or not 1 <= attempt_count <= MAX_AUTOMATIC_ATTEMPTS:
        raise BackgroundJobLifecycleError("The retry boundary is invalid.")
    delay = min(RETRY_BASE_SECONDS * (2 ** (attempt_count - 1)), RETRY_MAX_SECONDS)
    return now + timedelta(seconds=delay)


def require_transition(
    current: BackgroundJobStatus,
    target: BackgroundJobStatus,
    *,
    manual_retry: bool = False,
) -> None:
    allowed = {
        BackgroundJobStatus.queued: {BackgroundJobStatus.running},
        BackgroundJobStatus.running: {
            BackgroundJobStatus.retry_wait,
            BackgroundJobStatus.completed,
            BackgroundJobStatus.failed,
        },
        BackgroundJobStatus.retry_wait: {BackgroundJobStatus.running},
        BackgroundJobStatus.completed: set(),
        BackgroundJobStatus.failed: ({BackgroundJobStatus.queued} if manual_retry else set()),
    }
    if target not in allowed[current]:
        raise BackgroundJobLifecycleError(
            f"Invalid background job transition: {current.value} -> {target.value}."
        )
