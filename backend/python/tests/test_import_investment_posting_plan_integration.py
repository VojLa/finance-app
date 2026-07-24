from __future__ import annotations

import asyncio
import os
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy import delete, func, select
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
from app.modules.imports.investment_posting_plan import build_investment_posting_plan
from app.modules.imports.normalization import ImportNormalizationService
from app.modules.imports.posting_common import ImportPostStateError

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _principal(prefix: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=f"{prefix}-user",
        email=f"{prefix}@example.com",
        name=prefix,
    )


async def _seed(
    prefix: str,
    *,
    source: ImportSource,
    rows: list[dict[str, str]],
) -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    now = datetime.now(UTC).replace(tzinfo=None)
    account_id = f"{prefix}-account"
    batch_id = f"{prefix}-batch"
    user_id = f"{prefix}-user"
    async with AsyncSession(engine) as session:
        await session.execute(
            delete(ImportRowModel).where(ImportRowModel.import_batch_id == batch_id)
        )
        await session.execute(delete(ImportBatchModel).where(ImportBatchModel.id == batch_id))
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
                type=(
                    AccountType.broker
                    if source is ImportSource.trading212
                    else AccountType.exchange
                ),
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
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
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


async def _assert_no_entities() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        for model in (
            AssetModel,
            AssetListingModel,
            AssetAliasModel,
            InvestmentEventModel,
            InvestmentMovementModel,
            TransactionModel,
        ):
            assert await session.scalar(select(func.count()).select_from(model)) == 0
    await engine.dispose()


async def _snapshot(prefix: str) -> tuple[Any, Any]:
    assert DATABASE_URL is not None
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    async with AsyncSession(engine) as session:
        batch = await session.get(ImportBatchModel, f"{prefix}-batch")
        assert batch is not None
        rows = list(
            (
                await session.scalars(
                    select(ImportRowModel)
                    .where(ImportRowModel.import_batch_id == batch.id)
                    .order_by(ImportRowModel.row_number)
                )
            ).all()
        )
        batch_state = (
            batch.status,
            batch.rows_total,
            batch.rows_imported,
            batch.rows_skipped,
            batch.completed_at,
        )
        row_states = [
            (
                row.id,
                row.status,
                deepcopy(row.normalized_data),
                row.deduplication_key,
                row.created_transaction_id,
                row.created_investment_event_id,
            )
            for row in rows
        ]
    await engine.dispose()
    return batch_state, row_states


def _trading_buy(
    *,
    quantity: str = "2",
    date: str = "2026-07-25T10:00:00Z",
) -> dict[str, str]:
    return {
        "Action": "Market buy",
        "Time": date,
        "Ticker": "vwce",
        "ISIN": "IE00B4L5Y983",
        "Name": "Vanguard FTSE All-World",
        "Asset type": "ETF",
        "No. of shares": quantity,
        "Price / share": "100",
        "Currency (Price / share)": "EUR",
        "Total": "200",
        "Currency (Total)": "EUR",
        "Currency conversion fee": "0.5",
        "Currency (Currency conversion fee)": "EUR",
        "ID": "trade-1",
    }


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
        "Date": "2026-07-25T10:00:00Z",
        "Amount": amount,
        "Currency": currency,
        "anycoin TX ID": external_id,
    }


def test_trading212_buy_builds_from_freshly_reloaded_persisted_jsonb() -> None:
    prefix = "plan-db-t212-buy"

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.trading212, rows=[_trading_buy()])
        await _prepare(prefix)
        before = await _snapshot(prefix)
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            batch = await session.get(ImportBatchModel, f"{prefix}-batch")
            row = await session.get(ImportRowModel, f"{prefix}-row-0")
            assert batch is not None and row is not None
            plan = build_investment_posting_plan(
                account_id=f"{prefix}-account", batch=batch, row=row
            )
            assert plan.external_id == "trade-1"
            assert plan.asset_resolution is not None
            assert (
                plan.asset_resolution.asset_type,
                plan.asset_resolution.provider,
                plan.asset_resolution.listing_currency_hint,
            ) == (AssetType.etf, PriceSource.broker, "EUR")
            assert [movement.kind for movement in plan.movements] == [
                InvestmentMovementKind.asset,
                InvestmentMovementKind.cash,
                InvestmentMovementKind.fee,
            ]
            assert plan.movements[0].quantity == Decimal("2")
        await engine.dispose()
        assert await _snapshot(prefix) == before
        await _assert_no_entities()

    asyncio.run(scenario())


def test_anycoin_grouped_anchor_builds_plan_and_members_remain_skipped() -> None:
    prefix = "plan-db-any-group"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.anycoin,
            rows=[
                _anycoin("trade payment", "-500", "EUR", order_id="order-1"),
                _anycoin(
                    "trade fill",
                    "0.01",
                    "BTC",
                    order_id="order-1",
                    external_id="fill-1",
                ),
            ],
        )
        await _prepare(prefix)
        before = await _snapshot(prefix)
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            batch = await session.get(ImportBatchModel, f"{prefix}-batch")
            assert batch is not None
            rows = list(
                (
                    await session.scalars(
                        select(ImportRowModel).where(ImportRowModel.import_batch_id == batch.id)
                    )
                ).all()
            )
            anchor = next(row for row in rows if row.status is ImportRowStatus.pending)
            member = next(row for row in rows if row.status is ImportRowStatus.skipped)
            plan = build_investment_posting_plan(
                account_id=f"{prefix}-account", batch=batch, row=anchor
            )
            assert plan.order_id == "order-1"
            assert plan.asset_resolution is not None
            assert plan.asset_resolution.asset_type is AssetType.crypto
            assert [movement.kind for movement in plan.movements] == [
                InvestmentMovementKind.asset,
                InvestmentMovementKind.cash,
            ]
            assert member.normalized_data is not None
            assert member.normalized_data["kind"] == "group_member"
            assert "posting_intent" not in member.normalized_data
        await engine.dispose()
        assert await _snapshot(prefix) == before
        await _assert_no_entities()

    asyncio.run(scenario())


def test_anycoin_incoming_and_outgoing_transfers_have_explicit_movements() -> None:
    prefix = "plan-db-any-transfer"

    async def scenario() -> None:
        await _seed(
            prefix,
            source=ImportSource.anycoin,
            rows=[
                _anycoin("deposit", "0.5", "BTC", external_id="deposit-1"),
                _anycoin("withdrawal", "-0.25", "ETH", external_id="withdrawal-1"),
            ],
        )
        await _prepare(prefix)
        before = await _snapshot(prefix)
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            batch = await session.get(ImportBatchModel, f"{prefix}-batch")
            assert batch is not None
            rows = list(
                (
                    await session.scalars(
                        select(ImportRowModel)
                        .where(ImportRowModel.import_batch_id == batch.id)
                        .order_by(ImportRowModel.row_number)
                    )
                ).all()
            )
            plans = [
                build_investment_posting_plan(account_id=f"{prefix}-account", batch=batch, row=row)
                for row in rows
            ]
            assert [plan.movements[0].direction for plan in plans] == [
                MovementDirection.incoming,
                MovementDirection.outgoing,
            ]
            assert all(len(plan.movements) == 1 for plan in plans)
        await engine.dispose()
        assert await _snapshot(prefix) == before
        await _assert_no_entities()

    asyncio.run(scenario())


def test_directionless_trading212_transfer_is_review_and_has_no_plan() -> None:
    prefix = "plan-db-t212-transfer"
    raw = {
        "Action": "Portfolio transfer",
        "Time": "2026-07-25T10:00:00Z",
        "Ticker": "aapl",
        "ISIN": "US0378331005",
        "Name": "Apple",
        "Asset type": "stock",
        "No. of shares": "1",
        "ID": "transfer-1",
    }

    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.trading212, rows=[raw])
        await _prepare(prefix)
        before = await _snapshot(prefix)
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            batch = await session.get(ImportBatchModel, f"{prefix}-batch")
            row = await session.get(ImportRowModel, f"{prefix}-row-0")
            assert batch is not None and row is not None
            assert row.status is ImportRowStatus.needs_review
            assert row.normalized_data is not None
            assert row.normalized_data["posting_intent"]["target"] == "needs_review"
            assert row.validation_errors is not None
            errors = cast(list[dict[str, Any]], row.validation_errors)
            assert errors[0]["code"] == "missing_asset_direction"
            with pytest.raises(ImportPostStateError):
                build_investment_posting_plan(account_id=f"{prefix}-account", batch=batch, row=row)
        await engine.dispose()
        assert await _snapshot(prefix) == before
        await _assert_no_entities()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("prefix", "raw"),
    [
        ("plan-db-scale11", _trading_buy(quantity="0.00000000001")),
        (
            "plan-db-subms",
            _trading_buy(date="2026-07-25T10:00:00.123456+00:00"),
        ),
    ],
)
def test_unrepresentable_persisted_values_fail_without_mutation(
    prefix: str, raw: dict[str, str]
) -> None:
    async def scenario() -> None:
        await _seed(prefix, source=ImportSource.trading212, rows=[raw])
        await _prepare(prefix)
        before = await _snapshot(prefix)
        assert DATABASE_URL is not None
        engine = create_async_engine(normalize_database_url(DATABASE_URL))
        async with AsyncSession(engine) as session:
            batch = await session.get(ImportBatchModel, f"{prefix}-batch")
            row = await session.get(ImportRowModel, f"{prefix}-row-0")
            assert batch is not None and row is not None
            with pytest.raises(ImportPostStateError):
                build_investment_posting_plan(account_id=f"{prefix}-account", batch=batch, row=row)
        await engine.dispose()
        assert await _snapshot(prefix) == before
        await _assert_no_entities()

    asyncio.run(scenario())
