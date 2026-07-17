import asyncio
from decimal import Decimal

from app.modules.portfolio.contracts import AccountRow, HoldingRow
from app.modules.portfolio.service import PortfolioService


class FakePortfolioRepository:
    async def accessible_accounts(
        self,
        user_id: str,
        account_id: str | None = None,
    ) -> list[AccountRow]:
        assert user_id == "user-1"
        assert account_id is None
        return [
            AccountRow(id="account-1", name="Broker", type="broker", currency="EUR"),
        ]

    async def holdings_for_accounts(self, account_ids: list[str]) -> list[HoldingRow]:
        assert account_ids == ["account-1"]
        return [
            HoldingRow(
                id="holding-1",
                account_id="account-1",
                account_name="Broker",
                account_currency="EUR",
                symbol="VUAA",
                name="Vanguard S&P 500",
                asset_type="etf",
                quantity=Decimal("2"),
                avg_buy_price=Decimal("100"),
                currency="USD",
                listing_id="listing-1",
            )
        ]

    async def latest_exchange_rates(
        self,
        currency_pairs: list[tuple[str, str]],
    ) -> dict[tuple[str, str], float]:
        assert currency_pairs == [("USD", "EUR")]
        return {("USD", "EUR"): 0.9}


def test_portfolio_service_converts_cost_to_account_currency() -> None:
    service = PortfolioService(FakePortfolioRepository())

    summary = asyncio.run(service.get_portfolio("user-1"))

    assert summary.display_currency == "EUR"
    assert summary.total_cost == 180
    assert summary.holdings[0].cost_value == 200
    assert summary.holdings[0].cost_value_account_currency == 180
