"""Small cooperative scheduling primitive for CPU-bound import row loops."""

from __future__ import annotations

import asyncio

ROW_YIELD_INTERVAL = 128


async def yield_after_rows(processed: int) -> None:
    """Give the event loop a turn at bounded intervals without changing transactions."""

    if processed > 0 and processed % ROW_YIELD_INTERVAL == 0:
        await asyncio.sleep(0)
