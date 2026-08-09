from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from uuid import UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import AuthenticatedPrincipal
from app.db.models.budgets import (
    BudgetAccountModel,
    BudgetItemCategoryModel,
    BudgetItemModel,
    BudgetModel,
)
from app.db.models.enums import BudgetPeriodType, CategoryType, TransactionType
from app.db.models.transactions import TransactionModel
from app.modules.budgets.models import (
    BudgetAlertResponse,
    BudgetCategoryResponse,
    BudgetProgressItemResponse,
    BudgetProgressResponse,
    BudgetSaveRequest,
)
from app.modules.budgets.repository import BudgetRepository
from app.shared.errors import ApplicationError
from app.shared.numeric_serialization import serialize_money, serialize_percentage

_BUDGET_NAMESPACE = UUID("4d762b9e-2225-5d09-81e8-c4ed0b853d53")
_APPROACHING = Decimal("0.8000")


class BudgetUnavailableError(ApplicationError):
    def __init__(
        self, message: str = "Budget progress cannot be produced from persisted evidence."
    ) -> None:
        super().__init__(code="budget_unavailable", message=message, status_code=409)


class BudgetCategoryError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            code="budget_category_invalid",
            message="A budget category is unavailable or incompatible.",
            status_code=422,
        )


def month_range(month: int, year: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def previous_month(month: int, year: int) -> tuple[int, int]:
    return (12, year - 1) if month == 1 else (month - 1, year)


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def _money(value: Decimal) -> Decimal:
    try:
        serialize_money(value)
    except ValueError as exc:
        raise BudgetUnavailableError() from exc
    return value


def _percentage(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= 0:
        return Decimal("0.0000")
    with localcontext() as context:
        context.prec = 48
        value = min(Decimal(100), numerator * Decimal(100) / denominator).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
    try:
        serialize_percentage(value)
    except ValueError as exc:
        raise BudgetUnavailableError() from exc
    return value


def transaction_czk(transaction: TransactionModel) -> Decimal:
    if transaction.currency == "CZK":
        value = transaction.amount
    elif transaction.reporting_currency == "CZK" and transaction.reporting_amount is not None:
        value = transaction.reporting_amount
    else:
        raise BudgetUnavailableError("A transaction has no persisted CZK representation.")
    value = _money(value)
    if transaction.type is TransactionType.expense and value >= 0:
        raise BudgetUnavailableError()
    if transaction.type is TransactionType.income and value <= 0:
        raise BudgetUnavailableError()
    return value


class BudgetService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = BudgetRepository(session)

    async def get_progress(
        self, *, principal: AuthenticatedPrincipal, month: int, year: int
    ) -> BudgetProgressResponse | None:
        return await self._build_progress(user_id=principal.user_id, month=month, year=year)

    async def save(
        self, *, principal: AuthenticatedPrincipal, payload: BudgetSaveRequest
    ) -> BudgetProgressResponse:
        await self.repository.lock_month(principal.user_id, payload.month, payload.year)
        start, end = month_range(payload.month, payload.year)
        budget = await self.repository.load_budget(
            user_id=principal.user_id, start=start, end=end, for_update=True
        )
        now = _now()
        if budget is None:
            budget_id = str(
                uuid5(
                    _BUDGET_NAMESPACE,
                    f"budget:{principal.user_id}:{payload.year:04d}-{payload.month:02d}",
                )
            )
            budget = BudgetModel(
                id=budget_id,
                name="Monthly budget",
                period_start=start,
                period_end=end,
                period_type=BudgetPeriodType.monthly,
                currency="CZK",
                rollover_enabled=payload.rollover,
                user_id=principal.user_id,
                created_at=now,
                updated_at=now,
            )
            self.repository.add(budget)
            await self.session.flush()
        else:
            budget.rollover_enabled = payload.rollover
            budget.updated_at = now

        category_ids = tuple(item.category_id for item in payload.items)
        categories = {
            category.id: category
            for category in await self.repository.accessible_categories(
                user_id=principal.user_id, category_ids=category_ids
            )
        }
        if len(categories) != len(category_ids) or any(
            categories[category_id].type not in {CategoryType.expense, CategoryType.both}
            for category_id in category_ids
        ):
            await self.session.rollback()
            raise BudgetCategoryError()

        account_ids = await self.repository.accessible_account_ids(principal.user_id)
        rollover_by_category: dict[str, Decimal] = {}
        if payload.rollover:
            previous_month_value, previous_year = previous_month(payload.month, payload.year)
            previous = await self._build_progress(
                user_id=principal.user_id,
                month=previous_month_value,
                year=previous_year,
            )
            if previous is not None:
                rollover_by_category = {item.category_id: item.remaining for item in previous.items}

        await self.repository.replace_children(budget.id)
        for account_id in account_ids:
            self.repository.add(
                BudgetAccountModel(
                    id=str(uuid5(_BUDGET_NAMESPACE, f"budget-account:{budget.id}:{account_id}")),
                    budget_id=budget.id,
                    account_id=account_id,
                    created_at=now,
                )
            )
        for item in payload.items:
            item_id = str(uuid5(_BUDGET_NAMESPACE, f"budget-item:{budget.id}:{item.category_id}"))
            self.repository.add(
                BudgetItemModel(
                    id=item_id,
                    name=None,
                    amount=item.amount,
                    currency="CZK",
                    rollover_amount=rollover_by_category.get(item.category_id, Decimal(0)),
                    budget_id=budget.id,
                    created_at=now,
                    updated_at=now,
                )
            )
            # The schema mirror intentionally has no ORM relationships, so make
            # the parent row visible before inserting its explicit link row.
            await self.session.flush()
            self.repository.add(
                BudgetItemCategoryModel(
                    id=str(
                        uuid5(_BUDGET_NAMESPACE, f"budget-category:{item_id}:{item.category_id}")
                    ),
                    budget_item_id=item_id,
                    category_id=item.category_id,
                    created_at=now,
                )
            )
        await self.session.flush()
        result = await self._build_progress(
            user_id=principal.user_id, month=payload.month, year=payload.year
        )
        if result is None:
            await self.session.rollback()
            raise BudgetUnavailableError()
        try:
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return result

    async def _build_progress(
        self, *, user_id: str, month: int, year: int
    ) -> BudgetProgressResponse | None:
        start, end = month_range(month, year)
        budget = await self.repository.load_budget(user_id=user_id, start=start, end=end)
        if budget is None:
            return None
        rows = await self.repository.items_with_categories(budget.id)
        account_ids = await self.repository.budget_account_ids(budget.id)
        if not account_ids:
            account_ids = await self.repository.accessible_account_ids(user_id)
        category_ids = tuple(category.id for _, category in rows)
        spent = {category_id: Decimal(0) for category_id in category_ids}
        for transaction in await self.repository.expense_transactions(
            account_ids=account_ids,
            category_ids=category_ids,
            start=start,
            end=end,
        ):
            if transaction.category_id is None:
                raise BudgetUnavailableError()
            spent[transaction.category_id] = _money(
                spent[transaction.category_id] - transaction_czk(transaction)
            )

        items: list[BudgetProgressItemResponse] = []
        alerts: list[BudgetAlertResponse] = []
        for item, category in rows:
            amount = _money(item.amount)
            rollover = _money(item.rollover_amount or Decimal(0))
            effective = _money(amount + rollover)
            item_spent = _money(spent[category.id])
            remaining = _money(effective - item_spent)
            progress = _percentage(item_spent, effective)
            ratio = item_spent / effective if effective > 0 else Decimal(0)
            is_over = item_spent > effective
            is_approaching = effective > 0 and ratio >= _APPROACHING
            response = BudgetProgressItemResponse(
                id=item.id,
                amount=amount,
                rollover_amount=rollover,
                effective_amount=effective,
                spent=item_spent,
                remaining=remaining,
                progress_pct=progress,
                is_approaching=is_approaching,
                is_over=is_over,
                currency=item.currency,
                category_id=category.id,
                category=BudgetCategoryResponse(
                    id=category.id,
                    name=category.name,
                    icon=category.icon,
                    color=category.color,
                ),
            )
            items.append(response)
            if is_over or is_approaching:
                alert_type = "exceeded" if is_over else "approaching_limit"
                alerts.append(
                    BudgetAlertResponse(
                        id=f"budget-alert:{item.id}:{alert_type}",
                        type=alert_type,
                        category_id=category.id,
                        category_name=category.name,
                        threshold=Decimal("1.0000") if is_over else _APPROACHING,
                        triggered_at=item.updated_at,
                        acknowledged_at=None,
                    )
                )

        total_base = _money(sum((item.amount for item in items), Decimal(0)))
        total_rollover = _money(sum((item.rollover_amount for item in items), Decimal(0)))
        total_limit = _money(sum((item.effective_amount for item in items), Decimal(0)))
        total_spent = _money(sum((item.spent for item in items), Decimal(0)))
        return BudgetProgressResponse(
            id=budget.id,
            month=month,
            year=year,
            period_type=budget.period_type.value,
            currency=budget.currency,
            rollover=budget.rollover_enabled,
            account_ids=list(account_ids),
            total_limit=total_limit,
            total_base_limit=total_base,
            total_rollover=total_rollover,
            total_spent=total_spent,
            total_remaining=_money(total_limit - total_spent),
            progress_pct=_percentage(total_spent, total_limit),
            is_over=total_spent > total_limit,
            alerts=alerts,
            items=items,
        )
