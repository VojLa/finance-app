import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.main import create_app


def test_enabled_worker_starts_and_stops_with_application_lifespan(monkeypatch) -> None:
    events: list[str] = []

    class FakeEngine:
        async def dispose(self) -> None:
            events.append("database_closed")

    class FakeDatabase:
        engine = FakeEngine()
        session_factory = object()

    class FakeExecutor:
        def __init__(self, *_args: object) -> None:
            events.append("executor_created")

    class FakeWorker:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            events.append("worker_created")

    class FakeRunner:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.stop_event = asyncio.Event()

        async def run(self) -> None:
            events.append("runner_started")
            await self.stop_event.wait()
            events.append("runner_stopped")

        def stop(self) -> None:
            self.stop_event.set()

    monkeypatch.setattr("app.lifespan.create_database", lambda _settings: FakeDatabase())
    monkeypatch.setattr("app.lifespan.DurableImportJobExecutor", FakeExecutor)
    monkeypatch.setattr("app.lifespan.BackgroundJobWorker", FakeWorker)
    monkeypatch.setattr("app.lifespan.WorkerRunner", FakeRunner)
    settings = Settings(
        environment="test",
        background_jobs_enabled=True,
        database_url="postgresql://configured",
        _env_file=None,
    )
    app = create_app(settings)

    with TestClient(app):
        assert isinstance(app.state.background_job_runner, FakeRunner)

    assert events == [
        "executor_created",
        "worker_created",
        "runner_started",
        "runner_stopped",
        "database_closed",
    ]


def test_enabled_worker_fails_startup_without_database() -> None:
    settings = Settings(environment="test", background_jobs_enabled=True, _env_file=None)

    with pytest.raises(RuntimeError, match="configured database"):
        with TestClient(create_app(settings)):
            pass
