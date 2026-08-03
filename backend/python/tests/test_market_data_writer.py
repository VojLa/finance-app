from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid5

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.db.models.enums import ExchangeRateSource, PriceSource
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.modules.fx.models import ExchangeRateObservation
from app.modules.market_data.models import (
    MarketEvidenceConflictError,
    MarketEvidenceStateError,
)
from app.modules.market_data.writer import (
    EXCHANGE_RATE_NAMESPACE,
    PRICE_SNAPSHOT_NAMESPACE,
    MarketEvidenceWriter,
    PersistMarketEvidenceCommand,
    exchange_rate_id,
    price_snapshot_id,
)
from app.modules.market_data.writer_repository import (
    exchange_rate_lock_scope,
    price_lock_scope,
)
from app.modules.prices.models import PriceObservation

OBSERVED_AT = datetime(2026, 8, 3, 10, 11, 12, 123000)
CREATED_AT = datetime(2026, 8, 3, 10, 12, 0, 456000)


class _Transaction:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> None:
        self.session.active = True
        self.session.begin_count += 1

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            self.session.commit_count += 1
        else:
            self.session.rollback_count += 1
        self.session.active = False


class _Session:
    def __init__(self) -> None:
        self.active = False
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def in_transaction(self) -> bool:
        return self.active

    def begin(self) -> _Transaction:
        return _Transaction(self)


class _DriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("controlled")
        self.sqlstate = sqlstate


class _SqlStateError(SQLAlchemyError):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("controlled")
        self.orig = _DriverError(sqlstate)


class _Repository:
    def __init__(self) -> None:
        self.prices: dict[tuple[object, ...], PriceSnapshotModel] = {}
        self.rates: dict[tuple[object, ...], ExchangeRateModel] = {}
        self.price_ids: dict[str, PriceSnapshotModel] = {}
        self.rate_ids: dict[str, ExchangeRateModel] = {}
        self.calls: list[object] = []
        self.flush_errors: list[SQLAlchemyError] = []
        self.reload_price_mismatch = False
        self.reload_rate_mismatch = False

    async def set_transaction_serializable(self) -> None:
        self.calls.append("serializable")

    async def acquire_identity_locks(self, scopes: tuple[str, ...]) -> None:
        self.calls.append(("locks", scopes))

    async def load_price(self, **values: object) -> PriceSnapshotModel | None:
        self.calls.append(("price", values))
        return self.prices.get((values["listing_id"], values["observed_at"], values["source"]))

    async def load_exchange_rate(self, **values: object) -> ExchangeRateModel | None:
        self.calls.append(("rate", values))
        return self.rates.get(
            (
                values["from_currency"],
                values["to_currency"],
                values["effective_at"],
                values["source"],
            )
        )

    async def load_price_by_id(self, price_id: str) -> PriceSnapshotModel | None:
        self.calls.append(("price-id", price_id))
        return self.price_ids.get(price_id)

    async def load_exchange_rate_by_id(
        self,
        rate_id: str,
    ) -> ExchangeRateModel | None:
        self.calls.append(("rate-id", rate_id))
        return self.rate_ids.get(rate_id)

    def add_price(self, row: PriceSnapshotModel) -> None:
        self.calls.append(("add-price", row.id))
        self.prices[(row.listing_id, row.timestamp, row.source)] = row
        self.price_ids[row.id] = row

    def add_exchange_rate(self, row: ExchangeRateModel) -> None:
        self.calls.append(("add-rate", row.id))
        self.rates[(row.from_currency, row.to_currency, row.date, row.source)] = row
        self.rate_ids[row.id] = row

    async def flush(self) -> None:
        self.calls.append("flush")
        if self.flush_errors:
            raise self.flush_errors.pop(0)

    async def reload_price(self, price_id: str) -> PriceSnapshotModel | None:
        self.calls.append(("reload-price", price_id))
        row = self.price_ids.get(price_id)
        if row is not None and self.reload_price_mismatch:
            row.price = Decimal("999")
        return row

    async def reload_exchange_rate(
        self,
        rate_id: str,
    ) -> ExchangeRateModel | None:
        self.calls.append(("reload-rate", rate_id))
        row = self.rate_ids.get(rate_id)
        if row is not None and self.reload_rate_mismatch:
            row.rate = Decimal("999")
        return row


def _price(
    *,
    listing_id: str = "listing-1",
    price: str = "10.1234567890",
) -> PriceObservation:
    return PriceObservation(
        asset_id=f"asset-{listing_id[-1]}",
        listing_id=listing_id,
        provider=PriceSource.yahoo_finance,
        provider_symbol=f"SYMBOL-{listing_id[-1]}",
        price=Decimal(price),
        currency="EUR",
        observed_at=OBSERVED_AT,
    )


def _rate(*, rate: str = "25.12345678") -> ExchangeRateObservation:
    return ExchangeRateObservation(
        from_currency="EUR",
        to_currency="CZK",
        provider=ExchangeRateSource.ecb,
        rate=Decimal(rate),
        effective_at=OBSERVED_AT,
    )


def _command(
    *,
    prices: tuple[PriceObservation, ...] | None = None,
    rates: tuple[ExchangeRateObservation, ...] | None = None,
) -> PersistMarketEvidenceCommand:
    return PersistMarketEvidenceCommand(
        price_observations=prices if prices is not None else (_price(),),
        exchange_rate_observations=rates if rates is not None else (_rate(),),
        created_at=CREATED_AT,
    )


def _writer() -> tuple[MarketEvidenceWriter, _Session, _Repository]:
    session = _Session()
    repository = _Repository()
    return (
        MarketEvidenceWriter(cast(Any, session), repository=repository),
        session,
        repository,
    )


def _price_row(observation: PriceObservation) -> PriceSnapshotModel:
    return PriceSnapshotModel(
        id=price_snapshot_id(observation),
        asset_id=observation.asset_id,
        listing_id=observation.listing_id,
        price=observation.price,
        currency=observation.currency,
        source=observation.provider,
        timestamp=observation.observed_at,
        created_at=CREATED_AT,
    )


def _rate_row(observation: ExchangeRateObservation) -> ExchangeRateModel:
    return ExchangeRateModel(
        id=exchange_rate_id(observation),
        from_currency=observation.from_currency,
        to_currency=observation.to_currency,
        rate=observation.rate,
        source=observation.provider,
        date=observation.effective_at,
        created_at=CREATED_AT,
    )


def test_deterministic_ids_use_fixed_documented_namespaces() -> None:
    price = _price()
    rate = _rate()
    assert PRICE_SNAPSHOT_NAMESPACE == UUID("8c46da0b-b09a-49c7-94f1-a510cf4c2f7c")
    assert EXCHANGE_RATE_NAMESPACE == UUID("93484f65-330c-47e9-a592-49e4fd9a5122")
    assert price_snapshot_id(price) == str(
        uuid5(
            PRICE_SNAPSHOT_NAMESPACE,
            "\0".join(
                (
                    "listing-1",
                    "2026-08-03T10:11:12.123",
                    "yahoo_finance",
                )
            ),
        )
    )
    assert exchange_rate_id(rate) == str(
        uuid5(
            EXCHANGE_RATE_NAMESPACE,
            "\0".join(
                (
                    "EUR",
                    "CZK",
                    "2026-08-03T10:11:12.123",
                    "ecb",
                )
            ),
        )
    )


def test_lock_scopes_are_exact_namespaced_identities() -> None:
    assert price_lock_scope(
        listing_id="listing-1",
        observed_at=OBSERVED_AT,
        source=PriceSource.yahoo_finance,
    ) == "\0".join(
        (
            "market_evidence:price",
            "listing-1",
            "2026-08-03T10:11:12.123",
            "yahoo_finance",
        )
    )
    assert exchange_rate_lock_scope(
        from_currency="EUR",
        to_currency="CZK",
        effective_at=OBSERVED_AT,
        source=ExchangeRateSource.ecb,
    ) == "\0".join(
        (
            "market_evidence:fx",
            "EUR",
            "CZK",
            "2026-08-03T10:11:12.123",
            "ecb",
        )
    )


@pytest.mark.asyncio
async def test_writer_creates_complete_price_and_fx_batch() -> None:
    writer, session, repository = _writer()
    result = await writer.write(_command())

    assert result.prices_created == 1
    assert result.rates_created == 1
    assert result.prices_replayed == 0
    assert result.rates_replayed == 0
    assert result.price_ids == tuple(sorted(result.price_ids))
    assert result.exchange_rate_ids == tuple(sorted(result.exchange_rate_ids))
    assert session.begin_count == session.commit_count == 1
    assert session.rollback_count == 0
    assert repository.calls[0] == "serializable"
    lock_call = cast(tuple[str, tuple[str, ...]], repository.calls[1])
    assert lock_call[0] == "locks"
    assert lock_call[1] == tuple(sorted(lock_call[1]))


@pytest.mark.asyncio
async def test_writer_exact_replay_is_read_only() -> None:
    writer, _, repository = _writer()
    price = _price()
    rate = _rate()
    price_row = _price_row(price)
    rate_row = _rate_row(rate)
    repository.prices[(price.listing_id, price.observed_at, price.provider)] = price_row
    repository.price_ids[price_row.id] = price_row
    repository.rates[(rate.from_currency, rate.to_currency, rate.effective_at, rate.provider)] = (
        rate_row
    )
    repository.rate_ids[rate_row.id] = rate_row

    result = await writer.write(_command())

    assert result.prices_created == result.rates_created == 0
    assert result.prices_replayed == result.rates_replayed == 1
    assert not any(
        isinstance(call, tuple) and call[0] in {"add-price", "add-rate"}
        for call in repository.calls
    )


@pytest.mark.asyncio
async def test_writer_supports_mix_of_create_and_replay() -> None:
    writer, _, repository = _writer()
    first = _price(listing_id="listing-1")
    second = _price(listing_id="listing-2")
    existing = _price_row(first)
    repository.prices[(first.listing_id, first.observed_at, first.provider)] = existing
    repository.price_ids[existing.id] = existing

    result = await writer.write(_command(prices=(second, first), rates=()))

    assert result.prices_created == 1
    assert result.prices_replayed == 1
    assert result.rates_created == result.rates_replayed == 0


@pytest.mark.asyncio
async def test_one_conflict_rolls_back_complete_batch_without_retry() -> None:
    writer, session, repository = _writer()
    price = _price()
    repository.prices[(price.listing_id, price.observed_at, price.provider)] = _price_row(
        _price(price="999")
    )

    with pytest.raises(MarketEvidenceConflictError):
        await writer.write(_command())

    assert session.begin_count == 1
    assert session.rollback_count == 1
    assert session.commit_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("sqlstate", ["40001", "40P01", "23505"])
async def test_writer_retries_only_bounded_concurrency_failures(sqlstate: str) -> None:
    writer, session, repository = _writer()
    repository.flush_errors = [_SqlStateError(sqlstate)]

    result = await writer.write(_command())

    assert session.begin_count == 2
    assert session.rollback_count == 1
    assert session.commit_count == 1
    assert result.prices_replayed == 1
    assert result.rates_replayed == 1


@pytest.mark.asyncio
async def test_writer_does_not_retry_nonretryable_database_failure() -> None:
    writer, session, repository = _writer()
    repository.flush_errors = [_SqlStateError("22003")]
    with pytest.raises(MarketEvidenceStateError):
        await writer.write(_command())
    assert session.begin_count == 1
    assert session.rollback_count == 1


@pytest.mark.asyncio
async def test_writer_rejects_caller_active_session() -> None:
    writer, session, _ = _writer()
    session.active = True
    with pytest.raises(MarketEvidenceStateError):
        await writer.write(_command())


@pytest.mark.asyncio
async def test_writer_rejects_duplicate_or_overprecise_observations() -> None:
    writer, _, _ = _writer()
    with pytest.raises(MarketEvidenceStateError):
        await writer.write(_command(prices=(_price(), _price()), rates=()))
    with pytest.raises(MarketEvidenceStateError):
        await writer.write(
            _command(
                prices=(_price(price="1.00000000001"),),
                rates=(),
            )
        )


@pytest.mark.asyncio
async def test_reload_mismatch_fails_and_rolls_back() -> None:
    writer, session, repository = _writer()
    repository.reload_rate_mismatch = True
    with pytest.raises(MarketEvidenceStateError):
        await writer.write(_command())
    assert session.rollback_count == 1
