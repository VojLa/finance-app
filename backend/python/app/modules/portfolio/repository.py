from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AccountMemberModel, AccountModel, ExchangeRateModel, HoldingModel
from app.modules.portfolio.contracts import AccountRow, HoldingRow
from app.modules.portfolio.conversions import to_float


def _enum_value(value: StrEnum | str) -> str:
    return value.value if isinstance(value, StrEnum) else value


class PortfolioRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def accessible_accounts(
        self,
        user_id: str,
        account_id: str | None = None,
    ) -> list[AccountRow]:
        statement = (
            select(
                AccountModel.id,
                AccountModel.name,
                AccountModel.type,
                AccountModel.currency,
            )
            .join(
                AccountMemberModel,
                AccountMemberModel.account_id == AccountModel.id,
            )
            .where(
                AccountMemberModel.user_id == user_id,
                AccountModel.is_archived.is_(False),
            )
            .order_by(AccountModel.created_at.asc())
        )
        if account_id is not None:
            statement = statement.where(AccountModel.id == account_id)

        rows = (await self.session.execute(statement)).all()
        return [
            AccountRow(
                id=row.id,
                name=row.name,
                type=_enum_value(row.type),
                currency=row.currency,
            )
            for row in rows
        ]

    async def holdings_for_accounts(self, account_ids: list[str]) -> list[HoldingRow]:
        if not account_ids:
            return []

        statement = (
            select(
                HoldingModel.id,
                HoldingModel.account_id,
                AccountModel.name.label("account_name"),
                AccountModel.currency.label("account_currency"),
                HoldingModel.symbol,
                HoldingModel.name,
                HoldingModel.asset_type,
                HoldingModel.quantity,
                HoldingModel.avg_buy_price,
                HoldingModel.currency,
                HoldingModel.listing_id,
            )
            .join(AccountModel, AccountModel.id == HoldingModel.account_id)
            .where(HoldingModel.account_id.in_(account_ids))
            .order_by(AccountModel.created_at.asc(), HoldingModel.symbol.asc())
        )
        rows = (await self.session.execute(statement)).all()
        return [
            HoldingRow(
                id=row.id,
                account_id=row.account_id,
                account_name=row.account_name,
                account_currency=row.account_currency,
                symbol=row.symbol,
                name=row.name,
                asset_type=_enum_value(row.asset_type),
                quantity=row.quantity,
                avg_buy_price=row.avg_buy_price,
                currency=row.currency,
                listing_id=row.listing_id,
            )
            for row in rows
        ]

    async def latest_exchange_rates(
        self,
        currency_pairs: list[tuple[str, str]],
    ) -> dict[tuple[str, str], float]:
        unique_pairs = sorted(set(currency_pairs))
        rates: dict[tuple[str, str], float] = {}

        for from_currency, to_currency in unique_pairs:
            if from_currency == to_currency:
                rates[(from_currency, to_currency)] = 1.0
                continue

            statement = (
                select(ExchangeRateModel.rate)
                .where(
                    ExchangeRateModel.from_currency == from_currency,
                    ExchangeRateModel.to_currency == to_currency,
                )
                .order_by(ExchangeRateModel.date.desc())
                .limit(1)
            )
            rate = (await self.session.execute(statement)).scalar_one_or_none()
            if rate is not None:
                rates[(from_currency, to_currency)] = to_float(rate)

        return rates
