from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.canonical_lineage import AccountCanonicalStateModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.db.url import normalize_database_url
from app.modules.canonical_state import CanonicalChangeKind, CanonicalStateService
from app.modules.holdings.rebuild_service import HoldingRebuildService
from app.modules.snapshot_refresh.executor import (
    ExecuteUserSnapshotRefreshCommand,
    UserSnapshotRefreshExecutor,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required"),
]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
PREVIOUS_SCHEMA = BACKEND_ROOT / "database" / "revisions" / "3m0001importanchor" / "schema.sql"
NOW = datetime(2026, 8, 19, 12, 0)
EVENT_AT = datetime(2026, 8, 18, 10, 0)
SNAPSHOT_AT = datetime(2026, 8, 19, 11, 55)


def _run_alembic(database_url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = database_url
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(BACKEND_ROOT / "alembic.ini"),
            *arguments,
        ],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


async def _seed_previous_head(connection: asyncpg.Connection, prefix: str) -> None:
    user_id = f"{prefix}-user"
    await connection.execute(
        'INSERT INTO public."User" '
        '(id, email, name, "passwordHash", "baseCurrency", "createdAt", "updatedAt") '
        "VALUES ($1, $2, NULL, NULL, 'CZK', $3, $3)",
        user_id,
        f"{prefix}@example.test",
        NOW,
    )
    for suffix, account_type in (
        ("empty-exchange", "exchange"),
        ("cash", "bank"),
        ("ambiguous-broker", "broker"),
    ):
        await connection.execute(
            'INSERT INTO public."Account" '
            '(id, name, type, currency, color, "isArchived", "archivedAt", '
            '"createdAt", "updatedAt", notes) '
            "VALUES ($1, $2, $3, 'CZK', NULL, false, NULL, $4, $4, NULL)",
            f"{prefix}-{suffix}",
            suffix,
            account_type,
            NOW,
        )
    await connection.execute(
        'INSERT INTO public."AccountCanonicalChange" '
        '("accountId", revision, kind, "entityId", "financialTimestamp", "createdAt") '
        "VALUES ($1, 1, 'investment_event', $2, $3, $3)",
        f"{prefix}-ambiguous-broker",
        f"{prefix}-ambiguous-root",
        EVENT_AT,
    )


async def _seed_funded_broker_and_refresh(database_url: str, prefix: str) -> None:
    user_id = f"{prefix}-user"
    broker_id = f"{prefix}-funded-broker"
    exchange_id = f"{prefix}-fresh-exchange"
    engine = create_async_engine(normalize_database_url(database_url))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            for account_id, name, account_type in (
                (broker_id, "Funded broker", AccountType.broker),
                (exchange_id, "Fresh empty exchange", AccountType.exchange),
            ):
                session.add(
                    AccountModel(
                        id=account_id,
                        name=name,
                        type=account_type,
                        currency="CZK",
                        color=None,
                        notes=None,
                        is_archived=False,
                        archived_at=None,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
            await session.flush()
            for account_id in (broker_id, exchange_id):
                state = await session.get(AccountCanonicalStateModel, account_id)
                assert state is not None
                assert state.holding_revision == 0
                session.add(
                    AccountMemberModel(
                        id=f"{account_id}-member",
                        account_id=account_id,
                        user_id=user_id,
                        role=AccountMemberRole.owner,
                        relation_type=AccountRelationType.owner,
                        invited_by_id=None,
                        accepted_at=NOW,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
            event_id = f"{prefix}-deposit"
            session.add(
                InvestmentEventModel(
                    id=event_id,
                    account_id=broker_id,
                    type=InvestmentEventType.cash_deposit,
                    date=EVENT_AT,
                    source=None,
                    external_id=event_id,
                    order_id=None,
                    description="Funded broker cash",
                    realized_pnl=None,
                    realized_pnl_currency=None,
                    import_batch_id=None,
                    archived_at=None,
                    deleted_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await session.flush()
            session.add(
                InvestmentMovementModel(
                    id=f"{prefix}-deposit-movement",
                    event_id=event_id,
                    account_id=broker_id,
                    asset_id=None,
                    listing_id=None,
                    kind=InvestmentMovementKind.cash,
                    direction=MovementDirection.incoming,
                    quantity=Decimal("1000"),
                    currency="CZK",
                    price_per_unit=None,
                    value_amount=Decimal("1000"),
                    value_currency="CZK",
                    source_symbol=None,
                    source_asset_type=None,
                    note=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            await CanonicalStateService(session).record(
                account_id=broker_id,
                kind=CanonicalChangeKind.investment_event,
                entity_id=event_id,
                financial_timestamp=EVENT_AT,
                created_at=NOW,
                replay=False,
            )
            await HoldingRebuildService(session).rebuild(account_id=broker_id, rebuilt_at=NOW)
            await session.commit()

            refreshed = await UserSnapshotRefreshExecutor(session).execute(
                ExecuteUserSnapshotRefreshCommand(
                    user_id=user_id,
                    snapshot_timestamp=SNAPSHOT_AT,
                    granularity=SnapshotGranularity.minute,
                    source=SnapshotSource.import_event,
                    calculation_version=2,
                    calculated_at=NOW,
                    created_at=NOW,
                    is_recalculated=False,
                )
            )
            assert {item.account_id for item in refreshed.account_snapshots} == {
                broker_id,
                exchange_id,
            }
            assert refreshed.selected_account_snapshot_count == 2

        async with AsyncSession(engine) as session:
            snapshots = tuple(
                (
                    await session.scalars(
                        select(AccountSnapshotModel)
                        .where(AccountSnapshotModel.account_id.in_((broker_id, exchange_id)))
                        .order_by(AccountSnapshotModel.account_id)
                    )
                ).all()
            )
            assert len(snapshots) == 2
            by_account = {snapshot.account_id: snapshot for snapshot in snapshots}
            assert by_account[broker_id].total_value == Decimal("1000.000000")
            assert by_account[exchange_id].total_value == Decimal("0.000000")
            net_worth = await session.scalar(
                select(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id == user_id)
            )
            assert net_worth is not None
            assert net_worth.total_net_worth == Decimal("1000.000000")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_previous_head_upgrade_initializes_only_proven_empty_investment_state() -> None:
    assert DATABASE_URL is not None
    source_url = make_url(normalize_database_url(DATABASE_URL))
    database_name = f"finance_app_3n_emptyhold_{uuid4().hex}"
    admin_url = source_url.set(drivername="postgresql", database="postgres")
    target_url = source_url.set(database=database_name)
    admin_dsn = admin_url.render_as_string(hide_password=False)
    target_dsn = target_url.set(drivername="postgresql").render_as_string(hide_password=False)
    target_database_url = target_url.render_as_string(hide_password=False)
    prefix = f"emptyhold-{uuid4().hex}"
    admin = await asyncpg.connect(admin_dsn)
    try:
        await admin.execute(f'CREATE DATABASE "{database_name}"')
        target = await asyncpg.connect(target_dsn)
        try:
            previous_schema = PREVIOUS_SCHEMA.read_text(encoding="utf-8").replace(
                'CREATE SCHEMA "public";\n', "", 1
            )
            await target.execute(previous_schema)
            await target.execute(
                "CREATE TABLE public.alembic_version ("
                "version_num varchar(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            )
            await target.execute(
                "INSERT INTO public.alembic_version (version_num) VALUES ('3m0001importanchor')"
            )
            await _seed_previous_head(target, prefix)
        finally:
            await target.close()

        upgraded = _run_alembic(target_database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr

        target = await asyncpg.connect(target_dsn)
        try:
            rows = await target.fetch(
                'SELECT account.id, state."holdingRevision" '
                'FROM public."Account" AS account '
                'JOIN public."AccountCanonicalState" AS state '
                'ON state."accountId" = account.id ORDER BY account.id'
            )
            states = {row["id"]: row["holdingRevision"] for row in rows}
            assert states[f"{prefix}-empty-exchange"] == 0
            assert states[f"{prefix}-cash"] is None
            assert states[f"{prefix}-ambiguous-broker"] is None

            for suffix, account_type, expected in (
                ("new-wallet", "crypto_wallet", 0),
                ("new-bank", "bank", None),
            ):
                account_id = f"{prefix}-{suffix}"
                await target.execute(
                    'INSERT INTO public."Account" '
                    '(id, name, type, currency, color, "isArchived", "archivedAt", '
                    '"createdAt", "updatedAt", notes) '
                    "VALUES ($1, $2, $3, 'CZK', NULL, false, NULL, $4, $4, NULL)",
                    account_id,
                    suffix,
                    account_type,
                    NOW,
                )
                assert (
                    await target.fetchval(
                        'SELECT "holdingRevision" FROM public."AccountCanonicalState" '
                        'WHERE "accountId" = $1',
                        account_id,
                    )
                    == expected
                )
        finally:
            await target.close()

        downgrade = _run_alembic(target_database_url, "downgrade", "3m0001importanchor")
        assert downgrade.returncode != 0
        assert (
            "Cannot remove initialized empty investment Holding revisions automatically."
            in downgrade.stdout + downgrade.stderr
        )

        await _seed_funded_broker_and_refresh(target_database_url, prefix)
    finally:
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database_name,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{database_name}"')
        await admin.close()
