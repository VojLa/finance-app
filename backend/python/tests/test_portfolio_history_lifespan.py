from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.routes import health as health_module
from app.config.settings import Settings
from app.lifespan import _shutdown_runner
from app.main import create_app


class _Engine:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def dispose(self) -> None:
        self.events.append("database_closed")


class _Database:
    def __init__(self, events: list[str]) -> None:
        self.engine = _Engine(events)
        self.session_factory = object()


class _WaitingRunner:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events
        self.stopped = asyncio.Event()

    async def run(self) -> None:
        self.events.append(f"{self.name}_started")
        await self.stopped.wait()
        self.events.append(f"{self.name}_finished")

    def stop(self) -> None:
        self.events.append(f"{self.name}_stop")
        self.stopped.set()


def _settings() -> Settings:
    return Settings(
        environment="test",
        database_url="postgresql://configured",
        portfolio_history_runtime_enabled=True,
        portfolio_history_shutdown_grace_seconds=0.1,
        _env_file=None,
    )


def test_enabled_history_runtime_starts_atomically_and_stops_scheduler_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    worker = _WaitingRunner("worker", events)
    scheduler = _WaitingRunner("scheduler", events)

    async def compose(*_args: object, **_kwargs: object) -> object:
        events.append("runtime_composed")
        return SimpleNamespace(worker=worker, scheduler=scheduler)

    monkeypatch.setattr("app.lifespan.create_database", lambda _settings: _Database(events))
    monkeypatch.setattr("app.lifespan.create_portfolio_history_runtime", compose)

    app = create_app(_settings())
    with TestClient(app):
        assert app.state.portfolio_history_runtime.worker is worker
        assert len(app.state.portfolio_history_runtime_tasks) == 2

    assert events == [
        "runtime_composed",
        "worker_started",
        "scheduler_started",
        "scheduler_stop",
        "scheduler_finished",
        "worker_stop",
        "worker_finished",
        "database_closed",
    ]


def test_history_runtime_composition_failure_closes_database_without_starting_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    async def fail(*_args: object, **_kwargs: object) -> object:
        events.append("composition_failed")
        raise RuntimeError("history graph invalid")

    monkeypatch.setattr("app.lifespan.create_database", lambda _settings: _Database(events))
    monkeypatch.setattr("app.lifespan.create_portfolio_history_runtime", fail)

    with pytest.raises(RuntimeError, match="history graph invalid"):
        with TestClient(create_app(_settings())):
            pass

    assert events == ["composition_failed", "database_closed"]


def test_failed_scheduler_makes_readiness_unavailable_and_does_not_skip_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    worker = _WaitingRunner("worker", events)

    class FailedScheduler:
        async def run(self) -> None:
            events.append("scheduler_started")
            raise RuntimeError("scheduler failed")

        def stop(self) -> None:
            events.append("scheduler_stop")

    async def compose(*_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(worker=worker, scheduler=FailedScheduler())

    async def database_available(_database: object) -> bool:
        return True

    monkeypatch.setattr("app.lifespan.create_database", lambda _settings: _Database(events))
    monkeypatch.setattr("app.lifespan.create_portfolio_history_runtime", compose)
    monkeypatch.setattr(health_module, "check_database", database_available)

    with TestClient(create_app(_settings())) as client:
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert response.json()["dependencies"]["portfolioHistoryRuntime"] == "unavailable"

    assert events[-3:] == ["worker_stop", "worker_finished", "database_closed"]


@pytest.mark.asyncio
async def test_shutdown_is_bounded_when_task_needs_a_second_cancellation() -> None:
    events: list[str] = []

    class ResistantRunner:
        def stop(self) -> None:
            events.append("stop")

        async def run(self) -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                events.append("first_cancel")
                await asyncio.Event().wait()

    runner = ResistantRunner()
    task = asyncio.create_task(runner.run())
    await asyncio.sleep(0)

    await asyncio.wait_for(
        _shutdown_runner(runner, task, grace_seconds=0, log_name="resistant"),
        timeout=0.5,
    )

    assert task.done()
    assert events == ["stop", "first_cancel"]
