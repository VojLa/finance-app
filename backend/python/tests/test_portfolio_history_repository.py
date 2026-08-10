from __future__ import annotations

from datetime import datetime
from typing import Any, cast

import pytest

from app.db.models.snapshots import NetWorthSnapshotModel
from app.modules.jobs.publication_queries import is_history_snapshot_visible
from app.modules.portfolio_history.repository import PortfolioHistoryRepository


class _Result:
    def all(self) -> list[object]:
        return []


class _Session:
    def __init__(self) -> None:
        self.statement: object | None = None

    async def execute(self, statement: object) -> _Result:
        self.statement = statement
        return _Result()


@pytest.mark.asyncio
async def test_import_event_history_query_requires_completed_published_anchor() -> None:
    session = _Session()
    repository = PortfolioHistoryRepository(cast(Any, session))

    assert (
        await repository.load_candidate_points(
            user_id="user-a", currency="CZK", start=None, end=datetime(2034, 2, 3, 10, 15)
        )
        == ()
    )

    assert session.statement is not None
    sql = str(session.statement)
    assert "EXISTS" in sql
    assert '"DailySnapshotBaseline"."netWorthSnapshotId"' in sql
    assert '"ImportJobPublicationTarget"."publishedAt" IS NOT NULL' in sql
    assert '"BackgroundJob".status = :status_1' in sql


def test_history_snapshot_expression_is_correlated_and_read_only() -> None:
    expression = is_history_snapshot_visible(
        snapshot_id=NetWorthSnapshotModel.id,
        user_id=NetWorthSnapshotModel.user_id,
        timestamp=NetWorthSnapshotModel.timestamp,
        source=NetWorthSnapshotModel.source,
    )

    sql = str(expression)
    assert "EXISTS" in sql
    assert '"DailySnapshotBaseline"."netWorthSnapshotId"' in sql
    assert '"NetWorthSnapshot".id' in sql
    assert '"ImportJobPublicationTarget"."publishedAt" IS NOT NULL' in sql
    assert '"BackgroundJob".status = :status_1' in sql
