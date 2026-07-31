"""Static backend contract evidence for the 5M application-cutover audit."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.config.settings import Settings
from app.main import create_app

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
BASE_SHA = "64d1e151baf90e160b45d86e8d415811f5dc42f1"


def _changed_files() -> set[str]:
    tracked = subprocess.run(
        ["git", "diff", "--name-only", BASE_SHA, "--"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {value.replace("\\", "/") for value in f"{tracked}\n{untracked}".splitlines() if value}


def test_audit_changes_only_tests_reports_and_documentation() -> None:
    allowed_exact = {"ChatGPT/steps/5M.md"}
    allowed_prefixes = (
        "!docs/",
        "ChatGPT/audits/",
        "src/test/",
        "backend/python/tests/",
    )

    for path in _changed_files():
        is_frontend_test = path.startswith("src/") and (
            path.endswith(".test.ts") or path.endswith(".test.tsx")
        )
        assert path in allowed_exact or path.startswith(allowed_prefixes) or is_frontend_test, path


def test_snapshot_http_contracts_remain_in_openapi_with_nonempty_5l_accounts() -> None:
    schema = create_app(
        Settings(
            environment="test",
            database_url=None,
            docs_enabled=True,
            log_level="ERROR",
            log_json=False,
            internal_auth_secret="5m-final-audit-secret-with-32-characters",
            _env_file=None,
        )
    ).openapi()

    paths = schema["paths"]
    assert set(
        path
        for path in paths
        if path
        in {
            "/api/v1/snapshot-refresh/recalculate",
            "/api/v1/portfolio/snapshot",
            "/api/v1/dashboard/snapshot",
        }
    ) == {
        "/api/v1/snapshot-refresh/recalculate",
        "/api/v1/portfolio/snapshot",
        "/api/v1/dashboard/snapshot",
    }
    request_schema = schema["components"]["schemas"]["ExactPortfolioSnapshotSetRequest"]
    assert request_schema["properties"]["accounts"]["minItems"] == 1


def test_cross_runtime_helper_is_stdin_only_and_uses_real_verifier() -> None:
    helper = (BACKEND_ROOT / "tests" / "support" / "verify_internal_token_cli.py").read_text(
        encoding="utf-8"
    )

    assert "InternalTokenVerifier(" in helper
    assert "sys.stdin.read()" in helper
    assert "len(sys.argv) != 1" in helper
    assert 'token = request["token"]' in helper
    assert "print(token" not in helper
    assert "repr(" not in helper
    assert "traceback" not in helper
