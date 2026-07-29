"""Focused tests for persisted snapshot-refresh coverage selection."""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.exc import OperationalError

from app.db.models.accounts import AccountMemberModel, AccountModel
from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    SnapshotGranularity,
    SnapshotSource,
)
from app.db.models.snapshots import AccountSnapshotModel
from app.db.models.users import UserModel
from app.modules.snapshot_refresh import (
    AccountSnapshotRefreshMode,
    BuildSnapshotRefreshCoverageCommand,
    CompleteSnapshotRefreshCoverage,
    SnapshotRefreshEvidenceService,
    SnapshotRefreshEvidenceStateError,
    SnapshotRefreshPlanStateError,
    build_user_snapshot_refresh_plan,
)
from app.modules.snapshot_refresh.repository import (
    PersistedSnapshotRefreshAccess,
    SnapshotRefreshEvidenceRepository,
)

NOW = datetime(2026, 7, 27)
ERROR = "Persisted evidence cannot produce complete snapshot refresh coverage."


class FakeSession:
    def __init__(self, *, active: bool = True) -> None:
        self.active = active
        self.begin = Mock()
        self.begin_nested = Mock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.flush = AsyncMock()
        self.add = Mock()

    def in_transaction(self) -> bool:
        return self.active


class FakeRepository:
    def __init__(
        self,
        *,
        isolation: str | None = "repeatable read",
        user: UserModel | None = None,
        accesses: tuple[PersistedSnapshotRefreshAccess, ...] = (),
        snapshots: tuple[AccountSnapshotModel, ...] = (),
    ) -> None:
        self.isolation = isolation
        self.user: UserModel | None = _user() if user is None else user
        self.accesses = accesses
        self.snapshots = snapshots
        self.isolation_calls = 0
        self.user_calls = 0
        self.access_calls = 0
        self.snapshot_calls = 0
        self.snapshot_arguments: dict[str, object] | None = None

    async def load_transaction_isolation(self) -> str | None:
        self.isolation_calls += 1
        return self.isolation

    async def load_user(self, user_id: str) -> UserModel | None:
        self.user_calls += 1
        return self.user

    async def load_account_accesses(
        self,
        user_id: str,
    ) -> tuple[PersistedSnapshotRefreshAccess, ...]:
        self.access_calls += 1
        return self.accesses

    async def load_exact_reuse_snapshots(
        self,
        **kwargs: object,
    ) -> tuple[AccountSnapshotModel, ...]:
        self.snapshot_calls += 1
        self.snapshot_arguments = kwargs
        return self.snapshots


def _user(
    user_id: str = "user-a",
    *,
    currency: str = "CZK",
) -> UserModel:
    return UserModel(
        id=user_id,
        email="user@example.test",
        name="User",
        password_hash=None,
        base_currency=currency,
        created_at=NOW,
        updated_at=NOW,
    )


def _account(
    account_id: str = "account-a",
    *,
    account_type: AccountType = AccountType.broker,
    currency: str = "CZK",
    archived: bool = False,
) -> AccountModel:
    return AccountModel(
        id=account_id,
        name="Account",
        type=account_type,
        currency=currency,
        color=None,
        is_archived=archived,
        archived_at=NOW if archived else None,
        created_at=NOW,
        updated_at=NOW,
        notes=None,
    )


def _access(
    account: AccountModel,
    *,
    membership_id: str | None = None,
    user_id: str = "user-a",
    role: AccountMemberRole = AccountMemberRole.owner,
    relation_type: AccountRelationType = AccountRelationType.owner,
    accepted_at: datetime | None = NOW,
) -> PersistedSnapshotRefreshAccess:
    return PersistedSnapshotRefreshAccess(
        account=account,
        membership=AccountMemberModel(
            id=membership_id or f"member-{account.id}",
            account_id=account.id,
            user_id=user_id,
            role=role,
            relation_type=relation_type,
            invited_by_id=None,
            accepted_at=accepted_at,
            created_at=NOW,
            updated_at=NOW,
        ),
    )


def _snapshot(
    account_id: str = "account-a",
    *,
    snapshot_id: str | None = None,
    timestamp: datetime = NOW,
    granularity: SnapshotGranularity = SnapshotGranularity.day,
    currency: str = "CZK",
    source: SnapshotSource = SnapshotSource.manual_recalculation,
    calculation_version: int = 1,
    calculated_at: datetime = NOW,
    created_at: datetime = NOW,
    is_recalculated: bool = True,
) -> AccountSnapshotModel:
    return AccountSnapshotModel(
        id=snapshot_id or f"snapshot-{account_id}",
        account_id=account_id,
        timestamp=timestamp,
        granularity=granularity,
        source=source,
        currency=currency,
        cash_value=Decimal("999999999999.999999"),
        investment_value=Decimal("-1"),
        investment_cost_basis=Decimal("-2"),
        liabilities_value=Decimal("-3"),
        total_value=Decimal("NaN"),
        is_recalculated=is_recalculated,
        calculated_at=calculated_at,
        calculation_version=calculation_version,
        created_at=created_at,
        net_deposits_value=Decimal("NaN"),
        realized_pnl_value=Decimal("NaN"),
        unrealized_pnl_value=Decimal("NaN"),
        fees_value=Decimal("-1"),
        taxes_value=Decimal("-1"),
        cash_value_by_currency={"malformed": object()},
        investment_value_by_currency={"malformed": object()},
        investment_cost_basis_by_currency=None,
        net_deposits_by_currency=None,
        realized_pnl_by_currency=None,
        unrealized_pnl_by_currency=None,
        fees_by_currency=None,
        taxes_by_currency=None,
        exchange_rates={"not": "validated"},
    )


def _command(**changes: object) -> BuildSnapshotRefreshCoverageCommand:
    values: dict[str, object] = {
        "user_id": "user-a",
        "snapshot_timestamp": NOW,
        "granularity": SnapshotGranularity.day,
        "source": SnapshotSource.manual_recalculation,
        "calculation_version": 1,
        "calculated_at": NOW,
        "created_at": NOW,
        "is_recalculated": True,
    }
    values.update(changes)
    return BuildSnapshotRefreshCoverageCommand(**cast(Any, values))


def _service(
    repository: FakeRepository,
    *,
    session: FakeSession | None = None,
    plan_builder: Any = build_user_snapshot_refresh_plan,
) -> tuple[SnapshotRefreshEvidenceService, FakeSession]:
    resolved = session or FakeSession()
    return (
        SnapshotRefreshEvidenceService(
            cast(Any, resolved),
            repository=cast(Any, repository),
            plan_builder=plan_builder,
        ),
        resolved,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    [
        cast(Any, object()),
        _command(user_id=""),
        _command(user_id=" user "),
        _command(snapshot_timestamp=cast(Any, "2026-07-27")),
        _command(snapshot_timestamp=datetime(2026, 7, 27, tzinfo=UTC)),
        _command(snapshot_timestamp=datetime(2026, 7, 27, 0, 0, 0, 1)),
        _command(snapshot_timestamp=datetime(2026, 7, 27, 0, 1)),
        _command(granularity=cast(Any, "day")),
        _command(source=cast(Any, "manual_recalculation")),
        _command(calculation_version=0),
        _command(calculation_version=cast(Any, True)),
        _command(calculation_version=2_147_483_648),
        _command(calculated_at=datetime(2026, 7, 27, tzinfo=UTC)),
        _command(created_at=datetime(2026, 7, 27, 0, 0, 0, 1)),
        _command(is_recalculated=False),
        _command(source=SnapshotSource.scheduled, is_recalculated=True),
    ],
)
async def test_invalid_command_fails_before_repository_reads(
    command: object,
) -> None:
    repository = FakeRepository()
    service, _ = _service(repository)

    with pytest.raises(SnapshotRefreshEvidenceStateError, match=ERROR):
        await service.build(cast(Any, command))

    assert repository.isolation_calls == 0
    assert repository.user_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("active", "isolation"),
    [
        (False, "repeatable read"),
        (True, "read committed"),
        (True, "read uncommitted"),
        (True, None),
        (True, "unknown"),
    ],
)
async def test_active_coherent_caller_transaction_is_required(
    active: bool,
    isolation: str | None,
) -> None:
    repository = FakeRepository(isolation=isolation)
    service, _ = _service(repository, session=FakeSession(active=active))

    with pytest.raises(SnapshotRefreshEvidenceStateError):
        await service.build(_command())

    assert repository.user_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "isolation",
    ["repeatable read", "REPEATABLE_READ", "serializable", "SERIALIZABLE"],
)
async def test_coherent_isolation_levels_succeed(isolation: str) -> None:
    result = await _service(FakeRepository(isolation=isolation))[0].build(_command())
    assert result.plan.account_targets == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user",
    [
        None,
        _user(""),
        _user("different"),
        _user(currency="czk"),
        _user(currency=" CZK"),
        _user(currency="CZ"),
    ],
)
async def test_missing_or_malformed_persisted_user_fails(
    user: UserModel | None,
) -> None:
    repository = FakeRepository()
    repository.user = user
    service, _ = _service(repository)

    with pytest.raises(SnapshotRefreshEvidenceStateError):
        await service.build(_command())

    assert repository.access_calls == 0


@pytest.mark.asyncio
async def test_persisted_base_currency_reaches_plan_unchanged_once() -> None:
    account = _account(currency="USD")
    builder = Mock(side_effect=build_user_snapshot_refresh_plan)
    repository = FakeRepository(
        user=_user(currency="EUR"),
        accesses=(_access(account),),
    )
    result = await _service(repository, plan_builder=builder)[0].build(_command())

    builder.assert_called_once()
    plan_input = builder.call_args.args[0]
    assert plan_input.user_base_currency == "EUR"
    assert result.plan.output_currency == "EUR"
    assert result.refresh_targets[0].account_currency == "USD"
    assert result.refresh_targets[0].requires_fx_conversion is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "expected_mode"),
    [
        (AccountMemberRole.owner, AccountSnapshotRefreshMode.refresh),
        (AccountMemberRole.admin, AccountSnapshotRefreshMode.refresh),
        (AccountMemberRole.editor, AccountSnapshotRefreshMode.refresh),
        (AccountMemberRole.viewer, AccountSnapshotRefreshMode.reuse_only),
    ],
)
async def test_persisted_role_maps_through_5ka_exactly_once(
    role: AccountMemberRole,
    expected_mode: AccountSnapshotRefreshMode,
) -> None:
    account = _account()
    snapshots = (_snapshot(),) if role is AccountMemberRole.viewer else ()
    builder = Mock(side_effect=build_user_snapshot_refresh_plan)
    result = await _service(
        FakeRepository(
            accesses=(_access(account, role=role),),
            snapshots=snapshots,
        ),
        plan_builder=builder,
    )[0].build(_command())

    builder.assert_called_once()
    assert result.plan.account_targets[0].mode is expected_mode


@pytest.mark.asyncio
async def test_archived_account_is_excluded_by_5ka() -> None:
    archived = _account(
        account_type=AccountType.bank,
        archived=True,
    )
    result = await _service(FakeRepository(accesses=(_access(archived),)))[0].build(_command())
    assert result.plan.account_targets == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda access: setattr(access.account, "id", ""),
        lambda access: setattr(access.account, "type", "broker"),
        lambda access: setattr(access.account, "currency", "czk"),
        lambda access: setattr(access.account, "is_archived", 1),
        lambda access: setattr(access.account, "archived_at", NOW),
        lambda access: setattr(access.membership, "id", ""),
        lambda access: setattr(access.membership, "account_id", "other"),
        lambda access: setattr(access.membership, "user_id", "other"),
        lambda access: setattr(access.membership, "role", "owner"),
        lambda access: setattr(access.membership, "relation_type", "owner"),
        lambda access: setattr(access.membership, "accepted_at", None),
        lambda access: setattr(
            access.membership,
            "accepted_at",
            datetime(2026, 7, 27, tzinfo=UTC),
        ),
    ],
)
async def test_malformed_account_or_membership_fails_closed(
    mutate: Any,
) -> None:
    access = _access(_account())
    mutate(access)
    service, _ = _service(FakeRepository(accesses=(access,)))
    with pytest.raises(SnapshotRefreshEvidenceStateError):
        await service.build(_command())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [AccountType.bank, AccountType.cash, AccountType.savings],
)
async def test_unsupported_active_account_fails_before_snapshot_query(
    account_type: AccountType,
) -> None:
    repository = FakeRepository(accesses=(_access(_account(account_type=account_type)),))
    service, _ = _service(repository)
    with pytest.raises(SnapshotRefreshEvidenceStateError):
        await service.build(_command())
    assert repository.snapshot_calls == 0


@pytest.mark.asyncio
async def test_duplicate_account_or_membership_ids_fail() -> None:
    account = _account()
    duplicate_account = FakeRepository(
        accesses=(
            _access(account, membership_id="one"),
            _access(account, membership_id="two"),
        )
    )
    with pytest.raises(SnapshotRefreshEvidenceStateError):
        await _service(duplicate_account)[0].build(_command())

    duplicate_membership = FakeRepository(
        accesses=(
            _access(_account("one"), membership_id="same"),
            _access(_account("two"), membership_id="same"),
        )
    )
    with pytest.raises(SnapshotRefreshEvidenceStateError):
        await _service(duplicate_membership)[0].build(_command())


@pytest.mark.asyncio
async def test_refresh_only_never_queries_existing_snapshots() -> None:
    accounts = (
        _access(_account("owner"), role=AccountMemberRole.owner),
        _access(_account("admin"), role=AccountMemberRole.admin),
        _access(_account("editor"), role=AccountMemberRole.editor),
    )
    repository = FakeRepository(
        accesses=accounts,
        snapshots=(_snapshot("owner"),),
    )
    result = await _service(repository)[0].build(_command())

    assert result.refresh_target_count == 3
    assert result.reuse_only_target_count == 0
    assert result.selected_reuse_snapshot_count == 0
    assert repository.snapshot_calls == 0


@pytest.mark.asyncio
async def test_mixed_partition_is_complete_ordered_and_disjoint() -> None:
    accesses = (
        _access(_account("z-viewer"), role=AccountMemberRole.viewer),
        _access(_account("a-owner"), role=AccountMemberRole.owner),
        _access(_account("m-editor"), role=AccountMemberRole.editor),
    )
    repository = FakeRepository(
        accesses=accesses,
        snapshots=(_snapshot("z-viewer"),),
    )
    result = await _service(repository)[0].build(_command())

    assert tuple(target.account_id for target in result.refresh_targets) == (
        "a-owner",
        "m-editor",
    )
    assert tuple(target.account_id for target in result.reuse_only_targets) == ("z-viewer",)
    assert result.selected_reuse_snapshots[0].account_id == "z-viewer"
    assert {target.account_id for target in result.refresh_targets}.isdisjoint(
        target.account_id for target in result.reuse_only_targets
    )
    assert repository.snapshot_arguments == {
        "account_ids": ("z-viewer",),
        "timestamp": NOW,
        "granularity": SnapshotGranularity.day,
        "currency": "CZK",
    }


@pytest.mark.asyncio
async def test_exact_viewer_snapshot_succeeds_without_financial_validation() -> None:
    account = _account()
    repository = FakeRepository(
        accesses=(_access(account, role=AccountMemberRole.viewer),),
        snapshots=(_snapshot(),),
    )
    result = await _service(repository)[0].build(_command())

    assert result.selected_reuse_snapshots == (result.selected_reuse_snapshots[0],)
    assert result.selected_reuse_snapshots[0].snapshot_id == "snapshot-account-a"
    assert not hasattr(result.selected_reuse_snapshots[0], "total_value")


@pytest.mark.asyncio
async def test_missing_viewer_snapshot_fails() -> None:
    repository = FakeRepository(accesses=(_access(_account(), role=AccountMemberRole.viewer),))
    with pytest.raises(SnapshotRefreshEvidenceStateError):
        await _service(repository)[0].build(_command())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", ""),
        ("account_id", "unexpected"),
        ("timestamp", datetime(2026, 7, 28)),
        ("granularity", SnapshotGranularity.hour),
        ("currency", "EUR"),
        ("calculation_version", 2),
        ("source", cast(Any, "scheduled")),
        ("is_recalculated", cast(Any, 1)),
        ("calculated_at", datetime(2026, 7, 27, tzinfo=UTC)),
        ("created_at", datetime(2026, 7, 27, 0, 0, 0, 1)),
    ],
)
async def test_malformed_reuse_snapshot_identity_or_metadata_fails(
    field: str,
    value: object,
) -> None:
    snapshot = _snapshot()
    setattr(snapshot, field, value)
    repository = FakeRepository(
        accesses=(_access(_account(), role=AccountMemberRole.viewer),),
        snapshots=(snapshot,),
    )
    with pytest.raises(SnapshotRefreshEvidenceStateError):
        await _service(repository)[0].build(_command())


@pytest.mark.asyncio
async def test_duplicate_snapshot_id_or_unexpected_account_fails() -> None:
    accesses = (
        _access(_account("one"), role=AccountMemberRole.viewer),
        _access(_account("two"), role=AccountMemberRole.viewer),
    )
    duplicate = FakeRepository(
        accesses=accesses,
        snapshots=(
            _snapshot("one", snapshot_id="same"),
            _snapshot("two", snapshot_id="same"),
        ),
    )
    with pytest.raises(SnapshotRefreshEvidenceStateError):
        await _service(duplicate)[0].build(_command())

    unexpected = FakeRepository(
        accesses=(accesses[0],),
        snapshots=(_snapshot("other"),),
    )
    with pytest.raises(SnapshotRefreshEvidenceStateError):
        await _service(unexpected)[0].build(_command())


@pytest.mark.asyncio
async def test_manual_command_may_reuse_scheduled_snapshot() -> None:
    snapshot = _snapshot(
        source=SnapshotSource.scheduled,
        is_recalculated=False,
        calculated_at=datetime(2026, 7, 26),
        created_at=datetime(2026, 7, 26),
    )
    repository = FakeRepository(
        accesses=(_access(_account(), role=AccountMemberRole.viewer),),
        snapshots=(snapshot,),
    )
    result = await _service(repository)[0].build(_command())
    assert result.selected_reuse_snapshot_count == 1


@pytest.mark.asyncio
async def test_scheduled_command_may_reuse_manual_snapshot() -> None:
    repository = FakeRepository(
        accesses=(_access(_account(), role=AccountMemberRole.viewer),),
        snapshots=(_snapshot(),),
    )
    result = await _service(repository)[0].build(
        _command(source=SnapshotSource.scheduled, is_recalculated=False)
    )
    assert result.selected_reuse_snapshot_count == 1


@pytest.mark.asyncio
async def test_5ka_error_maps_with_cause() -> None:
    builder_error = SnapshotRefreshPlanStateError()
    builder = Mock(side_effect=builder_error)
    service, _ = _service(FakeRepository(), plan_builder=builder)
    with pytest.raises(SnapshotRefreshEvidenceStateError) as caught:
        await service.build(_command())
    assert caught.value.__cause__ is builder_error


@pytest.mark.asyncio
async def test_database_and_programming_errors_propagate_unchanged() -> None:
    database_error = OperationalError("sql", {}, RuntimeError("db"))
    repository = FakeRepository()
    cast(Any, repository).load_user = AsyncMock(side_effect=database_error)
    with pytest.raises(OperationalError) as caught:
        await _service(repository)[0].build(_command())
    assert caught.value is database_error

    programming_error = RuntimeError("programming error")
    builder = Mock(side_effect=programming_error)
    with pytest.raises(RuntimeError, match="programming error"):
        await _service(FakeRepository(), plan_builder=builder)[0].build(_command())


@pytest.mark.asyncio
async def test_service_is_transaction_neutral_and_output_is_frozen() -> None:
    repository = FakeRepository()
    service, session = _service(repository)
    result = await service.build(_command())

    session.begin.assert_not_called()
    session.begin_nested.assert_not_called()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
    session.flush.assert_not_awaited()
    session.add.assert_not_called()
    with pytest.raises(FrozenInstanceError):
        cast(Any, result).refresh_target_count = 2
    with pytest.raises(FrozenInstanceError):
        cast(Any, result.plan).output_currency = "EUR"
    assert isinstance(result, CompleteSnapshotRefreshCoverage)


def test_repository_source_contains_only_read_queries() -> None:
    source = inspect.getsource(SnapshotRefreshEvidenceRepository)
    for forbidden in (
        ".begin(",
        ".begin_nested(",
        ".commit(",
        ".rollback(",
        ".flush(",
        ".add(",
        "with_for_update",
        "pg_advisory",
        "update(",
        "delete(",
    ):
        assert forbidden not in source
    assert source.count("autoflush=False") == 4
