"""Explicit read-only SQL boundary for persisted net-worth evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import SnapshotGranularity
from app.db.models.snapshots import AccountSnapshotModel
from app.db.models.users import UserModel


@dataclass(frozen=True, slots=True)
class PersistedAccountAccess:
    account: AccountModel
    membership: AccountMemberModel


class NetWorthEvidenceRepository:
    """Repository methods perform no writes and own no transaction boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_transaction_isolation(self) -> str | None:
        return await self.session.scalar(text("SHOW transaction_isolation"))

    async def load_user(self, user_id: str) -> UserModel | None:
        return await self.session.scalar(
            select(UserModel).where(UserModel.id == user_id).execution_options(autoflush=False)
        )

    async def load_account_accesses(
        self,
        user_id: str,
    ) -> tuple[PersistedAccountAccess, ...]:
        result = await self.session.execute(
            select(AccountModel, AccountMemberModel)
            .join(
                AccountMemberModel,
                AccountMemberModel.account_id == AccountModel.id,
            )
            .where(AccountMemberModel.user_id == user_id)
            .order_by(AccountModel.id, AccountMemberModel.id)
            .execution_options(autoflush=False)
        )
        return tuple(PersistedAccountAccess(account, membership) for account, membership in result)

    async def load_exact_snapshots(
        self,
        *,
        account_ids: tuple[str, ...],
        timestamp: datetime,
        granularity: SnapshotGranularity,
        currency: str,
    ) -> tuple[AccountSnapshotModel, ...]:
        if not account_ids:
            return ()
        result = await self.session.scalars(
            select(AccountSnapshotModel)
            .where(
                AccountSnapshotModel.account_id.in_(account_ids),
                AccountSnapshotModel.timestamp == timestamp,
                AccountSnapshotModel.granularity == granularity,
                AccountSnapshotModel.currency == currency,
            )
            .order_by(AccountSnapshotModel.account_id, AccountSnapshotModel.id)
            .execution_options(autoflush=False)
        )
        return tuple(result)
