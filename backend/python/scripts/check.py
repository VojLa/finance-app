from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

CHECKS: tuple[tuple[str, list[str]], ...] = (
    ("Ruff lint", [sys.executable, "-m", "ruff", "check", "."]),
    ("Ruff format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
    ("Mypy", [sys.executable, "-m", "mypy", "app", "tests"]),
    (
        "Pytest",
        [
            sys.executable,
            "-m",
            "pytest",
            "--cov=app",
            "--cov-report=term-missing",
        ],
    ),
)


def run_checks() -> int:
    for label, command in CHECKS:
        print(f"\n==> {label}", flush=True)
        result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
        if result.returncode != 0:
            return result.returncode

    print("\nAll backend checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_checks())
