"""Deterministic read-only planning of exact market evidence."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountType,
    AssetAliasProvider,
    AssetType,
    ExchangeRateSource,
    InvestmentMovementKind,
    MarketDataFailureReason,
    MarketDataHealthState,
    PriceSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.prices import PriceSnapshotModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.modules.market_data.exchange_calendar import (
    assess_market,
    price_is_acceptable_for_market,
)
from app.modules.market_data.listing_selection import (
    ListingSelectionCandidate,
    ListingSelectionError,
    select_listing,
)
from app.modules.market_data.models import (
    ExchangeRateRequirement,
    MarketEvidenceRefreshPlan,
    MarketEvidenceStateError,
    PriceIdentityFailure,
    PriceRequirement,
)
from app.modules.market_data.policy import (
    DEFAULT_MARKET_EVIDENCE_POLICY,
    MarketEvidencePolicy,
    validate_market_evidence_policy,
)
from app.modules.market_data.requirements_repository import (
    MarketEvidenceRequirementsRepository,
    PersistedMarketHolding,
)
from app.modules.market_data.source_policy import (
    MarketEvidenceSourcePolicy,
    validate_market_evidence_source_policy,
)

logger = logging.getLogger(__name__)

_INVESTMENT_ACCOUNT_TYPES = {
    AccountType.broker,
    AccountType.exchange,
    AccountType.crypto_wallet,
}


@dataclass(frozen=True, slots=True)
class BuildMarketEvidenceRefreshPlanCommand:
    user_id: str
    snapshot_timestamp: datetime


@dataclass(frozen=True, slots=True)
class ResolvedPriceIdentity:
    """Exact persisted provider identity selected by the source policy."""

    provider: PriceSource
    provider_symbol: str
    price_currency: str


class _Repository(Protocol):
    async def load_user(self, user_id: str) -> UserModel | None: ...

    async def load_active_accounts(self, user_id: str) -> tuple[AccountModel, ...]: ...

    async def load_holdings(
        self,
        account_ids: tuple[str, ...],
        *,
        through: datetime,
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


def _holding_cost_currencies(holding: HoldingModel) -> tuple[str, ...]:
    average = holding.avg_buy_price
    value = holding.cost_basis_by_currency
    if average is None and value is None:
        return ()
    if average is None or value is None:
        raise _fail()
    if _finite_decimal(average) <= 0 or not isinstance(value, dict) or not value:
        raise _fail()
    currencies: list[str] = []
    for raw_currency, raw_amount in sorted(value.items()):
        currency = _currency(raw_currency)
        if not isinstance(raw_amount, str):
            raise _fail()
        try:
            amount = Decimal(raw_amount)
        except InvalidOperation as exc:
            raise _fail() from exc
        if (
            not amount.is_finite()
            or amount <= 0
            or amount >= Decimal("1000000000000000000")
            or format(amount, ".10f") != raw_amount
        ):
            raise _fail()
        currencies.append(currency)
    if len(set(currencies)) != len(currencies):
        raise _fail()
    return tuple(currencies)


def _alias_price_source(provider: AssetAliasProvider) -> PriceSource:
    try:
        return PriceSource(provider.value)
    except ValueError as exc:
        raise _fail() from exc


def build_price_requirement(
    *,
    account_id: str,
    listing: AssetListingModel,
    asset: AssetModel,
    aliases: tuple[AssetAliasModel, ...],
    supported_sources: frozenset[PriceSource],
    through: datetime,
    source_policy: MarketEvidenceSourcePolicy | None = None,
    asset_listing_count: int | None = None,
) -> PriceRequirement:
    """Resolve one trusted persisted listing identity without consulting Holdings."""

    identity = resolve_price_identity(
        listing=listing,
        asset=asset,
        aliases=aliases,
        supported_sources=supported_sources,
        source_policy=source_policy,
        asset_listing_count=asset_listing_count,
    )
    return PriceRequirement(
        account_id=_nonblank(account_id),
        asset_id=_nonblank(asset.id),
        listing_id=_nonblank(listing.id),
        listing_currency=identity.price_currency,
        provider=identity.provider,
        provider_symbol=identity.provider_symbol,
        through=_timestamp(through),
        listing_mic=listing.mic,
        asset_type=asset.asset_type,
    )


def resolve_price_identity(
    *,
    listing: AssetListingModel,
    asset: AssetModel,
    aliases: tuple[AssetAliasModel, ...],
    supported_sources: frozenset[PriceSource],
    source_policy: MarketEvidenceSourcePolicy | None = None,
    asset_listing_count: int | None = None,
) -> ResolvedPriceIdentity:
    """Resolve one exact listing/provider identity without inventing a symbol."""

    if not isinstance(listing, AssetListingModel) or not isinstance(asset, AssetModel):
        raise _fail()
    if listing.asset_id != asset.id:
        raise _fail()
    expected_source: PriceSource | None = None
    allowed_sources = supported_sources
    policy: MarketEvidenceSourcePolicy | None = None
    if source_policy is not None:
        policy = validate_market_evidence_source_policy(source_policy)
        if policy.price_sources != supported_sources:
            raise _fail()
        expected_source = policy.price_source_for(asset.asset_type)
        allowed_sources = policy.price_sources_for(asset.asset_type)
    if listing.provider in supported_sources and listing.provider in allowed_sources:
        if listing.provider is None:
            raise _fail()
        provider, symbol = listing.provider, _nonblank(listing.provider_symbol)
    else:
        listing_id = _nonblank(listing.id)
        scoped: list[tuple[PriceSource, str]] = []
        asset_wide: list[tuple[PriceSource, str]] = []
        for alias in aliases:
            if (
                not isinstance(alias, AssetAliasModel)
                or alias.asset_id != asset.id
                or not isinstance(alias.provider, AssetAliasProvider)
            ):
                raise _fail()
            source = _alias_price_source(alias.provider)
            alias_listing_id = alias.listing_id
            if alias_listing_id is not None and (
                not isinstance(alias_listing_id, str) or not alias_listing_id
            ):
                raise _fail()
            if alias_listing_id is not None and alias_listing_id != listing_id:
                continue
            if source in supported_sources and (
                expected_source is None or source is expected_source
            ):
                identity = (source, _nonblank(alias.external_id))
                if alias_listing_id == listing_id:
                    scoped.append(identity)
                elif source is PriceSource.coingecko or asset_listing_count == 1:
                    asset_wide.append(identity)
        identities = scoped if scoped else asset_wide
        if len(identities) != 1:
            raise _fail()
        provider, symbol = identities[0]
    price_currency = _currency(listing.currency)
    if (
        policy is not None
        and policy.mode == "local_free"
        and provider is PriceSource.yahoo_finance
        and asset.asset_type is AssetType.crypto
    ):
        expected_symbol = f"{_nonblank(asset.symbol)}-USD"
        if symbol != expected_symbol:
            raise _fail()
        price_currency = "USD"
    return ResolvedPriceIdentity(
        provider=provider,
        provider_symbol=symbol,
        price_currency=price_currency,
    )


def _missing_provider_symbol_failures(
    rows: tuple[PersistedMarketHolding, ...],
    *,
    supported_sources: frozenset[PriceSource],
    source_policy: MarketEvidenceSourcePolicy | None,
) -> tuple[PriceIdentityFailure, ...]:
    failures: dict[tuple[str, PriceSource], PriceIdentityFailure] = {}
    for persisted in rows:
        if _finite_decimal(persisted.holding.quantity) == 0 or persisted.asset is None:
            continue
        allowed = (
            supported_sources
            if source_policy is None
            else source_policy.price_sources_for(persisted.asset.asset_type)
        )
        for listing in persisted.candidate_listings or (
            (persisted.listing,) if persisted.listing is not None else ()
        ):
            if (
                listing.asset_id != persisted.asset.id
                or listing.provider not in allowed
                or listing.provider_symbol not in (None, "")
            ):
                continue
            provider = listing.provider
            assert provider is not None
            configured_at = listing.updated_at
            if not isinstance(configured_at, datetime) or configured_at.tzinfo is not None:
                raise _fail()
            key = (_nonblank(listing.id), provider)
            failures[key] = PriceIdentityFailure(
                listing_id=key[0],
                provider=provider,
                reason=MarketDataFailureReason.missing_provider_symbol,
                configured_at=configured_at,
            )
    return tuple(sorted(failures.values(), key=lambda item: (item.provider.value, item.listing_id)))


def _price_requirements(
    rows: tuple[PersistedMarketHolding, ...],
    *,
    accounts: dict[str, AccountModel],
    supported_sources: frozenset[PriceSource],
    through: datetime,
    policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
    source_policy: MarketEvidenceSourcePolicy | None = None,
) -> tuple[PriceRequirement, ...]:
    by_identity: dict[tuple[str, PriceSource, datetime], PriceRequirement] = {}
    holding_ids: set[str] = set()
    selection_now = max(datetime.now(UTC).replace(tzinfo=None), through)
    freshness_policy = validate_market_evidence_policy(policy)
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
        listings = persisted.candidate_listings or (listing,)
        aliases = persisted.candidate_aliases or persisted.aliases
        health_by_identity = {
            (row.listing_id, row.provider): row for row in persisted.candidate_health
        }
        if len(health_by_identity) != len(persisted.candidate_health):
            raise _fail()
        provider_retry_after = dict(persisted.provider_retry_after)
        if len(provider_retry_after) != len(persisted.provider_retry_after):
            raise _fail()
        candidates: list[ListingSelectionCandidate] = []
        listing_by_id: dict[str, AssetListingModel] = {}
        for candidate_listing in listings:
            if not isinstance(candidate_listing, AssetListingModel):
                raise _fail()
            candidate_id = _nonblank(candidate_listing.id)
            if candidate_id in listing_by_id:
                raise _fail()
            listing_by_id[candidate_id] = candidate_listing
            if candidate_listing.asset_id != asset.id:
                continue
            try:
                identity = resolve_price_identity(
                    listing=candidate_listing,
                    asset=asset,
                    aliases=tuple(
                        alias
                        for alias in aliases
                        if alias.listing_id is None or alias.listing_id == candidate_id
                    ),
                    supported_sources=supported_sources,
                    source_policy=source_policy,
                    asset_listing_count=persisted.asset_listing_count,
                )
                native_currency = _currency(identity.price_currency)
            except MarketEvidenceStateError:
                continue
            health = health_by_identity.get((candidate_id, identity.provider))
            if (
                health is not None
                and health.provider_symbol is not None
                and health.provider_symbol != identity.provider_symbol
            ):
                continue
            lease_active = (
                health is not None
                and health.lease_expires_at is not None
                and health.lease_expires_at > selection_now
            )
            matching_prices = tuple(
                price
                for price in persisted.candidate_prices
                if isinstance(price, PriceSnapshotModel)
                and price.asset_id == asset.id
                and price.listing_id == candidate_id
                and price.source is identity.provider
                and price.provider_symbol == identity.provider_symbol
                and price.currency == native_currency
                and price.timestamp <= through
                and price.price > 0
            )
            latest_timestamp = max((price.timestamp for price in matching_prices), default=None)
            latest_prices = tuple(
                price for price in matching_prices if price.timestamp == latest_timestamp
            )
            price_available = len(latest_prices) == 1 and price_is_acceptable_for_market(
                mic=candidate_listing.mic,
                asset_type=asset.asset_type.value,
                observed_at=latest_prices[0].timestamp,
                through=through,
                maximum_age=freshness_policy.maximum_price_age,
            )
            candidates.append(
                ListingSelectionCandidate(
                    listing_id=candidate_id,
                    asset_id=candidate_listing.asset_id,
                    asset_type=asset.asset_type,
                    currency=native_currency,
                    provider=identity.provider,
                    provider_symbol=identity.provider_symbol,
                    mic=candidate_listing.mic,
                    base_priority=candidate_listing.base_priority or 0,
                    health=health.state if health is not None else MarketDataHealthState.unknown,
                    last_failure_reason=(
                        health.last_failure_reason if health is not None else None
                    ),
                    retry_after=health.retry_after if health is not None else None,
                    provider_retry_after=provider_retry_after.get(identity.provider),
                    price_available=price_available,
                    acquisition_eligible=not lease_active,
                    acquisition_probe=True,
                )
            )
        if listing.id not in listing_by_id:
            raise _fail()
        allowed_sources = (
            supported_sources
            if source_policy is None
            else source_policy.price_sources_for(asset.asset_type)
        )
        if not candidates and any(
            candidate.provider in allowed_sources and candidate.provider_symbol in (None, "")
            for candidate in listings
        ):
            continue
        try:
            selection = select_listing(
                requested_listing_id=listing.id,
                asset_id=asset.id,
                asset_type=asset.asset_type,
                valuation_currency=_currency(listing.currency),
                through=through,
                now=selection_now,
                candidates=tuple(candidates),
            )
        except ListingSelectionError as exc:
            raise _fail() from exc
        if selection.fallback_reason is not None:
            logger.info(
                "market_data_listing_fallback",
                extra={
                    "provider": selection.provider.value,
                    "selection_reason": selection.reason.value,
                    "fallback_reason": selection.fallback_reason.value,
                },
            )
        selected_listing = listing_by_id[selection.selected_listing_id]
        selected_candidate = next(
            item for item in candidates if item.listing_id == selection.selected_listing_id
        )
        calendar = assess_market(
            selected_listing.mic,
            through.replace(tzinfo=UTC),
            asset_type=asset.asset_type.value,
        )
        if selected_candidate.price_available and calendar.status in {
            "closed",
            "weekend",
            "holiday",
        }:
            continue
        selected_aliases = tuple(
            alias
            for alias in aliases
            if alias.listing_id is None or alias.listing_id == selected_listing.id
        )
        selected_requirement = build_price_requirement(
            account_id=holding.account_id,
            listing=selected_listing,
            asset=asset,
            aliases=selected_aliases,
            supported_sources=supported_sources,
            through=through,
            source_policy=source_policy,
            asset_listing_count=persisted.asset_listing_count,
        )
        requirement = replace(
            selected_requirement,
            listing_currency=next(
                item.currency
                for item in candidates
                if item.listing_id == selection.selected_listing_id
            ),
            provider=selection.provider,
            provider_symbol=selection.provider_symbol,
            listing_mic=selected_listing.mic,
            requested_listing_id=selection.requested_listing_id,
            selection_reason=selection.reason.value,
            fallback_reason=(
                selection.fallback_reason.value if selection.fallback_reason is not None else None
            ),
            selected_base_priority=selection.base_priority,
            selected_health=selection.health.value,
        )
        key = (requirement.listing_id, requirement.provider, requirement.through)
        existing = by_identity.get(key)
        if existing is not None and (
            requirement.asset_id != existing.asset_id
            or requirement.listing_currency != existing.listing_currency
            or requirement.provider_symbol != existing.provider_symbol
            or requirement.listing_mic != existing.listing_mic
            or requirement.asset_type != existing.asset_type
        ):
            raise _fail()
        if existing is None or (
            requirement.account_id,
            requirement.requested_listing_id or "",
        ) < (
            existing.account_id,
            existing.requested_listing_id or "",
        ):
            by_identity[key] = requirement
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


def _add_conversion_requirements(
    requirements: dict[
        tuple[str, str, datetime, ExchangeRateSource],
        ExchangeRateRequirement,
    ],
    *,
    source_currency: str,
    target_currency: str,
    through: datetime,
    provider: ExchangeRateSource | None,
) -> None:
    source = _currency(source_currency)
    target = _currency(target_currency)
    if source == target:
        return
    _add_fx_requirement(
        requirements,
        from_currency=source,
        to_currency=target,
        through=through,
        provider=provider,
    )


def _add_account_conversion_requirements(
    requirements: dict[
        tuple[str, str, datetime, ExchangeRateSource],
        ExchangeRateRequirement,
    ],
    *,
    source_currency: str,
    account: AccountModel,
    output_currency: str,
    through: datetime,
    provider: ExchangeRateSource | None,
) -> None:
    for target_currency in {output_currency, _currency(account.currency)}:
        _add_conversion_requirements(
            requirements,
            source_currency=source_currency,
            target_currency=target_currency,
            through=through,
            provider=provider,
        )


class MarketEvidenceRequirementsPlanner:
    """Build an immutable plan without I/O beyond repository reads."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        price_sources: frozenset[PriceSource],
        fx_source: ExchangeRateSource | None,
        policy: MarketEvidencePolicy = DEFAULT_MARKET_EVIDENCE_POLICY,
        repository: _Repository | None = None,
        source_policy: MarketEvidenceSourcePolicy | None = None,
    ) -> None:
        if PriceSource.manual in price_sources or fx_source is ExchangeRateSource.manual:
            raise _fail()
        self.session = session
        self.price_sources = price_sources
        self.fx_source = fx_source
        self.policy = validate_market_evidence_policy(policy)
        if source_policy is not None:
            source_contract = validate_market_evidence_source_policy(source_policy)
            if (
                source_contract.price_sources != price_sources
                or source_contract.fx_source is not fx_source
            ):
                raise _fail()
        self.source_policy = source_policy
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
        holdings = await self.repository.load_holdings(
            account_ids,
            through=snapshot_timestamp,
        )
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
            policy=self.policy,
            source_policy=self.source_policy,
        )
        identity_failures = _missing_provider_symbol_failures(
            holdings,
            supported_sources=self.price_sources,
            source_policy=self.source_policy,
        )

        fx: dict[
            tuple[str, str, datetime, ExchangeRateSource],
            ExchangeRateRequirement,
        ] = {}
        for account in accounts.values():
            _add_conversion_requirements(
                fx,
                source_currency=account.currency,
                target_currency=output_currency,
                through=snapshot_timestamp,
                provider=self.fx_source,
            )
        for price in prices:
            _add_account_conversion_requirements(
                fx,
                source_currency=price.listing_currency,
                account=accounts[price.account_id],
                output_currency=output_currency,
                through=snapshot_timestamp,
                provider=self.fx_source,
            )
        for persisted in holdings:
            if _finite_decimal(persisted.holding.quantity) == 0:
                continue
            if persisted.listing is None:
                raise _fail()
            _add_account_conversion_requirements(
                fx,
                source_currency=persisted.listing.currency,
                account=accounts[persisted.holding.account_id],
                output_currency=output_currency,
                through=snapshot_timestamp,
                provider=self.fx_source,
            )
            for source_currency in _holding_cost_currencies(persisted.holding):
                _add_account_conversion_requirements(
                    fx,
                    source_currency=source_currency,
                    account=accounts[persisted.holding.account_id],
                    output_currency=output_currency,
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
            _add_account_conversion_requirements(
                fx,
                source_currency=liability.currency,
                account=accounts[liability.account_id],
                output_currency=output_currency,
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
                _add_account_conversion_requirements(
                    fx,
                    source_currency=persisted_event.realized_pnl_currency,
                    account=accounts[persisted_event.account_id],
                    output_currency=output_currency,
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
            movement_account = accounts[movement.account_id]
            if movement.kind is not InvestmentMovementKind.asset:
                _add_account_conversion_requirements(
                    fx,
                    source_currency=movement.currency,
                    account=movement_account,
                    output_currency=output_currency,
                    through=movement_event.date,
                    provider=self.fx_source,
                )
                _add_account_conversion_requirements(
                    fx,
                    source_currency=movement.currency,
                    account=movement_account,
                    output_currency=output_currency,
                    through=snapshot_timestamp,
                    provider=self.fx_source,
                )
            if movement.value_currency is not None:
                _add_account_conversion_requirements(
                    fx,
                    source_currency=movement.value_currency,
                    account=movement_account,
                    output_currency=output_currency,
                    through=movement_event.date,
                    provider=self.fx_source,
                )
        transaction_ids: set[str] = set()
        for transaction in transactions:
            transaction_id = _nonblank(transaction.id)
            if transaction_id in transaction_ids or transaction.account_id not in accounts:
                raise _fail()
            transaction_ids.add(transaction_id)
            transaction_account = accounts[transaction.account_id]
            _add_account_conversion_requirements(
                fx,
                source_currency=transaction.currency,
                account=transaction_account,
                output_currency=output_currency,
                through=transaction.date,
                provider=self.fx_source,
            )
            _add_account_conversion_requirements(
                fx,
                source_currency=transaction.currency,
                account=transaction_account,
                output_currency=output_currency,
                through=snapshot_timestamp,
                provider=self.fx_source,
            )
            if transaction.reporting_currency is not None:
                _add_account_conversion_requirements(
                    fx,
                    source_currency=transaction.reporting_currency,
                    account=transaction_account,
                    output_currency=output_currency,
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
            identity_failures=identity_failures,
        )
