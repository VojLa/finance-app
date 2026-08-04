from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest

from app.db.models.enums import ExchangeRateSource, PriceSource
from app.modules.fx.models import ExchangeRateObservation
from app.modules.market_data.models import (
    ExchangeRateRequirement,
    MarketEvidenceRefreshPlan,
    MarketEvidenceStateError,
    PriceRequirement,
)
from app.modules.market_data.providers import (
    ExchangeRateProviderRegistry,
    PriceProviderRegistry,
)
from app.modules.market_data.service import (
    MarketEvidenceRefreshService,
    RefreshMarketEvidenceCommand,
    _coalesce_price_observations,
)
from app.modules.market_data.writer import PersistMarketEvidenceResult
from app.modules.prices.models import PriceObservation

SNAPSHOT_AT = datetime(2026, 8, 3, 12)
CREATED_AT = datetime(2026, 8, 3, 12, 1)
SAME_DAY_SNAPSHOT_AT = datetime(2026, 8, 3, 16)
SAME_DAY_RATE_AT = datetime(2026, 8, 3)


class _Transaction:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> None:
        self.session.active = True
        self.session.calls.append("begin")

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.session.calls.append("commit" if exc_type is None else "rollback")
        self.session.active = False


class _Session:
    def __init__(self) -> None:
        self.active = False
        self.calls: list[str] = []

    def in_transaction(self) -> bool:
        return self.active

    def begin(self) -> _Transaction:
        return _Transaction(self)


class _ReadBoundary:
    def __init__(self, session: _Session, calls: list[str]) -> None:
        self.session = session
        self.calls = calls

    async def set_transaction_repeatable_read_only(self) -> None:
        assert self.session.active
        self.calls.append("repeatable-read-only")


class _Planner:
    def __init__(
        self,
        session: _Session,
        calls: list[str],
        plan: MarketEvidenceRefreshPlan,
    ) -> None:
        self.session = session
        self.calls = calls
        self.plan = plan

    async def build(self, command: object) -> MarketEvidenceRefreshPlan:
        assert self.session.active
        self.calls.append("plan")
        return self.plan


class _PriceProvider:
    source = PriceSource.yahoo_finance

    def __init__(self, session: _Session, calls: list[str]) -> None:
        self.session = session
        self.calls = calls
        self.count = 0
        self.error: Exception | None = None
        self.observation = PriceObservation(
            asset_id="asset-1",
            listing_id="listing-1",
            provider=self.source,
            provider_symbol="EXACT",
            price=Decimal("10.1234567890"),
            currency="EUR",
            observed_at=SNAPSHOT_AT - timedelta(hours=1),
        )

    async def fetch(self, requirement: PriceRequirement) -> PriceObservation:
        assert not self.session.active
        self.calls.append("price-provider")
        self.count += 1
        if self.error is not None:
            raise self.error
        return self.observation


class _FxProvider:
    source = ExchangeRateSource.ecb

    def __init__(self, session: _Session, calls: list[str]) -> None:
        self.session = session
        self.calls = calls
        self.count = 0
        self.observations: list[ExchangeRateObservation] = []
        self.observation = ExchangeRateObservation(
            from_currency="EUR",
            to_currency="CZK",
            provider=self.source,
            rate=Decimal("25.12345678"),
            effective_at=SNAPSHOT_AT - timedelta(days=1),
        )

    async def fetch(
        self,
        requirement: ExchangeRateRequirement,
    ) -> ExchangeRateObservation:
        assert not self.session.active
        self.calls.append("fx-provider")
        self.count += 1
        if self.observations:
            return self.observations[self.count - 1]
        return self.observation


class _Writer:
    def __init__(self, session: _Session, calls: list[str]) -> None:
        self.session = session
        self.calls = calls
        self.commands: list[object] = []

    async def write(self, command: object) -> PersistMarketEvidenceResult:
        assert not self.session.active
        self.calls.append("writer")
        self.commands.append(command)
        persisted = cast(Any, command)
        price_count = len(persisted.price_observations)
        rate_count = len(persisted.exchange_rate_observations)
        return PersistMarketEvidenceResult(
            price_ids=("price-id",) if price_count else (),
            exchange_rate_ids=("rate-id",) if rate_count else (),
            prices_created=price_count,
            prices_replayed=0,
            rates_created=rate_count,
            rates_replayed=0,
        )


def _plan() -> MarketEvidenceRefreshPlan:
    return MarketEvidenceRefreshPlan(
        user_id="user-1",
        output_currency="CZK",
        snapshot_timestamp=SNAPSHOT_AT,
        price_requirements=(
            PriceRequirement(
                account_id="account-1",
                asset_id="asset-1",
                listing_id="listing-1",
                listing_currency="EUR",
                provider=PriceSource.yahoo_finance,
                provider_symbol="EXACT",
                through=SNAPSHOT_AT,
            ),
        ),
        fx_requirements=(
            ExchangeRateRequirement(
                from_currency="EUR",
                to_currency="CZK",
                through=SNAPSHOT_AT,
                provider=ExchangeRateSource.ecb,
            ),
        ),
    )


def _service() -> tuple[
    MarketEvidenceRefreshService,
    _Session,
    list[str],
    _PriceProvider,
    _FxProvider,
    _Writer,
]:
    session = _Session()
    calls: list[str] = []
    price = _PriceProvider(session, calls)
    fx = _FxProvider(session, calls)
    writer = _Writer(session, calls)
    service = MarketEvidenceRefreshService(
        cast(Any, session),
        price_registry=PriceProviderRegistry((price,)),
        fx_registry=ExchangeRateProviderRegistry((fx,)),
        read_boundary=_ReadBoundary(session, calls),
        planner=_Planner(session, calls, _plan()),
        writer=writer,
    )
    return service, session, calls, price, fx, writer


def _same_day_fx_service(
    *,
    second_rate: str = "24.50000000",
) -> tuple[MarketEvidenceRefreshService, _FxProvider, _Writer]:
    session = _Session()
    calls: list[str] = []
    fx = _FxProvider(session, calls)
    fx.observations = [
        ExchangeRateObservation(
            from_currency="EUR",
            to_currency="CZK",
            provider=ExchangeRateSource.ecb,
            rate=Decimal("24.50000000"),
            effective_at=SAME_DAY_RATE_AT,
        ),
        ExchangeRateObservation(
            from_currency="EUR",
            to_currency="CZK",
            provider=ExchangeRateSource.ecb,
            rate=Decimal(second_rate),
            effective_at=SAME_DAY_RATE_AT,
        ),
    ]
    writer = _Writer(session, calls)
    plan = MarketEvidenceRefreshPlan(
        user_id="user-1",
        output_currency="CZK",
        snapshot_timestamp=SAME_DAY_SNAPSHOT_AT,
        price_requirements=(),
        fx_requirements=(
            ExchangeRateRequirement(
                from_currency="EUR",
                to_currency="CZK",
                through=datetime(2026, 8, 3, 10),
                provider=ExchangeRateSource.ecb,
            ),
            ExchangeRateRequirement(
                from_currency="EUR",
                to_currency="CZK",
                through=datetime(2026, 8, 3, 15),
                provider=ExchangeRateSource.ecb,
            ),
        ),
    )
    service = MarketEvidenceRefreshService(
        cast(Any, session),
        fx_registry=ExchangeRateProviderRegistry((fx,)),
        read_boundary=_ReadBoundary(session, calls),
        planner=_Planner(session, calls, plan),
        writer=writer,
    )
    return service, fx, writer


@pytest.mark.parametrize(
    "registry",
    [
        lambda provider: PriceProviderRegistry((provider, provider)),
        lambda provider: PriceProviderRegistry(
            (cast(Any, type("ManualPrice", (), {"source": PriceSource.manual})()),)
        ),
    ],
)
def test_price_registry_rejects_duplicate_and_manual(
    registry: Any,
) -> None:
    provider = cast(Any, type("Price", (), {"source": PriceSource.stooq})())
    with pytest.raises(MarketEvidenceStateError):
        registry(provider)


@pytest.mark.parametrize(
    "registry",
    [
        lambda provider: ExchangeRateProviderRegistry((provider, provider)),
        lambda provider: ExchangeRateProviderRegistry(
            (
                cast(
                    Any,
                    type("ManualFx", (), {"source": ExchangeRateSource.manual})(),
                ),
            )
        ),
    ],
)
def test_fx_registry_rejects_duplicate_and_manual(registry: Any) -> None:
    provider = cast(Any, type("Fx", (), {"source": ExchangeRateSource.cnb})())
    with pytest.raises(MarketEvidenceStateError):
        registry(provider)


@pytest.mark.asyncio
async def test_service_orders_boundaries_and_persists_one_validated_batch() -> None:
    service, session, calls, _, _, writer = _service()

    result = await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert session.calls == ["begin", "commit"]
    assert calls == [
        "repeatable-read-only",
        "plan",
        "price-provider",
        "fx-provider",
        "writer",
    ]
    assert result.required_price_count == 1
    assert result.required_fx_count == 1
    assert result.price_ids == ("price-id",)
    assert result.exchange_rate_ids == ("rate-id",)
    command = cast(Any, writer.commands[0])
    assert command.price_observations[0].price == Decimal("10.1234567890")
    assert command.exchange_rate_observations[0].rate == Decimal("25.12345678")
    assert command.created_at == CREATED_AT


@pytest.mark.asyncio
async def test_provider_failure_writes_nothing_and_is_not_retried() -> None:
    service, _, calls, price, fx, writer = _service()
    price.error = RuntimeError("provider internals")

    with pytest.raises(MarketEvidenceStateError) as error:
        await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert str(error.value) == "Market evidence is unavailable."
    assert price.count == 1
    assert fx.count == 0
    assert writer.commands == []
    assert calls[-1] == "price-provider"


@pytest.mark.asyncio
async def test_invalid_provider_identity_fails_before_writer() -> None:
    service, _, _, price, _, writer = _service()
    price.observation = PriceObservation(
        asset_id="wrong",
        listing_id="listing-1",
        provider=PriceSource.yahoo_finance,
        provider_symbol="EXACT",
        price=Decimal("10"),
        currency="EUR",
        observed_at=SNAPSHOT_AT,
    )
    with pytest.raises(MarketEvidenceStateError):
        await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))
    assert writer.commands == []


@pytest.mark.asyncio
async def test_service_coalesces_exact_same_day_fx_observations_before_writer() -> None:
    service, fx, writer = _same_day_fx_service()

    result = await service.refresh(
        RefreshMarketEvidenceCommand(
            "user-1",
            SAME_DAY_SNAPSHOT_AT,
            CREATED_AT,
        )
    )

    assert fx.count == 2
    assert result.required_fx_count == 2
    assert len(writer.commands) == 1
    command = cast(Any, writer.commands[0])
    assert command.exchange_rate_observations == (fx.observations[0],)


@pytest.mark.asyncio
async def test_service_rejects_conflicting_same_identity_fx_observations() -> None:
    service, fx, writer = _same_day_fx_service(second_rate="24.60000000")

    with pytest.raises(MarketEvidenceStateError):
        await service.refresh(
            RefreshMarketEvidenceCommand(
                "user-1",
                SAME_DAY_SNAPSHOT_AT,
                CREATED_AT,
            )
        )

    assert fx.count == 2
    assert writer.commands == []


def test_price_observation_coalescing_is_exact_fail_closed_and_sorted() -> None:
    second = PriceObservation(
        asset_id="asset-2",
        listing_id="listing-2",
        provider=PriceSource.yahoo_finance,
        provider_symbol="SECOND",
        price=Decimal("20.0000000000"),
        currency="EUR",
        observed_at=SNAPSHOT_AT,
    )
    first = PriceObservation(
        asset_id="asset-1",
        listing_id="listing-1",
        provider=PriceSource.yahoo_finance,
        provider_symbol="FIRST",
        price=Decimal("10.0000000000"),
        currency="EUR",
        observed_at=SNAPSHOT_AT,
    )

    assert _coalesce_price_observations((second, second, first)) == (
        first,
        second,
    )

    conflicting = PriceObservation(
        asset_id=second.asset_id,
        listing_id=second.listing_id,
        provider=second.provider,
        provider_symbol=second.provider_symbol,
        price=Decimal("20.1000000000"),
        currency=second.currency,
        observed_at=second.observed_at,
    )
    with pytest.raises(MarketEvidenceStateError):
        _coalesce_price_observations((second, conflicting))


@pytest.mark.asyncio
async def test_active_caller_transaction_is_rejected() -> None:
    service, session, _, _, _, _ = _service()
    session.active = True
    with pytest.raises(MarketEvidenceStateError):
        await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))


def test_explicit_fx_source_must_exist_in_registry() -> None:
    with pytest.raises(MarketEvidenceStateError):
        MarketEvidenceRefreshService(
            cast(Any, _Session()),
            fx_registry=ExchangeRateProviderRegistry(),
            fx_source=ExchangeRateSource.ecb,
        )
