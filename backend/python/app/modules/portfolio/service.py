from app.modules.portfolio.models import AccountSummary, HoldingSummary, PortfolioSummary
from app.modules.portfolio.repository import PortfolioRepository, to_float


class PortfolioService:
    def __init__(self, repository: PortfolioRepository):
        self.repository = repository

    async def get_portfolio(self, user_id: str, account_id: str | None = None) -> PortfolioSummary:
        accounts_raw = await self.repository.accessible_accounts(user_id, account_id)
        account_ids = [account["id"] for account in accounts_raw]
        holdings_raw = await self.repository.holdings_for_accounts(account_ids)

        pairs = [
            (holding["currency"], holding["account_currency"])
            for holding in holdings_raw
            if holding["currency"] != holding["account_currency"]
        ]
        rates = await self.repository.latest_exchange_rates(pairs)

        holdings: list[HoldingSummary] = []
        warnings: list[str] = []
        total_cost = 0.0

        for holding in holdings_raw:
            quantity = to_float(holding["quantity"])
            avg_buy_price = to_float(holding["avg_buy_price"])
            cost_value = quantity * avg_buy_price
            pair = (holding["currency"], holding["account_currency"])
            rate = 1.0 if pair[0] == pair[1] else rates.get(pair)

            if rate is None:
                rate = 1.0
                warnings.append(
                    f"Missing FX rate {pair[0]}->{pair[1]} for holding {holding['symbol']}."
                )

            cost_value_account_currency = cost_value * rate
            total_cost += cost_value_account_currency

            holdings.append(
                HoldingSummary(
                    id=holding["id"],
                    account_id=holding["account_id"],
                    account_name=holding["account_name"],
                    symbol=holding["symbol"],
                    name=holding["name"],
                    asset_type=holding["asset_type"],
                    quantity=quantity,
                    avg_buy_price=avg_buy_price,
                    currency=holding["currency"],
                    listing_id=holding["listing_id"],
                    cost_value=cost_value,
                    cost_value_account_currency=cost_value_account_currency,
                    account_currency=holding["account_currency"],
                )
            )

        display_currency = accounts_raw[0]["currency"] if len(accounts_raw) == 1 else "mixed"

        return PortfolioSummary(
            display_currency=display_currency,
            total_cost=total_cost,
            accounts=[AccountSummary(**account) for account in accounts_raw],
            holdings=holdings,
            warnings=warnings,
        )
