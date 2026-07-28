from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.db.models.snapshots import NetWorthSnapshotModel
from app.modules.net_worth.evidence_service import (
    BuildNetWorthEvidenceCommand,
    CompleteNetWorthEvidence,
    NetWorthEvidenceStateError,
    SelectedAccountSnapshotIdentity,
)
from app.modules.net_worth.persistence_projection import (
    CanonicalNetWorthJsonObject,
    ExpectedNetWorthSnapshotPersistence,
    ExpectedNetWorthSnapshotRow,
    NetWorthSnapshotPersistenceAudit,
    NetWorthSnapshotPersistenceMetadata,
    NetWorthSnapshotPersistenceProjectionError,
)
from app.modules.net_worth.writer import (
    NetWorthSnapshotWriteConflictError,
    NetWorthSnapshotWriteDisposition,
    NetWorthSnapshotWriter,
    NetWorthSnapshotWriteResult,
    NetWorthSnapshotWriteStateError,
    WriteNetWorthSnapshotCommand,
)
from app.modules.net_worth.writer_repository import (
    advisory_lock_id,
    net_worth_snapshot_lock_scope,
)

SNAPSHOT_AT = datetime(2032, 8, 2)
CALCULATED_AT = datetime(2032, 8, 2, 1, 2, 3, 456000)
CREATED_AT = datetime(2032, 8, 2, 1, 2, 4, 567000)


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


class _DriverError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("controlled database failure")
        self.sqlstate = sqlstate


class _SqlStateError(SQLAlchemyError):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("controlled database failure")
        self.orig = _DriverError(sqlstate)


class _Evidence:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.commands: list[BuildNetWorthEvidenceCommand] = []
        self.value = cast(CompleteNetWorthEvidence, object())
        self.error: Exception | None = None

    async def build(
        self,
        command: BuildNetWorthEvidenceCommand,
    ) -> CompleteNetWorthEvidence:
        self.calls.append("evidence")
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return self.value


class _Repository:
    def __init__(
        self,
        calls: list[str],
        projection: ExpectedNetWorthSnapshotPersistence,
    ) -> None:
        self.calls = calls
        self.projection = projection
        self.existing: NetWorthSnapshotModel | None = None
        self.id_conflict: NetWorthSnapshotModel | None = None
        self.inserted: NetWorthSnapshotModel | None = None
        self.reload_mismatch = False
        self.flush_errors: list[SQLAlchemyError] = []

    async def set_transaction_serializable(self) -> None:
        self.calls.append("serializable")

    async def acquire_snapshot_lock(self, **_: object) -> None:
        self.calls.append("lock")

    async def load_existing_snapshot(self, **_: object) -> NetWorthSnapshotModel | None:
        self.calls.append("existing")
        return self.existing

    async def load_snapshot_by_id(self, snapshot_id: str) -> NetWorthSnapshotModel | None:
        self.calls.append("id")
        return self.id_conflict

    def add_snapshot(self, snapshot: NetWorthSnapshotModel) -> None:
        self.calls.append("add")
        self.inserted = snapshot

    async def flush(self) -> None:
        self.calls.append("flush")
        if self.flush_errors:
            error = self.flush_errors.pop(0)
            if getattr(getattr(error, "orig", None), "sqlstate", None) == "23505":
                self.existing = self.inserted
            raise error

    async def reload_snapshot(self, snapshot_id: str) -> NetWorthSnapshotModel | None:
        self.calls.append("reload")
        if self.reload_mismatch:
            assert self.inserted is not None
            self.inserted.total_net_worth = Decimal("999")
        return self.inserted


class _Projector:
    def __init__(
        self,
        calls: list[str],
        projection: ExpectedNetWorthSnapshotPersistence,
    ) -> None:
        self.calls = calls
        self.projection = projection
        self.inputs: list[tuple[CompleteNetWorthEvidence, NetWorthSnapshotPersistenceMetadata]] = []
        self.error: Exception | None = None

    def __call__(
        self,
        evidence: CompleteNetWorthEvidence,
        metadata: NetWorthSnapshotPersistenceMetadata,
    ) -> ExpectedNetWorthSnapshotPersistence:
        self.calls.append("projection")
        self.inputs.append((evidence, metadata))
        if self.error is not None:
            raise self.error
        return self.projection


def _command(**changes: object) -> WriteNetWorthSnapshotCommand:
    values: dict[str, object] = {
        "user_id": "user-1",
        "snapshot_timestamp": SNAPSHOT_AT,
        "granularity": SnapshotGranularity.day,
        "currency": "CZK",
        "source": SnapshotSource.manual_recalculation,
        "calculation_version": 1,
        "calculated_at": CALCULATED_AT,
        "created_at": CREATED_AT,
        "is_recalculated": True,
    }
    values.update(changes)
    return WriteNetWorthSnapshotCommand(**cast(Any, values))


def _json(value: str) -> CanonicalNetWorthJsonObject:
    return CanonicalNetWorthJsonObject((("CZK", value),))


def _projection() -> ExpectedNetWorthSnapshotPersistence:
    return ExpectedNetWorthSnapshotPersistence(
        snapshot=ExpectedNetWorthSnapshotRow(
            id="snapshot-1",
            user_id="user-1",
            timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.day,
            source=SnapshotSource.manual_recalculation,
            currency="CZK",
            cash_value=Decimal("100"),
            portfolio_value=Decimal("400"),
            liabilities_value=Decimal("250"),
            total_net_worth=Decimal("250"),
            is_recalculated=True,
            calculated_at=CALCULATED_AT,
            calculation_version=1,
            created_at=CREATED_AT,
            cash_value_by_currency=_json("100.000000"),
            portfolio_value_by_currency=_json("400.0000000000"),
            liabilities_value_by_currency=_json("250.000000"),
            total_net_worth_by_currency=_json("250.0000000000"),
            exchange_rates=None,
        ),
        audit=NetWorthSnapshotPersistenceAudit(
            selected_account_ids=("account-1", "account-2"),
            selected_account_snapshot_ids=("source-1", "source-2"),
            selected_identities=(
                SelectedAccountSnapshotIdentity("account-1", "source-1"),
                SelectedAccountSnapshotIdentity("account-2", "source-2"),
            ),
        ),
    )


def _model(
    projection: ExpectedNetWorthSnapshotPersistence | None = None,
) -> NetWorthSnapshotModel:
    value = projection or _projection()
    return NetWorthSnapshotModel(**value.snapshot.model_values())


def _writer(
    session: _Session | None = None,
    projection: ExpectedNetWorthSnapshotPersistence | None = None,
) -> tuple[
    NetWorthSnapshotWriter,
    _Session,
    _Repository,
    _Evidence,
    _Projector,
    list[str],
]:
    active_session = session or _Session()
    expected = projection or _projection()
    calls: list[str] = []
    repository = _Repository(calls, expected)
    evidence = _Evidence(calls)
    projector = _Projector(calls, expected)
    writer = NetWorthSnapshotWriter(
        cast(Any, active_session),
        repository=repository,
        evidence_service=evidence,
        projection_builder=projector,
    )
    return writer, active_session, repository, evidence, projector, calls


@pytest.mark.asyncio
async def test_created_path_owns_one_transaction_and_exact_operation_order() -> None:
    writer, session, repository, evidence, projector, calls = _writer()

    result = await writer.write(_command())

    assert result == NetWorthSnapshotWriteResult(
        snapshot_id="snapshot-1",
        user_id="user-1",
        disposition=NetWorthSnapshotWriteDisposition.created,
        timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        currency="CZK",
        account_count=2,
        selected_account_snapshot_count=2,
    )
    assert calls == [
        "serializable",
        "lock",
        "evidence",
        "projection",
        "existing",
        "id",
        "add",
        "flush",
        "reload",
    ]
    assert session.begin_count == session.commit_count == 1
    assert session.rollback_count == 0
    assert evidence.commands == [
        BuildNetWorthEvidenceCommand(
            user_id="user-1",
            timestamp=SNAPSHOT_AT,
            granularity=SnapshotGranularity.day,
            currency="CZK",
            calculation_version=1,
        )
    ]
    assert projector.inputs[0][1] == NetWorthSnapshotPersistenceMetadata(
        source=SnapshotSource.manual_recalculation,
        calculated_at=CALCULATED_AT,
        created_at=CREATED_AT,
        is_recalculated=True,
    )
    assert repository.inserted is not None
    assert repository.inserted.total_net_worth == Decimal("250")


@pytest.mark.asyncio
async def test_exact_replay_is_read_only() -> None:
    writer, session, repository, _, _, calls = _writer()
    repository.existing = _model()

    result = await writer.write(_command())

    assert result.disposition is NetWorthSnapshotWriteDisposition.replayed
    assert calls == ["serializable", "lock", "evidence", "projection", "existing"]
    assert repository.inserted is None
    assert session.commit_count == 1
    assert session.rollback_count == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "different-id"),
        ("user_id", "user-2"),
        ("timestamp", SNAPSHOT_AT + timedelta(days=1)),
        ("granularity", SnapshotGranularity.hour),
        ("source", SnapshotSource.scheduled),
        ("currency", "USD"),
        ("cash_value", Decimal("101")),
        ("portfolio_value", Decimal("401")),
        ("liabilities_value", Decimal("251")),
        ("total_net_worth", Decimal("249")),
        ("is_recalculated", False),
        ("calculated_at", CALCULATED_AT + timedelta(milliseconds=1)),
        ("calculation_version", 2),
        ("created_at", CREATED_AT + timedelta(milliseconds=1)),
        ("cash_value_by_currency", {}),
        ("portfolio_value_by_currency", None),
        ("liabilities_value_by_currency", {}),
        ("total_net_worth_by_currency", {}),
        ("exchange_rates", {}),
    ],
)
@pytest.mark.asyncio
async def test_every_physical_field_mismatch_is_conflict(
    field: str,
    value: object,
) -> None:
    writer, session, repository, _, _, _ = _writer()
    repository.existing = _model()
    setattr(repository.existing, field, value)

    with pytest.raises(
        NetWorthSnapshotWriteConflictError,
        match=r"^Net-worth snapshot conflicts with persisted state\.$",
    ):
        await writer.write(_command())

    assert repository.inserted is None
    assert session.commit_count == 0
    assert session.rollback_count == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"user_id": ""},
        {"user_id": " user-1"},
        {"snapshot_timestamp": SNAPSHOT_AT.replace(tzinfo=UTC)},
        {"snapshot_timestamp": SNAPSHOT_AT.replace(microsecond=1000)},
        {"granularity": "day"},
        {"currency": "czk"},
        {"currency": "EURO"},
        {"source": "manual_recalculation"},
        {"calculation_version": 0},
        {"calculation_version": True},
        {"calculation_version": 2_147_483_648},
        {"calculated_at": CALCULATED_AT.replace(tzinfo=UTC)},
        {"created_at": CREATED_AT.replace(microsecond=567001)},
        {"is_recalculated": False},
    ],
)
@pytest.mark.asyncio
async def test_invalid_commands_fail_before_transaction(changes: dict[str, object]) -> None:
    writer, session, _, evidence, projector, calls = _writer()

    with pytest.raises(
        NetWorthSnapshotWriteStateError,
        match=r"^Net-worth snapshot could not be persisted\.$",
    ):
        await writer.write(_command(**changes))

    assert session.begin_count == session.commit_count == session.rollback_count == 0
    assert evidence.commands == []
    assert projector.inputs == []
    assert calls == []


@pytest.mark.asyncio
async def test_wrong_command_runtime_type_fails_before_transaction() -> None:
    writer, session, _, _, _, calls = _writer()

    with pytest.raises(NetWorthSnapshotWriteStateError):
        await writer.write(cast(Any, object()))

    assert session.begin_count == 0
    assert calls == []


@pytest.mark.asyncio
async def test_active_caller_transaction_is_rejected() -> None:
    session = _Session()
    session.active = True
    writer, _, _, _, _, calls = _writer(session)

    with pytest.raises(NetWorthSnapshotWriteStateError):
        await writer.write(_command())

    assert session.begin_count == session.commit_count == session.rollback_count == 0
    assert calls == []


@pytest.mark.parametrize(
    "projection",
    [
        replace(
            _projection(),
            snapshot=replace(_projection().snapshot, user_id="other"),
        ),
        replace(
            _projection(),
            snapshot=replace(
                _projection().snapshot,
                timestamp=SNAPSHOT_AT + timedelta(days=1),
            ),
        ),
        replace(
            _projection(),
            snapshot=replace(_projection().snapshot, currency="USD"),
        ),
        replace(
            _projection(),
            snapshot=replace(
                _projection().snapshot,
                source=SnapshotSource.scheduled,
            ),
        ),
        replace(
            _projection(),
            snapshot=replace(
                _projection().snapshot,
                calculated_at=CALCULATED_AT + timedelta(milliseconds=1),
            ),
        ),
        replace(_projection(), audit=cast(Any, object())),
        replace(
            _projection(),
            audit=replace(
                _projection().audit,
                selected_account_snapshot_ids=("source-1",),
            ),
        ),
    ],
)
@pytest.mark.asyncio
async def test_projection_identity_or_audit_mismatch_fails_closed(
    projection: ExpectedNetWorthSnapshotPersistence,
) -> None:
    writer, session, repository, _, _, _ = _writer(projection=projection)

    with pytest.raises(NetWorthSnapshotWriteStateError):
        await writer.write(_command())

    assert repository.inserted is None
    assert session.rollback_count == 1


@pytest.mark.asyncio
async def test_wrong_projection_runtime_type_fails_closed() -> None:
    writer, session, repository, _, projector, _ = _writer()
    projector.projection = cast(Any, object())

    with pytest.raises(NetWorthSnapshotWriteStateError):
        await writer.write(_command())

    assert repository.inserted is None
    assert session.rollback_count == 1


@pytest.mark.asyncio
async def test_deterministic_id_collision_is_conflict() -> None:
    writer, session, repository, _, _, calls = _writer()
    repository.id_conflict = _model()

    with pytest.raises(NetWorthSnapshotWriteConflictError):
        await writer.write(_command())

    assert calls[-1] == "id"
    assert repository.inserted is None
    assert session.rollback_count == 1


@pytest.mark.parametrize("sqlstate", ["40001", "40P01", "23505"])
@pytest.mark.asyncio
async def test_retryable_database_errors_restart_complete_transaction(
    sqlstate: str,
) -> None:
    writer, session, repository, evidence, projector, calls = _writer()
    repository.flush_errors = [_SqlStateError(sqlstate)]

    result = await writer.write(_command())

    assert result.disposition is (
        NetWorthSnapshotWriteDisposition.replayed
        if sqlstate == "23505"
        else NetWorthSnapshotWriteDisposition.created
    )
    assert session.begin_count == 2
    assert session.rollback_count == 1
    assert session.commit_count == 1
    assert len(evidence.commands) == 2
    assert len(projector.inputs) == 2
    assert calls.count("serializable") == calls.count("lock") == 2


@pytest.mark.asyncio
async def test_retry_budget_is_bounded_to_three_complete_attempts() -> None:
    writer, session, repository, evidence, projector, _ = _writer()
    repository.flush_errors = [_SqlStateError("40001") for _ in range(3)]

    with pytest.raises(NetWorthSnapshotWriteStateError) as caught:
        await writer.write(_command())

    assert isinstance(caught.value.__cause__, SQLAlchemyError)
    assert session.begin_count == session.rollback_count == 3
    assert session.commit_count == 0
    assert len(evidence.commands) == len(projector.inputs) == 3


@pytest.mark.asyncio
async def test_nonretryable_database_error_has_one_attempt() -> None:
    writer, session, repository, evidence, projector, _ = _writer()
    repository.flush_errors = [_SqlStateError("22003")]

    with pytest.raises(NetWorthSnapshotWriteStateError):
        await writer.write(_command())

    assert session.begin_count == session.rollback_count == 1
    assert len(evidence.commands) == len(projector.inputs) == 1


@pytest.mark.parametrize(
    "error",
    [
        NetWorthEvidenceStateError(),
        NetWorthSnapshotPersistenceProjectionError(),
    ],
)
@pytest.mark.asyncio
async def test_domain_errors_are_not_retried(error: Exception) -> None:
    writer, session, repository, evidence, projector, _ = _writer()
    if isinstance(error, NetWorthEvidenceStateError):
        evidence.error = error
    else:
        projector.error = error

    with pytest.raises(type(error)):
        await writer.write(_command())

    assert session.begin_count == session.rollback_count == 1
    assert repository.inserted is None


@pytest.mark.asyncio
async def test_reload_mismatch_rolls_back_created_row() -> None:
    writer, session, repository, _, _, _ = _writer()
    repository.reload_mismatch = True

    with pytest.raises(NetWorthSnapshotWriteStateError):
        await writer.write(_command())

    assert repository.inserted is not None
    assert session.commit_count == 0
    assert session.rollback_count == 1


def test_command_result_and_projection_contracts_are_frozen() -> None:
    command = _command()
    result = NetWorthSnapshotWriteResult(
        snapshot_id="snapshot-1",
        user_id="user-1",
        disposition=NetWorthSnapshotWriteDisposition.created,
        timestamp=SNAPSHOT_AT,
        granularity=SnapshotGranularity.day,
        currency="CZK",
        account_count=2,
        selected_account_snapshot_count=2,
    )

    with pytest.raises(FrozenInstanceError):
        command.__setattr__("user_id", "changed")
    with pytest.raises(FrozenInstanceError):
        result.__setattr__("snapshot_id", "changed")


def test_advisory_lock_scope_and_hash_are_stable_and_namespaced() -> None:
    scope = net_worth_snapshot_lock_scope(
        user_id="user-1",
        timestamp=SNAPSHOT_AT,
        currency="CZK",
        granularity=SnapshotGranularity.day,
    )

    assert scope.split("\0") == [
        "net_worth:snapshot",
        "user-1",
        "2032-08-02T00:00:00.000",
        "CZK",
        "day",
    ]
    assert advisory_lock_id(scope) == advisory_lock_id(scope)
    assert -(2**63) <= advisory_lock_id(scope) < 2**63
