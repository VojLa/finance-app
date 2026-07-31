import type {
  OperationalBudget,
  OperationalBudgetItem,
  OperationalDashboardData,
  OperationalExpenseCategory,
  OperationalMonthlyTrend,
  OperationalRecentTransaction,
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
    limitCzk: number(item.limitCzk),
    spentCzk: number(item.spentCzk),
    remainingCzk: number(item.remainingCzk),
    progressPct: number(item.progressPct),
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
    limitCzk: number(source.limitCzk),
    spentCzk: number(source.spentCzk),
    remainingCzk: number(source.remainingCzk),
    progressPct: number(source.progressPct),
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
    amountCzk: number(source.amountCzk),
  }
}

function monthlyTrend(value: unknown): OperationalMonthlyTrend {
  const source = record(value)
  return {
    month: text(source.month),
    label: text(source.label),
    incomeCzk: number(source.incomeCzk),
    expenseCzk: number(source.expenseCzk),
    netCzk: number(source.netCzk),
  }
}

function recentTransaction(value: unknown): OperationalRecentTransaction {
  const source = record(value)
  return {
    id: text(source.id),
    date: text(source.date),
    amount: number(source.amount),
    amountCzk: number(source.amountCzk),
    currency: text(source.currency),
    type: text(source.type),
    description: nullableText(source.description),
    counterparty: nullableText(source.counterparty),
    accountName: text(source.accountName),
    categoryName: nullableText(source.categoryName),
    categoryIcon: nullableText(source.categoryIcon),
  }
}

export function buildOperationalDashboardData(value: unknown): OperationalDashboardData {
  const source = record(value)
  const summary = record(source.summary)
  return {
    currentMonth: {
      income: number(summary.currentMonthIncomeCzk),
      expenses: number(summary.currentMonthExpenseCzk),
      net: number(summary.currentMonthNetCzk),
    },
    budget: budget(source.budget),
    expenseByCategory: array(source.expenseByCategory).map(expenseCategory),
    monthlyTrends: array(source.monthlyTrends).map(monthlyTrend),
    recentTransactions: array(source.recentTransactions).map(recentTransaction),
  }
}
