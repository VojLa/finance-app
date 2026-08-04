"""Read-only PostgreSQL boundary for market-evidence planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel


@dataclass(frozen=True, slots=True)
class PersistedMarketHolding:
    holding: HoldingModel
    listing: AssetListingModel | None
    asset: AssetModel | None
    aliases: tuple[AssetAliasModel, ...]


class MarketEvidenceRequirementsRepository:
    """Repository methods own no transaction, lock, provider call, or write."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_transaction_repeatable_read_only(self) -> None:
        await self.session.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        )

    async def load_user(self, user_id: str) -> UserModel | None:
        return await self.session.get(UserModel, user_id)

    async def load_active_accounts(self, user_id: str) -> tuple[AccountModel, ...]:
        rows = await self.session.scalars(
            select(AccountModel)
            .join(
                AccountMemberModel,
                AccountMemberModel.account_id == AccountModel.id,
            )
            .where(
                AccountMemberModel.user_id == user_id,
                AccountModel.is_archived.is_(False),
                AccountModel.archived_at.is_(None),
            )
            .order_by(AccountModel.id)
        )
        return tuple(rows.all())

    async def load_holdings(
        self,
        account_ids: tuple[str, ...],
    ) -> tuple[PersistedMarketHolding, ...]:
        if not account_ids:
            return ()
        rows = (
            await self.session.execute(
                select(HoldingModel, AssetListingModel, AssetModel)
                .outerjoin(
                    AssetListingModel,
                    AssetListingModel.id == HoldingModel.listing_id,
                )
                .outerjoin(AssetModel, AssetModel.id == HoldingModel.asset_id)
                .where(HoldingModel.account_id.in_(account_ids))
                .order_by(HoldingModel.account_id, HoldingModel.listing_id, HoldingModel.id)
            )
        ).all()
        asset_ids = tuple(sorted({row[2].id for row in rows if isinstance(row[2], AssetModel)}))
        aliases_by_asset: dict[str, list[AssetAliasModel]] = {}
        if asset_ids:
            aliases = await self.session.scalars(
                select(AssetAliasModel)
                .where(AssetAliasModel.asset_id.in_(asset_ids))
                .order_by(
                    AssetAliasModel.asset_id,
                    AssetAliasModel.provider,
                    AssetAliasModel.external_id,
                    AssetAliasModel.id,
                )
            )
            for alias in aliases.all():
                aliases_by_asset.setdefault(alias.asset_id, []).append(alias)
        return tuple(
            PersistedMarketHolding(
                holding=row[0],
                listing=row[1],
                asset=row[2],
                aliases=tuple(aliases_by_asset.get(row[0].asset_id or "", ())),
            )
            for row in rows
        )

    async def load_transactions(
        self,
        account_ids: tuple[str, ...],
        *,
        through: datetime,
    ) -> tuple[TransactionModel, ...]:
        if not account_ids:
            return ()
        rows = await self.session.scalars(
            select(TransactionModel)
            .where(
                TransactionModel.account_id.in_(account_ids),
                TransactionModel.date <= through,
                TransactionModel.archived_at.is_(None),
                TransactionModel.deleted_at.is_(None),
            )
            .order_by(TransactionModel.date, TransactionModel.id)
        )
        return tuple(rows.all())

    async def load_events(
        self,
        account_ids: tuple[str, ...],
        *,
        through: datetime,
    ) -> tuple[InvestmentEventModel, ...]:
        if not account_ids:
            return ()
        rows = await self.session.scalars(
            select(InvestmentEventModel)
            .where(
                InvestmentEventModel.account_id.in_(account_ids),
                InvestmentEventModel.date <= through,
                InvestmentEventModel.archived_at.is_(None),
                InvestmentEventModel.deleted_at.is_(None),
            )
            .order_by(InvestmentEventModel.date, InvestmentEventModel.id)
        )
        return tuple(rows.all())

    async def load_movements(
        self,
        account_ids: tuple[str, ...],
        *,
        through: datetime,
    ) -> tuple[InvestmentMovementModel, ...]:
        if not account_ids:
            return ()
        rows = await self.session.scalars(
            select(InvestmentMovementModel)
            .join(
                InvestmentEventModel,
                InvestmentEventModel.id == InvestmentMovementModel.event_id,
            )
            .where(
                InvestmentEventModel.date <= through,
                InvestmentEventModel.archived_at.is_(None),
                InvestmentEventModel.deleted_at.is_(None),
                or_(
                    InvestmentEventModel.account_id.in_(account_ids),
                    InvestmentMovementModel.account_id.in_(account_ids),
                ),
            )
            .order_by(InvestmentMovementModel.event_id, InvestmentMovementModel.id)
        )
        return tuple(rows.all())

    async def load_liability_balances(
        self,
        account_ids: tuple[str, ...],
        *,
        through: datetime,
    ) -> tuple[LiabilityBalanceModel, ...]:
        if not account_ids:
            return ()
        rows = await self.session.scalars(
            select(LiabilityBalanceModel)
            .where(
                LiabilityBalanceModel.account_id.in_(account_ids),
                LiabilityBalanceModel.effective_at <= through,
            )
            .order_by(
                LiabilityBalanceModel.account_id,
                LiabilityBalanceModel.effective_at,
                LiabilityBalanceModel.id,
            )
        )
        return tuple(rows.all())
