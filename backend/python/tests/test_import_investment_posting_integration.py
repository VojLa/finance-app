from __future__ import annotations

import asyncio
import os
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.models import AuthenticatedPrincipal
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetAliasModel, AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetType,
    ImportRowStatus,
    ImportSource,
    ImportStatus,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.imports.classification_service import ImportClassificationService
from app.modules.imports.deduplication import ImportDeduplicationService
from app.modules.imports.investment_posting import ImportInvestmentPostingWriter
from app.modules.imports.investment_posting_plan import build_investment_posting_plan
from app.modules.imports.normalization import ImportNormalizationService
from app.modules.imports.posting_common import ImportPostStateError

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=4)


def _principal(prefix: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=f"{prefix}-user", email=f"{prefix}@example.com", name=prefix
    )


async def _seed(prefix: str, *, source: ImportSource, rows: list[dict[str, str]]) -> None:
    engine = _engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    account_id, batch_id, user_id = f"{prefix}-account", f"{prefix}-batch", f"{prefix}-user"
    async with AsyncSession(engine) as session:
        linked_event_ids = set(
            (
                await session.scalars(
                    select(ImportRowModel.created_investment_event_id).where(
                        ImportRowModel.import_batch_id == batch_id,
                        ImportRowModel.created_investment_event_id.is_not(None),
                    )
                )
            ).all()
        )
        previous_event_ids = list(
            linked_event_ids
            | set(
                (
                    await session.scalars(
                        select(InvestmentEventModel.id).where(
                            or_(
                                InvestmentEventModel.import_batch_id == batch_id,
                                InvestmentEventModel.account_id == account_id,
                            )
                        )
                    )
                ).all()
            )
        )
        if previous_event_ids:
            await session.execute(
                delete(InvestmentMovementModel).where(
                    InvestmentMovementModel.event_id.in_(previous_event_ids)
                )
            )
        await session.execute(
            delete(InvestmentEventModel).where(InvestmentEventModel.import_batch_id == batch_id)
        )
        if previous_event_ids:
            await session.execute(
                delete(InvestmentEventModel).where(InvestmentEventModel.id.in_(previous_event_ids))
            )
        await session.execute(
            delete(ImportRowModel).where(ImportRowModel.import_batch_id == batch_id)
        )
        await session.execute(delete(ImportBatchModel).where(ImportBatchModel.id == batch_id))
        manual_listing_ids = list(
            (
                await session.scalars(
                    select(AssetListingModel.id).where(AssetListingModel.id.like(f"{prefix}-%"))
                )
            ).all()
        )
        if manual_listing_ids:
            await session.execute(
                delete(AssetListingModel).where(AssetListingModel.id.in_(manual_listing_ids))
            )
        await session.execute(delete(AssetModel).where(AssetModel.id.like(f"{prefix}-%")))
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id == account_id)
        )
        await session.execute(delete(AccountModel).where(AccountModel.id == account_id))
        await session.execute(delete(UserModel).where(UserModel.id == user_id))
        session.add(
            UserModel(
                id=user_id,
                email=f"{prefix}@example.com",
                name=prefix,
                password_hash=None,
                base_currency="EUR",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            AccountModel(
                id=account_id,
                name=prefix,
                type=AccountType.broker
                if source is ImportSource.trading212
                else AccountType.exchange,
                currency="EUR",
                color=None,
                notes=None,
                is_archived=False,
                archived_at=None,
                created_at=now,
                updated_at=now,
            )
        )
        await session.flush()
        session.add(
            AccountMemberModel(
                id=f"{prefix}-member",
                account_id=account_id,
                user_id=user_id,
                role=AccountMemberRole.owner,
                relation_type=AccountRelationType.owner,
                invited_by_id=None,
                accepted_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            ImportBatchModel(
                id=batch_id,
                user_id=user_id,
                account_id=account_id,
                source=source,
                filename=f"{prefix}.csv",
                file_size=1,
                file_encoding="utf-8",
                checksum=(prefix[:1] or "a") * 64,
                status=ImportStatus.processing,
                rows_total=len(rows),
                rows_imported=0,
                rows_skipped=0,
                created_at=now,
                completed_at=None,
                retain_until=None,
                raw_data_purged_at=None,
            )
        )
        session.add_all(
            [
                ImportRowModel(
                    id=f"{prefix}-row-{index}",
                    import_batch_id=batch_id,
                    row_number=index + 2,
                    raw_data=raw,
                    normalized_data=None,
                    validation_errors=None,
                    deduplication_key=None,
                    status=ImportRowStatus.pending,
                    error_message=None,
                    created_transaction_id=None,
                    created_investment_event_id=None,
                    created_at=now,
                )
                for index, raw in enumerate(rows)
            ]
        )
        await session.commit()
    await engine.dispose()


async def _prepare(prefix: str) -> None:
    engine = _engine()
    principal = _principal(prefix)
    account_id, batch_id = f"{prefix}-account", f"{prefix}-batch"
    async with AsyncSession(engine) as session:
        await ImportNormalizationService(session).normalize_batch(
            principal=principal, account_id=account_id, batch_id=batch_id
        )
    async with AsyncSession(engine) as session:
        await ImportDeduplicationService(session).deduplicate_batch(
            principal=principal, account_id=account_id, batch_id=batch_id
        )
    async with AsyncSession(engine) as session:
        await ImportClassificationService(session).classify_batch(
            principal=principal, account_id=account_id, batch_id=batch_id
        )
    await engine.dispose()


async def _post(prefix: str, *, commit: bool = True):
    engine = _engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        batch = await session.scalar(
            select(ImportBatchModel).where(ImportBatchModel.id == f"{prefix}-batch")
        )
        row = await session.scalar(
            select(ImportRowModel).where(ImportRowModel.id == f"{prefix}-row-0")
        )
        assert batch is not None and row is not None
        result = await ImportInvestmentPostingWriter(session).post_row(
            account_id=batch.account_id, batch=batch, row=row
        )
        if commit:
            await session.commit()
        else:
            await session.rollback()
    await engine.dispose()
    return result


async def _counts() -> dict[str, int]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        result = {
            model.__tablename__: int(
                await session.scalar(select(func.count()).select_from(model)) or 0
            )
            for model in (
                AssetModel,
                AssetListingModel,
                AssetAliasModel,
                InvestmentEventModel,
                InvestmentMovementModel,
                TransactionModel,
            )
        }
    await engine.dispose()
    return result


async def _batch_history_counts(prefix: str) -> tuple[int, int]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        event_ids = list(
            (
                await session.scalars(
                    select(InvestmentEventModel.id).where(
                        InvestmentEventModel.import_batch_id == f"{prefix}-batch"
                    )
                )
            ).all()
        )
        movements = (
            0
            if not event_ids
            else int(
                await session.scalar(
                    select(func.count())
                    .select_from(InvestmentMovementModel)
                    .where(InvestmentMovementModel.event_id.in_(event_ids))
                )
                or 0
            )
        )
    await engine.dispose()
    return len(event_ids), movements


def _trading_buy(symbol: str, isin: str) -> dict[str, str]:
    return {
        "Action": "Market buy",
        "Time": "2026-07-26T10:00:00Z",
        "Ticker": symbol,
        "ISIN": isin,
        "Name": "Writer fixture",
        "Asset type": "ETF",
        "No. of shares": "2",
        "Price / share": "100",
        "Currency (Price / share)": "EUR",
        "Total": "200",
        "Currency (Total)": "EUR",
        "ID": f"trade-{symbol}",
    }


def _trading_cash(action: str, external_id: str) -> dict[str, str]:
    row = _trading_buy("", "")
    row.update(
        {
            "Action": action,
            "Ticker": "",
            "ISIN": "",
            "Name": "",
            "Asset type": "",
            "No. of shares": "",
            "Price / share": "",
            "Currency (Price / share)": "",
            "ID": external_id,
        }
    )
    return row


def _trading_dividend(symbol: str, isin: str, external_id: str) -> dict[str, str]:
    row = _trading_buy(symbol, isin)
    row.update(
        {
            "Action": "Dividend (Tax Exempted)",
            "No. of shares": "",
            "Price / share": "",
            "Currency (Price / share)": "",
            "Total": "5.25",
            "Currency (Total)": "EUR",
            "ID": external_id,
        }
    )
    return row


def _anycoin(
    kind: str,
    amount: str,
    currency: str,
    *,
    order_id: str = "",
    external_id: str = "",
) -> dict[str, str]:
    return {
        "Type": kind,
        "Order ID": order_id,
        "Date": "2026-07-26T10:00:00Z",
        "Amount": amount,
        "Currency": currency,
        "anycoin TX ID": external_id,
    }


async def _batch_snapshot(prefix: str) -> tuple[object, ...]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        batch = await session.get(ImportBatchModel, f"{prefix}-batch")
        assert batch is not None
        value = (
            batch.status,
            batch.rows_total,
            batch.rows_imported,
            batch.rows_skipped,
            batch.completed_at,
        )
    await engine.dispose()
    return value


async def _row_snapshot(prefix: str, index: int = 0) -> tuple[object, ...]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        row = await session.get(ImportRowModel, f"{prefix}-row-{index}")
        assert row is not None
        value = (
            row.status,
            deepcopy(row.raw_data),
            deepcopy(row.normalized_data),
            deepcopy(row.validation_errors),
            row.deduplication_key,
            row.error_message,
            row.created_transaction_id,
            row.created_investment_event_id,
        )
    await engine.dispose()
    return value


async def _history(prefix: str) -> tuple[InvestmentEventModel, tuple[InvestmentMovementModel, ...]]:
    engine = _engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        event = await session.scalar(
            select(InvestmentEventModel).where(
                InvestmentEventModel.import_batch_id == f"{prefix}-batch"
            )
        )
        assert event is not None
        movements = tuple(
            (
                await session.scalars(
                    select(InvestmentMovementModel)
                    .where(InvestmentMovementModel.event_id == event.id)
                    .order_by(InvestmentMovementModel.id)
                )
            ).all()
        )
    await engine.dispose()
    return event, movements


async def _assert_scope_counts(prefix: str, *, events: int, movements: int) -> None:
    assert await _batch_history_counts(prefix) == (events, movements)
    counts = await _counts()
    assert counts["AssetAlias"] == 0
    assert counts["Transaction"] == 0


async def _seed_compatible_listing(prefix: str) -> tuple[str, str]:
    engine = _engine()
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    async with AsyncSession(engine) as session:
        batch = await session.get(ImportBatchModel, f"{prefix}-batch")
        row = await session.get(ImportRowModel, f"{prefix}-row-0")
        assert batch is not None and row is not None
        plan = build_investment_posting_plan(
            account_id=batch.account_id,
            batch=batch,
            row=row,
        )
        assert plan.asset_resolution is not None
        asset = AssetModel(
            id=f"{prefix}-asset",
            symbol=plan.asset_resolution.symbol,
            isin=plan.asset_resolution.isin,
            name=plan.asset_resolution.name,
            asset_type=plan.asset_resolution.asset_type,
            currency="EUR",
            updated_at=now,
        )
        listing = AssetListingModel(
            id=f"{prefix}-listing",
            asset_id=asset.id,
            symbol=plan.asset_resolution.symbol,
            exchange=plan.asset_resolution.exchange,
            mic=None,
            currency="EUR",
            country=None,
            provider=plan.asset_resolution.provider,
            provider_symbol=plan.asset_resolution.provider_symbol,
            is_primary=False,
            updated_at=now,
        )
        session.add(asset)
        await session.flush()
        session.add(listing)
        asset_id, listing_id = asset.id, listing.id
        await session.commit()
    await engine.dispose()
    return asset_id, listing_id


def test_trading212_buy_persists_event_movements_and_exact_replay() -> None:
    prefix, symbol, isin = "b3-buy", "B3BUY", "ISINB3BUY"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)])
        await _prepare(prefix)
        first = await _post(prefix)
        original_event_timestamp = first.event.updated_at
        original_movement_ids = tuple(movement.id for movement in first.movements)
        second = await _post(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            row = await session.get(ImportRowModel, f"{prefix}-row-0")
            batch = await session.get(ImportBatchModel, f"{prefix}-batch")
            assert row is not None and batch is not None
            assert row.status is ImportRowStatus.imported
            assert (
                row.created_transaction_id is None
                and row.created_investment_event_id == first.event.id
            )
            assert batch.status is ImportStatus.processing and batch.rows_imported == 0
            event = await session.get(InvestmentEventModel, first.event.id)
            assert event is not None and event.updated_at == original_event_timestamp
        await engine.dispose()
        assert first.created is True and second.created is False
        assert first.event.id == second.event.id
        assert tuple(movement.id for movement in second.movements) == original_movement_ids
        assert len(first.movements) == 2
        assert await _batch_history_counts(prefix) == (1, 2)
        counts = await _counts()
        assert counts["AssetAlias"] == 0 and counts["Transaction"] == 0

    asyncio.run(scenario())


def test_anycoin_transfer_and_caller_rollback_retry() -> None:
    prefix = "b3-transfer"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.anycoin,
            rows=[
                {
                    "Type": "deposit",
                    "Order ID": "",
                    "Date": "2026-07-26T10:00:00Z",
                    "Amount": "0.01",
                    "Currency": "BTC",
                    "anycoin TX ID": "b3-deposit",
                }
            ],
        )
        await _prepare(prefix)
        first = await _post(prefix, commit=False)
        assert first.created is True
        assert await _batch_history_counts(prefix) == (0, 0)
        engine = _engine()
        async with AsyncSession(engine) as session:
            row = await session.get(ImportRowModel, f"{prefix}-row-0")
            assert row is not None
            assert row.status is ImportRowStatus.pending
            assert row.created_investment_event_id is None
        await engine.dispose()
        retry = await _post(prefix)
        assert retry.movements[0].direction.value == "in"
        assert retry.movements[0].asset_id is not None and retry.movements[0].listing_id is not None
        assert await _batch_history_counts(prefix) == (1, 1)

    asyncio.run(scenario())


def test_corrupt_event_fails_closed_without_repair() -> None:
    prefix, symbol, isin = "b3-corrupt", "B3CORRUPT", "ISINB3CORRUPT"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)])
        await _prepare(prefix)
        posted = await _post(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            event = await session.get(InvestmentEventModel, posted.event.id)
            assert event is not None
            event.description = "tampered"
            await session.commit()
        async with AsyncSession(engine) as session:
            batch = await session.get(ImportBatchModel, f"{prefix}-batch")
            row = await session.get(ImportRowModel, f"{prefix}-row-0")
            assert batch is not None and row is not None
            with pytest.raises(ImportPostStateError):
                await ImportInvestmentPostingWriter(session).post_row(
                    account_id=batch.account_id, batch=batch, row=row
                )
            assert row.created_investment_event_id == posted.event.id
        await engine.dispose()
        assert await _batch_history_counts(prefix) == (1, 2)

    asyncio.run(scenario())


def test_anycoin_grouped_trade_posts_only_anchor() -> None:
    prefix, symbol = "b3-grouped", "B3GROUP"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.anycoin,
            rows=[
                _anycoin("trade payment", "-500", "EUR", order_id="b3-order"),
                _anycoin(
                    "trade fill",
                    "0.01",
                    symbol,
                    order_id="b3-order",
                    external_id="b3-fill",
                ),
            ],
        )
        await _prepare(prefix)
        before_batch = await _batch_snapshot(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            rows = list(
                (
                    await session.scalars(
                        select(ImportRowModel)
                        .where(ImportRowModel.import_batch_id == f"{prefix}-batch")
                        .order_by(ImportRowModel.row_number)
                    )
                ).all()
            )
            anchor = next(row for row in rows if row.status is ImportRowStatus.pending)
            member = next(row for row in rows if row.status is ImportRowStatus.skipped)
            batch = await session.get(ImportBatchModel, f"{prefix}-batch")
            assert batch is not None
            posted = await ImportInvestmentPostingWriter(session).post_row(
                account_id=batch.account_id, batch=batch, row=anchor
            )
            member_id = member.id
            await session.commit()
        await engine.dispose()

        event, movements = await _history(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            loaded_member = await session.get(ImportRowModel, member_id)
            assert loaded_member is not None
            assert loaded_member.status is ImportRowStatus.skipped
            assert loaded_member.created_transaction_id is None
            assert loaded_member.created_investment_event_id is None
        await engine.dispose()
        assert posted.created is True
        assert event.source is ImportSource.anycoin and event.order_id == "b3-order"
        assert len(movements) == 2
        asset_movement = next(m for m in movements if m.kind is InvestmentMovementKind.asset)
        cash_movement = next(m for m in movements if m.kind is InvestmentMovementKind.cash)
        assert asset_movement.direction is MovementDirection.incoming
        assert asset_movement.asset_id and asset_movement.listing_id
        assert cash_movement.direction is MovementDirection.outgoing
        assert cash_movement.asset_id is None and cash_movement.listing_id is None
        assert await _batch_snapshot(prefix) == before_batch
        await _assert_scope_counts(prefix, events=1, movements=2)

    asyncio.run(scenario())


def test_anycoin_outgoing_transfer_and_exact_replay() -> None:
    prefix, symbol = "b3-outgoing", "B3OUT"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.anycoin,
            rows=[_anycoin("withdrawal", "-0.25", symbol, external_id="b3-withdrawal")],
        )
        await _prepare(prefix)
        before_batch = await _batch_snapshot(prefix)
        first = await _post(prefix)
        event_before, movements_before = await _history(prefix)
        assert len(movements_before) == 1
        movement = movements_before[0]
        assert movement.kind is InvestmentMovementKind.asset
        assert movement.direction is MovementDirection.outgoing
        assert movement.quantity == Decimal("0.25") and movement.currency == symbol
        assert movement.asset_id and movement.listing_id
        event_timestamp = event_before.updated_at
        movement_timestamp = movement.updated_at
        movement_id = movement.id
        second = await _post(prefix)
        event_after, movements_after = await _history(prefix)
        assert second.created is False and second.event.id == first.event.id
        assert event_after.updated_at == event_timestamp
        assert len(movements_after) == 1
        assert movements_after[0].id == movement_id
        assert movements_after[0].updated_at == movement_timestamp
        engine = _engine()
        async with AsyncSession(engine) as session:
            asset = await session.get(AssetModel, movement.asset_id)
            listing = await session.get(AssetListingModel, movement.listing_id)
            assert asset is not None and listing is not None
            assert asset.asset_type is AssetType.crypto
            assert listing.asset_id == asset.id
            assert listing.provider is PriceSource.exchange
            assert listing.exchange == "anycoin"
        await engine.dispose()
        assert await _batch_snapshot(prefix) == before_batch
        await _assert_scope_counts(prefix, events=1, movements=1)

    asyncio.run(scenario())


def test_dividend_reuses_exact_provider_listing() -> None:
    prefix, symbol, isin = "b3-dividend", "B3DIV", "ISINB3DIV"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.trading212,
            rows=[_trading_dividend(symbol, isin, "b3-dividend-id")],
        )
        await _prepare(prefix)
        asset_id, listing_id = await _seed_compatible_listing(prefix)
        before = await _counts()
        before_batch = await _batch_snapshot(prefix)
        posted = await _post(prefix)
        after = await _counts()
        assert posted.asset is not None and posted.asset.id == asset_id
        assert posted.listing is not None and posted.listing.id == listing_id
        assert after["Asset"] == before["Asset"]
        assert after["AssetListing"] == before["AssetListing"]
        assert len(posted.movements) == 1
        movement = posted.movements[0]
        assert movement.kind is InvestmentMovementKind.cash
        assert movement.direction is MovementDirection.incoming
        assert movement.quantity == Decimal("5.25") and movement.currency == "EUR"
        assert movement.asset_id == asset_id and movement.listing_id == listing_id
        assert await _batch_snapshot(prefix) == before_batch
        await _assert_scope_counts(prefix, events=1, movements=1)

    asyncio.run(scenario())


def test_dividend_without_listing_evidence_fails_closed() -> None:
    prefix, symbol, isin = "b3-div-no-evidence", "B3DNE", "ISINB3DNE"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.trading212,
            rows=[_trading_dividend(symbol, isin, "b3-div-no-evidence")],
        )
        await _prepare(prefix)
        before_row = await _row_snapshot(prefix)
        before_batch = await _batch_snapshot(prefix)
        before = await _counts()
        with pytest.raises(ImportPostStateError):
            await _post(prefix)
        assert await _row_snapshot(prefix) == before_row
        assert await _batch_snapshot(prefix) == before_batch
        after = await _counts()
        assert after["Asset"] == before["Asset"]
        assert after["AssetListing"] == before["AssetListing"]
        await _assert_scope_counts(prefix, events=0, movements=0)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("action", "prefix", "movement_count"),
    [
        ("Currency conversion", "b3-conversion", 2),
        ("Spending cashback", "b3-interest", 1),
    ],
)
def test_cash_only_events_are_asset_free_and_replay_read_only(
    action: str, prefix: str, movement_count: int
) -> None:
    async def scenario() -> None:
        raw = _trading_cash(action, f"{prefix}-id")
        if action == "Currency conversion":
            raw.update(
                {
                    "Total": "100",
                    "Currency (Total)": "EUR",
                    "Currency conversion from amount": "100",
                    "Currency (Currency conversion from amount)": "EUR",
                    "Currency conversion to amount": "110",
                    "Currency (Currency conversion to amount)": "USD",
                }
            )
        await _seed(prefix, source=ImportSource.trading212, rows=[raw])
        await _prepare(prefix)
        before_assets = await _counts()
        before_batch = await _batch_snapshot(prefix)
        first = await _post(prefix)
        event, movements = await _history(prefix)
        ids = (event.id, tuple(m.id for m in movements))
        second = await _post(prefix)
        replay_event, replay_movements = await _history(prefix)
        assert first.created is True and second.created is False
        assert (replay_event.id, tuple(m.id for m in replay_movements)) == ids
        assert len(movements) == movement_count
        assert all(m.asset_id is None and m.listing_id is None for m in movements)
        if action == "Currency conversion":
            assert {(m.direction, m.currency) for m in movements} == {
                (MovementDirection.outgoing, "EUR"),
                (MovementDirection.incoming, "USD"),
            }
        after_assets = await _counts()
        assert after_assets["Asset"] == before_assets["Asset"]
        assert after_assets["AssetListing"] == before_assets["AssetListing"]
        assert await _batch_snapshot(prefix) == before_batch
        await _assert_scope_counts(prefix, events=1, movements=movement_count)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field",
    [
        "account_id",
        "type",
        "date",
        "source",
        "import_batch_id",
        "external_id",
        "order_id",
        "description",
        "realized_pnl",
        "realized_pnl_currency",
        "archived_at",
        "deleted_at",
    ],
)
def test_event_corruption_matrix_is_never_repaired(field: str) -> None:
    prefix = f"b3-ev-{field.replace('_', '-')}"
    symbol = f"E{field.replace('_', '').upper()}"
    isin = f"ISIN{field.upper()}"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)])
        await _prepare(prefix)
        posted = await _post(prefix)
        before_batch = await _batch_snapshot(prefix)
        before_counts = await _counts()
        engine = _engine()
        async with AsyncSession(engine) as session:
            event = await session.get(InvestmentEventModel, posted.event.id)
            assert event is not None
            if field == "account_id":
                other = await session.scalar(
                    select(AccountModel.id).where(AccountModel.id != event.account_id).limit(1)
                )
                assert other is not None
                event.account_id = other
            elif field == "type":
                event.type = InvestmentEventType.dividend
            elif field == "date":
                event.date = datetime(2026, 7, 27, 10)
            elif field == "source":
                event.source = ImportSource.anycoin
            elif field == "import_batch_id":
                event.import_batch_id = None
            elif field == "external_id":
                event.external_id = "tampered-external"
            elif field == "order_id":
                event.order_id = "tampered-order"
            elif field == "description":
                event.description = "tampered-description"
            elif field == "realized_pnl":
                event.realized_pnl = Decimal("1")
            elif field == "realized_pnl_currency":
                event.realized_pnl_currency = "USD"
            elif field == "archived_at":
                event.archived_at = datetime(2026, 7, 27, 10)
            else:
                event.deleted_at = datetime(2026, 7, 27, 10)
            tampered = getattr(event, field)
            await session.commit()
        await engine.dispose()
        with pytest.raises(ImportPostStateError):
            await _post(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            event = await session.get(InvestmentEventModel, posted.event.id)
            row = await session.get(ImportRowModel, f"{prefix}-row-0")
            assert event is not None and row is not None
            assert getattr(event, field) == tampered
            assert row.created_investment_event_id == posted.event.id
        await engine.dispose()
        assert await _counts() == before_counts
        assert await _batch_snapshot(prefix) == before_batch

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "extra",
        "duplicate",
        "kind",
        "direction",
        "quantity",
        "currency",
        "price_per_unit",
        "value_amount",
        "value_currency",
        "source_symbol",
        "source_asset_type",
        "note",
        "asset_id",
        "listing_id",
    ],
)
def test_movement_corruption_matrix_is_never_repaired(mutation: str) -> None:
    prefix = f"b3-mv-{mutation.replace('_', '-')}"
    symbol = f"M{mutation.replace('_', '').upper()}"
    isin = f"ISINM{mutation.upper()}"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)])
        await _prepare(prefix)
        posted = await _post(prefix)
        before_batch = await _batch_snapshot(prefix)
        engine = _engine()
        async with AsyncSession(engine) as session:
            movements = list(
                (
                    await session.scalars(
                        select(InvestmentMovementModel)
                        .where(InvestmentMovementModel.event_id == posted.event.id)
                        .order_by(InvestmentMovementModel.id)
                    )
                ).all()
            )
            target = next(
                movement for movement in movements if movement.kind is InvestmentMovementKind.asset
            )
            if mutation == "missing":
                await session.delete(target)
            elif mutation in {"extra", "duplicate"}:
                source = target if mutation == "duplicate" else movements[-1]
                session.add(
                    InvestmentMovementModel(
                        id=f"{prefix}-{mutation}",
                        event_id=source.event_id,
                        account_id=source.account_id,
                        asset_id=source.asset_id,
                        listing_id=source.listing_id,
                        kind=source.kind,
                        direction=source.direction,
                        quantity=source.quantity
                        if mutation == "duplicate"
                        else source.quantity + Decimal("1"),
                        currency=source.currency,
                        price_per_unit=source.price_per_unit,
                        value_amount=source.value_amount,
                        value_currency=source.value_currency,
                        source_symbol=source.source_symbol,
                        source_asset_type=source.source_asset_type,
                        note=source.note,
                        updated_at=source.updated_at,
                    )
                )
            elif mutation == "kind":
                target.kind = InvestmentMovementKind.fee
            elif mutation == "direction":
                target.direction = MovementDirection.outgoing
            elif mutation == "quantity":
                target.quantity += Decimal("1")
            elif mutation == "currency":
                target.currency = "USD"
            elif mutation == "price_per_unit":
                target.price_per_unit = Decimal("2")
            elif mutation == "value_amount":
                target.value_amount = Decimal("2")
            elif mutation == "value_currency":
                target.value_currency = "USD"
            elif mutation == "source_symbol":
                target.source_symbol = "TAMPER"
            elif mutation == "source_asset_type":
                target.source_asset_type = AssetType.stock
            elif mutation == "note":
                target.note = "tampered"
            else:
                now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
                other_asset = AssetModel(
                    id=f"{prefix}-other-asset",
                    symbol=f"X{symbol}",
                    isin=f"X{isin}",
                    name="Wrong",
                    asset_type=AssetType.etf,
                    currency="EUR",
                    updated_at=now,
                )
                other_listing = AssetListingModel(
                    id=f"{prefix}-other-listing",
                    asset_id=other_asset.id,
                    symbol=f"X{symbol}",
                    exchange="trading212",
                    mic=None,
                    currency="EUR",
                    country=None,
                    provider=PriceSource.broker,
                    provider_symbol=f"X{symbol}",
                    is_primary=False,
                    updated_at=now,
                )
                session.add(other_asset)
                await session.flush()
                session.add(other_listing)
                await session.flush()
                if mutation == "asset_id":
                    target.asset_id = other_asset.id
                else:
                    target.listing_id = other_listing.id
            await session.commit()
        await engine.dispose()
        corrupted_counts = await _counts()
        with pytest.raises(ImportPostStateError):
            await _post(prefix)
        assert await _counts() == corrupted_counts
        assert await _batch_snapshot(prefix) == before_batch
        assert (await _row_snapshot(prefix))[-1] == posted.event.id

    asyncio.run(scenario())


def test_missing_listing_replay_fails_without_replacement() -> None:
    prefix, symbol, isin = "b3-missing-listing", "B3MISS", "ISINB3MISS"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)])
        await _prepare(prefix)
        posted = await _post(prefix)
        assert posted.listing is not None
        engine = _engine()
        async with AsyncSession(engine) as session:
            listing = await session.get(AssetListingModel, posted.listing.id)
            assert listing is not None
            await session.delete(listing)
            await session.commit()
        await engine.dispose()
        corrupted_counts = await _counts()
        event_before, movements_before = await _history(prefix)
        with pytest.raises(ImportPostStateError):
            await _post(prefix)
        event_after, movements_after = await _history(prefix)
        assert event_after.id == event_before.id
        assert [(m.id, m.asset_id, m.listing_id) for m in movements_after] == [
            (m.id, m.asset_id, m.listing_id) for m in movements_before
        ]
        assert await _counts() == corrupted_counts
        assert (await _row_snapshot(prefix))[-1] == posted.event.id

    asyncio.run(scenario())


def test_same_row_concurrency_waits_on_postgresql_lock_and_replays() -> None:
    prefix, symbol, isin = "b3-concurrent", "B3CON", "ISINB3CON"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)])
        await _prepare(prefix)
        before_batch = await _batch_snapshot(prefix)
        engine = _engine()
        first_holds = asyncio.Event()
        release_first = asyncio.Event()
        second_pid_ready = asyncio.Event()
        second_pid: int | None = None

        async def run_first():
            async with AsyncSession(engine, expire_on_commit=False) as session:
                batch = await session.get(ImportBatchModel, f"{prefix}-batch")
                row = await session.get(ImportRowModel, f"{prefix}-row-0")
                assert batch is not None and row is not None
                result = await ImportInvestmentPostingWriter(session).post_row(
                    account_id=batch.account_id, batch=batch, row=row
                )
                first_holds.set()
                await release_first.wait()
                await session.commit()
                return result

        async def run_second():
            nonlocal second_pid
            await first_holds.wait()
            async with AsyncSession(engine, expire_on_commit=False) as session:
                batch = await session.get(ImportBatchModel, f"{prefix}-batch")
                row = await session.get(ImportRowModel, f"{prefix}-row-0")
                assert batch is not None and row is not None
                second_pid = int(await session.scalar(text("SELECT pg_backend_pid()")))
                second_pid_ready.set()
                result = await ImportInvestmentPostingWriter(session).post_row(
                    account_id=batch.account_id, batch=batch, row=row
                )
                await session.commit()
                return result

        first_task = asyncio.create_task(run_first())
        second_task = asyncio.create_task(run_second())
        await asyncio.wait_for(second_pid_ready.wait(), timeout=10)
        assert second_pid is not None
        blocked = False
        async with AsyncSession(engine) as inspector:
            for _ in range(100):
                blockers = await inspector.scalar(
                    text("SELECT cardinality(pg_blocking_pids(:pid))").bindparams(pid=second_pid)
                )
                state = (
                    await inspector.execute(
                        text(
                            "SELECT wait_event_type, wait_event "
                            "FROM pg_stat_activity WHERE pid = :pid"
                        ),
                        {"pid": second_pid},
                    )
                ).one()
                if int(blockers or 0) > 0 and state.wait_event_type == "Lock":
                    blocked = True
                    break
                await asyncio.sleep(0.02)
        assert blocked
        release_first.set()
        first, second = await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=15)
        await engine.dispose()
        assert first.created is True and second.created is False
        assert first.event.id == second.event.id
        assert {m.id for m in first.movements} == {m.id for m in second.movements}
        assert await _batch_snapshot(prefix) == before_batch
        await _assert_scope_counts(prefix, events=1, movements=2)

    asyncio.run(scenario())


def test_full_graph_caller_rollback_retry_and_replay() -> None:
    prefix, symbol, isin = "b3-full-rollback", "B3ROLL", "ISINB3ROLL"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)])
        await _prepare(prefix)
        before_row = await _row_snapshot(prefix)
        before_batch = await _batch_snapshot(prefix)
        before_counts = await _counts()
        rolled_back = await _post(prefix, commit=False)
        assert rolled_back.created is True
        assert await _row_snapshot(prefix) == before_row
        assert await _batch_snapshot(prefix) == before_batch
        assert await _counts() == before_counts
        retry = await _post(prefix)
        replay = await _post(prefix)
        assert retry.created is True and replay.created is False
        assert retry.event.id == replay.event.id
        assert {m.id for m in retry.movements} == {m.id for m in replay.movements}
        assert await _batch_snapshot(prefix) == before_batch
        await _assert_scope_counts(prefix, events=1, movements=2)

    asyncio.run(scenario())
