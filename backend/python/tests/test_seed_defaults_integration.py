from __future__ import annotations

import os
from datetime import datetime

import pytest
from sqlalchemy import func, select

from app.config.settings import Settings
from app.db.connection import close_database, create_database
from app.db.models.categories import CategoryModel, CategoryRuleModel
from scripts.seed_defaults import DEFAULT_CATEGORIES, seed_defaults

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL is required for integration tests"
)


@pytest.mark.integration
async def test_default_seed_is_atomic_and_idempotent_on_clean_database() -> None:
    database = create_database(Settings())
    assert database is not None
    now = datetime(2026, 8, 10, 0, 0, 0)
    expected_rules = sum(len(category.keywords) for category in DEFAULT_CATEGORIES)

    try:
        async with database.session_factory() as session:
            async with session.begin():
                assert (
                    int(await session.scalar(select(func.count()).select_from(CategoryModel)) or 0)
                    == 0
                )
                first = await seed_defaults(session, now=now)
            async with session.begin():
                second = await seed_defaults(session, now=now)

            assert first.categories_created == len(DEFAULT_CATEGORIES)
            assert first.categories_replayed == 0
            assert first.rules_created == expected_rules
            assert first.rules_replayed == 0
            assert second.categories_created == 0
            assert second.categories_replayed == len(DEFAULT_CATEGORIES)
            assert second.rules_created == 0
            assert second.rules_replayed == expected_rules
            assert int(
                await session.scalar(select(func.count()).select_from(CategoryModel)) or 0
            ) == len(DEFAULT_CATEGORIES)
            assert (
                int(await session.scalar(select(func.count()).select_from(CategoryRuleModel)) or 0)
                == expected_rules
            )
    finally:
        await close_database(database)
