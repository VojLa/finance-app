from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import datetime
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ClauseElement

from app.api.routes import health as health_module
from app.config.settings import Settings
from app.main import create_app
from app.modules.snapshot_refresh.market_backed_models import (
    ExecuteMarketBackedSnapshotRefreshCommand,
)
from app.modules.snapshot_refresh.market_backed_service import MarketBackedSnapshotRefreshService
from app.modules.snapshot_refresh.scheduled_runner import ScheduledSnapshotRefreshRunner


class _Begin:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_args: object) -> None:
        return None


class _Session:
    def __init__(self, *, locked: bool = True, user_ids: Sequence[str] = ()) -> None:
        self.locked = locked
        self.user_ids = user_ids
        self.scalar_statements: list[object] = []
        self.scalars_statements: list[object] = []

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _Begin:
        return _Begin()

    async def scalar(self, _statement: object) -> bool:
        self.scalar_statements.append(_statement)
        return self.locked

    async def scalars(self, _statement: object) -> Sequence[str]:
        self.scalars_statements.append(_statement)
        return self.user_ids


class _SessionFactory:
    def __init__(self, lock_session: _Session) -> None:
        self.lock_session = lock_session

    def __call__(self) -> _Session:
        return self.lock_session


class _RefreshService:
    def __init__(
        self,
        commands: list[ExecuteMarketBackedSnapshotRefreshCommand],
        *,
        failed_users: set[str] | None = None,
    ) -> None:
        self.commands = commands
        self.failed_users = failed_users or set()

    async def execute(self, command: ExecuteMarketBackedSnapshotRefreshCommand) -> None:
        self.commands.append(command)
        if command.user_id in self.failed_users:
            raise RuntimeError("provider unavailable")


def _settings() -> Settings:
    return Settings(environment="test", database_url="postgresql://configured", _env_file=None)


def test_cycle_uses_minute_aligned_price_refresh_and_isolates_user_failures() -> None:
    commands: list[ExecuteMarketBackedSnapshotRefreshCommand] = []
    service = _RefreshService(commands, failed_users={"user-b"})
    runner = ScheduledSnapshotRefreshRunner(
        _SessionFactory(_Session(user_ids=("user-a", "user-b", "user-c"))),  # type: ignore[arg-type]
        settings=_settings(),
        clock=lambda: datetime(2026, 9, 3, 12, 5),
        refresh_service_factory=lambda _session, _settings: cast(
            MarketBackedSnapshotRefreshService, service
        ),
    )

    assert asyncio.run(runner.run_once()) is True
    assert [command.user_id for command in commands] == ["user-a", "user-b", "user-c"]
    for command in commands:
        assert command.snapshot_timestamp == datetime(2026, 9, 3, 12, 5)
        assert command.snapshot_timestamp.tzinfo is None
        assert command.granularity.value == "minute"
        assert command.source.value == "price_refresh"
        assert command.is_recalculated is False


def test_duplicate_process_cycle_lock_skips_refresh() -> None:
    commands: list[ExecuteMarketBackedSnapshotRefreshCommand] = []
    runner = ScheduledSnapshotRefreshRunner(
        _SessionFactory(_Session(locked=False, user_ids=("user-a",))),  # type: ignore[arg-type]
        settings=_settings(),
        clock=lambda: datetime(2026, 9, 3, 12, 5),
        refresh_service_factory=lambda _session, _settings: cast(
            MarketBackedSnapshotRefreshService, _RefreshService(commands)
        ),
    )

    assert asyncio.run(runner.run_once()) is False
    assert commands == []


def test_eligible_users_exclude_active_snapshot_series_jobs() -> None:
    session = _Session(user_ids=("user-a",))
    runner = ScheduledSnapshotRefreshRunner(
        _SessionFactory(session),  # type: ignore[arg-type]
        settings=_settings(),
    )

    assert asyncio.run(runner._eligible_user_ids(cast(AsyncSession, session))) == ("user-a",)
    statement = str(
        cast(ClauseElement, session.scalars_statements[0]).compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert '"SnapshotSeriesRebuildJob"' in statement
    assert "NOT (EXISTS" in statement
    assert "'queued', 'retry_wait', 'running'" in statement


def test_runner_stop_ends_waiting_loop_cleanly() -> None:
    runner = ScheduledSnapshotRefreshRunner(
        _SessionFactory(_Session(locked=False)),  # type: ignore[arg-type]
        settings=_settings(),
        interval_seconds=300,
    )

    async def exercise() -> None:
        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0)
        runner.stop()
        await asyncio.wait_for(task, timeout=0.2)

    asyncio.run(exercise())


def test_runner_propagates_cancellation_during_user_refresh() -> None:
    started = asyncio.Event()

    class BlockingService:
        async def execute(self, _command: ExecuteMarketBackedSnapshotRefreshCommand) -> None:
            started.set()
            await asyncio.Event().wait()

    runner = ScheduledSnapshotRefreshRunner(
        _SessionFactory(_Session(user_ids=("user-a",))),  # type: ignore[arg-type]
        settings=_settings(),
        clock=lambda: datetime(2026, 9, 3, 12, 5),
        refresh_service_factory=lambda _session, _settings: cast(
            MarketBackedSnapshotRefreshService, BlockingService()
        ),
    )

    async def exercise() -> None:
        task = asyncio.create_task(runner.run_once())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())


def test_lifespan_starts_and_stops_scheduled_refresh_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class FakeEngine:
        async def dispose(self) -> None:
            events.append("database_closed")

    class WaitingRunner:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.stopped = asyncio.Event()

        async def run(self) -> None:
            events.append("runner_started")
            await self.stopped.wait()
            events.append("runner_finished")

        def stop(self) -> None:
            events.append("runner_stopped")
            self.stopped.set()

    async def database_available(_database: object) -> bool:
        return True

    database = SimpleNamespace(engine=FakeEngine(), session_factory=object())
    monkeypatch.setattr("app.lifespan.create_database", lambda _settings: database)
    monkeypatch.setattr("app.lifespan.ScheduledSnapshotRefreshRunner", WaitingRunner)
    monkeypatch.setattr(health_module, "check_database", database_available)
    settings = Settings(
        environment="test",
        database_url="postgresql://configured",
        scheduled_snapshot_refresh_runner_enabled=True,
        scheduled_snapshot_refresh_shutdown_grace_seconds=0.1,
        _env_file=None,
    )

    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health/ready").json()["dependencies"] == {
            "database": "available",
            "portfolioHistoryRuntime": "disabled",
            "scheduledSnapshotRefreshRuntime": "available",
        }

    assert events == ["runner_started", "runner_stopped", "runner_finished", "database_closed"]
