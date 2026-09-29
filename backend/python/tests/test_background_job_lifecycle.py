from datetime import datetime, timedelta

import pytest

from app.db.models.enums import BackgroundJobStatus
from app.modules.jobs.lifecycle import (
    BackgroundJobLifecycleError,
    LeaseIdentity,
    automatic_retry_at,
    require_transition,
)


def test_lifecycle_allows_only_worker_and_explicit_manual_retry_transitions() -> None:
    require_transition(BackgroundJobStatus.queued, BackgroundJobStatus.running)
    require_transition(BackgroundJobStatus.running, BackgroundJobStatus.retry_wait)
    require_transition(BackgroundJobStatus.retry_wait, BackgroundJobStatus.running)
    require_transition(BackgroundJobStatus.running, BackgroundJobStatus.completed)
    require_transition(BackgroundJobStatus.running, BackgroundJobStatus.failed)
    require_transition(
        BackgroundJobStatus.failed,
        BackgroundJobStatus.queued,
        manual_retry=True,
    )

    for current, target in (
        (BackgroundJobStatus.queued, BackgroundJobStatus.completed),
        (BackgroundJobStatus.retry_wait, BackgroundJobStatus.completed),
        (BackgroundJobStatus.completed, BackgroundJobStatus.queued),
        (BackgroundJobStatus.failed, BackgroundJobStatus.queued),
    ):
        with pytest.raises(BackgroundJobLifecycleError):
            require_transition(current, target)


def test_retry_backoff_is_deterministic_and_bounded_by_attempt_policy() -> None:
    now = datetime(2030, 1, 1)
    assert automatic_retry_at(now=now, attempt_count=1) == now + timedelta(seconds=5)
    assert automatic_retry_at(now=now, attempt_count=5) == now + timedelta(seconds=80)
    for invalid in (0, 6):
        with pytest.raises(BackgroundJobLifecycleError):
            automatic_retry_at(now=now, attempt_count=invalid)


@pytest.mark.parametrize(
    ("job_id", "owner", "version"),
    (("", "worker", 1), ("job", " worker", 1), ("job", "worker", 0)),
)
def test_lease_identity_rejects_unfenced_or_noncanonical_values(
    job_id: str, owner: str, version: int
) -> None:
    assert LeaseIdentity(job_id="job-1", owner="worker-1", version=2).version == 2
    with pytest.raises(BackgroundJobLifecycleError):
        LeaseIdentity(job_id=job_id, owner=owner, version=version)
