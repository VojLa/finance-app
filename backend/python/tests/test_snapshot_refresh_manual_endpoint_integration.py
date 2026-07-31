"""PostgreSQL endpoint evidence for coordinated manual snapshot refresh."""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    ExchangeRateSource,
    LiabilityBalanceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.prices import ExchangeRateModel
from app.db.models.snapshots import (
    AccountSnapshotItemModel,
    AccountSnapshotModel,
    NetWorthSnapshotModel,
)
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.snapshot_refresh.api import get_user_snapshot_refresh_clock
from app.modules.snapshots.writer import AccountSnapshotWriter, WriteAccountSnapshotCommand

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
BUCKET = datetime(2036, 7, 29, 14, 35)
EVIDENCE_AT = BUCKET - timedelta(days=1)


@dataclass(frozen=True, slots=True)
class _AccountSpec:
    suffix: str
    role: AccountMemberRole = AccountMemberRole.owner
    currency: str = "EUR"
    amount: Decimal = Decimal("100")
    with_rate: bool = True
    account_type: AccountType = AccountType.loan


def _engine() -> AsyncEngine:
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=12)


def _user_id(prefix: str) -> str:
    return f"{prefix}-user"


def _account_id(prefix: str, suffix: str) -> str:
    return f"{prefix}-{suffix}"


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.test",
        name=user_id,
    )


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            user_ids = tuple(
                await session.scalars(
                    select(UserModel.id).where(UserModel.id.startswith(f"{prefix}-"))
                )
            )
            account_ids = tuple(
                await session.scalars(
                    select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
                )
            )
            snapshot_ids = (
                tuple(
                    await session.scalars(
                        select(AccountSnapshotModel.id).where(
                            AccountSnapshotModel.account_id.in_(account_ids)
                        )
                    )
                )
                if account_ids
                else ()
            )
            if snapshot_ids:
                await session.execute(
                    delete(AccountSnapshotItemModel).where(
                        AccountSnapshotItemModel.snapshot_id.in_(snapshot_ids)
                    )
                )
            if user_ids:
                await session.execute(
                    delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id.in_(user_ids))
                )
            if account_ids:
                await session.execute(
                    delete(AccountSnapshotModel).where(
                        AccountSnapshotModel.account_id.in_(account_ids)
                    )
                )
                await session.execute(
                    delete(LiabilityBalanceModel).where(
                        LiabilityBalanceModel.account_id.in_(account_ids)
                    )
                )
                await session.execute(
                    delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
                )
                await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
            await session.execute(
                delete(ExchangeRateModel).where(ExchangeRateModel.id.startswith(f"{prefix}-"))
            )
            if user_ids:
                await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
            await session.commit()
    finally:
        await engine.dispose()


async def _seed(prefix: str, specs: tuple[_AccountSpec, ...]) -> None:
    await _cleanup(prefix)
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            session.add(
                UserModel(
                    id=_user_id(prefix),
                    email=f"{prefix}@example.test",
                    name="Manual snapshot refresh",
                    password_hash=None,
                    base_currency="EUR",
                    created_at=EVIDENCE_AT,
                    updated_at=EVIDENCE_AT,
                )
            )
            for spec in specs:
                account_id = _account_id(prefix, spec.suffix)
                session.add(
                    AccountModel(
                        id=account_id,
                        name=spec.suffix,
                        type=spec.account_type,
                        currency=spec.currency,
                        color=None,
                        is_archived=False,
                        archived_at=None,
                        created_at=EVIDENCE_AT,
                        updated_at=EVIDENCE_AT,
                        notes=None,
                    )
                )
                await session.flush()
                session.add(
                    AccountMemberModel(
                        id=f"{prefix}-member-{spec.suffix}",
                        account_id=account_id,
                        user_id=_user_id(prefix),
                        role=spec.role,
                        relation_type=AccountRelationType.owner,
                        invited_by_id=None,
                        accepted_at=EVIDENCE_AT,
                        created_at=EVIDENCE_AT,
                        updated_at=EVIDENCE_AT,
                    )
                )
                if spec.account_type in {
                    AccountType.credit_card,
                    AccountType.loan,
                    AccountType.mortgage,
                }:
                    session.add(
                        LiabilityBalanceModel(
                            id=f"{prefix}-balance-{spec.suffix}",
                            account_id=account_id,
                            effective_at=EVIDENCE_AT,
                            currency=spec.currency,
                            outstanding_principal=spec.amount,
                            accrued_interest=Decimal("0"),
                            fees_outstanding=Decimal("0"),
                            total_outstanding=spec.amount,
                            source=LiabilityBalanceSource.statement,
                            external_id=f"{prefix}-external-{spec.suffix}",
                            created_at=EVIDENCE_AT,
                        )
                    )
                    if spec.currency != "EUR" and spec.with_rate:
                        session.add(
                            ExchangeRateModel(
                                id=f"{prefix}-rate-{spec.suffix}",
                                from_currency=spec.currency,
                                to_currency="EUR",
                                rate=Decimal("0.90000000"),
                                date=EVIDENCE_AT,
                                source=ExchangeRateSource.ecb,
                                created_at=EVIDENCE_AT,
                            )
                        )
            await session.commit()
    finally:
        await engine.dispose()


async def _write_viewer_snapshot(prefix: str, suffix: str) -> str:
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            result = await AccountSnapshotWriter(session).write(
                WriteAccountSnapshotCommand(
                    account_id=_account_id(prefix, suffix),
                    snapshot_timestamp=BUCKET,
                    granularity=SnapshotGranularity.minute,
                    source=SnapshotSource.manual_recalculation,
                    calculation_version=1,
                    calculated_at=BUCKET,
                    created_at=BUCKET,
                    is_recalculated=True,
                    output_currency="EUR",
                )
            )
        return result.snapshot_id
    finally:
        await engine.dispose()


def _call(prefix: str, *, user_id: str | None = None):
    settings = Settings(
        environment="test",
        database_url=DATABASE_URL,
        docs_enabled=True,
        internal_auth_secret="test-secret-that-is-long-enough-for-auth",
        _env_file=None,
    )
    app = create_app(settings)
    principal_id = _user_id(prefix) if user_id is None else user_id
    app.dependency_overrides[get_current_principal] = lambda: _principal(principal_id)
    app.dependency_overrides[get_user_snapshot_refresh_clock] = lambda: lambda: BUCKET
    with TestClient(app) as client:
        return client.post("/api/v1/snapshot-refresh/recalculate")


async def _counts(prefix: str) -> tuple[int, int]:
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            account_ids = select(AccountModel.id).where(AccountModel.id.startswith(f"{prefix}-"))
            account_count = (
                await session.scalar(
                    select(func.count())
                    .select_from(AccountSnapshotModel)
                    .where(AccountSnapshotModel.account_id.in_(account_ids))
                )
                or 0
            )
            net_worth_count = (
                await session.scalar(
                    select(func.count())
                    .select_from(NetWorthSnapshotModel)
                    .where(NetWorthSnapshotModel.user_id == _user_id(prefix))
                )
                or 0
            )
            return int(account_count), int(net_worth_count)
    finally:
        await engine.dispose()


def test_mixed_create_and_fresh_session_replay() -> None:
    prefix = "k5e1-mixed"
    asyncio.run(
        _seed(
            prefix,
            (
                _AccountSpec("a-owner"),
                _AccountSpec("b-editor-usd", AccountMemberRole.editor, "USD"),
                _AccountSpec("c-viewer", AccountMemberRole.viewer),
            ),
        )
    )
    asyncio.run(_write_viewer_snapshot(prefix, "c-viewer"))
    try:
        first = _call(prefix)
        replay = _call(prefix)

        assert first.status_code == replay.status_code == 200
        assert first.json() == {
            "netWorthSnapshotId": first.json()["netWorthSnapshotId"],
            "netWorthStatus": "created",
            "timestamp": "2036-07-29T14:35:00.000",
            "granularity": "minute",
            "currency": "EUR",
            "calculationVersion": 1,
            "accounts": first.json()["accounts"],
            "refreshAccountCount": 2,
            "reuseOnlyAccountCount": 1,
            "createdAccountSnapshotCount": 2,
            "replayedAccountSnapshotCount": 0,
            "reusedAccountSnapshotCount": 1,
            "selectedAccountSnapshotCount": 3,
        }
        assert replay.json()["netWorthStatus"] == "replayed"
        assert replay.json()["netWorthSnapshotId"] == first.json()["netWorthSnapshotId"]
        assert replay.json()["createdAccountSnapshotCount"] == 0
        assert replay.json()["replayedAccountSnapshotCount"] == 2
        assert replay.json()["reusedAccountSnapshotCount"] == 1
        assert replay.json()["accounts"] == first.json()["accounts"]
        assert [item["accountId"] for item in first.json()["accounts"]] == [
            _account_id(prefix, "a-owner"),
            _account_id(prefix, "b-editor-usd"),
            _account_id(prefix, "c-viewer"),
        ]
        assert len({item["snapshotId"] for item in first.json()["accounts"]}) == 3
        assert asyncio.run(_counts(prefix)) == (3, 1)
    finally:
        asyncio.run(_cleanup(prefix))


def test_missing_viewer_coverage_is_generic_and_writes_nothing() -> None:
    prefix = "k5e1-viewer-missing"
    asyncio.run(
        _seed(
            prefix,
            (
                _AccountSpec("a-owner"),
                _AccountSpec("b-viewer", AccountMemberRole.viewer),
            ),
        )
    )
    try:
        response = _call(prefix)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "snapshot_refresh_unavailable"
        assert response.json()["error"]["message"] == (
            "Snapshot refresh cannot be completed from the current account data."
        )
        assert _account_id(prefix, "b-viewer") not in response.text
        assert asyncio.run(_counts(prefix)) == (0, 0)
    finally:
        asyncio.run(_cleanup(prefix))


def test_partial_failure_commits_prefix_and_retry_resumes() -> None:
    prefix = "k5e1-resume"
    asyncio.run(
        _seed(
            prefix,
            (
                _AccountSpec("a-eur"),
                _AccountSpec("b-xzz", currency="XZZ", with_rate=False),
            ),
        )
    )
    try:
        first = _call(prefix)
        assert first.status_code == 409
        assert first.json()["error"]["code"] == "snapshot_refresh_unavailable"
        assert asyncio.run(_counts(prefix)) == (1, 0)

        async def add_rate() -> None:
            engine = _engine()
            try:
                async with AsyncSession(engine) as session:
                    session.add(
                        ExchangeRateModel(
                            id=f"{prefix}-rate-b-xzz",
                            from_currency="XZZ",
                            to_currency="EUR",
                            rate=Decimal("0.90000000"),
                            date=EVIDENCE_AT,
                            source=ExchangeRateSource.ecb,
                            created_at=EVIDENCE_AT,
                        )
                    )
                    await session.commit()
            finally:
                await engine.dispose()

        asyncio.run(add_rate())
        resumed = _call(prefix)
        assert resumed.status_code == 200
        assert resumed.json()["netWorthStatus"] == "created"
        assert resumed.json()["createdAccountSnapshotCount"] == 1
        assert resumed.json()["replayedAccountSnapshotCount"] == 1
        assert asyncio.run(_counts(prefix)) == (2, 1)
    finally:
        asyncio.run(_cleanup(prefix))


def test_empty_user_creates_and_replays_zero_account_net_worth() -> None:
    prefix = "k5e1-empty"
    asyncio.run(_seed(prefix, ()))
    try:
        first = _call(prefix)
        second = _call(prefix)
        assert first.status_code == second.status_code == 200
        assert first.json()["netWorthStatus"] == "created"
        assert second.json()["netWorthStatus"] == "replayed"
        for field in (
            "refreshAccountCount",
            "reuseOnlyAccountCount",
            "createdAccountSnapshotCount",
            "replayedAccountSnapshotCount",
            "reusedAccountSnapshotCount",
            "selectedAccountSnapshotCount",
        ):
            assert first.json()[field] == second.json()[field] == 0
        assert asyncio.run(_counts(prefix)) == (0, 1)
    finally:
        asyncio.run(_cleanup(prefix))


@pytest.mark.parametrize(
    "account_type",
    [AccountType.bank, AccountType.cash, AccountType.savings],
)
def test_unsupported_active_account_fails_without_disclosure(
    account_type: AccountType,
) -> None:
    prefix = f"k5e1-unsupported-{account_type.value}"
    asyncio.run(_seed(prefix, (_AccountSpec("a", account_type=account_type),)))
    try:
        response = _call(prefix)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "snapshot_refresh_unavailable"
        assert account_type.value not in response.text
        assert asyncio.run(_counts(prefix)) == (0, 0)
    finally:
        asyncio.run(_cleanup(prefix))


def test_physical_conflict_is_generic_and_does_not_repair() -> None:
    prefix = "k5e1-conflict"
    asyncio.run(_seed(prefix, (_AccountSpec("a"),)))
    try:
        first = _call(prefix)
        assert first.status_code == 200

        async def corrupt() -> datetime:
            corrupted_at = BUCKET + timedelta(minutes=1)
            engine = _engine()
            try:
                async with AsyncSession(engine) as session:
                    snapshot_id = await session.scalar(
                        select(AccountSnapshotModel.id).where(
                            AccountSnapshotModel.account_id == _account_id(prefix, "a")
                        )
                    )
                    assert snapshot_id is not None
                    await session.execute(
                        update(AccountSnapshotModel)
                        .where(AccountSnapshotModel.id == snapshot_id)
                        .values(created_at=corrupted_at)
                    )
                    await session.commit()
                return corrupted_at
            finally:
                await engine.dispose()

        corrupted_at = asyncio.run(corrupt())
        response = _call(prefix)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "snapshot_refresh_conflict"
        assert first.json()["netWorthSnapshotId"] not in response.text

        async def persisted_created_at() -> datetime:
            engine = _engine()
            try:
                async with AsyncSession(engine) as session:
                    value = await session.scalar(
                        select(AccountSnapshotModel.created_at).where(
                            AccountSnapshotModel.account_id == _account_id(prefix, "a")
                        )
                    )
                    assert value is not None
                    return value
            finally:
                await engine.dispose()

        assert asyncio.run(persisted_created_at()) == corrupted_at
        assert asyncio.run(_counts(prefix)) == (1, 1)
    finally:
        asyncio.run(_cleanup(prefix))


def test_principal_isolation_uses_only_current_user() -> None:
    prefix_a = "k5e1-principal-a"
    prefix_b = "k5e1-principal-b"
    asyncio.run(_seed(prefix_a, (_AccountSpec("a"),)))
    asyncio.run(_seed(prefix_b, (_AccountSpec("b"),)))
    try:
        response = _call(prefix_a)
        assert response.status_code == 200
        assert _user_id(prefix_a) not in response.text
        assert _user_id(prefix_b) not in response.text
        assert asyncio.run(_counts(prefix_a)) == (1, 1)
        assert asyncio.run(_counts(prefix_b)) == (0, 0)
    finally:
        asyncio.run(_cleanup(prefix_a))
        asyncio.run(_cleanup(prefix_b))


def test_concurrent_requests_converge_without_duplicate_rows() -> None:
    prefix = "k5e1-concurrent"
    asyncio.run(_seed(prefix, (_AccountSpec("a"),)))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(_call, prefix)
            second_future = pool.submit(_call, prefix)
            first = first_future.result(timeout=30)
            second = second_future.result(timeout=30)
        assert first.status_code == second.status_code == 200
        assert {first.json()["netWorthStatus"], second.json()["netWorthStatus"]} == {
            "created",
            "replayed",
        }
        assert first.json()["netWorthSnapshotId"] == second.json()["netWorthSnapshotId"]
        account_dispositions = {
            (
                response.json()["createdAccountSnapshotCount"],
                response.json()["replayedAccountSnapshotCount"],
            )
            for response in (first, second)
        }
        assert account_dispositions == {(1, 0), (0, 1)}
        assert asyncio.run(_counts(prefix)) == (1, 1)
    finally:
        asyncio.run(_cleanup(prefix))
