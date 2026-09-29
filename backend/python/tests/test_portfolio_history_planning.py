from datetime import datetime, timedelta

from app.modules.portfolio_history.builder.planning import build_rebuild_generation_plan
from app.modules.portfolio_history.lattice import HistoryResolution


def test_old_first_event_uses_retained_coarser_layer_without_old_intraday_boundary() -> None:
    through = datetime(2026, 9, 28, 12)
    first = through - timedelta(days=100)
    available_since = through - timedelta(days=2)

    plan = build_rebuild_generation_plan(
        first_event_at=first,
        dirty_from=first,
        covered_through=through,
        subdaily_available_since=available_since,
    )

    subdaily = {
        HistoryResolution.minutes_30,
        HistoryResolution.hours_2,
        HistoryResolution.hours_6,
        HistoryResolution.hours_12,
    }
    assert all(
        bucket.representative_at >= available_since
        for bucket in plan.buckets
        if bucket.resolution in subdaily
    )
    assert any(
        bucket.bucket.start <= first < bucket.bucket.end
        for bucket in plan.buckets
        if bucket.resolution not in subdaily
    )


def test_dirty_suffix_plan_does_not_replay_unchanged_prefix() -> None:
    through = datetime(2026, 9, 28, 12)
    plan = build_rebuild_generation_plan(
        first_event_at=through - timedelta(days=2),
        dirty_from=through - timedelta(hours=1),
        covered_through=through,
    )

    assert plan.prefix_buckets
    assert plan.suffix_buckets
    assert plan.replay_timestamps == tuple(
        sorted({through, *(item.representative_at for item in plan.suffix_buckets)})
    )
    prefix_only = (
        {item.representative_at for item in plan.prefix_buckets}
        - {item.representative_at for item in plan.suffix_buckets}
        - {through}
    )
    assert prefix_only.isdisjoint(plan.replay_timestamps)
