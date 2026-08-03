"""Deterministic read-only planning of exact market evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountType,
    AssetAliasProvider,
    ExchangeRateSource,
    InvestmentMovementKind,
    PriceSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.modules.market_data.models import (
    ExchangeRateRequirement,
    MarketEvidenceRefreshPlan,
    MarketEvidenceStateError,
    PriceRequirement,
)
from app.modules.market_data.requirements_repository import (
    MarketEvidenceRequirementsRepository,
    PersistedMarketHolding,
)

_INVESTMENT_ACCOUNT_TYPES = {
    AccountType.broker,
    AccountType.exchange,
    AccountType.crypto_wallet,
}


@dataclass(frozen=True, slots=True)
class BuildMarketEvidenceRefreshPlanCommand:
    user_id: str
    snapshot_timestamp: datetime


class _Repository(Protocol):
    async def load_user(self, user_id: str) -> UserModel | None: ...

    async def load_active_accounts(self, user_id: str) -> tuple[AccountModel, ...]: ...

    async def load_holdings(
        self,
        account_ids: tuple[str, ...],
    ) -> tuple[PersistedMarketHolding, ...]: ...

    async def load_transactions(
        self,
        account_ids: tuple[str, ...],
        *,
        through: datetime,
    ) -> tuple[TransactionModel, ...]: ...

    async def load_events(
        self,
        account_ids: tuple[str, ...],
        *,
        through: datetime,
    ) -> tuple[InvestmentEventModel, ...]: ...

    async def load_movements(
        self,
        account_ids: tuple[str, ...],
        *,
        through: datetime,
    ) -> tuple[InvestmentMovementModel, ...]: ...

    async def load_liability_balances(
        self,
        account_ids: tuple[str, ...],
        *,
        through: datetime,
    ) -> tuple[LiabilityBalanceModel, ...]: ...


def _fail() -> MarketEvidenceStateError:
    return MarketEvidenceStateError()


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _fail()
    return value


def _currency(value: object) -> str:
    result = _nonblank(value)
    if len(result) != 3 or result != result.upper() or not result.isascii() or not result.isalpha():
        raise _fail()
    return result


def _timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or value.microsecond % 1_000 != 0
    ):
        raise _fail()
    return value


def _finite_decimal(value: object) -> Decimal:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise _fail()
    return value


def _alias_price_source(provider: AssetAliasProvider) -> PriceSource:
    try:
        return PriceSource(provider.value)
    except ValueError as exc:
        raise _fail() from exc


def _price_identity(
    persisted: PersistedMarketHolding,
    *,
    supported_sources: frozenset[PriceSource],
) -> tuple[PriceSource, str]:
    listing = persisted.listing
    asset = persisted.asset
    if not isinstance(listing, AssetListingModel) or not isinstance(asset, AssetModel):
        raise _fail()
    if listing.provider in supported_sources:
        if listing.provider is None:
            raise _fail()
        return listing.provider, _nonblank(listing.provider_symbol)

    aliases: list[tuple[PriceSource, str]] = []
    for alias in persisted.aliases:
        if (
            not isinstance(alias, AssetAliasModel)
            or alias.asset_id != asset.id
            or not isinstance(alias.provider, AssetAliasProvider)
        ):
            raise _fail()
        source = _alias_price_source(alias.provider)
        if source in supported_sources:
            aliases.append((source, _nonblank(alias.external_id)))
    if len(aliases) != 1:
        raise _fail()
    return aliases[0]


def _price_requirements(
    rows: tuple[PersistedMarketHolding, ...],
    *,
    accounts: dict[str, AccountModel],
    supported_sources: frozenset[PriceSource],
    through: datetime,
) -> tuple[PriceRequirement, ...]:
    by_identity: dict[tuple[str, PriceSource, datetime], PriceRequirement] = {}
    holding_ids: set[str] = set()
    for persisted in rows:
        holding = persisted.holding
        listing = persisted.listing
        asset = persisted.asset
        if not isinstance(holding, HoldingModel):
            raise _fail()
        holding_id = _nonblank(holding.id)
        account = accounts.get(holding.account_id)
        if holding_id in holding_ids or account is None:
            raise _fail()
        holding_ids.add(holding_id)
        quantity = _finite_decimal(holding.quantity)
        if account.type not in _INVESTMENT_ACCOUNT_TYPES:
            raise _fail()
        if quantity == 0:
            continue
        if (
            not isinstance(listing, AssetListingModel)
            or not isinstance(asset, AssetModel)
            or holding.asset_id != asset.id
            or holding.listing_id != listing.id
            or listing.asset_id != asset.id
        ):
            raise _fail()
        provider, symbol = _price_identity(
            persisted,
            supported_sources=supported_sources,
        )
        requirement = PriceRequirement(
            account_id=holding.account_id,
            asset_id=_nonblank(asset.id),
            listing_id=_nonblank(listing.id),
            listing_currency=_currency(listing.currency),
            provider=provider,
            provider_symbol=symbol,
            through=through,
        )
        key = (requirement.listing_id, requirement.provider, requirement.through)
        existing = by_identity.get(key)
        if existing is None or requirement.account_id < existing.account_id:
            by_identity[key] = requirement
        elif (
            requirement.asset_id != existing.asset_id
            or requirement.listing_currency != existing.listing_currency
            or requirement.provider_symbol != existing.provider_symbol
        ):
            raise _fail()
    return tuple(
        sorted(
            by_identity.values(),
            key=lambda item: (
                item.account_id,
                item.asset_id,
                item.listing_id,
                item.provider.value,
                item.provider_symbol,
            ),
        )
    )


def _add_fx_requirement(
    requirements: dict[
        tuple[str, str, datetime, ExchangeRateSource],
        ExchangeRateRequirement,
    ],
    *,
    from_currency: object,
    to_currency: str,
    through: object,
    provider: ExchangeRateSource | None,
) -> None:
    source_currency = _currency(from_currency)
    timestamp = _timestamp(through)
    if source_currency == to_currency:
        return
    if provider is None or provider is ExchangeRateSource.manual:
        raise _fail()
    requirement = ExchangeRateRequirement(
        from_currency=source_currency,
        to_currency=to_currency,
        through=timestamp,
        provider=provider,
    )
    requirements[
        (
            requirement.from_currency,
            requirement.to_currency,
            requirement.through,
            requirement.provider,
        )
    ] = requirement


class MarketEvidenceRequirementsPlanner:
    """Build an immutable plan without I/O beyond repository reads."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        price_sources: frozenset[PriceSource],
        fx_source: ExchangeRateSource | None,
        repository: _Repository | None = None,
    ) -> None:
        if PriceSource.manual in price_sources or fx_source is ExchangeRateSource.manual:
            raise _fail()
        self.session = session
        self.price_sources = price_sources
        self.fx_source = fx_source
        self.repository = repository or MarketEvidenceRequirementsRepository(session)

    async def build(
        self,
        command: BuildMarketEvidenceRefreshPlanCommand,
    ) -> MarketEvidenceRefreshPlan:
        if not isinstance(command, BuildMarketEvidenceRefreshPlanCommand):
            raise _fail()
        user_id = _nonblank(command.user_id)
        snapshot_timestamp = _timestamp(command.snapshot_timestamp)
        user = await self.repository.load_user(user_id)
        if not isinstance(user, UserModel) or _nonblank(user.id) != user_id:
            raise _fail()
        output_currency = _currency(user.base_currency)
        loaded_accounts = await self.repository.load_active_accounts(user_id)
        accounts: dict[str, AccountModel] = {}
        for account in loaded_accounts:
            if (
                not isinstance(account, AccountModel)
                or account.id in accounts
                or account.is_archived is not False
                or account.archived_at is not None
                or not isinstance(account.type, AccountType)
            ):
                raise _fail()
            _currency(account.currency)
            accounts[_nonblank(account.id)] = account
        account_ids = tuple(sorted(accounts))
        holdings = await self.repository.load_holdings(account_ids)
        transactions = await self.repository.load_transactions(
            account_ids,
            through=snapshot_timestamp,
        )
        events = await self.repository.load_events(
            account_ids,
            through=snapshot_timestamp,
        )
        movements = await self.repository.load_movements(
            account_ids,
            through=snapshot_timestamp,
        )
        liability_balances = await self.repository.load_liability_balances(
            account_ids,
            through=snapshot_timestamp,
        )
        prices = _price_requirements(
            holdings,
            accounts=accounts,
            supported_sources=self.price_sources,
            through=snapshot_timestamp,
        )

        fx: dict[
            tuple[str, str, datetime, ExchangeRateSource],
            ExchangeRateRequirement,
        ] = {}
        for account in accounts.values():
            _add_fx_requirement(
                fx,
                from_currency=account.currency,
                to_currency=output_currency,
                through=snapshot_timestamp,
                provider=self.fx_source,
            )
        for price in prices:
            _add_fx_requirement(
                fx,
                from_currency=price.listing_currency,
                to_currency=output_currency,
                through=snapshot_timestamp,
                provider=self.fx_source,
            )
        for persisted in holdings:
            if _finite_decimal(persisted.holding.quantity) == 0:
                continue
            _add_fx_requirement(
                fx,
                from_currency=persisted.holding.currency,
                to_currency=output_currency,
                through=snapshot_timestamp,
                provider=self.fx_source,
            )
        liability_ids: set[str] = set()
        for liability in liability_balances:
            liability_id = _nonblank(liability.id)
            if (
                liability_id in liability_ids
                or liability.account_id not in accounts
                or _timestamp(liability.effective_at) > snapshot_timestamp
            ):
                raise _fail()
            liability_ids.add(liability_id)
            _add_fx_requirement(
                fx,
                from_currency=liability.currency,
                to_currency=output_currency,
                through=snapshot_timestamp,
                provider=self.fx_source,
            )

        event_by_id: dict[str, InvestmentEventModel] = {}
        for persisted_event in events:
            event_id = _nonblank(persisted_event.id)
            if (
                event_id in event_by_id
                or persisted_event.account_id not in accounts
                or _timestamp(persisted_event.date) > snapshot_timestamp
            ):
                raise _fail()
            event_by_id[event_id] = persisted_event
            if (persisted_event.realized_pnl is None) != (
                persisted_event.realized_pnl_currency is None
            ):
                raise _fail()
            if persisted_event.realized_pnl_currency is not None:
                _add_fx_requirement(
                    fx,
                    from_currency=persisted_event.realized_pnl_currency,
                    to_currency=output_currency,
                    through=persisted_event.date,
                    provider=self.fx_source,
                )
        movement_ids: set[str] = set()
        for movement in movements:
            movement_id = _nonblank(movement.id)
            movement_event = event_by_id.get(movement.event_id)
            if (
                movement_id in movement_ids
                or movement_event is None
                or movement.account_id not in accounts
                or not isinstance(movement.kind, InvestmentMovementKind)
            ):
                raise _fail()
            movement_ids.add(movement_id)
            if movement.kind is not InvestmentMovementKind.asset:
                _add_fx_requirement(
                    fx,
                    from_currency=movement.currency,
                    to_currency=output_currency,
                    through=movement_event.date,
                    provider=self.fx_source,
                )
                _add_fx_requirement(
                    fx,
                    from_currency=movement.currency,
                    to_currency=output_currency,
                    through=snapshot_timestamp,
                    provider=self.fx_source,
                )
            if movement.value_currency is not None:
                _add_fx_requirement(
                    fx,
                    from_currency=movement.value_currency,
                    to_currency=output_currency,
                    through=movement_event.date,
                    provider=self.fx_source,
                )
        transaction_ids: set[str] = set()
        for transaction in transactions:
            transaction_id = _nonblank(transaction.id)
            if transaction_id in transaction_ids or transaction.account_id not in accounts:
                raise _fail()
            transaction_ids.add(transaction_id)
            _add_fx_requirement(
                fx,
                from_currency=transaction.currency,
                to_currency=output_currency,
                through=transaction.date,
                provider=self.fx_source,
            )
            _add_fx_requirement(
                fx,
                from_currency=transaction.currency,
                to_currency=output_currency,
                through=snapshot_timestamp,
                provider=self.fx_source,
            )
            if transaction.reporting_currency is not None:
                _add_fx_requirement(
                    fx,
                    from_currency=transaction.reporting_currency,
                    to_currency=output_currency,
                    through=transaction.date,
                    provider=self.fx_source,
                )

        fx_requirements = tuple(
            sorted(
                fx.values(),
                key=lambda item: (
                    item.from_currency,
                    item.to_currency,
                    item.through,
                    item.provider.value,
                ),
            )
        )
        return MarketEvidenceRefreshPlan(
            user_id=user_id,
            output_currency=output_currency,
            snapshot_timestamp=snapshot_timestamp,
            price_requirements=prices,
            fx_requirements=fx_requirements,
        )
