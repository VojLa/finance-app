"""Current static acceptance evidence for the version 0.1 production boundaries."""

from __future__ import annotations

from pathlib import Path

from app.config.settings import Settings
from app.db.models.enums import ImportSource
from app.main import create_app
from app.modules.imports.parsers import PARSER_REGISTRY, parse_csv, parse_raiffeisenbank

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]


def _source(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_python_api_inventory_contains_the_current_public_boundaries() -> None:
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
        ("GET", "/api/v1/portfolio/history"),
    }.issubset(operations)


def test_required_import_sources_use_the_production_parser_registry() -> None:
    assert {
        source: PARSER_REGISTRY[source]
        for source in (
            ImportSource.raiffeisenbank,
            ImportSource.trading212,
            ImportSource.anycoin,
        )
    } == {
        ImportSource.raiffeisenbank: parse_raiffeisenbank,
        ImportSource.trading212: parse_csv,
        ImportSource.anycoin: parse_csv,
    }


def test_manual_and_import_boundaries_use_the_market_backed_coordinator() -> None:
    manual = _source("backend/python/app/modules/snapshot_refresh/manual_service.py")
    imports = _source("backend/python/app/modules/imports/post_processing_service.py")

    assert "ExecuteMarketBackedSnapshotRefreshCommand" in manual
    assert "ExecuteMarketBackedSnapshotRefreshCommand" in imports
    for source in (manual, imports):
        assert "UserSnapshotRefreshExecutor" not in source
        assert "ExecuteUserSnapshotRefreshCommand" not in source


def test_active_browser_boundaries_are_thin_python_adapters() -> None:
    accounts = _source("src/app/api/accounts/route.ts")
    imports = _source("src/app/api/import/route.ts")
    import_handler = _source("src/modules/imports/python/import-route.ts")
    portfolio = _source("src/app/api/snapshot-workflow/portfolio/route.ts")
    dashboard = _source("src/app/api/snapshot-workflow/dashboard/route.ts")
    history = _source("src/app/api/portfolio/history/route.ts")
    active = "\n".join((accounts, imports, import_handler, portfolio, dashboard, history))

    assert "createAccount" in accounts
    assert "handleImportPost" in imports
    assert "runImportWorkflow" in import_handler
    assert "runPortfolioSnapshotWorkflow" in portfolio
    assert "runDashboardSnapshotWorkflow" in dashboard
    assert "readSnapshotBackedPortfolioHistory" in history
    for forbidden in ("@/lib/prisma", "importCsvFilesAsync", "getPortfolioSnapshotHistory"):
        assert forbidden not in active


def test_release_has_backend_schema_and_write_free_frontend_remote_gates() -> None:
    backend = _source(".github/workflows/backend-python.yml")
    schema = _source(".github/workflows/database-schema.yml")
    frontend = _source(".github/workflows/frontend.yml")

    assert "name: Backend Python" in backend
    assert "name: Database Schema" in schema
    assert "name: Frontend" in frontend
    for command in (
        "npm ci",
        "npm run api:python:check",
        "npm test",
        "npm run lint",
        "npx tsc --noEmit --incremental false",
        "npm run db:validate",
        "git diff --check",
        'test -z "$(git status --porcelain)"',
    ):
        assert command in frontend
