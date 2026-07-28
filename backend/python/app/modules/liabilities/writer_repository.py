"""Explicit PostgreSQL lock and persistence boundary for liability balances."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.enums import LiabilityBalanceSource
from app.db.models.liabilities import LiabilityBalanceModel


def advisory_lock_id(scope: str) -> int:
    return int.from_bytes(sha256(scope.encode()).digest()[:8], "big", signed=True)


def balance_identity_lock_scope(
    *,
    account_id: str,
    effective_at: datetime,
    source: LiabilityBalanceSource,
) -> str:
    return "\0".join(
        (
            "liabilities:balance",
            account_id,
            effective_at.isoformat(timespec="milliseconds"),
            source.value,
        )
    )


def external_identity_lock_scope(
    *,
    account_id: str,
    source: LiabilityBalanceSource,
    external_id: str,
) -> str:
    return "\0".join(("liabilities:external", account_id, source.value, external_id))


def identity_lock_ids(
    *,
    account_id: str,
    effective_at: datetime,
    source: LiabilityBalanceSource,
    external_id: str | None,
) -> tuple[int, ...]:
    scopes = {
        balance_identity_lock_scope(
            account_id=account_id,
            effective_at=effective_at,
            source=source,
        )
    }
    if external_id is not None:
        scopes.add(
            external_identity_lock_scope(
                account_id=account_id,
                source=source,
                external_id=external_id,
            )
        )
    return tuple(sorted({advisory_lock_id(scope) for scope in scopes}))


class LiabilityBalanceWriterRepository:
    """Repository helpers assume the writer's active outer transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_account_for_share(self, account_id: str) -> AccountModel | None:
        return await self.session.scalar(
            select(AccountModel)
            .where(AccountModel.id == account_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )

    async def acquire_identity_locks(self, lock_ids: tuple[int, ...]) -> None:
        for lock_id in lock_ids:
            await self.session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    async def load_by_timestamp_identity(
        self,
        *,
        account_id: str,
        effective_at: datetime,
        source: LiabilityBalanceSource,
    ) -> LiabilityBalanceModel | None:
        return await self.session.scalar(
            select(LiabilityBalanceModel)
            .where(
                LiabilityBalanceModel.account_id == account_id,
                LiabilityBalanceModel.effective_at == effective_at,
                LiabilityBalanceModel.source == source,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_by_external_identity(
        self,
        *,
        account_id: str,
        source: LiabilityBalanceSource,
        external_id: str,
    ) -> LiabilityBalanceModel | None:
        return await self.session.scalar(
            select(LiabilityBalanceModel)
            .where(
                LiabilityBalanceModel.account_id == account_id,
                LiabilityBalanceModel.source == source,
                LiabilityBalanceModel.external_id == external_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_by_id(self, balance_id: str) -> LiabilityBalanceModel | None:
        return await self.session.scalar(
            select(LiabilityBalanceModel)
            .where(LiabilityBalanceModel.id == balance_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def add(self, balance: LiabilityBalanceModel) -> None:
        self.session.add(balance)

    async def flush(self) -> None:
        await self.session.flush()

    async def reload(self, balance_id: str) -> LiabilityBalanceModel | None:
        return await self.session.scalar(
            select(LiabilityBalanceModel)
            .where(LiabilityBalanceModel.id == balance_id)
            .execution_options(populate_existing=True)
        )
