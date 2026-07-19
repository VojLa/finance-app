from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.modules.accounts.models import AccountResponse


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_accessible(self, user_id: str) -> list[AccountResponse]:
        statement = (
            select(AccountModel, AccountMemberModel.role, AccountMemberModel.relation_type)
            .join(AccountMemberModel, AccountMemberModel.account_id == AccountModel.id)
            .where(
                AccountMemberModel.user_id == user_id,
                AccountModel.is_archived.is_(False),
            )
            .order_by(AccountModel.created_at.asc(), AccountModel.id.asc())
        )
        rows = (await self.session.execute(statement)).all()
        return [
            AccountResponse(
                id=account.id,
                name=account.name,
                type=account.type,
                currency=account.currency,
                color=account.color,
                notes=account.notes,
                is_archived=account.is_archived,
                role=role,
                relation_type=relation_type,
                created_at=account.created_at,
                updated_at=account.updated_at,
            )
            for account, role, relation_type in rows
        ]

    async def get_with_membership(self, *, account_id: str, user_id: str) -> AccountResponse | None:
        statement = (
            select(AccountModel, AccountMemberModel.role, AccountMemberModel.relation_type)
            .join(AccountMemberModel, AccountMemberModel.account_id == AccountModel.id)
            .where(
                AccountModel.id == account_id,
                AccountMemberModel.user_id == user_id,
                AccountModel.is_archived.is_(False),
            )
        )
        row = (await self.session.execute(statement)).one_or_none()
        if row is None:
            return None
        account, role, relation_type = row
        return AccountResponse(
            id=account.id,
            name=account.name,
            type=account.type,
            currency=account.currency,
            color=account.color,
            notes=account.notes,
            is_archived=account.is_archived,
            role=role,
            relation_type=relation_type,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )

    def add_account(self, account: AccountModel) -> None:
        self.session.add(account)

    def add_membership(self, membership: AccountMemberModel) -> None:
        self.session.add(membership)

    async def get_account_for_update(self, account_id: str) -> AccountModel | None:
        return await self.session.scalar(
            select(AccountModel).where(
                AccountModel.id == account_id,
                AccountModel.is_archived.is_(False),
            )
        )

    async def get_account_for_lifecycle(self, account_id: str) -> AccountModel | None:
        return await self.session.scalar(select(AccountModel).where(AccountModel.id == account_id))
