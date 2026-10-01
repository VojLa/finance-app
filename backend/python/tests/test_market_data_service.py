from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest

from app.db.models.enums import (
    AssetType,
    ExchangeRateSource,
    MarketDataFailureReason,
    PriceSource,
)
from app.modules.fx.models import ExchangeRateObservation
from app.modules.market_data.models import (
    ExchangeRateRequirement,
    MarketEvidenceRefreshPlan,
    MarketEvidenceStateError,
    PriceIdentityFailure,
    PriceRequirement,
)
from app.modules.market_data.provider_failure import ProviderFailure
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
from app.modules.prices.validation import PriceObservationValidationError

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


class _BatchFxProvider(_FxProvider):
    async def fetch_many(
        self,
        requirements: tuple[ExchangeRateRequirement, ...],
    ) -> tuple[ExchangeRateObservation, ...]:
        assert not self.session.active
        self.calls.append("fx-batch-provider")
        self.count += 1
        return tuple(self.observation for _ in requirements)


class _Writer:
    def __init__(self, session: _Session, calls: list[str]) -> None:
        self.session = session
        self.calls = calls
        self.commands: list[object] = []

    async def write(
        self,
        command: object,
        *,
        transactional_finalize: Callable[[], Awaitable[None]] | None = None,
    ) -> PersistMarketEvidenceResult:
        assert not self.session.active
        self.calls.append("writer")
        self.commands.append(command)
        persisted = cast(Any, command)
        price_count = len(persisted.price_observations)
        rate_count = len(persisted.exchange_rate_observations)
        result = PersistMarketEvidenceResult(
            price_ids=("price-id",) if price_count else (),
            exchange_rate_ids=("rate-id",) if rate_count else (),
            prices_created=price_count,
            prices_replayed=0,
            rates_created=rate_count,
            rates_replayed=0,
        )
        if transactional_finalize is not None:
            async with self.session.begin():
                await transactional_finalize()
        return result


class _Health:
    def __init__(self, session: _Session, calls: list[str]) -> None:
        self.session = session
        self.calls = calls
        self.denied = False
        self.reject_record = False
        self.claims: list[dict[str, Any]] = []
        self.outcomes: list[dict[str, Any]] = []
        self.active_tokens: set[str] = set()

    async def claim(self, **kwargs: Any) -> bool:
        assert self.session.active
        self.calls.append("health-claim")
        self.claims.append(kwargs)
        if self.denied:
            return False
        self.active_tokens.add(kwargs["lease_owner"])
        return True

    async def record(self, **kwargs: Any) -> object | None:
        assert self.session.active
        self.calls.append("health-record")
        self.outcomes.append(kwargs)
        if self.reject_record:
            return None
        lease_owner = kwargs.get("lease_owner")
        if lease_owner is not None:
            assert lease_owner in self.active_tokens
            self.active_tokens.remove(lease_owner)
        return object()


def _service_with_health() -> tuple[
    MarketEvidenceRefreshService, _Session, list[str], _PriceProvider, _FxProvider, _Writer, _Health
]:
    service, session, calls, price, fx, writer = _service()
    health = _Health(session, calls)
    service.health = health
    service.health_clock = lambda: CREATED_AT
    service.health_token = lambda: "attempt-1"
    return service, session, calls, price, fx, writer, health


class _AcquisitionProbe:
    def __init__(self, *, expected_parallel: int) -> None:
        self.expected_parallel = expected_parallel
        self.active = 0
        self.maximum_active = 0
        self.entered: list[str] = []
        self.reached_parallelism = asyncio.Event()
        self.release = asyncio.Event()

    async def hold(self, label: str, *, fail: bool = False) -> None:
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        self.entered.append(label)
        if self.active >= self.expected_parallel:
            self.reached_parallelism.set()
        try:
            if fail:
                await self.reached_parallelism.wait()
                raise RuntimeError("provider failed")
            await self.release.wait()
        finally:
            self.active -= 1


class _ConcurrentPriceProvider:
    def __init__(
        self,
        source: PriceSource,
        probe: _AcquisitionProbe,
        *,
        fail: bool = False,
    ) -> None:
        self.source = source
        self.probe = probe
        self.fail = fail

    async def fetch(self, requirement: PriceRequirement) -> PriceObservation:
        await self.probe.hold(f"price:{self.source.value}", fail=self.fail)
        return PriceObservation(
            asset_id=requirement.asset_id,
            listing_id=requirement.listing_id,
            provider=self.source,
            provider_symbol=requirement.provider_symbol,
            price=Decimal("10.0000000000"),
            currency=requirement.listing_currency,
            observed_at=requirement.through,
        )


class _ConcurrentBatchFxProvider:
    def __init__(self, source: ExchangeRateSource, probe: _AcquisitionProbe) -> None:
        self.source = source
        self.probe = probe

    async def fetch(self, requirement: ExchangeRateRequirement) -> ExchangeRateObservation:
        return (await self.fetch_many((requirement,)))[0]

    async def fetch_many(
        self,
        requirements: tuple[ExchangeRateRequirement, ...],
    ) -> tuple[ExchangeRateObservation, ...]:
        await self.probe.hold(f"fx:{self.source.value}")
        return tuple(
            ExchangeRateObservation(
                from_currency=requirement.from_currency,
                to_currency=requirement.to_currency,
                provider=self.source,
                rate=Decimal("25.00000000"),
                effective_at=requirement.through,
            )
            for requirement in requirements
        )


def _concurrent_plan() -> MarketEvidenceRefreshPlan:
    price_sources = (
        PriceSource.coingecko,
        PriceSource.twelve_data,
        PriceSource.yahoo_finance,
    )
    asset_order = {
        PriceSource.coingecko: "asset-3",
        PriceSource.twelve_data: "asset-2",
        PriceSource.yahoo_finance: "asset-1",
    }
    prices = tuple(
        sorted(
            (
                PriceRequirement(
                    account_id="account-1",
                    asset_id=asset_order[source],
                    listing_id=f"listing-{source.value}",
                    listing_currency="EUR",
                    provider=source,
                    provider_symbol=f"SYMBOL-{source.value}",
                    through=SNAPSHOT_AT,
                )
                for source in price_sources
            ),
            key=lambda item: (
                item.account_id,
                item.asset_id,
                item.listing_id,
                item.provider.value,
                item.provider_symbol,
            ),
        )
    )
    return MarketEvidenceRefreshPlan(
        user_id="user-1",
        output_currency="CZK",
        snapshot_timestamp=SNAPSHOT_AT,
        price_requirements=prices,
        fx_requirements=(
            ExchangeRateRequirement("EUR", "CZK", SNAPSHOT_AT, ExchangeRateSource.ecb),
            ExchangeRateRequirement("EUR", "USD", SNAPSHOT_AT, ExchangeRateSource.cnb),
        ),
    )


def _concurrent_service(
    probe: _AcquisitionProbe,
    *,
    failing_price: bool = False,
) -> tuple[MarketEvidenceRefreshService, _Writer]:
    session = _Session()
    calls: list[str] = []
    plan = _concurrent_plan()
    price_providers = tuple(
        _ConcurrentPriceProvider(
            source,
            probe,
            fail=failing_price and source is PriceSource.coingecko,
        )
        for source in (PriceSource.coingecko, PriceSource.twelve_data, PriceSource.yahoo_finance)
    )
    fx_providers = (
        _ConcurrentBatchFxProvider(ExchangeRateSource.ecb, probe),
        _ConcurrentBatchFxProvider(ExchangeRateSource.cnb, probe),
    )
    writer = _Writer(session, calls)
    return (
        MarketEvidenceRefreshService(
            cast(Any, session),
            price_registry=PriceProviderRegistry(price_providers),
            fx_registry=ExchangeRateProviderRegistry(fx_providers),
            read_boundary=_ReadBoundary(session, calls),
            planner=_Planner(session, calls, plan),
            writer=writer,
        ),
        writer,
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


def _batch_service(
    *, missing_observation: bool
) -> tuple[MarketEvidenceRefreshService, _BatchFxProvider, _Writer]:
    session = _Session()
    calls: list[str] = []
    price = _PriceProvider(session, calls)
    fx = _BatchFxProvider(session, calls)
    writer = _Writer(session, calls)
    plan = MarketEvidenceRefreshPlan(
        user_id="user-1",
        output_currency="CZK",
        snapshot_timestamp=SNAPSHOT_AT,
        price_requirements=(),
        fx_requirements=(
            ExchangeRateRequirement(
                "EUR", "CZK", SNAPSHOT_AT - timedelta(days=1), ExchangeRateSource.ecb
            ),
            ExchangeRateRequirement("EUR", "CZK", SNAPSHOT_AT, ExchangeRateSource.ecb),
        ),
    )
    if missing_observation:

        async def missing(
            requirements: tuple[ExchangeRateRequirement, ...],
        ) -> tuple[ExchangeRateObservation, ...]:
            fx.calls.append("fx-batch-provider")
            return (fx.observation,)

        fx.fetch_many = missing  # type: ignore[method-assign]
    service = MarketEvidenceRefreshService(
        cast(Any, session),
        price_registry=PriceProviderRegistry((price,)),
        fx_registry=ExchangeRateProviderRegistry((fx,)),
        read_boundary=_ReadBoundary(session, calls),
        planner=_Planner(session, calls, plan),
        writer=writer,
    )
    return service, fx, writer


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
    provider = cast(Any, type("Fx", (), {"source": ExchangeRateSource.twelve_data})())
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
async def test_health_claim_commits_before_provider_and_success_records_after_writer() -> None:
    service, session, calls, price, _, writer, health = _service_with_health()

    result = await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert session.calls == ["begin", "commit", "begin", "commit", "begin", "commit"]
    assert calls == [
        "repeatable-read-only",
        "plan",
        "health-claim",
        "price-provider",
        "fx-provider",
        "writer",
        "health-record",
    ]
    assert price.count == 1
    assert health.active_tokens == set()
    assert health.claims[0]["lease_owner"] == "attempt-1"
    assert health.claims[0]["lease_for"] == timedelta(minutes=5)
    assert health.outcomes[0]["outcome"].reason is None
    assert health.outcomes[0]["outcome"].attempt_token == "attempt-1"
    assert len(writer.commands) == 1
    assert result.prices_created == 1


@pytest.mark.asyncio
async def test_writer_failure_never_records_false_health_success() -> None:
    service, _, calls, _, _, writer, health = _service_with_health()

    async def fail_write(
        command: object,
        *,
        transactional_finalize: Callable[[], Awaitable[None]] | None = None,
    ) -> PersistMarketEvidenceResult:
        calls.append("writer")
        raise MarketEvidenceStateError()

    writer.write = fail_write  # type: ignore[method-assign]
    with pytest.raises(MarketEvidenceStateError):
        await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert calls[-1] == "writer"
    assert health.outcomes == []
    assert health.active_tokens == {"attempt-1"}


@pytest.mark.asyncio
async def test_lost_lease_rolls_back_evidence_transaction() -> None:
    service, session, calls, _, _, writer, health = _service_with_health()
    health.reject_record = True

    with pytest.raises(MarketEvidenceStateError):
        await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert session.calls == ["begin", "commit", "begin", "commit", "begin", "rollback"]
    assert calls[-2:] == ["writer", "health-record"]
    assert len(writer.commands) == 1
    assert health.active_tokens == {"attempt-1"}


@pytest.mark.asyncio
async def test_health_denial_prevents_all_provider_io_and_writer() -> None:
    service, session, calls, price, fx, writer, health = _service_with_health()
    health.denied = True

    with pytest.raises(MarketEvidenceStateError):
        await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert session.calls == ["begin", "commit", "begin", "rollback"]
    assert calls == ["repeatable-read-only", "plan", "health-claim"]
    assert price.count == 0
    assert fx.count == 0
    assert writer.commands == []


@pytest.mark.asyncio
async def test_explicit_missing_provider_symbol_records_health_without_provider_io() -> None:
    service, session, calls, price, fx, writer, health = _service_with_health()
    configured_at = SNAPSHOT_AT - timedelta(days=1)
    cast(Any, service.planner).plan = MarketEvidenceRefreshPlan(
        user_id="user-1",
        output_currency="CZK",
        snapshot_timestamp=SNAPSHOT_AT,
        price_requirements=(),
        fx_requirements=(),
        identity_failures=(
            PriceIdentityFailure(
                listing_id="listing-1",
                provider=PriceSource.yahoo_finance,
                reason=MarketDataFailureReason.missing_provider_symbol,
                configured_at=configured_at,
            ),
        ),
    )

    result = await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert session.calls == ["begin", "commit", "begin", "commit"]
    assert calls == ["repeatable-read-only", "plan", "health-record", "writer"]
    assert price.count == 0
    assert fx.count == 0
    assert health.active_tokens == set()
    assert health.outcomes[0]["provider_symbol"] is None
    assert health.outcomes[0]["outcome"].reason is MarketDataFailureReason.missing_provider_symbol
    assert health.outcomes[0]["outcome"].attempt_started_at == configured_at
    assert result.required_price_count == 0
    assert len(writer.commands) == 1


@pytest.mark.asyncio
async def test_classified_price_failure_records_reason_and_releases_lease() -> None:
    service, session, calls, price, fx, writer, health = _service_with_health()
    retry_after = CREATED_AT + timedelta(minutes=20)
    price.error = ProviderFailure(MarketDataFailureReason.rate_limit, retry_after=retry_after)

    with pytest.raises(MarketEvidenceStateError):
        await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert session.calls == ["begin", "commit", "begin", "commit", "begin", "commit"]
    assert calls.index("health-record") > calls.index("price-provider")
    assert fx.count == 1
    assert writer.commands == []
    assert health.active_tokens == set()
    assert health.outcomes[0]["outcome"].reason is MarketDataFailureReason.rate_limit
    assert health.outcomes[0]["outcome"].retry_after == retry_after


@pytest.mark.asyncio
async def test_unexpected_price_failure_records_safe_incomplete_response() -> None:
    service, _, _, price, _, writer, health = _service_with_health()
    price.error = RuntimeError("provider secret")

    with pytest.raises(MarketEvidenceStateError) as error:
        await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert str(error.value) == "Market evidence is unavailable."
    assert health.outcomes[0]["outcome"].reason is MarketDataFailureReason.incomplete_response
    assert health.active_tokens == set()
    assert writer.commands == []


@pytest.mark.asyncio
async def test_classified_validation_failure_records_safe_reason() -> None:
    service, _, _, price, _, writer, health = _service_with_health()
    price.error = PriceObservationValidationError(MarketDataFailureReason.stale_timestamp)

    with pytest.raises(MarketEvidenceStateError):
        await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert health.outcomes[0]["outcome"].reason is MarketDataFailureReason.stale_timestamp
    assert health.active_tokens == set()
    assert writer.commands == []


@pytest.mark.asyncio
async def test_supported_closed_market_records_session_boundary_not_provider_failure() -> None:
    service, _, _, price, _, writer, health = _service_with_health()
    original = _plan()
    requirement = replace(
        original.price_requirements[0],
        listing_mic="XNAS",
        asset_type=AssetType.stock,
    )
    cast(Any, service.planner).plan = replace(
        original,
        price_requirements=(requirement,),
    )
    price.error = PriceObservationValidationError(MarketDataFailureReason.stale_timestamp)

    with pytest.raises(MarketEvidenceStateError):
        await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    outcome = health.outcomes[0]["outcome"]
    assert outcome.reason is MarketDataFailureReason.market_closed
    assert outcome.next_session_at == datetime(2026, 8, 3, 13, 30)
    assert writer.commands == []


@pytest.mark.asyncio
async def test_invalid_price_identity_records_validation_reason() -> None:
    service, _, _, price, _, writer, health = _service_with_health()
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

    assert (
        health.outcomes[0]["outcome"].reason is MarketDataFailureReason.provider_identity_conflict
    )
    assert health.active_tokens == set()
    assert writer.commands == []


@pytest.mark.asyncio
async def test_health_uses_unique_attempt_token_for_each_price_requirement() -> None:
    probe = _AcquisitionProbe(expected_parallel=1)
    probe.release.set()
    service, writer = _concurrent_service(probe)
    health = _Health(cast(Any, service.session), writer.calls)
    service.health = health
    service.health_clock = lambda: CREATED_AT
    tokens = iter(("attempt-1", "attempt-2", "attempt-3"))
    service.health_token = lambda: next(tokens)

    await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert [item["provider"].value for item in health.claims] == sorted(
        item.provider.value for item in _concurrent_plan().price_requirements
    )
    assert {item["lease_owner"] for item in health.claims} == {
        "attempt-1",
        "attempt-2",
        "attempt-3",
    }
    assert {item["outcome"].attempt_token for item in health.outcomes} == {
        "attempt-1",
        "attempt-2",
        "attempt-3",
    }
    assert [item["provider"].value for item in health.outcomes] == sorted(
        item.provider.value for item in _concurrent_plan().price_requirements
    )
    assert health.active_tokens == set()


@pytest.mark.asyncio
async def test_duplicate_attempt_token_rolls_back_claim_batch_before_io() -> None:
    probe = _AcquisitionProbe(expected_parallel=1)
    service, writer = _concurrent_service(probe)
    session = cast(_Session, service.session)
    health = _Health(session, writer.calls)
    service.health = health
    service.health_clock = lambda: CREATED_AT
    service.health_token = lambda: "duplicate"

    with pytest.raises(MarketEvidenceStateError):
        await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert session.calls == ["begin", "commit", "begin", "rollback"]
    assert len(health.claims) == 1
    assert probe.entered == []
    assert writer.commands == []


@pytest.mark.asyncio
async def test_health_success_is_independent_of_writer_replay() -> None:
    service, _, _, _, _, writer, health = _service_with_health()
    tokens = iter(("attempt-1", "attempt-2"))
    service.health_token = lambda: next(tokens)

    first = await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    async def replay(
        command: object,
        *,
        transactional_finalize: Callable[[], Awaitable[None]] | None = None,
    ) -> PersistMarketEvidenceResult:
        writer.commands.append(command)
        result = PersistMarketEvidenceResult(
            price_ids=("price-id",),
            exchange_rate_ids=("rate-id",),
            prices_created=0,
            prices_replayed=1,
            rates_created=0,
            rates_replayed=1,
        )
        if transactional_finalize is not None:
            async with writer.session.begin():
                await transactional_finalize()
        return result

    writer.write = replay  # type: ignore[method-assign]
    second = await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert first.prices_created == 1
    assert second.prices_replayed == 1
    assert len(writer.commands) == 2
    assert [item["outcome"].reason for item in health.outcomes] == [None, None]
    assert health.active_tokens == set()


@pytest.mark.asyncio
async def test_provider_failure_writes_nothing_and_is_not_retried() -> None:
    service, _, calls, price, fx, writer = _service()
    price.error = RuntimeError("provider internals")

    with pytest.raises(MarketEvidenceStateError) as error:
        await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert str(error.value) == "Market evidence is unavailable."
    assert price.count == 1
    assert fx.count == 1
    assert writer.commands == []
    assert "price-provider" in calls
    assert "fx-provider" in calls


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


@pytest.mark.asyncio
async def test_batch_fx_provider_is_called_once_per_source_before_atomic_writer() -> None:
    service, fx, writer = _batch_service(missing_observation=False)

    await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert fx.count == 1
    assert len(writer.commands) == 1


@pytest.mark.asyncio
async def test_batch_fx_missing_one_observation_writes_nothing() -> None:
    service, _, writer = _batch_service(missing_observation=True)

    with pytest.raises(MarketEvidenceStateError):
        await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert writer.commands == []


@pytest.mark.asyncio
async def test_service_bounds_overlapping_price_and_fx_source_acquisitions() -> None:
    probe = _AcquisitionProbe(expected_parallel=4)
    service, writer = _concurrent_service(probe)

    refresh = asyncio.create_task(
        service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))
    )
    await asyncio.wait_for(probe.reached_parallelism.wait(), timeout=1)

    assert probe.maximum_active == 4
    assert "fx:ecb" in probe.entered
    probe.release.set()
    result = await refresh

    assert probe.maximum_active == 4
    assert set(probe.entered) == {
        "price:coingecko",
        "price:twelve_data",
        "price:yahoo_finance",
        "fx:ecb",
        "fx:cnb",
    }
    assert result.required_price_count == 3
    assert result.required_fx_count == 2
    command = cast(Any, writer.commands[0])
    assert tuple(item.listing_id for item in command.price_observations) == tuple(
        sorted(item.listing_id for item in _concurrent_plan().price_requirements)
    )
    assert tuple(
        (item.from_currency, item.to_currency) for item in command.exchange_rate_observations
    ) == (("EUR", "CZK"), ("EUR", "USD"))


@pytest.mark.asyncio
async def test_concurrent_acquisition_failure_cancels_batch_and_never_calls_writer() -> None:
    probe = _AcquisitionProbe(expected_parallel=4)
    service, writer = _concurrent_service(probe, failing_price=True)

    with pytest.raises(MarketEvidenceStateError):
        await service.refresh(RefreshMarketEvidenceCommand("user-1", SNAPSHOT_AT, CREATED_AT))

    assert probe.maximum_active == 4
    assert probe.active == 0
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
