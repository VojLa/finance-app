"""Pure retained-lattice planning for one immutable history generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.modules.market_data.source_policy import (
    CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    MarketEvidenceSourcePolicy,
    validate_market_evidence_source_policy,
)
from app.modules.portfolio_history.lattice import (
    CORE_HISTORY_RESOLUTIONS,
    HistoryBucket,
    HistoryPublicRange,
    HistoryResolution,
    history_buckets_between,
    resolution_level,
    resolution_minutes,
    retention_cutoff,
    select_history_range,
)

_MILLISECOND = timedelta(milliseconds=1)
_MINUTE = timedelta(minutes=1)
_MAX_LAYER_BUCKETS = 4_096
_SUBDAILY_RESOLUTIONS = frozenset(
    {
        HistoryResolution.minutes_30,
        HistoryResolution.hours_2,
        HistoryResolution.hours_6,
        HistoryResolution.hours_12,
    }
)


class HistoryGenerationBuildError(RuntimeError):
    """The frozen input cannot produce one bounded generation build."""

    def __init__(self) -> None:
        super().__init__("Portfolio history generation cannot be built.")


@dataclass(frozen=True, slots=True)
class PlannedHistoryBucket:
    level: int
    resolution: HistoryResolution
    resolution_minutes: int
    bucket: HistoryBucket
    representative_at: datetime
    rebuild_required: bool


@dataclass(frozen=True, slots=True)
class RebuildGenerationPlan:
    first_event_at: datetime
    dirty_from: datetime
    covered_through: datetime
    buckets: tuple[PlannedHistoryBucket, ...]
    replay_timestamps: tuple[datetime, ...]
    market_timestamps: tuple[datetime, ...]
    subdaily_market_timestamps: tuple[datetime, ...]

    @property
    def prefix_buckets(self) -> tuple[PlannedHistoryBucket, ...]:
        return tuple(item for item in self.buckets if not item.rebuild_required)

    @property
    def suffix_buckets(self) -> tuple[PlannedHistoryBucket, ...]:
        return tuple(item for item in self.buckets if item.rebuild_required)


def _timestamp(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is not None or value.microsecond % 1_000:
        raise HistoryGenerationBuildError()
    return value


def _representative(
    bucket: HistoryBucket, through: datetime, *, first_event_at: datetime
) -> datetime:
    if bucket.start <= first_event_at < bucket.end:
        return first_event_at
    candidate = min(bucket.end - _MINUTE, through)
    if candidate < bucket.start:
        candidate = bucket.start
    candidate = candidate.replace(second=0, microsecond=0)
    if not bucket.start <= candidate < bucket.end:
        raise HistoryGenerationBuildError()
    return candidate


def build_rebuild_generation_plan(
    *,
    first_event_at: datetime,
    dirty_from: datetime,
    covered_through: datetime,
    source_policy: MarketEvidenceSourcePolicy = CANONICAL_MARKET_EVIDENCE_SOURCE_POLICY,
    subdaily_available_since: datetime | None = None,
) -> RebuildGenerationPlan:
    """Plan retained layers and mark the exact parent-prefix/dirty-suffix boundary."""

    first = _timestamp(first_event_at)
    dirty = _timestamp(dirty_from)
    through = _timestamp(covered_through)
    policy = validate_market_evidence_source_policy(source_policy)
    available_since = (
        _timestamp(subdaily_available_since) if subdaily_available_since is not None else None
    )
    if first > through or through.second or through.microsecond:
        raise HistoryGenerationBuildError()

    resolutions = list(CORE_HISTORY_RESOLUTIONS)
    all_selection = select_history_range(
        HistoryPublicRange.all,
        through=through,
        first_event_at=first,
    )
    if all_selection.resolution not in resolutions:
        resolutions.append(all_selection.resolution)

    planned: list[PlannedHistoryBucket] = []
    for resolution in resolutions:
        cutoff = retention_cutoff(resolution, through=through)
        # Yahoo listed-price and direct-FX lookback share a truthful 50-day
        # subdaily fence. Older local-free history stays covered by the daily
        # layer; it must never be represented as repeated intraday closes.
        if policy.mode == "local_free" and resolution in {
            HistoryResolution.hours_6,
            HistoryResolution.hours_12,
        }:
            source_cutoff = through - timedelta(days=50)
            cutoff = source_cutoff if cutoff is None else max(cutoff, source_cutoff)
        if resolution in _SUBDAILY_RESOLUTIONS and available_since is not None:
            cutoff = available_since if cutoff is None else max(cutoff, available_since)
        start = first if cutoff is None else max(first, cutoff)
        if start > through:
            continue
        retained_buckets = history_buckets_between(
            start,
            through + _MILLISECOND,
            resolution,
            limit=_MAX_LAYER_BUCKETS,
        )
        # A first-event boundary outside this layer's retention is not a
        # historical intraday observation. The coarser retained layer owns
        # that span; never add a synthetic old close to the market request.
        for bucket in retained_buckets:
            representative_at = _representative(bucket, through, first_event_at=first)
            if cutoff is not None and representative_at < cutoff:
                continue
            planned.append(
                PlannedHistoryBucket(
                    level=resolution_level(resolution),
                    resolution=resolution,
                    resolution_minutes=resolution_minutes(resolution),
                    bucket=bucket,
                    representative_at=representative_at,
                    rebuild_required=bucket.end > dirty,
                )
            )
    canonical = tuple(sorted(planned, key=lambda item: (item.level, item.bucket.start)))
    if not canonical or len({(item.level, item.bucket.start) for item in canonical}) != len(
        canonical
    ):
        raise HistoryGenerationBuildError()
    # The exact covered-through replay state owns the durable checkpoints even
    # when the first-event boundary replaces this bucket's ordinary close.
    replay_timestamps = tuple(
        sorted({through, *(item.representative_at for item in canonical if item.rebuild_required)})
    )
    market_timestamps = tuple(
        sorted({item.representative_at for item in canonical if item.rebuild_required})
    )
    subdaily_market_timestamps = tuple(
        sorted(
            {
                item.representative_at
                for item in canonical
                if item.rebuild_required and item.resolution in _SUBDAILY_RESOLUTIONS
            }
        )
    )
    if not market_timestamps:
        raise HistoryGenerationBuildError()
    return RebuildGenerationPlan(
        first_event_at=first,
        dirty_from=dirty,
        covered_through=through,
        buckets=canonical,
        replay_timestamps=replay_timestamps,
        market_timestamps=market_timestamps,
        subdaily_market_timestamps=subdaily_market_timestamps,
    )


__all__ = [
    "HistoryGenerationBuildError",
    "PlannedHistoryBucket",
    "RebuildGenerationPlan",
    "build_rebuild_generation_plan",
]
