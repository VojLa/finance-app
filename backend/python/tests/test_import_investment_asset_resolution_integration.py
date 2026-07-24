from __future__ import annotations

import asyncio
import os
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

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
    PriceSource,
)
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.transactions import TransactionModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.imports.classification_service import ImportClassificationService
from app.modules.imports.deduplication import ImportDeduplicationService
from app.modules.imports.investment_asset_resolution import ImportInvestmentAssetResolver
from app.modules.imports.investment_posting_plan import (
    InvestmentAssetResolutionPlan,
    build_investment_posting_plan,
)
from app.modules.imports.normalization import ImportNormalizationService
from app.modules.imports.posting_common import ImportPostStateError

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=4)


def _session(engine):
    return AsyncSession(engine, expire_on_commit=False)


def _principal(prefix: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=f"{prefix}-user", email=f"{prefix}@example.com", name=prefix
    )


async def _clean_assets(*, symbols: set[str], isins: set[str]) -> None:
    engine = _engine()
    async with AsyncSession(engine) as session:
        listing_ids = list(
            (
                await session.scalars(
                    select(AssetListingModel.id).where(AssetListingModel.symbol.in_(symbols))
                )
            ).all()
        )
        if listing_ids:
            await session.execute(
                delete(AssetListingModel).where(AssetListingModel.id.in_(listing_ids))
            )
        await session.execute(
            delete(AssetModel).where(AssetModel.symbol.in_(symbols) | AssetModel.isin.in_(isins))
        )
        await session.commit()
    await engine.dispose()


async def _seed_pipeline(
    prefix: str,
    *,
    source: ImportSource,
    rows: list[dict[str, str]],
) -> None:
    engine = _engine()
    now = datetime.now(UTC).replace(tzinfo=None)
    account_id, batch_id, user_id = (
        f"{prefix}-account",
        f"{prefix}-batch",
        f"{prefix}-user",
    )
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
    principal = _principal(prefix)
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


async def _fresh_plan(prefix: str, row_id: str | None = None) -> InvestmentAssetResolutionPlan:
    engine = _engine()
    async with AsyncSession(engine) as session:
        batch = await session.get(ImportBatchModel, f"{prefix}-batch")
        row = await session.get(ImportRowModel, row_id or f"{prefix}-row-0")
        assert batch is not None and row is not None
        plan = build_investment_posting_plan(
            account_id=f"{prefix}-account", batch=batch, row=row
        ).asset_resolution
        assert plan is not None
    await engine.dispose()
    return plan


async def _import_snapshot(prefix: str) -> Any:
    engine = _engine()
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
        snapshot = (
            batch.status,
            batch.rows_total,
            batch.rows_imported,
            batch.rows_skipped,
            batch.completed_at,
            [
                (
                    row.status,
                    row.created_transaction_id,
                    row.created_investment_event_id,
                    deepcopy(row.normalized_data),
                    row.deduplication_key,
                )
                for row in rows
            ],
        )
    await engine.dispose()
    return snapshot


async def _out_of_scope_counts() -> dict[str, int]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        result = {
            model.__tablename__: int(
                await session.scalar(select(func.count()).select_from(model)) or 0
            )
            for model in (
                AssetAliasModel,
                InvestmentEventModel,
                InvestmentMovementModel,
                TransactionModel,
            )
        }
    await engine.dispose()
    return result


async def _asset_counts(*, symbols: set[str], isins: set[str]) -> tuple[int, int]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        assets = int(
            await session.scalar(
                select(func.count())
                .select_from(AssetModel)
                .where(AssetModel.symbol.in_(symbols) | AssetModel.isin.in_(isins))
            )
            or 0
        )
        listings = int(
            await session.scalar(
                select(func.count())
                .select_from(AssetListingModel)
                .where(AssetListingModel.symbol.in_(symbols))
            )
            or 0
        )
    await engine.dispose()
    return assets, listings


def _trading_buy(symbol: str, isin: str) -> dict[str, str]:
    return {
        "Action": "Market buy",
        "Time": "2026-07-26T10:00:00Z",
        "Ticker": symbol,
        "ISIN": isin,
        "Name": "Resolver fixture",
        "Asset type": "ETF",
        "No. of shares": "2",
        "Price / share": "100",
        "Currency (Price / share)": "EUR",
        "Total": "200",
        "Currency (Total)": "EUR",
        "ID": f"trade-{symbol}",
    }


def _trading_dividend(symbol: str, isin: str) -> dict[str, str]:
    return {
        "Action": "Dividend (Tax Exempted)",
        "Time": "2026-07-26T10:00:00Z",
        "Ticker": symbol,
        "ISIN": isin,
        "Name": "Dividend fixture",
        "No. of shares": "",
        "Price / share": "",
        "Currency (Price / share)": "",
        "Total": "5",
        "Currency (Total)": "EUR",
        "ID": f"dividend-{symbol}",
    }


async def _seed_asset(
    *,
    asset: AssetModel,
    listing: AssetListingModel | None = None,
) -> None:
    engine = _engine()
    async with _session(engine) as session:
        session.add(asset)
        await session.flush()
        if listing is not None:
            session.add(listing)
        await session.commit()
    await engine.dispose()


def _asset(
    symbol: str,
    isin: str | None,
    *,
    asset_id: str,
    asset_type: AssetType = AssetType.etf,
    currency: str = "EUR",
) -> AssetModel:
    now = datetime.now(UTC).replace(tzinfo=None)
    return AssetModel(
        id=asset_id,
        symbol=symbol,
        isin=isin,
        name="Seeded asset",
        asset_type=asset_type,
        currency=currency,
        updated_at=now,
    )


def _listing(
    asset: AssetModel,
    plan: InvestmentAssetResolutionPlan,
    *,
    listing_id: str,
    symbol: str | None = None,
    exchange: str | None = None,
    currency: str | None = None,
) -> AssetListingModel:
    return AssetListingModel(
        id=listing_id,
        asset_id=asset.id,
        symbol=symbol or plan.symbol,
        exchange=exchange or plan.exchange,
        mic=None,
        currency=currency or plan.listing_currency_hint or "EUR",
        country=None,
        provider=plan.provider,
        provider_symbol=plan.provider_symbol,
        is_primary=False,
        updated_at=datetime.now(UTC).replace(tzinfo=None),
    )


def test_new_trading212_pair_and_exact_replay_preserve_import_state() -> None:
    prefix, symbol, isin = "b2-new", "B2NEW", "ISINB2NEW"

    async def scenario() -> None:
        await _clean_assets(symbols={symbol}, isins={isin})
        await _seed_pipeline(
            prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)]
        )
        plan = await _fresh_plan(prefix)
        before = await _import_snapshot(prefix)
        engine = _engine()
        async with _session(engine) as session:
            first = await ImportInvestmentAssetResolver(session).resolve(plan=plan)
            await session.commit()
        async with _session(engine) as session:
            replay = await ImportInvestmentAssetResolver(session).resolve(plan=plan)
            await session.commit()
        await engine.dispose()
        assert (first.asset_created, first.listing_created) == (True, True)
        assert (
            replay.asset.id,
            replay.listing.id,
            replay.asset_created,
            replay.listing_created,
        ) == (
            first.asset.id,
            first.listing.id,
            False,
            False,
        )
        assert (first.asset.symbol, first.asset.isin, first.asset.currency) == (symbol, isin, "EUR")
        assert (first.listing.provider, first.listing.exchange, first.listing.currency) == (
            PriceSource.broker,
            "trading212",
            "EUR",
        )
        assert await _asset_counts(symbols={symbol}, isins={isin}) == (1, 1)
        assert await _import_snapshot(prefix) == before
        assert await _out_of_scope_counts() == {
            "AssetAlias": 0,
            "InvestmentEvent": 0,
            "InvestmentMovement": 0,
            "Transaction": 0,
        }

    asyncio.run(scenario())


def test_existing_provider_listing_is_reused_without_update() -> None:
    prefix, symbol, isin = "b2-provider", "B2PROVIDER", "ISINB2PROVIDER"

    async def scenario() -> None:
        await _clean_assets(symbols={symbol}, isins={isin})
        await _seed_pipeline(
            prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)]
        )
        plan = await _fresh_plan(prefix)
        asset = _asset(symbol, isin, asset_id="b2-provider-asset")
        listing = _listing(asset, plan, listing_id="b2-provider-listing")
        await _seed_asset(asset=asset, listing=listing)
        engine = _engine()
        async with _session(engine) as session:
            seeded = await session.get(AssetModel, asset.id)
            assert seeded is not None
            original_updated_at = seeded.updated_at
        async with _session(engine) as session:
            resolved = await ImportInvestmentAssetResolver(session).resolve(plan=plan)
            await session.commit()
        async with _session(engine) as session:
            reloaded = await session.get(AssetModel, asset.id)
            assert reloaded is not None and reloaded.updated_at == original_updated_at
        await engine.dispose()
        assert (
            resolved.asset.id,
            resolved.listing.id,
            resolved.asset_created,
            resolved.listing_created,
        ) == (
            asset.id,
            listing.id,
            False,
            False,
        )
        assert await _asset_counts(symbols={symbol}, isins={isin}) == (1, 1)

    asyncio.run(scenario())


def test_unique_isin_asset_creates_only_listing() -> None:
    prefix, symbol, isin = "b2-isin", "B2ISIN", "ISINB2ISIN"

    async def scenario() -> None:
        await _clean_assets(symbols={symbol, "OLDSYMBOL"}, isins={isin})
        await _seed_pipeline(
            prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)]
        )
        plan = await _fresh_plan(prefix)
        asset = _asset("OLDSYMBOL", isin, asset_id="b2-isin-asset")
        await _seed_asset(asset=asset)
        engine = _engine()
        async with _session(engine) as session:
            resolved = await ImportInvestmentAssetResolver(session).resolve(plan=plan)
            await session.commit()
        await engine.dispose()
        assert (resolved.asset.id, resolved.asset_created, resolved.listing_created) == (
            asset.id,
            False,
            True,
        )
        assert await _asset_counts(symbols={symbol, "OLDSYMBOL"}, isins={isin}) == (1, 1)

    asyncio.run(scenario())


def test_symbol_only_identity_never_merges_assets() -> None:
    prefix, symbol, isin = "b2-symbol", "B2SYMBOL", "ISINB2SYMBOL"

    async def scenario() -> None:
        await _clean_assets(symbols={symbol}, isins={isin, "OTHERISIN"})
        await _seed_pipeline(
            prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)]
        )
        plan = await _fresh_plan(prefix)
        unrelated = _asset(symbol, "OTHERISIN", asset_id="b2-symbol-old")
        await _seed_asset(asset=unrelated)
        engine = _engine()
        async with _session(engine) as session:
            resolved = await ImportInvestmentAssetResolver(session).resolve(plan=plan)
            await session.commit()
        await engine.dispose()
        assert resolved.asset.id != unrelated.id and resolved.asset_created is True
        assert await _asset_counts(symbols={symbol}, isins={isin, "OTHERISIN"}) == (2, 1)

    asyncio.run(scenario())


def test_missing_currency_evidence_and_ambiguous_isin_fail_without_mutation() -> None:
    missing_prefix, missing_symbol, missing_isin = "b2-missing", "B2DIV", "ISINB2DIV"
    ambiguous_prefix, ambiguous_symbol, ambiguous_isin = "b2-ambiguous", "B2AMB", "ISINB2AMB"

    async def scenario() -> None:
        await _clean_assets(
            symbols={missing_symbol, ambiguous_symbol, "B2AMBONE", "B2AMBTWO"},
            isins={missing_isin, ambiguous_isin},
        )
        await _seed_pipeline(
            missing_prefix,
            source=ImportSource.trading212,
            rows=[_trading_dividend(missing_symbol, missing_isin)],
        )
        missing_plan = await _fresh_plan(missing_prefix)
        missing_before = await _import_snapshot(missing_prefix)
        engine = _engine()
        async with _session(engine) as session:
            with pytest.raises(ImportPostStateError):
                await ImportInvestmentAssetResolver(session).resolve(plan=missing_plan)
        await engine.dispose()
        assert await _asset_counts(symbols={missing_symbol}, isins={missing_isin}) == (0, 0)
        assert await _import_snapshot(missing_prefix) == missing_before

        await _seed_pipeline(
            ambiguous_prefix,
            source=ImportSource.trading212,
            rows=[_trading_buy(ambiguous_symbol, ambiguous_isin)],
        )
        ambiguous_plan = await _fresh_plan(ambiguous_prefix)
        await _seed_asset(asset=_asset("B2AMBONE", ambiguous_isin, asset_id="b2-amb-one"))
        await _seed_asset(asset=_asset("B2AMBTWO", ambiguous_isin, asset_id="b2-amb-two"))
        async with AsyncSession(_engine()) as session:
            with pytest.raises(ImportPostStateError):
                await ImportInvestmentAssetResolver(session).resolve(plan=ambiguous_plan)
        assert await _asset_counts(
            symbols={ambiguous_symbol, "B2AMBONE", "B2AMBTWO"}, isins={ambiguous_isin}
        ) == (2, 0)

    asyncio.run(scenario())


@pytest.mark.parametrize("conflict", ["symbol", "exchange", "currency", "type", "isin"])
def test_exact_provider_corruption_fails_closed(conflict: str) -> None:
    prefix, symbol, isin = (
        f"b2-conflict-{conflict}",
        f"B2{conflict.upper()}",
        f"ISINB2{conflict.upper()}",
    )

    async def scenario() -> None:
        await _clean_assets(symbols={symbol, "OTHER"}, isins={isin, "OTHERISIN"})
        await _seed_pipeline(
            prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)]
        )
        plan = await _fresh_plan(prefix)
        asset = _asset(
            symbol if conflict != "type" else "OTHER",
            "OTHERISIN" if conflict == "isin" else isin,
            asset_id=f"{prefix}-asset",
            asset_type=AssetType.stock if conflict == "type" else AssetType.etf,
            currency="USD" if conflict == "currency" else "EUR",
        )
        listing = _listing(
            asset,
            plan,
            listing_id=f"{prefix}-listing",
            symbol="OTHER" if conflict == "symbol" else None,
            exchange="other" if conflict == "exchange" else None,
        )
        await _seed_asset(asset=asset, listing=listing)
        engine = _engine()
        async with _session(engine) as session:
            with pytest.raises(ImportPostStateError):
                await ImportInvestmentAssetResolver(session).resolve(plan=plan)
        await engine.dispose()
        assert await _asset_counts(symbols={symbol, "OTHER"}, isins={isin, "OTHERISIN"}) == (1, 1)

    asyncio.run(scenario())


def test_caller_rollback_removes_pair_then_retry_creates_one() -> None:
    prefix, symbol, isin = "b2-rollback", "B2ROLL", "ISINB2ROLL"

    async def scenario() -> None:
        await _clean_assets(symbols={symbol}, isins={isin})
        await _seed_pipeline(
            prefix, source=ImportSource.trading212, rows=[_trading_buy(symbol, isin)]
        )
        plan = await _fresh_plan(prefix)
        engine = _engine()
        async with _session(engine) as session:
            first = await ImportInvestmentAssetResolver(session).resolve(plan=plan)
            assert first.asset_created and first.listing_created
            await session.rollback()
        assert await _asset_counts(symbols={symbol}, isins={isin}) == (0, 0)
        async with _session(engine) as session:
            retry = await ImportInvestmentAssetResolver(session).resolve(plan=plan)
            await session.commit()
        async with _session(engine) as session:
            replay = await ImportInvestmentAssetResolver(session).resolve(plan=plan)
            await session.commit()
        await engine.dispose()
        assert retry.asset.id == replay.asset.id and retry.listing.id == replay.listing.id
        assert await _asset_counts(symbols={symbol}, isins={isin}) == (1, 1)

    asyncio.run(scenario())


def test_same_provider_concurrency_returns_one_pair() -> None:
    symbol, isin = "B2CONCURRENT", "ISINB2CONCURRENT"
    plan = InvestmentAssetResolutionPlan(
        symbol=symbol,
        isin=isin,
        name="Concurrent",
        asset_type=AssetType.etf,
        provider=PriceSource.broker,
        provider_symbol=symbol,
        exchange="trading212",
        listing_currency_hint="EUR",
        asset_currency_hint="EUR",
    )

    async def scenario() -> None:
        await _clean_assets(symbols={symbol}, isins={isin})
        engine = _engine()
        first_resolved = asyncio.Event()
        second_started = asyncio.Event()
        release_first = asyncio.Event()

        async def first_call():
            async with _session(engine) as session:
                result = await ImportInvestmentAssetResolver(session).resolve(plan=plan)
                first_resolved.set()
                await release_first.wait()
                await session.commit()
                return result

        async def second_call():
            await first_resolved.wait()
            second_started.set()
            async with _session(engine) as session:
                result = await ImportInvestmentAssetResolver(session).resolve(plan=plan)
                await session.commit()
                return result

        first_task = asyncio.create_task(first_call())
        second_task = asyncio.create_task(second_call())
        await second_started.wait()
        release_first.set()
        first, second = await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=10)
        await engine.dispose()
        assert (first.asset.id, first.listing.id) == (second.asset.id, second.listing.id)
        assert await _asset_counts(symbols={symbol}, isins={isin}) == (1, 1)

    asyncio.run(scenario())


def test_same_isin_different_symbols_concurrency_reuses_one_asset() -> None:
    isin = "ISINB2TWOLISTINGS"
    plan_a = InvestmentAssetResolutionPlan(
        symbol="B2ALPHA",
        isin=isin,
        name="Alpha",
        asset_type=AssetType.etf,
        provider=PriceSource.broker,
        provider_symbol="B2ALPHA",
        exchange="trading212",
        listing_currency_hint="EUR",
        asset_currency_hint="EUR",
    )
    plan_b = InvestmentAssetResolutionPlan(
        symbol="B2BETA",
        isin=isin,
        name="Beta provider symbol",
        asset_type=AssetType.etf,
        provider=PriceSource.broker,
        provider_symbol="B2BETA",
        exchange="trading212",
        listing_currency_hint="EUR",
        asset_currency_hint="EUR",
    )

    async def scenario() -> None:
        await _clean_assets(symbols={"B2ALPHA", "B2BETA"}, isins={isin})
        engine = _engine()
        first_resolved = asyncio.Event()
        second_started = asyncio.Event()
        release_first = asyncio.Event()

        async def resolve_and_hold(plan: InvestmentAssetResolutionPlan, *, hold: bool):
            async with _session(engine) as session:
                result = await ImportInvestmentAssetResolver(session).resolve(plan=plan)
                if hold:
                    first_resolved.set()
                    await release_first.wait()
                await session.commit()
                return result

        first_task = asyncio.create_task(resolve_and_hold(plan_a, hold=True))
        await first_resolved.wait()

        async def second_call():
            second_started.set()
            return await resolve_and_hold(plan_b, hold=False)

        second_task = asyncio.create_task(second_call())
        await second_started.wait()
        release_first.set()
        first, second = await asyncio.wait_for(asyncio.gather(first_task, second_task), timeout=10)
        await engine.dispose()
        assert first.asset.id == second.asset.id
        assert first.listing.provider_symbol != second.listing.provider_symbol
        assert await _asset_counts(symbols={"B2ALPHA", "B2BETA"}, isins={isin}) == (1, 2)

    asyncio.run(scenario())


def test_anycoin_transfer_resolves_crypto_exchange_identity() -> None:
    prefix, symbol = "b2-anycoin", "BTC"

    async def scenario() -> None:
        await _clean_assets(symbols={symbol}, isins=set())
        await _seed_pipeline(
            prefix,
            source=ImportSource.anycoin,
            rows=[
                {
                    "Type": "deposit",
                    "Order ID": "",
                    "Date": "2026-07-26T10:00:00Z",
                    "Amount": "0.01",
                    "Currency": "BTC",
                    "anycoin TX ID": "deposit-b2-anycoin",
                },
            ],
        )
        plan = await _fresh_plan(prefix)
        before = await _import_snapshot(prefix)
        engine = _engine()
        async with _session(engine) as session:
            resolved = await ImportInvestmentAssetResolver(session).resolve(plan=plan)
            await session.commit()
        await engine.dispose()
        assert (
            resolved.asset.asset_type,
            resolved.listing.provider,
            resolved.listing.exchange,
        ) == (
            AssetType.crypto,
            PriceSource.exchange,
            "anycoin",
        )
        assert (resolved.asset.currency, resolved.listing.currency) == ("BTC", "BTC")
        assert await _import_snapshot(prefix) == before
        assert await _out_of_scope_counts() == {
            "AssetAlias": 0,
            "InvestmentEvent": 0,
            "InvestmentMovement": 0,
            "Transaction": 0,
        }

    asyncio.run(scenario())
