"""Cross-entry and physical PostgreSQL evidence for the final 5K audit."""

from __future__ import annotations

import asyncio
import importlib
import os
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
from threading import Event
from typing import Any, cast
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_principal
from app.config.settings import Settings
from app.db.connection import get_db_session
from app.db.models.accounts import AccountMemberModel
from app.db.models.enums import AccountMemberRole, ImportSource, ImportStatus
from app.db.models.holdings import HoldingModel
from app.db.models.imports import ImportBatchModel, ImportRowModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.main import create_app
from app.modules.snapshot_refresh import version as snapshot_version_module
from app.modules.snapshot_refresh.api import (
    get_manual_user_snapshot_refresh_service,
    get_user_snapshot_refresh_clock,
)
from app.modules.snapshot_refresh.executor import (
    ExecuteUserSnapshotRefreshCommand,
    ExecuteUserSnapshotRefreshResult,
    UserSnapshotRefreshExecutor,
)
from app.modules.snapshot_refresh.manual_service import ManualUserSnapshotRefreshService

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")

posting_support = cast(
    Any,
    importlib.import_module("tests.test_import_posting_integration"),
)
post_processing_support = cast(
    Any,
    importlib.import_module("tests.test_import_post_processing_integration"),
)
manual_support = cast(
    Any,
    importlib.import_module("tests.test_snapshot_refresh_manual_endpoint_integration"),
)
posting_service_module = cast(
    Any,
    importlib.import_module("app.modules.imports.posting_service"),
)

BUCKET = datetime(2036, 7, 29, 14, 35)
COMPLETED_AT = datetime(2036, 7, 29, 14, 35, 10)


def _settings() -> Settings:
    assert DATABASE_URL is not None
    return Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        log_level="ERROR",
        log_json=False,
        internal_auth_secret="final-5k-audit-secret-with-32-characters",
        _env_file=None,
    )


def _manual_refresh_call(prefix: str):
    app = create_app(_settings())
    app.dependency_overrides[get_current_principal] = lambda: posting_support._principal(
        f"{prefix}-owner"
    )
    app.dependency_overrides[get_user_snapshot_refresh_clock] = lambda: lambda: BUCKET
    with TestClient(app) as client:
        return client.post("/api/v1/snapshot-refresh/recalculate")


async def _snapshot_state(
    prefix: str,
) -> tuple[tuple[tuple[object, ...], ...], tuple[tuple[object, ...], ...]]:
    engine = posting_support._engine()
    try:
        async with AsyncSession(engine) as session:
            account_rows = tuple(
                tuple(deepcopy(value) for value in row)
                for row in (
                    await session.execute(
                        select(*AccountSnapshotModel.__table__.columns)
                        .where(AccountSnapshotModel.account_id == f"{prefix}-account")
                        .order_by(AccountSnapshotModel.id)
                    )
                ).all()
            )
            net_worth_rows = tuple(
                tuple(deepcopy(value) for value in row)
                for row in (
                    await session.execute(
                        select(*NetWorthSnapshotModel.__table__.columns)
                        .where(NetWorthSnapshotModel.user_id == f"{prefix}-owner")
                        .order_by(NetWorthSnapshotModel.id)
                    )
                ).all()
            )
            return account_rows, net_worth_rows
    finally:
        await engine.dispose()


async def _canonical_counts(prefix: str) -> tuple[int, int, int, int, int]:
    engine = posting_support._engine()
    try:
        async with AsyncSession(engine) as session:
            batch_id = f"{prefix}-batch"
            event_ids = select(InvestmentEventModel.id).where(
                InvestmentEventModel.import_batch_id == batch_id
            )
            return (
                int(
                    await session.scalar(
                        select(func.count())
                        .select_from(InvestmentEventModel)
                        .where(InvestmentEventModel.import_batch_id == batch_id)
                    )
                    or 0
                ),
                int(
                    await session.scalar(
                        select(func.count())
                        .select_from(InvestmentMovementModel)
                        .where(InvestmentMovementModel.event_id.in_(event_ids))
                    )
                    or 0
                ),
                int(
                    await session.scalar(
                        select(func.count())
                        .select_from(HoldingModel)
                        .where(HoldingModel.account_id == f"{prefix}-account")
                    )
                    or 0
                ),
                int(
                    await session.scalar(
                        select(func.count())
                        .select_from(AccountSnapshotModel)
                        .where(AccountSnapshotModel.account_id == f"{prefix}-account")
                    )
                    or 0
                ),
                int(
                    await session.scalar(
                        select(func.count())
                        .select_from(NetWorthSnapshotModel)
                        .where(NetWorthSnapshotModel.user_id == f"{prefix}-owner")
                    )
                    or 0
                ),
            )
    finally:
        await engine.dispose()


async def _cleanup_import_case(prefix: str, symbol: str) -> None:
    await post_processing_support._cleanup_holdings(prefix)
    await posting_support._cleanup(prefix)
    await post_processing_support._remove_market_evidence(prefix)
    await posting_support._remove_asset_identities({symbol})


def test_manual_and_import_refresh_same_bucket_preserve_immutable_identity() -> None:
    async def scenario() -> None:
        prefix = "k5-final-cross-source"
        symbol = "K5FINALCROSS"
        await posting_support._seed(
            prefix,
            source=ImportSource.trading212,
            rows=[posting_support._trading_buy(symbol, f"{prefix}-external")],
        )
        try:
            await post_processing_support._seed_investment_identity(prefix, symbol)
            await posting_support._prepare(prefix)
            with patch.object(
                posting_service_module,
                "_current_timestamp",
                return_value=COMPLETED_AT,
            ):
                imported = await post_processing_support._post(prefix)
            assert imported.snapshot_refresh_status.value == "created"
            assert imported.completed_at == COMPLETED_AT
            original = await _snapshot_state(prefix)
            assert len(original[0]) == len(original[1]) == 1
            assert original[0][0][2] == BUCKET
            assert original[1][0][2] == BUCKET

            manual = await asyncio.to_thread(_manual_refresh_call, prefix)
            assert manual.status_code == 409
            error = manual.json()["error"]
            assert error == {
                "code": "snapshot_refresh_conflict",
                "message": "Snapshot refresh conflicts with existing data.",
                "request_id": error["request_id"],
            }
            UUID(error["request_id"])
            assert await _snapshot_state(prefix) == original
            assert await _canonical_counts(prefix) == (1, 2, 1, 1, 1)

            engine = posting_support._engine()
            try:
                async with AsyncSession(engine) as session:
                    batch = await session.get(ImportBatchModel, f"{prefix}-batch")
                    row = await session.scalar(
                        select(ImportRowModel).where(
                            ImportRowModel.import_batch_id == f"{prefix}-batch"
                        )
                    )
                    assert batch is not None
                    assert batch.status is ImportStatus.completed
                    assert batch.completed_at == COMPLETED_AT
                    assert row is not None
                    assert row.created_investment_event_id is not None
            finally:
                await engine.dispose()
        finally:
            await _cleanup_import_case(prefix, symbol)

    asyncio.run(scenario())


def test_coordinated_version_mismatch_fails_before_snapshot_writes() -> None:
    manual_prefix = "k5-final-version-manual"
    import_prefix = "k5-final-version-import"
    symbol = "K5FINALVERSION"
    asyncio.run(manual_support._seed(manual_prefix, ()))
    asyncio.run(
        posting_support._seed(
            import_prefix,
            source=ImportSource.trading212,
            rows=[
                posting_support._trading_buy(
                    symbol,
                    f"{import_prefix}-external",
                )
            ],
        )
    )
    try:
        asyncio.run(post_processing_support._seed_investment_identity(import_prefix, symbol))
        asyncio.run(posting_support._prepare(import_prefix))
        mismatched_version = (
            snapshot_version_module.CURRENT_ACCOUNT_SNAPSHOT_CALCULATION_VERSION + 1
        )
        with patch.object(
            snapshot_version_module,
            "CURRENT_NET_WORTH_CALCULATION_VERSION",
            mismatched_version,
        ):
            manual = manual_support._call(manual_prefix)
            with patch.object(
                posting_service_module,
                "_current_timestamp",
                return_value=COMPLETED_AT,
            ):
                imported = post_processing_support._endpoint_call(import_prefix)

        assert manual.status_code == 409
        error = manual.json()["error"]
        assert error == {
            "code": "snapshot_refresh_unavailable",
            "message": "Snapshot refresh cannot be completed from the current account data.",
            "request_id": error["request_id"],
        }
        UUID(error["request_id"])
        assert imported.status_code == 200
        imported_payload = imported.json()
        assert imported_payload["snapshot_refresh_status"] == "unavailable"
        assert set(imported_payload) == {
            "batch_id",
            "status",
            "rows_total",
            "rows_imported",
            "rows_skipped",
            "completed_at",
            "replayed",
            "snapshot_refresh_status",
        }
        assert asyncio.run(manual_support._counts(manual_prefix)) == (0, 0)
        assert asyncio.run(_canonical_counts(import_prefix)) == (1, 2, 1, 0, 0)

        async def verify_committed_import() -> None:
            engine = posting_support._engine()
            try:
                async with AsyncSession(engine) as session:
                    batch = await session.get(
                        ImportBatchModel,
                        f"{import_prefix}-batch",
                    )
                    assert batch is not None
                    assert batch.status is ImportStatus.completed
                    assert batch.completed_at == COMPLETED_AT
            finally:
                await engine.dispose()

        asyncio.run(verify_committed_import())
    finally:
        asyncio.run(manual_support._cleanup(manual_prefix))
        asyncio.run(_cleanup_import_case(import_prefix, symbol))


def test_viewer_only_user_reuses_exact_snapshot_without_writer_creation() -> None:
    prefix = "k5-final-viewer-only"
    asyncio.run(
        manual_support._seed(
            prefix,
            (
                manual_support._AccountSpec(
                    "viewer",
                    AccountMemberRole.viewer,
                ),
            ),
        )
    )
    snapshot_id = asyncio.run(manual_support._write_viewer_snapshot(prefix, "viewer"))
    try:
        first = manual_support._call(prefix)
        replay = manual_support._call(prefix)

        assert first.status_code == replay.status_code == 200
        assert first.json() == {
            "netWorthSnapshotId": first.json()["netWorthSnapshotId"],
            "netWorthStatus": "created",
            "timestamp": "2036-07-29T14:35:00.000",
            "granularity": "minute",
            "currency": "EUR",
            "calculationVersion": 1,
            "accounts": [
                {
                    "accountId": manual_support._account_id(prefix, "viewer"),
                    "snapshotId": snapshot_id,
                }
            ],
            "refreshAccountCount": 0,
            "reuseOnlyAccountCount": 1,
            "createdAccountSnapshotCount": 0,
            "replayedAccountSnapshotCount": 0,
            "reusedAccountSnapshotCount": 1,
            "selectedAccountSnapshotCount": 1,
        }
        assert replay.json()["netWorthStatus"] == "replayed"
        assert replay.json()["netWorthSnapshotId"] == first.json()["netWorthSnapshotId"]
        assert replay.json()["reusedAccountSnapshotCount"] == 1
        assert replay.json()["accounts"] == first.json()["accounts"]
        assert asyncio.run(manual_support._counts(prefix)) == (1, 1)

        async def selected_snapshot_ids() -> tuple[str, ...]:
            engine = posting_support._engine()
            try:
                async with AsyncSession(engine) as session:
                    return tuple(
                        await session.scalars(
                            select(AccountSnapshotModel.id).where(
                                AccountSnapshotModel.account_id
                                == manual_support._account_id(prefix, "viewer")
                            )
                        )
                    )
            finally:
                await engine.dispose()

        assert asyncio.run(selected_snapshot_ids()) == (snapshot_id,)
    finally:
        asyncio.run(manual_support._cleanup(prefix))


def test_role_revocation_between_auth_and_coverage_is_detected() -> None:
    prefix = "k5-final-role-revocation"
    ready = Event()
    release = Event()
    asyncio.run(
        manual_support._seed(
            prefix,
            (manual_support._AccountSpec("account", AccountMemberRole.owner),),
        )
    )

    class _BarrierExecutor:
        def __init__(self, session: AsyncSession) -> None:
            self.session = session

        async def execute(
            self,
            command: ExecuteUserSnapshotRefreshCommand,
        ) -> ExecuteUserSnapshotRefreshResult:
            ready.set()
            assert await asyncio.to_thread(release.wait, 10)
            return await UserSnapshotRefreshExecutor(self.session).execute(command)

    app = create_app(_settings())
    app.dependency_overrides[get_current_principal] = lambda: manual_support._principal(
        manual_support._user_id(prefix)
    )

    def service_dependency(
        session: AsyncSession = Depends(get_db_session),
    ) -> ManualUserSnapshotRefreshService:
        return ManualUserSnapshotRefreshService(
            session,
            clock=lambda: BUCKET,
            executor_factory=_BarrierExecutor,
        )

    app.dependency_overrides[get_manual_user_snapshot_refresh_service] = service_dependency

    async def revoke_role() -> None:
        engine = posting_support._engine()
        try:
            async with AsyncSession(engine) as session:
                membership = await session.get(
                    AccountMemberModel,
                    f"{prefix}-member-account",
                )
                assert membership is not None
                membership.role = AccountMemberRole.viewer
                await session.commit()
        finally:
            await engine.dispose()

    def call_endpoint():
        with TestClient(app) as client:
            return client.post("/api/v1/snapshot-refresh/recalculate")

    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            request = pool.submit(call_endpoint)
            assert ready.wait(10)
            asyncio.run(revoke_role())
            release.set()
            response = request.result(timeout=30)

        assert response.status_code == 409
        error = response.json()["error"]
        assert error == {
            "code": "snapshot_refresh_unavailable",
            "message": "Snapshot refresh cannot be completed from the current account data.",
            "request_id": error["request_id"],
        }
        UUID(error["request_id"])
        assert prefix not in response.text
        assert asyncio.run(manual_support._counts(prefix)) == (0, 0)
    finally:
        release.set()
        app.dependency_overrides.clear()
        asyncio.run(manual_support._cleanup(prefix))


@pytest.mark.asyncio
async def test_physical_postgresql_snapshot_contract_matches_final_5k_audit() -> None:
    engine = posting_support._engine()
    try:
        async with AsyncSession(engine) as session:
            physical_counts = (
                await session.execute(
                    text(
                        """
                        SELECT
                            (
                                SELECT count(*)
                                FROM information_schema.tables
                                WHERE table_schema = 'public'
                                  AND table_type = 'BASE TABLE'
                            ) AS table_count,
                            (
                                SELECT count(*)
                                FROM pg_type AS type
                                JOIN pg_namespace AS namespace
                                  ON namespace.oid = type.typnamespace
                                WHERE namespace.nspname = 'public'
                                  AND type.typtype = 'e'
                            ) AS enum_count
                        """
                    )
                )
            ).one()
            assert physical_counts == (32, 28)

            columns = {
                (row.table_name, row.column_name): row
                for row in (
                    await session.execute(
                        text(
                            """
                            SELECT
                                table_name,
                                column_name,
                                data_type,
                                udt_name,
                                datetime_precision,
                                numeric_precision,
                                numeric_scale
                            FROM information_schema.columns
                            WHERE table_schema = 'public'
                              AND table_name IN (
                                'AccountSnapshot',
                                'AccountSnapshotItem',
                                'NetWorthSnapshot',
                                'ImportLog'
                              )
                            """
                        )
                    )
                ).all()
            }
            for table_name, column_name in (
                ("AccountSnapshot", "timestamp"),
                ("AccountSnapshot", "calculatedAt"),
                ("AccountSnapshot", "createdAt"),
                ("AccountSnapshotItem", "priceTimestamp"),
                ("AccountSnapshotItem", "createdAt"),
                ("NetWorthSnapshot", "timestamp"),
                ("NetWorthSnapshot", "calculatedAt"),
                ("NetWorthSnapshot", "createdAt"),
                ("ImportLog", "createdAt"),
            ):
                column = columns[(table_name, column_name)]
                assert column.data_type == "timestamp without time zone"
                assert column.datetime_precision == 3

            for table_name, column_name in (
                ("AccountSnapshot", "cashValue"),
                ("AccountSnapshot", "investmentValue"),
                ("AccountSnapshot", "investmentCostBasis"),
                ("AccountSnapshot", "liabilitiesValue"),
                ("AccountSnapshot", "totalValue"),
                ("AccountSnapshot", "netDepositsValue"),
                ("AccountSnapshot", "realizedPnlValue"),
                ("AccountSnapshot", "unrealizedPnlValue"),
                ("AccountSnapshot", "feesValue"),
                ("AccountSnapshot", "taxesValue"),
                ("AccountSnapshotItem", "value"),
                ("NetWorthSnapshot", "cashValue"),
                ("NetWorthSnapshot", "portfolioValue"),
                ("NetWorthSnapshot", "liabilitiesValue"),
                ("NetWorthSnapshot", "totalNetWorth"),
            ):
                column = columns[(table_name, column_name)]
                assert (column.numeric_precision, column.numeric_scale) == (18, 6)

            for column_name in (
                "quantity",
                "pricePerUnit",
                "costBasis",
                "nativeValue",
                "nativeCostBasis",
            ):
                column = columns[("AccountSnapshotItem", column_name)]
                assert (column.numeric_precision, column.numeric_scale) == (28, 10)
            allocation = columns[("AccountSnapshotItem", "allocationPct")]
            assert (allocation.numeric_precision, allocation.numeric_scale) == (8, 4)

            jsonb_columns = {key for key, value in columns.items() if value.udt_name == "jsonb"}
            assert {
                ("AccountSnapshot", "cashValueByCurrency"),
                ("AccountSnapshot", "investmentValueByCurrency"),
                ("AccountSnapshot", "investmentCostBasisByCurrency"),
                ("AccountSnapshot", "netDepositsByCurrency"),
                ("AccountSnapshot", "realizedPnlByCurrency"),
                ("AccountSnapshot", "unrealizedPnlByCurrency"),
                ("AccountSnapshot", "feesByCurrency"),
                ("AccountSnapshot", "taxesByCurrency"),
                ("AccountSnapshot", "exchangeRates"),
                ("NetWorthSnapshot", "cashValueByCurrency"),
                ("NetWorthSnapshot", "portfolioValueByCurrency"),
                ("NetWorthSnapshot", "liabilitiesValueByCurrency"),
                ("NetWorthSnapshot", "totalNetWorthByCurrency"),
                ("NetWorthSnapshot", "exchangeRates"),
            }.issubset(jsonb_columns)

            constraints = {
                (row.table_name, row.contype, row.definition)
                for row in (
                    await session.execute(
                        text(
                            """
                            SELECT
                                cls.relname AS table_name,
                                con.contype::text AS contype,
                                pg_get_constraintdef(con.oid) AS definition
                            FROM pg_constraint AS con
                            JOIN pg_class AS cls ON cls.oid = con.conrelid
                            JOIN pg_namespace AS ns ON ns.oid = cls.relnamespace
                            WHERE ns.nspname = 'public'
                              AND cls.relname IN (
                                'AccountSnapshot',
                                'AccountSnapshotItem',
                                'NetWorthSnapshot',
                                'ImportLog'
                              )
                            """
                        )
                    )
                ).all()
            }
            assert ("ImportLog", "p", "PRIMARY KEY (id)") in constraints
            assert (
                "AccountSnapshotItem",
                "f",
                'FOREIGN KEY ("snapshotId") REFERENCES "AccountSnapshot"(id) ON UPDATE CASCADE ON DELETE CASCADE',
            ) in constraints
            assert (
                "AccountSnapshotItem",
                "f",
                'FOREIGN KEY ("listingId") REFERENCES "AssetListing"(id) ON UPDATE CASCADE ON DELETE RESTRICT',
            ) in constraints

            index_definitions = tuple(
                (
                    await session.scalars(
                        text(
                            """
                            SELECT indexdef
                            FROM pg_indexes
                            WHERE schemaname = 'public'
                              AND tablename IN (
                                'AccountSnapshot',
                                'AccountSnapshotItem',
                                'NetWorthSnapshot',
                                'ImportLog'
                              )
                            ORDER BY tablename, indexname
                            """
                        )
                    )
                ).all()
            )
            index_text = "\n".join(index_definitions)
            for required in (
                '"accountId", granularity, "timestamp"',
                'CREATE UNIQUE INDEX "AccountSnapshot_accountId_timestamp_currency_granularity_key"',
                '"accountId", "timestamp", currency, granularity',
                '"userId", granularity, "timestamp"',
                'CREATE UNIQUE INDEX "NetWorthSnapshot_userId_timestamp_currency_granularity_key"',
                '"userId", "timestamp", currency, granularity',
                'CREATE UNIQUE INDEX "AccountSnapshotItem_snapshotId_listingId_key"',
                '"snapshotId", "listingId"',
                '"importBatchId", "createdAt"',
            ):
                assert required in index_text

            for table_name, identity in (
                (
                    "AccountSnapshot",
                    '"accountId", "timestamp", currency, granularity',
                ),
                (
                    "NetWorthSnapshot",
                    '"userId", "timestamp", currency, granularity',
                ),
                (
                    "AccountSnapshotItem",
                    '"snapshotId", "listingId"',
                ),
            ):
                duplicate_count = await session.scalar(
                    text(
                        f"""
                        SELECT count(*)
                        FROM (
                            SELECT {identity}
                            FROM public."{table_name}"
                            GROUP BY {identity}
                            HAVING count(*) > 1
                        ) AS duplicates
                        """
                    )
                )
                assert duplicate_count == 0

            forbidden_tables = await session.scalar(
                text(
                    """
                    SELECT count(*)
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                      AND table_name IN (
                        'SnapshotRefreshJob',
                        'SnapshotRefreshExecution',
                        'ImportPostProcessingJob'
                      )
                    """
                )
            )
            assert forbidden_tables == 0
            assert not session.new
            assert not session.dirty
            assert not session.deleted
            await session.rollback()
            assert session.in_transaction() is False
    finally:
        await engine.dispose()
