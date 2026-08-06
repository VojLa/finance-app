from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.enums import SnapshotGranularity, SnapshotSource
from app.modules.portfolio_history.models import (
    PersistedPortfolioHistoryPoint,
    PortfolioHistoryRange,
)
from app.modules.portfolio_history.repository import PersistedPortfolioHistoryUser
from app.modules.portfolio_history.service import (
    PortfolioHistoryUnavailableError,
    ReadPortfolioHistoryCommand,
    ReadPortfolioHistoryResult,
    SnapshotBackedPortfolioHistoryService,
)

END = datetime(2026, 8, 1, 10, 15, 0, 123000)
MODULE_DIR = Path(__file__).parents[1] / "app" / "modules" / "portfolio_history"


def _principal(user_id: str = "user-a") -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user_id,
        email=f"{user_id}@example.test",
        name=user_id,
    )


def _point(
    timestamp: datetime = END,
    *,
    snapshot_id: str = "snapshot-a",
    user_id: str = "user-a",
    currency: str = "EUR",
) -> PersistedPortfolioHistoryPoint:
    return PersistedPortfolioHistoryPoint(
        snapshot_id=snapshot_id,
        user_id=user_id,
        timestamp=timestamp,
        granularity=SnapshotGranularity.minute,
        source=SnapshotSource.scheduled,
        currency=currency,
        cash_value=Decimal("10.000000"),
        portfolio_value=Decimal("20.000000"),
        liabilities_value=Decimal("5.000000"),
        total_net_worth=Decimal("25.000000"),
        calculation_version=1,
    )


class _Transaction:
    def __init__(self, session: _Session) -> None:
        self.session = session

    async def __aenter__(self) -> _Transaction:
        assert not self.session.active
        self.session.active = True
        self.session.events.append("begin")
        return self

    async def __aexit__(self, *args: object) -> None:
        self.session.events.append("rollback-read" if args[0] else "commit-read")
        if not self.session.leave_active:
            self.session.active = False


class _Session:
    def __init__(self, *, leave_active: bool = False) -> None:
        self.active = True
        self.leave_active = leave_active
        self.events: list[str] = []
        self.rollback_count = 0
        self.commit_count = 0

    def in_transaction(self) -> bool:
        return self.active

    async def commit(self) -> None:
        self.commit_count += 1
        self.events.append("commit-auth")
        self.active = False

    async def rollback(self) -> None:
        self.rollback_count += 1
        self.events.append("rollback")
        self.active = False

    def begin(self) -> _Transaction:
        return _Transaction(self)

    async def execute(self, statement: object) -> None:
        self.events.append(str(statement))


class _Repository:
    def __init__(
        self,
        session: _Session,
        *,
        user: object = PersistedPortfolioHistoryUser("user-a", "EUR"),
        points: object = (_point(),),
        failure: BaseException | None = None,
    ) -> None:
        self.session = session
        self.user = user
        self.points = points
        self.failure = failure
        self.calls: list[object] = []

    async def load_user(self, user_id: str) -> PersistedPortfolioHistoryUser | None:
        self.calls.append(("user", user_id, self.session.in_transaction()))
        if self.failure:
            raise self.failure
        return cast(PersistedPortfolioHistoryUser | None, self.user)

    async def load_candidate_points(
        self,
        *,
        user_id: str,
        currency: str,
        start: datetime | None,
        end: datetime,
    ) -> tuple[PersistedPortfolioHistoryPoint, ...]:
        self.calls.append(("points", user_id, currency, start, end, self.session.in_transaction()))
        return cast(tuple[PersistedPortfolioHistoryPoint, ...], self.points)


def _service(
    *,
    clock: object = END,
    user: object = PersistedPortfolioHistoryUser("user-a", "EUR"),
    points: object = (_point(),),
    failure: BaseException | None = None,
    leave_active: bool = False,
) -> tuple[SnapshotBackedPortfolioHistoryService, _Session, _Repository, list[int]]:
    session = _Session(leave_active=leave_active)
    repository = _Repository(session, user=user, points=points, failure=failure)
    clock_reads: list[int] = []

    def read_clock() -> datetime:
        clock_reads.append(1)
        return cast(datetime, clock)

    service = SnapshotBackedPortfolioHistoryService(
        cast(AsyncSession, session),
        clock=read_clock,
        repository_factory=lambda _session: repository,
    )
    return service, session, repository, clock_reads


@pytest.mark.asyncio
async def test_service_reads_clock_once_and_owns_read_only_transaction() -> None:
    service, session, repository, clock_reads = _service()

    result = await service.read(
        ReadPortfolioHistoryCommand(_principal(), PortfolioHistoryRange.one_year)
    )

    assert clock_reads == [1]
    assert session.events[:3] == [
        "commit-auth",
        "begin",
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
    ]
    assert repository.calls == [
        ("user", "user-a", True),
        (
            "points",
            "user-a",
            "EUR",
            datetime(2025, 8, 1, 10, 15, 0, 123000),
            END,
            True,
        ),
    ]
    assert result.history.currency == "EUR"
    assert result.selected_snapshot_ids == ("snapshot-a",)
    assert not session.in_transaction()


@pytest.mark.asyncio
async def test_empty_history_is_valid_and_all_has_no_lower_bound() -> None:
    service, _, repository, _ = _service(points=())
    result = await service.read(
        ReadPortfolioHistoryCommand(_principal(), PortfolioHistoryRange.all)
    )

    assert result.history.points == ()
    assert cast(tuple[object, ...], repository.calls[1])[3] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "clock",
    [END.replace(tzinfo=UTC), END.replace(microsecond=123456), object()],
)
async def test_invalid_clock_fails_before_repository(clock: object) -> None:
    service, session, repository, clock_reads = _service(clock=clock)

    with pytest.raises(PortfolioHistoryUnavailableError):
        await service.read(
            ReadPortfolioHistoryCommand(_principal(), PortfolioHistoryRange.one_year)
        )

    assert clock_reads == [1]
    assert repository.calls == []
    assert session.rollback_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    [
        object(),
        ReadPortfolioHistoryCommand(_principal(""), PortfolioHistoryRange.one_year),
        ReadPortfolioHistoryCommand(_principal(), cast(PortfolioHistoryRange, "1Y")),
    ],
)
async def test_invalid_command_fails_closed(command: object) -> None:
    service, session, repository, _ = _service()
    with pytest.raises(PortfolioHistoryUnavailableError):
        await service.read(command)
    assert repository.calls == []
    assert session.rollback_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user",
    [
        None,
        object(),
        PersistedPortfolioHistoryUser("user-b", "EUR"),
        PersistedPortfolioHistoryUser("user-a", "eur"),
    ],
)
async def test_missing_or_corrupt_user_is_generic_unavailable(user: object) -> None:
    service, session, _, _ = _service(user=user)
    with pytest.raises(PortfolioHistoryUnavailableError):
        await service.read(
            ReadPortfolioHistoryCommand(_principal(), PortfolioHistoryRange.one_year)
        )
    assert not session.in_transaction()


@pytest.mark.asyncio
async def test_repository_sql_failure_is_generic_unavailable() -> None:
    service, session, _, _ = _service(failure=SQLAlchemyError("secret SQL"))
    with pytest.raises(PortfolioHistoryUnavailableError) as caught:
        await service.read(
            ReadPortfolioHistoryCommand(_principal(), PortfolioHistoryRange.one_year)
        )
    assert caught.value.message == "Portfolio history is unavailable."
    assert "secret" not in caught.value.message
    assert not session.in_transaction()


@pytest.mark.asyncio
async def test_dependency_transaction_leak_is_rolled_back_and_unavailable() -> None:
    service, session, _, _ = _service(leave_active=True)
    with pytest.raises(PortfolioHistoryUnavailableError):
        await service.read(
            ReadPortfolioHistoryCommand(_principal(), PortfolioHistoryRange.one_year)
        )
    assert session.rollback_count == 1
    assert not session.in_transaction()


@pytest.mark.asyncio
async def test_unexpected_programming_error_propagates_when_session_is_idle() -> None:
    service, session, _, _ = _service(failure=RuntimeError("programmer"))
    with pytest.raises(RuntimeError, match="programmer"):
        await service.read(
            ReadPortfolioHistoryCommand(_principal(), PortfolioHistoryRange.one_year)
        )
    assert not session.in_transaction()


def test_command_and_result_are_immutable() -> None:
    command = ReadPortfolioHistoryCommand(_principal(), PortfolioHistoryRange.one_year)
    service_result = ReadPortfolioHistoryResult  # static constructor guard
    with pytest.raises(FrozenInstanceError):
        command.range = PortfolioHistoryRange.all  # type: ignore[misc]
    assert service_result is ReadPortfolioHistoryResult


def test_production_module_has_only_approved_read_dependencies() -> None:
    forbidden_import_fragments = {
        "transactions",
        "holdings",
        "market_data",
        "prices",
        "fx",
        "imports",
    }
    forbidden_source = (
        "httpx",
        "requests",
        "refresh",
        "writer",
        "create_task",
        "background",
        "cache",
        "prisma",
        "FOR UPDATE",
        "advisory",
        "INSERT",
        "UPDATE",
        "DELETE",
    )
    for path in MODULE_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        modules = {
            node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        assert not any(
            fragment in module for module in modules for fragment in forbidden_import_fragments
        )
        lowered = source.lower()
        for value in forbidden_source:
            if value == "refresh":
                assert "snapshot_refresh" not in lowered
            elif value == "writer":
                assert "writer" not in lowered
            else:
                assert value.lower() not in lowered
