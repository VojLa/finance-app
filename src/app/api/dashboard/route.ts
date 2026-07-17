import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma, toNum } from "@/lib/prisma"
import { getCzkRates, toCzk } from "@/modules/portfolio/rates/service"
import { getAccessibleAccountIds } from "@/lib/accountAccess"
import { getBudgetProgress } from "@/modules/budgets"

const BANK_ACCOUNT_TYPES = new Set(["bank", "cash", "savings"])
const INVESTMENT_ACCOUNT_TYPES = new Set(["broker", "exchange", "crypto_wallet"])
const LIABILITY_ACCOUNT_TYPES = new Set(["credit_card", "loan", "mortgage"])

function monthStart(date: Date) {
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

function monthKey(date: Date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`
}

function monthLabel(date: Date) {
  return date.toLocaleDateString("cs-CZ", { month: "short" }).replace(".", "")
}

function transactionAmountCzk(
  tx: {
    amount: unknown
    reportingAmount: unknown
    reportingCurrency: string | null
    currency: string
  },
  czkRates: Record<string, number>
) {
  const converted = toNum(tx.reportingAmount as never)
  if (converted && tx.reportingCurrency === "CZK") return converted
  return toCzk(toNum(tx.amount as never), tx.currency, czkRates)
}

export async function GET() {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const now = new Date()
  const currentMonth = now.getMonth() + 1
  const currentYear = now.getFullYear()
  const currentStart = monthStart(now)
  const trendStart = new Date(currentYear, now.getMonth() - 5, 1)
  const trendEnd = new Date(currentYear, now.getMonth() + 1, 1)

  const accessibleIds = await getAccessibleAccountIds(session.user.id, "viewer")
  const [accounts, czkRates] = await Promise.all([
    prisma.account.findMany({
      where: { id: { in: accessibleIds } },
      orderBy: { createdAt: "asc" },
    }),
    getCzkRates(),
  ])

  const accountIds = accounts.map((account) => account.id)

  if (accountIds.length === 0) {
    return NextResponse.json({
      summary: {
        cashValueCzk: 0,
        portfolioValueCzk: 0,
        liabilitiesValueCzk: 0,
        netWorthCzk: 0,
        currentMonthIncomeCzk: 0,
        currentMonthExpenseCzk: 0,
        currentMonthNetCzk: 0,
      },
      accountBalances: [],
      budget: null,
      expenseByCategory: [],
      monthlyTrends: [],
      recentTransactions: [],
      czkRates,
    })
  }

  const balanceAccountIds = accounts
    .filter(
      (account) => BANK_ACCOUNT_TYPES.has(account.type) || LIABILITY_ACCOUNT_TYPES.has(account.type)
    )
    .map((account) => account.id)
  const investmentAccountIds = accounts
    .filter((account) => INVESTMENT_ACCOUNT_TYPES.has(account.type))
    .map((account) => account.id)

  const [
    balanceTransactions,
    investmentCashTransactions,
    holdings,
    budgetProgress,
    trendTransactions,
    recentTransactions,
  ] = await Promise.all([
    prisma.transaction.findMany({
      where: {
        accountId: { in: balanceAccountIds },
        type: { in: ["income", "expense"] },
      },
      select: {
        accountId: true,
        type: true,
        amount: true,
        reportingAmount: true,
        reportingCurrency: true,
        currency: true,
      },
    }),
    prisma.investmentMovement.findMany({
      where: {
        accountId: { in: investmentAccountIds },
        kind: { in: ["cash", "fee", "tax"] },
        event: { deletedAt: null, archivedAt: null },
      },
      select: {
        accountId: true,
        direction: true,
        quantity: true,
        currency: true,
      },
    }),
    prisma.holding.findMany({
      where: { accountId: { in: accountIds } },
      select: {
        accountId: true,
        symbol: true,
        quantity: true,
        avgBuyPrice: true,
        currency: true,
        currentValue: true,
      },
    }),
    getBudgetProgress({ userId: session.user.id, month: currentMonth, year: currentYear }),
    prisma.transaction.findMany({
      where: {
        accountId: { in: accountIds },
        type: { in: ["income", "expense"] },
        date: { gte: trendStart, lt: trendEnd },
      },
      include: {
        category: { select: { id: true, name: true, icon: true, color: true } },
      },
      orderBy: { date: "asc" },
    }),
    prisma.transaction.findMany({
      where: { accountId: { in: accountIds } },
      include: {
        category: { select: { id: true, name: true, icon: true, color: true } },
        account: { select: { name: true, currency: true } },
      },
      orderBy: { date: "desc" },
      take: 6,
    }),
  ])

  const accountBalances = accounts.map((account) => ({
    accountId: account.id,
    accountName: account.name,
    accountType: account.type,
    currency: account.currency,
    color: account.color,
    totalCzk: 0,
    balances: {} as Record<string, number>,
  }))
  const accountBalanceMap = new Map(accountBalances.map((account) => [account.accountId, account]))

  for (const tx of balanceTransactions) {
    const balance = accountBalanceMap.get(tx.accountId)
    if (!balance) continue

    const nativeAmount = toNum(tx.amount)
    const signedNative = tx.type === "income" ? nativeAmount : -nativeAmount
    const signedCzk =
      tx.type === "income"
        ? transactionAmountCzk(tx, czkRates)
        : -transactionAmountCzk(tx, czkRates)

    balance.totalCzk += signedCzk
    balance.balances[tx.currency] = (balance.balances[tx.currency] ?? 0) + signedNative
  }

  for (const tx of investmentCashTransactions) {
    const balance = accountBalanceMap.get(tx.accountId)
    if (!balance) continue

    const amount = Math.abs(toNum(tx.quantity))
    const direction = tx.direction === "in" ? 1 : -1

    const signedNative = amount * direction
    const signedCzk = toCzk(signedNative, tx.currency, czkRates)

    balance.totalCzk += signedCzk
    balance.balances[tx.currency] = (balance.balances[tx.currency] ?? 0) + signedNative
  }

  const serializedAccountBalances = accountBalances
    .map((account) => ({
      ...account,
      balances: Object.entries(account.balances)
        .filter(([, amount]) => Math.abs(amount) >= 0.01)
        .map(([currency, amount]) => ({
          currency,
          amount,
          amountCzk: toCzk(amount, currency, czkRates),
        })),
    }))
    .filter((account) => Math.abs(account.totalCzk) >= 0.01 || account.balances.length > 0)

  const portfolioValueCzk = holdings.reduce((sum, holding) => {
    const quantity = toNum(holding.quantity)
    const fallbackValue = quantity * toNum(holding.avgBuyPrice)
    const value = holding.currentValue == null ? fallbackValue : toNum(holding.currentValue)
    return sum + toCzk(value, holding.currency, czkRates)
  }, 0)

  const cashValueCzk = accountBalances
    .filter(
      (account) =>
        !LIABILITY_ACCOUNT_TYPES.has(account.accountType) &&
        (BANK_ACCOUNT_TYPES.has(account.accountType) ||
          INVESTMENT_ACCOUNT_TYPES.has(account.accountType))
    )
    .reduce((sum, account) => sum + account.totalCzk, 0)
  const liabilitiesValueCzk = accountBalances
    .filter((account) => LIABILITY_ACCOUNT_TYPES.has(account.accountType))
    .reduce((sum, account) => sum + Math.abs(Math.min(0, account.totalCzk)), 0)

  type MonthlyTrend = {
    month: string
    label: string
    incomeCzk: number
    expenseCzk: number
    netCzk: number
  }

  const monthMap = new Map<string, MonthlyTrend>(
    Array.from({ length: 6 }, (_, index) => {
      const date = new Date(currentYear, now.getMonth() - 5 + index, 1)
      return [
        monthKey(date),
        {
          month: monthKey(date),
          label: monthLabel(date),
          incomeCzk: 0,
          expenseCzk: 0,
          netCzk: 0,
        },
      ]
    })
  )

  const expenseByCategory = new Map<
    string,
    {
      categoryId: string | null
      name: string
      icon: string | null
      color: string | null
      amountCzk: number
    }
  >()

  for (const tx of trendTransactions) {
    const amountCzk = transactionAmountCzk(tx, czkRates)
    const key = monthKey(tx.date)
    const trend = monthMap.get(key)
    if (trend) {
      if (tx.type === "income") trend.incomeCzk += amountCzk
      if (tx.type === "expense") trend.expenseCzk += amountCzk
      trend.netCzk = trend.incomeCzk - trend.expenseCzk
    }

    if (tx.type === "expense" && tx.date >= currentStart) {
      const categoryKey = tx.categoryId ?? "uncategorized"
      const current = expenseByCategory.get(categoryKey) ?? {
        categoryId: tx.categoryId,
        name: tx.category?.name ?? "Bez kategorie",
        icon: tx.category?.icon ?? null,
        color: tx.category?.color ?? null,
        amountCzk: 0,
      }
      current.amountCzk += amountCzk
      expenseByCategory.set(categoryKey, current)
    }
  }

  const currentTrend = monthMap.get(monthKey(now))
  const spentByCategory = new Map(
    Array.from(expenseByCategory.values()).map((category) => [
      category.categoryId,
      category.amountCzk,
    ])
  )

  const budgetItems =
    budgetProgress?.items.map((item) => ({
      id: item.id,
      categoryId: item.categoryId,
      name: item.category.name,
      icon: item.category.icon,
      color: item.category.color,
      limitCzk: item.effectiveAmount,
      spentCzk: spentByCategory.get(item.categoryId) ?? item.spent,
      remainingCzk: item.remaining,
      progressPct: item.progressPct,
      isOver: item.isOver,
    })) ?? []

  return NextResponse.json({
    summary: {
      cashValueCzk,
      portfolioValueCzk,
      liabilitiesValueCzk,
      netWorthCzk: cashValueCzk + portfolioValueCzk - liabilitiesValueCzk,
      currentMonthIncomeCzk: currentTrend?.incomeCzk ?? 0,
      currentMonthExpenseCzk: currentTrend?.expenseCzk ?? 0,
      currentMonthNetCzk: currentTrend?.netCzk ?? 0,
    },
    accountBalances: serializedAccountBalances,
    budget: budgetProgress
      ? {
          id: budgetProgress.id,
          month: budgetProgress.month,
          year: budgetProgress.year,
          limitCzk: budgetProgress.totalLimit,
          spentCzk: budgetProgress.totalSpent,
          remainingCzk: budgetProgress.totalRemaining,
          progressPct: budgetProgress.progressPct,
          items: budgetItems.sort((a, b) => b.progressPct - a.progressPct),
        }
      : null,
    expenseByCategory: Array.from(expenseByCategory.values()).sort(
      (a, b) => b.amountCzk - a.amountCzk
    ),
    monthlyTrends: Array.from(monthMap.values()),
    recentTransactions: recentTransactions.map((tx) => ({
      id: tx.id,
      date: tx.date,
      amount: toNum(tx.amount),
      amountCzk: transactionAmountCzk(tx, czkRates),
      currency: tx.currency,
      type: tx.type,
      description: tx.description,
      counterparty: tx.counterparty,
      accountName: tx.account.name,
      categoryName: tx.category?.name ?? null,
      categoryIcon: tx.category?.icon ?? null,
    })),
    czkRates,
  })
}
