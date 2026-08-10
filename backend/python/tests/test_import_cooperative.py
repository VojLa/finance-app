from unittest.mock import AsyncMock, call

import pytest

from app.modules.imports.cooperative import ROW_YIELD_INTERVAL, yield_after_rows


async def test_row_loop_yields_at_a_bounded_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("app.modules.imports.cooperative.asyncio.sleep", sleep)

    for processed in range(1, ROW_YIELD_INTERVAL * 2 + 1):
        await yield_after_rows(processed)

    assert sleep.await_args_list == [call(0), call(0)]
