from __future__ import annotations

import asyncio
import os
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from typing import Any, cast

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetType,
    ExchangeRateSource,
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.prices import ExchangeRateModel, PriceSnapshotModel
from app.db.models.snapshots import AccountSnapshotItemModel, AccountSnapshotModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.holdings.rebuild_service import HoldingRebuildService
from app.modules.holdings.repository import HoldingRebuildRepository
from app.modules.imports.classification import classify_import_row
from app.modules.imports.posting_service import (
    ImportBatchPostingService,
    PostImportBatchCommand,
)
from app.modules.imports.repository import ImportBatchRepository
from app.modules.snapshots.financial_metrics import AccountSnapshotEvidenceStateError
from app.modules.snapshots.persistence_projection import (
    AccountSnapshotPersistenceProjectionError,
)
from app.modules.snapshots.writer import (
    AccountSnapshotWriteConflictError,
    AccountSnapshotWriteDisposition,
    AccountSnapshotWriter,
    AccountSnapshotWriteStateError,
    WriteAccountSnapshotCommand,
)
from app.modules.snapshots.writer_repository import AccountSnapshotWriterRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
BASE_AT = datetime(2030, 1, 1)


def _scenario_times(identity: str) -> tuple[datetime, datetime, datetime, datetime]:
    prefix = identity.removesuffix("-account")
    day_offset = int.from_bytes(sha256(prefix.encode()).digest()[:4], "big") % 20_000
    snapshot_at = BASE_AT + timedelta(days=day_offset)
    event_at = snapshot_at - timedelta(days=1)
    return (
        snapshot_at,
        event_at,
        snapshot_at + timedelta(minutes=1),
        snapshot_at + timedelta(minutes=2),
    )


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=6)


def _command(account_id: str, **changes: object) -> WriteAccountSnapshotCommand:
    snapshot_at, _, calculated_at, created_at = _scenario_times(account_id)
    values: dict[str, object] = {
        "account_id": account_id,
        "snapshot_timestamp": snapshot_at,
        "granularity": SnapshotGranularity.day,
        "source": SnapshotSource.manual_recalculation,
        "calculation_version": 1,
        "calculated_at": calculated_at,
        "created_at": created_at,
        "is_recalculated": True,
    }
    values.update(changes)
    return WriteAccountSnapshotCommand(**cast(Any, values))


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        account_ids = tuple(
            await session.scalars(
                select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
            )
        )
        snapshot_ids = tuple(
            await session.scalars(
                select(AccountSnapshotModel.id).where(
                    AccountSnapshotModel.account_id.in_(account_ids)
                )
            )
        )
        if snapshot_ids:
            await session.execute(
                delete(AccountSnapshotItemModel).where(
                    AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids)
                )
            )
        if account_ids:
            batch_ids = tuple(
                await session.scalars(
                    select(ImportBatchModel.id).where(ImportBatchModel.account_id.in_(account_ids))
                )
            )
            if batch_ids:
                await session.execute(
                    delete(ImportRowModel).where(ImportRowModel.import_batch_id.in_(batch_ids))
                )
            await session.execute(
                delete(AccountSnapshotModel).where(AccountSnapshotModel.account_id.in_(account_ids))
            )
            await session.execute(
                delete(InvestmentMovementModel).where(
                    InvestmentMovementModel.account_id.in_(account_ids)
                )
            )
            await session.execute(
                delete(InvestmentEventModel).where(InvestmentEventModel.account_id.in_(account_ids))
            )
            await session.execute(
                delete(HoldingModel).where(HoldingModel.account_id.in_(account_ids))
            )
            if batch_ids:
                await session.execute(
                    delete(ImportBatchModel).where(ImportBatchModel.id.in_(batch_ids))
                )
            await session.execute(
                delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
            )
        await session.execute(
            delete(PriceSnapshotModel).where(PriceSnapshotModel.id.startswith(f"{prefix}-"))
        )
        await session.execute(
            delete(ExchangeRateModel).where(ExchangeRateModel.id.startswith(f"{prefix}-"))
        )
        await session.execute(
            delete(AssetListingModel).where(AssetListingModel.id.startswith(f"{prefix}-listing"))
        )
        await session.execute(delete(AssetModel).where(AssetModel.id.startswith(f"{prefix}-asset")))
        if account_ids:
            await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        await session.execute(delete(UserModel).where(UserModel.id.startswith(f"{prefix}-")))
        await session.commit()
    await engine.dispose()


async def _seed_investment(prefix: str) -> str:
    account_id = f"{prefix}-account"
    snapshot_at, event_at, _, _ = _scenario_times(account_id)
    asset_id = f"{prefix}-asset"
    listing_id = f"{prefix}-listing"
    symbol = prefix.replace("-", "").upper()[-16:]
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            AccountModel(
                id=account_id,
                name="Broker",
                type=AccountType.broker,
                currency="CZK",
                color=None,
                notes=None,
                is_archived=False,
                archived_at=None,
                created_at=event_at,
                updated_at=event_at,
            )
        )
        session.add(
            AssetModel(
                id=asset_id,
                symbol=symbol,
                isin=None,
                name=symbol,
                asset_type=AssetType.stock,
                currency="EUR",
                created_at=event_at,
                updated_at=event_at,
            )
        )
        await session.flush()
        session.add(
            AssetListingModel(
                id=listing_id,
                asset_id=asset_id,
                symbol=symbol,
                exchange="trading212",
                mic=None,
                currency="EUR",
                country=None,
                provider=PriceSource.broker,
                provider_symbol=symbol,
                is_primary=False,
                created_at=event_at,
                updated_at=event_at,
            )
        )
        await session.flush()
        session.add(
            HoldingModel(
                id=f"{prefix}-holding",
                account_id=account_id,
                asset_id=asset_id,
                listing_id=listing_id,
                symbol=symbol,
                name=symbol,
                asset_type=AssetType.stock,
                quantity=Decimal("2"),
                avg_buy_price=Decimal("10"),
                currency="EUR",
                current_price=None,
                current_value=None,
                unrealized_pnl=None,
                realized_pnl=None,
                calculated_at=snapshot_at,
                updated_at=snapshot_at,
            )
        )
        session.add_all(
            [
                PriceSnapshotModel(
                    id=f"{prefix}-price",
                    asset_id=asset_id,
                    listing_id=listing_id,
                    price=Decimal("15"),
                    currency="EUR",
                    source=PriceSource.broker,
                    timestamp=snapshot_at,
                    created_at=snapshot_at,
                ),
                ExchangeRateModel(
                    id=f"{prefix}-event-rate",
                    from_currency="EUR",
                    to_currency="CZK",
                    rate=Decimal("20"),
                    date=event_at,
                    source=ExchangeRateSource.ecb,
                    created_at=event_at,
                ),
                ExchangeRateModel(
                    id=f"{prefix}-snapshot-rate",
                    from_currency="EUR",
                    to_currency="CZK",
                    rate=Decimal("25"),
                    date=snapshot_at,
                    source=ExchangeRateSource.ecb,
                    created_at=snapshot_at,
                ),
            ]
        )
        session.add(
            InvestmentEventModel(
                id=f"{prefix}-deposit",
                account_id=account_id,
                type=InvestmentEventType.cash_deposit,
                date=event_at,
                source=ImportSource.trading212,
                external_id=None,
                order_id=None,
                description=None,
                realized_pnl=None,
                realized_pnl_currency=None,
                import_batch_id=None,
                archived_at=None,
                deleted_at=None,
                created_at=event_at,
                updated_at=event_at,
            )
        )
        session.add(
            InvestmentEventModel(
                id=f"{prefix}-trade",
                account_id=account_id,
                type=InvestmentEventType.trade,
                date=event_at,
                source=ImportSource.trading212,
                external_id=f"{prefix}-trade",
                order_id=None,
                description=symbol,
                realized_pnl=None,
                realized_pnl_currency=None,
                import_batch_id=None,
                archived_at=None,
                deleted_at=None,
                created_at=event_at,
                updated_at=event_at,
            )
        )
        await session.flush()
        session.add_all(
            [
                InvestmentMovementModel(
                    id=f"{prefix}-cash",
                    event_id=f"{prefix}-deposit",
                    account_id=account_id,
                    asset_id=None,
                    listing_id=None,
                    kind=InvestmentMovementKind.cash,
                    direction=MovementDirection.incoming,
                    quantity=Decimal("10"),
                    currency="EUR",
                    price_per_unit=None,
                    value_amount=Decimal("10"),
                    value_currency="EUR",
                    source_symbol=None,
                    source_asset_type=None,
                    note=None,
                    created_at=event_at,
                    updated_at=event_at,
                ),
                InvestmentMovementModel(
                    id=f"{prefix}-trade-asset",
                    event_id=f"{prefix}-trade",
                    account_id=account_id,
                    asset_id=asset_id,
                    listing_id=listing_id,
                    kind=InvestmentMovementKind.asset,
                    direction=MovementDirection.incoming,
                    quantity=Decimal("2"),
                    currency=symbol,
                    price_per_unit=Decimal("10"),
                    value_amount=Decimal("20"),
                    value_currency="EUR",
                    source_symbol=symbol,
                    source_asset_type=AssetType.stock,
                    note=None,
                    created_at=event_at,
                    updated_at=event_at,
                ),
                InvestmentMovementModel(
                    id=f"{prefix}-trade-cash",
                    event_id=f"{prefix}-trade",
                    account_id=account_id,
                    asset_id=None,
                    listing_id=None,
                    kind=InvestmentMovementKind.cash,
                    direction=MovementDirection.outgoing,
                    quantity=Decimal("20"),
                    currency="EUR",
                    price_per_unit=None,
                    value_amount=Decimal("20"),
                    value_currency="EUR",
                    source_symbol=None,
                    source_asset_type=None,
                    note=None,
                    created_at=event_at,
                    updated_at=event_at,
                ),
            ]
        )
        await session.commit()
    await engine.dispose()
    return account_id


async def _seed_postable_cash_batch(prefix: str, account_id: str) -> AuthenticatedPrincipal:
    _, event_at, _, _ = _scenario_times(account_id)
    user_id = f"{prefix}-posting-user"
    batch_id = f"{prefix}-posting-batch"
    canonical: dict[str, Any] = {
        "schema_version": 2,
        "source": "trading212",
        "kind": "investment_event",
        "date": (event_at + timedelta(hours=1)).isoformat(),
        "action": "cash_deposit",
        "external_id": f"{prefix}-posting-deposit",
        "raw_action": "cash deposit",
        "asset": {
            "symbol": None,
            "isin": None,
            "name": None,
            "asset_type_hint": None,
        },
        "quantity": None,
        "price": None,
        "total": {"amount": "50", "currency": "EUR"},
        "fee": None,
        "conversion": None,
        "realized_pnl": None,
        "is_promotional": False,
        "note": None,
        "order_id": None,
        "asset_direction": None,
    }
    posting_intent = classify_import_row(
        source=ImportSource.trading212,
        normalized_data=canonical,
    ).model_dump(mode="json")
    normalized = deepcopy(canonical)
    normalized["deduplication"] = {"schema_version": 1, "status": "unique"}
    normalized["posting_intent"] = posting_intent
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            UserModel(
                id=user_id,
                email=f"{user_id}@example.com",
                name=user_id,
                password_hash=None,
                base_currency="CZK",
                created_at=event_at,
                updated_at=event_at,
            )
        )
        await session.flush()
        session.add(
            AccountMemberModel(
                id=f"{prefix}-posting-member",
                account_id=account_id,
                user_id=user_id,
                role=AccountMemberRole.owner,
                relation_type=AccountRelationType.owner,
                invited_by_id=None,
                accepted_at=event_at,
                created_at=event_at,
                updated_at=event_at,
            )
        )
        session.add(
            ImportBatchModel(
                id=batch_id,
                user_id=user_id,
                account_id=account_id,
                source=ImportSource.trading212,
                filename=f"{prefix}.csv",
                file_size=1,
                file_encoding="utf-8",
                checksum=sha256(prefix.encode()).hexdigest(),
                status=ImportStatus.processing,
                rows_total=1,
                rows_imported=0,
                rows_skipped=0,
                created_at=event_at,
                completed_at=None,
                retain_until=None,
                raw_data_purged_at=None,
            )
        )
        session.add(
            ImportRowModel(
                id=f"{prefix}-posting-row",
                import_batch_id=batch_id,
                row_number=1,
                raw_data={"test": prefix},
                normalized_data=normalized,
                validation_errors=None,
                deduplication_key=f"{prefix}-posting-deduplication",
                status=ImportRowStatus.pending,
                error_message=None,
                created_transaction_id=None,
                created_investment_event_id=None,
                created_at=event_at,
            )
        )
        await session.commit()
    await engine.dispose()
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.com",
        name=user_id,
    )


async def _counts(session: AsyncSession, account_id: str) -> tuple[int, int]:
    snapshots = (
        await session.scalar(
            select(func.count())
            .select_from(AccountSnapshotModel)
            .where(AccountSnapshotModel.account_id == account_id)
        )
        or 0
    )
    items = (
        await session.scalar(
            select(func.count())
            .select_from(AccountSnapshotItemModel)
            .join(
                AccountSnapshotModel,
                AccountSnapshotModel.id == AccountSnapshotItemModel.snapshot_id,
            )
            .where(AccountSnapshotModel.account_id == account_id)
        )
        or 0
    )
    return snapshots, items


@pytest.mark.asyncio
async def test_create_exact_snapshot_and_fresh_session_replay() -> None:
    prefix = "i5d-create"
    await _cleanup(prefix)
    account_id = await _seed_investment(prefix)
    snapshot_at, _, calculated_at, created_at = _scenario_times(account_id)
    engine = _engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            first = await AccountSnapshotWriter(session).write(_command(account_id))
            assert first.disposition is AccountSnapshotWriteDisposition.created

        async with AsyncSession(engine) as session:
            snapshot = await session.scalar(
                select(AccountSnapshotModel).where(AccountSnapshotModel.account_id == account_id)
            )
            assert snapshot is not None
            items = tuple(
                await session.scalars(
                    select(AccountSnapshotItemModel)
                    .where(AccountSnapshotItemModel.snapshot_id == snapshot.id)
                    .order_by(AccountSnapshotItemModel.listing_id)
                )
            )
            assert snapshot.id == first.snapshot_id
            assert snapshot.cash_value == Decimal("-250.000000")
            assert snapshot.investment_value == Decimal("750.000000")
            assert snapshot.investment_cost_basis == Decimal("500.000000")
            assert snapshot.net_deposits_value == Decimal("200.000000")
            assert snapshot.unrealized_pnl_value == Decimal("250.000000")
            assert snapshot.total_value == Decimal("500.000000")
            assert snapshot.created_at == created_at
            assert snapshot.calculated_at == calculated_at
            assert snapshot.exchange_rates == {
                "version": 1,
                "snapshotRates": [
                    {
                        "rateId": f"{prefix}-snapshot-rate",
                        "from": "EUR",
                        "to": "CZK",
                        "rate": "25.00000000",
                        "timestamp": snapshot_at.isoformat(timespec="milliseconds"),
                        "source": "ecb",
                    }
                ],
                "historicalRateIds": [f"{prefix}-event-rate"],
            }
            assert len(items) == 1
            assert items[0].value == Decimal("750.000000")
            assert items[0].native_value == Decimal("30.0000000000")
            assert await _counts(session, account_id) == (1, 1)

        async with AsyncSession(engine, expire_on_commit=False) as session:
            second = await AccountSnapshotWriter(session).write(_command(account_id))
            assert second.disposition is AccountSnapshotWriteDisposition.replayed
            assert second.snapshot_id == first.snapshot_id
        async with AsyncSession(engine) as session:
            assert await _counts(session, account_id) == (1, 1)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_metadata_conflict_and_persisted_corruption_are_not_repaired() -> None:
    prefix = "i5d-conflict"
    await _cleanup(prefix)
    account_id = await _seed_investment(prefix)
    _, _, _, created_at = _scenario_times(account_id)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            created = await AccountSnapshotWriter(session).write(_command(account_id))
        async with AsyncSession(engine) as session:
            with pytest.raises(AccountSnapshotWriteConflictError):
                await AccountSnapshotWriter(session).write(
                    _command(account_id, created_at=created_at + timedelta(minutes=1))
                )
        async with AsyncSession(engine) as session:
            snapshot = await session.get(AccountSnapshotModel, created.snapshot_id)
            assert snapshot is not None
            snapshot.cash_value = Decimal("999")
            await session.commit()
        async with AsyncSession(engine) as session:
            with pytest.raises(AccountSnapshotWriteConflictError):
                await AccountSnapshotWriter(session).write(_command(account_id))
        async with AsyncSession(engine) as session:
            snapshot = await session.get(AccountSnapshotModel, created.snapshot_id)
            assert snapshot is not None
            assert snapshot.cash_value == Decimal("999.000000")
            assert await _counts(session, account_id) == (1, 1)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [
        AccountType.bank,
        AccountType.cash,
        AccountType.savings,
        AccountType.credit_card,
        AccountType.loan,
        AccountType.mortgage,
    ],
)
async def test_unsupported_account_writes_nothing(account_type: AccountType) -> None:
    prefix = f"i5d-unsupported-{account_type.value}"
    await _cleanup(prefix)
    account_id = f"{prefix}-account"
    _, event_at, _, _ = _scenario_times(account_id)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                AccountModel(
                    id=account_id,
                    name="Unsupported",
                    type=account_type,
                    currency="CZK",
                    color=None,
                    notes=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=event_at,
                    updated_at=event_at,
                )
            )
            await session.commit()
        async with AsyncSession(engine) as session:
            expected_error = (
                AccountSnapshotPersistenceProjectionError
                if account_type in {AccountType.bank, AccountType.cash, AccountType.savings}
                else AccountSnapshotEvidenceStateError
            )
            with pytest.raises(expected_error):
                await AccountSnapshotWriter(session).write(_command(account_id))
        async with AsyncSession(engine) as session:
            assert await _counts(session, account_id) == (0, 0)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


class _BrokenItemsRepository(AccountSnapshotWriterRepository):
    def add_items(self, items: tuple[AccountSnapshotItemModel, ...]) -> None:
        items[0].listing_id = "missing-listing"
        super().add_items(items)


@pytest.mark.asyncio
async def test_item_flush_failure_rolls_back_snapshot_and_clean_retry_succeeds() -> None:
    prefix = "i5d-rollback"
    await _cleanup(prefix)
    account_id = await _seed_investment(prefix)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            with pytest.raises(AccountSnapshotWriteStateError):
                await AccountSnapshotWriter(
                    session,
                    repository=_BrokenItemsRepository(session),
                ).write(_command(account_id))
        async with AsyncSession(engine) as session:
            assert await _counts(session, account_id) == (0, 0)
        async with AsyncSession(engine) as session:
            result = await AccountSnapshotWriter(session).write(_command(account_id))
            assert result.disposition is AccountSnapshotWriteDisposition.created
        async with AsyncSession(engine) as session:
            assert await _counts(session, account_id) == (1, 1)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_ambiguous_price_fails_before_physical_write() -> None:
    prefix = "i5d-ambiguous"
    await _cleanup(prefix)
    account_id = await _seed_investment(prefix)
    snapshot_at, _, _, _ = _scenario_times(account_id)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                PriceSnapshotModel(
                    id=f"{prefix}-ambiguous-price",
                    asset_id=f"{prefix}-asset",
                    listing_id=f"{prefix}-listing",
                    price=Decimal("16"),
                    currency="EUR",
                    source=PriceSource.manual,
                    timestamp=snapshot_at,
                    created_at=snapshot_at,
                )
            )
            await session.commit()
        async with AsyncSession(engine) as session:
            with pytest.raises(AccountSnapshotEvidenceStateError):
                await AccountSnapshotWriter(session).write(_command(account_id))
        async with AsyncSession(engine) as session:
            assert await _counts(session, account_id) == (0, 0)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_ambiguous_fx_fails_before_physical_write() -> None:
    prefix = "i5d-ambiguous-fx"
    await _cleanup(prefix)
    account_id = await _seed_investment(prefix)
    snapshot_at, _, _, _ = _scenario_times(account_id)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                ExchangeRateModel(
                    id=f"{prefix}-ambiguous-rate",
                    from_currency="EUR",
                    to_currency="CZK",
                    rate=Decimal("26"),
                    date=snapshot_at,
                    source=ExchangeRateSource.manual,
                    created_at=snapshot_at,
                )
            )
            await session.commit()
        async with AsyncSession(engine) as session:
            with pytest.raises(AccountSnapshotEvidenceStateError):
                await AccountSnapshotWriter(session).write(_command(account_id))
        async with AsyncSession(engine) as session:
            assert await _counts(session, account_id) == (0, 0)
    finally:
        await engine.dispose()
        await _cleanup(prefix)


class _PausingMarketRepository(AccountSnapshotWriterRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        locked: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        super().__init__(session)
        self.locked = locked
        self.release = release

    async def lock_market_evidence_tables(self) -> None:
        await super().lock_market_evidence_tables()
        self.locked.set()
        await asyncio.wait_for(self.release.wait(), timeout=10)


@pytest.mark.asyncio
async def test_changed_price_evidence_waits_then_fails_without_mixed_snapshot() -> None:
    prefix = "i5d-price-change"
    await _cleanup(prefix)
    account_id = await _seed_investment(prefix)
    snapshot_at, _, _, _ = _scenario_times(account_id)
    engine = _engine()
    market_locked = asyncio.Event()
    release_writer = asyncio.Event()
    price_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:

        async def first_write():
            async with AsyncSession(engine) as session:
                return await AccountSnapshotWriter(
                    session,
                    repository=_PausingMarketRepository(
                        session,
                        locked=market_locked,
                        release=release_writer,
                    ),
                ).write(_command(account_id))

        async def insert_price():
            await asyncio.wait_for(market_locked.wait(), timeout=10)
            async with AsyncSession(engine) as session:
                pid = await session.scalar(select(func.pg_backend_pid()))
                assert pid is not None
                price_pid.set_result(pid)
                session.add(
                    PriceSnapshotModel(
                        id=f"{prefix}-later-price",
                        asset_id=f"{prefix}-asset",
                        listing_id=f"{prefix}-listing",
                        price=Decimal("16"),
                        currency="EUR",
                        source=PriceSource.manual,
                        timestamp=snapshot_at,
                        created_at=snapshot_at,
                    )
                )
                await session.commit()

        writer_task = asyncio.create_task(first_write())
        price_task = asyncio.create_task(insert_price())
        await _wait_for_database_lock(
            engine,
            await asyncio.wait_for(price_pid, timeout=10),
            locktype="relation",
        )
        release_writer.set()
        created, _ = await asyncio.wait_for(
            asyncio.gather(writer_task, price_task),
            timeout=20,
        )
        assert created.disposition is AccountSnapshotWriteDisposition.created
        async with AsyncSession(engine) as session:
            with pytest.raises(AccountSnapshotEvidenceStateError):
                await AccountSnapshotWriter(session).write(_command(account_id))
        async with AsyncSession(engine) as session:
            snapshot = await session.get(AccountSnapshotModel, created.snapshot_id)
            assert snapshot is not None
            assert snapshot.investment_value == Decimal("750.000000")
            assert snapshot.total_value == Decimal("500.000000")
            assert await _counts(session, account_id) == (1, 1)
    finally:
        release_writer.set()
        await engine.dispose()
        await _cleanup(prefix)


class _PausingRepository(AccountSnapshotWriterRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        locked: asyncio.Event | None = None,
        release: asyncio.Event | None = None,
        pid_ready: asyncio.Future[int] | None = None,
    ) -> None:
        super().__init__(session)
        self.locked = locked
        self.release = release
        self.pid_ready = pid_ready

    async def acquire_snapshot_lock(self, **values: Any) -> None:
        pid = await self.session.scalar(select(func.pg_backend_pid()))
        if self.pid_ready is not None and pid is not None:
            self.pid_ready.set_result(pid)
        await super().acquire_snapshot_lock(**values)
        if self.locked is not None:
            self.locked.set()
        if self.release is not None:
            await asyncio.wait_for(self.release.wait(), timeout=10)


async def _wait_for_database_lock(engine: Any, pid: int, *, locktype: str) -> None:
    for _ in range(100):
        async with engine.connect() as connection:
            blocked = await connection.scalar(
                text(
                    "SELECT cardinality(pg_blocking_pids(:pid)) > 0 "
                    "AND wait_event_type = 'Lock' "
                    "AND EXISTS ("
                    "  SELECT 1 FROM pg_locks "
                    "  WHERE pg_locks.pid = :pid "
                    "    AND locktype = :locktype "
                    "    AND NOT granted"
                    ") "
                    "FROM pg_stat_activity WHERE pid = :pid"
                ),
                {"pid": pid, "locktype": locktype},
            )
        if blocked:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("Second writer did not wait on a PostgreSQL lock")


async def _wait_for_lock(engine: Any, pid: int) -> None:
    await _wait_for_database_lock(engine, pid, locktype="advisory")


@pytest.mark.asyncio
async def test_same_identity_concurrency_creates_once_and_replays_after_lock_wait() -> None:
    prefix = "i5d-concurrent"
    await _cleanup(prefix)
    account_id = await _seed_investment(prefix)
    engine = _engine()
    locked = asyncio.Event()
    release = asyncio.Event()
    loop = asyncio.get_running_loop()
    second_pid: asyncio.Future[int] = loop.create_future()
    try:

        async def first_write():
            async with AsyncSession(engine) as session:
                repository = _PausingRepository(
                    session,
                    locked=locked,
                    release=release,
                )
                return await AccountSnapshotWriter(session, repository=repository).write(
                    _command(account_id)
                )

        async def second_write():
            await asyncio.wait_for(locked.wait(), timeout=10)
            async with AsyncSession(engine) as session:
                repository = _PausingRepository(session, pid_ready=second_pid)
                return await AccountSnapshotWriter(session, repository=repository).write(
                    _command(account_id)
                )

        first_task = asyncio.create_task(first_write())
        second_task = asyncio.create_task(second_write())
        pid = await asyncio.wait_for(second_pid, timeout=10)
        await _wait_for_lock(engine, pid)
        release.set()
        first, second = await asyncio.wait_for(
            asyncio.gather(first_task, second_task),
            timeout=20,
        )
        assert first.disposition is AccountSnapshotWriteDisposition.created
        assert second.disposition is AccountSnapshotWriteDisposition.replayed
        assert first.snapshot_id == second.snapshot_id
        async with AsyncSession(engine) as session:
            assert await _counts(session, account_id) == (1, 1)
    finally:
        release.set()
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_same_identity_different_metadata_creates_once_then_conflicts() -> None:
    prefix = "i5d-concurrent-conflict"
    await _cleanup(prefix)
    account_id = await _seed_investment(prefix)
    engine = _engine()
    locked = asyncio.Event()
    release = asyncio.Event()
    second_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:

        async def first_write():
            async with AsyncSession(engine) as session:
                return await AccountSnapshotWriter(
                    session,
                    repository=_PausingRepository(
                        session,
                        locked=locked,
                        release=release,
                    ),
                ).write(_command(account_id))

        async def second_write():
            await asyncio.wait_for(locked.wait(), timeout=10)
            async with AsyncSession(engine) as session:
                return await AccountSnapshotWriter(
                    session,
                    repository=_PausingRepository(session, pid_ready=second_pid),
                ).write(
                    _command(
                        account_id,
                        created_at=datetime(2026, 7, 28, 0, 3),
                    )
                )

        first_task = asyncio.create_task(first_write())
        second_task = asyncio.create_task(second_write())
        await _wait_for_lock(engine, await asyncio.wait_for(second_pid, timeout=10))
        release.set()
        first = await asyncio.wait_for(first_task, timeout=20)
        assert first.disposition is AccountSnapshotWriteDisposition.created
        with pytest.raises(AccountSnapshotWriteConflictError):
            await asyncio.wait_for(second_task, timeout=20)
        async with AsyncSession(engine) as session:
            assert await _counts(session, account_id) == (1, 1)
    finally:
        release.set()
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_different_accounts_do_not_share_snapshot_or_history_locks() -> None:
    first_prefix = "i5d-parallel-a"
    second_prefix = "i5d-parallel-b"
    await _cleanup(first_prefix)
    await _cleanup(second_prefix)
    first_account = await _seed_investment(first_prefix)
    second_account = await _seed_investment(second_prefix)
    engine = _engine()
    locked = asyncio.Event()
    release = asyncio.Event()
    try:

        async def paused_write():
            async with AsyncSession(engine) as session:
                return await AccountSnapshotWriter(
                    session,
                    repository=_PausingRepository(
                        session,
                        locked=locked,
                        release=release,
                    ),
                ).write(_command(first_account))

        first_task = asyncio.create_task(paused_write())
        await asyncio.wait_for(locked.wait(), timeout=10)
        async with AsyncSession(engine) as session:
            second = await asyncio.wait_for(
                AccountSnapshotWriter(session).write(_command(second_account)),
                timeout=10,
            )
        assert second.disposition is AccountSnapshotWriteDisposition.created
        assert not first_task.done()
        release.set()
        first = await asyncio.wait_for(first_task, timeout=20)
        assert first.disposition is AccountSnapshotWriteDisposition.created
    finally:
        release.set()
        await engine.dispose()
        await _cleanup(first_prefix)
        await _cleanup(second_prefix)


class _PausingHoldingRepository(HoldingRebuildRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        locked: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        super().__init__(session)
        self.locked = locked
        self.release = release

    async def lock_canonical_history_scopes(self, account_id: str) -> None:
        await super().lock_canonical_history_scopes(account_id)
        self.locked.set()
        await asyncio.wait_for(self.release.wait(), timeout=10)


class _PausingImportRepository(ImportBatchRepository):
    def __init__(
        self,
        session: AsyncSession,
        *,
        locked: asyncio.Event,
        release: asyncio.Event,
    ) -> None:
        super().__init__(session)
        self.locked = locked
        self.release = release

    async def lock_deduplication_scope(
        self,
        *,
        account_id: str,
        source: ImportSource,
    ) -> None:
        await super().lock_deduplication_scope(account_id=account_id, source=source)
        self.locked.set()
        await asyncio.wait_for(self.release.wait(), timeout=10)


@pytest.mark.asyncio
async def test_writer_waits_for_holding_rebuild_source_locks_without_deadlock() -> None:
    prefix = "i5d-holding-race"
    await _cleanup(prefix)
    account_id = await _seed_investment(prefix)
    snapshot_at, _, _, _ = _scenario_times(account_id)
    engine = _engine()
    locked = asyncio.Event()
    release = asyncio.Event()
    writer_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:

        async def rebuild():
            async with AsyncSession(engine) as session, session.begin():
                service = HoldingRebuildService(session)
                service.repository = _PausingHoldingRepository(
                    session,
                    locked=locked,
                    release=release,
                )
                return await service.rebuild(
                    account_id=account_id,
                    rebuilt_at=snapshot_at,
                )

        async def write():
            await asyncio.wait_for(locked.wait(), timeout=10)
            async with AsyncSession(engine) as session:
                return await AccountSnapshotWriter(
                    session,
                    repository=_PausingRepository(session, pid_ready=writer_pid),
                ).write(_command(account_id))

        rebuild_task = asyncio.create_task(rebuild())
        writer_task = asyncio.create_task(write())
        await _wait_for_lock(engine, await asyncio.wait_for(writer_pid, timeout=10))
        release.set()
        rebuild_result, writer_result = await asyncio.wait_for(
            asyncio.gather(rebuild_task, writer_task),
            timeout=20,
        )
        assert rebuild_result.updated == 1
        assert rebuild_result.replayed is False
        assert writer_result.disposition is AccountSnapshotWriteDisposition.created
        async with AsyncSession(engine) as session:
            assert await _counts(session, account_id) == (1, 1)
    finally:
        release.set()
        await engine.dispose()
        await _cleanup(prefix)


@pytest.mark.asyncio
async def test_writer_waits_for_investment_posting_and_reads_complete_committed_history() -> None:
    prefix = "i5d-posting-race"
    await _cleanup(prefix)
    account_id = await _seed_investment(prefix)
    principal = await _seed_postable_cash_batch(prefix, account_id)
    engine = _engine()
    posting_locked = asyncio.Event()
    release_posting = asyncio.Event()
    writer_pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    try:

        async def post_batch():
            async with AsyncSession(engine) as session:
                service = ImportBatchPostingService(session)
                service.repository = _PausingImportRepository(
                    session,
                    locked=posting_locked,
                    release=release_posting,
                )
                return await service.post_batch(
                    PostImportBatchCommand(
                        principal=principal,
                        account_id=account_id,
                        batch_id=f"{prefix}-posting-batch",
                    )
                )

        async def write_snapshot():
            await asyncio.wait_for(posting_locked.wait(), timeout=10)
            async with AsyncSession(engine) as session:
                return await AccountSnapshotWriter(
                    session,
                    repository=_PausingRepository(session, pid_ready=writer_pid),
                ).write(_command(account_id))

        posting_task = asyncio.create_task(post_batch())
        writer_task = asyncio.create_task(write_snapshot())
        await _wait_for_lock(engine, await asyncio.wait_for(writer_pid, timeout=10))
        release_posting.set()
        posting_result, writer_result = await asyncio.wait_for(
            asyncio.gather(posting_task, writer_task),
            timeout=20,
        )
        assert posting_result.status is ImportStatus.completed
        assert posting_result.rows_imported == 1
        assert writer_result.disposition is AccountSnapshotWriteDisposition.created

        async with AsyncSession(engine) as session:
            snapshot = await session.get(AccountSnapshotModel, writer_result.snapshot_id)
            row = await session.get(ImportRowModel, f"{prefix}-posting-row")
            assert snapshot is not None
            assert row is not None
            assert row.status is ImportRowStatus.imported
            assert row.created_investment_event_id is not None
            assert snapshot.cash_value == Decimal("1000.000000")
            assert snapshot.investment_value == Decimal("750.000000")
            assert snapshot.net_deposits_value == Decimal("1200.000000")
            assert snapshot.total_value == Decimal("1750.000000")
            assert await _counts(session, account_id) == (1, 1)
    finally:
        release_posting.set()
        await engine.dispose()
        await _cleanup(prefix)
