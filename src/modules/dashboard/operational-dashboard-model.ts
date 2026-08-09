import type {
  OperationalBudget,
  OperationalBudgetItem,
  OperationalDashboardData,
  OperationalExpenseCategory,
  OperationalMonthlyTrend,
  OperationalRecentTransaction,
  OperationalDashboardResponse,
} from "./operational-dashboard-contract"

export class OperationalDashboardContractError extends Error {
  constructor() {
    super("Operational dashboard response is incompatible.")
    this.name = "OperationalDashboardContractError"
  }
}

function fail(): never {
  throw new OperationalDashboardContractError()
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return fail()
  return value as Record<string, unknown>
}

function array(value: unknown): unknown[] {
  if (!Array.isArray(value)) return fail()
  return value
}

function text(value: unknown): string {
  if (typeof value !== "string") return fail()
  return value
}

function nullableText(value: unknown): string | null {
  if (value === null) return null
  return text(value)
}

function exactNumber(value: unknown, scale: number): number {
  if (
    typeof value !== "string" ||
    !new RegExp(`^-?(?:0|[1-9][0-9]{0,11})\\.[0-9]{${scale}}$`).test(value)
  ) {
    return fail()
  }
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return fail()
  return parsed
}

function number(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fail()
  return value
}

function integer(value: unknown): number {
  const parsed = number(value)
  if (!Number.isSafeInteger(parsed)) return fail()
  return parsed
}

function boolean(value: unknown): boolean {
  if (typeof value !== "boolean") return fail()
  return value
}

function budgetItem(value: unknown): OperationalBudgetItem {
  const item = record(value)
  return {
    id: text(item.id),
    categoryId: text(item.categoryId),
    name: text(item.name),
    icon: nullableText(item.icon),
    color: nullableText(item.color),
    limitCzk: exactNumber(item.limitCzk, 6),
    spentCzk: exactNumber(item.spentCzk, 6),
    remainingCzk: exactNumber(item.remainingCzk, 6),
    progressPct: exactNumber(item.progressPct, 4),
    isOver: boolean(item.isOver),
  }
}

function budget(value: unknown): OperationalBudget | null {
  if (value === null) return null
  const source = record(value)
  return {
    id: text(source.id),
    month: integer(source.month),
    year: integer(source.year),
    limitCzk: exactNumber(source.limitCzk, 6),
    spentCzk: exactNumber(source.spentCzk, 6),
    remainingCzk: exactNumber(source.remainingCzk, 6),
    progressPct: exactNumber(source.progressPct, 4),
    items: array(source.items).map(budgetItem),
  }
}

function expenseCategory(value: unknown): OperationalExpenseCategory {
  const source = record(value)
  return {
    categoryId: nullableText(source.categoryId),
    name: text(source.name),
    icon: nullableText(source.icon),
    color: nullableText(source.color),
    amountCzk: exactNumber(source.amountCzk, 6),
  }
}

function monthlyTrend(value: unknown): OperationalMonthlyTrend {
  const source = record(value)
  return {
    month: text(source.month),
    label: text(source.label),
    incomeCzk: exactNumber(source.incomeCzk, 6),
    expenseCzk: exactNumber(source.expenseCzk, 6),
    netCzk: exactNumber(source.netCzk, 6),
  }
}

function recentTransaction(value: unknown): OperationalRecentTransaction {
  const source = record(value)
  return {
    id: text(source.id),
    date: text(source.date),
    amount: exactNumber(source.amount, 6),
    amountCzk: exactNumber(source.amountCzk, 6),
    currency: text(source.currency),
    type: text(source.type),
    description: nullableText(source.description),
    counterparty: nullableText(source.counterparty),
    accountName: text(source.accountName),
    categoryName: nullableText(source.categoryName),
    categoryIcon: nullableText(source.categoryIcon),
  }
}

export function buildOperationalDashboardData(
  value: OperationalDashboardResponse
): OperationalDashboardData {
  const source = record(value)
  const summary = record(source.summary)
  return {
    currentMonth: {
      income: exactNumber(summary.currentMonthIncomeCzk, 6),
      expenses: exactNumber(summary.currentMonthExpenseCzk, 6),
      net: exactNumber(summary.currentMonthNetCzk, 6),
    },
    budget: budget(source.budget),
    expenseByCategory: array(source.expenseByCategory).map(expenseCategory),
    monthlyTrends: array(source.monthlyTrends).map(monthlyTrend),
    recentTransactions: array(source.recentTransactions).map(recentTransaction),
  }
}
