"""Explicit PostgreSQL lock and persistence boundary for market evidence."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import ExchangeRateSource, PriceSource
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel


def advisory_lock_id(scope: str) -> int:
    return int.from_bytes(sha256(scope.encode()).digest()[:8], "big", signed=True)


def price_lock_scope(
    *,
    listing_id: str,
    observed_at: datetime,
    source: PriceSource,
) -> str:
    return "\0".join(
        (
            "market_evidence:price",
            listing_id,
            observed_at.isoformat(timespec="milliseconds"),
            source.value,
        )
    )


def exchange_rate_lock_scope(
    *,
    from_currency: str,
    to_currency: str,
    effective_at: datetime,
    source: ExchangeRateSource,
) -> str:
    return "\0".join(
        (
            "market_evidence:fx",
            from_currency,
            to_currency,
            effective_at.isoformat(timespec="milliseconds"),
            source.value,
        )
    )


class MarketEvidenceWriterRepository:
    """Helpers assume one active writer-owned SERIALIZABLE attempt."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def set_transaction_serializable(self) -> None:
        await self.session.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))

    async def acquire_identity_locks(self, scopes: tuple[str, ...]) -> None:
        for scope in scopes:
            await self.session.execute(select(func.pg_advisory_xact_lock(advisory_lock_id(scope))))

    async def load_price(
        self,
        *,
        listing_id: str,
        observed_at: datetime,
        source: PriceSource,
    ) -> PriceSnapshotModel | None:
        return await self.session.scalar(
            select(PriceSnapshotModel)
            .where(
                PriceSnapshotModel.listing_id == listing_id,
                PriceSnapshotModel.timestamp == observed_at,
                PriceSnapshotModel.source == source,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_exchange_rate(
        self,
        *,
        from_currency: str,
        to_currency: str,
        effective_at: datetime,
        source: ExchangeRateSource,
    ) -> ExchangeRateModel | None:
        return await self.session.scalar(
            select(ExchangeRateModel)
            .where(
                ExchangeRateModel.from_currency == from_currency,
                ExchangeRateModel.to_currency == to_currency,
                ExchangeRateModel.date == effective_at,
                ExchangeRateModel.source == source,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_price_by_id(self, price_id: str) -> PriceSnapshotModel | None:
        return await self.session.scalar(
            select(PriceSnapshotModel)
            .where(PriceSnapshotModel.id == price_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def load_exchange_rate_by_id(
        self,
        rate_id: str,
    ) -> ExchangeRateModel | None:
        return await self.session.scalar(
            select(ExchangeRateModel)
            .where(ExchangeRateModel.id == rate_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def add_price(self, row: PriceSnapshotModel) -> None:
        self.session.add(row)

    def add_exchange_rate(self, row: ExchangeRateModel) -> None:
        self.session.add(row)

    async def flush(self) -> None:
        await self.session.flush()

    async def reload_price(self, price_id: str) -> PriceSnapshotModel | None:
        return await self.session.scalar(
            select(PriceSnapshotModel)
            .where(PriceSnapshotModel.id == price_id)
            .execution_options(populate_existing=True)
        )

    async def reload_exchange_rate(
        self,
        rate_id: str,
    ) -> ExchangeRateModel | None:
        return await self.session.scalar(
            select(ExchangeRateModel)
            .where(ExchangeRateModel.id == rate_id)
            .execution_options(populate_existing=True)
        )
