"""Static release-audit guards for R5 market-evidence ownership.

The PostgreSQL suites named below prove runtime behavior. These guards make the
production call graph, provider composition, public response surface, and the
known alias-onboarding release blocker explicit and reviewable.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.config.settings import Settings
from app.db.models.enums import ExchangeRateSource, PriceSource
from app.modules.fx.providers import create_production_exchange_rate_registry
from app.modules.imports.models import ImportPostResponse
from app.modules.prices.providers import create_production_price_registry
from app.modules.snapshot_refresh.models import UserSnapshotRefreshRecalculateResponse

PYTHON_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = PYTHON_ROOT / "app"
TEST_ROOT = PYTHON_ROOT / "tests"

MANUAL_SERVICE = APP_ROOT / "modules" / "snapshot_refresh" / "manual_service.py"
IMPORT_SERVICE = APP_ROOT / "modules" / "imports" / "post_processing_service.py"
COORDINATOR = APP_ROOT / "modules" / "snapshot_refresh" / "market_backed_service.py"
MANUAL_API = APP_ROOT / "modules" / "snapshot_refresh" / "api.py"
IMPORT_API = APP_ROOT / "modules" / "imports" / "api.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _defined_tests(path: Path) -> set[str]:
    tree = ast.parse(_source(path), filename=str(path))
    return {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def test_production_provider_registries_have_only_the_approved_r5_sources() -> None:
    settings = Settings(_env_file=None)

    price_registry = create_production_price_registry(settings)
    fx_registry = create_production_exchange_rate_registry(settings)

    assert price_registry.sources == frozenset({PriceSource.coingecko, PriceSource.twelve_data})
    assert fx_registry.sources == frozenset({ExchangeRateSource.cnb})


def test_public_boundaries_delegate_to_the_market_backed_coordinator() -> None:
    forbidden_boundary_symbols = {
        "UserSnapshotRefreshExecutor",
        "ExecuteUserSnapshotRefreshCommand",
        "ExecutorFactory",
    }
    for boundary in (MANUAL_SERVICE, IMPORT_SERVICE):
        boundary_source = _source(boundary)
        assert all(symbol not in boundary_source for symbol in forbidden_boundary_symbols)
        assert "ExecuteMarketBackedSnapshotRefreshCommand" in boundary_source

    coordinator_source = _source(COORDINATOR)
    assert "UserSnapshotRefreshExecutor" in coordinator_source
    assert "ExecuteUserSnapshotRefreshCommand" in coordinator_source

    assert '"/recalculate"' in _source(MANUAL_API)
    assert '"/{batch_id}/post"' in _source(IMPORT_API)


def test_production_has_no_exact_asset_alias_write_or_reconciliation_path() -> None:
    """R5-ALIAS-01 is intentionally a documented MISSING release gate."""

    production_alias_calls: list[str] = []
    suspicious_production_symbols: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        source = _source(path)
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) == "AssetAliasModel":
                production_alias_calls.append(str(path.relative_to(PYTHON_ROOT)))
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                normalized = node.name.casefold()
                if "assetalias" in normalized and any(
                    word in normalized for word in ("write", "create", "reconcile", "service")
                ):
                    suspicious_production_symbols.append(
                        f"{path.relative_to(PYTHON_ROOT)}:{node.name}"
                    )

    assert production_alias_calls == []
    assert suspicious_production_symbols == []

    test_seed_sources = (
        TEST_ROOT / "support" / "coingecko_price_integration.py",
        TEST_ROOT / "support" / "twelve_data_price_integration.py",
        TEST_ROOT / "test_import_market_backed_refresh_integration.py",
    )
    assert all("AssetAliasModel(" in _source(path) for path in test_seed_sources)


def test_public_response_models_do_not_expose_market_evidence_metadata() -> None:
    forbidden_fields = {
        "price_ids",
        "exchange_rate_ids",
        "provider",
        "provider_symbol",
        "required_price_count",
        "required_fx_count",
        "prices_created",
        "prices_replayed",
        "rates_created",
        "rates_replayed",
        "api_key",
        "provider_url",
        "raw_payload",
    }

    assert forbidden_fields.isdisjoint(ImportPostResponse.model_fields)
    assert forbidden_fields.isdisjoint(UserSnapshotRefreshRecalculateResponse.model_fields)


def test_r5_coordinators_do_not_schedule_retry_or_cache_work() -> None:
    forbidden_calls = {
        "create_task",
        "ensure_future",
        "retry",
        "sleep",
        "to_thread",
    }
    forbidden_decorators = {"cache", "cached_property", "lru_cache"}

    for path in (COORDINATOR, MANUAL_SERVICE, IMPORT_SERVICE):
        tree = ast.parse(_source(path), filename=str(path))
        call_names = {
            name
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            if (name := _call_name(node)) is not None
        }
        decorator_names = {
            decorator.id
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Name)
        }
        assert forbidden_calls.isdisjoint(call_names)
        assert forbidden_decorators.isdisjoint(decorator_names)


def test_postgresql_evidence_suites_cover_public_flows_replay_and_failures() -> None:
    manual_tests = _defined_tests(
        TEST_ROOT / "test_snapshot_refresh_manual_endpoint_integration.py"
    )
    import_tests = _defined_tests(TEST_ROOT / "test_import_market_backed_refresh_integration.py")
    import_concurrency_tests = _defined_tests(
        TEST_ROOT / "test_import_post_processing_integration.py"
    )

    assert {
        "test_production_mixed_provider_endpoint_e2e_and_replay",
        "test_provider_failure_endpoint_matrix_writes_no_market_or_snapshot_graph",
        "test_alias_failure_endpoint_stops_before_provider_http",
        "test_snapshot_conflict_after_market_commit_preserves_market_evidence",
        "test_concurrent_requests_converge_without_duplicate_rows",
    } <= manual_tests
    assert {
        "test_raiffeisenbank_import_uses_empty_market_plan_and_replays",
        "test_investment_import_uses_exact_provider_alias_and_replays",
        "test_provider_failure_preserves_posting_and_holdings_without_partial_graph",
        "test_missing_or_ambiguous_alias_fails_before_http",
        "test_snapshot_conflict_preserves_market_and_replay_market_conflict_skips_snapshot",
        "test_delayed_replay_rejects_future_provider_observation_without_moving_bucket",
    } <= import_tests
    assert "test_concurrent_import_post_endpoint_requests_converge" in (import_concurrency_tests)
