"""Release-audit guards for the complete R6 portfolio presentation contract."""

from __future__ import annotations

import ast
import importlib
import os
import subprocess
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy.dialects.postgresql import JSONB

from app.config.settings import Settings
from app.db.models.snapshots import AccountSnapshotModel
from app.main import create_app
from app.modules.portfolio_snapshot.currency_breakdown import (
    PortfolioCurrencyBreakdownError,
    decode_portfolio_currency_breakdown,
)
from app.modules.portfolio_snapshot.models import PortfolioCurrencyAmount

PYTHON_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PYTHON_ROOT.parents[1]
APP_ROOT = PYTHON_ROOT / "app"
PORTFOLIO_ROOT = APP_ROOT / "modules" / "portfolio_snapshot"
FRONTEND_ROOT = REPOSITORY_ROOT / "src"

R6_A_BASE = "6199211d1b4f02c2cfec8d8d48be30b632661c20"
R6_A_MERGE = "b5b68828cfcdb20a13a0d63242363de55026fba3"
R6_B_HEAD = "62074c3958a670493296602923c2ca88a0ce328b"
R6_AUDIT_BASE = "bd42fa36fde6c657eeb7217b9e229d448c5a8f31"

postgres_support = cast(
    Any,
    importlib.import_module("tests.test_portfolio_dashboard_final_audit_integration"),
)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(_source(path), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _changed_files(start: str, end: str) -> set[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{start}..{end}"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return {line for line in result.stdout.splitlines() if line}


def test_r6_lineage_and_physical_schema_are_unchanged() -> None:
    assert subprocess.run(
        ["git", "rev-parse", R6_A_BASE, R6_A_MERGE, R6_B_HEAD, R6_AUDIT_BASE],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines() == [R6_A_BASE, R6_A_MERGE, R6_B_HEAD, R6_AUDIT_BASE]

    cash_column = AccountSnapshotModel.cash_value_by_currency.property.columns[0]
    deposits_column = AccountSnapshotModel.net_deposits_by_currency.property.columns[0]
    assert cash_column.name == "cashValueByCurrency"
    assert deposits_column.name == "netDepositsByCurrency"
    assert isinstance(cash_column.type, JSONB)
    assert isinstance(deposits_column.type, JSONB)

    changed = _changed_files(R6_A_BASE, R6_AUDIT_BASE)
    forbidden_prefixes = (
        "backend/python/migrations/",
        "backend/python/database/revisions/",
    )
    assert not any(path.startswith(forbidden_prefixes) for path in changed)
    assert "prisma/schema.prisma" not in changed
    assert not {
        "backend/python/app/modules/snapshots/calculation.py",
        "backend/python/app/modules/snapshots/writer.py",
    }.intersection(changed)


def test_r6_production_flow_reads_only_persisted_snapshot_evidence() -> None:
    reader = PORTFOLIO_ROOT / "reader.py"
    projection = PORTFOLIO_ROOT / "projection.py"
    aggregation = PORTFOLIO_ROOT / "aggregation.py"
    api_models = PORTFOLIO_ROOT / "api_models.py"
    multi_api_models = PORTFOLIO_ROOT / "multi_account_api_models.py"

    reader_source = _source(reader)
    assert "snapshot.cash_value_by_currency" in reader_source
    assert "snapshot.net_deposits_by_currency" in reader_source
    assert reader_source.count("decode_portfolio_currency_breakdown(") == 2
    forbidden_import_parts = (
        ".transactions",
        ".holdings",
        ".market_data",
        ".prices",
        ".fx",
    )
    assert not any(
        part in imported for imported in _imports(reader) for part in forbidden_import_parts
    )

    projection_source = _source(projection)
    assert projection_source.count("validate_portfolio_currency_breakdown(") == 2
    assert "cash_by_currency=cash_by_currency" in projection_source
    assert "net_deposits_by_currency=net_deposits_by_currency" in projection_source
    aggregation_source = _source(aggregation)
    assert "_sum_breakdowns" in aggregation_source
    assert "exchange_rate" not in aggregation_source.casefold()
    assert "fx" not in aggregation_source.casefold()
    for source in (_source(api_models), _source(multi_api_models)):
        assert "cashByCurrency" in source
        assert "netDepositsByCurrency" in source


def test_canonical_decoder_and_immutable_model_fail_closed() -> None:
    decoded = decode_portfolio_currency_breakdown(
        {
            "USD": "-50.000000",
            "CZK": "10000.000000",
            "EUR": "0.000000",
        },
        scalar_total=Decimal("1.000000"),
        output_currency="EUR",
    )
    assert decoded == (
        PortfolioCurrencyAmount("CZK", Decimal("10000.000000")),
        PortfolioCurrencyAmount("EUR", Decimal("0.000000")),
        PortfolioCurrencyAmount("USD", Decimal("-50.000000")),
    )
    with pytest.raises(FrozenInstanceError):
        decoded[0].amount = Decimal("0.000000")  # type: ignore[misc]

    invalid_values: tuple[object, ...] = (
        None,
        [],
        {"eur": "1.000000"},
        {" EUR": "1.000000"},
        {"EURO": "1.000000"},
        {"EUR": 1},
        {"EUR": True},
        {"EUR": None},
        {"EUR": []},
        {"EUR": {}},
        {"EUR": "NaN"},
        {"EUR": "Infinity"},
        {"EUR": "1e2"},
        {"EUR": "+1.000000"},
        {"EUR": " 1.000000"},
        {"EUR": "01.000000"},
        {"EUR": "1.0"},
        {"EUR": "1.0000000"},
        {"EUR": "1000000000000.000000"},
    )
    for value in invalid_values:
        with pytest.raises(PortfolioCurrencyBreakdownError):
            decode_portfolio_currency_breakdown(
                value,
                scalar_total=Decimal("0.000000"),
                output_currency="EUR",
            )

    with pytest.raises(PortfolioCurrencyBreakdownError):
        decode_portfolio_currency_breakdown(
            {},
            scalar_total=Decimal("1.000000"),
            output_currency="EUR",
        )
    with pytest.raises(PortfolioCurrencyBreakdownError):
        decode_portfolio_currency_breakdown(
            {"EUR": "1.000000"},
            scalar_total=Decimal("2.000000"),
            output_currency="EUR",
        )


def test_public_contract_requires_breakdowns_and_keeps_dashboard_isolated() -> None:
    app = create_app(Settings(_env_file=None))
    schemas = app.openapi()["components"]["schemas"]

    currency_amount = schemas["PortfolioCurrencyAmountResponse"]
    assert currency_amount["required"] == ["currency", "amount"]
    assert currency_amount["properties"]["currency"]["type"] == "string"

    for name in (
        "PortfolioSnapshotSummaryResponse",
        "MultiAccountPortfolioSummaryResponse",
    ):
        schema = schemas[name]
        assert {"cashByCurrency", "netDepositsByCurrency"} <= set(schema["required"])
        for field in ("cashByCurrency", "netDepositsByCurrency"):
            assert (
                schema["properties"][field]["items"]["$ref"]
                == "#/components/schemas/PortfolioCurrencyAmountResponse"
            )

    dashboard = schemas["DashboardSnapshotSummaryResponse"]
    assert "cashByCurrency" not in dashboard["properties"]
    assert "netDepositsByCurrency" not in dashboard["properties"]

    generated = _source(FRONTEND_ROOT / "generated" / "python-api.ts")
    assert "PortfolioCurrencyAmountResponse" in generated
    assert generated.count("cashByCurrency:") >= 2
    assert generated.count("netDepositsByCurrency:") >= 2


@pytest.mark.asyncio
async def test_postgresql_r6_contract_when_database_is_configured() -> None:
    """Run the representative physical-to-public API proof in the dedicated gate."""

    if os.getenv("DATABASE_URL") is None:
        defined = {name for name in vars(postgres_support) if name.startswith("test_")}
        assert {
            "test_portfolio_exposes_exact_persisted_currency_breakdowns_without_dashboard_drift",
            "test_single_multi_and_dashboard_share_one_exact_broker_view",
        } <= defined
        return

    await postgres_support.test_portfolio_exposes_exact_persisted_currency_breakdowns_without_dashboard_drift()
