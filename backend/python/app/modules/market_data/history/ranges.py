"""Exact UTC-naive time windows and bounded chunks for history providers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.modules.market_data.history.models import HistoricalMarketEvidenceStateError

_MILLISECOND = timedelta(milliseconds=1)
_MAX_CHUNKS = 1_024


def _fail() -> HistoricalMarketEvidenceStateError:
    return HistoricalMarketEvidenceStateError()


def _timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or value.microsecond % 1_000 != 0
    ):
        raise _fail()
    return value


def _positive_millisecond_timedelta(value: object) -> timedelta:
    if (
        not isinstance(value, timedelta)
        or value <= timedelta(0)
        or value % _MILLISECOND != timedelta(0)
    ):
        raise _fail()
    return value


@dataclass(frozen=True, slots=True)
class HistoricalTimeRange:
    """Half-open naive-UTC range: ``start <= timestamp < end``."""

    start: datetime
    end: datetime


def build_historical_window(
    requested_at: tuple[datetime, ...],
    *,
    lookback: timedelta,
) -> HistoricalTimeRange:
    if not isinstance(requested_at, tuple) or not requested_at:
        raise _fail()
    canonical_lookback = _positive_millisecond_timedelta(lookback)
    requested = tuple(_timestamp(item) for item in requested_at)
    if requested != tuple(sorted(requested)) or len(set(requested)) != len(requested):
        raise _fail()
    return HistoricalTimeRange(
        start=requested[0] - canonical_lookback,
        end=requested[-1] + _MILLISECOND,
    )


def chunk_historical_window(
    value: HistoricalTimeRange,
    *,
    maximum_span: timedelta,
) -> tuple[HistoricalTimeRange, ...]:
    if not isinstance(value, HistoricalTimeRange):
        raise _fail()
    canonical_maximum_span = _positive_millisecond_timedelta(maximum_span)
    start = _timestamp(value.start)
    end = _timestamp(value.end)
    if start >= end:
        raise _fail()
    chunks: list[HistoricalTimeRange] = []
    cursor = start
    while cursor < end:
        if len(chunks) >= _MAX_CHUNKS:
            raise _fail()
        next_end = min(cursor + canonical_maximum_span, end)
        chunks.append(HistoricalTimeRange(start=cursor, end=next_end))
        cursor = next_end
    return tuple(chunks)


__all__ = ["HistoricalTimeRange", "build_historical_window", "chunk_historical_window"]
