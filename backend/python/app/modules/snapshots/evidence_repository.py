"""Explicit read-only SQL boundary for persisted account-snapshot evidence."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.transactions import TransactionModel


@dataclass(frozen=True, slots=True)
class PersistedHoldingEvidence:
    holding: HoldingModel
    listing: AssetListingModel | None
    asset: AssetModel | None


class AccountSnapshotEvidenceRepository:
    """Repository methods deliberately perform no writes or transaction control."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def load_account(self, account_id: str) -> AccountModel | None:
        return await self.session.get(AccountModel, account_id)

    async def load_holdings(
        self,
        account_id: str,
    ) -> tuple[PersistedHoldingEvidence, ...]:
        result = await self.session.execute(
            select(HoldingModel, AssetListingModel, AssetModel)
            .outerjoin(
                AssetListingModel,
                AssetListingModel.id == HoldingModel.listing_id,
            )
            .outerjoin(AssetModel, AssetModel.id == HoldingModel.asset_id)
            .where(HoldingModel.account_id == account_id)
            .order_by(HoldingModel.listing_id, HoldingModel.id)
        )
        return tuple(PersistedHoldingEvidence(*row) for row in result.all())

    async def load_price_candidates(
        self,
        listing_ids: tuple[str, ...],
        *,
        through,
    ) -> tuple[PriceSnapshotModel, ...]:
        if not listing_ids:
            return ()
        result = await self.session.scalars(
            select(PriceSnapshotModel)
            .where(
                PriceSnapshotModel.listing_id.in_(listing_ids),
                PriceSnapshotModel.timestamp <= through,
            )
            .order_by(
                PriceSnapshotModel.listing_id,
                PriceSnapshotModel.timestamp.desc(),
                PriceSnapshotModel.id.desc(),
            )
        )
        return tuple(result.all())

    async def load_exchange_rate_candidates(
        self,
        base_currencies: tuple[str, ...],
        quote_currency: str,
        *,
        through,
    ) -> tuple[ExchangeRateModel, ...]:
        if not base_currencies:
            return ()
        result = await self.session.scalars(
            select(ExchangeRateModel)
            .where(
                ExchangeRateModel.from_currency.in_(base_currencies),
                ExchangeRateModel.to_currency == quote_currency,
                ExchangeRateModel.date <= through,
            )
            .order_by(
                ExchangeRateModel.from_currency,
                ExchangeRateModel.date.desc(),
                ExchangeRateModel.id.desc(),
            )
        )
        return tuple(result.all())

    async def load_active_transactions(
        self,
        account_id: str,
        *,
        through,
    ) -> tuple[TransactionModel, ...]:
        result = await self.session.scalars(
            select(TransactionModel)
            .where(
                TransactionModel.account_id == account_id,
                TransactionModel.date <= through,
                TransactionModel.archived_at.is_(None),
                TransactionModel.deleted_at.is_(None),
            )
            .order_by(TransactionModel.date, TransactionModel.id)
        )
        return tuple(result.all())

    async def load_active_events(
        self,
        account_id: str,
        *,
        through,
    ) -> tuple[InvestmentEventModel, ...]:
        result = await self.session.scalars(
            select(InvestmentEventModel)
            .where(
                InvestmentEventModel.account_id == account_id,
                InvestmentEventModel.date <= through,
                InvestmentEventModel.archived_at.is_(None),
                InvestmentEventModel.deleted_at.is_(None),
            )
            .order_by(InvestmentEventModel.date, InvestmentEventModel.id)
        )
        return tuple(result.all())

    async def load_active_movements(
        self,
        account_id: str,
        *,
        through,
    ) -> tuple[InvestmentMovementModel, ...]:
        result = await self.session.scalars(
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
                    InvestmentEventModel.account_id == account_id,
                    InvestmentMovementModel.account_id == account_id,
                ),
            )
            .order_by(
                InvestmentMovementModel.event_id,
                InvestmentMovementModel.id,
            )
        )
        return tuple(result.all())
