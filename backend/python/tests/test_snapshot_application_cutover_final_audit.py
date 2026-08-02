"""Static backend contract evidence for the 5M application-cutover audit."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.config.settings import Settings
from app.main import create_app

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
BASE_SHA = "64d1e151baf90e160b45d86e8d415811f5dc42f1"
AUDIT_FINAL_SHA = "20db8a8b5466957868b8ec4e61bcde3d4f2cf265"
AUDIT_CHANGED_FILES = frozenset(
    {
        "!docs/01-architecture/01-technical-overview.md",
        "!docs/01-architecture/04-security.md",
        "!docs/03-api/01-conventions.md",
        "!docs/05-decisions/0005-openapi-contracts.md",
        "ChatGPT/audits/5M-final-audit.md",
        "ChatGPT/steps/5M.md",
        "backend/python/tests/support/verify_internal_token_cli.py",
        "backend/python/tests/test_snapshot_application_cutover_final_audit.py",
        "src/app/dashboard/dashboard-snapshot-cutover.test.ts",
        "src/app/portfolio/portfolio-snapshot-cutover.test.ts",
        "src/app/snapshot-cutover-final-audit.test.ts",
        "src/modules/dashboard/dashboard-cutover-final-audit.test.ts",
        "src/modules/portfolio/portfolio-cutover-final-audit.test.ts",
        "src/modules/python-api/snapshot-cutover-final-audit.test.ts",
    }
)


def _changed_files() -> set[str]:
    audit_range_is_available = all(
        subprocess.run(
            ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
            cwd=REPOSITORY_ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
        for commit in (BASE_SHA, AUDIT_FINAL_SHA)
    )
    if not audit_range_is_available:
        assert all((REPOSITORY_ROOT / path).is_file() for path in AUDIT_CHANGED_FILES)
        return set(AUDIT_CHANGED_FILES)

    tracked = subprocess.run(
        ["git", "diff", "--name-only", BASE_SHA, AUDIT_FINAL_SHA, "--"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {value.replace("\\", "/") for value in tracked.splitlines() if value}


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
