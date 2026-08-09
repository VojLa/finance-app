from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    AccountMemberRole,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
)
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.modules.accounts.access import require_account_access
from app.modules.canonical_state import (
    CanonicalChangeKind,
    CanonicalStateError,
    CanonicalStateService,
)
from app.modules.holdings.projection import HoldingProjectionStateError
from app.modules.holdings.rebuild_service import HoldingRebuildService, HoldingRebuildStateError
from app.modules.imports.investment_asset_resolution import ImportInvestmentAssetResolver
from app.modules.imports.investment_posting_plan import (
    InvestmentAssetResolutionPlan,
    InvestmentMovementPlan,
)
from app.modules.imports.posting_common import ImportPostStateError
from app.modules.investments.models import (
    ManualInvestmentAction,
    ManualInvestmentCreateRequest,
    ManualInvestmentCreateResponse,
    ManualInvestmentHoldingResult,
    ManualInvestmentSnapshotResult,
    SymbolDetailResponse,
    SymbolEventResponse,
    SymbolPositionResponse,
)
from app.modules.investments.repository import InvestmentRepository
from app.modules.snapshot_refresh.manual_service import (
    RecalculateUserSnapshotRefreshCommand,
    RecalculateUserSnapshotRefreshResult,
    UserSnapshotRefreshConflictError,
    UserSnapshotRefreshUnavailableError,
)
from app.shared.errors import ApplicationError

_EVENT_NAMESPACE = UUID("6ac2f979-971e-54cf-87ec-33343b18cfe2")
_MOVEMENT_NAMESPACE = UUID("7aab8203-b2d5-5334-9d54-c5b590988ac0")
_WRITE_ROLES = {
    AccountMemberRole.owner,
    AccountMemberRole.admin,
    AccountMemberRole.editor,
}


class ManualInvestmentConflictError(ApplicationError):
    def __init__(self, message: str = "The idempotency key has already been used.") -> None:
        super().__init__(code="manual_investment_conflict", message=message, status_code=409)


class ManualInvestmentUnavailableError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="manual_investment_unavailable",
            message="The investment event cannot be produced from the supplied evidence.",
            status_code=409,
        )


class _SnapshotService(Protocol):
    async def recalculate(
        self, command: RecalculateUserSnapshotRefreshCommand
    ) -> RecalculateUserSnapshotRefreshResult: ...


@dataclass(frozen=True, slots=True)
class ManualEventPlan:
    event_type: InvestmentEventType
    description: str | None
    asset: InvestmentAssetResolutionPlan | None
    movements: tuple[InvestmentMovementPlan, ...]


def _now() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    precision = TIMESTAMP.precision
    if precision is None:
        raise RuntimeError("Timestamp precision is unavailable.")
    unit = 10 ** (6 - precision)
    return value.replace(microsecond=value.microsecond - (value.microsecond % unit))


def _movement(
    *,
    kind: InvestmentMovementKind,
    direction: MovementDirection,
    quantity: object,
    currency: str,
    requires_asset: bool = False,
    price_per_unit: object = None,
    value_amount: object = None,
    value_currency: str | None = None,
    asset: InvestmentAssetResolutionPlan | None = None,
) -> InvestmentMovementPlan:
    from decimal import Decimal

    if not isinstance(quantity, Decimal) or quantity <= 0:
        raise ManualInvestmentUnavailableError()
    if price_per_unit is not None and (
        not isinstance(price_per_unit, Decimal) or price_per_unit <= 0
    ):
        raise ManualInvestmentUnavailableError()
    if value_amount is not None and (not isinstance(value_amount, Decimal) or value_amount <= 0):
        raise ManualInvestmentUnavailableError()
    if requires_asset and asset is None:
        raise ManualInvestmentUnavailableError()
    return InvestmentMovementPlan(
        kind=kind,
        direction=direction,
        quantity=quantity,
        currency=currency,
        requires_asset=requires_asset,
        price_per_unit=price_per_unit,
        value_amount=value_amount,
        value_currency=value_currency,
        source_symbol=asset.symbol if requires_asset and asset is not None else None,
        source_asset_type=asset.asset_type if requires_asset and asset is not None else None,
        note=None,
    )


def _asset_plan(payload: ManualInvestmentCreateRequest) -> InvestmentAssetResolutionPlan | None:
    if payload.symbol is None or payload.asset_type is None:
        return None
    listing_currency = (
        payload.symbol
        if payload.asset_type.value == "crypto"
        else payload.price_currency or payload.total_currency
    )
    if listing_currency is None:
        raise ManualInvestmentUnavailableError()
    return InvestmentAssetResolutionPlan(
        symbol=payload.symbol,
        isin=None,
        name=payload.name,
        asset_type=payload.asset_type,
        provider=PriceSource.manual,
        provider_symbol=payload.symbol,
        exchange="manual",
        listing_currency_hint=listing_currency,
        asset_currency_hint=payload.symbol
        if payload.asset_type.value == "crypto"
        else listing_currency,
    )


def build_manual_event_plan(payload: ManualInvestmentCreateRequest) -> ManualEventPlan:
    asset = _asset_plan(payload)
    movements: list[InvestmentMovementPlan] = []
    action = payload.type
    event_type = {
        ManualInvestmentAction.buy: InvestmentEventType.trade,
        ManualInvestmentAction.sell: InvestmentEventType.trade,
        ManualInvestmentAction.dividend: InvestmentEventType.dividend,
        ManualInvestmentAction.interest: InvestmentEventType.interest,
        ManualInvestmentAction.staking_reward: InvestmentEventType.staking_reward,
        ManualInvestmentAction.deposit: (
            InvestmentEventType.asset_transfer
            if asset is not None
            else InvestmentEventType.cash_deposit
        ),
        ManualInvestmentAction.withdrawal: (
            InvestmentEventType.asset_transfer
            if asset is not None
            else InvestmentEventType.cash_withdrawal
        ),
        ManualInvestmentAction.fee: InvestmentEventType.fee,
        ManualInvestmentAction.currency_conversion: InvestmentEventType.currency_conversion,
        ManualInvestmentAction.airdrop: InvestmentEventType.airdrop,
    }[action]

    if action in {ManualInvestmentAction.buy, ManualInvestmentAction.sell}:
        assert asset is not None and payload.quantity is not None
        assert payload.total_amount is not None and payload.total_currency is not None
        asset_direction = (
            MovementDirection.incoming
            if action is ManualInvestmentAction.buy
            else MovementDirection.outgoing
        )
        cash_direction = (
            MovementDirection.outgoing
            if action is ManualInvestmentAction.buy
            else MovementDirection.incoming
        )
        movements.extend(
            (
                _movement(
                    kind=InvestmentMovementKind.asset,
                    direction=asset_direction,
                    quantity=payload.quantity,
                    currency=asset.symbol,
                    requires_asset=True,
                    price_per_unit=payload.price_per_unit,
                    value_amount=payload.total_amount,
                    value_currency=payload.total_currency,
                    asset=asset,
                ),
                _movement(
                    kind=InvestmentMovementKind.cash,
                    direction=cash_direction,
                    quantity=payload.total_amount,
                    currency=payload.total_currency,
                    value_amount=payload.total_amount,
                    value_currency=payload.total_currency,
                ),
            )
        )
    elif action is ManualInvestmentAction.dividend:
        assert asset is not None and payload.total_amount is not None
        assert payload.total_currency is not None
        movements.append(
            _movement(
                kind=InvestmentMovementKind.cash,
                direction=MovementDirection.incoming,
                quantity=payload.total_amount,
                currency=payload.total_currency,
                requires_asset=True,
                value_amount=payload.total_amount,
                value_currency=payload.total_currency,
                asset=asset,
            )
        )
    elif (
        action in {ManualInvestmentAction.interest, ManualInvestmentAction.deposit}
        and asset is None
    ):
        assert payload.total_amount is not None and payload.total_currency is not None
        movements.append(
            _movement(
                kind=InvestmentMovementKind.cash,
                direction=MovementDirection.incoming,
                quantity=payload.total_amount,
                currency=payload.total_currency,
                value_amount=payload.total_amount,
                value_currency=payload.total_currency,
            )
        )
    elif action is ManualInvestmentAction.withdrawal and asset is None:
        assert payload.total_amount is not None and payload.total_currency is not None
        movements.append(
            _movement(
                kind=InvestmentMovementKind.cash,
                direction=MovementDirection.outgoing,
                quantity=payload.total_amount,
                currency=payload.total_currency,
                value_amount=payload.total_amount,
                value_currency=payload.total_currency,
            )
        )
    elif action in {ManualInvestmentAction.deposit, ManualInvestmentAction.withdrawal}:
        assert asset is not None and payload.quantity is not None
        movements.append(
            _movement(
                kind=InvestmentMovementKind.asset,
                direction=(
                    MovementDirection.incoming
                    if action is ManualInvestmentAction.deposit
                    else MovementDirection.outgoing
                ),
                quantity=payload.quantity,
                currency=asset.symbol,
                requires_asset=True,
                price_per_unit=payload.price_per_unit,
                value_currency=payload.price_currency,
                asset=asset,
            )
        )
    elif action is ManualInvestmentAction.fee:
        assert payload.total_amount is not None and payload.total_currency is not None
        movements.append(
            _movement(
                kind=InvestmentMovementKind.fee,
                direction=MovementDirection.outgoing,
                quantity=payload.total_amount,
                currency=payload.total_currency,
                value_amount=payload.total_amount,
                value_currency=payload.total_currency,
            )
        )
    elif action is ManualInvestmentAction.currency_conversion:
        assert payload.conversion_from_amount is not None
        assert payload.conversion_from_currency is not None
        assert payload.conversion_to_amount is not None
        assert payload.conversion_to_currency is not None
        movements.extend(
            (
                _movement(
                    kind=InvestmentMovementKind.cash,
                    direction=MovementDirection.outgoing,
                    quantity=payload.conversion_from_amount,
                    currency=payload.conversion_from_currency,
                    value_amount=payload.conversion_from_amount,
                    value_currency=payload.conversion_from_currency,
                ),
                _movement(
                    kind=InvestmentMovementKind.cash,
                    direction=MovementDirection.incoming,
                    quantity=payload.conversion_to_amount,
                    currency=payload.conversion_to_currency,
                    value_amount=payload.conversion_to_amount,
                    value_currency=payload.conversion_to_currency,
                ),
            )
        )
    elif action in {ManualInvestmentAction.staking_reward, ManualInvestmentAction.airdrop}:
        assert asset is not None and payload.quantity is not None
        movements.append(
            _movement(
                kind=InvestmentMovementKind.asset,
                direction=MovementDirection.incoming,
                quantity=payload.quantity,
                currency=asset.symbol,
                requires_asset=True,
                price_per_unit=payload.price_per_unit,
                value_amount=payload.total_amount,
                value_currency=payload.total_currency or payload.price_currency,
                asset=asset,
            )
        )
    else:
        raise ManualInvestmentUnavailableError()

    if payload.fee is not None:
        if action is ManualInvestmentAction.fee or payload.fee_currency is None:
            raise ManualInvestmentUnavailableError()
        movements.append(
            _movement(
                kind=InvestmentMovementKind.fee,
                direction=MovementDirection.outgoing,
                quantity=payload.fee,
                currency=payload.fee_currency,
                value_amount=payload.fee,
                value_currency=payload.fee_currency,
            )
        )
    if not movements:
        raise ManualInvestmentUnavailableError()
    return ManualEventPlan(
        event_type=event_type,
        description=payload.name or payload.symbol or action.value,
        asset=asset,
        movements=tuple(movements),
    )


def _planned_signature(movement: InvestmentMovementPlan) -> tuple[object, ...]:
    return (
        movement.kind,
        movement.direction,
        movement.quantity,
        movement.currency,
        movement.requires_asset,
        movement.price_per_unit,
        movement.value_amount,
        movement.value_currency,
        movement.source_symbol,
        movement.source_asset_type,
        movement.note,
    )


def _persisted_signature(movement: InvestmentMovementModel) -> tuple[object, ...]:
    has_asset = movement.asset_id is not None and movement.listing_id is not None
    if (movement.asset_id is None) != (movement.listing_id is None):
        raise ManualInvestmentConflictError()
    return (
        movement.kind,
        movement.direction,
        movement.quantity,
        movement.currency,
        has_asset,
        movement.price_per_unit,
        movement.value_amount,
        movement.value_currency,
        movement.source_symbol,
        movement.source_asset_type,
        movement.note,
    )


def _event_action(
    event: InvestmentEventModel, movements: list[InvestmentMovementModel]
) -> ManualInvestmentAction | str:
    asset = next(
        (movement for movement in movements if movement.kind is InvestmentMovementKind.asset),
        None,
    )
    if event.type is InvestmentEventType.trade:
        return (
            ManualInvestmentAction.sell
            if asset is not None and asset.direction is MovementDirection.outgoing
            else ManualInvestmentAction.buy
        )
    if event.type is InvestmentEventType.asset_transfer:
        return (
            ManualInvestmentAction.withdrawal
            if asset is not None and asset.direction is MovementDirection.outgoing
            else ManualInvestmentAction.deposit
        )
    if event.type is InvestmentEventType.cash_deposit:
        return ManualInvestmentAction.deposit
    if event.type is InvestmentEventType.cash_withdrawal:
        return ManualInvestmentAction.withdrawal
    if event.type is InvestmentEventType.adjustment:
        return "transfer"
    return ManualInvestmentAction(event.type.value)


class InvestmentService:
    def __init__(
        self, session: AsyncSession, *, snapshot_service: _SnapshotService | None = None
    ) -> None:
        self.session = session
        self.repository = InvestmentRepository(session)
        self.snapshot_service = snapshot_service

    async def create_manual(
        self, *, principal: AuthenticatedPrincipal, payload: ManualInvestmentCreateRequest
    ) -> ManualInvestmentCreateResponse:
        plan = build_manual_event_plan(payload)
        scope = (
            f"manual-investment:{principal.user_id}:{payload.account_id}:{payload.idempotency_key}"
        )
        event_id = str(uuid5(_EVENT_NAMESPACE, scope))
        external_id = f"manual:{principal.user_id}:{payload.idempotency_key}"
        try:
            await require_account_access(
                session=self.session,
                principal=principal,
                account_id=payload.account_id,
                allowed_roles=_WRITE_ROLES,
                for_update=True,
            )
            await self.repository.lock_idempotency_key(scope)
            existing = await self.repository.event_for_update(event_id)
            now = _now()
            if existing is None:
                await self.repository.ensure_canonical_state(payload.account_id, now)
                resolved = (
                    None
                    if plan.asset is None
                    else await ImportInvestmentAssetResolver(self.session).resolve(plan=plan.asset)
                )
                event = InvestmentEventModel(
                    id=event_id,
                    account_id=payload.account_id,
                    type=plan.event_type,
                    date=payload.date,
                    source=ImportSource.manual,
                    external_id=external_id,
                    order_id=None,
                    description=plan.description,
                    realized_pnl=None,
                    realized_pnl_currency=None,
                    import_batch_id=None,
                    archived_at=None,
                    deleted_at=None,
                    created_at=now,
                    updated_at=now,
                )
                self.repository.add(event)
                await self.repository.flush()
                for index, movement in enumerate(plan.movements):
                    requires_asset = movement.requires_asset
                    if requires_asset and resolved is None:
                        raise ManualInvestmentUnavailableError()
                    self.repository.add(
                        InvestmentMovementModel(
                            id=str(uuid5(_MOVEMENT_NAMESPACE, f"{event_id}:{index}")),
                            event_id=event_id,
                            account_id=payload.account_id,
                            asset_id=resolved.asset.id if requires_asset and resolved else None,
                            listing_id=resolved.listing.id if requires_asset and resolved else None,
                            kind=movement.kind,
                            direction=movement.direction,
                            quantity=movement.quantity,
                            currency=movement.currency,
                            price_per_unit=movement.price_per_unit,
                            value_amount=movement.value_amount,
                            value_currency=movement.value_currency,
                            source_symbol=movement.source_symbol,
                            source_asset_type=movement.source_asset_type,
                            note=movement.note,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                await self.repository.flush()
                await CanonicalStateService(self.session).record(
                    account_id=payload.account_id,
                    kind=CanonicalChangeKind.investment_event,
                    entity_id=event.id,
                    financial_timestamp=event.date,
                    created_at=event.created_at,
                    replay=False,
                )
                replayed = False
            else:
                event = existing
                movements = await self.repository.event_movements_for_update(event.id)
                if (
                    event.account_id != payload.account_id
                    or event.type is not plan.event_type
                    or event.date != payload.date
                    or event.source is not ImportSource.manual
                    or event.external_id != external_id
                    or event.order_id is not None
                    or event.description != plan.description
                    or event.realized_pnl is not None
                    or event.realized_pnl_currency is not None
                    or event.import_batch_id is not None
                    or event.archived_at is not None
                    or event.deleted_at is not None
                    or Counter(_persisted_signature(value) for value in movements)
                    != Counter(_planned_signature(value) for value in plan.movements)
                ):
                    raise ManualInvestmentConflictError()
                await CanonicalStateService(self.session).record(
                    account_id=payload.account_id,
                    kind=CanonicalChangeKind.investment_event,
                    entity_id=event.id,
                    financial_timestamp=event.date,
                    created_at=event.created_at,
                    replay=True,
                )
                replayed = True

            rebuilt = await HoldingRebuildService(self.session).rebuild(
                account_id=payload.account_id,
                rebuilt_at=now,
            )
            await self.session.commit()
        except ManualInvestmentConflictError:
            await self.session.rollback()
            raise
        except (
            CanonicalStateError,
            HoldingProjectionStateError,
            HoldingRebuildStateError,
            ImportPostStateError,
        ) as exc:
            await self.session.rollback()
            raise ManualInvestmentUnavailableError() from exc
        except Exception:
            await self.session.rollback()
            raise

        snapshot = await self._refresh_snapshot(principal)
        return ManualInvestmentCreateResponse(
            event_id=event_id,
            replayed=replayed,
            holdings=ManualInvestmentHoldingResult(
                created=rebuilt.created,
                updated=rebuilt.updated,
                deleted=rebuilt.deleted,
                total=rebuilt.total,
                replayed=rebuilt.replayed,
            ),
            snapshot=snapshot,
        )

    async def _refresh_snapshot(
        self, principal: AuthenticatedPrincipal
    ) -> ManualInvestmentSnapshotResult:
        if self.snapshot_service is None:
            return ManualInvestmentSnapshotResult(status="unavailable")
        try:
            result = await self.snapshot_service.recalculate(
                RecalculateUserSnapshotRefreshCommand(principal=principal)
            )
        except UserSnapshotRefreshConflictError:
            return ManualInvestmentSnapshotResult(status="conflict")
        except UserSnapshotRefreshUnavailableError:
            return ManualInvestmentSnapshotResult(status="unavailable")
        return ManualInvestmentSnapshotResult(
            status="ready",
            net_worth_snapshot_id=result.net_worth_snapshot_id,
            timestamp=result.timestamp,
        )

    async def symbol_detail(
        self, *, principal: AuthenticatedPrincipal, symbol: str
    ) -> SymbolDetailResponse:
        canonical_symbol = symbol.strip().upper()
        if not canonical_symbol or not canonical_symbol.isascii() or len(canonical_symbol) > 64:
            raise ManualInvestmentUnavailableError()
        positions = await self.repository.symbol_positions(
            user_id=principal.user_id, symbol=canonical_symbol
        )
        events = await self.repository.symbol_events(
            user_id=principal.user_id, symbol=canonical_symbol
        )
        response = SymbolDetailResponse(
            symbol=canonical_symbol,
            positions=[
                SymbolPositionResponse(
                    id=holding.id,
                    account_id=holding.account_id,
                    account_name=account.name,
                    asset_id=holding.asset_id,
                    listing_id=holding.listing_id,
                    symbol=holding.symbol,
                    name=holding.name,
                    asset_type=holding.asset_type,
                    quantity=holding.quantity,
                    avg_buy_price=holding.avg_buy_price,
                    currency=holding.currency,
                    current_price=holding.current_price,
                    current_value=holding.current_value,
                    unrealized_pnl=holding.unrealized_pnl,
                    realized_pnl=holding.realized_pnl,
                    calculated_at=holding.calculated_at,
                )
                for holding, account in positions
            ],
            events=[
                self._event_response(event, account.name, movements)
                for event, account, movements in events
            ],
        )
        await self.session.commit()
        return response

    def _event_response(
        self,
        event: InvestmentEventModel,
        account_name: str,
        movements: list[InvestmentMovementModel],
    ) -> SymbolEventResponse:
        asset = next(
            (value for value in movements if value.kind is InvestmentMovementKind.asset), None
        )
        cash = next(
            (value for value in movements if value.kind is InvestmentMovementKind.cash), None
        )
        fee = next((value for value in movements if value.kind is InvestmentMovementKind.fee), None)
        price_currency = (
            asset.value_currency
            if asset is not None and asset.value_currency is not None
            else cash.currency
            if cash is not None
            else None
        )
        return SymbolEventResponse(
            id=event.id,
            account_id=event.account_id,
            account_name=account_name,
            date=event.date,
            type=_event_action(event, movements),
            description=event.description,
            quantity=None if asset is None else asset.quantity,
            price_per_unit=None if asset is None else asset.price_per_unit,
            price_currency=price_currency,
            total_amount=(
                cash.quantity if cash is not None else None if asset is None else asset.value_amount
            ),
            total_currency=(
                cash.currency
                if cash is not None
                else None
                if asset is None
                else asset.value_currency
            ),
            fee=None if fee is None else fee.quantity,
            fee_currency=None if fee is None else fee.currency,
            realized_pnl=event.realized_pnl,
            realized_pnl_currency=event.realized_pnl_currency,
        )
