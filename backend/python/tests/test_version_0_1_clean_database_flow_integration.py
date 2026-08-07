"""Guard that the former registration-only probe stays replaced by the R8 proof."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SCENARIO = (
    REPOSITORY_ROOT / "backend/python/tests/test_version_0_1_clean_main_scenario_integration.py"
)


def test_clean_database_acceptance_runs_the_full_supported_main_scenario() -> None:
    source = SCENARIO.read_text(encoding="utf-8")

    assert 'EXPECTED_DATABASE = "finance_app_version_0_1_r8"' in source
    assert 'base_currency="CZK"' in source
    assert '"main_scenario.csv"' in source
    assert '"history.csv"' in source
    assert '"account_statement.csv"' in source
    assert "_install_market_overrides" in source
    assert "/api/v1/snapshot-refresh/recalculate" in source
    assert "_public_reads" in source
    assert "_canonical_tuples" in source
    assert "rows_imported" in source
    assert "no-real-python-fixture" not in source
    assert "NOT READY boundary" not in source


def test_clean_scenario_creates_only_the_user_directly() -> None:
    source = SCENARIO.read_text(encoding="utf-8")

    assert "UserModel(" in source
    assert "AccountModel(" not in source
    assert "AccountSnapshotModel(" not in source
    assert "NetWorthSnapshotModel(" not in source
    assert "PriceSnapshotModel(" not in source
    assert "ExchangeRateModel(" not in source
    assert "AssetAliasModel(" not in source
