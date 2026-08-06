"""Read-only PostgreSQL boundary for NetWorthSnapshot history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.snapshots import NetWorthSnapshotModel
from app.db.models.users import UserModel
from app.modules.portfolio_history.models import PersistedPortfolioHistoryPoint


@dataclass(frozen=True, slots=True)
class PersistedPortfolioHistoryUser:
    user_id: object
    base_currency: object


class PortfolioHistoryRepository:
    """Load only the persisted user identity and NetWorthSnapshot point fields."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_user(self, user_id: str) -> PersistedPortfolioHistoryUser | None:
        row = (
            await self.session.execute(
                select(UserModel.id, UserModel.base_currency)
                .where(UserModel.id == user_id)
                .execution_options(autoflush=False)
            )
        ).one_or_none()
        if row is None:
            return None
        return PersistedPortfolioHistoryUser(user_id=row.id, base_currency=row.base_currency)

    async def load_candidate_points(
        self,
        *,
        user_id: str,
        currency: str,
        start: datetime | None,
        end: datetime,
    ) -> tuple[PersistedPortfolioHistoryPoint, ...]:
        statement = select(
            NetWorthSnapshotModel.id,
            NetWorthSnapshotModel.user_id,
            NetWorthSnapshotModel.timestamp,
            NetWorthSnapshotModel.granularity,
            NetWorthSnapshotModel.source,
            NetWorthSnapshotModel.currency,
            NetWorthSnapshotModel.cash_value,
            NetWorthSnapshotModel.portfolio_value,
            NetWorthSnapshotModel.liabilities_value,
            NetWorthSnapshotModel.total_net_worth,
            NetWorthSnapshotModel.calculation_version,
        ).where(
            NetWorthSnapshotModel.user_id == user_id,
            NetWorthSnapshotModel.currency == currency,
            NetWorthSnapshotModel.timestamp <= end,
        )
        if start is not None:
            statement = statement.where(NetWorthSnapshotModel.timestamp >= start)
        rows = (
            await self.session.execute(
                statement.order_by(
                    NetWorthSnapshotModel.timestamp,
                    NetWorthSnapshotModel.granularity,
                    NetWorthSnapshotModel.id,
                ).execution_options(autoflush=False)
            )
        ).all()
        return tuple(
            PersistedPortfolioHistoryPoint(
                snapshot_id=row.id,
                user_id=row.user_id,
                timestamp=row.timestamp,
                granularity=row.granularity,
                source=row.source,
                currency=row.currency,
                cash_value=row.cash_value,
                portfolio_value=row.portfolio_value,
                liabilities_value=row.liabilities_value,
                total_net_worth=row.total_net_worth,
                calculation_version=row.calculation_version,
            )
            for row in rows
        )
