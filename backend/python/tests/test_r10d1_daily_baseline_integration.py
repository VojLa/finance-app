from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.assets import AssetListingModel, AssetModel
from app.db.models.canonical_lineage import (
    AccountCanonicalChangeModel,
    AccountCanonicalStateModel,
    AccountSnapshotCanonicalBoundaryModel,
    DailySnapshotBaselineAccountModel,
    DailySnapshotBaselineModel,
    SnapshotGenerationModel,
    SnapshotGenerationTargetModel,
    UserReadModelPublicationModel,
    UserReadModelPublicationWatermarkModel,
)
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    AssetType,
    ExchangeRateSource,
    ImportSource,
    InvestmentEventType,
    InvestmentMovementKind,
    LiabilityBalanceSource,
    MovementDirection,
    PriceSource,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.holdings import HoldingModel
from app.db.models.investment_snapshots import PortfolioSnapshotModel
from app.db.models.ledger import InvestmentEventModel, InvestmentMovementModel
from app.db.models.liabilities import LiabilityBalanceModel
from app.db.models.prices import ExchangeRateModel
from app.db.models.snapshot_series_jobs import (
    SnapshotSeriesDirtyStateModel,
    SnapshotSeriesRebuildJobModel,
)
from app.db.models.snapshot_series_publication import (
    SnapshotSeriesHeadModel,
    SnapshotSeriesPointLinkModel,
    SnapshotSeriesPublicationReceiptModel,
    SnapshotSeriesVersionStateModel,
)
from app.db.models.snapshots import AccountSnapshotModel, NetWorthSnapshotModel
from app.db.models.users import UserModel
from app.db.url import normalize_database_url
from app.modules.canonical_state import CanonicalChangeKind, CanonicalStateService
from app.modules.daily_baselines import (
    DailyBaselineUnavailableError,
    DailySnapshotBaselineService,
)
from app.modules.holdings.rebuild_service import HoldingRebuildService
from app.modules.liabilities.writer import (
    LiabilityBalanceWriter,
    WriteLiabilityBalanceCommand,
)
from app.modules.snapshot_refresh.executor import (
    ExecuteUserSnapshotRefreshCommand,
    ExecuteUserSnapshotRefreshResult,
    UserSnapshotRefreshExecutor,
)

DATABASE_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL is required")
AT = datetime(2038, 8, 8)
INITIAL_AT = AT - timedelta(days=1)
CREATED_AT = datetime(2038, 8, 8, 1)


def _engine():
    assert DATABASE_URL is not None
    return create_async_engine(normalize_database_url(DATABASE_URL), pool_size=8)


async def _cleanup(prefix: str) -> None:
    engine = _engine()
    user_id = f"{prefix}-user"
    account_id = f"{prefix}-account"
    async with AsyncSession(engine) as session:
        generation_ids = tuple(
            await session.scalars(
                select(SnapshotGenerationTargetModel.generation_id).where(
                    SnapshotGenerationTargetModel.user_id == user_id
                )
            )
        )
        await session.execute(
            delete(UserReadModelPublicationModel).where(
                UserReadModelPublicationModel.user_id == user_id
            )
        )
        # PostgreSQL protects committed publication metadata from ordinary
        # mutation. This transaction-local override is limited to test-owned
        # immutable rows; all financial evidence is removed with FKs enabled.
        await session.execute(text("SET LOCAL session_replication_role = replica"))
        await session.execute(
            delete(SnapshotSeriesPublicationReceiptModel).where(
                SnapshotSeriesPublicationReceiptModel.user_id == user_id
            )
        )
        await session.execute(
            delete(SnapshotSeriesPointLinkModel).where(
                SnapshotSeriesPointLinkModel.user_id == user_id
            )
        )
        heads = tuple(
            await session.scalars(
                select(SnapshotSeriesHeadModel.id)
                .where(SnapshotSeriesHeadModel.user_id == user_id)
                .order_by(SnapshotSeriesHeadModel.version.desc())
            )
        )
        for head_id in heads:
            await session.execute(
                delete(SnapshotSeriesHeadModel).where(SnapshotSeriesHeadModel.id == head_id)
            )
        await session.execute(
            delete(SnapshotSeriesVersionStateModel).where(
                SnapshotSeriesVersionStateModel.user_id == user_id
            )
        )
        await session.execute(
            delete(UserReadModelPublicationWatermarkModel).where(
                UserReadModelPublicationWatermarkModel.user_id == user_id
            )
        )
        await session.execute(text("SET LOCAL session_replication_role = origin"))
        await session.execute(
            delete(SnapshotSeriesDirtyStateModel).where(
                SnapshotSeriesDirtyStateModel.user_id == user_id
            )
        )
        await session.execute(
            delete(PortfolioSnapshotModel).where(PortfolioSnapshotModel.user_id == user_id)
        )
        await session.execute(
            delete(DailySnapshotBaselineAccountModel).where(
                DailySnapshotBaselineAccountModel.account_id == account_id
            )
        )
        await session.execute(
            delete(DailySnapshotBaselineModel).where(DailySnapshotBaselineModel.user_id == user_id)
        )
        await session.execute(
            delete(ExchangeRateModel).where(ExchangeRateModel.id.startswith(f"{prefix}-"))
        )
        await session.execute(
            delete(NetWorthSnapshotModel).where(NetWorthSnapshotModel.user_id == user_id)
        )
        await session.execute(
            delete(AccountSnapshotModel).where(AccountSnapshotModel.account_id == account_id)
        )
        await session.execute(
            delete(LiabilityBalanceModel).where(LiabilityBalanceModel.account_id == account_id)
        )
        await session.execute(
            delete(SnapshotGenerationTargetModel).where(
                SnapshotGenerationTargetModel.user_id == user_id
            )
        )
        await session.execute(
            delete(SnapshotSeriesRebuildJobModel).where(
                SnapshotSeriesRebuildJobModel.user_id == user_id
            )
        )
        if generation_ids:
            await session.execute(
                delete(SnapshotGenerationModel).where(
                    SnapshotGenerationModel.id.in_(generation_ids)
                )
            )
        await session.execute(
            delete(AccountMemberModel).where(AccountMemberModel.account_id == account_id)
        )
        await session.execute(delete(AccountModel).where(AccountModel.id == account_id))
        await session.execute(delete(UserModel).where(UserModel.id == user_id))
        assert await session.get(UserModel, user_id) is None
        assert await session.get(AccountModel, account_id) is None
        assert not tuple(
            await session.scalars(
                select(SnapshotSeriesPointLinkModel.id).where(
                    SnapshotSeriesPointLinkModel.user_id == user_id
                )
            )
        )
        assert not tuple(
            await session.scalars(
                select(SnapshotGenerationTargetModel.generation_id).where(
                    SnapshotGenerationTargetModel.user_id == user_id
                )
            )
        )
        await session.commit()
    await engine.dispose()


async def _seed(
    prefix: str,
    *,
    base_currency: str = "EUR",
    account_currency: str = "EUR",
) -> tuple[str, str]:
    await _cleanup(prefix)
    engine = _engine()
    user_id = f"{prefix}-user"
    account_id = f"{prefix}-account"
    async with AsyncSession(engine) as session:
        session.add(
            UserModel(
                id=user_id,
                email=f"{prefix}@example.test",
                name="D1 baseline",
                password_hash=None,
                base_currency=base_currency,
                created_at=INITIAL_AT,
                updated_at=INITIAL_AT,
            )
        )
        session.add(
            AccountModel(
                id=account_id,
                name="Loan",
                type=AccountType.loan,
                currency=account_currency,
                color=None,
                is_archived=False,
                archived_at=None,
                created_at=INITIAL_AT,
                updated_at=INITIAL_AT,
                notes=None,
            )
        )
        await session.flush()
        session.add(
            AccountMemberModel(
                id=f"{prefix}-membership",
                account_id=account_id,
                user_id=user_id,
                role=AccountMemberRole.owner,
                relation_type=AccountRelationType.owner,
                invited_by_id=None,
                accepted_at=INITIAL_AT,
                created_at=INITIAL_AT,
                updated_at=INITIAL_AT,
            )
        )
        await session.commit()
    await engine.dispose()
    return user_id, account_id


async def _seed_direct_rate(prefix: str, *, from_currency: str, to_currency: str) -> str:
    engine = _engine()
    rate_id = f"{prefix}-{from_currency.lower()}-{to_currency.lower()}-rate"
    async with AsyncSession(engine) as session:
        session.add(
            ExchangeRateModel(
                id=rate_id,
                from_currency=from_currency,
                to_currency=to_currency,
                rate=Decimal("25.00000000"),
                date=INITIAL_AT,
                source=ExchangeRateSource.twelve_data,
                created_at=INITIAL_AT,
            )
        )
        await session.commit()
    await engine.dispose()
    return rate_id


async def _write_liability(
    account_id: str,
    *,
    effective_at: datetime,
    created_at: datetime,
    external_id: str,
    amount: str,
) -> str:
    engine = _engine()
    async with AsyncSession(engine) as session:
        result = await LiabilityBalanceWriter(session).write(
            WriteLiabilityBalanceCommand(
                account_id=account_id,
                effective_at=effective_at,
                currency="EUR",
                outstanding_principal=Decimal(amount),
                accrued_interest=Decimal("0"),
                fees_outstanding=Decimal("0"),
                source=LiabilityBalanceSource.statement,
                external_id=external_id,
                created_at=created_at,
            )
        )
    await engine.dispose()
    return result.balance_id


async def _refresh(user_id: str, *, at: datetime = AT) -> ExecuteUserSnapshotRefreshResult:
    engine = _engine()
    async with AsyncSession(engine) as session:
        # These tests exercise the direct baseline path after setup writes. The
        # rebuild worker, tested separately, owns real dirty-series publication.
        await session.execute(
            delete(SnapshotSeriesDirtyStateModel).where(
                SnapshotSeriesDirtyStateModel.user_id == user_id
            )
        )
        await session.execute(
            delete(SnapshotSeriesRebuildJobModel).where(
                SnapshotSeriesRebuildJobModel.user_id == user_id
            )
        )
        await session.commit()
        result = await UserSnapshotRefreshExecutor(session).execute(
            ExecuteUserSnapshotRefreshCommand(
                user_id=user_id,
                snapshot_timestamp=at,
                granularity=SnapshotGranularity.day,
                source=SnapshotSource.manual_recalculation,
                calculation_version=3,
                calculated_at=at,
                created_at=at,
                is_recalculated=True,
            )
        )
    await engine.dispose()
    return result


def test_daily_manifest_forward_change_and_backfill_invalidation() -> None:
    prefix = "r10d1-lineage"

    async def scenario() -> None:
        user_id, account_id = await _seed(prefix)
        balance_id = await _write_liability(
            account_id,
            effective_at=INITIAL_AT,
            created_at=INITIAL_AT,
            external_id="initial",
            amount="100",
        )
        refresh = await _refresh(user_id)

        engine = _engine()
        async with AsyncSession(engine) as session:
            version = await session.scalar(text("select current_setting('server_version')"))
            assert isinstance(version, str) and version.startswith("16.10")
            state = await session.get(AccountCanonicalStateModel, account_id)
            assert state is not None
            assert (state.last_revision, state.last_investment_revision) == (1, 0)
            changes = tuple(
                (
                    await session.scalars(
                        select(AccountCanonicalChangeModel)
                        .where(AccountCanonicalChangeModel.account_id == account_id)
                        .order_by(AccountCanonicalChangeModel.revision)
                    )
                ).all()
            )
            assert tuple((row.revision, row.kind, row.entity_id) for row in changes) == (
                (1, "liability_balance", balance_id),
            )
            baseline = await session.scalar(
                select(DailySnapshotBaselineModel).where(
                    DailySnapshotBaselineModel.user_id == user_id
                )
            )
            assert baseline is not None
            child = await session.scalar(
                select(DailySnapshotBaselineAccountModel).where(
                    DailySnapshotBaselineAccountModel.baseline_id == baseline.id
                )
            )
            assert child is not None
            assert child.primary_snapshot_id == child.presentation_snapshot_id
            assert child.canonical_revision == 1
            assert child.selected_liability_balance_id == balance_id
            boundary = await session.get(
                AccountSnapshotCanonicalBoundaryModel, child.primary_snapshot_id
            )
            assert boundary is not None
            assert boundary.selected_liability_balance_id == balance_id
            assert boundary.canonical_revision == 1
            assert refresh.net_worth_snapshot_id == baseline.net_worth_snapshot_id
        await engine.dispose()

        engine = _engine()
        async with AsyncSession(engine) as session:
            selected = await DailySnapshotBaselineService(session).select_latest_valid(
                user_id=user_id, through=AT
            )
            assert selected.baseline_id == baseline.id
            assert selected.post_baseline_changes == ()
        await engine.dispose()

        forward_id = await _write_liability(
            account_id,
            effective_at=AT + timedelta(hours=1),
            created_at=CREATED_AT,
            external_id="forward",
            amount="90",
        )
        engine = _engine()
        async with AsyncSession(engine) as session:
            selected = await DailySnapshotBaselineService(session).select_latest_valid(
                user_id=user_id, through=AT + timedelta(hours=2)
            )
            assert tuple(
                (change.revision, change.entity_id) for change in selected.post_baseline_changes
            ) == ((2, forward_id),)
        await engine.dispose()

        await _write_liability(
            account_id,
            effective_at=AT - timedelta(days=2),
            created_at=CREATED_AT + timedelta(hours=1),
            external_id="backfill",
            amount="110",
        )
        engine = _engine()
        async with AsyncSession(engine) as session:
            with pytest.raises(DailyBaselineUnavailableError):
                await DailySnapshotBaselineService(session).select_latest_valid(
                    user_id=user_id, through=AT + timedelta(hours=3)
                )
            assert not session.in_transaction()
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DailySnapshotBaselineModel)
                    .where(DailySnapshotBaselineModel.user_id == user_id)
                )
                == 1
            )
        await engine.dispose()

    asyncio.run(scenario())


def test_daily_manifest_replay_and_read_are_physically_immutable() -> None:
    prefix = "r10d1-replay"

    async def scenario() -> None:
        user_id, account_id = await _seed(prefix)
        await _write_liability(
            account_id,
            effective_at=INITIAL_AT,
            created_at=INITIAL_AT,
            external_id="initial",
            amount="100",
        )
        first = await _refresh(user_id)
        second = await _refresh(user_id)
        assert first.net_worth_snapshot_id == second.net_worth_snapshot_id

        engine = _engine()
        async with AsyncSession(engine) as session:
            before = (
                await session.scalar(
                    select(func.count())
                    .select_from(AccountSnapshotModel)
                    .where(AccountSnapshotModel.account_id == account_id)
                ),
                await session.scalar(
                    select(func.count())
                    .select_from(NetWorthSnapshotModel)
                    .where(NetWorthSnapshotModel.user_id == user_id)
                ),
                await session.scalar(
                    select(func.count())
                    .select_from(DailySnapshotBaselineModel)
                    .where(DailySnapshotBaselineModel.user_id == user_id)
                ),
                await session.scalar(
                    select(func.count())
                    .select_from(DailySnapshotBaselineAccountModel)
                    .where(DailySnapshotBaselineAccountModel.account_id == account_id)
                ),
            )
            await session.rollback()
            selected = await DailySnapshotBaselineService(session).select_latest_valid(
                user_id=user_id, through=AT
            )
            assert (
                selected.accounts[0].primary_snapshot_id == first.account_snapshots[0].snapshot_id
            )
            after = (
                await session.scalar(
                    select(func.count())
                    .select_from(AccountSnapshotModel)
                    .where(AccountSnapshotModel.account_id == account_id)
                ),
                await session.scalar(
                    select(func.count())
                    .select_from(NetWorthSnapshotModel)
                    .where(NetWorthSnapshotModel.user_id == user_id)
                ),
                await session.scalar(
                    select(func.count())
                    .select_from(DailySnapshotBaselineModel)
                    .where(DailySnapshotBaselineModel.user_id == user_id)
                ),
                await session.scalar(
                    select(func.count())
                    .select_from(DailySnapshotBaselineAccountModel)
                    .where(DailySnapshotBaselineAccountModel.account_id == account_id)
                ),
            )
            assert after == before
        await engine.dispose()

    asyncio.run(scenario())


def test_mixed_currency_primary_and_companion_share_one_canonical_boundary() -> None:
    prefix = "r10d1-mixed"

    async def scenario() -> None:
        user_id, account_id = await _seed(
            prefix,
            base_currency="CZK",
            account_currency="EUR",
        )
        await _write_liability(
            account_id,
            effective_at=INITIAL_AT,
            created_at=INITIAL_AT,
            external_id="initial",
            amount="100",
        )
        await _seed_direct_rate(prefix, from_currency="EUR", to_currency="CZK")
        refresh = await _refresh(user_id)

        engine = _engine()
        async with AsyncSession(engine) as session:
            root = await session.scalar(
                select(DailySnapshotBaselineModel).where(
                    DailySnapshotBaselineModel.user_id == user_id
                )
            )
            assert root is not None
            child = await session.get(
                DailySnapshotBaselineAccountModel,
                (root.id, account_id),
            )
            assert child is not None
            primary = await session.get(AccountSnapshotModel, child.primary_snapshot_id)
            presentation = await session.get(AccountSnapshotModel, child.presentation_snapshot_id)
            primary_boundary = await session.get(
                AccountSnapshotCanonicalBoundaryModel,
                child.primary_snapshot_id,
            )
            presentation_boundary = await session.get(
                AccountSnapshotCanonicalBoundaryModel,
                child.presentation_snapshot_id,
            )
            net_worth = await session.get(NetWorthSnapshotModel, root.net_worth_snapshot_id)
            assert primary is not None and presentation is not None and net_worth is not None
            assert primary_boundary is not None and presentation_boundary is not None
            assert (primary.currency, presentation.currency) == ("CZK", "EUR")
            assert primary.id != presentation.id
            assert (
                child.primary_snapshot_id
                == refresh.required_account_snapshot_identities[0].snapshot_id
            )
            assert child.canonical_revision == 1
            assert primary_boundary.canonical_revision == 1
            assert presentation_boundary.canonical_revision == 1
            assert (
                primary_boundary.selected_liability_balance_id
                == presentation_boundary.selected_liability_balance_id
                == child.selected_liability_balance_id
            )
            assert net_worth.currency == "CZK"
            assert net_worth.total_net_worth == primary.total_value
            assert net_worth.total_net_worth != presentation.total_value
        await engine.dispose()

    asyncio.run(scenario())


def test_concurrent_identical_daily_refresh_converges_to_one_manifest() -> None:
    prefix = "r10d1-concurrent-baseline"

    async def scenario() -> None:
        user_id, account_id = await _seed(prefix)
        await _write_liability(
            account_id,
            effective_at=INITIAL_AT,
            created_at=INITIAL_AT,
            external_id="initial",
            amount="100",
        )

        first, second = await asyncio.gather(_refresh(user_id), _refresh(user_id))
        assert first.net_worth_snapshot_id == second.net_worth_snapshot_id

        engine = _engine()
        async with AsyncSession(engine) as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DailySnapshotBaselineModel)
                    .where(DailySnapshotBaselineModel.user_id == user_id)
                )
                == 1
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(DailySnapshotBaselineAccountModel)
                    .join(
                        DailySnapshotBaselineModel,
                        DailySnapshotBaselineAccountModel.baseline_id
                        == DailySnapshotBaselineModel.id,
                    )
                    .where(DailySnapshotBaselineModel.user_id == user_id)
                )
                == 1
            )
        await engine.dispose()

    asyncio.run(scenario())


def test_concurrent_canonical_writes_serialize_committed_revisions() -> None:
    prefix = "r10d1-concurrent-change"

    async def scenario() -> None:
        _, account_id = await _seed(prefix)
        await asyncio.gather(
            _write_liability(
                account_id,
                effective_at=INITIAL_AT,
                created_at=INITIAL_AT,
                external_id="first",
                amount="100",
            ),
            _write_liability(
                account_id,
                effective_at=INITIAL_AT + timedelta(hours=1),
                created_at=INITIAL_AT + timedelta(milliseconds=1),
                external_id="second",
                amount="101",
            ),
        )

        engine = _engine()
        async with AsyncSession(engine) as session:
            state = await session.get(AccountCanonicalStateModel, account_id)
            changes = tuple(
                (
                    await session.scalars(
                        select(AccountCanonicalChangeModel)
                        .where(AccountCanonicalChangeModel.account_id == account_id)
                        .order_by(AccountCanonicalChangeModel.revision)
                    )
                ).all()
            )
            assert state is not None
            assert (state.last_revision, state.last_investment_revision) == (2, 0)
            assert tuple(change.revision for change in changes) == (1, 2)
            assert {change.entity_id for change in changes} == {
                row.id
                for row in (
                    await session.scalars(
                        select(LiabilityBalanceModel).where(
                            LiabilityBalanceModel.account_id == account_id
                        )
                    )
                ).all()
            }
        await engine.dispose()

    asyncio.run(scenario())


def test_investment_revision_makes_holding_stale_until_atomic_rebuild() -> None:
    prefix = "r10d1-holding"
    account_id = f"{prefix}-account"
    asset_id = f"{prefix}-asset"
    listing_id = f"{prefix}-listing"

    async def add_event(event_id: str, at: datetime) -> None:
        engine = _engine()
        async with AsyncSession(engine) as session:
            async with session.begin():
                session.add(
                    InvestmentEventModel(
                        id=event_id,
                        account_id=account_id,
                        type=InvestmentEventType.trade,
                        date=at,
                        source=ImportSource.trading212,
                        external_id=event_id,
                        order_id=None,
                        description="ETF",
                        realized_pnl=None,
                        realized_pnl_currency=None,
                        import_batch_id=None,
                        archived_at=None,
                        deleted_at=None,
                        created_at=at,
                        updated_at=at,
                    )
                )
                session.add_all(
                    [
                        InvestmentMovementModel(
                            id=f"{event_id}-asset",
                            event_id=event_id,
                            account_id=account_id,
                            asset_id=asset_id,
                            listing_id=listing_id,
                            kind=InvestmentMovementKind.asset,
                            direction=MovementDirection.incoming,
                            quantity=Decimal("1"),
                            currency="ETF",
                            price_per_unit=Decimal("10"),
                            value_amount=Decimal("10"),
                            value_currency="EUR",
                            source_symbol="ETF",
                            source_asset_type=AssetType.etf,
                            note=None,
                            created_at=at,
                            updated_at=at,
                        ),
                        InvestmentMovementModel(
                            id=f"{event_id}-cash",
                            event_id=event_id,
                            account_id=account_id,
                            asset_id=None,
                            listing_id=None,
                            kind=InvestmentMovementKind.cash,
                            direction=MovementDirection.outgoing,
                            quantity=Decimal("10"),
                            currency="EUR",
                            price_per_unit=None,
                            value_amount=Decimal("10"),
                            value_currency="EUR",
                            source_symbol=None,
                            source_asset_type=None,
                            note=None,
                            created_at=at,
                            updated_at=at,
                        ),
                    ]
                )
                await CanonicalStateService(session).record(
                    account_id=account_id,
                    kind=CanonicalChangeKind.investment_event,
                    entity_id=event_id,
                    financial_timestamp=at,
                    created_at=at,
                    replay=False,
                )
        await engine.dispose()

    async def rebuild(at: datetime) -> None:
        engine = _engine()
        async with AsyncSession(engine) as session:
            async with session.begin():
                await HoldingRebuildService(session).rebuild(
                    account_id=account_id,
                    rebuilt_at=at,
                )
        await engine.dispose()

    async def scenario() -> None:
        engine = _engine()
        async with AsyncSession(engine) as session:
            await session.execute(delete(HoldingModel).where(HoldingModel.account_id == account_id))
            await session.execute(
                delete(InvestmentMovementModel).where(
                    InvestmentMovementModel.account_id == account_id
                )
            )
            await session.execute(
                delete(InvestmentEventModel).where(InvestmentEventModel.account_id == account_id)
            )
            await session.execute(delete(AccountModel).where(AccountModel.id == account_id))
            await session.execute(
                delete(AssetListingModel).where(AssetListingModel.id == listing_id)
            )
            await session.execute(delete(AssetModel).where(AssetModel.id == asset_id))
            session.add(
                AccountModel(
                    id=account_id,
                    name="Broker",
                    type=AccountType.broker,
                    currency="EUR",
                    color=None,
                    is_archived=False,
                    archived_at=None,
                    created_at=INITIAL_AT,
                    updated_at=INITIAL_AT,
                    notes=None,
                )
            )
            session.add(
                AssetModel(
                    id=asset_id,
                    symbol="ETF",
                    isin=None,
                    name="ETF",
                    asset_type=AssetType.etf,
                    currency="EUR",
                    created_at=INITIAL_AT,
                    updated_at=INITIAL_AT,
                )
            )
            await session.flush()
            session.add(
                AssetListingModel(
                    id=listing_id,
                    asset_id=asset_id,
                    symbol="ETF",
                    exchange="audit",
                    mic=None,
                    currency="EUR",
                    country=None,
                    provider=PriceSource.broker,
                    provider_symbol="ETF",
                    is_primary=False,
                    created_at=INITIAL_AT,
                    updated_at=INITIAL_AT,
                )
            )
            await session.commit()
        await engine.dispose()

        await add_event(f"{prefix}-event-1", INITIAL_AT)
        engine = _engine()
        async with AsyncSession(engine) as session:
            state = await session.get(AccountCanonicalStateModel, account_id)
            assert state is not None
            assert (state.last_revision, state.last_investment_revision) == (1, 1)
            assert state.holding_revision == 0
        await engine.dispose()

        await rebuild(CREATED_AT)
        engine = _engine()
        async with AsyncSession(engine) as session:
            state = await session.get(AccountCanonicalStateModel, account_id)
            assert state is not None and state.holding_revision == 1
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(HoldingModel)
                    .where(HoldingModel.account_id == account_id)
                )
                == 1
            )
        await engine.dispose()

        await add_event(f"{prefix}-event-2", CREATED_AT + timedelta(hours=1))
        engine = _engine()
        async with AsyncSession(engine) as session:
            state = await session.get(AccountCanonicalStateModel, account_id)
            assert state is not None
            assert (state.last_investment_revision, state.holding_revision) == (2, 1)
        await engine.dispose()

        await rebuild(CREATED_AT + timedelta(hours=2))
        engine = _engine()
        async with AsyncSession(engine) as session:
            state = await session.get(AccountCanonicalStateModel, account_id)
            assert state is not None
            assert state.holding_revision == state.last_investment_revision == 2
            holding = await session.scalar(
                select(HoldingModel).where(HoldingModel.account_id == account_id)
            )
            assert holding is not None and holding.quantity == Decimal("2.0000000000")
        await engine.dispose()

    asyncio.run(scenario())


def test_newest_invalid_baseline_never_falls_back_to_older_manifest() -> None:
    prefix = "r10d1-no-fallback"

    async def scenario() -> None:
        user_id, account_id = await _seed(prefix)
        await _write_liability(
            account_id,
            effective_at=INITIAL_AT,
            created_at=INITIAL_AT,
            external_id="initial",
            amount="100",
        )
        await _refresh(user_id, at=AT)
        newest_at = AT + timedelta(days=1)
        await _refresh(user_id, at=newest_at)

        engine = _engine()
        async with AsyncSession(engine) as session:
            roots = tuple(
                (
                    await session.scalars(
                        select(DailySnapshotBaselineModel)
                        .where(DailySnapshotBaselineModel.user_id == user_id)
                        .order_by(DailySnapshotBaselineModel.timestamp)
                    )
                ).all()
            )
            assert tuple(root.timestamp for root in roots) == (AT, newest_at)
            newest_child = await session.scalar(
                select(DailySnapshotBaselineAccountModel).where(
                    DailySnapshotBaselineAccountModel.baseline_id == roots[-1].id
                )
            )
            assert newest_child is not None
            newest_child.account_currency = "USD"
            await session.commit()

        async with AsyncSession(engine) as session:
            with pytest.raises(DailyBaselineUnavailableError):
                await DailySnapshotBaselineService(
                    session
                ).select_published_manifest_for_authorized_read(
                    user_id=user_id,
                )
            assert not session.in_transaction()
        await engine.dispose()

    asyncio.run(scenario())


def test_account_configuration_change_invalidates_exact_baseline() -> None:
    prefix = "r10d1-config"

    async def scenario() -> None:
        user_id, account_id = await _seed(prefix)
        await _write_liability(
            account_id,
            effective_at=INITIAL_AT,
            created_at=INITIAL_AT,
            external_id="initial",
            amount="100",
        )
        await _refresh(user_id)

        engine = _engine()
        async with AsyncSession(engine) as session:
            account = await session.get(AccountModel, account_id)
            assert account is not None
            account.currency = "USD"
            await session.commit()
        async with AsyncSession(engine) as session:
            with pytest.raises(DailyBaselineUnavailableError):
                await DailySnapshotBaselineService(session).select_latest_valid(
                    user_id=user_id,
                    through=AT,
                )
        async with AsyncSession(engine) as session:
            account = await session.get(AccountModel, account_id)
            assert account is not None
            account.currency = "EUR"
            account.is_archived = True
            account.archived_at = CREATED_AT
            await session.commit()
        async with AsyncSession(engine) as session:
            with pytest.raises(DailyBaselineUnavailableError):
                await DailySnapshotBaselineService(session).select_latest_valid(
                    user_id=user_id,
                    through=AT,
                )
        await engine.dispose()

    asyncio.run(scenario())


def test_user_base_currency_change_invalidates_exact_baseline_without_relabeling() -> None:
    prefix = "r10d1-user-currency"

    async def scenario() -> None:
        user_id, account_id = await _seed(prefix)
        await _write_liability(
            account_id,
            effective_at=INITIAL_AT,
            created_at=INITIAL_AT,
            external_id="initial",
            amount="100",
        )
        await _refresh(user_id)

        engine = _engine()
        async with AsyncSession(engine) as session:
            user = await session.get(UserModel, user_id)
            assert user is not None
            user.base_currency = "USD"
            await session.commit()
        async with AsyncSession(engine) as session:
            with pytest.raises(DailyBaselineUnavailableError):
                await DailySnapshotBaselineService(session).select_latest_valid(
                    user_id=user_id,
                    through=AT,
                )
            assert not session.in_transaction()
        await engine.dispose()

    asyncio.run(scenario())
