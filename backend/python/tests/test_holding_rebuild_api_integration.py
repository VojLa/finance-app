from __future__ import annotations

import asyncio
import os
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from app.auth.dependencies import get_current_principal
from app.auth.models import AuthenticatedPrincipal
from app.config.settings import Settings
from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetType,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    MovementDirection,
    PriceSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.main import create_app
from app.modules.accounts.access import (
    AccountAccessDeniedError,
    AccountNotFoundError,
)
from app.modules.holdings.orchestration import (
    HoldingRebuildApplicationService,
    HoldingRebuildUnavailableError,
    RebuildHoldingsCommand,
)
from app.modules.holdings.rebuild_service import HoldingRebuildService
from app.modules.holdings.repository import HoldingRebuildRepository

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
NOW = datetime(2026, 7, 27, 15, 0, 0, 123000)
LATER = datetime(2026, 7, 27, 16, 0, 0, 456000)


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=8)


def _principal(user_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.com",
        name=user_id,
    )


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    pattern = f"{prefix}%"
    async with AsyncSession(engine) as session:
        account_ids = list(
            (
                await session.scalars(select(AccountModel.id).where(AccountModel.id.like(pattern)))
            ).all()
        )
        user_ids = list(
            (await session.scalars(select(UserModel.id).where(UserModel.id.like(pattern)))).all()
        )
        if account_ids:
            await session.execute(
                delete(HoldingModel).where(HoldingModel.account_id.in_(account_ids))
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
                delete(AccountMemberModel).where(AccountMemberModel.account_id.in_(account_ids))
            )
        await session.execute(delete(AssetListingModel).where(AssetListingModel.id.like(pattern)))
        await session.execute(delete(AssetModel).where(AssetModel.id.like(pattern)))
        if account_ids:
            await session.execute(delete(AccountModel).where(AccountModel.id.in_(account_ids)))
        if user_ids:
            await session.execute(delete(UserModel).where(UserModel.id.in_(user_ids)))
        await session.commit()
    await engine.dispose()


async def _seed(
    prefix: str,
    *,
    roles: tuple[AccountMemberRole, ...] = (AccountMemberRole.owner,),
    archived: bool = False,
    history: str = "buy",
) -> tuple[str, tuple[str, ...]]:
    await _cleanup(prefix)
    account_id = f"{prefix}-account"
    user_ids = tuple(f"{prefix}-user-{index}" for index in range(len(roles)))
    asset_id = f"{prefix}-asset"
    listing_id = f"{prefix}-listing"
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add_all(
            [
                UserModel(
                    id=user_id,
                    email=f"{user_id}@example.com",
                    name=user_id,
                    password_hash=None,
                    base_currency="EUR",
                    created_at=NOW,
                    updated_at=NOW,
                )
                for user_id in user_ids
            ]
        )
        session.add(
            AccountModel(
                id=account_id,
                name=account_id,
                type=AccountType.broker,
                currency="EUR",
                color=None,
                is_archived=archived,
                archived_at=NOW if archived else None,
                created_at=NOW,
                updated_at=NOW,
                notes=None,
            )
        )
        await session.flush()
        session.add_all(
            [
                AccountMemberModel(
                    id=f"{prefix}-member-{index}",
                    account_id=account_id,
                    user_id=user_id,
                    role=role,
                    relation_type=(
                        AccountRelationType.owner
                        if role is AccountMemberRole.owner
                        else AccountRelationType.collaborator
                    ),
                    invited_by_id=None,
                    accepted_at=NOW,
                    created_at=NOW,
                    updated_at=NOW,
                )
                for index, (user_id, role) in enumerate(zip(user_ids, roles, strict=True))
            ]
        )
        session.add(
            AssetModel(
                id=asset_id,
                symbol="VWCE",
                isin=f"{prefix}-isin",
                name="VWCE",
                asset_type=AssetType.etf,
                currency="EUR",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.flush()
        session.add(
            AssetListingModel(
                id=listing_id,
                asset_id=asset_id,
                symbol="VWCE",
                exchange=f"{prefix}-exchange",
                mic=None,
                currency="EUR",
                country=None,
                provider=PriceSource.broker,
                provider_symbol=f"{prefix}-symbol",
                is_primary=False,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        if history != "none":
            event_id = f"{prefix}-event"
            session.add(
                InvestmentEventModel(
                    id=event_id,
                    account_id=account_id,
                    type=(
                        InvestmentEventType.trade
                        if history == "buy"
                        else InvestmentEventType.asset_transfer
                    ),
                    date=NOW,
                    source=(ImportSource.trading212 if history == "buy" else ImportSource.anycoin),
                    external_id=event_id,
                    order_id=None,
                    description=None,
                    realized_pnl=None,
                    realized_pnl_currency=None,
                    import_batch_id=None,
                    archived_at=None,
                    deleted_at=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.add(
                InvestmentMovementModel(
                    id=f"{event_id}-asset",
                    event_id=event_id,
                    account_id=account_id,
                    asset_id=asset_id,
                    listing_id=listing_id,
                    kind=InvestmentMovementKind.asset,
                    direction=MovementDirection.incoming,
                    quantity=Decimal("2"),
                    currency="VWCE",
                    price_per_unit=Decimal("100") if history == "buy" else None,
                    value_amount=Decimal("200") if history == "buy" else None,
                    value_currency="EUR" if history == "buy" else None,
                    source_symbol="VWCE",
                    source_asset_type=AssetType.etf,
                    note=None,
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            if history == "buy":
                session.add(
                    InvestmentMovementModel(
                        id=f"{event_id}-cash",
                        event_id=event_id,
                        account_id=account_id,
                        asset_id=None,
                        listing_id=None,
                        kind=InvestmentMovementKind.cash,
                        direction=MovementDirection.outgoing,
                        quantity=Decimal("200"),
                        currency="EUR",
                        price_per_unit=None,
                        value_amount=Decimal("200"),
                        value_currency="EUR",
                        source_symbol=None,
                        source_asset_type=None,
                        note=None,
                        created_at=NOW,
                        updated_at=NOW,
                    )
                )
        await session.commit()
    await engine.dispose()
    return account_id, user_ids


async def _add_user_without_membership(prefix: str) -> str:
    user_id = f"{prefix}-non-member"
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            UserModel(
                id=user_id,
                email=f"{user_id}@example.com",
                name=user_id,
                password_hash=None,
                base_currency="EUR",
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.commit()
    await engine.dispose()
    return user_id


async def _rebuild(
    *,
    account_id: str,
    user_id: str,
    timestamp: datetime = NOW,
):
    engine = _engine()
    try:
        async with AsyncSession(engine) as session:
            return await HoldingRebuildApplicationService(
                session,
                clock=lambda: timestamp,
            ).rebuild(
                RebuildHoldingsCommand(
                    principal=_principal(user_id),
                    account_id=account_id,
                )
            )
    finally:
        await engine.dispose()


async def _snapshot(account_id: str) -> tuple[Any, ...]:
    engine = _engine()
    async with AsyncSession(engine) as session:
        holdings = list(
            (
                await session.scalars(
                    select(HoldingModel)
                    .where(HoldingModel.account_id == account_id)
                    .order_by(HoldingModel.id)
                )
            ).all()
        )
        result = tuple(
            (
                row.id,
                row.asset_id,
                row.listing_id,
                row.quantity,
                row.avg_buy_price,
                row.currency,
                row.calculated_at,
                row.updated_at,
            )
            for row in holdings
        )
    await engine.dispose()
    return result


async def _holding_count(account_id: str) -> int:
    engine = _engine()
    async with AsyncSession(engine) as session:
        count = int(
            await session.scalar(
                select(func.count())
                .select_from(HoldingModel)
                .where(HoldingModel.account_id == account_id)
            )
            or 0
        )
    await engine.dispose()
    return count


async def _blocked(engine: AsyncEngine, pid: int) -> bool:
    async with AsyncSession(engine) as inspector:
        for _ in range(100):
            state = (
                await inspector.execute(
                    text(
                        "SELECT cardinality(pg_blocking_pids(:pid)), wait_event_type "
                        "FROM pg_stat_activity WHERE pid = :pid"
                    ),
                    {"pid": pid},
                )
            ).one()
            if int(state[0] or 0) and state[1] == "Lock":
                return True
            await asyncio.sleep(0.02)
    return False


@pytest.mark.parametrize(
    "role",
    [AccountMemberRole.owner, AccountMemberRole.admin, AccountMemberRole.editor],
)
async def test_persisted_write_roles_can_rebuild_and_exactly_replay(
    role: AccountMemberRole,
) -> None:
    prefix = f"h5d-role-{role.value}"
    account_id, (user_id,) = await _seed(prefix, roles=(role,))

    first = await _rebuild(account_id=account_id, user_id=user_id)
    initial = await _snapshot(account_id)
    second = await _rebuild(account_id=account_id, user_id=user_id, timestamp=LATER)

    assert (first.created, first.updated, first.deleted, first.total, first.replayed) == (
        1,
        0,
        0,
        1,
        False,
    )
    assert second.model_dump() == {
        "account_id": account_id,
        "created": 0,
        "updated": 0,
        "deleted": 0,
        "total": 1,
        "replayed": True,
        "rebuilt_at": None,
    }
    assert await _snapshot(account_id) == initial
    await _cleanup(prefix)


@pytest.mark.parametrize(
    ("access", "expected_error"),
    [
        ("viewer", AccountAccessDeniedError),
        ("non_member", AccountNotFoundError),
        ("archived", AccountNotFoundError),
    ],
)
async def test_rejected_access_never_mutates_holdings(
    access: str,
    expected_error: type[Exception],
) -> None:
    prefix = f"h5d-reject-{access}"
    role = AccountMemberRole.viewer if access == "viewer" else AccountMemberRole.owner
    account_id, (member_id,) = await _seed(
        prefix,
        roles=(role,),
        archived=access == "archived",
    )
    user_id = await _add_user_without_membership(prefix) if access == "non_member" else member_id

    with pytest.raises(expected_error):
        await _rebuild(account_id=account_id, user_id=user_id)

    assert await _snapshot(account_id) == ()
    await _cleanup(prefix)


def test_real_endpoint_serializes_response_and_conceals_path_substitution() -> None:
    prefix = "h5d-http"

    async def seed() -> tuple[str, str, str]:
        account_id, (owner_id,) = await _seed(prefix)
        foreign_id = await _add_user_without_membership(prefix)
        return account_id, owner_id, foreign_id

    account_id, owner_id, foreign_id = asyncio.run(seed())

    def call(user_id: str):
        settings = Settings(
            environment="test",
            database_url=DATABASE_URL,
            docs_enabled=True,
            internal_auth_secret="test-secret-that-is-long-enough-for-auth",
            _env_file=None,
        )
        app = create_app(settings)
        app.dependency_overrides[get_current_principal] = lambda: _principal(user_id)
        with TestClient(app) as client:
            return client.post(f"/api/v1/accounts/{account_id}/holdings/rebuild")

    rejected = call(foreign_id)
    assert (rejected.status_code, rejected.json()["error"]["code"]) == (
        404,
        "account_not_found",
    )
    assert asyncio.run(_holding_count(account_id)) == 0

    accepted = call(owner_id)
    assert accepted.status_code == 200
    assert accepted.json()["account_id"] == account_id
    assert accepted.json()["created"] == 1
    assert set(accepted.json()) == {
        "account_id",
        "created",
        "updated",
        "deleted",
        "total",
        "replayed",
        "rebuilt_at",
    }
    asyncio.run(_cleanup(prefix))


async def test_unsupported_history_maps_to_conflict_and_preserves_holdings() -> None:
    prefix = "h5d-unsupported"
    account_id, (user_id,) = await _seed(prefix, history="transfer")

    with pytest.raises(HoldingRebuildUnavailableError):
        await _rebuild(account_id=account_id, user_id=user_id)

    assert await _snapshot(account_id) == ()
    await _cleanup(prefix)


async def test_controlled_flush_failure_rolls_back_and_clean_retry_succeeds() -> None:
    prefix = "h5d-rollback"
    account_id, (user_id,) = await _seed(prefix)
    original = HoldingRebuildRepository.flush

    async def fail_after_flush(self: HoldingRebuildRepository) -> None:
        await original(self)
        raise RuntimeError("controlled flush failure")

    with patch.object(HoldingRebuildRepository, "flush", fail_after_flush):
        with pytest.raises(RuntimeError, match="controlled flush failure"):
            await _rebuild(account_id=account_id, user_id=user_id)

    assert await _snapshot(account_id) == ()
    retry = await _rebuild(account_id=account_id, user_id=user_id, timestamp=LATER)
    assert (retry.created, retry.total, retry.replayed) == (1, 1, False)
    assert await _holding_count(account_id) == 1
    await _cleanup(prefix)


async def test_same_account_requests_serialize_then_replay() -> None:
    prefix = "h5d-concurrent"
    account_id, (owner_id, editor_id) = await _seed(
        prefix,
        roles=(AccountMemberRole.owner, AccountMemberRole.editor),
    )
    engine = _engine()
    first_ready = asyncio.Event()
    release_first = asyncio.Event()
    original = HoldingRebuildService.rebuild
    calls = 0

    async def held(self: HoldingRebuildService, *, account_id: str, rebuilt_at: datetime):
        nonlocal calls
        result = await original(self, account_id=account_id, rebuilt_at=rebuilt_at)
        calls += 1
        if calls == 1:
            first_ready.set()
            await release_first.wait()
        return result

    async def run(session: AsyncSession, user_id: str):
        return await HoldingRebuildApplicationService(session, clock=lambda: NOW).rebuild(
            RebuildHoldingsCommand(principal=_principal(user_id), account_id=account_id)
        )

    async with AsyncSession(engine) as first_session, AsyncSession(engine) as second_session:
        second_pid = int(await second_session.scalar(text("SELECT pg_backend_pid()")))
        with patch.object(HoldingRebuildService, "rebuild", held):
            first_task = asyncio.create_task(run(first_session, owner_id))
            await asyncio.wait_for(first_ready.wait(), timeout=10)
            second_task = asyncio.create_task(run(second_session, editor_id))
            assert await _blocked(engine, second_pid)
            release_first.set()
            first, second = await asyncio.wait_for(
                asyncio.gather(first_task, second_task),
                timeout=15,
            )
    await engine.dispose()
    assert first.replayed is False
    assert second.replayed is True
    assert await _holding_count(account_id) == 1
    await _cleanup(prefix)


async def test_membership_downgrade_commits_first_and_rebuild_revalidates() -> None:
    prefix = "h5d-downgrade-first"
    account_id, (editor_id,) = await _seed(
        prefix,
        roles=(AccountMemberRole.editor,),
    )
    engine = _engine()
    async with (
        AsyncSession(engine) as downgrade_session,
        AsyncSession(engine) as rebuild_session,
    ):
        membership = await downgrade_session.scalar(
            select(AccountMemberModel)
            .where(AccountMemberModel.id == f"{prefix}-member-0")
            .with_for_update()
        )
        assert membership is not None
        membership.role = AccountMemberRole.viewer
        await downgrade_session.flush()
        rebuild_pid = int(await rebuild_session.scalar(text("SELECT pg_backend_pid()")))
        task = asyncio.create_task(
            HoldingRebuildApplicationService(rebuild_session, clock=lambda: NOW).rebuild(
                RebuildHoldingsCommand(
                    principal=_principal(editor_id),
                    account_id=account_id,
                )
            )
        )
        assert await _blocked(engine, rebuild_pid)
        await downgrade_session.commit()
        result = await asyncio.wait_for(
            asyncio.gather(task, return_exceptions=True),
            timeout=10,
        )
    await engine.dispose()
    assert isinstance(result[0], AccountAccessDeniedError)
    assert await _snapshot(account_id) == ()
    await _cleanup(prefix)


async def test_rebuild_membership_lock_makes_concurrent_downgrade_wait() -> None:
    prefix = "h5d-rebuild-first"
    account_id, (editor_id,) = await _seed(
        prefix,
        roles=(AccountMemberRole.editor,),
    )
    engine = _engine()
    rebuild_ready = asyncio.Event()
    release_rebuild = asyncio.Event()
    original = HoldingRebuildService.rebuild

    async def held(self: HoldingRebuildService, *, account_id: str, rebuilt_at: datetime):
        result = await original(self, account_id=account_id, rebuilt_at=rebuilt_at)
        rebuild_ready.set()
        await release_rebuild.wait()
        return result

    async with (
        AsyncSession(engine) as rebuild_session,
        AsyncSession(engine) as downgrade_session,
    ):
        with patch.object(HoldingRebuildService, "rebuild", held):
            rebuild_task = asyncio.create_task(
                HoldingRebuildApplicationService(rebuild_session, clock=lambda: NOW).rebuild(
                    RebuildHoldingsCommand(
                        principal=_principal(editor_id),
                        account_id=account_id,
                    )
                )
            )
            await asyncio.wait_for(rebuild_ready.wait(), timeout=10)
            downgrade_pid = int(await downgrade_session.scalar(text("SELECT pg_backend_pid()")))

            async def downgrade() -> None:
                membership = await downgrade_session.scalar(
                    select(AccountMemberModel)
                    .where(AccountMemberModel.id == f"{prefix}-member-0")
                    .with_for_update()
                )
                assert membership is not None
                membership.role = AccountMemberRole.viewer
                await downgrade_session.commit()

            downgrade_task = asyncio.create_task(downgrade())
            assert await _blocked(engine, downgrade_pid)
            release_rebuild.set()
            rebuild_result, _ = await asyncio.wait_for(
                asyncio.gather(rebuild_task, downgrade_task),
                timeout=15,
            )
    await engine.dispose()
    assert rebuild_result.created == 1
    assert await _holding_count(account_id) == 1
    with pytest.raises(AccountAccessDeniedError):
        await _rebuild(account_id=account_id, user_id=editor_id, timestamp=LATER)
    await _cleanup(prefix)


async def test_different_accounts_do_not_share_rebuild_or_membership_lock() -> None:
    first_prefix = "h5d-independent-a"
    second_prefix = "h5d-independent-b"
    first_account, (first_user,) = await _seed(first_prefix)
    second_account, _ = await _seed(second_prefix)
    engine = _engine()
    async with AsyncSession(engine) as session:
        session.add(
            AccountMemberModel(
                id=f"{second_prefix}-cross-member",
                account_id=second_account,
                user_id=first_user,
                role=AccountMemberRole.owner,
                relation_type=AccountRelationType.owner,
                invited_by_id=None,
                accepted_at=NOW,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        await session.commit()

    first_ready = asyncio.Event()
    release_first = asyncio.Event()
    original = HoldingRebuildService.rebuild

    async def held(self: HoldingRebuildService, *, account_id: str, rebuilt_at: datetime):
        result = await original(self, account_id=account_id, rebuilt_at=rebuilt_at)
        if account_id == first_account:
            first_ready.set()
            await release_first.wait()
        return result

    async def run(session: AsyncSession, account_id: str):
        return await HoldingRebuildApplicationService(session, clock=lambda: NOW).rebuild(
            RebuildHoldingsCommand(
                principal=_principal(first_user),
                account_id=account_id,
            )
        )

    async with AsyncSession(engine) as first_session, AsyncSession(engine) as second_session:
        with patch.object(HoldingRebuildService, "rebuild", held):
            first_task = asyncio.create_task(run(first_session, first_account))
            await asyncio.wait_for(first_ready.wait(), timeout=10)
            second = await asyncio.wait_for(run(second_session, second_account), timeout=5)
            release_first.set()
            first = await asyncio.wait_for(first_task, timeout=10)
    await engine.dispose()
    assert first.created == second.created == 1
    await _cleanup(second_prefix)
    await _cleanup(first_prefix)
