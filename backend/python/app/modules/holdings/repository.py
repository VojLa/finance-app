"""Explicit SQL and lock boundary for atomic Holding rebuilds."""

from __future__ import annotations

from hashlib import sha256

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.canonical_lineage import (
    AccountCanonicalChangeModel,
    AccountCanonicalStateModel,
)
from app.db.models.enums import ImportSource
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import (
    InvestmentEventModel,
    InvestmentMovementModel,
    InvestmentMovementValuationEvidenceModel,
)
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.modules.investments.transfer_valuation import validate_transfer_valuation_citations


def advisory_lock_id(scope: str) -> int:
    return int.from_bytes(sha256(scope.encode()).digest()[:8], "big", signed=True)


def holdings_rebuild_lock_scope(account_id: str) -> str:
    return f"holdings:rebuild:{account_id}"


def canonical_history_lock_scopes(account_id: str) -> tuple[str, ...]:
    return tuple(
        f"imports:deduplication:{account_id}:{source.value}"
        for source in sorted(ImportSource, key=lambda item: item.value)
    )


class HoldingRebuildRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_rebuild_scope(self, account_id: str) -> None:
        lock_id = advisory_lock_id(holdings_rebuild_lock_scope(account_id))
        await self.session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    async def lock_canonical_history_scopes(self, account_id: str) -> None:
        lock_ids = sorted(
            {advisory_lock_id(scope) for scope in canonical_history_lock_scopes(account_id)}
        )
        for lock_id in lock_ids:
            await self.session.execute(select(func.pg_advisory_xact_lock(lock_id)))

    async def lock_canonical_state(self, account_id: str) -> AccountCanonicalStateModel | None:
        return await self.session.scalar(
            select(AccountCanonicalStateModel)
            .where(AccountCanonicalStateModel.account_id == account_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_active_events_for_update(
        self,
        account_id: str,
    ) -> list[InvestmentEventModel]:
        result = await self.session.scalars(
            select(InvestmentEventModel)
            .where(
                InvestmentEventModel.account_id == account_id,
                InvestmentEventModel.archived_at.is_(None),
                InvestmentEventModel.deleted_at.is_(None),
            )
            .order_by(InvestmentEventModel.date, InvestmentEventModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.all())

    async def load_investment_changes_for_update(
        self,
        account_id: str,
    ) -> list[AccountCanonicalChangeModel]:
        result = await self.session.scalars(
            select(AccountCanonicalChangeModel)
            .where(
                AccountCanonicalChangeModel.account_id == account_id,
                AccountCanonicalChangeModel.kind == "investment_event",
            )
            .order_by(AccountCanonicalChangeModel.revision)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.all())

    async def load_active_account_movements_for_update(
        self,
        account_id: str,
    ) -> list[InvestmentMovementModel]:
        result = await self.session.scalars(
            select(InvestmentMovementModel)
            .join(
                InvestmentEventModel,
                InvestmentEventModel.id == InvestmentMovementModel.event_id,
            )
            .where(
                InvestmentEventModel.archived_at.is_(None),
                InvestmentEventModel.deleted_at.is_(None),
                or_(
                    InvestmentEventModel.account_id == account_id,
                    InvestmentMovementModel.account_id == account_id,
                ),
            )
            .order_by(InvestmentMovementModel.event_id, InvestmentMovementModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.all())

    async def load_transfer_valuations_for_update(
        self,
        movement_ids: tuple[str, ...],
    ) -> list[InvestmentMovementValuationEvidenceModel]:
        if not movement_ids:
            return []
        result = await self.session.execute(
            select(
                InvestmentMovementValuationEvidenceModel,
                PriceSnapshotModel,
                ExchangeRateModel,
                InvestmentMovementModel,
            )
            .join(
                PriceSnapshotModel,
                PriceSnapshotModel.id == InvestmentMovementValuationEvidenceModel.price_snapshot_id,
            )
            .outerjoin(
                ExchangeRateModel,
                ExchangeRateModel.id == InvestmentMovementValuationEvidenceModel.exchange_rate_id,
            )
            .join(
                InvestmentMovementModel,
                InvestmentMovementModel.id == InvestmentMovementValuationEvidenceModel.movement_id,
            )
            .where(InvestmentMovementValuationEvidenceModel.movement_id.in_(movement_ids))
            .order_by(
                InvestmentMovementValuationEvidenceModel.movement_id,
                InvestmentMovementValuationEvidenceModel.revision,
            )
            .with_for_update(of=InvestmentMovementValuationEvidenceModel)
            .execution_options(populate_existing=True)
        )
        rows: list[InvestmentMovementValuationEvidenceModel] = []
        for evidence, price, rate, movement in result.all():
            validate_transfer_valuation_citations(
                evidence=evidence,
                movement=movement,
                price=price,
                exchange_rate=rate,
            )
            rows.append(evidence)
        return rows

    async def lock_account_holdings(self, account_id: str) -> list[HoldingModel]:
        result = await self.session.scalars(
            select(HoldingModel)
            .where(HoldingModel.account_id == account_id)
            .order_by(HoldingModel.listing_id, HoldingModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.all())

    async def load_listings_for_update(
        self,
        listing_ids: tuple[str, ...],
    ) -> list[AssetListingModel]:
        if not listing_ids:
            return []
        result = await self.session.scalars(
            select(AssetListingModel)
            .where(AssetListingModel.id.in_(listing_ids))
            .order_by(AssetListingModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.all())

    async def load_assets_for_update(
        self,
        asset_ids: tuple[str, ...],
    ) -> list[AssetModel]:
        if not asset_ids:
            return []
        result = await self.session.scalars(
            select(AssetModel)
            .where(AssetModel.id.in_(asset_ids))
            .order_by(AssetModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.all())

    async def load_holdings_by_ids_for_update(
        self,
        holding_ids: tuple[str, ...],
    ) -> list[HoldingModel]:
        if not holding_ids:
            return []
        result = await self.session.scalars(
            select(HoldingModel)
            .where(HoldingModel.id.in_(holding_ids))
            .order_by(HoldingModel.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return list(result.all())

    def add_holding(self, holding: HoldingModel) -> None:
        self.session.add(holding)

    async def delete_holding(self, holding: HoldingModel) -> None:
        await self.session.delete(holding)

    async def flush(self) -> None:
        await self.session.flush()
