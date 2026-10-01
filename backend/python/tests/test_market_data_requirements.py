from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest

from app.config.settings import Settings
from app.db.models.accounts import AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountType,
    AssetAliasProvider,
    AssetType,
    ExchangeRateSource,
    InvestmentEventType,
    InvestmentMovementKind,
    LiabilityBalanceSource,
    MarketDataFailureReason,
    MarketDataHealthState,
    MovementDirection,
    PriceSource,
    TransactionClassification,
    TransactionType,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.market_health import MarketDataListingHealthModel
from app.db.models.prices import PriceSnapshotModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.modules.market_data.models import MarketEvidenceStateError, PriceRequirement
from app.modules.market_data.providers import PriceProviderRegistry
from app.modules.market_data.requirements import (
    BuildMarketEvidenceRefreshPlanCommand,
    MarketEvidenceRequirementsPlanner,
    resolve_price_identity,
)
from app.modules.market_data.requirements_repository import PersistedMarketHolding
from app.modules.market_data.source_policy import (
    LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY,
    MarketEvidenceSourcePolicy,
)
from app.modules.prices.models import PriceObservation
from app.modules.prices.providers import create_production_price_registry

SNAPSHOT_AT = datetime(2026, 8, 3, 12)
EVENT_AT = SNAPSHOT_AT - timedelta(days=3)


class _Repository:
    def __init__(self) -> None:
        self.user: UserModel | None = _user()
        self.accounts: tuple[AccountModel, ...] = (_account(),)
        self.holdings: tuple[PersistedMarketHolding, ...] = (_holding(),)
        self.transactions: tuple[TransactionModel, ...] = ()
        self.events: tuple[InvestmentEventModel, ...] = ()
        self.movements: tuple[InvestmentMovementModel, ...] = ()
        self.liability_balances: tuple[LiabilityBalanceModel, ...] = ()
        self.calls: list[object] = []

    async def load_user(self, user_id: str) -> UserModel | None:
        self.calls.append(("user", user_id))
        return self.user

    async def load_active_accounts(self, user_id: str) -> tuple[AccountModel, ...]:
        self.calls.append(("accounts", user_id))
        return self.accounts

    async def load_holdings(
        self,
        account_ids: tuple[str, ...],
        *,
        through: datetime,
    ) -> tuple[PersistedMarketHolding, ...]:
        self.calls.append(("holdings", account_ids, through))
        return self.holdings

    async def load_transactions(
        self,
        account_ids: tuple[str, ...],
        *,
        through: datetime,
    ) -> tuple[TransactionModel, ...]:
        self.calls.append(("transactions", account_ids, through))
        return self.transactions

    async def load_events(
        self,
        account_ids: tuple[str, ...],
        *,
        through: datetime,
    ) -> tuple[InvestmentEventModel, ...]:
        self.calls.append(("events", account_ids, through))
        return self.events

    async def load_movements(
        self,
        account_ids: tuple[str, ...],
        *,
        through: datetime,
    ) -> tuple[InvestmentMovementModel, ...]:
        self.calls.append(("movements", account_ids, through))
        return self.movements

    async def load_liability_balances(
        self,
        account_ids: tuple[str, ...],
        *,
        through: datetime,
    ) -> tuple[LiabilityBalanceModel, ...]:
        self.calls.append(("liabilities", account_ids, through))
        return self.liability_balances


class _InjectedTwelveDataProvider:
    source = PriceSource.twelve_data

    async def fetch(self, _requirement: PriceRequirement) -> PriceObservation:
        raise AssertionError("Planner tests must not call a provider.")


def _user(*, currency: str = "CZK") -> UserModel:
    return UserModel(
        id="user-1",
        email="owner@example.com",
        name=None,
        password_hash=None,
        base_currency=currency,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
    )


def _account(
    account_id: str = "account-1",
    *,
    currency: str = "EUR",
    account_type: AccountType = AccountType.broker,
) -> AccountModel:
    return AccountModel(
        id=account_id,
        name=account_id,
        type=account_type,
        currency=currency,
        color=None,
        notes=None,
        is_archived=False,
        archived_at=None,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
    )


def _holding(
    suffix: str = "1",
    *,
    account_id: str = "account-1",
    quantity: str = "2",
    cost_currency: str = "USD",
    listing_currency: str = "EUR",
    provider: PriceSource | None = PriceSource.yahoo_finance,
    provider_symbol: str | None = "EXACT",
    aliases: tuple[AssetAliasModel, ...] = (),
    symbol: str = "SAME",
    asset_type: AssetType = AssetType.etf,
    asset_listing_count: int = 1,
) -> PersistedMarketHolding:
    asset = AssetModel(
        id=f"asset-{suffix}",
        symbol=symbol,
        isin=None,
        name="Exact asset",
        asset_type=asset_type,
        currency=listing_currency,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
    )
    listing = AssetListingModel(
        id=f"listing-{suffix}",
        asset_id=asset.id,
        symbol=symbol,
        exchange=f"EX{suffix}",
        mic=None,
        currency=listing_currency,
        country=None,
        provider=provider,
        provider_symbol=provider_symbol,
        is_primary=False,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
    )
    holding = HoldingModel(
        id=f"holding-{suffix}",
        symbol=symbol,
        name="Exact holding",
        asset_type=asset_type,
        quantity=Decimal(quantity),
        avg_buy_price=Decimal("10"),
        currency=listing_currency,
        cost_basis_by_currency={cost_currency: "10.0000000000"},
        current_price=None,
        current_value=None,
        unrealized_pnl=None,
        realized_pnl=None,
        asset_id=asset.id,
        listing_id=listing.id,
        account_id=account_id,
        calculated_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
    )
    return PersistedMarketHolding(holding, listing, asset, aliases, asset_listing_count)


def _alias(
    provider: AssetAliasProvider,
    external_id: str,
    *,
    asset_id: str = "asset-1",
    listing_id: str | None = None,
) -> AssetAliasModel:
    return AssetAliasModel(
        id=f"alias-{provider.value}",
        asset_id=asset_id,
        listing_id=listing_id,
        provider=provider,
        external_id=external_id,
        created_at=SNAPSHOT_AT,
    )


def test_yahoo_aliases_resolve_only_for_their_listing() -> None:
    persisted = _holding(provider=PriceSource.broker, asset_listing_count=2)
    assert persisted.listing is not None and persisted.asset is not None
    other = _alias(AssetAliasProvider.yahoo_finance, "VUAA.DE", listing_id="other-listing")
    matching = _alias(AssetAliasProvider.yahoo_finance, "VUAA.MI", listing_id=persisted.listing.id)
    identity = resolve_price_identity(
        listing=persisted.listing,
        asset=persisted.asset,
        aliases=(other, matching),
        supported_sources=frozenset({PriceSource.yahoo_finance}),
        asset_listing_count=2,
    )
    assert identity.provider_symbol == "VUAA.MI"
    assert identity.price_currency == "EUR"


def test_yahoo_aliases_for_one_listing_must_be_unambiguous() -> None:
    persisted = _holding(provider=PriceSource.broker)
    assert persisted.listing is not None and persisted.asset is not None
    with pytest.raises(MarketEvidenceStateError):
        resolve_price_identity(
            listing=persisted.listing,
            asset=persisted.asset,
            aliases=(
                _alias(AssetAliasProvider.yahoo_finance, "VUAA.MI", listing_id="listing-1"),
                _alias(AssetAliasProvider.yahoo_finance, "VUAA.DE", listing_id="listing-1"),
            ),
            supported_sources=frozenset({PriceSource.yahoo_finance}),
            asset_listing_count=1,
        )


@pytest.mark.parametrize("listing_count", [None, 2])
def test_legacy_yahoo_alias_fails_with_unproven_or_multiple_listings(
    listing_count: int | None,
) -> None:
    persisted = _holding(provider=PriceSource.broker)
    assert persisted.listing is not None and persisted.asset is not None
    with pytest.raises(MarketEvidenceStateError):
        resolve_price_identity(
            listing=persisted.listing,
            asset=persisted.asset,
            aliases=(_alias(AssetAliasProvider.yahoo_finance, "VUAA.MI"),),
            supported_sources=frozenset({PriceSource.yahoo_finance}),
            asset_listing_count=listing_count,
        )


def test_legacy_yahoo_alias_resolves_for_proven_single_listing() -> None:
    persisted = _holding(provider=PriceSource.broker)
    assert persisted.listing is not None and persisted.asset is not None
    identity = resolve_price_identity(
        listing=persisted.listing,
        asset=persisted.asset,
        aliases=(_alias(AssetAliasProvider.yahoo_finance, "VUAA.MI"),),
        supported_sources=frozenset({PriceSource.yahoo_finance}),
        asset_listing_count=1,
    )
    assert identity.provider_symbol == "VUAA.MI"


def test_asset_scoped_twelve_data_alias_fails_for_multiple_listings() -> None:
    persisted = _holding(provider=PriceSource.broker, asset_listing_count=2)
    assert persisted.listing is not None and persisted.asset is not None
    with pytest.raises(MarketEvidenceStateError):
        resolve_price_identity(
            listing=persisted.listing,
            asset=persisted.asset,
            aliases=(
                _alias(
                    AssetAliasProvider.twelve_data,
                    '{"symbol":"VUAA","mic_code":"XMIL"}',
                ),
            ),
            supported_sources=frozenset({PriceSource.twelve_data}),
            asset_listing_count=2,
        )


def _event() -> InvestmentEventModel:
    return InvestmentEventModel(
        id="event-1",
        account_id="account-1",
        type=InvestmentEventType.trade,
        date=EVENT_AT,
        source=None,
        external_id=None,
        order_id=None,
        description=None,
        realized_pnl=Decimal("4"),
        realized_pnl_currency="CHF",
        import_batch_id=None,
        archived_at=None,
        deleted_at=None,
        created_at=EVENT_AT,
        updated_at=EVENT_AT,
    )


def _movement() -> InvestmentMovementModel:
    return InvestmentMovementModel(
        id="movement-1",
        event_id="event-1",
        account_id="account-1",
        asset_id=None,
        listing_id=None,
        kind=InvestmentMovementKind.cash,
        direction=MovementDirection.outgoing,
        quantity=Decimal("20"),
        currency="GBP",
        price_per_unit=None,
        value_amount=Decimal("20"),
        value_currency="GBP",
        source_symbol=None,
        source_asset_type=None,
        note=None,
        created_at=EVENT_AT,
        updated_at=EVENT_AT,
    )


def _transaction() -> TransactionModel:
    return TransactionModel(
        id="transaction-1",
        date=EVENT_AT + timedelta(hours=1),
        booking_date=None,
        amount=Decimal("10"),
        currency="CAD",
        reporting_amount=None,
        reporting_currency=None,
        type=TransactionType.income,
        classification=TransactionClassification.real_income,
        description=None,
        note=None,
        counterparty=None,
        external_id=None,
        is_reviewed=False,
        archived_at=None,
        deleted_at=None,
        category_id=None,
        account_id="account-1",
        import_batch_id=None,
        created_at=EVENT_AT,
        updated_at=EVENT_AT,
    )


def _liability() -> LiabilityBalanceModel:
    return LiabilityBalanceModel(
        id="liability-1",
        account_id="account-1",
        effective_at=EVENT_AT,
        currency="JPY",
        outstanding_principal=Decimal("100"),
        accrued_interest=Decimal("0"),
        fees_outstanding=Decimal("0"),
        total_outstanding=Decimal("100"),
        source=LiabilityBalanceSource.manual,
        external_id=None,
        created_at=EVENT_AT,
    )


def _planner(
    repository: _Repository,
    *,
    price_sources: frozenset[PriceSource] = frozenset({PriceSource.yahoo_finance}),
    fx_source: ExchangeRateSource | None = ExchangeRateSource.ecb,
    source_policy: MarketEvidenceSourcePolicy | None = None,
) -> MarketEvidenceRequirementsPlanner:
    return MarketEvidenceRequirementsPlanner(
        cast(Any, object()),
        price_sources=price_sources,
        fx_source=fx_source,
        repository=repository,
        source_policy=source_policy,
    )


@pytest.mark.asyncio
async def test_plan_uses_exact_listing_identity_and_canonical_order() -> None:
    repository = _Repository()
    repository.holdings = (_holding("2"), _holding("1"))

    plan = await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )

    assert plan.user_id == "user-1"
    assert plan.output_currency == "CZK"
    assert plan.snapshot_timestamp == SNAPSHOT_AT
    assert [item.listing_id for item in plan.price_requirements] == [
        "listing-1",
        "listing-2",
    ]
    assert [item.provider_symbol for item in plan.price_requirements] == [
        "EXACT",
        "EXACT",
    ]
    assert all(item.through == SNAPSHOT_AT for item in plan.price_requirements)
    assert repository.calls == [
        ("user", "user-1"),
        ("accounts", "user-1"),
        ("holdings", ("account-1",), SNAPSHOT_AT),
        ("transactions", ("account-1",), SNAPSHOT_AT),
        ("events", ("account-1",), SNAPSHOT_AT),
        ("movements", ("account-1",), SNAPSHOT_AT),
        ("liabilities", ("account-1",), SNAPSHOT_AT),
    ]


@pytest.mark.asyncio
async def test_closed_market_reuses_exact_previous_close_without_provider_fetch() -> None:
    repository = _Repository()
    persisted = _holding()
    assert persisted.listing is not None and persisted.asset is not None
    persisted.listing.mic = "XNAS"
    persisted.listing.base_priority = 100
    previous_close = PriceSnapshotModel(
        id="price-previous-close",
        asset_id=persisted.asset.id,
        listing_id=persisted.listing.id,
        provider_symbol="EXACT",
        price=Decimal("100"),
        currency="EUR",
        source=PriceSource.yahoo_finance,
        timestamp=datetime(2026, 7, 31, 20),
        created_at=datetime(2026, 7, 31, 20),
    )
    repository.holdings = (
        replace(
            persisted,
            candidate_listings=(persisted.listing,),
            candidate_prices=(previous_close,),
        ),
    )

    plan = await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )

    assert plan.price_requirements == ()


@pytest.mark.asyncio
async def test_unknown_calendar_never_guesses_previous_close_reuse() -> None:
    repository = _Repository()
    persisted = _holding()
    assert persisted.listing is not None and persisted.asset is not None
    persisted.listing.mic = "XZZZ"
    previous = PriceSnapshotModel(
        id="price-unknown-calendar",
        asset_id=persisted.asset.id,
        listing_id=persisted.listing.id,
        provider_symbol="EXACT",
        price=Decimal("100"),
        currency="EUR",
        source=PriceSource.yahoo_finance,
        timestamp=datetime(2026, 7, 31, 20),
        created_at=datetime(2026, 7, 31, 20),
    )
    repository.holdings = (
        replace(
            persisted,
            candidate_listings=(persisted.listing,),
            candidate_prices=(previous,),
        ),
    )

    plan = await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )

    assert len(plan.price_requirements) == 1


@pytest.mark.asyncio
async def test_missing_direct_provider_symbol_is_an_explicit_identity_failure() -> None:
    repository = _Repository()
    repository.holdings = (_holding(provider_symbol=None),)

    plan = await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )

    assert plan.price_requirements == ()
    assert len(plan.identity_failures) == 1
    failure = plan.identity_failures[0]
    assert failure.listing_id == "listing-1"
    assert failure.provider is PriceSource.yahoo_finance
    assert failure.reason is MarketDataFailureReason.missing_provider_symbol


def _alternate_listing(
    requested: AssetListingModel,
    *,
    listing_id: str = "listing-alternate",
    priority: int = 80,
    currency: str = "EUR",
    asset_id: str | None = None,
    provider_symbol: str = "ALTERNATE",
) -> AssetListingModel:
    return AssetListingModel(
        id=listing_id,
        asset_id=asset_id or requested.asset_id,
        symbol="EXACT-ALT",
        exchange="XALT",
        mic="XMIL",
        currency=currency,
        country=None,
        provider=PriceSource.yahoo_finance,
        provider_symbol=provider_symbol,
        is_primary=False,
        base_priority=priority,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
    )


def _listing_health(
    listing: AssetListingModel,
    state: MarketDataHealthState,
    *,
    retry_after: datetime | None = None,
    lease_expires_at: datetime | None = None,
) -> MarketDataListingHealthModel:
    return MarketDataListingHealthModel(
        id=f"health-{listing.id}",
        listing_id=listing.id,
        provider=PriceSource.yahoo_finance,
        provider_symbol=listing.provider_symbol,
        state=state,
        retry_after=retry_after,
        lease_expires_at=lease_expires_at,
        state_changed_at=SNAPSHOT_AT,
    )


async def _plan_for_candidates(
    requested: AssetListingModel,
    alternate: AssetListingModel,
    *,
    health: tuple[MarketDataListingHealthModel, ...] = (),
    provider_retry_after: tuple[tuple[PriceSource, datetime], ...] = (),
):
    repository = _Repository()
    persisted = repository.holdings[0]
    repository.holdings = (
        replace(
            persisted,
            candidate_listings=(alternate, requested),
            candidate_health=health,
            provider_retry_after=provider_retry_after,
            asset_listing_count=2,
        ),
    )
    return await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )


@pytest.mark.asyncio
async def test_plan_selects_higher_priority_exact_listing_and_persists_selected_identity() -> None:
    requested = _holding().listing
    assert requested is not None
    requested.base_priority = 50
    alternate = _alternate_listing(requested, priority=100)
    plan = await _plan_for_candidates(requested, alternate)
    price = plan.price_requirements[0]
    assert (price.listing_id, price.provider_symbol, price.listing_mic) == (
        alternate.id,
        "ALTERNATE",
        "XMIL",
    )
    assert price.requested_listing_id == requested.id
    assert price.selection_reason == "higher_base_priority"
    assert price.fallback_reason == "higher_base_priority"
    assert price.selected_base_priority == 100
    assert price.selected_health == "unknown"


@pytest.mark.asyncio
async def test_plan_skips_degraded_listing_then_restores_it_after_recovery() -> None:
    requested = _holding().listing
    assert requested is not None
    requested.base_priority = 100
    alternate = _alternate_listing(requested)
    degraded = await _plan_for_candidates(
        requested,
        alternate,
        health=(_listing_health(requested, MarketDataHealthState.degraded),),
    )
    assert degraded.price_requirements[0].listing_id == alternate.id
    assert degraded.price_requirements[0].fallback_reason == "requested_listing_degraded"
    recovered = await _plan_for_candidates(
        requested,
        alternate,
        health=(_listing_health(requested, MarketDataHealthState.healthy),),
    )
    assert recovered.price_requirements[0].listing_id == requested.id
    assert recovered.price_requirements[0].selected_health == "healthy"


@pytest.mark.asyncio
async def test_plan_keeps_suspect_preferred_listing_and_ties_are_stable() -> None:
    requested = _holding().listing
    assert requested is not None
    requested.base_priority = 100
    alternate = _alternate_listing(requested, priority=80)
    plan = await _plan_for_candidates(
        requested,
        alternate,
        health=(_listing_health(requested, MarketDataHealthState.suspect),),
    )
    assert plan.price_requirements[0].listing_id == requested.id
    assert plan.price_requirements[0].selected_health == "suspect"

    alternate.base_priority = 100
    alternate.provider_symbol = "AAA"
    tied = await _plan_for_candidates(requested, alternate)
    assert tied.price_requirements[0].listing_id == alternate.id


@pytest.mark.asyncio
async def test_plan_excludes_other_asset_and_other_currency() -> None:
    requested = _holding().listing
    assert requested is not None
    requested.base_priority = 10
    foreign = _alternate_listing(requested, priority=1000, asset_id="foreign-asset")
    plan = await _plan_for_candidates(requested, foreign)
    assert plan.price_requirements[0].listing_id == requested.id

    alternate = _alternate_listing(requested, priority=1000, currency="USD")
    plan = await _plan_for_candidates(requested, alternate)
    assert plan.price_requirements[0].listing_id == requested.id


@pytest.mark.asyncio
async def test_plan_falls_back_when_requested_provider_identity_is_missing() -> None:
    persisted = _holding(provider=PriceSource.yahoo_finance, provider_symbol=None)
    requested = persisted.listing
    assert requested is not None
    requested.base_priority = 100
    alternate = _alternate_listing(requested, priority=80)
    repository = _Repository()
    repository.holdings = (
        replace(
            persisted,
            candidate_listings=(requested, alternate),
            asset_listing_count=2,
        ),
    )

    plan = await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )

    selected = plan.price_requirements[0]
    assert selected.requested_listing_id == requested.id
    assert selected.listing_id == alternate.id
    assert selected.fallback_reason == "requested_listing_incompatible"


@pytest.mark.asyncio
async def test_plan_respects_persisted_cooldown_and_active_lease() -> None:
    requested = _holding().listing
    assert requested is not None
    requested.base_priority = 100
    alternate = _alternate_listing(requested)
    deadline = datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=10)
    with pytest.raises(MarketEvidenceStateError):
        await _plan_for_candidates(
            requested,
            alternate,
            provider_retry_after=((PriceSource.yahoo_finance, deadline),),
        )

    leased = await _plan_for_candidates(
        requested,
        alternate,
        health=(
            _listing_health(requested, MarketDataHealthState.healthy, lease_expires_at=deadline),
        ),
    )
    assert leased.price_requirements[0].listing_id == alternate.id


@pytest.mark.asyncio
async def test_two_exact_listings_of_same_asset_remain_distinct_requirements() -> None:
    repository = _Repository()
    first = _holding("1")
    second = _holding("2")
    assert first.asset is not None
    assert second.asset is not None
    assert second.listing is not None
    second.holding.asset_id = first.asset.id
    second.listing.asset_id = first.asset.id
    repository.holdings = (
        first,
        PersistedMarketHolding(
            second.holding,
            second.listing,
            first.asset,
            (),
        ),
    )

    plan = await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )

    assert len(plan.price_requirements) == 2
    assert {item.asset_id for item in plan.price_requirements} == {"asset-1"}
    assert {item.listing_id for item in plan.price_requirements} == {
        "listing-1",
        "listing-2",
    }


@pytest.mark.asyncio
async def test_same_listing_in_two_accounts_has_one_price_requirement() -> None:
    repository = _Repository()
    repository.accounts = (_account("account-1"), _account("account-2"))
    first = _holding(account_id="account-1")
    second = _holding(account_id="account-2")
    second.holding.id = "holding-second"
    repository.holdings = (second, first)

    plan = await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )

    assert len(plan.price_requirements) == 1
    assert plan.price_requirements[0].account_id == "account-1"


@pytest.mark.asyncio
async def test_plan_uses_one_exact_supported_asset_alias() -> None:
    repository = _Repository()
    repository.holdings = (
        _holding(
            provider=PriceSource.broker,
            provider_symbol="BROKER",
            aliases=(
                _alias(AssetAliasProvider.coingecko, "exact-coin"),
                _alias(AssetAliasProvider.broker, "ignored-broker"),
            ),
        ),
    )

    plan = await _planner(
        repository,
        price_sources=frozenset({PriceSource.coingecko}),
    ).build(BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT))

    assert plan.price_requirements[0].provider is PriceSource.coingecko
    assert plan.price_requirements[0].provider_symbol == "exact-coin"


@pytest.mark.asyncio
async def test_local_free_crypto_uses_coingecko_native_listing_currency() -> None:
    repository = _Repository()
    policy = LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY
    provider = policy.price_source_for(AssetType.crypto)
    repository.holdings = (
        _holding(
            symbol="BTC",
            asset_type=AssetType.crypto,
            cost_currency="EUR",
            listing_currency="EUR",
            provider=PriceSource.broker,
            provider_symbol="ANYCOIN",
            aliases=(_alias(AssetAliasProvider(provider.value), "bitcoin"),),
        ),
    )

    plan = await _planner(
        repository,
        price_sources=policy.price_sources,
        fx_source=policy.fx_source,
        source_policy=policy,
    ).build(BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT))

    requirement = plan.price_requirements[0]
    assert (
        requirement.provider,
        requirement.provider_symbol,
        requirement.listing_currency,
    ) == (provider, "bitcoin", "EUR")
    assert {(item.from_currency, item.to_currency) for item in plan.fx_requirements} == {
        ("EUR", "CZK"),
    }


@pytest.mark.asyncio
async def test_local_free_crypto_accepts_explicit_yahoo_pair_listing() -> None:
    repository = _Repository()
    policy = LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY
    repository.holdings = (
        _holding(
            symbol="BTC",
            asset_type=AssetType.crypto,
            cost_currency="USD",
            listing_currency="USD",
            provider=PriceSource.yahoo_finance,
            provider_symbol="BTC-USD",
            aliases=(),
        ),
    )

    plan = await _planner(
        repository,
        price_sources=policy.price_sources,
        fx_source=policy.fx_source,
        source_policy=policy,
    ).build(BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT))

    requirement = plan.price_requirements[0]
    assert (
        requirement.provider,
        requirement.provider_symbol,
        requirement.listing_currency,
    ) == (PriceSource.yahoo_finance, "BTC-USD", "USD")


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_symbol", [" BTC-USD", "ethereum "])
async def test_local_free_crypto_rejects_malformed_coingecko_alias(
    provider_symbol: str,
) -> None:
    repository = _Repository()
    policy = LOCAL_FREE_MARKET_EVIDENCE_SOURCE_POLICY
    provider = policy.price_source_for(AssetType.crypto)
    repository.holdings = (
        _holding(
            symbol="BTC",
            asset_type=AssetType.crypto,
            listing_currency="EUR",
            provider=PriceSource.broker,
            provider_symbol="ANYCOIN",
            aliases=(_alias(AssetAliasProvider(provider.value), provider_symbol),),
        ),
    )

    with pytest.raises(MarketEvidenceStateError):
        await _planner(
            repository,
            price_sources=policy.price_sources,
            fx_source=policy.fx_source,
            source_policy=policy,
        ).build(BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT))


@pytest.mark.asyncio
async def test_injected_twelve_data_provider_uses_exact_opaque_alias() -> None:
    registry = PriceProviderRegistry((_InjectedTwelveDataProvider(),))
    repository = _Repository()
    repository.holdings = (
        _holding(
            provider=PriceSource.broker,
            provider_symbol="TRADING212",
            aliases=(_alias(AssetAliasProvider.twelve_data, "opaque-exact-identity"),),
        ),
    )

    plan = await _planner(
        repository,
        price_sources=registry.sources,
    ).build(BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT))

    requirement = plan.price_requirements[0]
    assert requirement.provider is PriceSource.twelve_data
    assert requirement.provider_symbol == "opaque-exact-identity"


@pytest.mark.asyncio
async def test_twelve_data_identity_is_never_inferred_from_listing_metadata() -> None:
    repository = _Repository()
    persisted = _holding(
        provider=PriceSource.broker,
        provider_symbol="TRADING212",
        aliases=(),
    )
    assert persisted.asset is not None
    assert persisted.listing is not None
    persisted.asset.symbol = "AAPL"
    persisted.asset.isin = "US0378331005"
    persisted.asset.name = "Apple Inc."
    persisted.listing.exchange = "NASDAQ"
    persisted.listing.mic = "XNAS"
    repository.holdings = (persisted,)

    with pytest.raises(MarketEvidenceStateError):
        await _planner(
            repository,
            price_sources=frozenset({PriceSource.twelve_data}),
        ).build(BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT))


@pytest.mark.asyncio
async def test_production_registry_projects_exact_twelve_data_requirement() -> None:
    registry = create_production_price_registry(Settings(_env_file=None))
    repository = _Repository()
    repository.holdings = (
        _holding(
            provider=PriceSource.broker,
            provider_symbol="TRADING212",
            aliases=(
                _alias(
                    AssetAliasProvider.twelve_data,
                    '{"symbol":"AAPL","mic_code":"XNAS"}',
                ),
            ),
        ),
    )

    assert registry.sources == frozenset({PriceSource.coingecko, PriceSource.twelve_data})
    plan = await _planner(repository, price_sources=registry.sources).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )
    assert plan.price_requirements[0].provider is PriceSource.twelve_data
    assert plan.price_requirements[0].provider_symbol == '{"symbol":"AAPL","mic_code":"XNAS"}'


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "aliases",
    [
        (),
        (
            _alias(AssetAliasProvider.coingecko, "coin"),
            _alias(AssetAliasProvider.yahoo_finance, "ticker"),
        ),
    ],
)
async def test_missing_or_ambiguous_alias_fails_closed(
    aliases: tuple[AssetAliasModel, ...],
) -> None:
    repository = _Repository()
    repository.holdings = (
        _holding(
            provider=PriceSource.broker,
            aliases=aliases,
        ),
    )
    with pytest.raises(MarketEvidenceStateError):
        await _planner(
            repository,
            price_sources=frozenset({PriceSource.coingecko, PriceSource.yahoo_finance}),
        ).build(BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT))


@pytest.mark.asyncio
async def test_supported_listing_with_blank_symbol_does_not_guess_from_alias() -> None:
    repository = _Repository()
    repository.holdings = (
        _holding(
            provider=PriceSource.yahoo_finance,
            provider_symbol="",
            aliases=(_alias(AssetAliasProvider.coingecko, "coin"),),
        ),
    )
    plan = await _planner(
        repository,
        price_sources=frozenset({PriceSource.yahoo_finance, PriceSource.coingecko}),
    ).build(BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT))
    assert plan.price_requirements == ()
    assert plan.identity_failures[0].reason is MarketDataFailureReason.missing_provider_symbol


@pytest.mark.asyncio
async def test_zero_holding_is_not_a_price_requirement() -> None:
    repository = _Repository()
    repository.holdings = (_holding(quantity="0"),)
    plan = await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )
    assert plan.price_requirements == ()


@pytest.mark.asyncio
async def test_unknown_holding_basis_keeps_price_and_omits_only_cost_fx() -> None:
    repository = _Repository()
    persisted = _holding(cost_currency="USD", listing_currency="EUR")
    persisted.holding.avg_buy_price = None
    persisted.holding.cost_basis_by_currency = None
    repository.holdings = (persisted,)

    plan = await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )

    assert len(plan.price_requirements) == 1
    assert plan.price_requirements[0].listing_id == "listing-1"
    assert {
        (item.from_currency, item.to_currency, item.through) for item in plan.fx_requirements
    } == {
        ("EUR", "CZK", SNAPSHOT_AT),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("average", "costs"),
    [
        (None, {"USD": "10.0000000000"}),
        (Decimal("10"), None),
        (Decimal("0"), {"USD": "10.0000000000"}),
    ],
)
async def test_incomplete_or_invalid_holding_basis_pair_fails_closed(
    average: Decimal | None,
    costs: dict[str, str] | None,
) -> None:
    repository = _Repository()
    persisted = _holding()
    persisted.holding.avg_buy_price = average
    persisted.holding.cost_basis_by_currency = cast(dict[str, object] | None, costs)
    repository.holdings = (persisted,)

    with pytest.raises(MarketEvidenceStateError):
        await _planner(repository).build(
            BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
        )


@pytest.mark.asyncio
async def test_fx_requirements_separate_snapshot_and_event_time() -> None:
    repository = _Repository()
    repository.events = (_event(),)
    repository.movements = (_movement(),)
    repository.transactions = (_transaction(),)
    repository.liability_balances = (_liability(),)

    plan = await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )

    identities = {
        (item.from_currency, item.to_currency, item.through, item.provider)
        for item in plan.fx_requirements
    }
    assert ("EUR", "CZK", SNAPSHOT_AT, ExchangeRateSource.ecb) in identities
    assert ("USD", "CZK", SNAPSHOT_AT, ExchangeRateSource.ecb) in identities
    assert ("GBP", "CZK", EVENT_AT, ExchangeRateSource.ecb) in identities
    assert ("CHF", "CZK", EVENT_AT, ExchangeRateSource.ecb) in identities
    assert ("GBP", "EUR", EVENT_AT, ExchangeRateSource.ecb) in identities
    assert ("CHF", "EUR", EVENT_AT, ExchangeRateSource.ecb) in identities
    assert ("JPY", "CZK", SNAPSHOT_AT, ExchangeRateSource.ecb) in identities
    assert (
        "CAD",
        "CZK",
        EVENT_AT + timedelta(hours=1),
        ExchangeRateSource.ecb,
    ) in identities
    assert plan.fx_requirements == tuple(
        sorted(
            plan.fx_requirements,
            key=lambda item: (
                item.from_currency,
                item.to_currency,
                item.through,
                item.provider.value,
            ),
        )
    )


@pytest.mark.asyncio
async def test_same_currency_is_structural_bypass_without_fx_provider() -> None:
    repository = _Repository()
    repository.user = _user(currency="EUR")
    repository.accounts = (_account(currency="EUR"),)
    repository.holdings = (_holding(cost_currency="EUR", listing_currency="EUR"),)

    plan = await _planner(repository, fx_source=None).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )

    assert plan.fx_requirements == ()


@pytest.mark.asyncio
async def test_direct_fx_requirement_never_inverts_or_derives() -> None:
    repository = _Repository()
    plan = await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )
    assert all(item.from_currency != item.to_currency for item in plan.fx_requirements)
    assert ("USD", "EUR", SNAPSHOT_AT) in {
        (item.from_currency, item.to_currency, item.through) for item in plan.fx_requirements
    }


@pytest.mark.asyncio
async def test_multi_settlement_holding_requires_each_direct_snapshot_pair() -> None:
    repository = _Repository()
    persisted = _holding(cost_currency="EUR", listing_currency="USD")
    persisted.holding.cost_basis_by_currency = {
        "EUR": "100.0000000000",
        "USD": "110.0000000000",
    }
    repository.holdings = (persisted,)

    plan = await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )

    pairs = {(item.from_currency, item.to_currency) for item in plan.fx_requirements}
    assert {("EUR", "CZK"), ("USD", "EUR"), ("USD", "CZK")} <= pairs


@pytest.mark.asyncio
async def test_non_czk_targets_plan_only_direct_output_observations() -> None:
    repository = _Repository()
    repository.user = _user(currency="EUR")
    repository.accounts = (_account(currency="USD"),)
    repository.holdings = (_holding(cost_currency="EUR", listing_currency="GBP"),)

    plan = await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )

    assert {
        (item.from_currency, item.to_currency, item.through) for item in plan.fx_requirements
    } == {
        ("EUR", "USD", SNAPSHOT_AT),
        ("GBP", "EUR", SNAPSHOT_AT),
        ("GBP", "USD", SNAPSHOT_AT),
        ("USD", "EUR", SNAPSHOT_AT),
    }


@pytest.mark.asyncio
async def test_plan_rejects_invalid_identity_timestamp_and_output_currency() -> None:
    repository = _Repository()
    for command in (
        BuildMarketEvidenceRefreshPlanCommand("", SNAPSHOT_AT),
        BuildMarketEvidenceRefreshPlanCommand(
            "user-1",
            datetime(2026, 8, 3, microsecond=1),
        ),
    ):
        with pytest.raises(MarketEvidenceStateError):
            await _planner(repository).build(command)
    repository.user = _user(currency="czk")
    with pytest.raises(MarketEvidenceStateError):
        await _planner(repository).build(
            BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
        )
