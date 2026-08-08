from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.canonical_lineage import (
    AccountCanonicalChangeModel,
    AccountCanonicalStateModel,
)


class CanonicalStateRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_state(self, account_id: str) -> AccountCanonicalStateModel | None:
        return await self.session.scalar(
            select(AccountCanonicalStateModel)
            .where(AccountCanonicalStateModel.account_id == account_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_change_by_entity(
        self, *, kind: str, entity_id: str
    ) -> AccountCanonicalChangeModel | None:
        return await self.session.scalar(
            select(AccountCanonicalChangeModel)
            .where(
                AccountCanonicalChangeModel.kind == kind,
                AccountCanonicalChangeModel.entity_id == entity_id,
            )
            .execution_options(populate_existing=True)
        )

    async def load_change_by_revision(
        self, *, account_id: str, revision: int
    ) -> AccountCanonicalChangeModel | None:
        return await self.session.scalar(
            select(AccountCanonicalChangeModel)
            .where(
                AccountCanonicalChangeModel.account_id == account_id,
                AccountCanonicalChangeModel.revision == revision,
            )
            .execution_options(populate_existing=True)
        )

    def add_change(self, change: AccountCanonicalChangeModel) -> None:
        self.session.add(change)

    async def flush(self) -> None:
        await self.session.flush()
