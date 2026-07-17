from decimal import Decimal
from typing import Any

import asyncpg


def to_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    return float(value)


class PortfolioRepository:
    def __init__(self, connection: asyncpg.Connection):
        self.connection = connection

    async def accessible_accounts(self, user_id: str, account_id: str | None = None):
        rows = await self.connection.fetch(
            """
            SELECT a."id", a."name", a."type"::text AS "type", a."currency"
            FROM "Account" a
            JOIN "AccountMember" am ON am."accountId" = a."id"
            WHERE am."userId" = $1
              AND a."isArchived" = false
              AND ($2::text IS NULL OR a."id" = $2)
            ORDER BY a."createdAt" ASC
            """,
            user_id,
            account_id,
        )
        return [dict(row) for row in rows]

    async def holdings_for_accounts(self, account_ids: list[str]):
        if not account_ids:
            return []

        rows = await self.connection.fetch(
            """
            SELECT
              h."id",
              h."accountId" AS "account_id",
              a."name" AS "account_name",
              a."currency" AS "account_currency",
              h."symbol",
              h."name",
              h."assetType"::text AS "asset_type",
              h."quantity",
              h."avgBuyPrice" AS "avg_buy_price",
              h."currency",
              h."listingId" AS "listing_id"
            FROM "Holding" h
            JOIN "Account" a ON a."id" = h."accountId"
            WHERE h."accountId" = ANY($1::text[])
            ORDER BY a."createdAt" ASC, h."symbol" ASC
            """,
            account_ids,
        )
        return [dict(row) for row in rows]

    async def latest_exchange_rates(self, currency_pairs: list[tuple[str, str]]):
        unique_pairs = sorted(
            {(from_currency, to_currency) for from_currency, to_currency in currency_pairs}
        )
        rates: dict[tuple[str, str], float] = {}

        for from_currency, to_currency in unique_pairs:
            if from_currency == to_currency:
                rates[(from_currency, to_currency)] = 1.0
                continue

            row = await self.connection.fetchrow(
                """
                SELECT "rate"
                FROM "ExchangeRate"
                WHERE "fromCurrency" = $1
                  AND "toCurrency" = $2
                ORDER BY "date" DESC
                LIMIT 1
                """,
                from_currency,
                to_currency,
            )
            if row:
                rates[(from_currency, to_currency)] = to_float(row["rate"])

        return rates
