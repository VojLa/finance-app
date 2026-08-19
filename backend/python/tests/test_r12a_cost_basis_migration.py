from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.url import normalize_database_url

DATABASE_URL = os.getenv("DATABASE_URL")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    BACKEND_ROOT / "migrations" / "versions" / "3k0001mcost_add_multicurrency_holding_cost_basis.py"
)


def _migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("r12a_cost_basis_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_cost_basis_model_contract_supports_complete_or_unknown_evidence() -> None:
    from app.db.models.holdings import HoldingModel
    from app.db.models.snapshots import AccountSnapshotItemModel

    # R12-A introduced the JSON object contract. Revision 3o deliberately
    # supersedes its non-nullability so imports with genuinely unavailable
    # acquisition evidence remain truthful instead of inventing zero cost.
    assert HoldingModel.__table__.c.costBasisByCurrency.nullable is True
    assert AccountSnapshotItemModel.__table__.c.nativeCostBasisByCurrency.nullable is True
    assert AccountSnapshotItemModel.__table__.c.averageBuyPrice.nullable is True
    assert AccountSnapshotItemModel.__table__.c.averageBuyPriceCurrency.nullable is True


@pytest.mark.integration
@pytest.mark.skipif(DATABASE_URL is None, reason="DATABASE_URL is required for integration tests")
async def test_r12a_legacy_backfill_uses_postgresql_half_even_quantity_boundary() -> None:
    assert DATABASE_URL is not None
    migration = _migration_module()
    engine = create_async_engine(normalize_database_url(DATABASE_URL))
    try:
        async with engine.connect() as connection:
            cases = {
                "1.00000000005::numeric * 10000000000::numeric": "1.0000000000",
                "1.00000000015::numeric * 10000000000::numeric": "1.0000000002",
                "1.000000000051::numeric * 10000000000::numeric": "1.0000000001",
            }
            for scaled_expression, expected in cases.items():
                amount = await connection.scalar(
                    text(
                        "SELECT "
                        f"(({migration.half_even_quantity_sql(scaled_expression)})"
                        "::numeric(28, 10))::text"
                    )
                )
                assert amount == expected
    finally:
        await engine.dispose()
