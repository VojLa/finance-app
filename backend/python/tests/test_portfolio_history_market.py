from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.modules.market_data.history.models import (
    HistoricalProviderRangeCapability,
    HistoricalTimeSeriesInterval,
)
from app.modules.portfolio_history.builder.market import (
    HistoricalMarketLookbackUnavailableError,
    _require_available,
)


def test_declared_provider_lookback_fails_permanently_outside_available_range() -> None:
    provider = SimpleNamespace(
        capability=SimpleNamespace(
            ranges=(
                HistoricalProviderRangeCapability(
                    requested_interval=HistoricalTimeSeriesInterval.thirty_minutes,
                    native_observation_interval=timedelta(minutes=30),
                    maximum_request_span=timedelta(days=7),
                    maximum_age=timedelta(days=60),
                ),
            )
        )
    )
    as_of = datetime(2026, 9, 28, 12)

    with pytest.raises(HistoricalMarketLookbackUnavailableError):
        _require_available(
            provider,
            HistoricalTimeSeriesInterval.thirty_minutes,
            at=as_of - timedelta(days=61),
            as_of=as_of,
        )
    _require_available(
        provider,
        HistoricalTimeSeriesInterval.thirty_minutes,
        at=as_of - timedelta(days=59),
        as_of=as_of,
    )
