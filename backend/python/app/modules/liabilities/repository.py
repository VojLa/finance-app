"""Explicit read-only SQL boundary for liability balance observations."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.liabilities import LiabilityBalanceModel


class LiabilityBalanceEvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_account(self, account_id: str) -> AccountModel | None:
        return await self.session.get(AccountModel, account_id)

    async def load_eligible_balances(
        self,
        account_id: str,
        *,
        through: datetime,
    ) -> tuple[LiabilityBalanceModel, ...]:
        rows = await self.session.scalars(
            select(LiabilityBalanceModel)
            .where(
                LiabilityBalanceModel.account_id == account_id,
                LiabilityBalanceModel.effective_at <= through,
            )
            .order_by(
                LiabilityBalanceModel.effective_at.desc(),
                LiabilityBalanceModel.source,
                LiabilityBalanceModel.id,
            )
        )
        return tuple(rows.all())
