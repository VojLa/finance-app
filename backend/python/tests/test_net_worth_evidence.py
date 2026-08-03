from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

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
from app.modules.net_worth.evidence_service import (
    BuildNetWorthEvidenceCommand,
    CompleteNetWorthEvidence,
    NetWorthEvidenceService,
    NetWorthEvidenceStateError,
    SelectedAccountSnapshotIdentity,
)
from app.modules.net_worth.projection import (
    NetWorthProjectionInput,
    NetWorthProjectionStateError,
    build_net_worth_projection,
)
from app.modules.net_worth.repository import PersistedAccountAccess

NOW = datetime(2026, 7, 27)


class FakeSession:
    def __init__(self, *, active: bool = True) -> None:
        self.active = active
        self.begin = Mock()
        self.begin_nested = Mock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()
        self.flush = AsyncMock()

    def in_transaction(self) -> bool:
        return self.active


class FakeRepository:
    def __init__(
        self,
        *,
        isolation: str | None = "repeatable read",
        user: UserModel | None = None,
        accesses: tuple[PersistedAccountAccess, ...] = (),
        snapshots: tuple[AccountSnapshotModel, ...] = (),
    ) -> None:
        self.isolation = isolation
        self.user: UserModel | None = user if user is not None else _user()
        self.accesses = accesses
        self.snapshots = snapshots
        self.isolation_calls = 0
        self.user_calls = 0
        self.account_calls = 0
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
    ) -> tuple[PersistedAccountAccess, ...]:
        self.account_calls += 1
        return self.accesses

    async def load_exact_snapshots(self, **kwargs: object) -> tuple[AccountSnapshotModel, ...]:
        self.snapshot_calls += 1
        self.snapshot_arguments = kwargs
        return self.snapshots


def _user(user_id: str = "user-1") -> UserModel:
    return UserModel(
        id=user_id,
        email="owner@example.com",
        name="Owner",
        password_hash=None,
        base_currency="CZK",
        created_at=NOW,
        updated_at=NOW,
    )


def _account(
    account_id: str = "account-1",
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


def _access(account: AccountModel, *, membership_id: str | None = None) -> PersistedAccountAccess:
    return PersistedAccountAccess(
        account=account,
        membership=AccountMemberModel(
            id=membership_id or f"member-{account.id}",
            account_id=account.id,
            user_id="user-1",
            role=AccountMemberRole.owner,
            relation_type=AccountRelationType.owner,
            invited_by_id=None,
            accepted_at=NOW,
            created_at=NOW,
            updated_at=NOW,
        ),
    )


def _snapshot(
    account: AccountModel,
    *,
    snapshot_id: str | None = None,
) -> AccountSnapshotModel:
    liability = account.type in {
        AccountType.credit_card,
        AccountType.loan,
        AccountType.mortgage,
    }
    cash_only = account.type in {
        AccountType.bank,
        AccountType.cash,
        AccountType.savings,
    }
    cash = Decimal(0) if liability else Decimal("100.000000")
    investment = Decimal(0) if liability or cash_only else Decimal("400.000000")
    cost_basis = Decimal(0) if liability or cash_only else Decimal("300.000000")
    liabilities = Decimal("250.000000") if liability else Decimal(0)
    return AccountSnapshotModel(
        id=snapshot_id or f"snapshot-{account.id}",
        account_id=account.id,
        timestamp=NOW,
        granularity=SnapshotGranularity.day,
        source=SnapshotSource.manual_recalculation,
        currency="CZK",
        cash_value=cash,
        investment_value=investment,
        investment_cost_basis=cost_basis,
        liabilities_value=liabilities,
        total_value=cash + investment - liabilities,
        is_recalculated=True,
        calculated_at=NOW,
        calculation_version=1,
        created_at=NOW,
        net_deposits_value=Decimal(0),
        realized_pnl_value=Decimal(0),
        unrealized_pnl_value=investment - cost_basis,
        fees_value=Decimal(0),
        taxes_value=Decimal(0),
        cash_value_by_currency={} if cash == 0 else {"CZK": "100.000000"},
        investment_value_by_currency=({} if investment == 0 else {"CZK": "400.0000000000"}),
        investment_cost_basis_by_currency=({} if cost_basis == 0 else {"CZK": "300.0000000000"}),
        net_deposits_by_currency={},
        realized_pnl_by_currency={},
        unrealized_pnl_by_currency=({} if liability else {"CZK": "100.000000"}),
        fees_by_currency={},
        taxes_by_currency={},
        exchange_rates={"version": 1},
    )


def _command(**changes: object) -> BuildNetWorthEvidenceCommand:
    values: dict[str, object] = {
        "user_id": "user-1",
        "timestamp": NOW,
        "granularity": SnapshotGranularity.day,
        "currency": "CZK",
        "calculation_version": 1,
    }
    values.update(changes)
    return BuildNetWorthEvidenceCommand(**cast(Any, values))


def _identity(
    account_id: str = "account-1",
    snapshot_id: str = "snapshot-account-1",
) -> SelectedAccountSnapshotIdentity:
    return SelectedAccountSnapshotIdentity(
        account_id=account_id,
        snapshot_id=snapshot_id,
    )


def _set_archive_state(
    access: PersistedAccountAccess,
    *,
    archived: bool,
    archived_at: datetime | None,
) -> None:
    access.account.is_archived = archived
    access.account.archived_at = archived_at


def _service(
    repository: FakeRepository,
    *,
    session: FakeSession | None = None,
    projection_builder: Any = build_net_worth_projection,
) -> tuple[NetWorthEvidenceService, FakeSession]:
    resolved_session = session or FakeSession()
    return (
        NetWorthEvidenceService(
            cast(Any, resolved_session),
            repository=cast(Any, repository),
            projection_builder=projection_builder,
        ),
        resolved_session,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    [
        cast(Any, object()),
        _command(user_id=""),
        _command(user_id=" user "),
        _command(timestamp="2026-07-27"),
        _command(timestamp=datetime(2026, 7, 27, tzinfo=UTC)),
        _command(timestamp=datetime(2026, 7, 27, 0, 0, 0, 1)),
        _command(timestamp=datetime(2026, 7, 27, 0, 1)),
        _command(granularity=cast(Any, "day")),
        _command(currency="czk"),
        _command(currency="CZ"),
        _command(calculation_version=0),
        _command(calculation_version=cast(Any, True)),
        _command(calculation_version=2_147_483_648),
    ],
)
async def test_invalid_command_fails_before_repository_access(command: object) -> None:
    repository = FakeRepository()
    service, _ = _service(repository)

    with pytest.raises(
        NetWorthEvidenceStateError,
        match=r"Persisted evidence cannot produce a complete net worth snapshot\.",
    ):
        await service.build(cast(Any, command))

    assert repository.isolation_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "required",
    [
        cast(Any, [_identity()]),
        cast(Any, (object(),)),
        (_identity(account_id=""),),
        (_identity(account_id=" account-1"),),
        (_identity(snapshot_id=""),),
        (_identity(snapshot_id="snapshot-account-1 "),),
        (
            _identity("account-1", "snapshot-1"),
            _identity("account-1", "snapshot-2"),
        ),
        (
            _identity("account-1", "snapshot-1"),
            _identity("account-2", "snapshot-1"),
        ),
        (
            _identity("account-b", "snapshot-b"),
            _identity("account-a", "snapshot-a"),
        ),
    ],
)
async def test_invalid_required_identities_fail_before_repository_access(
    required: object,
) -> None:
    repository = FakeRepository()
    service, _ = _service(repository)

    with pytest.raises(
        NetWorthEvidenceStateError,
        match=r"^Persisted evidence cannot produce a complete net worth snapshot\.$",
    ):
        await service.build(_command(required_account_snapshot_identities=required))

    assert repository.isolation_calls == 0
    assert repository.user_calls == 0
    assert repository.account_calls == 0
    assert repository.snapshot_calls == 0


@pytest.mark.asyncio
async def test_none_required_identities_preserves_unconstrained_selection() -> None:
    account = _account()
    repository = FakeRepository(
        accesses=(_access(account),),
        snapshots=(_snapshot(account),),
    )
    service, _ = _service(repository)

    result = await service.build(_command(required_account_snapshot_identities=None))

    assert result.selected_identities == (_identity(),)


@pytest.mark.asyncio
async def test_explicit_empty_required_identities_accepts_exact_empty_user() -> None:
    service, _ = _service(FakeRepository())

    result = await service.build(_command(required_account_snapshot_identities=()))

    assert result.selected_identities == ()
    assert result.projection.account_count == 0


@pytest.mark.asyncio
async def test_exact_required_identities_match_persisted_accounts_and_snapshots() -> None:
    account_a = _account("account-a")
    account_b = _account("account-b")
    required = (
        _identity("account-a", "snapshot-a"),
        _identity("account-b", "snapshot-b"),
    )
    repository = FakeRepository(
        accesses=(_access(account_b), _access(account_a)),
        snapshots=(
            _snapshot(account_b, snapshot_id="snapshot-b"),
            _snapshot(account_a, snapshot_id="snapshot-a"),
        ),
    )
    service, _ = _service(repository)

    result = await service.build(_command(required_account_snapshot_identities=required))

    assert result.selected_identities == required
    assert result.selected_account_ids == ("account-a", "account-b")
    assert required == (
        _identity("account-a", "snapshot-a"),
        _identity("account-b", "snapshot-b"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "required",
    [
        (),
        (_identity("account-b", "snapshot-account-b"),),
        (
            _identity("account-1", "snapshot-account-1"),
            _identity("account-2", "snapshot-account-2"),
        ),
    ],
)
async def test_required_account_set_must_exactly_match_active_accounts(
    required: tuple[SelectedAccountSnapshotIdentity, ...],
) -> None:
    account = _account()
    repository = FakeRepository(
        accesses=(_access(account),),
        snapshots=(_snapshot(account),),
    )
    service, _ = _service(repository)

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(_command(required_account_snapshot_identities=required))

    assert repository.account_calls == 1
    assert repository.snapshot_calls == 0


@pytest.mark.asyncio
async def test_required_snapshot_identity_must_match_selected_snapshot() -> None:
    account = _account()
    repository = FakeRepository(
        accesses=(_access(account),),
        snapshots=(_snapshot(account),),
    )
    projection = Mock(side_effect=build_net_worth_projection)
    service, _ = _service(repository, projection_builder=projection)

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(
            _command(
                required_account_snapshot_identities=(_identity(snapshot_id="different-snapshot"),)
            )
        )

    assert repository.snapshot_calls == 1
    projection.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("base_currency", ["EUR", "czk", " CZK", "CZ"])
async def test_persisted_base_currency_mismatch_or_corruption_fails_before_projection(
    base_currency: str,
) -> None:
    repository = FakeRepository(user=_user())
    assert repository.user is not None
    repository.user.base_currency = base_currency
    projection = Mock()
    service, _ = _service(repository, projection_builder=projection)

    with pytest.raises(
        NetWorthEvidenceStateError,
        match=r"Persisted evidence cannot produce a complete net worth snapshot\.",
    ):
        await service.build(_command(currency="CZK"))

    assert repository.user_calls == 1
    assert repository.account_calls == 0
    projection.assert_not_called()


@pytest.mark.asyncio
async def test_matching_persisted_base_currency_reaches_projection() -> None:
    projection = Mock(
        return_value=build_net_worth_projection(
            NetWorthProjectionInput(
                user_id="user-1",
                timestamp=NOW,
                granularity=SnapshotGranularity.day,
                currency="CZK",
                calculation_version=1,
                account_snapshots=(),
            )
        )
    )
    service, _ = _service(FakeRepository(user=_user()), projection_builder=projection)

    result = await service.build(_command())

    assert result.projection.currency == "CZK"
    projection.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("session", "isolation"),
    [
        (FakeSession(active=False), "repeatable read"),
        (FakeSession(), "read committed"),
        (FakeSession(), None),
    ],
)
async def test_caller_transaction_and_coherent_isolation_are_required(
    session: FakeSession,
    isolation: str | None,
) -> None:
    repository = FakeRepository(isolation=isolation)
    service, _ = _service(repository, session=session)

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(_command())


@pytest.mark.asyncio
@pytest.mark.parametrize("isolation", ["repeatable read", "REPEATABLE_READ", "serializable"])
async def test_coherent_isolation_levels_are_accepted(isolation: str) -> None:
    repository = FakeRepository(isolation=isolation)
    service, _ = _service(repository)

    result = await service.build(_command())

    assert result.projection.account_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user",
    [
        None,
        _user(""),
        _user("different-user"),
    ],
)
async def test_missing_or_corrupt_user_fails_closed(user: UserModel | None) -> None:
    repository = FakeRepository(user=user)
    if user is None:
        repository.user = None
    service, _ = _service(repository)

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(_command())


@pytest.mark.asyncio
async def test_real_user_with_zero_accounts_builds_exact_zero_once() -> None:
    repository = FakeRepository()
    projection_builder = Mock(side_effect=build_net_worth_projection)
    service, _ = _service(repository, projection_builder=projection_builder)

    result = await service.build(_command())

    assert isinstance(result, CompleteNetWorthEvidence)
    assert result.projection.net_worth_value == 0
    assert result.selected_account_ids == ()
    assert result.selected_account_snapshot_ids == ()
    assert result.selected_identities == ()
    projection_builder.assert_called_once()
    assert repository.snapshot_calls == 0
    assert repository.snapshot_arguments is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_type",
    [
        AccountType.broker,
        AccountType.exchange,
        AccountType.crypto_wallet,
        AccountType.bank,
        AccountType.cash,
        AccountType.savings,
        AccountType.credit_card,
        AccountType.loan,
        AccountType.mortgage,
    ],
)
async def test_one_supported_account_maps_persisted_type_and_values(
    account_type: AccountType,
) -> None:
    account = _account(account_type=account_type)
    repository = FakeRepository(
        accesses=(_access(account),),
        snapshots=(_snapshot(account),),
    )
    service, _ = _service(repository)

    result = await service.build(_command())

    contribution = result.projection.accounts[0]
    assert contribution.account_type is account_type
    assert result.selected_account_ids == (account.id,)
    assert result.selected_account_snapshot_ids == (f"snapshot-{account.id}",)


@pytest.mark.asyncio
async def test_mixed_supported_accounts_are_selected_deterministically() -> None:
    mortgage = _account("z-mortgage", account_type=AccountType.mortgage)
    broker = _account("a-broker")
    repository = FakeRepository(
        accesses=(_access(mortgage), _access(broker)),
        snapshots=(_snapshot(mortgage), _snapshot(broker)),
    )
    service, _ = _service(repository)

    result = await service.build(_command())

    assert result.selected_account_ids == ("a-broker", "z-mortgage")
    assert result.projection.assets_value == Decimal("500.000000")
    assert result.projection.liabilities_value == Decimal("250.000000")
    assert result.projection.net_worth_value == Decimal("250.000000")


@pytest.mark.asyncio
async def test_valid_archived_account_is_excluded_from_current_evidence() -> None:
    account = _account(account_type=AccountType.bank, archived=True)
    repository = FakeRepository(accesses=(_access(account),))
    service, _ = _service(repository)

    result = await service.build(_command())

    assert result.projection.account_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutate",
    [
        lambda access: setattr(access.account, "id", ""),
        lambda access: setattr(access.account, "type", "broker"),
        lambda access: setattr(access.account, "currency", "czk"),
        lambda access: _set_archive_state(access, archived=False, archived_at=NOW),
        lambda access: _set_archive_state(access, archived=True, archived_at=None),
        lambda access: setattr(access.membership, "user_id", "other"),
        lambda access: setattr(access.membership, "account_id", "other"),
        lambda access: setattr(access.membership, "accepted_at", None),
        lambda access: setattr(access.membership, "role", "owner"),
    ],
)
async def test_malformed_account_or_membership_fails_closed(mutate: Any) -> None:
    access = _access(_account())
    mutate(access)
    repository = FakeRepository(accesses=(access,))
    service, _ = _service(repository)

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(_command())


@pytest.mark.asyncio
async def test_duplicate_account_access_row_fails_closed() -> None:
    account = _account()
    repository = FakeRepository(
        accesses=(
            _access(account, membership_id="member-1"),
            _access(account, membership_id="member-2"),
        )
    )
    service, _ = _service(repository)

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(_command())


@pytest.mark.asyncio
async def test_missing_snapshot_fails_closed() -> None:
    account = _account()
    repository = FakeRepository(accesses=(_access(account),), snapshots=())
    service, _ = _service(repository)

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(_command())


@pytest.mark.asyncio
async def test_unexpected_snapshot_account_fails_closed() -> None:
    account = _account()
    unexpected = _snapshot(_account("unexpected"))
    repository = FakeRepository(
        accesses=(_access(account),),
        snapshots=(_snapshot(account), unexpected),
    )
    service, _ = _service(repository)

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(_command())


@pytest.mark.asyncio
async def test_duplicate_snapshots_for_one_account_fail_closed() -> None:
    account = _account()
    repository = FakeRepository(
        accesses=(_access(account),),
        snapshots=(
            _snapshot(account, snapshot_id="snapshot-1"),
            _snapshot(account, snapshot_id="snapshot-2"),
        ),
    )
    service, _ = _service(repository)

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(_command())


@pytest.mark.asyncio
async def test_duplicate_snapshot_id_across_accounts_fails_closed() -> None:
    first = _account("account-1")
    second = _account("account-2")
    repository = FakeRepository(
        accesses=(_access(first), _access(second)),
        snapshots=(
            _snapshot(first, snapshot_id="same"),
            _snapshot(second, snapshot_id="same"),
        ),
    )
    service, _ = _service(repository)

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(_command())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", ""),
        ("account_id", "other"),
        ("timestamp", datetime(2026, 7, 28)),
        ("granularity", SnapshotGranularity.hour),
        ("currency", "EUR"),
        ("calculation_version", 2),
        ("source", cast(Any, "manual_recalculation")),
        ("is_recalculated", cast(Any, 1)),
    ],
)
async def test_wrong_snapshot_identity_or_metadata_fails_closed(
    field: str,
    value: object,
) -> None:
    account = _account()
    snapshot = _snapshot(account)
    setattr(snapshot, field, value)
    repository = FakeRepository(accesses=(_access(account),), snapshots=(snapshot,))
    service, _ = _service(repository)

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(_command())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total_value", Decimal("499.000000")),
        ("investment_value", Decimal("-1.000000")),
        ("liabilities_value", Decimal("-1.000000")),
        ("cash_value", Decimal("0.0000001")),
        ("cash_value", Decimal("1000000000000.000000")),
        ("investment_cost_basis", Decimal("-1.000000")),
        ("unrealized_pnl_value", Decimal("99.000000")),
        ("fees_value", Decimal("-1.000000")),
        ("taxes_value", Decimal("-1.000000")),
    ],
)
async def test_corrupt_physical_financial_value_fails_closed(
    field: str,
    value: Decimal,
) -> None:
    account = _account()
    snapshot = _snapshot(account)
    setattr(snapshot, field, value)
    repository = FakeRepository(accesses=(_access(account),), snapshots=(snapshot,))
    service, _ = _service(repository)

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(_command())


@pytest.mark.asyncio
async def test_mixed_liability_and_investment_fields_fail_closed() -> None:
    account = _account(account_type=AccountType.mortgage)
    snapshot = _snapshot(account)
    snapshot.investment_value = Decimal("1.000000")
    snapshot.investment_cost_basis = Decimal("1.000000")
    snapshot.total_value = Decimal("-249.000000")
    repository = FakeRepository(accesses=(_access(account),), snapshots=(snapshot,))
    service, _ = _service(repository)

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(_command())


@pytest.mark.asyncio
async def test_sql_null_breakdowns_remain_unavailable() -> None:
    account = _account()
    snapshot = _snapshot(account)
    snapshot.cash_value_by_currency = None
    snapshot.investment_value_by_currency = None
    repository = FakeRepository(accesses=(_access(account),), snapshots=(snapshot,))
    service, _ = _service(repository)

    result = await service.build(_command())

    assert result.projection.cash_value_by_currency is None
    assert result.projection.portfolio_value_by_currency is None


@pytest.mark.asyncio
async def test_empty_json_objects_map_to_exact_empty_tuples_for_zero_values() -> None:
    account = _account()
    snapshot = _snapshot(account)
    snapshot.cash_value = Decimal(0)
    snapshot.investment_value = Decimal(0)
    snapshot.investment_cost_basis = Decimal(0)
    snapshot.total_value = Decimal(0)
    snapshot.unrealized_pnl_value = Decimal(0)
    snapshot.cash_value_by_currency = {}
    snapshot.investment_value_by_currency = {}
    snapshot.investment_cost_basis_by_currency = {}
    repository = FakeRepository(accesses=(_access(account),), snapshots=(snapshot,))
    service, _ = _service(repository)

    result = await service.build(_command())

    assert result.projection.cash_value_by_currency == ()
    assert result.projection.portfolio_value_by_currency == ()


@pytest.mark.asyncio
async def test_valid_multi_currency_breakdown_is_sorted() -> None:
    account = _account()
    snapshot = _snapshot(account)
    snapshot.cash_value_by_currency = {
        "USD": "2.000000",
        "CZK": "100.000000",
    }
    repository = FakeRepository(accesses=(_access(account),), snapshots=(snapshot,))
    service, _ = _service(repository)

    result = await service.build(_command())

    assert tuple(item.currency for item in result.projection.cash_value_by_currency or ()) == (
        "CZK",
        "USD",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("cash_value_by_currency", []),
        ("cash_value_by_currency", {"CZK": {"amount": "1.000000"}}),
        ("cash_value_by_currency", {"CZK": 1.0}),
        ("cash_value_by_currency", {"czk": "1.000000"}),
        ("cash_value_by_currency", {"CZK": "1.00000"}),
        ("cash_value_by_currency", {"CZK": "1e0"}),
        ("cash_value_by_currency", {"CZK": "NaN"}),
        ("cash_value_by_currency", {"CZK": "1000000000000.000000"}),
        ("investment_value_by_currency", {"CZK": "1.000000"}),
        ("investment_value_by_currency", {"CZK": "1.00000000001"}),
        ("exchange_rates", []),
    ],
)
async def test_malformed_jsonb_evidence_fails_closed(field: str, value: object) -> None:
    account = _account()
    snapshot = _snapshot(account)
    setattr(snapshot, field, value)
    repository = FakeRepository(accesses=(_access(account),), snapshots=(snapshot,))
    service, _ = _service(repository)

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(_command())


@pytest.mark.asyncio
async def test_projection_receives_exact_persisted_command_once() -> None:
    account = _account(currency="EUR")
    snapshot = _snapshot(account)
    snapshot.currency = "CZK"
    repository = FakeRepository(accesses=(_access(account),), snapshots=(snapshot,))
    projection_builder = Mock(side_effect=build_net_worth_projection)
    service, _ = _service(repository, projection_builder=projection_builder)

    result = await service.build(_command())

    projection_builder.assert_called_once()
    projection_input = projection_builder.call_args.args[0]
    assert projection_input.user_id == "user-1"
    assert projection_input.account_snapshots[0].account_currency == "EUR"
    assert projection_input.account_snapshots[0].snapshot_currency == "CZK"
    assert result.projection.net_worth_value == Decimal("500.000000")


@pytest.mark.asyncio
async def test_pure_projection_error_maps_to_generic_evidence_error() -> None:
    repository = FakeRepository()
    projection_builder = Mock(side_effect=NetWorthProjectionStateError())
    service, _ = _service(repository, projection_builder=projection_builder)

    with pytest.raises(
        NetWorthEvidenceStateError,
        match=r"Persisted evidence cannot produce a complete net worth snapshot\.",
    ):
        await service.build(_command())


@pytest.mark.asyncio
async def test_malformed_projection_result_fails_closed() -> None:
    repository = FakeRepository()
    service, _ = _service(repository, projection_builder=Mock(return_value=object()))

    with pytest.raises(NetWorthEvidenceStateError):
        await service.build(_command())


@pytest.mark.asyncio
async def test_unexpected_programming_error_propagates_unchanged() -> None:
    error = RuntimeError("controlled programming error")
    service, _ = _service(
        FakeRepository(),
        projection_builder=Mock(side_effect=error),
    )

    with pytest.raises(RuntimeError) as caught:
        await service.build(_command())

    assert caught.value is error


@pytest.mark.asyncio
async def test_service_and_repository_are_transaction_neutral() -> None:
    repository = FakeRepository()
    service, session = _service(repository)

    await service.build(_command())

    session.begin.assert_not_called()
    session.begin_nested.assert_not_called()
    session.commit.assert_not_awaited()
    session.rollback.assert_not_awaited()
    session.flush.assert_not_awaited()
    assert repository.isolation_calls == 1
    assert repository.user_calls == 1
    assert repository.account_calls == 1
    assert repository.snapshot_calls == 0


def test_result_contract_is_frozen() -> None:
    identity = _identity()
    command = _command(required_account_snapshot_identities=(identity,))
    with pytest.raises(FrozenInstanceError):
        cast(Any, command).user_id = "other"
    with pytest.raises(FrozenInstanceError):
        cast(Any, identity).snapshot_id = "other"
    assert not hasattr(command, "__dict__")
