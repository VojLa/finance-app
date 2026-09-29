"""Checkout-portable audit for the current snapshot-backed history contract."""

from __future__ import annotations

import ast
from pathlib import Path

from app.config.settings import Settings
from app.db.models.common import MONEY, TIMESTAMP
from app.main import create_app
from app.modules.portfolio_history.lattice import HistoryPublicRange

ROOT = Path(__file__).parents[1]
MODULE_DIR = ROOT / "app" / "modules" / "portfolio_history"
SECRET = "r7-final-audit-secret-with-32-characters"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }


def test_history_public_reader_is_read_only_and_checkout_portable() -> None:
    reader_paths = (
        MODULE_DIR / "api.py",
        MODULE_DIR / "api_models.py",
        MODULE_DIR.parent / "portfolio_snapshot" / "history_reader.py",
    )
    assert all(path.is_file() for path in reader_paths)

    forbidden_operations = (
        "create_task",
        "httpx",
        "requests",
        "for update",
        "advisory",
        "insert(",
        "update(",
        "delete(",
    )
    for path in reader_paths:
        lowered = path.read_text(encoding="utf-8").lower()
        for operation in forbidden_operations:
            assert operation not in lowered

    history_reader = reader_paths[-1]
    history_imports = _imports(history_reader)
    assert "app.db.models.snapshots" in history_imports
    assert "app.db.models.investment_snapshots" in history_imports
    assert "app.modules.market_data" not in history_imports
    reader_source = history_reader.read_text(encoding="utf-8")
    assert "PublishedPortfolioSnapshotHistoryReader" in reader_source
    assert "UserReadModelPublicationModel" in reader_source
    assert "SnapshotSeriesHeadModel" in reader_source
    assert "SnapshotSeriesPointLinkModel" in reader_source
    assert "GenerationPortfolioHistoryRepository" not in reader_source
    assert "TransactionModel" not in reader_source
    assert "InvestmentEventModel" not in reader_source


def test_generation_history_model_and_openapi_contract_are_exact() -> None:
    assert MONEY.precision == 18
    assert MONEY.scale == 6
    assert TIMESTAMP.precision == 3
    assert tuple(item.value for item in HistoryPublicRange) == (
        "1D",
        "1W",
        "1M",
        "3M",
        "6M",
        "1Y",
        "5Y",
        "10Y",
        "ALL",
    )

    settings = Settings(
        environment="test",
        database_url="postgresql+asyncpg://audit:audit@127.0.0.1:1/audit",
        log_level="ERROR",
        log_json=False,
        docs_enabled=True,
        internal_auth_secret=SECRET,
        _env_file=None,
    )
    schema = create_app(settings).openapi()
    operation = schema["paths"]["/api/v1/portfolio/history"]["get"]
    assert operation["security"] == [{"InternalSessionToken": []}]
    assert operation["parameters"] == [
        {
            "name": "range",
            "in": "query",
            "required": False,
            "schema": {
                "$ref": "#/components/schemas/HistoryPublicRange",
                "default": "1Y",
            },
        },
        {
            "name": "accountId",
            "in": "query",
            "required": False,
            "schema": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "title": "Accountid",
            },
        },
    ]
    components = schema["components"]["schemas"]
    assert components["HistoryPublicRange"]["enum"] == [
        "1D",
        "1W",
        "1M",
        "3M",
        "6M",
        "1Y",
        "5Y",
        "10Y",
        "ALL",
    ]
    assert components["PortfolioHistoryReadState"]["enum"] == [
        "ready",
        "rebuilding",
        "failed",
        "empty",
    ]
    point = components["GenerationPortfolioHistoryPointResponse"]
    assert point["required"] == [
        "timestamp",
        "cashValue",
        "investmentValue",
        "liabilitiesValue",
        "netWorthValue",
        "resolutionMinutes",
    ]
    assert point["additionalProperties"] is False
    coverage = components["PortfolioHistoryCoverageResponse"]
    assert coverage["required"] == ["resolutionMinutes", "start", "end"]
    assert coverage["additionalProperties"] is False
    response = components["PortfolioHistoryResponse"]
    assert response["required"] == [
        "range",
        "state",
        "currency",
        "resolutions",
        "coverage",
        "points",
    ]
    assert response["additionalProperties"] is False
    assert set(response["properties"]) == {
        "range",
        "state",
        "currency",
        "generationId",
        "publicationVersion",
        "coveredThrough",
        "preferredResolutionMinutes",
        "resolutions",
        "coverage",
        "points",
        "publicationId",
        "valuationTimestamp",
        "isStale",
    }
