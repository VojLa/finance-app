"""Repeated clean PostgreSQL acceptance for the current version 0.1 main scenario."""

from __future__ import annotations

import importlib
import os
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

dashboard_integration = cast(
    Any,
    importlib.import_module("tests.test_portfolio_dashboard_snapshot_api_integration"),
)
r8_clean_main = cast(
    Any,
    importlib.import_module("tests.test_version_0_1_clean_main_scenario_integration"),
)

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="The dedicated R9 PostgreSQL DATABASE_URL is required.",
)


def test_r9_repeats_the_clean_three_source_main_scenario(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run the production-boundary R8 proof again on a freshly bootstrapped database."""

    r8_clean_main.test_clean_main_scenario_reaches_exact_browser_owned_read_models_and_replays(
        tmp_path,
        monkeypatch,
    )


@pytest.mark.asyncio
async def test_r9_repeating_dashboard_ratio_is_exact_and_totals_one_hundred() -> None:
    prefix = dashboard_integration._prefix("r9-repeating-ratio")
    await dashboard_integration._cleanup(prefix)
    try:
        user_id, accounts, snapshots = await dashboard_integration._seed_pair(prefix)
        await dashboard_integration._set_single_position(
            f"{prefix}-a",
            snapshot_id=snapshots[0],
            value="1",
            cost="1",
        )
        await dashboard_integration._set_single_position(
            f"{prefix}-b",
            snapshot_id=snapshots[1],
            value="2",
            cost="2",
        )

        response = dashboard_integration._call(
            dashboard_integration.DASHBOARD_PATH,
            user_id,
            dashboard_integration._body(accounts),
        )

        assert response.status_code == 200
        percentages = tuple(
            Decimal(position["allocationPct"]) for position in response.json()["topPositions"]
        )
        assert percentages == (Decimal("66.6667"), Decimal("33.3333"))
        assert sum(percentages, Decimal()) == Decimal("100.0000")
    finally:
        await dashboard_integration._cleanup(prefix)
