"""Checkout-portable static acceptance guards for the version 0.1 R9 audit."""

from __future__ import annotations

import json
from pathlib import Path

from app.config.settings import Settings
from app.db.models.enums import ImportSource
from app.main import create_app
from app.modules.imports.parsers import PARSER_REGISTRY, parse_csv, parse_raiffeisenbank

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parents[1]
HISTORICAL_MATRIX = "ChatGPT/audits/0.1-requirement-matrix.md"
R9_MATRIX = "ChatGPT/audits/0.1-r9-requirement-matrix.md"


def _source(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def _matrix_rows(relative_path: str) -> tuple[tuple[str, ...], ...]:
    rows: list[tuple[str, ...]] = []
    for line in _source(relative_path).splitlines():
        if not line.startswith("| "):
            continue
        cells = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        if cells and cells[0] not in {"ID", "-------------", "---"} and cells[0][:1].isalpha():
            rows.append(cells)
    return tuple(rows)


def _openapi() -> dict[str, object]:
    return create_app(
        Settings(
            environment="test",
            database_url=None,
            docs_enabled=True,
            log_level="ERROR",
            log_json=False,
            internal_auth_secret="version-0-1-r9-audit-secret-at-least-32-characters",
            _env_file=None,
        )
    ).openapi()


def test_r9_reuses_every_historical_requirement_id_and_scope_text() -> None:
    historical = _matrix_rows(HISTORICAL_MATRIX)
    current = _matrix_rows(R9_MATRIX)

    assert len(historical) == len(current) == 87
    assert tuple((row[0], row[1], row[2]) for row in current) == tuple(
        (row[0], row[1], row[2]) for row in historical
    )
    assert len({row[0] for row in current}) == 87
    statuses = {row[0]: row[5] for row in current}
    assert statuses["SCOPE-02"] == "OUT_OF_SCOPE"
    assert set(statuses.values()) == {"PASS", "OUT_OF_SCOPE"}


def test_historical_not_ready_audit_remains_historical_evidence() -> None:
    report = _source("ChatGPT/audits/0.1-final-acceptance.md")
    matrix = _source(HISTORICAL_MATRIX)

    assert "## Final verdict" in report
    assert "**NOT READY**" in report
    for blocker in (
        "B1 account browser cutover",
        "B2 import browser/status/multi-file cutover",
        "B4 prices and FX boundary",
        "B6 portfolio history",
        "B7 clean/browser E2E and replay",
    ):
        assert blocker in report
    assert "| ACC-04 " in matrix and "| MISSING " in matrix
    assert "| SCOPE-02 " in matrix and "| OUT OF SCOPE " in matrix


def test_python_api_inventory_contains_every_active_version_0_1_boundary() -> None:
    schema = _openapi()
    paths = schema["paths"]
    assert isinstance(paths, dict)
    operations = {
        (method.upper(), path)
        for path, path_operations in paths.items()
        if isinstance(path_operations, dict)
        for method in path_operations
        if method in {"get", "post", "put", "patch", "delete"}
    }

    assert {
        ("GET", "/api/v1/accounts"),
        ("POST", "/api/v1/accounts"),
        ("PATCH", "/api/v1/accounts/{account_id}"),
        ("POST", "/api/v1/accounts/{account_id}/archive"),
        ("POST", "/api/v1/accounts/{account_id}/restore"),
        ("GET", "/api/v1/accounts/{account_id}/imports"),
        ("POST", "/api/v1/accounts/{account_id}/imports"),
        ("GET", "/api/v1/accounts/{account_id}/imports/{batch_id}"),
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


def test_public_finance_contracts_do_not_expose_market_or_secret_metadata() -> None:
    components = _openapi()["components"]
    assert isinstance(components, dict)
    schemas = components["schemas"]
    assert isinstance(schemas, dict)
    selected = {
        name: value
        for name, value in schemas.items()
        if any(
            marker in name
            for marker in (
                "Portfolio",
                "Dashboard",
                "ImportPostResponse",
                "UserSnapshotRefreshRecalculateResponse",
            )
        )
    }
    serialized = json.dumps(selected, sort_keys=True)

    for forbidden in (
        "price_ids",
        "exchange_rate_ids",
        "provider_symbol",
        "required_price_count",
        "required_fx_count",
        "prices_created",
        "rates_created",
        "api_key",
        "database_url",
        "raw_payload",
        "sql_detail",
    ):
        assert forbidden not in serialized


def test_required_source_parsers_and_provider_registries_are_production_owned() -> None:
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

    prices = _source("backend/python/app/modules/prices/providers/__init__.py")
    fx = _source("backend/python/app/modules/fx/providers/__init__.py")
    factory = _source("backend/python/app/modules/market_data/factory.py")
    assert "CoinGeckoPriceProvider" in prices
    assert "TwelveDataPriceProvider" in prices
    assert "PriceProviderRegistry" in prices
    assert "CnbExchangeRateProvider" in fx
    assert "ExchangeRateProviderRegistry" in fx
    assert "fx_source=ExchangeRateSource.cnb" in factory


def test_manual_and_import_paths_have_no_direct_snapshot_executor_fallback() -> None:
    manual = _source("backend/python/app/modules/snapshot_refresh/manual_service.py")
    imports = _source("backend/python/app/modules/imports/post_processing_service.py")
    coordinator = _source("backend/python/app/modules/snapshot_refresh/market_backed_service.py")

    for boundary in (manual, imports):
        assert "ExecuteMarketBackedSnapshotRefreshCommand" in boundary
        assert "UserSnapshotRefreshExecutor" not in boundary
        assert "ExecuteUserSnapshotRefreshCommand" not in boundary
    assert "create_production_market_evidence_service" in coordinator
    assert "UserSnapshotRefreshExecutor" in coordinator
    assert coordinator.index("await market_service.refresh") < coordinator.index(
        "await snapshot_executor.execute"
    )


def test_active_browser_routes_are_thin_authenticated_python_adapters() -> None:
    sources = {
        path: _source(path)
        for path in (
            "src/app/api/accounts/route.ts",
            "src/app/api/import/route.ts",
            "src/modules/imports/python/import-route.ts",
            "src/app/api/snapshot-workflow/portfolio/route.ts",
            "src/app/api/snapshot-workflow/dashboard/route.ts",
            "src/app/api/portfolio/history/route.ts",
            "src/modules/accounts/server/account-api.ts",
            "src/modules/imports/python/import-api.ts",
            "src/modules/python-api/server/transport.ts",
            "src/modules/python-api/server/portfolio-history.ts",
        )
    }
    combined = "\n".join(sources.values())

    assert "createAccount" in sources["src/app/api/accounts/route.ts"]
    assert "handleImportPost" in sources["src/app/api/import/route.ts"]
    assert "runImportWorkflow" in sources["src/modules/imports/python/import-route.ts"]
    assert (
        "runPortfolioSnapshotWorkflow"
        in sources["src/app/api/snapshot-workflow/portfolio/route.ts"]
    )
    assert (
        "runDashboardSnapshotWorkflow"
        in sources["src/app/api/snapshot-workflow/dashboard/route.ts"]
    )
    assert "readSnapshotBackedPortfolioHistory" in sources["src/app/api/portfolio/history/route.ts"]
    assert "issueInternalToken" in sources["src/modules/python-api/server/transport.ts"]
    assert 'cache: "no-store"' in sources["src/modules/python-api/server/transport.ts"]
    for forbidden in (
        "@/lib/prisma",
        "importCsvFilesAsync",
        "getPortfolioSnapshotHistory",
        "Cookie:",
    ):
        assert forbidden not in combined


def test_active_pages_do_not_consume_legacy_financial_business_routes() -> None:
    accounts = _source("src/app/accounts/page.tsx")
    imports = _source("src/app/import/page.tsx")
    portfolio = _source("src/app/portfolio/page.tsx")
    dashboard = _source("src/app/dashboard/page.tsx")
    active = "\n".join((accounts, imports, portfolio, dashboard))

    assert "requestAccounts" in accounts
    assert "requestImport" in imports
    assert "requestPortfolioPageState" in portfolio
    assert "requestDashboardFinancialState" in dashboard
    assert "startPortfolioHistoryRequest" in portfolio
    for forbidden in (
        "importCsvFilesAsync",
        "/api/portfolio/snapshots/recalculate",
        "/api/rates",
        "@/lib/prisma",
        "getPortfolioSnapshotHistory",
    ):
        assert forbidden not in active


def test_pure_python_financial_projections_have_no_framework_or_orm_dependency() -> None:
    projection_files = sorted(
        (REPOSITORY_ROOT / "backend/python/app/modules").glob("*/projection.py")
    )
    assert projection_files
    for path in projection_files:
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "fastapi",
            "pydantic",
            "sqlalchemy.orm",
            "AsyncSession",
            "mapped_column",
        ):
            assert forbidden not in source, f"{path.relative_to(REPOSITORY_ROOT)}: {forbidden}"


def test_remote_gates_cover_backend_schema_and_frontend_without_error_suppression() -> None:
    workflows = {
        name: _source(f".github/workflows/{name}")
        for name in ("backend-python.yml", "database-schema.yml", "frontend.yml")
    }
    assert "name: Backend Python" in workflows["backend-python.yml"]
    assert "name: Database Schema" in workflows["database-schema.yml"]
    assert "name: Frontend" in workflows["frontend.yml"]
    frontend = workflows["frontend.yml"]
    for path in ('- "src/**"', '- "prisma/**"', '- "package.json"'):
        assert path in frontend
    for command in (
        "npm ci",
        "npm run db:generate",
        "npm run api:python:check",
        "npm test",
        "npm run lint",
        "npx tsc --noEmit --incremental false",
        "npm run db:validate",
        "git diff --check",
        'test -z "$(git status --porcelain)"',
    ):
        assert command in frontend
    for source in workflows.values():
        assert "continue-on-error" not in source
        assert "|| true" not in source


def test_r9_records_a_pass_without_rewriting_the_historical_verdict() -> None:
    remediation = _source("ChatGPT/steps/0.1-remediation.md")
    roadmap = _source("!planning/product/02-roadmap.md")
    report = _source("ChatGPT/audits/0.1-r9-final-acceptance.md")

    assert "0.1-R9 — repeat final acceptance audit: implemented — PASS" in remediation
    assert "Version 0.1 — complete" in remediation
    assert "VERSION 0.1 FINAL VERDICT: PASS" in report
    assert "0.1 - Architecture Locked" in report
    assert "internal architecture MVP" in report
    assert "is production ready" not in report.lower()
    assert "is a public beta" not in report.lower()
    assert "0.1 - Architecture Locked" in roadmap
    assert "completed technical milestone" in roadmap
