from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.common import TIMESTAMP
from app.db.models.enums import (
    AccountMemberRole,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MarketDataHealthState,
    MovementDirection,
    PriceSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.market_health import MarketDataListingHealthModel
from app.db.models.prices import PriceSnapshotModel
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
from app.modules.market_data.exchange_calendar import assess_market
from app.modules.market_data.listing_selection import (
    ListingSelectionCandidate,
    ListingSelectionError,
    ListingSelectionResult,
    select_listing,
)
from app.modules.market_data.models import MarketEvidenceStateError
from app.modules.market_data.policy import DEFAULT_MARKET_EVIDENCE_POLICY
from app.modules.market_data.requirements import ResolvedPriceIdentity, resolve_price_identity
from app.modules.market_data.source_policy import MarketEvidenceSourcePolicy
from app.modules.portfolio_history.invalidation.service import (
    PortfolioHistoryInvalidationService,
    PortfolioHistoryInvalidationStateError,
)
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


def _trace_status(
    *,
    holding: HoldingModel,
    listing: AssetListingModel | None,
    asset: AssetModel | None,
    identity: ResolvedPriceIdentity | None,
    price: PriceSnapshotModel | None,
    conflicting_price: bool,
    as_of: datetime,
    selected_listing: AssetListingModel | None = None,
) -> Literal["ok", "unresolved", "conflict", "stale", "unavailable"]:
    if listing is None or asset is None:
        return "unresolved"
    if (
        holding.asset_id != asset.id
        or holding.listing_id != listing.id
        or listing.asset_id != asset.id
        or holding.asset_type is not asset.asset_type
    ):
        return "conflict"
    if identity is None:
        return "unresolved"
    if holding.currency != listing.currency:
        return "conflict"
    if price is None:
        return "conflict" if conflicting_price else "unavailable"
    actual_listing = selected_listing or listing
    if (
        price.asset_id != asset.id
        or actual_listing.asset_id != asset.id
        or price.listing_id != actual_listing.id
        or price.source is not identity.provider
        or price.currency != identity.price_currency
    ):
        return "conflict"
    if price.provider_symbol is None:
        return "unavailable"
    if price.provider_symbol != identity.provider_symbol:
        return "conflict"
    if identity.price_currency != holding.currency:
        return "unavailable"
    if price.timestamp > as_of:
        return "conflict"
    if (
        _price_freshness(
            price=price, listing=actual_listing, asset_type=holding.asset_type.value, as_of=as_of
        )
        == "stale"
    ):
        return "stale"
    if holding.current_price is None or holding.current_value is None:
        return "unavailable"
    return "ok"


def _price_freshness(
    *,
    price: PriceSnapshotModel | None,
    listing: AssetListingModel,
    asset_type: str,
    as_of: datetime,
) -> Literal["fresh", "stale", "unavailable"]:
    if price is None:
        return "unavailable"
    if price.timestamp > as_of:
        return "stale"
    if as_of - price.timestamp <= DEFAULT_MARKET_EVIDENCE_POLICY.maximum_price_age:
        return "fresh"
    calendar = assess_market(listing.mic, as_of.replace(tzinfo=UTC), asset_type=asset_type)
    return (
        "fresh"
        if calendar.status in {"closed", "weekend", "holiday"}
        and calendar.expected_previous_close is not None
        and price.timestamp.replace(tzinfo=UTC) >= calendar.expected_previous_close
        else "stale"
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
) -> ManualInvestmentAction | Literal["transfer"]:
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
            history = PortfolioHistoryInvalidationService(self.session)
            locked_memberships = await history.lock_current_memberships((payload.account_id,))
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
                recorded = await CanonicalStateService(self.session).record(
                    account_id=payload.account_id,
                    kind=CanonicalChangeKind.investment_event,
                    entity_id=event.id,
                    financial_timestamp=event.date,
                    created_at=event.created_at,
                    replay=False,
                )
                await history.invalidate_recorded_changes(
                    changes=(recorded,),
                    locked_memberships=locked_memberships,
                    now=now,
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
                recorded = await CanonicalStateService(self.session).record(
                    account_id=payload.account_id,
                    kind=CanonicalChangeKind.investment_event,
                    entity_id=event.id,
                    financial_timestamp=event.date,
                    created_at=event.created_at,
                    replay=True,
                )
                await history.invalidate_recorded_changes(
                    changes=(recorded,),
                    locked_memberships=locked_memberships,
                    now=now,
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
            PortfolioHistoryInvalidationStateError,
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
        self,
        *,
        principal: AuthenticatedPrincipal,
        symbol: str,
        source_policy: MarketEvidenceSourcePolicy,
    ) -> SymbolDetailResponse:
        canonical_symbol = symbol.strip().upper()
        if not canonical_symbol or not canonical_symbol.isascii() or len(canonical_symbol) > 64:
            raise ManualInvestmentUnavailableError()
        positions = await self.repository.symbol_positions(
            user_id=principal.user_id, symbol=canonical_symbol
        )
        asset_ids = tuple(sorted({asset.id for _, _, _, asset in positions if asset is not None}))
        (
            aliases_by_asset,
            listings_by_asset,
            health_by_identity,
            provider_retry_after,
        ) = await self.repository.symbol_identity_context(asset_ids)
        events = await self.repository.symbol_events(
            user_id=principal.user_id, symbol=canonical_symbol
        )
        response = SymbolDetailResponse(
            symbol=canonical_symbol,
            positions=[
                await self._position_response(
                    holding=holding,
                    account_name=account.name,
                    listing=listing,
                    asset=asset,
                    aliases=aliases_by_asset.get(asset.id, ()) if asset is not None else (),
                    candidate_listings=listings_by_asset.get(asset.id, ())
                    if asset is not None
                    else (),
                    health_by_identity=health_by_identity,
                    provider_retry_after=provider_retry_after,
                    source_policy=source_policy,
                )
                for holding, account, listing, asset in positions
            ],
            events=[
                self._event_response(event, account.name, movements)
                for event, account, movements in events
            ],
        )
        await self.session.commit()
        return response

    async def _position_response(
        self,
        *,
        holding: HoldingModel,
        account_name: str,
        listing: AssetListingModel | None,
        asset: AssetModel | None,
        aliases: tuple[AssetAliasModel, ...],
        candidate_listings: tuple[AssetListingModel, ...],
        health_by_identity: dict[tuple[str, PriceSource], MarketDataListingHealthModel],
        provider_retry_after: dict[PriceSource, datetime],
        source_policy: MarketEvidenceSourcePolicy,
    ) -> SymbolPositionResponse:
        as_of = datetime.now(UTC).replace(tzinfo=None)
        identity: ResolvedPriceIdentity | None = None
        price: PriceSnapshotModel | None = None
        conflicting_price = False
        selection: ListingSelectionResult | None = None
        selected_listing: AssetListingModel | None = None
        candidates: list[ListingSelectionCandidate] = []
        prices: dict[str, PriceSnapshotModel] = {}
        identities: dict[str, ResolvedPriceIdentity] = {}
        listings = {
            item.id: item
            for item in candidate_listings
            if asset is not None and item.asset_id == asset.id
        }
        if (
            listing is not None
            and asset is not None
            and holding.asset_id == asset.id
            and listing.asset_id == asset.id
        ):
            for candidate_listing in listings.values():
                candidate_aliases = tuple(
                    alias
                    for alias in aliases
                    if alias.listing_id is None or alias.listing_id == candidate_listing.id
                )
                try:
                    candidate_identity = resolve_price_identity(
                        listing=candidate_listing,
                        asset=asset,
                        aliases=candidate_aliases,
                        supported_sources=source_policy.price_sources,
                        source_policy=source_policy,
                        asset_listing_count=len(listings),
                    )
                except MarketEvidenceStateError:
                    continue
                identities[candidate_listing.id] = candidate_identity
                candidate_price, candidate_conflict = await self.repository.exact_price(
                    listing_id=candidate_listing.id,
                    asset_id=asset.id,
                    source=candidate_identity.provider,
                    provider_symbol=candidate_identity.provider_symbol,
                    currency=candidate_identity.price_currency,
                )
                if candidate_listing.id == listing.id:
                    identity, price, conflicting_price = (
                        candidate_identity,
                        candidate_price,
                        candidate_conflict,
                    )
                health = health_by_identity.get((candidate_listing.id, candidate_identity.provider))
                if health is not None and health.provider_symbol not in (
                    None,
                    candidate_identity.provider_symbol,
                ):
                    if candidate_listing.id == listing.id:
                        price, conflicting_price = None, True
                    continue
                fresh = (
                    _price_freshness(
                        price=candidate_price,
                        listing=candidate_listing,
                        asset_type=asset.asset_type.value,
                        as_of=as_of,
                    )
                    == "fresh"
                )
                if fresh and candidate_price is not None:
                    prices[candidate_listing.id] = candidate_price
                candidates.append(
                    ListingSelectionCandidate(
                        listing_id=candidate_listing.id,
                        asset_id=candidate_listing.asset_id,
                        asset_type=asset.asset_type,
                        currency=candidate_identity.price_currency,
                        provider=candidate_identity.provider,
                        provider_symbol=candidate_identity.provider_symbol,
                        mic=candidate_listing.mic,
                        base_priority=candidate_listing.base_priority or 0,
                        health=health.state
                        if health is not None
                        else MarketDataHealthState.unknown,
                        retry_after=health.retry_after if health is not None else None,
                        provider_retry_after=provider_retry_after.get(candidate_identity.provider),
                        price_available=fresh,
                        acquisition_eligible=False,
                    )
                )
            if holding.currency == listing.currency and holding.asset_type is asset.asset_type:
                try:
                    selection = select_listing(
                        requested_listing_id=listing.id,
                        asset_id=asset.id,
                        asset_type=asset.asset_type,
                        valuation_currency=holding.currency,
                        through=as_of,
                        now=as_of,
                        candidates=tuple(candidates),
                    )
                except ListingSelectionError:
                    pass
        requested_identity = identity
        if selection is not None:
            selected_listing = listings[selection.selected_listing_id]
            identity = identities[selection.selected_listing_id]
            price = prices[selection.selected_listing_id]
            conflicting_price = False
        freshness_listing = selected_listing if selected_listing is not None else listing
        price_freshness: Literal["fresh", "stale", "unavailable"] = (
            _price_freshness(
                price=price,
                listing=freshness_listing,
                asset_type=holding.asset_type.value,
                as_of=as_of,
            )
            if freshness_listing is not None
            else "unavailable"
        )
        return SymbolPositionResponse(
            id=holding.id,
            account_id=holding.account_id,
            account_name=account_name,
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
            asset_name=asset.name if asset is not None else None,
            asset_isin=asset.isin if asset is not None else None,
            listing_symbol=listing.symbol if listing is not None else None,
            listing_exchange=listing.exchange if listing is not None else None,
            listing_mic=listing.mic if listing is not None else None,
            listing_currency=listing.currency if listing is not None else None,
            listing_base_priority=listing.base_priority if listing is not None else None,
            requested_listing_id=holding.listing_id,
            selected_listing_id=selection.selected_listing_id if selection is not None else None,
            selection_reason=selection.reason.value if selection is not None else None,
            fallback_reason=(
                selection.fallback_reason.value
                if selection is not None and selection.fallback_reason is not None
                else None
            ),
            selected_base_priority=selection.base_priority if selection is not None else None,
            selected_health=selection.health.value if selection is not None else None,
            selected_provider=selection.provider.value if selection is not None else None,
            selected_provider_symbol=selection.provider_symbol if selection is not None else None,
            market_provider=(
                requested_identity.provider.value if requested_identity is not None else None
            ),
            market_provider_symbol=(
                requested_identity.provider_symbol if requested_identity is not None else None
            ),
            price_amount=price.price if price is not None else None,
            price_currency=price.currency if price is not None else None,
            price_timestamp=price.timestamp if price is not None else None,
            price_source=price.source.value if price is not None else None,
            price_provider_symbol=price.provider_symbol if price is not None else None,
            price_snapshot_id=price.id if price is not None else None,
            price_freshness=price_freshness,
            fx_evidence_id=None,
            fx_rate=None,
            converted_value=None,
            trace_status=_trace_status(
                holding=holding,
                listing=listing,
                asset=asset,
                identity=identity,
                price=price,
                conflicting_price=conflicting_price,
                as_of=as_of,
                selected_listing=selected_listing,
            ),
        )

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
