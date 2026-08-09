"""Read-only audit of persisted exchange-rate source collisions and invalid rows."""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config.settings import Settings  # noqa: E402
from app.db.url import normalize_database_url  # noqa: E402


@dataclass(frozen=True, slots=True)
class SourceCount:
    source: str
    count: int


@dataclass(frozen=True, slots=True)
class SourceCollision:
    from_currency: str
    to_currency: str
    observed_at: str
    sources: tuple[str, ...]
    row_count: int


@dataclass(frozen=True, slots=True)
class ExchangeRateAuditReport:
    total_rows: int
    source_counts: tuple[SourceCount, ...]
    source_collisions: tuple[SourceCollision, ...]
    duplicate_source_identities: int
    invalid_rows: int


def build_report(
    *,
    source_rows: list[tuple[str, int]],
    collision_rows: list[tuple[str, str, datetime, list[str], int]],
    duplicate_source_identities: int,
    invalid_rows: int,
) -> ExchangeRateAuditReport:
    source_counts = tuple(SourceCount(source, count) for source, count in source_rows)
    collisions = tuple(
        SourceCollision(
            from_currency=from_currency,
            to_currency=to_currency,
            observed_at=observed_at.isoformat(),
            sources=tuple(sources),
            row_count=row_count,
        )
        for from_currency, to_currency, observed_at, sources, row_count in collision_rows
    )
    return ExchangeRateAuditReport(
        total_rows=sum(item.count for item in source_counts),
        source_counts=source_counts,
        source_collisions=collisions,
        duplicate_source_identities=duplicate_source_identities,
        invalid_rows=invalid_rows,
    )


async def audit(database_url: str) -> ExchangeRateAuditReport:
    engine = create_async_engine(normalize_database_url(database_url))
    try:
        async with engine.connect() as connection:
            async with connection.begin():
                await connection.execute(text("SET TRANSACTION READ ONLY"))
                source_rows = [
                    (str(source), int(count))
                    for source, count in (
                        await connection.execute(
                            text(
                                "SELECT source::text, COUNT(*) "
                                'FROM "ExchangeRate" GROUP BY source ORDER BY source::text'
                            )
                        )
                    ).all()
                ]
                collision_rows = [
                    (
                        str(from_currency),
                        str(to_currency),
                        observed_at,
                        [str(source) for source in sources],
                        int(row_count),
                    )
                    for from_currency, to_currency, observed_at, sources, row_count in (
                        await connection.execute(
                            text(
                                'SELECT "fromCurrency", "toCurrency", date, '
                                "array_agg(source::text ORDER BY source::text), COUNT(*) "
                                'FROM "ExchangeRate" '
                                'GROUP BY "fromCurrency", "toCurrency", date '
                                "HAVING COUNT(DISTINCT source) > 1 "
                                'ORDER BY date, "fromCurrency", "toCurrency"'
                            )
                        )
                    ).all()
                ]
                duplicate_source_identities = int(
                    await connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM ("
                            'SELECT 1 FROM "ExchangeRate" '
                            'GROUP BY "fromCurrency", "toCurrency", date, source '
                            "HAVING COUNT(*) > 1"
                            ") duplicates"
                        )
                    )
                    or 0
                )
                invalid_rows = int(
                    await connection.scalar(
                        text(
                            'SELECT COUNT(*) FROM "ExchangeRate" '
                            'WHERE rate <= 0 OR "fromCurrency" = "toCurrency"'
                        )
                    )
                    or 0
                )
        return build_report(
            source_rows=source_rows,
            collision_rows=collision_rows,
            duplicate_source_identities=duplicate_source_identities,
            invalid_rows=invalid_rows,
        )
    finally:
        await engine.dispose()


def main() -> int:
    settings = Settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required for the exchange-rate audit.")
    report = asyncio.run(audit(settings.database_url))
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
