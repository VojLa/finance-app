from __future__ import annotations

import os
from datetime import datetime
from uuid import uuid4

import pytest
from sqlalchemy import func, select

import scripts.seed_defaults as seed_module
from app.config.settings import Settings
from app.db.connection import close_database, create_database
from app.db.models.categories import CategoryModel, CategoryRuleModel
from app.db.models.enums import CategoryType
from scripts.seed_defaults import DefaultCategory, seed_defaults

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"), reason="DATABASE_URL is required for integration tests"
)


@pytest.mark.integration
async def test_default_seed_is_atomic_and_idempotent_on_clean_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = create_database(Settings())
    assert database is not None
    now = datetime(2026, 8, 10, 0, 0, 0)
    prefix = f"seed-{uuid4().hex[:12]}"
    categories = (
        DefaultCategory(
            f"{prefix}-expense",
            "E",
            "#123456",
            CategoryType.expense,
            (f"{prefix}-keyword",),
        ),
        DefaultCategory(
            f"{prefix}-income",
            "I",
            "#654321",
            CategoryType.income,
        ),
    )
    monkeypatch.setattr(seed_module, "DEFAULT_CATEGORIES", categories)
    category_ids = tuple(category.id for category in categories)
    expected_rules = sum(len(category.keywords) for category in categories)

    try:
        async with database.session_factory() as session:
            transaction = await session.begin()
            try:
                first = await seed_defaults(session, now=now)
                second = await seed_defaults(session, now=now)

                assert first.categories_created == len(categories)
                assert first.categories_replayed == 0
                assert first.rules_created == expected_rules
                assert first.rules_replayed == 0
                assert second.categories_created == 0
                assert second.categories_replayed == len(categories)
                assert second.rules_created == 0
                assert second.rules_replayed == expected_rules
                assert int(
                    await session.scalar(
                        select(func.count())
                        .select_from(CategoryModel)
                        .where(CategoryModel.id.in_(category_ids))
                    )
                    or 0
                ) == len(categories)
                assert (
                    int(
                        await session.scalar(
                            select(func.count())
                            .select_from(CategoryRuleModel)
                            .where(CategoryRuleModel.category_id.in_(category_ids))
                        )
                        or 0
                    )
                    == expected_rules
                )
            finally:
                await transaction.rollback()
    finally:
        await close_database(database)
