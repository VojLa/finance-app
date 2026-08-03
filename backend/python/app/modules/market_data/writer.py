"""Atomic append-only writer for exact price and FX observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid5

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import ExchangeRateSource, PriceSource
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.modules.fx.models import ExchangeRateObservation
from app.modules.fx.validation import (
    ExchangeRateObservationValidationError,
    validate_exchange_rate_observation,
)
from app.modules.market_data.models import (
    ExchangeRateRequirement,
    MarketEvidenceConflictError,
    MarketEvidenceStateError,
    PriceRequirement,
)
from app.modules.market_data.policy import MarketEvidencePolicy
from app.modules.market_data.writer_repository import (
    MarketEvidenceWriterRepository,
    exchange_rate_lock_scope,
    price_lock_scope,
)
from app.modules.prices.models import PriceObservation
from app.modules.prices.validation import (
    PriceObservationValidationError,
    validate_price_observation,
)

PRICE_SNAPSHOT_NAMESPACE = UUID("8c46da0b-b09a-49c7-94f1-a510cf4c2f7c")
EXCHANGE_RATE_NAMESPACE = UUID("93484f65-330c-47e9-a592-49e4fd9a5122")
_MAX_TRANSACTION_ATTEMPTS = 3
_RETRYABLE_SQLSTATES = {"40001", "40P01", "23505"}


class MarketEvidenceWriteDisposition(StrEnum):
    created = "created"
    replayed = "replayed"


@dataclass(frozen=True, slots=True)
class PersistMarketEvidenceCommand:
    price_observations: tuple[PriceObservation, ...]
    exchange_rate_observations: tuple[ExchangeRateObservation, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class PersistMarketEvidenceResult:
    price_ids: tuple[str, ...]
    exchange_rate_ids: tuple[str, ...]
    prices_created: int
    prices_replayed: int
    rates_created: int
    rates_replayed: int


class _Repository(Protocol):
    async def set_transaction_serializable(self) -> None: ...

    async def acquire_identity_locks(self, scopes: tuple[str, ...]) -> None: ...

    async def load_price(
        self,
        *,
        listing_id: str,
        observed_at: datetime,
        source: PriceSource,
    ) -> PriceSnapshotModel | None: ...

    async def load_exchange_rate(
        self,
        *,
        from_currency: str,
        to_currency: str,
        effective_at: datetime,
        source: ExchangeRateSource,
    ) -> ExchangeRateModel | None: ...

    async def load_price_by_id(self, price_id: str) -> PriceSnapshotModel | None: ...

    async def load_exchange_rate_by_id(
        self,
        rate_id: str,
    ) -> ExchangeRateModel | None: ...

    def add_price(self, row: PriceSnapshotModel) -> None: ...

    def add_exchange_rate(self, row: ExchangeRateModel) -> None: ...

    async def flush(self) -> None: ...

    async def reload_price(self, price_id: str) -> PriceSnapshotModel | None: ...

    async def reload_exchange_rate(
        self,
        rate_id: str,
    ) -> ExchangeRateModel | None: ...


def _fail() -> MarketEvidenceStateError:
    return MarketEvidenceStateError()


def _timestamp(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is not None
        or value.microsecond % 1_000 != 0
    ):
        raise _fail()
    return value


def price_snapshot_id(observation: PriceObservation) -> str:
    identity = "\0".join(
        (
            observation.listing_id,
            observation.observed_at.isoformat(timespec="milliseconds"),
            observation.provider.value,
        )
    )
    return str(uuid5(PRICE_SNAPSHOT_NAMESPACE, identity))


def exchange_rate_id(observation: ExchangeRateObservation) -> str:
    identity = "\0".join(
        (
            observation.from_currency,
            observation.to_currency,
            observation.effective_at.isoformat(timespec="milliseconds"),
            observation.provider.value,
        )
    )
    return str(uuid5(EXCHANGE_RATE_NAMESPACE, identity))


def _canonical_price(value: object) -> PriceObservation:
    if not isinstance(value, PriceObservation):
        raise _fail()
    try:
        return validate_price_observation(
            value,
            requirement=PriceRequirement(
                account_id="writer",
                asset_id=value.asset_id,
                listing_id=value.listing_id,
                listing_currency=value.currency,
                provider=value.provider,
                provider_symbol=value.provider_symbol,
                through=value.observed_at,
            ),
            policy=MarketEvidencePolicy(
                maximum_price_age=timedelta(milliseconds=1),
                maximum_fx_age=timedelta(milliseconds=1),
            ),
        )
    except PriceObservationValidationError as exc:
        raise _fail() from exc


def _canonical_rate(value: object) -> ExchangeRateObservation:
    if not isinstance(value, ExchangeRateObservation):
        raise _fail()
    try:
        return validate_exchange_rate_observation(
            value,
            requirement=ExchangeRateRequirement(
                from_currency=value.from_currency,
                to_currency=value.to_currency,
                through=value.effective_at,
                provider=value.provider,
            ),
            policy=MarketEvidencePolicy(
                maximum_price_age=timedelta(milliseconds=1),
                maximum_fx_age=timedelta(milliseconds=1),
            ),
        )
    except ExchangeRateObservationValidationError as exc:
        raise _fail() from exc


def _validate_command(
    value: object,
) -> tuple[
    tuple[PriceObservation, ...],
    tuple[ExchangeRateObservation, ...],
    datetime,
]:
    if (
        not isinstance(value, PersistMarketEvidenceCommand)
        or not isinstance(value.price_observations, tuple)
        or not isinstance(value.exchange_rate_observations, tuple)
    ):
        raise _fail()
    prices = tuple(_canonical_price(item) for item in value.price_observations)
    rates = tuple(_canonical_rate(item) for item in value.exchange_rate_observations)
    price_keys = {(item.listing_id, item.observed_at, item.provider) for item in prices}
    rate_keys = {
        (item.from_currency, item.to_currency, item.effective_at, item.provider) for item in rates
    }
    if len(price_keys) != len(prices) or len(rate_keys) != len(rates):
        raise _fail()
    return (
        tuple(
            sorted(
                prices,
                key=lambda item: (
                    item.listing_id,
                    item.observed_at,
                    item.provider.value,
                ),
            )
        ),
        tuple(
            sorted(
                rates,
                key=lambda item: (
                    item.from_currency,
                    item.to_currency,
                    item.effective_at,
                    item.provider.value,
                ),
            )
        ),
        _timestamp(value.created_at),
    )


def _price_matches(
    row: object,
    observation: PriceObservation,
    expected_id: str,
    *,
    created_at: datetime | None = None,
) -> bool:
    return (
        isinstance(row, PriceSnapshotModel)
        and row.id == expected_id
        and row.asset_id == observation.asset_id
        and row.listing_id == observation.listing_id
        and row.price == observation.price
        and row.currency == observation.currency
        and row.source is observation.provider
        and row.timestamp == observation.observed_at
        and isinstance(row.created_at, datetime)
        and (created_at is None or row.created_at == created_at)
    )


def _rate_matches(
    row: object,
    observation: ExchangeRateObservation,
    expected_id: str,
    *,
    created_at: datetime | None = None,
) -> bool:
    return (
        isinstance(row, ExchangeRateModel)
        and row.id == expected_id
        and row.from_currency == observation.from_currency
        and row.to_currency == observation.to_currency
        and row.rate == observation.rate
        and row.source is observation.provider
        and row.date == observation.effective_at
        and isinstance(row.created_at, datetime)
        and (created_at is None or row.created_at == created_at)
    )


def _sqlstate(error: BaseException) -> str | None:
    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        candidate = pending.pop()
        if id(candidate) in seen:
            continue
        seen.add(id(candidate))
        for attribute in ("sqlstate", "pgcode"):
            value = getattr(candidate, attribute, None)
            if isinstance(value, str):
                return value
        for attribute in ("orig", "__cause__", "__context__"):
            nested = getattr(candidate, attribute, None)
            if isinstance(nested, BaseException):
                pending.append(nested)
    return None


class MarketEvidenceWriter:
    """Own one complete append-only SERIALIZABLE batch per attempt."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        repository: _Repository | None = None,
    ) -> None:
        self.session = session
        self.repository = repository or MarketEvidenceWriterRepository(session)

    async def write(
        self,
        command: PersistMarketEvidenceCommand,
    ) -> PersistMarketEvidenceResult:
        prices, rates, created_at = _validate_command(command)
        if self.session.in_transaction():
            raise _fail()
        for attempt in range(_MAX_TRANSACTION_ATTEMPTS):
            try:
                async with self.session.begin():
                    return await self._write_attempt(
                        prices=prices,
                        rates=rates,
                        created_at=created_at,
                    )
            except (MarketEvidenceConflictError, MarketEvidenceStateError):
                raise
            except SQLAlchemyError as exc:
                if (
                    _sqlstate(exc) in _RETRYABLE_SQLSTATES
                    and attempt + 1 < _MAX_TRANSACTION_ATTEMPTS
                ):
                    continue
                raise _fail() from exc
        raise _fail()

    async def _write_attempt(
        self,
        *,
        prices: tuple[PriceObservation, ...],
        rates: tuple[ExchangeRateObservation, ...],
        created_at: datetime,
    ) -> PersistMarketEvidenceResult:
        await self.repository.set_transaction_serializable()
        scopes = tuple(
            sorted(
                (
                    *(
                        price_lock_scope(
                            listing_id=item.listing_id,
                            observed_at=item.observed_at,
                            source=item.provider,
                        )
                        for item in prices
                    ),
                    *(
                        exchange_rate_lock_scope(
                            from_currency=item.from_currency,
                            to_currency=item.to_currency,
                            effective_at=item.effective_at,
                            source=item.provider,
                        )
                        for item in rates
                    ),
                )
            )
        )
        await self.repository.acquire_identity_locks(scopes)

        price_ids: list[str] = []
        rate_ids: list[str] = []
        created_prices: list[tuple[PriceObservation, str]] = []
        created_rates: list[tuple[ExchangeRateObservation, str]] = []
        prices_replayed = 0
        rates_replayed = 0

        for price_observation in prices:
            expected_id = price_snapshot_id(price_observation)
            price_ids.append(expected_id)
            existing_price = await self.repository.load_price(
                listing_id=price_observation.listing_id,
                observed_at=price_observation.observed_at,
                source=price_observation.provider,
            )
            if existing_price is not None:
                if not _price_matches(existing_price, price_observation, expected_id):
                    raise MarketEvidenceConflictError()
                prices_replayed += 1
                continue
            if await self.repository.load_price_by_id(expected_id) is not None:
                raise MarketEvidenceConflictError()
            created_prices.append((price_observation, expected_id))

        for rate_observation in rates:
            expected_id = exchange_rate_id(rate_observation)
            rate_ids.append(expected_id)
            existing_rate = await self.repository.load_exchange_rate(
                from_currency=rate_observation.from_currency,
                to_currency=rate_observation.to_currency,
                effective_at=rate_observation.effective_at,
                source=rate_observation.provider,
            )
            if existing_rate is not None:
                if not _rate_matches(existing_rate, rate_observation, expected_id):
                    raise MarketEvidenceConflictError()
                rates_replayed += 1
                continue
            if await self.repository.load_exchange_rate_by_id(expected_id) is not None:
                raise MarketEvidenceConflictError()
            created_rates.append((rate_observation, expected_id))

        for price_observation, expected_id in created_prices:
            self.repository.add_price(
                PriceSnapshotModel(
                    id=expected_id,
                    asset_id=price_observation.asset_id,
                    listing_id=price_observation.listing_id,
                    price=price_observation.price,
                    currency=price_observation.currency,
                    source=price_observation.provider,
                    timestamp=price_observation.observed_at,
                    created_at=created_at,
                )
            )
        for rate_observation, expected_id in created_rates:
            self.repository.add_exchange_rate(
                ExchangeRateModel(
                    id=expected_id,
                    from_currency=rate_observation.from_currency,
                    to_currency=rate_observation.to_currency,
                    rate=rate_observation.rate,
                    date=rate_observation.effective_at,
                    source=rate_observation.provider,
                    created_at=created_at,
                )
            )

        await self.repository.flush()
        for price_observation, expected_id in created_prices:
            persisted_price = await self.repository.reload_price(expected_id)
            if not _price_matches(
                persisted_price,
                price_observation,
                expected_id,
                created_at=created_at,
            ):
                raise _fail()
        for rate_observation, expected_id in created_rates:
            persisted_rate = await self.repository.reload_exchange_rate(expected_id)
            if not _rate_matches(
                persisted_rate,
                rate_observation,
                expected_id,
                created_at=created_at,
            ):
                raise _fail()
        return PersistMarketEvidenceResult(
            price_ids=tuple(sorted(price_ids)),
            exchange_rate_ids=tuple(sorted(rate_ids)),
            prices_created=len(created_prices),
            prices_replayed=prices_replayed,
            rates_created=len(created_rates),
            rates_replayed=rates_replayed,
        )
