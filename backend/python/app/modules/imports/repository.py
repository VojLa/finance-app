from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.imports import ImportBatchModel, ImportLogModel, ImportRowModel


class ImportBatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_account(self, account_id: str) -> list[ImportBatchModel]:
        result = await self.session.scalars(
            select(ImportBatchModel)
            .where(ImportBatchModel.account_id == account_id)
            .order_by(ImportBatchModel.created_at.desc(), ImportBatchModel.id.desc())
        )
        return list(result.all())

    async def get_for_account(
        self,
        *,
        account_id: str,
        batch_id: str,
        for_update: bool = False,
    ) -> ImportBatchModel | None:
        statement = select(ImportBatchModel).where(
            ImportBatchModel.id == batch_id,
            ImportBatchModel.account_id == account_id,
        )
        if for_update:
            statement = statement.with_for_update()
        return await self.session.scalar(statement)

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

    async def count_rows(self, batch_id: str) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(ImportRowModel)
                .where(ImportRowModel.import_batch_id == batch_id)
            )
            or 0
        )

    async def delete_rows(self, batch_id: str) -> None:
        await self.session.execute(
            delete(ImportRowModel).where(ImportRowModel.import_batch_id == batch_id)
        )

    def add_batch(self, batch: ImportBatchModel) -> None:
        self.session.add(batch)

    def add_row(self, row: ImportRowModel) -> None:
        self.session.add(row)

    def add_log(self, log: ImportLogModel) -> None:
        self.session.add(log)
