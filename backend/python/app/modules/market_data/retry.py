"""Bounded immediate retries; durable provider cooldown belongs to health storage."""

import asyncio
import random
from collections.abc import Awaitable, Callable

from app.db.models.enums import MarketDataFailureReason
from app.modules.market_data.provider_failure import ProviderFailure


async def with_provider_retry[T](
    operation: Callable[[], Awaitable[T]],
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    jitter: Callable[[], float] = random.random,
) -> T:
    """Attempt at most three times; leave rate limits to persisted health cooldown."""
    for attempt in range(3):
        try:
            return await operation()
        except ProviderFailure as exc:
            if (
                not exc.retryable
                or exc.reason is MarketDataFailureReason.rate_limit
                or attempt == 2
            ):
                raise
            fraction = jitter()
            if not 0 <= fraction <= 1:
                raise ValueError("jitter must be between zero and one") from None
            await sleep(min(2**attempt, 8) * (1 + 0.25 * fraction))
    raise AssertionError("unreachable")
