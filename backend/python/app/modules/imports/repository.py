from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.imports import ImportBatchModel, ImportLogModel


class ImportBatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_account(self, account_id: str) -> list[ImportBatchModel]:
        result = await self.session.scalars(
            select(ImportBatchModel)
            .where(ImportBatchModel.account_id == account_id)
            .order_by(ImportBatchModel.created_at.desc(), ImportBatchModel.id.asc())
        )
        return list(result.all())

    async def get_for_account(
        self,
        *,
        account_id: str,
        batch_id: str,
    ) -> ImportBatchModel | None:
        return await self.session.scalar(
            select(ImportBatchModel).where(
                ImportBatchModel.id == batch_id,
                ImportBatchModel.account_id == account_id,
            )
        )

    async def get_by_checksum(
        self,
        *,
        user_id: str,
        account_id: str,
        checksum: str,
    ) -> ImportBatchModel | None:
        return await self.session.scalar(
            select(ImportBatchModel).where(
                ImportBatchModel.user_id == user_id,
                ImportBatchModel.account_id == account_id,
                ImportBatchModel.checksum == checksum,
            )
        )

    def add_batch(self, batch: ImportBatchModel) -> None:
        self.session.add(batch)

    def add_log(self, log: ImportLogModel) -> None:
        self.session.add(log)
