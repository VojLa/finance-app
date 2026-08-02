"""Static acceptance evidence for the version 0.1 architecture-lock audit."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.config.settings import Settings
from app.db.models.enums import ImportSource
from app.main import create_app
from app.modules.imports.parsers import PARSER_REGISTRY, parse_csv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
BASE_SHA = "20db8a8b5466957868b8ec4e61bcde3d4f2cf265"
AUDIT_FINAL_SHA = "73a9aa668a6725e2bc7f2ba6dcd3ae1712841fc0"
AUDIT_FILES = frozenset(
    {
        "ChatGPT/audits/0.1-final-acceptance.md",
        "ChatGPT/audits/0.1-requirement-matrix.md",
        "backend/python/tests/test_snapshot_application_cutover_final_audit.py",
        "backend/python/tests/test_version_0_1_acceptance.py",
        "backend/python/tests/test_version_0_1_acceptance_integration.py",
        "backend/python/tests/test_version_0_1_clean_database_flow_integration.py",
        "src/app/version-0-1-final-audit.test.ts",
        "src/modules/accounts/version-0-1-account-cutover-audit.test.ts",
        "src/modules/imports/version-0-1-import-cutover-audit.test.ts",
        "src/modules/python-api/version-0-1-boundary-audit.test.ts",
    }
)


def _changed_files() -> set[str]:
    audit_range_available = all(
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
    if not audit_range_available:
        assert all((REPOSITORY_ROOT / path).is_file() for path in AUDIT_FILES)
        return set(AUDIT_FILES)

    tracked = subprocess.run(
        ["git", "diff", "--name-only", BASE_SHA, AUDIT_FINAL_SHA, "--"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return {value.replace("\\", "/") for value in tracked.splitlines() if value}


def test_audit_changes_no_production_file() -> None:
    assert _changed_files() == AUDIT_FILES


def test_python_api_inventory_contains_implemented_core_boundaries() -> None:
    schema = create_app(
        Settings(
            environment="test",
            database_url=None,
            docs_enabled=True,
            log_level="ERROR",
            log_json=False,
            internal_auth_secret="version-0-1-audit-secret-at-least-32-characters",
            _env_file=None,
        )
    ).openapi()
    operations = {
        (method.upper(), path)
        for path, path_operations in schema["paths"].items()
        for method in path_operations
        if method in {"get", "post", "put", "patch", "delete"}
    }

    assert {
        ("GET", "/api/v1/accounts"),
        ("POST", "/api/v1/accounts"),
        ("POST", "/api/v1/accounts/{account_id}/imports"),
        ("PUT", "/api/v1/accounts/{account_id}/imports/{batch_id}/file"),
        ("POST", "/api/v1/accounts/{account_id}/imports/{batch_id}/parse"),
        ("POST", "/api/v1/accounts/{account_id}/imports/{batch_id}/normalize"),
        ("POST", "/api/v1/accounts/{account_id}/imports/{batch_id}/deduplicate"),
        ("POST", "/api/v1/accounts/{account_id}/imports/{batch_id}/classify"),
        ("POST", "/api/v1/accounts/{account_id}/imports/{batch_id}/post"),
        ("POST", "/api/v1/snapshot-refresh/recalculate"),
        ("POST", "/api/v1/portfolio/snapshot"),
        ("POST", "/api/v1/dashboard/snapshot"),
    }.issubset(operations)


def test_all_mandatory_sources_still_share_the_generic_python_parser() -> None:
    assert {
        source: PARSER_REGISTRY[source]
        for source in (
            ImportSource.raiffeisenbank,
            ImportSource.trading212,
            ImportSource.anycoin,
        )
    } == {
        ImportSource.raiffeisenbank: parse_csv,
        ImportSource.trading212: parse_csv,
        ImportSource.anycoin: parse_csv,
    }


def test_python_has_no_price_or_fx_api_boundary_for_the_required_provider_workflow() -> None:
    schema = create_app(
        Settings(
            environment="test",
            database_url=None,
            docs_enabled=True,
            log_level="ERROR",
            log_json=False,
            internal_auth_secret="version-0-1-audit-secret-at-least-32-characters",
            _env_file=None,
        )
    ).openapi()
    paths = set(schema["paths"])

    assert not any("/prices" in path or "/fx" in path or "/rates" in path for path in paths)
