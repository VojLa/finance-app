"""Canonical investment-event posting with caller-owned transactions."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.common import TIMESTAMP
from app.db.models.enums import ImportRowStatus
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.modules.imports.investment_asset_resolution import (
    ImportInvestmentAssetResolver,
    ResolvedInvestmentAsset,
    validate_resolved_investment_asset,
)
from app.modules.imports.investment_posting_plan import (
    InvestmentEventPostingPlan,
    InvestmentMovementPlan,
    build_investment_posting_plan,
)
from app.modules.imports.posting_common import ImportPostStateError

type MovementSignature = tuple[object, ...]


@dataclass(frozen=True, slots=True)
class PostedInvestmentEvent:
    event: InvestmentEventModel
    movements: tuple[InvestmentMovementModel, ...]
    asset: AssetModel | None
    listing: AssetListingModel | None
    created: bool


def _current_updated_at() -> datetime:
    """Return a naive UTC bookkeeping time exactly representable by TIMESTAMP."""
    now = datetime.now(UTC).replace(tzinfo=None)
    precision = TIMESTAMP.precision
    if precision is None or not 0 <= precision <= 6:
        raise RuntimeError("Canonical TIMESTAMP precision must be between zero and six")
    unit = 10 ** (6 - precision)
    return now.replace(microsecond=now.microsecond - (now.microsecond % unit))


def _exact_persisted_timestamp(value: object) -> bool:
    precision = TIMESTAMP.precision
    if not isinstance(value, datetime) or precision is None:
        return False
    return value.tzinfo is None and value.microsecond % (10 ** (6 - precision)) == 0


def _event_matches(
    event: InvestmentEventModel,
    *,
    event_id: str,
    plan: InvestmentEventPostingPlan,
) -> bool:
    return (
        event.id == event_id
        and event.account_id == plan.account_id
        and event.type is plan.event_type
        and event.date == plan.date
        and event.source is plan.source
        and event.external_id == plan.external_id
        and event.order_id == plan.order_id
        and event.description == plan.description
        and event.realized_pnl == plan.realized_pnl
        and event.realized_pnl_currency == plan.realized_pnl_currency
        and event.import_batch_id == plan.import_batch_id
        and event.archived_at is None
        and event.deleted_at is None
        and _exact_persisted_timestamp(event.created_at)
        and _exact_persisted_timestamp(event.updated_at)
    )


def _movement_signature(
    movement: InvestmentMovementModel,
) -> MovementSignature:
    return (
        movement.kind,
        movement.direction,
        movement.quantity,
        movement.currency,
        movement.asset_id,
        movement.listing_id,
        movement.price_per_unit,
        movement.value_amount,
        movement.value_currency,
        movement.source_symbol,
        movement.source_asset_type,
        movement.note,
    )


def _planned_signature(
    movement: InvestmentMovementPlan,
    *,
    asset: AssetModel | None,
    listing: AssetListingModel | None,
) -> MovementSignature:
    if movement.requires_asset:
        if asset is None or listing is None:
            raise ImportPostStateError()
        asset_id, listing_id = asset.id, listing.id
    else:
        asset_id, listing_id = None, None
    return (
        movement.kind,
        movement.direction,
        movement.quantity,
        movement.currency,
        asset_id,
        listing_id,
        movement.price_per_unit,
        movement.value_amount,
        movement.value_currency,
        movement.source_symbol,
        movement.source_asset_type,
        movement.note,
    )


class ImportInvestmentPostingWriter:
    """Persist one B1 investment plan inside a transaction owned by the caller."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _locked_row(
        self,
        *,
        batch: ImportBatchModel,
        row: ImportRowModel,
    ) -> ImportRowModel:
        locked = await self.session.scalar(
            select(ImportRowModel)
            .where(
                ImportRowModel.id == row.id,
                ImportRowModel.import_batch_id == batch.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked is None:
            raise ImportPostStateError()
        return locked

    async def _resolve_asset(
        self,
        *,
        plan: InvestmentEventPostingPlan,
    ) -> ResolvedInvestmentAsset | None:
        if plan.asset_resolution is None:
            if any(movement.requires_asset for movement in plan.movements):
                raise ImportPostStateError()
            return None
        resolved = await ImportInvestmentAssetResolver(self.session).resolve(
            plan=plan.asset_resolution
        )
        if (
            not resolved.asset.id
            or not resolved.listing.id
            or resolved.listing.asset_id != resolved.asset.id
        ):
            raise ImportPostStateError()
        return resolved

    async def _replay(
        self,
        *,
        row: ImportRowModel,
        plan: InvestmentEventPostingPlan,
    ) -> PostedInvestmentEvent:
        event_id = row.created_investment_event_id
        if not isinstance(event_id, str) or not event_id:
            raise ImportPostStateError()
        event = await self.session.scalar(
            select(InvestmentEventModel)
            .where(InvestmentEventModel.id == event_id)
            .with_for_update()
        )
        if event is None or not _event_matches(event, event_id=event_id, plan=plan):
            raise ImportPostStateError()
        movements = tuple(
            (
                await self.session.scalars(
                    select(InvestmentMovementModel)
                    .where(InvestmentMovementModel.event_id == event.id)
                    .with_for_update()
                )
            ).all()
        )
        asset, listing = await self._replay_asset_identity(plan=plan, movements=movements)
        expected = Counter(
            _planned_signature(movement, asset=asset, listing=listing)
            for movement in plan.movements
        )
        if Counter(_movement_signature(movement) for movement in movements) != expected:
            raise ImportPostStateError()
        return PostedInvestmentEvent(
            event=event,
            movements=movements,
            asset=asset,
            listing=listing,
            created=False,
        )

    async def _replay_asset_identity(
        self,
        *,
        plan: InvestmentEventPostingPlan,
        movements: tuple[InvestmentMovementModel, ...],
    ) -> tuple[AssetModel | None, AssetListingModel | None]:
        if plan.asset_resolution is None:
            if any(
                movement.asset_id is not None or movement.listing_id is not None
                for movement in movements
            ):
                raise ImportPostStateError()
            return None, None
        linked_pairs = {
            (movement.asset_id, movement.listing_id)
            for movement in movements
            if movement.asset_id is not None or movement.listing_id is not None
        }
        if len(linked_pairs) != 1:
            raise ImportPostStateError()
        asset_id, listing_id = linked_pairs.pop()
        if (
            not isinstance(asset_id, str)
            or not asset_id
            or not isinstance(listing_id, str)
            or not listing_id
        ):
            raise ImportPostStateError()
        asset = await self.session.scalar(
            select(AssetModel).where(AssetModel.id == asset_id).with_for_update()
        )
        listing = await self.session.scalar(
            select(AssetListingModel).where(AssetListingModel.id == listing_id).with_for_update()
        )
        if asset is None or listing is None:
            raise ImportPostStateError()
        validate_resolved_investment_asset(
            plan=plan.asset_resolution,
            asset=asset,
            listing=listing,
        )
        return asset, listing

    async def post_row(
        self,
        *,
        account_id: str,
        batch: ImportBatchModel,
        row: ImportRowModel,
    ) -> PostedInvestmentEvent:
        locked_row = await self._locked_row(batch=batch, row=row)
        plan = build_investment_posting_plan(
            account_id=account_id,
            batch=batch,
            row=locked_row,
        )
        if locked_row.status is ImportRowStatus.imported:
            return await self._replay(row=locked_row, plan=plan)
        if locked_row.status is not ImportRowStatus.pending:
            raise ImportPostStateError()
        resolved = await self._resolve_asset(plan=plan)

        asset = None if resolved is None else resolved.asset
        listing = None if resolved is None else resolved.listing
        updated_at = _current_updated_at()
        event = InvestmentEventModel(
            id=str(uuid4()),
            account_id=plan.account_id,
            type=plan.event_type,
            date=plan.date,
            source=plan.source,
            external_id=plan.external_id,
            order_id=plan.order_id,
            description=plan.description,
            realized_pnl=plan.realized_pnl,
            realized_pnl_currency=plan.realized_pnl_currency,
            import_batch_id=plan.import_batch_id,
            archived_at=None,
            deleted_at=None,
            updated_at=updated_at,
        )
        self.session.add(event)
        movements: list[InvestmentMovementModel] = []
        for movement_plan in plan.movements:
            signature = _planned_signature(
                movement_plan,
                asset=asset,
                listing=listing,
            )
            movement = InvestmentMovementModel(
                id=str(uuid4()),
                event_id=event.id,
                account_id=plan.account_id,
                asset_id=signature[4],
                listing_id=signature[5],
                kind=movement_plan.kind,
                direction=movement_plan.direction,
                quantity=movement_plan.quantity,
                currency=movement_plan.currency,
                price_per_unit=movement_plan.price_per_unit,
                value_amount=movement_plan.value_amount,
                value_currency=movement_plan.value_currency,
                source_symbol=movement_plan.source_symbol,
                source_asset_type=movement_plan.source_asset_type,
                note=movement_plan.note,
                updated_at=updated_at,
            )
            self.session.add(movement)
            movements.append(movement)
        await self.session.flush()
        locked_row.status = ImportRowStatus.imported
        locked_row.created_transaction_id = None
        locked_row.created_investment_event_id = event.id
        return PostedInvestmentEvent(
            event=event,
            movements=tuple(movements),
            asset=asset,
            listing=listing,
            created=True,
        )
