"""Static production guards for the post-B4 R5 remediation re-audit."""

from __future__ import annotations

import ast
from pathlib import Path

from app.db.models.enums import AssetAliasProvider, AssetType
from app.modules.asset_aliases.identity import (
    COINGECKO_ASSET_TYPES,
    SUPPORTED_ASSET_ALIAS_PROVIDERS,
    TWELVE_DATA_ASSET_TYPES,
)
from app.modules.asset_aliases.service import ASSET_ALIAS_NAMESPACE

PYTHON_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PYTHON_ROOT.parents[1]
APP_ROOT = PYTHON_ROOT / "app"
TEST_ROOT = PYTHON_ROOT / "tests"
ALIAS_ROOT = APP_ROOT / "modules" / "asset_aliases"
ALIAS_IDENTITY = ALIAS_ROOT / "identity.py"
ALIAS_REPOSITORY = ALIAS_ROOT / "repository.py"
ALIAS_SERVICE = ALIAS_ROOT / "service.py"
ALIAS_CLI = PYTHON_ROOT / "scripts" / "asset_alias.py"
COINGECKO_PROVIDER = APP_ROOT / "modules" / "prices" / "providers" / "coingecko.py"
TWELVE_DATA_PROVIDER = APP_ROOT / "modules" / "prices" / "providers" / "twelve_data.py"
ONBOARDING_E2E = TEST_ROOT / "test_asset_alias_onboarding_e2e_integration.py"


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


def test_historical_audit_remains_an_explicit_pre_b4_not_ready_record() -> None:
    historical_audit = _source(REPOSITORY_ROOT / "ChatGPT" / "audits" / "0.1-r5-final-audit.md")
    historical_matrix = _source(
        REPOSITORY_ROOT / "ChatGPT" / "audits" / "0.1-r5-requirement-matrix.md"
    )

    assert "f67fd8615e423c7af851522e623e7db32481427e" in historical_audit
    assert "R5 FINAL VERDICT: NOT READY" in historical_audit
    assert "R5-ALIAS-01" in historical_matrix
    assert "MISSING" in historical_matrix


def test_only_the_approved_production_writer_constructs_asset_alias_rows() -> None:
    constructors: list[str] = []
    forbidden_roots = (
        APP_ROOT / "modules" / "imports",
        APP_ROOT / "modules" / "holdings",
        APP_ROOT / "modules" / "market_data",
        APP_ROOT / "modules" / "snapshot_refresh",
    )
    for path in APP_ROOT.rglob("*.py"):
        tree = ast.parse(_source(path), filename=str(path))
        if any(
            isinstance(node, ast.Call) and _call_name(node) == "AssetAliasModel"
            for node in ast.walk(tree)
        ):
            constructors.append(path.relative_to(PYTHON_ROOT).as_posix())

    assert constructors == ["app/modules/asset_aliases/service.py"]
    for root in forbidden_roots:
        for path in root.rglob("*.py"):
            source = _source(path)
            assert "AssetAliasModel(" not in source
            assert "AssetAliasOnboardingService" not in source


def test_alias_onboarding_has_no_public_or_browser_mutation_boundary() -> None:
    assert not (ALIAS_ROOT / "api.py").exists()
    for path in APP_ROOT.rglob("api.py"):
        folded = _source(path).casefold()
        assert "asset_alias" not in folded
        assert "asset-alias" not in folded

    for path in (REPOSITORY_ROOT / "src").rglob("*.ts*"):
        source = _source(path)
        assert "AssetAliasOnboardingService" not in source
        assert "asset_alias.py" not in source


def test_provider_identity_validation_is_shared_exact_and_type_limited() -> None:
    identity_source = _source(ALIAS_IDENTITY)

    assert "parse_coingecko_asset_identity" in identity_source
    assert "parse_twelve_data_quote_identity" in identity_source
    assert "parse_coingecko_asset_identity" in _source(COINGECKO_PROVIDER)
    assert "parse_twelve_data_quote_identity" in _source(TWELVE_DATA_PROVIDER)
    assert SUPPORTED_ASSET_ALIAS_PROVIDERS == frozenset(
        {AssetAliasProvider.coingecko, AssetAliasProvider.twelve_data}
    )
    assert COINGECKO_ASSET_TYPES == frozenset({AssetType.crypto})
    assert TWELVE_DATA_ASSET_TYPES == frozenset(
        {
            AssetType.stock,
            AssetType.etf,
            AssetType.bond,
            AssetType.commodity,
            AssetType.other,
        }
    )


def test_operator_cli_validates_provider_before_database_composition() -> None:
    source = _source(ALIAS_CLI)
    tree = ast.parse(source, filename=str(ALIAS_CLI))
    argument_flags = {
        argument.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _call_name(node) == "add_argument"
        for argument in node.args
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
    }

    assert "--database-url" not in argument_flags
    assert source.index("provider = _provider(args.provider)") < source.index(
        "settings = Settings()"
    )
    assert "AssetAliasInventoryService" in source
    assert "AssetAliasOnboardingService" in source
    assert "json.dumps(" in source
    assert "traceback" not in source.casefold()


def test_inventory_query_is_read_only_held_compatible_and_deterministic() -> None:
    source = _source(ALIAS_REPOSITORY)
    inventory_source = source[
        source.index("    async def list_unresolved") : source.index(
            "\n\n\nclass AssetAliasWriterRepository"
        )
    ]

    assert "REPEATABLE READ, READ ONLY" in source
    assert "HoldingModel.quantity != 0" in inventory_source
    assert "AssetModel.asset_type.in_(compatible_types)" in inventory_source
    assert "~exists(" in inventory_source
    assert ".order_by(AssetModel.symbol, AssetModel.id)" in inventory_source
    assert "AssetListingModel.provider_symbol" in inventory_source
    assert "AssetListingModel.id" in inventory_source
    assert "external_id" not in inventory_source
    assert ".add(" not in inventory_source


def test_writer_identity_transaction_lock_and_retry_contract_is_explicit() -> None:
    source = _source(ALIAS_SERVICE)

    assert str(ASSET_ALIAS_NAMESPACE) == "b1d66d76-35f0-4db0-b1d9-0f5452d4a27c"
    assert 'f"{asset_id}\\0{provider.value}"' in source
    assert "_MAX_TRANSACTION_ATTEMPTS = 3" in source
    assert '_RETRYABLE_SQLSTATES = {"40001", "40P01", "23505"}' in source
    assert "set_transaction_serializable" in source
    assert "sorted(" in source
    assert "asset_provider_lock_scope" in source
    assert "provider_external_lock_scope" in source
    assert "load_alias_by_id(expected_id)" in source
    assert "self.repository.reload_alias(expected_id)" in source
    assert ".update(" not in source
    assert ".delete(" not in source


def test_runtime_suites_cover_state_retry_subprocess_recovery_and_concurrency() -> None:
    service_tests = _defined_tests(TEST_ROOT / "test_asset_alias_service_integration.py")
    onboarding_tests = _defined_tests(ONBOARDING_E2E)
    manual_tests = _defined_tests(
        TEST_ROOT / "test_snapshot_refresh_manual_endpoint_integration.py"
    )
    import_tests = _defined_tests(TEST_ROOT / "test_import_market_backed_refresh_integration.py")
    import_concurrency_tests = _defined_tests(
        TEST_ROOT / "test_import_post_processing_integration.py"
    )

    assert {
        "test_postgresql_create_and_replay_are_physically_exact",
        "test_concurrent_same_command_converges_to_one_physical_row",
        "test_concurrent_conflicting_commands_have_one_winner",
        "test_existing_state_matrix_fails_without_repair",
        "test_historical_replay_rejects_foreign_deterministic_id_collision",
        "test_reload_failure_rolls_back_insert_and_leaves_idle_session",
        "test_retryable_sqlstates_retry_complete_transaction",
        "test_nonretryable_sql_failure_rolls_back_without_retry",
        "test_unresolved_inventory_filters_and_orders_physical_rows",
    } <= service_tests
    assert {
        "test_clean_import_and_manual_recovery_use_actual_cli_without_direct_insert",
        "test_actual_cli_missing_database_url_is_safe_json",
    } <= onboarding_tests
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


def test_clean_recovery_suite_uses_actual_cli_without_direct_alias_insertion() -> None:
    source = _source(ONBOARDING_E2E)

    assert '[UV, "run", "python", "scripts/asset_alias.py"' in source
    assert "AssetAliasModel(" not in source
    assert "INSERT INTO" not in source.upper()
    assert "list-unresolved" in source
    assert "--dry-run" in source
    assert "onboard" in source
    assert '"bitcoin"' in source
    assert '"bitcoin,ethereum"' in source
