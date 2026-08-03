"""Focused tests for the pure coordinated snapshot-refresh plan."""

from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from app.db.models.enums import (
    AccountMemberRole,
    AccountRelationType,
    AccountType,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.snapshot_refresh import (
    AccountSnapshotRefreshMode,
    ExpectedUserSnapshotRefreshPlan,
    SnapshotRefreshAccountEvidence,
    SnapshotRefreshPlanInput,
    SnapshotRefreshPlanStateError,
    build_user_snapshot_refresh_plan,
)
from app.modules.snapshot_refresh import plan as plan_module

ERROR = "Snapshot refresh evidence cannot produce a complete plan."
BUCKET = datetime(2026, 7, 27, 10, 20)


def _account(
    account_id: str = "account-a",
    *,
    account_type: AccountType = AccountType.broker,
    account_currency: str = "CZK",
    membership_id: str | None = None,
    membership_role: AccountMemberRole = AccountMemberRole.owner,
    relation_type: AccountRelationType = AccountRelationType.owner,
    accepted_at: datetime = datetime(2026, 1, 1),
    is_archived: bool = False,
    archived_at: datetime | None = None,
) -> SnapshotRefreshAccountEvidence:
    return SnapshotRefreshAccountEvidence(
        account_id=account_id,
        account_type=account_type,
        account_currency=account_currency,
        membership_id=membership_id or f"member-{account_id}",
        membership_role=membership_role,
        relation_type=relation_type,
        accepted_at=accepted_at,
        is_archived=is_archived,
        archived_at=archived_at,
    )


def _input(
    *accounts: SnapshotRefreshAccountEvidence,
    user_id: str = "user-a",
    user_base_currency: str = "CZK",
    snapshot_timestamp: datetime = BUCKET,
    granularity: SnapshotGranularity = SnapshotGranularity.minute,
    source: SnapshotSource = SnapshotSource.manual_recalculation,
    calculation_version: int = 1,
    calculated_at: datetime = BUCKET,
    created_at: datetime = BUCKET,
    is_recalculated: bool = True,
) -> SnapshotRefreshPlanInput:
    return SnapshotRefreshPlanInput(
        user_id=user_id,
        user_base_currency=user_base_currency,
        snapshot_timestamp=snapshot_timestamp,
        granularity=granularity,
        source=source,
        calculation_version=calculation_version,
        calculated_at=calculated_at,
        created_at=created_at,
        is_recalculated=is_recalculated,
        accounts=accounts,
    )


def _fails(value: SnapshotRefreshPlanInput) -> None:
    with pytest.raises(SnapshotRefreshPlanStateError, match=ERROR):
        build_user_snapshot_refresh_plan(value)


def test_empty_active_account_set_still_builds_final_target() -> None:
    result = build_user_snapshot_refresh_plan(_input())

    assert result.account_targets == ()
    assert result.net_worth_target.required_account_ids == ()
    assert result.refresh_account_count == 0
    assert result.reuse_only_account_count == 0
    assert result.fx_conversion_account_count == 0
    assert result.net_worth_target.user_id == "user-a"
    assert result.net_worth_target.output_currency == "CZK"


@pytest.mark.parametrize(
    "account_type",
    [
        AccountType.broker,
        AccountType.exchange,
        AccountType.crypto_wallet,
        AccountType.credit_card,
        AccountType.loan,
        AccountType.mortgage,
    ],
)
def test_every_supported_account_type_produces_one_target(
    account_type: AccountType,
) -> None:
    result = build_user_snapshot_refresh_plan(_input(_account(account_type=account_type)))

    assert result.account_targets[0].account_type is account_type
    assert result.refresh_account_count == 1
    assert result.net_worth_target.required_account_ids == ("account-a",)


@pytest.mark.parametrize(
    ("role", "expected_mode"),
    [
        (AccountMemberRole.owner, AccountSnapshotRefreshMode.refresh),
        (AccountMemberRole.admin, AccountSnapshotRefreshMode.refresh),
        (AccountMemberRole.editor, AccountSnapshotRefreshMode.refresh),
        (AccountMemberRole.viewer, AccountSnapshotRefreshMode.reuse_only),
    ],
)
def test_role_maps_to_exact_refresh_capability(
    role: AccountMemberRole,
    expected_mode: AccountSnapshotRefreshMode,
) -> None:
    result = build_user_snapshot_refresh_plan(_input(_account(membership_role=role)))

    assert result.account_targets[0].mode is expected_mode
    assert result.refresh_account_count == int(expected_mode is AccountSnapshotRefreshMode.refresh)
    assert result.reuse_only_account_count == int(
        expected_mode is AccountSnapshotRefreshMode.reuse_only
    )


def test_mixed_investment_liability_roles_and_currencies_are_complete() -> None:
    result = build_user_snapshot_refresh_plan(
        _input(
            _account("z-loan", account_type=AccountType.loan),
            _account(
                "a-broker",
                account_currency="EUR",
                membership_role=AccountMemberRole.viewer,
            ),
            _account(
                "m-wallet",
                account_type=AccountType.crypto_wallet,
                account_currency="USD",
                membership_role=AccountMemberRole.editor,
            ),
        )
    )

    assert tuple(target.account_id for target in result.account_targets) == (
        "a-broker",
        "m-wallet",
        "z-loan",
    )
    assert result.net_worth_target.required_account_ids == (
        "a-broker",
        "m-wallet",
        "z-loan",
    )
    assert result.refresh_account_count == 2
    assert result.reuse_only_account_count == 1
    assert result.fx_conversion_account_count == 2


@pytest.mark.parametrize(
    ("granularity", "timestamp"),
    [
        (SnapshotGranularity.minute, datetime(2026, 7, 27, 10, 20)),
        (SnapshotGranularity.hour, datetime(2026, 7, 27, 10)),
        (SnapshotGranularity.day, datetime(2026, 7, 27)),
        (SnapshotGranularity.week, datetime(2026, 7, 27)),
        (SnapshotGranularity.month, datetime(2026, 7, 1)),
    ],
)
def test_every_canonical_bucket_is_accepted(
    granularity: SnapshotGranularity,
    timestamp: datetime,
) -> None:
    result = build_user_snapshot_refresh_plan(
        _input(
            _account(),
            snapshot_timestamp=timestamp,
            granularity=granularity,
            calculated_at=timestamp,
            created_at=timestamp,
        )
    )

    assert result.net_worth_target.snapshot_timestamp == timestamp
    assert result.account_targets[0].granularity is granularity


def test_output_currency_is_user_base_currency_not_account_currency() -> None:
    result = build_user_snapshot_refresh_plan(
        _input(
            _account("same", account_currency="EUR"),
            _account("different", account_currency="USD"),
            user_base_currency="EUR",
        )
    )

    by_id = {target.account_id: target for target in result.account_targets}
    assert by_id["same"].account_currency == "EUR"
    assert by_id["same"].output_currency == "EUR"
    assert by_id["same"].requires_fx_conversion is False
    assert by_id["different"].account_currency == "USD"
    assert by_id["different"].output_currency == "EUR"
    assert by_id["different"].requires_fx_conversion is True
    assert result.output_currency == "EUR"
    assert result.net_worth_target.output_currency == "EUR"


@pytest.mark.parametrize("currency", ["czk", "CZ", " CZK", "CZK ", "ÄBC", "C2K"])
def test_malformed_user_base_currency_fails_closed(currency: str) -> None:
    _fails(_input(user_base_currency=currency))


@pytest.mark.parametrize("currency", ["usd", "US", " USD", "USD ", "ÅBC", "U2D"])
def test_malformed_account_currency_fails_closed(currency: str) -> None:
    _fails(_input(_account(account_currency=currency)))


@pytest.mark.parametrize(
    "account_type",
    [AccountType.bank, AccountType.cash, AccountType.savings],
)
def test_each_active_cash_account_type_is_a_refresh_target(
    account_type: AccountType,
) -> None:
    result = build_user_snapshot_refresh_plan(_input(_account(account_type=account_type)))
    assert len(result.account_targets) == 1
    assert result.account_targets[0].account_type is account_type
    assert result.account_targets[0].mode is AccountSnapshotRefreshMode.refresh


def test_investment_and_cash_accounts_produce_one_complete_plan() -> None:
    result = build_user_snapshot_refresh_plan(
        _input(
            _account("broker"),
            _account("bank", account_type=AccountType.bank),
        )
    )
    assert tuple(target.account_id for target in result.account_targets) == ("bank", "broker")


def test_consistently_archived_account_is_excluded() -> None:
    archived = _account(
        "archived",
        account_type=AccountType.bank,
        is_archived=True,
        archived_at=datetime(2026, 1, 1),
    )
    result = build_user_snapshot_refresh_plan(_input(_account("active"), archived))

    assert tuple(target.account_id for target in result.account_targets) == ("active",)


@pytest.mark.parametrize(
    "account",
    [
        replace(_account(), is_archived=cast(bool, 1)),
        _account("archived-no-time", is_archived=True),
        _account("active-with-time", archived_at=datetime(2026, 1, 1)),
        _account(
            "archived-aware",
            is_archived=True,
            archived_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        _account(
            "archived-precision",
            is_archived=True,
            archived_at=datetime(2026, 1, 1, 0, 0, 0, 1),
        ),
    ],
)
def test_contradictory_or_malformed_archive_state_fails_closed(
    account: SnapshotRefreshAccountEvidence,
) -> None:
    _fails(_input(account))


@pytest.mark.parametrize(
    "account",
    [
        replace(_account(), membership_id=""),
        replace(_account(), membership_id=" member "),
        replace(_account(), accepted_at=cast(datetime, None)),
        replace(_account(), accepted_at=datetime(2026, 1, 1, tzinfo=UTC)),
        replace(_account(), accepted_at=datetime(2026, 1, 1, 0, 0, 0, 1)),
        replace(
            _account(),
            membership_role=cast(AccountMemberRole, "owner"),
        ),
        replace(
            _account(),
            relation_type=cast(AccountRelationType, "owner"),
        ),
    ],
)
def test_malformed_active_membership_fails_closed(
    account: SnapshotRefreshAccountEvidence,
) -> None:
    _fails(_input(account))


def test_duplicate_active_membership_identity_fails_closed() -> None:
    _fails(
        _input(
            _account("one", membership_id="same-member"),
            _account("two", membership_id="same-member"),
        )
    )


def test_duplicate_active_account_identity_fails_closed() -> None:
    _fails(
        _input(
            _account("same", membership_id="member-one"),
            _account("same", membership_id="member-two"),
        )
    )


@pytest.mark.parametrize(
    "value",
    [
        _input(user_id=""),
        _input(user_id=" user "),
        _input(snapshot_timestamp=datetime(2026, 7, 27, tzinfo=UTC)),
        _input(snapshot_timestamp=datetime(2026, 7, 27, 10, 20, 0, 1)),
        _input(snapshot_timestamp=datetime(2026, 7, 27, 10, 20, 1)),
        _input(granularity=cast(SnapshotGranularity, "minute")),
        _input(source=cast(SnapshotSource, "manual_recalculation")),
        _input(calculation_version=0),
        _input(calculation_version=cast(int, True)),
        _input(calculation_version=2_147_483_648),
        _input(calculated_at=datetime(2026, 7, 27, tzinfo=UTC)),
        _input(created_at=datetime(2026, 7, 27, 0, 0, 0, 1)),
        _input(is_recalculated=False),
        _input(
            source=SnapshotSource.scheduled,
            is_recalculated=True,
        ),
        replace(_input(), accounts=cast(Any, [])),
    ],
)
def test_invalid_plan_metadata_fails_closed(
    value: SnapshotRefreshPlanInput,
) -> None:
    _fails(value)


def test_scheduled_non_recalculated_plan_is_valid() -> None:
    result = build_user_snapshot_refresh_plan(
        _input(
            _account(),
            source=SnapshotSource.scheduled,
            is_recalculated=False,
        )
    )

    assert result.account_targets[0].source is SnapshotSource.scheduled
    assert result.account_targets[0].is_recalculated is False


def test_postgresql_integer_maximum_is_valid() -> None:
    result = build_user_snapshot_refresh_plan(_input(calculation_version=2_147_483_647))
    assert result.net_worth_target.calculation_version == 2_147_483_647


def test_permutation_is_equal_and_ordering_and_counts_remain_exact() -> None:
    accounts = (
        _account(
            "z",
            membership_role=AccountMemberRole.viewer,
            account_currency="EUR",
        ),
        _account("a", membership_role=AccountMemberRole.admin),
        _account(
            "m",
            membership_role=AccountMemberRole.editor,
            account_currency="USD",
        ),
    )

    first = build_user_snapshot_refresh_plan(_input(*accounts))
    second = build_user_snapshot_refresh_plan(_input(*reversed(accounts)))

    assert first == second
    assert first.net_worth_target.required_account_ids == ("a", "m", "z")
    assert first.refresh_account_count == 2
    assert first.reuse_only_account_count == 1
    assert first.fx_conversion_account_count == 2


def test_all_contracts_are_frozen_and_inputs_are_not_mutated() -> None:
    account = _account()
    value = _input(account)
    before = value.accounts
    result = build_user_snapshot_refresh_plan(value)

    with pytest.raises(FrozenInstanceError):
        cast(Any, account).account_id = "changed"
    with pytest.raises(FrozenInstanceError):
        cast(Any, value).user_id = "changed"
    with pytest.raises(FrozenInstanceError):
        cast(Any, result).output_currency = "EUR"
    with pytest.raises(FrozenInstanceError):
        cast(Any, result.account_targets[0]).account_id = "changed"
    with pytest.raises(FrozenInstanceError):
        cast(Any, result.net_worth_target).user_id = "changed"
    assert value.accounts is before
    assert value.accounts == (account,)


def test_wrong_runtime_input_and_account_types_fail_closed() -> None:
    with pytest.raises(SnapshotRefreshPlanStateError, match=ERROR):
        build_user_snapshot_refresh_plan(cast(SnapshotRefreshPlanInput, object()))
    _fails(replace(_input(), accounts=cast(Any, (object(),))))
    _fails(_input(replace(_account(), account_id=" account ")))
    _fails(
        _input(
            replace(
                _account(),
                account_type=cast(AccountType, "broker"),
            )
        )
    )


def test_result_uses_declared_immutable_contract() -> None:
    result = build_user_snapshot_refresh_plan(_input(_account()))
    assert isinstance(result, ExpectedUserSnapshotRefreshPlan)


def test_plan_module_has_no_database_writer_api_or_clock_imports() -> None:
    source = inspect.getsource(plan_module)
    tree = ast.parse(source)
    imported_modules = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }

    assert all(
        not module.startswith(
            (
                "sqlalchemy",
                "fastapi",
                "app.modules.snapshots",
                "app.modules.net_worth",
            )
        )
        for module in imported_modules
    )
    assert "AsyncSession" not in source
    assert "Writer" not in source
    assert "datetime.now" not in source
    assert "uuid" not in source.lower()
    assert Path(inspect.getfile(plan_module)).name == "plan.py"
