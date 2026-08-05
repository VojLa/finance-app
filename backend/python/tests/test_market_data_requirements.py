from __future__ import annotations

from datetime import datetime, timedelta
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
    MovementDirection,
    PriceSource,
    TransactionClassification,
    TransactionType,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.modules.market_data.models import MarketEvidenceStateError, PriceRequirement
from app.modules.market_data.providers import PriceProviderRegistry
from app.modules.market_data.requirements import (
    BuildMarketEvidenceRefreshPlanCommand,
    MarketEvidenceRequirementsPlanner,
)
from app.modules.market_data.requirements_repository import PersistedMarketHolding
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
    ) -> tuple[PersistedMarketHolding, ...]:
        self.calls.append(("holdings", account_ids))
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
) -> PersistedMarketHolding:
    asset = AssetModel(
        id=f"asset-{suffix}",
        symbol="SAME",
        isin=None,
        name="Exact asset",
        asset_type=AssetType.etf,
        currency=listing_currency,
        created_at=SNAPSHOT_AT,
        updated_at=SNAPSHOT_AT,
    )
    listing = AssetListingModel(
        id=f"listing-{suffix}",
        asset_id=asset.id,
        symbol="SAME",
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
        symbol="SAME",
        name="Exact holding",
        asset_type=AssetType.etf,
        quantity=Decimal(quantity),
        avg_buy_price=Decimal("10"),
        currency=cost_currency,
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
    return PersistedMarketHolding(holding, listing, asset, aliases)


def _alias(
    provider: AssetAliasProvider,
    external_id: str,
    *,
    asset_id: str = "asset-1",
) -> AssetAliasModel:
    return AssetAliasModel(
        id=f"alias-{provider.value}",
        asset_id=asset_id,
        provider=provider,
        external_id=external_id,
        created_at=SNAPSHOT_AT,
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
) -> MarketEvidenceRequirementsPlanner:
    return MarketEvidenceRequirementsPlanner(
        cast(Any, object()),
        price_sources=price_sources,
        fx_source=fx_source,
        repository=repository,
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
        ("holdings", ("account-1",)),
        ("transactions", ("account-1",), SNAPSHOT_AT),
        ("events", ("account-1",), SNAPSHOT_AT),
        ("movements", ("account-1",), SNAPSHOT_AT),
        ("liabilities", ("account-1",), SNAPSHOT_AT),
    ]


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
async def test_production_registry_leaves_twelve_data_requirement_unavailable() -> None:
    registry = create_production_price_registry(Settings(_env_file=None))
    repository = _Repository()
    repository.holdings = (
        _holding(
            provider=PriceSource.broker,
            provider_symbol="TRADING212",
            aliases=(_alias(AssetAliasProvider.twelve_data, "opaque-exact-identity"),),
        ),
    )

    assert registry.sources == frozenset({PriceSource.coingecko})
    with pytest.raises(MarketEvidenceStateError):
        await _planner(repository, price_sources=registry.sources).build(
            BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
        )


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
    with pytest.raises(MarketEvidenceStateError):
        await _planner(
            repository,
            price_sources=frozenset({PriceSource.yahoo_finance, PriceSource.coingecko}),
        ).build(BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT))


@pytest.mark.asyncio
async def test_zero_holding_is_not_a_price_requirement() -> None:
    repository = _Repository()
    repository.holdings = (_holding(quantity="0"),)
    plan = await _planner(repository).build(
        BuildMarketEvidenceRefreshPlanCommand("user-1", SNAPSHOT_AT)
    )
    assert plan.price_requirements == ()


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
    assert all(
        item.to_currency == "CZK" and item.from_currency != "CZK" for item in plan.fx_requirements
    )
    assert not any(
        item.from_currency == "CZK" and item.to_currency == "EUR" for item in plan.fx_requirements
    )


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
