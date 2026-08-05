from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import (
    ImportLogEvent,
    ImportLogLevel,
    ImportStatus,
    SnapshotGranularity,
    SnapshotSource,
)
from app.modules.holdings.models import HoldingRebuildResponse
from app.modules.holdings.orchestration import HoldingRebuildUnavailableError
from app.modules.imports.models import ImportSnapshotRefreshStatus
from app.modules.imports.post_processing_repository import (
    import_post_processing_audit_lock_id,
)
from app.modules.imports.post_processing_service import (
    ImportBatchPostProcessingService,
    canonical_import_snapshot_bucket,
)
from app.modules.imports.posting_service import (
    PostImportBatchCommand,
    PostImportBatchResult,
)
from app.modules.market_data.models import MarketEvidenceRefreshResult
from app.modules.net_worth.evidence_service import SelectedAccountSnapshotIdentity
from app.modules.net_worth.writer import NetWorthSnapshotWriteDisposition
from app.modules.snapshot_refresh.executor import (
    AccountSnapshotRefreshExecutionDisposition,
    ExecutedAccountSnapshotRefresh,
    ExecuteUserSnapshotRefreshResult,
)
from app.modules.snapshot_refresh.market_backed_models import (
    ExecuteMarketBackedSnapshotRefreshCommand,
    ExecuteMarketBackedSnapshotRefreshResult,
    MarketBackedSnapshotRefreshConflictError,
    MarketBackedSnapshotRefreshUnavailableError,
)
from app.modules.snapshot_refresh.plan import AccountSnapshotRefreshMode

COMPLETED_AT = datetime(2036, 7, 29, 14, 35, 27, 123000)
BUCKET = datetime(2036, 7, 29, 14, 35)


class _Transaction:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> None:
        self.session.calls.append("audit begin")
        self.session.active = True

    async def __aexit__(self, *_: object) -> None:
        self.session.calls.append("audit end")
        self.session.active = False


class _Session:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.active = False
        self.rollback = AsyncMock(side_effect=self._rollback)

    async def _rollback(self) -> None:
        self.calls.append("rollback")
        self.active = False

    def in_transaction(self) -> bool:
        return self.active

    def begin(self) -> _Transaction:
        return _Transaction(self)


class _AuditRepository:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.logs: dict[str, object] = {}

    async def acquire_audit_lock(self, log_id: str) -> None:
        self.calls.append("audit lock")

    async def load_log_for_update(self, log_id: str) -> object | None:
        self.calls.append("audit load")
        return self.logs.get(log_id)

    def add_log(self, log: object) -> None:
        self.calls.append("audit add")
        self.logs[cast(Any, log).id] = log

    async def flush(self) -> None:
        self.calls.append("audit flush")


def _principal(user_id: str = "user-a") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.test",
        name=user_id,
    )


def _command() -> PostImportBatchCommand:
    return PostImportBatchCommand(
        principal=_principal(),
        account_id="account-a",
        batch_id="batch-a",
    )


def _posting_result(
    *,
    rows_imported: int = 2,
    transactions: int = 1,
    investments: int = 1,
    replayed: bool = False,
) -> PostImportBatchResult:
    return PostImportBatchResult(
        batch_id="batch-a",
        status=ImportStatus.completed,
        rows_total=rows_imported,
        rows_imported=rows_imported,
        rows_skipped=0,
        completed_at=COMPLETED_AT,
        replayed=replayed,
        transaction_rows_imported=transactions,
        investment_event_rows_imported=investments,
    )


def _execution(
    account_id: str,
    disposition: AccountSnapshotRefreshExecutionDisposition,
) -> ExecutedAccountSnapshotRefresh:
    return ExecutedAccountSnapshotRefresh(
        account_id=account_id,
        snapshot_id=f"snapshot-{account_id}",
        mode=(
            AccountSnapshotRefreshMode.reuse_only
            if disposition is AccountSnapshotRefreshExecutionDisposition.reused
            else AccountSnapshotRefreshMode.refresh
        ),
        disposition=disposition,
    )


def _executor_result(
    *,
    disposition: NetWorthSnapshotWriteDisposition = NetWorthSnapshotWriteDisposition.created,
) -> ExecuteUserSnapshotRefreshResult:
    executions = (
        _execution("account-a", AccountSnapshotRefreshExecutionDisposition.created),
        _execution("account-b", AccountSnapshotRefreshExecutionDisposition.replayed),
        _execution("account-c", AccountSnapshotRefreshExecutionDisposition.reused),
    )
    return ExecuteUserSnapshotRefreshResult(
        user_id="user-a",
        snapshot_timestamp=BUCKET,
        granularity=SnapshotGranularity.minute,
        output_currency="EUR",
        source=SnapshotSource.import_event,
        calculation_version=1,
        account_snapshots=executions,
        required_account_snapshot_identities=tuple(
            SelectedAccountSnapshotIdentity(item.account_id, item.snapshot_id)
            for item in executions
        ),
        net_worth_snapshot_id="net-worth-a",
        net_worth_disposition=disposition,
        refresh_account_count=2,
        reuse_only_account_count=1,
        created_account_snapshot_count=1,
        replayed_account_snapshot_count=1,
        reused_account_snapshot_count=1,
        selected_account_snapshot_count=3,
    )


def _market_result() -> MarketEvidenceRefreshResult:
    return MarketEvidenceRefreshResult(
        user_id="user-a",
        snapshot_timestamp=BUCKET,
        output_currency="EUR",
        required_price_count=0,
        required_fx_count=0,
        price_ids=(),
        exchange_rate_ids=(),
        prices_created=0,
        prices_replayed=0,
        rates_created=0,
        rates_replayed=0,
    )


def _combined_result(
    snapshots: ExecuteUserSnapshotRefreshResult | None = None,
    *,
    market: MarketEvidenceRefreshResult | None = None,
) -> ExecuteMarketBackedSnapshotRefreshResult:
    return ExecuteMarketBackedSnapshotRefreshResult(
        market=market or _market_result(),
        snapshots=snapshots or _executor_result(),
    )


def _holding_result(*, replayed: bool = False) -> HoldingRebuildResponse:
    return HoldingRebuildResponse(
        account_id="account-a",
        created=0 if replayed else 1,
        updated=0,
        deleted=0,
        total=1,
        replayed=replayed,
        rebuilt_at=None if replayed else COMPLETED_AT,
    )


def _service(
    *,
    posting: object | None = None,
    holding: object | None = None,
    holding_error: Exception | None = None,
    executor: object | None = None,
    executor_error: Exception | None = None,
    combined: object | None = None,
) -> tuple[
    ImportBatchPostProcessingService,
    _Session,
    Mock,
    Mock,
    Mock,
    _AuditRepository,
]:
    session = _Session()
    calls = session.calls

    async def post_batch(_: object) -> object:
        calls.append("posting")
        session.active = False
        return posting if posting is not None else _posting_result()

    async def rebuild(_: object) -> object:
        calls.append("holding")
        session.active = False
        if holding_error is not None:
            raise holding_error
        return holding if holding is not None else _holding_result()

    async def execute(_: object) -> object:
        calls.append("market-backed")
        session.active = False
        if executor_error is not None:
            raise executor_error
        if combined is not None:
            return combined
        return _combined_result(cast(ExecuteUserSnapshotRefreshResult | None, executor))

    posting_factory = Mock(return_value=Mock(post_batch=AsyncMock(side_effect=post_batch)))
    holding_factory = Mock(return_value=Mock(rebuild=AsyncMock(side_effect=rebuild)))
    market_backed_service = Mock(execute=AsyncMock(side_effect=execute))
    repository = _AuditRepository(calls)
    service = ImportBatchPostProcessingService(
        cast(AsyncSession, session),
        market_backed_service=market_backed_service,
        posting_service_factory=posting_factory,
        holding_service_factory=holding_factory,
        repository_factory=Mock(return_value=repository),
    )
    return (
        service,
        session,
        posting_factory,
        holding_factory,
        market_backed_service,
        repository,
    )


def test_bucket_is_derived_from_completed_at() -> None:
    assert canonical_import_snapshot_bucket(COMPLETED_AT) == BUCKET


def test_audit_lock_scope_is_deterministic_and_signed_bigint_safe() -> None:
    first = import_post_processing_audit_lock_id("log-a")
    assert first == import_post_processing_audit_lock_id("log-a")
    assert first != import_post_processing_audit_lock_id("log-b")
    assert -(2**63) <= first < 2**63


@pytest.mark.parametrize(
    "command",
    [
        object(),
        PostImportBatchCommand(cast(Any, object()), "account-a", "batch-a"),
        PostImportBatchCommand(_principal(" "), "account-a", "batch-a"),
        PostImportBatchCommand(_principal(), "", "batch-a"),
        PostImportBatchCommand(_principal(), " account-a", "batch-a"),
        PostImportBatchCommand(_principal(), "account-a", "batch-a "),
    ],
)
async def test_invalid_command_fails_before_posting(command: object) -> None:
    service, _, posting_factory, _, _, _ = _service()
    with pytest.raises(RuntimeError):
        await service.post_batch(cast(Any, command))
    posting_factory.assert_not_called()


async def test_zero_import_is_not_required_without_post_processing() -> None:
    service, session, _, holding_factory, market_backed_service, repository = _service(
        posting=_posting_result(rows_imported=0, transactions=0, investments=0)
    )
    result = await service.post_batch(_command())
    assert result.snapshot_refresh_status is ImportSnapshotRefreshStatus.not_required
    holding_factory.assert_not_called()
    market_backed_service.execute.assert_not_awaited()
    assert repository.logs == {}
    assert session.calls == ["posting"]


async def test_investment_import_rebuilds_then_runs_market_backed_and_audits() -> None:
    service, session, _, holding_factory, market_backed_service, repository = _service()
    result = await service.post_batch(_command())
    assert result.snapshot_refresh_status is ImportSnapshotRefreshStatus.created
    holding_factory.assert_called_once()
    clock = holding_factory.call_args.args[1]
    assert clock() == COMPLETED_AT
    market_backed_service.execute.assert_awaited_once()
    combined_command = market_backed_service.execute.await_args.args[0]
    assert combined_command == ExecuteMarketBackedSnapshotRefreshCommand(
        user_id="user-a",
        snapshot_timestamp=BUCKET,
        granularity=SnapshotGranularity.minute,
        source=SnapshotSource.import_event,
        calculation_version=1,
        calculated_at=BUCKET,
        created_at=BUCKET,
        is_recalculated=False,
    )
    assert {cast(Any, log).event for log in repository.logs.values()} == {
        ImportLogEvent.holdings_recalculated,
        ImportLogEvent.snapshots_recalculated,
    }
    assert session.calls.index("posting") < session.calls.index("holding")
    assert session.calls.index("holding") < session.calls.index("market-backed")
    assert session.active is False


async def test_transaction_only_empty_market_plan_skips_holding_and_executes() -> None:
    service, _, _, holding_factory, market_backed_service, _ = _service(
        posting=_posting_result(rows_imported=1, transactions=1, investments=0)
    )
    result = await service.post_batch(_command())
    assert result.snapshot_refresh_status is ImportSnapshotRefreshStatus.created
    holding_factory.assert_not_called()
    market_backed_service.execute.assert_awaited_once()


async def test_replayed_batch_still_rebuilds_and_executes() -> None:
    service, _, _, holding_factory, market_backed_service, _ = _service(
        posting=_posting_result(replayed=True),
        holding=_holding_result(replayed=True),
        executor=_executor_result(disposition=NetWorthSnapshotWriteDisposition.replayed),
    )
    result = await service.post_batch(_command())
    assert result.replayed is True
    assert result.snapshot_refresh_status is ImportSnapshotRefreshStatus.replayed
    holding_factory.assert_called_once()
    market_backed_service.execute.assert_awaited_once()


async def test_holding_unavailable_preserves_import_result_and_skips_market() -> None:
    service, _, _, _, market_backed_service, repository = _service(
        holding_error=HoldingRebuildUnavailableError()
    )
    result = await service.post_batch(_command())
    assert result.status is ImportStatus.completed
    assert result.snapshot_refresh_status is ImportSnapshotRefreshStatus.unavailable
    market_backed_service.execute.assert_not_awaited()
    log = next(iter(repository.logs.values()))
    assert cast(Any, log).level is ImportLogLevel.warning
    assert cast(Any, log).event is ImportLogEvent.snapshot_validation_failed


@pytest.mark.parametrize(
    ("error", "status", "expected_audit_id"),
    [
        (
            MarketBackedSnapshotRefreshUnavailableError(),
            ImportSnapshotRefreshStatus.unavailable,
            "72c2de47-cf4b-501a-bf24-6d3868c8f5c9",
        ),
        (
            MarketBackedSnapshotRefreshConflictError(),
            ImportSnapshotRefreshStatus.conflict,
            "8d87167d-aa17-57fe-b3a5-bb829d0910e6",
        ),
    ],
)
async def test_known_snapshot_failure_is_http_success_status(
    error: Exception,
    status: ImportSnapshotRefreshStatus,
    expected_audit_id: str,
) -> None:
    service, _, _, _, _, repository = _service(executor_error=error)
    result = await service.post_batch(_command())
    assert result.snapshot_refresh_status is status
    failure_logs = {
        log_id: cast(Any, log)
        for log_id, log in repository.logs.items()
        if cast(Any, log).event is ImportLogEvent.snapshot_validation_failed
    }
    assert tuple(failure_logs) == (expected_audit_id,)
    assert failure_logs[expected_audit_id].level is ImportLogLevel.warning


async def test_unexpected_holding_and_market_backed_errors_propagate() -> None:
    holding_error = RuntimeError("holding infrastructure")
    service, _, _, _, _, _ = _service(holding_error=holding_error)
    with pytest.raises(RuntimeError, match="holding infrastructure"):
        await service.post_batch(_command())
    executor_error = RuntimeError("market-backed infrastructure")
    service, _, _, _, _, _ = _service(executor_error=executor_error)
    with pytest.raises(RuntimeError, match="market-backed infrastructure"):
        await service.post_batch(_command())


async def test_unexpected_market_backed_error_leak_becomes_runtime_error() -> None:
    service, session, _, _, _, _ = _service()

    async def execute(_: object) -> object:
        session.active = True
        raise RuntimeError("market-backed infrastructure")

    service.market_backed_service = Mock(execute=AsyncMock(side_effect=execute))
    with pytest.raises(RuntimeError, match="invalid state"):
        await service.post_batch(_command())
    session.rollback.assert_awaited_once()
    assert session.active is False


@pytest.mark.parametrize(
    "result",
    [
        object(),
        replace(_posting_result(), batch_id="other"),
        replace(_posting_result(), rows_total=3),
        replace(_posting_result(), transaction_rows_imported=True),
        replace(_posting_result(), completed_at=datetime(2036, 1, 1, 0, 0, 0, 1)),
    ],
)
async def test_malformed_posting_result_is_programming_error(result: object) -> None:
    service, _, _, holding_factory, market_backed_service, _ = _service(posting=result)
    with pytest.raises(RuntimeError):
        await service.post_batch(_command())
    holding_factory.assert_not_called()
    market_backed_service.execute.assert_not_awaited()


@pytest.mark.parametrize(
    "result",
    [
        object(),
        replace(_executor_result(), user_id="other"),
        replace(_executor_result(), snapshot_timestamp=datetime(2036, 7, 29, 14, 36)),
        replace(_executor_result(), source=SnapshotSource.manual_recalculation),
        replace(_executor_result(), output_currency="eur"),
        replace(_executor_result(), selected_account_snapshot_count=True),
        replace(_executor_result(), required_account_snapshot_identities=()),
    ],
)
async def test_malformed_snapshot_result_is_programming_error(result: object) -> None:
    service, _, _, _, _, _ = _service(executor=result)
    with pytest.raises(RuntimeError):
        await service.post_batch(_command())


async def test_wrong_combined_result_type_is_programming_error() -> None:
    service, _, _, _, market_backed_service, repository = _service(combined=object())

    with pytest.raises(RuntimeError, match="invalid state"):
        await service.post_batch(_command())

    market_backed_service.execute.assert_awaited_once()
    assert repository.logs == {}


async def test_market_metadata_never_enters_response_or_audit() -> None:
    market = replace(
        _market_result(),
        required_price_count=1,
        required_fx_count=1,
        price_ids=("sensitive-price-id",),
        exchange_rate_ids=("sensitive-rate-id",),
        prices_created=1,
        rates_created=1,
    )
    service, _, _, _, _, repository = _service(combined=_combined_result(market=market))

    result = await service.post_batch(_command())

    for field in (
        "market",
        "price_ids",
        "exchange_rate_ids",
        "provider",
        "required_price_count",
        "required_fx_count",
    ):
        assert not hasattr(result, field)
    serialized_audits = repr(tuple(repository.logs.values()))
    assert "sensitive-price-id" not in serialized_audits
    assert "sensitive-rate-id" not in serialized_audits


async def test_dependency_transaction_leak_is_rolled_back() -> None:
    service, session, _, _, market_backed_service, _ = _service()

    async def leaking_post(_: object) -> PostImportBatchResult:
        session.active = True
        return _posting_result()

    service.posting_service_factory = Mock(
        return_value=Mock(post_batch=AsyncMock(side_effect=leaking_post))
    )
    with pytest.raises(RuntimeError, match="Import posting dependency"):
        await service.post_batch(_command())
    session.rollback.assert_awaited_once()
    market_backed_service.execute.assert_not_awaited()


async def test_commands_and_results_are_immutable() -> None:
    command = _command()
    posting = _posting_result()
    with pytest.raises(FrozenInstanceError):
        command.account_id = "other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        posting.rows_imported = 0  # type: ignore[misc]
