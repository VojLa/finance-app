from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.alembic_baseline import DatabaseState
from scripts.database_migrate import (
    BASELINE_REVISION,
    DEFAULT_ADVISORY_LOCK_KEY,
    run_alembic,
    verify_revision_state,
)


def test_revision_state_requires_explicit_baseline_stamp() -> None:
    with pytest.raises(RuntimeError, match="not stamped"):
        verify_revision_state(DatabaseState(30, 27, ()), require_head=False)


def test_revision_state_rejects_unknown_revision() -> None:
    with pytest.raises(RuntimeError, match="unknown Alembic revisions"):
        verify_revision_state(DatabaseState(30, 27, ("unknown",)), require_head=False)


def test_revision_state_accepts_prepared_baseline_head() -> None:
    verify_revision_state(DatabaseState(30, 27, (BASELINE_REVISION,)), require_head=True)


def test_alembic_runner_uses_python_module_and_local_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run_command(
        command: list[str],
        *,
        database_url: str,
    ) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured["database_url"] = database_url
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("scripts.database_migrate.run_command", fake_run_command)
    run_alembic("postgresql://localhost/test", "current", "--check-heads")

    command = captured["command"]
    assert isinstance(command, list)
    assert command[1:4] == ["-m", "alembic", "-c"]
    assert Path(command[4]).name == "alembic.ini"
    assert command[-2:] == ["current", "--check-heads"]
    assert captured["database_url"] == "postgresql://localhost/test"


def test_advisory_lock_key_is_stable_and_signed_bigint_safe() -> None:
    assert DEFAULT_ADVISORY_LOCK_KEY == 731845204311764461
    assert -(2**63) <= DEFAULT_ADVISORY_LOCK_KEY < 2**63
