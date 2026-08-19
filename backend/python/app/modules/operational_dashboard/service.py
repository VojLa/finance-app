from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.categories import CategoryModel
from app.db.models.enums import TransactionType
from app.modules.budgets.service import BudgetService, _money, month_range, transaction_czk
from app.modules.operational_dashboard.models import (
    OperationalBudgetItemResponse,
    OperationalBudgetResponse,
    OperationalDashboardResponse,
    OperationalExpenseCategoryResponse,
    OperationalMonthlyTrendResponse,
    OperationalRecentTransactionResponse,
    OperationalSummaryResponse,
)
from app.modules.operational_dashboard.repository import OperationalDashboardRepository

_MONTH_LABELS = ("led", "úno", "bře", "dub", "kvě", "čen", "čvc", "srp", "zář", "říj", "lis", "pro")


def _month_shift(month: int, year: int, offset: int) -> tuple[int, int]:
    index = year * 12 + month - 1 + offset
    return index % 12 + 1, index // 12


class OperationalDashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = OperationalDashboardRepository(session)

    async def read(
        self,
        *,
        principal: AuthenticatedPrincipal,
        now: datetime | None = None,
    ) -> OperationalDashboardResponse:
        current = now or datetime.now(UTC).replace(tzinfo=None)
        if current.tzinfo is not None:
            current = current.astimezone(UTC).replace(tzinfo=None)
        current_month, current_year = current.month, current.year
        first_month, first_year = _month_shift(current_month, current_year, -5)
        trend_start, _ = month_range(first_month, first_year)
        _, trend_end = month_range(current_month, current_year)
        current_start, current_end = month_range(current_month, current_year)
        account_ids = await self.repository.accessible_account_ids(principal.user_id)
        trend_rows = await self.repository.trend_transactions(
            account_ids=account_ids, start=trend_start, end=trend_end
        )
        recent_rows = await self.repository.recent_transactions(account_ids=account_ids, limit=6)

        months: dict[str, dict[str, Decimal | str]] = {}
        for offset in range(-5, 1):
            month, year = _month_shift(current_month, current_year, offset)
            key = f"{year:04d}-{month:02d}"
            months[key] = {
                "label": _MONTH_LABELS[month - 1],
                "income": Decimal(0),
                "expense": Decimal(0),
            }
        expense_categories: dict[str, tuple[CategoryModel | None, Decimal]] = {}
        for operational_transaction, category in trend_rows:
            transaction = operational_transaction.transaction
            if operational_transaction.effective_type not in {
                TransactionType.income,
                TransactionType.expense,
            }:
                continue
            amount = transaction_czk(operational_transaction)
            key = f"{transaction.date.year:04d}-{transaction.date.month:02d}"
            bucket = months.get(key)
            if bucket is None:
                continue
            if operational_transaction.effective_type is TransactionType.income:
                bucket["income"] = _money(Decimal(bucket["income"]) + amount)
            else:
                expense = -amount
                bucket["expense"] = _money(Decimal(bucket["expense"]) + expense)
                if current_start <= transaction.date < current_end:
                    category_key = transaction.category_id or "uncategorized"
                    previous = expense_categories.get(category_key, (category, Decimal(0)))[1]
                    expense_categories[category_key] = (category, _money(previous + expense))

        monthly_trends = [
            OperationalMonthlyTrendResponse(
                month=key,
                label=str(bucket["label"]),
                income_czk=_money(Decimal(bucket["income"])),
                expense_czk=_money(Decimal(bucket["expense"])),
                net_czk=_money(Decimal(bucket["income"]) - Decimal(bucket["expense"])),
            )
            for key, bucket in months.items()
        ]
        current_trend = monthly_trends[-1]
        budget = await BudgetService(self.session).get_progress(
            principal=principal, month=current_month, year=current_year
        )
        operational_budget = (
            None
            if budget is None
            else OperationalBudgetResponse(
                id=budget.id,
                month=budget.month,
                year=budget.year,
                limit_czk=budget.total_limit,
                spent_czk=budget.total_spent,
                remaining_czk=budget.total_remaining,
                progress_pct=budget.progress_pct,
                items=[
                    OperationalBudgetItemResponse(
                        id=item.id,
                        category_id=item.category_id,
                        name=item.category.name,
                        icon=item.category.icon,
                        color=item.category.color,
                        limit_czk=item.effective_amount,
                        spent_czk=item.spent,
                        remaining_czk=item.remaining,
                        progress_pct=item.progress_pct,
                        is_over=item.is_over,
                    )
                    for item in sorted(
                        budget.items, key=lambda value: (-value.progress_pct, value.id)
                    )
                ],
            )
        )
        return OperationalDashboardResponse(
            summary=OperationalSummaryResponse(
                current_month_income_czk=current_trend.income_czk,
                current_month_expense_czk=current_trend.expense_czk,
                current_month_net_czk=current_trend.net_czk,
            ),
            budget=operational_budget,
            expense_by_category=[
                OperationalExpenseCategoryResponse(
                    category_id=None if key == "uncategorized" else key,
                    name="Bez kategorie" if category is None else category.name,
                    icon=None if category is None else category.icon,
                    color=None if category is None else category.color,
                    amount_czk=amount,
                )
                for key, (category, amount) in sorted(
                    expense_categories.items(), key=lambda value: (-value[1][1], value[0])
                )
            ],
            monthly_trends=monthly_trends,
            recent_transactions=[
                OperationalRecentTransactionResponse(
                    id=operational_transaction.transaction.id,
                    date=operational_transaction.transaction.date,
                    amount=abs(operational_transaction.transaction.amount),
                    amount_czk=abs(transaction_czk(operational_transaction)),
                    currency=operational_transaction.transaction.currency,
                    type=operational_transaction.effective_type.value,
                    description=operational_transaction.transaction.description,
                    counterparty=operational_transaction.transaction.counterparty,
                    account_name=account.name,
                    category_name=None if category is None else category.name,
                    category_icon=None if category is None else category.icon,
                )
                for operational_transaction, account, category in recent_rows
            ],
        )
