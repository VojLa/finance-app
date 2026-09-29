"""Atomically seed immutable application-wide default categories and rules."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import Settings  # noqa: E402
from app.db.connection import close_database, create_database  # noqa: E402
from app.db.models.categories import CategoryModel, CategoryRuleModel  # noqa: E402
from app.db.models.enums import CategoryType, RuleField, RuleOperator  # noqa: E402


class DefaultSeedConflictError(RuntimeError):
    """Raised when a reserved default identity contains unexpected data."""


@dataclass(frozen=True, slots=True)
class DefaultCategory:
    name: str
    icon: str
    color: str
    type: CategoryType
    keywords: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return f"default-{self.name}"


@dataclass(frozen=True, slots=True)
class SeedResult:
    categories_created: int
    categories_replayed: int
    rules_created: int
    rules_replayed: int


DEFAULT_CATEGORIES = (
    DefaultCategory("Jídlo & Restaurace", "🍽️", "#ef4444", CategoryType.expense),
    DefaultCategory(
        "Doprava",
        "🚗",
        "#3b82f6",
        CategoryType.expense,
        ("DPMB", "DPP", "Regiojet", "FlixBus", "Shell", "OMV", "MOL"),
    ),
    DefaultCategory(
        "Bydlení",
        "🏠",
        "#8b5cf6",
        CategoryType.expense,
        ("Nájemné", "Energie", "Vodné", "Internet"),
    ),
    DefaultCategory(
        "Zdraví",
        "💊",
        "#10b981",
        CategoryType.expense,
        ("Lékárna", "Dr.", "Nemocnice"),
    ),
    DefaultCategory(
        "Zábava",
        "🎮",
        "#ec4899",
        CategoryType.expense,
        ("Netflix", "Spotify", "Steam", "Cinema"),
    ),
    DefaultCategory(
        "Oblečení",
        "👕",
        "#f59e0b",
        CategoryType.expense,
        ("Zara", "H&M", "Reserved", "Vans"),
    ),
    DefaultCategory(
        "Elektronika",
        "💻",
        "#6366f1",
        CategoryType.expense,
        ("Alza", "CZC", "Datart", "Apple"),
    ),
    DefaultCategory(
        "Vzdělání",
        "📚",
        "#0891b2",
        CategoryType.expense,
        ("Udemy", "Coursera"),
    ),
    DefaultCategory(
        "Investice",
        "📈",
        "#16a34a",
        CategoryType.expense,
        ("Trading 212", "Anycoin"),
    ),
    DefaultCategory(
        "Potraviny",
        "🛒",
        "#f97316",
        CategoryType.expense,
        ("Albert", "Tesco", "Lidl", "Kaufland", "Billa", "Penny"),
    ),
    DefaultCategory("Ostatní výdaje", "💸", "#64748b", CategoryType.expense),
    DefaultCategory("Výplata", "💼", "#22c55e", CategoryType.income),
    DefaultCategory("Freelance", "🖥️", "#16a34a", CategoryType.income),
    DefaultCategory("Dividendy", "🏦", "#15803d", CategoryType.income, ("Dividenda",)),
    DefaultCategory("Ostatní příjmy", "💰", "#4ade80", CategoryType.income),
)


def _category_matches(row: CategoryModel, expected: DefaultCategory) -> bool:
    return (
        row.id == expected.id
        and row.name == expected.name
        and row.icon == expected.icon
        and row.color == expected.color
        and row.type is expected.type
        and row.parent_id is None
        and row.is_default is True
        and row.user_id is None
    )


def _rule_matches(row: CategoryRuleModel, category_id: str, keyword: str) -> bool:
    return (
        row.value == keyword
        and row.field is RuleField.counterparty
        and row.operator is RuleOperator.contains
        and row.classification is None
        and row.requires_review is False
        and row.priority == 0
        and row.user_id is None
        and row.category_id == category_id
    )


async def seed_defaults(session: AsyncSession, *, now: datetime) -> SeedResult:
    if now.tzinfo is not None or now.microsecond % 1_000 != 0:
        raise ValueError("Seed timestamp must be naive UTC at millisecond precision.")

    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('finance-app:seed-defaults:v1'))")
    )
    categories_created = categories_replayed = 0
    rules_created = rules_replayed = 0

    for expected in DEFAULT_CATEGORIES:
        category = await session.scalar(
            select(CategoryModel).where(CategoryModel.id == expected.id).with_for_update()
        )
        if category is None:
            session.add(
                CategoryModel(
                    id=expected.id,
                    name=expected.name,
                    icon=expected.icon,
                    color=expected.color,
                    type=expected.type,
                    parent_id=None,
                    is_default=True,
                    user_id=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            await session.flush()
            categories_created += 1
        elif _category_matches(category, expected):
            categories_replayed += 1
        else:
            raise DefaultSeedConflictError(
                f"Reserved category identity is inconsistent: {expected.id}"
            )

        for keyword in expected.keywords:
            rule_id = f"rule-{expected.name}-{keyword}"
            rule = await session.scalar(
                select(CategoryRuleModel).where(CategoryRuleModel.id == rule_id).with_for_update()
            )
            if rule is None:
                session.add(
                    CategoryRuleModel(
                        id=rule_id,
                        value=keyword,
                        field=RuleField.counterparty,
                        operator=RuleOperator.contains,
                        classification=None,
                        requires_review=False,
                        priority=0,
                        user_id=None,
                        category_id=expected.id,
                        created_at=now,
                        updated_at=now,
                    )
                )
                rules_created += 1
            elif _rule_matches(rule, expected.id, keyword):
                rules_replayed += 1
            else:
                raise DefaultSeedConflictError(f"Reserved category rule is inconsistent: {rule_id}")

    return SeedResult(
        categories_created=categories_created,
        categories_replayed=categories_replayed,
        rules_created=rules_created,
        rules_replayed=rules_replayed,
    )


async def run() -> SeedResult:
    database = create_database(Settings())
    if database is None:
        raise RuntimeError("DATABASE_URL is required for default seeding.")
    current = datetime.now(UTC).replace(tzinfo=None)
    now = current.replace(microsecond=(current.microsecond // 1_000) * 1_000)
    try:
        async with database.session_factory() as session:
            async with session.begin():
                return await seed_defaults(session, now=now)
    finally:
        await close_database(database)


def main() -> int:
    try:
        result = asyncio.run(run())
    except (SQLAlchemyError, ValidationError):
        print(json.dumps({"error": "Default seeding failed."}), file=sys.stderr)
        return 1
    except (DefaultSeedConflictError, RuntimeError, ValueError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
