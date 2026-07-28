from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid5

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.db.models.accounts import AccountModel
from app.db.models.common import MONEY, TIMESTAMP
from app.db.models.enums import AccountType, LiabilityBalanceSource
from app.db.models.liabilities import LiabilityBalanceModel
from app.modules.liabilities.writer import (
    ExpectedLiabilityBalanceRow,
    LiabilityBalanceWriteConflictError,
    LiabilityBalanceWriteDisposition,
    LiabilityBalanceWriter,
    LiabilityBalanceWriteResult,
    LiabilityBalanceWriteStateError,
    WriteLiabilityBalanceCommand,
    build_expected_liability_balance,
    deterministic_balance_id,
)
from app.modules.liabilities.writer_repository import (
    advisory_lock_id,
    balance_identity_lock_scope,
    external_identity_lock_scope,
    identity_lock_ids,
)

EFFECTIVE_AT = datetime(2026, 7, 28, 10, 20, 30, 123000)
CREATED_AT = datetime(2026, 7, 28, 10, 21, 0, 456000)
_NAMESPACE = UUID("ea19c471-9ff6-59bd-8fe2-33201b0ad13e")


class _Transaction:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> None:
        self.session.active = True
        self.session.begin_count += 1

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        if exc_type is None:
            self.session.commit_count += 1
        else:
            self.session.rollback_count += 1
        self.session.active = False


class _Session:
    def __init__(self) -> None:
        self.active = False
        self.begin_count = 0
        self.commit_count = 0
        self.rollback_count = 0

    def in_transaction(self) -> bool:
        return self.active

    def begin(self) -> _Transaction:
        return _Transaction(self)


class _Repository:
    def __init__(self) -> None:
        self.account: AccountModel | None = _account()
        self.by_timestamp: LiabilityBalanceModel | None = None
        self.by_external: LiabilityBalanceModel | None = None
        self.by_id: LiabilityBalanceModel | None = None
        self.inserted: LiabilityBalanceModel | None = None
        self.reload_value: LiabilityBalanceModel | None = None
        self.calls: list[object] = []
        self.flush_error: Exception | None = None
        self.account_error: Exception | None = None

    async def load_account_for_share(self, account_id: str) -> AccountModel | None:
        self.calls.append(("account", account_id))
        if self.account_error is not None:
            raise self.account_error
        return self.account

    async def acquire_identity_locks(self, lock_ids: tuple[int, ...]) -> None:
        self.calls.append(("locks", lock_ids))

    async def load_by_timestamp_identity(self, **values: object) -> LiabilityBalanceModel | None:
        self.calls.append(("timestamp", values))
        return self.by_timestamp

    async def load_by_external_identity(self, **values: object) -> LiabilityBalanceModel | None:
        self.calls.append(("external", values))
        return self.by_external

    async def load_by_id(self, balance_id: str) -> LiabilityBalanceModel | None:
        self.calls.append(("id", balance_id))
        return self.by_id

    def add(self, balance: LiabilityBalanceModel) -> None:
        self.calls.append(("add", balance.id))
        self.inserted = balance
        self.reload_value = balance

    async def flush(self) -> None:
        self.calls.append("flush")
        if self.flush_error is not None:
            raise self.flush_error

    async def reload(self, balance_id: str) -> LiabilityBalanceModel | None:
        self.calls.append(("reload", balance_id))
        return self.reload_value


def _account(
    *,
    account_id: str = "account-1",
    account_type: AccountType = AccountType.credit_card,
    currency: str = "CZK",
    archived: bool = False,
) -> AccountModel:
    return AccountModel(
        id=account_id,
        name="Liability",
        type=account_type,
        currency=currency,
        color=None,
        notes=None,
        is_archived=archived,
        archived_at=CREATED_AT if archived else None,
        created_at=datetime(2026, 1, 1),
        updated_at=CREATED_AT,
    )


def _command(**changes: object) -> WriteLiabilityBalanceCommand:
    values: dict[str, object] = {
        "account_id": "account-1",
        "effective_at": EFFECTIVE_AT,
        "currency": "CZK",
        "outstanding_principal": Decimal("100.123456"),
        "accrued_interest": Decimal("2.000001"),
        "fees_outstanding": Decimal("3.100000"),
        "source": LiabilityBalanceSource.statement,
        "external_id": "statement-42",
        "created_at": CREATED_AT,
    }
    values.update(changes)
    return WriteLiabilityBalanceCommand(**cast(Any, values))


def _model(
    expected: ExpectedLiabilityBalanceRow | None = None,
    **changes: object,
) -> LiabilityBalanceModel:
    values = (expected or build_expected_liability_balance(_command())).model_values()
    values.update(changes)
    return LiabilityBalanceModel(**cast(Any, values))


def _writer() -> tuple[LiabilityBalanceWriter, _Session, _Repository]:
    session = _Session()
    repository = _Repository()
    return (
        LiabilityBalanceWriter(cast(Any, session), repository=repository),
        session,
        repository,
    )


def test_lock_scopes_are_namespaced_nul_delimited_and_signed() -> None:
    balance_scope = balance_identity_lock_scope(
        account_id="account-1",
        effective_at=EFFECTIVE_AT,
        source=LiabilityBalanceSource.statement,
    )
    external_scope = external_identity_lock_scope(
        account_id="account-1",
        source=LiabilityBalanceSource.statement,
        external_id="statement-42",
    )
    assert balance_scope == "\0".join(
        (
            "liabilities:balance",
            "account-1",
            "2026-07-28T10:20:30.123",
            "statement",
        )
    )
    assert external_scope == "liabilities:external\0account-1\0statement\0statement-42"
    assert -(2**63) <= advisory_lock_id(balance_scope) < 2**63
    assert advisory_lock_id(balance_scope) != advisory_lock_id(external_scope)


def test_identity_lock_ids_are_sorted_and_deduplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.modules.liabilities.writer_repository.advisory_lock_id",
        lambda scope: 4 if scope.startswith("liabilities:balance") else -7,
    )
    assert identity_lock_ids(
        account_id="account-1",
        effective_at=EFFECTIVE_AT,
        source=LiabilityBalanceSource.statement,
        external_id="statement-42",
    ) == (-7, 4)
    monkeypatch.setattr(
        "app.modules.liabilities.writer_repository.advisory_lock_id",
        lambda scope: 9,
    )
    assert identity_lock_ids(
        account_id="account-1",
        effective_at=EFFECTIVE_AT,
        source=LiabilityBalanceSource.statement,
        external_id="statement-42",
    ) == (9,)


@pytest.mark.parametrize(
    "command",
    [
        object(),
        _command(account_id=""),
        _command(account_id=" account-1"),
        _command(account_id="account\0one"),
        _command(effective_at="2026-07-28"),
        _command(effective_at=datetime(2026, 7, 28, tzinfo=UTC)),
        _command(effective_at=datetime(2026, 7, 28, 0, 0, 0, 1)),
        _command(created_at=datetime(2026, 7, 28, tzinfo=UTC)),
        _command(created_at=datetime(2026, 7, 28, 0, 0, 0, 1)),
        _command(currency="czk"),
        _command(currency="CZ"),
        _command(currency="CZ1"),
        _command(outstanding_principal=1),
        _command(outstanding_principal=1.1),
        _command(outstanding_principal=True),
        _command(outstanding_principal=Decimal("-0.000001")),
        _command(accrued_interest=Decimal("-1")),
        _command(fees_outstanding=Decimal("-1")),
        _command(outstanding_principal=Decimal("0.0000001")),
        _command(outstanding_principal=Decimal("1000000000000")),
        _command(outstanding_principal=Decimal("NaN")),
        _command(outstanding_principal=Decimal("Infinity")),
        _command(source="statement"),
        _command(external_id=""),
        _command(external_id=" statement-42"),
        _command(external_id="statement\0identity"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_command_fails_before_transaction(command: object) -> None:
    writer, session, repository = _writer()
    with pytest.raises(
        LiabilityBalanceWriteStateError,
        match=r"^Liability balance could not be persisted\.$",
    ):
        await writer.write(cast(Any, command))
    assert session.begin_count == 0
    assert session.commit_count == 0
    assert session.rollback_count == 0
    assert repository.calls == []


def test_expected_row_has_exact_total_deterministic_id_and_is_frozen() -> None:
    expected = build_expected_liability_balance(_command())
    payload = "\0".join(
        (
            "liability-balance",
            "account-1",
            "2026-07-28T10:20:30.123",
            "statement",
            "statement-42",
        )
    )
    assert expected.id == str(uuid5(_NAMESPACE, payload))
    assert expected.id == deterministic_balance_id(
        account_id="account-1",
        effective_at=EFFECTIVE_AT,
        source=LiabilityBalanceSource.statement,
        external_id="statement-42",
    )
    assert expected.total_outstanding == Decimal("105.223457")
    assert tuple(expected.model_values()) == (
        "id",
        "account_id",
        "effective_at",
        "currency",
        "outstanding_principal",
        "accrued_interest",
        "fees_outstanding",
        "total_outstanding",
        "source",
        "external_id",
        "created_at",
    )
    with pytest.raises(FrozenInstanceError):
        cast(Any, expected).currency = "EUR"


def test_zero_and_maximum_money_boundaries_are_exact() -> None:
    zero = build_expected_liability_balance(
        _command(
            outstanding_principal=Decimal(0),
            accrued_interest=Decimal(0),
            fees_outstanding=Decimal(0),
        )
    )
    maximum = build_expected_liability_balance(
        _command(
            outstanding_principal=Decimal("999999999999.999999"),
            accrued_interest=Decimal(0),
            fees_outstanding=Decimal(0),
        )
    )
    assert zero.total_outstanding == 0
    assert maximum.total_outstanding == Decimal("999999999999.999999")
    assert MONEY.precision == 18
    assert MONEY.scale == 6
    assert TIMESTAMP.precision == 3


def test_component_sum_overflow_fails_closed() -> None:
    with pytest.raises(LiabilityBalanceWriteStateError):
        build_expected_liability_balance(
            _command(
                outstanding_principal=Decimal("999999999999.999999"),
                accrued_interest=Decimal("0.000001"),
                fees_outstanding=Decimal(0),
            )
        )


@pytest.mark.asyncio
async def test_created_path_owns_one_transaction_and_uses_required_order() -> None:
    writer, session, repository = _writer()
    expected = build_expected_liability_balance(_command())

    result = await writer.write(_command())

    assert result == LiabilityBalanceWriteResult(
        balance_id=expected.id,
        account_id="account-1",
        effective_at=EFFECTIVE_AT,
        currency="CZK",
        total_outstanding=Decimal("105.223457"),
        source=LiabilityBalanceSource.statement,
        disposition=LiabilityBalanceWriteDisposition.created,
    )
    assert [call[0] if isinstance(call, tuple) else call for call in repository.calls] == [
        "account",
        "locks",
        "timestamp",
        "external",
        "id",
        "add",
        "flush",
        "reload",
    ]
    lock_ids = cast(tuple[str, tuple[int, ...]], repository.calls[1])[1]
    assert lock_ids == tuple(sorted(set(lock_ids)))
    assert repository.inserted is not None
    assert repository.inserted.total_outstanding == expected.total_outstanding
    assert session.begin_count == 1
    assert session.commit_count == 1
    assert session.rollback_count == 0


@pytest.mark.asyncio
async def test_manual_create_uses_only_timestamp_identity_lock_and_no_external_lookup() -> None:
    writer, _, repository = _writer()
    command = _command(source=LiabilityBalanceSource.manual, external_id=None)
    result = await writer.write(command)
    assert result.disposition is LiabilityBalanceWriteDisposition.created
    assert not any(isinstance(call, tuple) and call[0] == "external" for call in repository.calls)
    lock_ids = cast(tuple[str, tuple[int, ...]], repository.calls[1])[1]
    assert len(lock_ids) == 1


@pytest.mark.asyncio
async def test_exact_timestamp_and_external_identity_replay_is_read_only() -> None:
    writer, session, repository = _writer()
    expected = build_expected_liability_balance(_command())
    persisted = _model(expected)
    repository.by_timestamp = persisted
    repository.by_external = persisted

    result = await writer.write(_command())

    assert result.disposition is LiabilityBalanceWriteDisposition.replayed
    assert repository.inserted is None
    assert "flush" not in repository.calls
    assert not any(isinstance(call, tuple) and call[0] == "id" for call in repository.calls)
    assert session.commit_count == 1
    assert session.rollback_count == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "wrong-id"),
        ("account_id", "other-account"),
        ("effective_at", datetime(2026, 7, 28, 10, 20, 31, 123000)),
        ("currency", "EUR"),
        ("outstanding_principal", Decimal("101.123456")),
        ("accrued_interest", Decimal("2.000002")),
        ("fees_outstanding", Decimal("3.200000")),
        ("total_outstanding", Decimal("106.223457")),
        ("source", LiabilityBalanceSource.provider),
        ("external_id", "other-external"),
        ("created_at", datetime(2026, 7, 28, 10, 21, 1, 456000)),
    ],
)
@pytest.mark.asyncio
async def test_existing_identity_with_any_physical_difference_is_conflict(
    field: str,
    value: object,
) -> None:
    writer, session, repository = _writer()
    repository.by_timestamp = _model(None, **{field: value})

    with pytest.raises(
        LiabilityBalanceWriteConflictError,
        match=r"^Liability balance conflicts with persisted state\.$",
    ):
        await writer.write(_command())

    assert repository.inserted is None
    assert "flush" not in repository.calls
    assert session.commit_count == 0
    assert session.rollback_count == 1


@pytest.mark.asyncio
async def test_timestamp_and_external_lookups_resolving_different_rows_conflict() -> None:
    writer, session, repository = _writer()
    repository.by_timestamp = _model()
    repository.by_external = _model(id="other-id")
    with pytest.raises(LiabilityBalanceWriteConflictError):
        await writer.write(_command())
    assert repository.inserted is None
    assert session.rollback_count == 1


@pytest.mark.asyncio
async def test_deterministic_primary_key_collision_conflicts_without_insert() -> None:
    writer, session, repository = _writer()
    repository.by_id = _model(effective_at=datetime(2026, 7, 1))
    with pytest.raises(LiabilityBalanceWriteConflictError):
        await writer.write(_command())
    assert repository.inserted is None
    assert session.rollback_count == 1


@pytest.mark.parametrize(
    "account",
    [
        None,
        _account(account_id="other-account"),
        _account(archived=True),
        _account(account_type=AccountType.bank),
        _account(account_type=AccountType.broker),
        _account(currency="EUR"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_locked_account_fails_without_observation(
    account: AccountModel | None,
) -> None:
    writer, session, repository = _writer()
    repository.account = account
    with pytest.raises(LiabilityBalanceWriteStateError):
        await writer.write(_command())
    assert repository.calls == [("account", "account-1")]
    assert repository.inserted is None
    assert session.rollback_count == 1


@pytest.mark.asyncio
async def test_active_transaction_is_rejected_without_nested_transaction() -> None:
    writer, session, repository = _writer()
    session.active = True
    with pytest.raises(LiabilityBalanceWriteStateError):
        await writer.write(_command())
    assert session.begin_count == 0
    assert repository.calls == []


@pytest.mark.asyncio
async def test_sqlalchemy_repository_and_flush_errors_map_to_state_and_roll_back() -> None:
    writer, session, repository = _writer()
    repository.account_error = SQLAlchemyError("load failed")
    with pytest.raises(LiabilityBalanceWriteStateError):
        await writer.write(_command())
    assert session.rollback_count == 1

    writer, session, repository = _writer()
    repository.flush_error = SQLAlchemyError("flush failed")
    with pytest.raises(LiabilityBalanceWriteStateError):
        await writer.write(_command())
    assert repository.inserted is not None
    assert session.commit_count == 0
    assert session.rollback_count == 1


@pytest.mark.asyncio
async def test_reload_mismatch_rolls_back_created_row() -> None:
    writer, session, repository = _writer()
    repository.reload_value = _model(currency="EUR")

    original_add = repository.add

    def add_without_replacing_reload(balance: LiabilityBalanceModel) -> None:
        original_reload = repository.reload_value
        original_add(balance)
        repository.reload_value = original_reload

    cast(Any, repository).add = add_without_replacing_reload
    with pytest.raises(LiabilityBalanceWriteStateError):
        await writer.write(_command())
    assert session.commit_count == 0
    assert session.rollback_count == 1


def test_result_and_command_contracts_are_immutable() -> None:
    command = _command()
    result = LiabilityBalanceWriteResult(
        balance_id="balance-1",
        account_id="account-1",
        effective_at=EFFECTIVE_AT,
        currency="CZK",
        total_outstanding=Decimal("1"),
        source=LiabilityBalanceSource.manual,
        disposition=LiabilityBalanceWriteDisposition.created,
    )
    with pytest.raises(FrozenInstanceError):
        cast(Any, command).currency = "EUR"
    with pytest.raises(FrozenInstanceError):
        cast(Any, result).currency = "EUR"
    assert replace(result, disposition=LiabilityBalanceWriteDisposition.replayed).balance_id == (
        result.balance_id
    )
