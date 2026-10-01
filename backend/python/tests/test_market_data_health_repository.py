from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.db.models.enums import MarketDataFailureReason, MarketDataHealthState, PriceSource
from app.modules.market_data.health import ListingHealthOutcome
from app.modules.market_data.health_repository import MarketDataHealthRepository, health_id
from app.modules.market_data.health_service import MarketDataHealthService

NOW = datetime(2026, 9, 30, 12)
PROVIDER = PriceSource.yahoo_finance


@dataclass
class FakeRow:
    id: str
    listing_id: str
    provider: PriceSource
    provider_symbol: str | None
    state: MarketDataHealthState
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    consecutive_failures: int
    last_failure_reason: MarketDataFailureReason | None
    retry_after: datetime | None
    state_changed_at: datetime
    last_attempt_token: str | None
    lease_owner: str | None
    lease_expires_at: datetime | None
    version: int
    total_successes: int = 0
    total_failures: int = 0


class FakeRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, PriceSource], FakeRow] = {}
        self.transaction = True
        self.symbol: str | None = "AAPL"

    def require_transaction(self) -> None:
        if not self.transaction:
            raise RuntimeError("caller-owned transaction required")

    async def lock_provider_and_listing(self, listing_id: str, provider: PriceSource) -> None:
        self.require_transaction()

    async def validate_identity(
        self, listing_id: str, provider: PriceSource, provider_symbol: str | None
    ) -> bool:
        return provider_symbol == self.symbol

    async def provider_retry_after(self, provider: PriceSource, now: datetime) -> datetime | None:
        deadlines = [
            row.retry_after
            for row in self.rows.values()
            if row.provider == provider
            and row.last_failure_reason == MarketDataFailureReason.rate_limit
            and row.retry_after is not None
            and row.retry_after > now
        ]
        return max(deadlines, default=None)

    async def locked_row(self, listing_id: str, provider: PriceSource) -> FakeRow | None:
        return self.rows.get((listing_id, provider))

    def add(self, row: FakeRow) -> None:
        self.rows[(row.listing_id, row.provider)] = row

    async def flush(self) -> None:
        pass


def outcome(token: str, started: datetime, reason: MarketDataFailureReason | None = None):
    return ListingHealthOutcome(
        attempt_started_at=started,
        attempt_token=token,
        observed_at=started + timedelta(seconds=1),
        reason=reason,
    )


@pytest.mark.asyncio
async def test_claim_lease_takeover_and_ordered_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.market_data import health_service

    monkeypatch.setattr(health_service, "MarketDataListingHealthModel", FakeRow)
    repo = FakeRepository()
    service = MarketDataHealthService(repo)  # type: ignore[arg-type]
    lease_for = timedelta(seconds=30)
    assert await service.claim(
        listing_id="one",
        provider=PROVIDER,
        provider_symbol="AAPL",
        lease_for=lease_for,
        lease_owner="worker-a",
        now=NOW,
    )
    assert not await service.claim(
        listing_id="one",
        provider=PROVIDER,
        provider_symbol="AAPL",
        lease_for=lease_for,
        lease_owner="worker-b",
        now=NOW + timedelta(seconds=10),
    )
    assert await service.claim(
        listing_id="one",
        provider=PROVIDER,
        provider_symbol="AAPL",
        lease_for=lease_for,
        lease_owner="worker-b",
        now=NOW + timedelta(seconds=31),
    )
    fresh = await service.record(
        listing_id="one",
        provider=PROVIDER,
        provider_symbol="AAPL",
        lease_owner="worker-b",
        outcome=outcome("b", NOW + timedelta(seconds=31)),
    )
    assert fresh is not None and fresh.state == MarketDataHealthState.healthy
    stale = await service.record(
        listing_id="one",
        provider=PROVIDER,
        provider_symbol="AAPL",
        lease_owner="worker-a",
        outcome=outcome("a", NOW),
    )
    assert stale is None
    assert repo.rows[("one", PROVIDER)].version == 3
    assert repo.rows[("one", PROVIDER)].lease_owner is None


@pytest.mark.asyncio
async def test_replay_and_provider_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.market_data import health_service

    monkeypatch.setattr(health_service, "MarketDataListingHealthModel", FakeRow)
    repo = FakeRepository()
    service = MarketDataHealthService(repo)  # type: ignore[arg-type]
    lease_for = timedelta(seconds=30)
    assert await service.claim(
        listing_id="one",
        provider=PROVIDER,
        provider_symbol="AAPL",
        lease_for=lease_for,
        lease_owner="worker-a",
        now=NOW,
    )
    limited = outcome("a", NOW, MarketDataFailureReason.rate_limit)
    first = await service.record(
        listing_id="one",
        provider=PROVIDER,
        provider_symbol="AAPL",
        lease_owner="worker-a",
        outcome=limited,
    )
    assert first is not None and first.retry_after is not None
    assert (
        await service.record(
            listing_id="one",
            provider=PROVIDER,
            provider_symbol="AAPL",
            lease_owner="worker-a",
            outcome=limited,
        )
        == first
    )
    assert repo.rows[("one", PROVIDER)].version == 2
    assert not await service.claim(
        listing_id="two",
        provider=PROVIDER,
        provider_symbol="AAPL",
        lease_for=lease_for,
        lease_owner="worker-b",
        now=NOW,
    )
    assert await service.claim(
        listing_id="two",
        provider=PROVIDER,
        provider_symbol="AAPL",
        lease_for=lease_for,
        lease_owner="worker-b",
        now=first.retry_after,
    )


@pytest.mark.asyncio
async def test_fixed_missing_symbol_rebinds_health_for_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.market_data import health_service

    monkeypatch.setattr(health_service, "MarketDataListingHealthModel", FakeRow)
    repo = FakeRepository()
    repo.symbol = None
    service = MarketDataHealthService(repo)  # type: ignore[arg-type]
    missing = await service.record(
        listing_id="one",
        provider=PROVIDER,
        provider_symbol=None,
        outcome=outcome(
            "configuration:missing-provider-symbol",
            NOW,
            MarketDataFailureReason.missing_provider_symbol,
        ),
    )
    assert missing is not None and missing.state is MarketDataHealthState.unavailable

    repo.symbol = "AAPL"
    assert await service.claim(
        listing_id="one",
        provider=PROVIDER,
        provider_symbol="AAPL",
        lease_owner="worker-a",
        now=NOW + timedelta(minutes=1),
        lease_for=timedelta(seconds=30),
    )
    row = repo.rows[("one", PROVIDER)]
    assert row.provider_symbol == "AAPL"
    assert row.state is MarketDataHealthState.unknown
    assert row.last_failure_reason is None


@pytest.mark.asyncio
async def test_removing_previously_healthy_symbol_records_configuration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.market_data import health_service

    monkeypatch.setattr(health_service, "MarketDataListingHealthModel", FakeRow)
    repo = FakeRepository()
    service = MarketDataHealthService(repo)  # type: ignore[arg-type]
    assert await service.claim(
        listing_id="one",
        provider=PROVIDER,
        provider_symbol="AAPL",
        lease_owner="worker-a",
        now=NOW,
        lease_for=timedelta(seconds=30),
    )
    healthy = await service.record(
        listing_id="one",
        provider=PROVIDER,
        provider_symbol="AAPL",
        lease_owner="worker-a",
        outcome=outcome("healthy", NOW),
    )
    assert healthy is not None and healthy.state is MarketDataHealthState.healthy

    repo.symbol = None
    missing = await service.record(
        listing_id="one",
        provider=PROVIDER,
        provider_symbol=None,
        outcome=outcome(
            "configuration:missing-provider-symbol",
            NOW + timedelta(minutes=1),
            MarketDataFailureReason.missing_provider_symbol,
        ),
    )

    row = repo.rows[("one", PROVIDER)]
    assert missing is not None and missing.state is MarketDataHealthState.unavailable
    assert row.provider_symbol is None
    assert row.last_failure_reason is MarketDataFailureReason.missing_provider_symbol
    assert row.lease_owner is None and row.lease_expires_at is None


@pytest.mark.asyncio
async def test_foreign_completion_and_identity_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.market_data import health_service

    monkeypatch.setattr(health_service, "MarketDataListingHealthModel", FakeRow)
    repo = FakeRepository()
    service = MarketDataHealthService(repo)  # type: ignore[arg-type]
    assert not await service.claim(
        listing_id="one",
        provider=PROVIDER,
        provider_symbol="WRONG",
        lease_owner="worker-a",
        now=NOW,
        lease_for=timedelta(seconds=30),
    )
    assert await service.claim(
        listing_id="one",
        provider=PROVIDER,
        provider_symbol="AAPL",
        lease_owner="worker-a",
        now=NOW,
        lease_for=timedelta(seconds=30),
    )
    assert (
        await service.record(
            listing_id="one",
            provider=PROVIDER,
            provider_symbol="AAPL",
            lease_owner="worker-b",
            outcome=outcome("b", NOW),
        )
        is None
    )
    assert repo.rows[("one", PROVIDER)].last_attempt_token is None
    assert (
        await service.record(
            listing_id="one",
            provider=PROVIDER,
            provider_symbol="AAPL",
            outcome=outcome("unclaimed", NOW),
        )
        is None
    )
    repo.transaction = False
    with pytest.raises(RuntimeError):
        await service.record(
            listing_id="one",
            provider=PROVIDER,
            provider_symbol="AAPL",
            lease_owner="worker-a",
            outcome=outcome("a", NOW),
        )


def test_health_id_is_stable_and_scoped() -> None:
    assert health_id("one", PROVIDER) == health_id("one", PROVIDER)
    assert health_id("one", PROVIDER) != health_id("two", PROVIDER)
    assert health_id("one", PROVIDER) != health_id("one", PriceSource.coingecko)


@pytest.mark.asyncio
async def test_identity_requires_exact_listing_mapping() -> None:
    class Session:
        def __init__(self, listing, aliases, listing_count=1):
            self.listing = listing
            self.aliases = aliases
            self.listing_count = listing_count

        def in_transaction(self):
            return True

        async def scalar(self, statement):
            description = statement.column_descriptions[0]
            return self.listing_count if description.get("name") == "count" else self.listing

        async def scalars(self, statement):
            return self.aliases

    listing = SimpleNamespace(asset_id="asset-one", provider=None, provider_symbol=None)
    alias = SimpleNamespace(listing_id=None, external_id="bitcoin")
    session = Session(listing, (alias,))
    repo = MarketDataHealthRepository(session)  # type: ignore[arg-type]
    assert await repo.validate_identity("one", PriceSource.coingecko, "bitcoin")
    assert not await repo.validate_identity("one", PriceSource.coingecko, "other")
    session.aliases = ()
    assert not await repo.validate_identity("one", PriceSource.coingecko, "bitcoin")
    listing.provider = PriceSource.coingecko
    listing.provider_symbol = "bitcoin"
    assert await repo.validate_identity("one", PriceSource.coingecko, "bitcoin")
    # An explicit direct providerSymbol is authoritative over legacy suggestions.
    session.aliases = (SimpleNamespace(listing_id=None, external_id="conflict"),)
    assert await repo.validate_identity("one", PriceSource.coingecko, "bitcoin")

    listing.provider = None
    listing.provider_symbol = None
    session.aliases = (SimpleNamespace(listing_id="one", external_id="scoped"),)
    assert await repo.validate_identity("one", PROVIDER, "scoped")
    session.aliases = (SimpleNamespace(listing_id=None, external_id="legacy"),)
    assert await repo.validate_identity("one", PROVIDER, "legacy")
    session.listing_count = 2
    assert not await repo.validate_identity("one", PROVIDER, "legacy")
