from datetime import UTC, datetime, timedelta

import pytest

from app.db.models.enums import MarketDataFailureReason as Reason
from app.modules.market_data.provider_failure import ProviderFailure, failure_for_status
from app.modules.market_data.retry import with_provider_retry


@pytest.mark.asyncio
async def test_bounded_exponential_jitter() -> None:
    attempts = 0
    delays: list[float] = []

    async def operation() -> None:
        nonlocal attempts
        attempts += 1
        raise ProviderFailure(Reason.timeout)

    async def sleep(delay: float) -> None:
        delays.append(delay)

    with pytest.raises(ProviderFailure, match="Market evidence is unavailable"):
        await with_provider_retry(operation, sleep=sleep, jitter=lambda: 1.0)
    assert attempts == 3
    assert delays == [1.25, 2.5]


@pytest.mark.asyncio
async def test_permanent_and_rate_limit_do_not_retry() -> None:
    now = datetime(2026, 9, 30, tzinfo=UTC)
    for failure in (
        ProviderFailure(Reason.currency_conflict),
        ProviderFailure(Reason.rate_limit),
        ProviderFailure(Reason.rate_limit, retry_after=now + timedelta(minutes=2)),
    ):
        calls = 0

        async def operation(failure: ProviderFailure = failure) -> None:
            nonlocal calls
            calls += 1
            raise failure

        with pytest.raises(ProviderFailure) as caught:
            await with_provider_retry(operation)
        assert caught.value is failure
        assert calls == 1


def test_status_classification_is_safe() -> None:
    for status, reason in (
        (408, Reason.timeout),
        (429, Reason.rate_limit),
        (500, Reason.server_error),
        (504, Reason.timeout),
        (404, Reason.unknown_symbol),
        (401, Reason.provider_identity_conflict),
    ):
        failure = failure_for_status(status)
        assert failure.reason is reason
        assert str(failure) == "Market evidence is unavailable."
