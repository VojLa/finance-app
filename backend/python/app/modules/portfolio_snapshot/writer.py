"""Persist generation-bound investment-account and portfolio projections."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_FLOOR, Decimal
from uuid import UUID, uuid5

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.canonical_lineage import (
    SnapshotGenerationModel,
    SnapshotGenerationTargetModel,
)
from app.db.models.enums import AccountType, SnapshotGranularity, SnapshotSource
from app.db.models.investment_snapshots import (
    InvestmentAccountSnapshotItemModel,
    InvestmentAccountSnapshotModel,
    PortfolioSnapshotInputModel,
    PortfolioSnapshotItemAccountModel,
    PortfolioSnapshotItemModel,
    PortfolioSnapshotModel,
)
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.modules.net_worth.evidence_service import (
    SelectedAccountSnapshotIdentity,
    validate_required_account_snapshot_identities,
)

_STATE_MESSAGE = "Investment portfolio snapshot could not be persisted."
_INVESTMENT_TYPES = {AccountType.broker, AccountType.exchange, AccountType.crypto_wallet}
_INVESTMENT_NAMESPACE = UUID("ee68a3f5-a6aa-5d34-b932-a5e5d263e5e5")
_INVESTMENT_ITEM_NAMESPACE = UUID("1209005c-c4a8-59a8-bda4-af6099a44688")
_PORTFOLIO_NAMESPACE = UUID("72eb899d-d7e2-5324-be53-5ba986a1e3f3")
_PORTFOLIO_ITEM_NAMESPACE = UUID("b9169441-ae10-5715-997a-fb1c8026a914")


class PortfolioSnapshotWriteError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(_STATE_MESSAGE)


@dataclass(frozen=True, slots=True)
class WritePortfolioSnapshotCommand:
    user_id: str
    generation_id: str
    timestamp: datetime
    granularity: SnapshotGranularity
    source: SnapshotSource
    currency: str
    calculation_version: int
    calculated_at: datetime
    created_at: datetime
    required_account_snapshot_identities: tuple[SelectedAccountSnapshotIdentity, ...]


@dataclass(frozen=True, slots=True)
class PortfolioSnapshotWriteResult:
    portfolio_snapshot_id: str
    generation_id: str
    user_id: str
    investment_account_snapshot_ids: tuple[str, ...]
    position_count: int


def _fail() -> PortfolioSnapshotWriteError:
    return PortfolioSnapshotWriteError()


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "\0" in value:
        raise _fail()
    return value


def _currency(value: object) -> str:
    result = _text(value)
    if len(result) != 3 or not result.isascii() or not result.isalpha() or result != result.upper():
        raise _fail()
    return result


def _breakdown_sum(values: tuple[dict[str, object] | None, ...]) -> dict[str, str] | None:
    if any(value is None for value in values):
        return None
    totals: dict[str, Decimal] = {}
    try:
        for value in values:
            assert value is not None
            for currency, amount in value.items():
                canonical_currency = _currency(currency)
                parsed = Decimal(str(amount))
                if not parsed.is_finite():
                    raise _fail()
                totals[canonical_currency] = totals.get(canonical_currency, Decimal(0)) + parsed
    except (ArithmeticError, AttributeError, ValueError, TypeError) as exc:
        raise _fail() from exc
    return {currency: format(amount, "f") for currency, amount in sorted(totals.items())}


def _optional_sum(values: tuple[Decimal | None, ...]) -> Decimal | None:
    if any(value is None for value in values):
        return None
    return sum((value for value in values if value is not None), Decimal(0))


def _allocations(values: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
    if not values:
        return ()
    total = sum(values, Decimal(0))
    if total <= 0:
        raise _fail()
    quantum = Decimal("0.0001")
    exact = tuple(value / total * Decimal(100) for value in values)
    floors = tuple(value.quantize(quantum, rounding=ROUND_FLOOR) for value in exact)
    units = int((Decimal("100.0000") - sum(floors, Decimal(0))) / quantum)
    order = sorted(range(len(values)), key=lambda index: (-(exact[index] - floors[index]), index))
    recipients = set(order[:units])
    return tuple(
        value + (quantum if index in recipients else Decimal(0))
        for index, value in enumerate(floors)
    )


def _position_evidence(
    items: tuple[InvestmentAccountSnapshotItemModel, ...],
) -> InvestmentAccountSnapshotItemModel:
    if not items:
        raise _fail()
    first = items[0]
    for item in items[1:]:
        if (
            item.asset_id != first.asset_id
            or item.symbol != first.symbol
            or item.price_per_unit != first.price_per_unit
            or item.price_currency != first.price_currency
            or item.price_source != first.price_source
            or item.price_timestamp != first.price_timestamp
        ):
            raise _fail()
    return first


def valuation_evidence_timestamp(
    price_timestamps: tuple[datetime, ...],
    exchange_rates: object,
    calculated_at: datetime,
) -> datetime:
    """Oldest live market evidence consumed by one immutable snapshot."""

    timestamps = list(price_timestamps)
    if isinstance(exchange_rates, dict):
        rates = exchange_rates.get("snapshotRates", [])
        if not isinstance(rates, list):
            raise _fail()
        for rate in rates:
            if not isinstance(rate, dict) or not isinstance(rate.get("timestamp"), str):
                raise _fail()
            try:
                timestamp = datetime.fromisoformat(rate["timestamp"])
            except ValueError as exc:
                raise _fail() from exc
            if timestamp.tzinfo is not None:
                raise _fail()
            timestamps.append(timestamp)
    return min(timestamps, default=calculated_at)


def _retry_result(
    existing: PortfolioSnapshotModel,
    command: WritePortfolioSnapshotCommand,
    *,
    portfolio_id: str,
    user_id: str,
    generation_id: str,
    currency: str,
    investment_rows: list[InvestmentAccountSnapshotModel],
    position_count: int,
) -> PortfolioSnapshotWriteResult:
    if (
        existing.id != portfolio_id
        or existing.user_id != user_id
        or existing.generation_id != generation_id
        or existing.timestamp != command.timestamp
        or existing.granularity is not command.granularity
        or existing.source is not command.source
        or existing.currency != currency
        or existing.valuation_timestamp
        != min((row.valuation_timestamp for row in investment_rows), default=command.calculated_at)
        or existing.calculated_at != command.calculated_at
        or existing.calculation_version != command.calculation_version
    ):
        raise _fail()
    return PortfolioSnapshotWriteResult(
        portfolio_snapshot_id=portfolio_id,
        generation_id=generation_id,
        user_id=user_id,
        investment_account_snapshot_ids=tuple(row.id for row in investment_rows),
        position_count=position_count,
    )


class PortfolioSnapshotWriter:
    """Build a complete per-user investment projection from exact account snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def write(self, command: WritePortfolioSnapshotCommand) -> PortfolioSnapshotWriteResult:
        if self.session.in_transaction():
            raise _fail()
        user_id = _text(command.user_id)
        generation_id = _text(command.generation_id)
        currency = _currency(command.currency)
        try:
            identities = validate_required_account_snapshot_identities(
                command.required_account_snapshot_identities
            )
        except ValueError as exc:
            raise _fail() from exc
        if identities is None:
            raise _fail()
        try:
            async with self.session.begin():
                await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
                generation = await self.session.get(SnapshotGenerationModel, generation_id)
                target = await self.session.get(
                    SnapshotGenerationTargetModel, (generation_id, user_id)
                )
                if (
                    generation is None
                    or (generation.state == "staged" and generation.published_at is not None)
                    or (generation.state == "published" and generation.published_at is None)
                    or generation.state not in {"staged", "published"}
                    or target is None
                ):
                    raise _fail()
                return await self._write(
                    command,
                    user_id=user_id,
                    generation_id=generation_id,
                    currency=currency,
                    identities=identities,
                    allow_create=generation.state == "staged",
                )
        except PortfolioSnapshotWriteError:
            raise
        except SQLAlchemyError as exc:
            raise _fail() from exc

    async def _write(
        self,
        command: WritePortfolioSnapshotCommand,
        *,
        user_id: str,
        generation_id: str,
        currency: str,
        identities: tuple[SelectedAccountSnapshotIdentity, ...],
        allow_create: bool,
    ) -> PortfolioSnapshotWriteResult:
        snapshot_ids = tuple(item.snapshot_id for item in identities)
        snapshots = tuple(
            (
                await self.session.scalars(
                    select(AccountSnapshotModel)
                    .where(AccountSnapshotModel.id.in_(snapshot_ids))
                    .order_by(AccountSnapshotModel.account_id)
                    .with_for_update(read=True)
                )
            ).all()
        )
        by_account = {item.account_id: item for item in snapshots}
        if len(by_account) != len(identities) or tuple(sorted(by_account)) != tuple(
            item.account_id for item in identities
        ):
            raise _fail()
        account_ids = tuple(by_account)
        accounts = tuple(
            (
                await self.session.scalars(
                    select(AccountModel)
                    .join(
                        AccountMemberModel,
                        AccountMemberModel.account_id == AccountModel.id,
                    )
                    .where(
                        AccountMemberModel.user_id == user_id,
                        AccountModel.id.in_(account_ids),
                    )
                    .order_by(AccountModel.id)
                    .with_for_update(read=True)
                )
            ).all()
        )
        account_types = {account.id: account.type for account in accounts}
        if set(account_types) != set(account_ids):
            raise _fail()
        for identity in identities:
            snapshot = by_account[identity.account_id]
            if (
                snapshot.id != identity.snapshot_id
                or snapshot.generation_id != generation_id
                or snapshot.timestamp != command.timestamp
                or snapshot.granularity is not command.granularity
                or snapshot.currency != currency
                or snapshot.calculation_version != command.calculation_version
            ):
                raise _fail()

        investment_accounts = tuple(
            identity
            for identity in identities
            if account_types[identity.account_id] in _INVESTMENT_TYPES
        )
        investment_rows: list[InvestmentAccountSnapshotModel] = []
        investment_items: dict[str, tuple[InvestmentAccountSnapshotItemModel, ...]] = {}
        for identity in investment_accounts:
            source = by_account[identity.account_id]
            source_items = tuple(
                (
                    await self.session.scalars(
                        select(AccountSnapshotItemModel)
                        .where(AccountSnapshotItemModel.snapshot_id == source.id)
                        .order_by(AccountSnapshotItemModel.listing_id)
                    )
                ).all()
            )
            investment_id = str(uuid5(_INVESTMENT_NAMESPACE, f"{generation_id}\0{source.id}"))
            valuation_at = valuation_evidence_timestamp(
                tuple(
                    item.price_timestamp
                    for item in source_items
                    if item.price_timestamp is not None
                ),
                source.exchange_rates,
                source.calculated_at,
            )
            row = InvestmentAccountSnapshotModel(
                id=investment_id,
                account_snapshot_id=source.id,
                account_id=source.account_id,
                generation_id=generation_id,
                timestamp=source.timestamp,
                valuation_timestamp=valuation_at,
                granularity=source.granularity,
                source=source.source,
                currency=source.currency,
                cash_value=source.cash_value,
                investment_value=source.investment_value,
                investment_cost_basis=source.investment_cost_basis,
                net_deposits_value=source.net_deposits_value,
                realized_pnl_value=source.realized_pnl_value,
                unrealized_pnl_value=source.unrealized_pnl_value,
                fees_value=source.fees_value,
                taxes_value=source.taxes_value,
                cash_value_by_currency=source.cash_value_by_currency,
                investment_value_by_currency=source.investment_value_by_currency,
                investment_cost_basis_by_currency=source.investment_cost_basis_by_currency,
                net_deposits_by_currency=source.net_deposits_by_currency,
                realized_pnl_by_currency=source.realized_pnl_by_currency,
                unrealized_pnl_by_currency=source.unrealized_pnl_by_currency,
                fees_by_currency=source.fees_by_currency,
                taxes_by_currency=source.taxes_by_currency,
                price_evidence={"accountSnapshotItemIds": [item.id for item in source_items]},
                exchange_rates=source.exchange_rates,
                calculated_at=source.calculated_at,
                calculation_version=source.calculation_version,
                created_at=command.created_at,
            )
            items = tuple(
                InvestmentAccountSnapshotItemModel(
                    id=str(uuid5(_INVESTMENT_ITEM_NAMESPACE, f"{investment_id}\0{item.id}")),
                    investment_account_snapshot_id=investment_id,
                    generation_id=generation_id,
                    account_id=source.account_id,
                    asset_id=item.asset_id,
                    listing_id=item.listing_id,
                    symbol=item.symbol,
                    quantity=item.quantity,
                    price_per_unit=item.price_per_unit,
                    price_currency=item.price_currency,
                    price_source=item.price_source,
                    price_timestamp=item.price_timestamp,
                    value=item.value,
                    cost_basis=item.cost_basis,
                    allocation_pct=item.allocation_pct,
                    native_value=item.native_value,
                    value_currency=item.value_currency,
                    native_cost_basis=item.native_cost_basis,
                    native_cost_currency=item.native_cost_currency,
                    price_evidence={"accountSnapshotItemId": item.id},
                    created_at=command.created_at,
                )
                for item in source_items
            )
            investment_rows.append(row)
            investment_items[investment_id] = items

        portfolio_id = str(
            uuid5(
                _PORTFOLIO_NAMESPACE,
                "\0".join(
                    (
                        generation_id,
                        user_id,
                        command.timestamp.isoformat(timespec="milliseconds"),
                        currency,
                        command.granularity.value,
                    )
                ),
            )
        )
        grouped: dict[
            str, list[tuple[InvestmentAccountSnapshotModel, InvestmentAccountSnapshotItemModel]]
        ] = {}
        for row in investment_rows:
            for item in investment_items[row.id]:
                grouped.setdefault(item.listing_id, []).append((row, item))
        for contributions in grouped.values():
            _position_evidence(tuple(item for _, item in contributions))

        existing = await self.session.get(
            PortfolioSnapshotModel,
            portfolio_id,
            with_for_update={"read": True},
        )
        if existing is not None:
            return _retry_result(
                existing,
                command,
                portfolio_id=portfolio_id,
                user_id=user_id,
                generation_id=generation_id,
                currency=currency,
                investment_rows=investment_rows,
                position_count=len(grouped),
            )
        if not allow_create:
            raise _fail()

        # These immutable models intentionally expose no ORM relationships.
        # Persist each composite-FK parent layer before adding its children so
        # SQLAlchemy cannot choose an invalid sibling-table insert order.
        for row in investment_rows:
            self.session.add(row)
        await self.session.flush()
        for row in investment_rows:
            self.session.add_all(investment_items[row.id])
        valuation_at = min(
            (row.valuation_timestamp for row in investment_rows),
            default=command.calculated_at,
        )
        portfolio = PortfolioSnapshotModel(
            id=portfolio_id,
            user_id=user_id,
            generation_id=generation_id,
            timestamp=command.timestamp,
            valuation_timestamp=valuation_at,
            granularity=command.granularity,
            source=command.source,
            currency=currency,
            cash_value=sum((row.cash_value for row in investment_rows), Decimal(0)),
            investment_value=sum((row.investment_value for row in investment_rows), Decimal(0)),
            investment_cost_basis=_optional_sum(
                tuple(row.investment_cost_basis for row in investment_rows)
            ),
            net_deposits_value=_optional_sum(
                tuple(row.net_deposits_value for row in investment_rows)
            ),
            realized_pnl_value=_optional_sum(
                tuple(row.realized_pnl_value for row in investment_rows)
            ),
            unrealized_pnl_value=_optional_sum(
                tuple(row.unrealized_pnl_value for row in investment_rows)
            ),
            fees_value=sum((row.fees_value for row in investment_rows), Decimal(0)),
            taxes_value=sum((row.taxes_value for row in investment_rows), Decimal(0)),
            cash_value_by_currency=_breakdown_sum(
                tuple(row.cash_value_by_currency for row in investment_rows)
            ),
            investment_value_by_currency=_breakdown_sum(
                tuple(row.investment_value_by_currency for row in investment_rows)
            ),
            investment_cost_basis_by_currency=_breakdown_sum(
                tuple(row.investment_cost_basis_by_currency for row in investment_rows)
            ),
            net_deposits_by_currency=_breakdown_sum(
                tuple(row.net_deposits_by_currency for row in investment_rows)
            ),
            realized_pnl_by_currency=_breakdown_sum(
                tuple(row.realized_pnl_by_currency for row in investment_rows)
            ),
            unrealized_pnl_by_currency=_breakdown_sum(
                tuple(row.unrealized_pnl_by_currency for row in investment_rows)
            ),
            fees_by_currency=_breakdown_sum(tuple(row.fees_by_currency for row in investment_rows)),
            taxes_by_currency=_breakdown_sum(
                tuple(row.taxes_by_currency for row in investment_rows)
            ),
            price_evidence={"investmentAccountSnapshotIds": [row.id for row in investment_rows]},
            exchange_rates={
                "accountSnapshots": {row.account_id: row.exchange_rates for row in investment_rows}
            },
            calculated_at=command.calculated_at,
            calculation_version=command.calculation_version,
            created_at=command.created_at,
        )
        self.session.add(portfolio)
        # Flush the aggregate parent and investment items before inserting
        # portfolio lineage and position-contribution rows.
        await self.session.flush()
        for row in investment_rows:
            self.session.add(
                PortfolioSnapshotInputModel(
                    portfolio_snapshot_id=portfolio_id,
                    investment_account_snapshot_id=row.id,
                    account_snapshot_id=row.account_snapshot_id,
                    generation_id=generation_id,
                    user_id=user_id,
                    account_id=row.account_id,
                    created_at=command.created_at,
                )
            )

        listing_ids = tuple(sorted(grouped))
        listing_values = tuple(
            sum((item.value for _, item in grouped[listing]), Decimal(0)) for listing in listing_ids
        )
        allocations = _allocations(listing_values)
        item_account_rows: list[PortfolioSnapshotItemAccountModel] = []
        for listing_id, allocation in zip(listing_ids, allocations, strict=True):
            contributions = grouped[listing_id]
            first = _position_evidence(tuple(item for _, item in contributions))
            quantity = sum((item.quantity for _, item in contributions), Decimal(0))
            value = sum((item.value for _, item in contributions), Decimal(0))
            cost_basis = _optional_sum(tuple(item.cost_basis for _, item in contributions))
            native_value = _optional_sum(tuple(item.native_value for _, item in contributions))
            native_cost_basis = _optional_sum(
                tuple(item.native_cost_basis for _, item in contributions)
            )
            value_currencies = {item.value_currency for _, item in contributions}
            cost_currencies = {item.native_cost_currency for _, item in contributions}
            item_id = str(uuid5(_PORTFOLIO_ITEM_NAMESPACE, f"{portfolio_id}\0{listing_id}"))
            self.session.add(
                PortfolioSnapshotItemModel(
                    id=item_id,
                    portfolio_snapshot_id=portfolio_id,
                    generation_id=generation_id,
                    user_id=user_id,
                    asset_id=first.asset_id,
                    listing_id=listing_id,
                    symbol=first.symbol,
                    quantity=quantity,
                    price_per_unit=first.price_per_unit,
                    price_currency=first.price_currency,
                    price_source=first.price_source,
                    price_timestamp=max(
                        (item.price_timestamp for _, item in contributions if item.price_timestamp),
                        default=command.calculated_at,
                    ),
                    value=value,
                    cost_basis=cost_basis,
                    allocation_pct=allocation,
                    native_value=native_value if len(value_currencies) == 1 else None,
                    value_currency=next(iter(value_currencies))
                    if len(value_currencies) == 1
                    else None,
                    native_cost_basis=(native_cost_basis if len(cost_currencies) == 1 else None),
                    native_cost_currency=(
                        next(iter(cost_currencies)) if len(cost_currencies) == 1 else None
                    ),
                    price_evidence={
                        "investmentAccountSnapshotItemIds": [item.id for _, item in contributions]
                    },
                    created_at=command.created_at,
                )
            )
            contribution_allocations = _allocations(tuple(item.value for _, item in contributions))
            for (row, item), contribution_allocation in zip(
                contributions, contribution_allocations, strict=True
            ):
                item_account_rows.append(
                    PortfolioSnapshotItemAccountModel(
                        portfolio_snapshot_item_id=item_id,
                        account_id=row.account_id,
                        portfolio_snapshot_id=portfolio_id,
                        investment_account_snapshot_id=row.id,
                        account_snapshot_id=row.account_snapshot_id,
                        generation_id=generation_id,
                        user_id=user_id,
                        listing_id=listing_id,
                        quantity=item.quantity,
                        value=item.value,
                        cost_basis=item.cost_basis,
                        allocation_pct=contribution_allocation,
                        created_at=command.created_at,
                    )
                )
        # Portfolio item-account rows reference both an input and an aggregate
        # item through composite foreign keys. Persist both parent sets first.
        await self.session.flush()
        self.session.add_all(item_account_rows)
        await self.session.flush()
        return PortfolioSnapshotWriteResult(
            portfolio_snapshot_id=portfolio_id,
            generation_id=generation_id,
            user_id=user_id,
            investment_account_snapshot_ids=tuple(row.id for row in investment_rows),
            position_count=len(grouped),
        )
