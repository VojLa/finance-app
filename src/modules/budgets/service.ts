import { prisma, serializePrisma, toNum } from "@/lib/prisma"

export const BUDGET_APPROACHING_THRESHOLD = 0.8

type BudgetInputItem = {
  categoryId: string
  amount: number
  currency?: string
}

export type BudgetProgressItem = {
  id: string
  amount: number
  rolloverAmount: number
  effectiveAmount: number
  spent: number
  remaining: number
  progressPct: number
  isApproaching: boolean
  isOver: boolean
  currency: string
  categoryId: string
  category: {
    id: string
    name: string
    icon: string | null
    color: string | null
  }
}

export type BudgetProgress = {
  id: string
  month: number
  year: number
  periodType: string
  currency: string
  rollover: boolean
  totalLimit: number
  totalBaseLimit: number
  totalRollover: number
  totalSpent: number
  totalRemaining: number
  progressPct: number
  isOver: boolean
  alerts: {
    id: string
    type: string
    categoryId: string
    categoryName: string
    threshold: number
    triggeredAt: Date
    acknowledgedAt: Date | null
  }[]
  items: BudgetProgressItem[]
}

function monthRange(month: number, year: number) {
  return {
    start: new Date(year, month - 1, 1),
    end: new Date(year, month, 1),
  }
}

function previousMonth(month: number, year: number) {
  if (month === 1) return { month: 12, year: year - 1 }
  return { month: month - 1, year }
}

async function getSpentByCategory(
  userId: string,
  start: Date,
  end: Date,
  categoryIds: string[]
): Promise<Record<string, number>> {
  if (categoryIds.length === 0) return {}

  const spentRows = await prisma.transaction.groupBy({
    by: ["categoryId"],
    where: {
      account: { members: { some: { userId } } },
      categoryId: { in: categoryIds },
      type: "expense",
      date: { gte: start, lt: end },
    },
    _sum: { amount: true },
  })

  return Object.fromEntries(spentRows.map((row) => [row.categoryId, toNum(row._sum?.amount)]))
}

async function findMonthlyBudget(userId: string, month: number, year: number) {
  const { start, end } = monthRange(month, year)
  return prisma.budget.findFirst({
    where: { userId, periodStart: start, periodEnd: end, name: "Monthly budget" },
  })
}

async function calculateRolloverAmount(
  userId: string,
  categoryId: string,
  month: number,
  year: number
): Promise<number> {
  const prev = previousMonth(month, year)
  const { start, end } = monthRange(prev.month, prev.year)
  const previousBudget = await prisma.budget.findFirst({
    where: { userId, periodStart: start, periodEnd: end, name: "Monthly budget" },
    include: {
      items: {
        include: {
          categories: true,
        },
      },
    },
  })

  const previousItem = previousBudget?.items.find((item) =>
    item.categories.some((category) => category.categoryId === categoryId)
  )
  if (!previousItem) return 0

  const spentMap = await getSpentByCategory(userId, start, end, [categoryId])
  const previousLimit = toNum(previousItem.amount) + toNum(previousItem.rolloverAmount)

  return previousLimit - (spentMap[categoryId] ?? 0)
}

async function syncBudgetAlerts(userId: string, items: BudgetProgressItem[]) {
  for (const item of items) {
    const alertType = item.isOver ? "exceeded" : item.isApproaching ? "approaching_limit" : null

    if (!alertType) {
      await prisma.budgetAlert.updateMany({
        where: {
          userId,
          budgetItemId: item.id,
          acknowledgedAt: null,
          type: { in: ["approaching_limit", "exceeded"] },
        },
        data: { acknowledgedAt: new Date() },
      })
      continue
    }

    const existing = await prisma.budgetAlert.findFirst({
      where: {
        userId,
        budgetItemId: item.id,
        type: alertType,
        acknowledgedAt: null,
      },
    })

    if (!existing) {
      await prisma.budgetAlert.create({
        data: {
          userId,
          budgetItemId: item.id,
          type: alertType,
          threshold: item.isOver ? 1 : BUDGET_APPROACHING_THRESHOLD,
        },
      })
    }
  }
}

export async function getBudgetProgress({
  userId,
  month,
  year,
}: {
  userId: string
  month: number
  year: number
}): Promise<BudgetProgress | null> {
  const { start, end } = monthRange(month, year)
  const budget = await prisma.budget.findFirst({
    where: { userId, periodStart: start, periodEnd: end, name: "Monthly budget" },
    include: {
      items: {
        include: {
          categories: {
            include: {
              category: {
                select: { id: true, name: true, icon: true, color: true },
              },
            },
          },
        },
        orderBy: { createdAt: "asc" },
      },
    },
  })

  if (!budget) return null

  const categoryIds = budget.items.flatMap((item) =>
    item.categories.map((category) => category.categoryId)
  )
  const spentMap = await getSpentByCategory(userId, start, end, categoryIds)

  const items: BudgetProgressItem[] = budget.items.map((item) => {
    const primaryCategory = item.categories[0]?.category
    const itemCategoryIds = item.categories.map((category) => category.categoryId)
    const amount = toNum(item.amount)
    const rolloverAmount = toNum(item.rolloverAmount)
    const effectiveAmount = amount + rolloverAmount
    const spent = itemCategoryIds.reduce((sum, categoryId) => sum + (spentMap[categoryId] ?? 0), 0)
    const progressPct = effectiveAmount > 0 ? Math.min(100, (spent / effectiveAmount) * 100) : 0

    return {
      ...serializePrisma(item),
      amount,
      rolloverAmount,
      effectiveAmount,
      spent,
      remaining: effectiveAmount - spent,
      progressPct,
      isApproaching: effectiveAmount > 0 && spent / effectiveAmount >= BUDGET_APPROACHING_THRESHOLD,
      isOver: spent > effectiveAmount,
      categoryId: primaryCategory?.id ?? "",
      category: primaryCategory ?? { id: "", name: item.name ?? "Budget", icon: null, color: null },
    }
  })

  await syncBudgetAlerts(userId, items)

  const alerts = await prisma.budgetAlert.findMany({
    where: {
      userId,
      budgetItemId: { in: items.map((item) => item.id) },
      acknowledgedAt: null,
    },
    include: {
      budgetItem: {
        include: {
          categories: {
            include: {
              category: { select: { id: true, name: true } },
            },
          },
        },
      },
    },
    orderBy: { triggeredAt: "desc" },
  })

  const totalBaseLimit = items.reduce((sum, item) => sum + item.amount, 0)
  const totalRollover = items.reduce((sum, item) => sum + item.rolloverAmount, 0)
  const totalLimit = items.reduce((sum, item) => sum + item.effectiveAmount, 0)
  const totalSpent = items.reduce((sum, item) => sum + item.spent, 0)

  return {
    id: budget.id,
    month,
    year,
    periodType: budget.periodType,
    currency: budget.currency,
    rollover: budget.rolloverEnabled,
    totalLimit,
    totalBaseLimit,
    totalRollover,
    totalSpent,
    totalRemaining: totalLimit - totalSpent,
    progressPct: totalLimit > 0 ? Math.min(100, (totalSpent / totalLimit) * 100) : 0,
    isOver: totalSpent > totalLimit,
    alerts: alerts.map((alert) => {
      const category = alert.budgetItem.categories[0]?.category
      return {
        id: alert.id,
        type: alert.type,
        categoryId: category?.id ?? alert.budgetItemId,
        categoryName: category?.name ?? alert.budgetItem.name ?? "Budget",
        threshold: toNum(alert.threshold),
        triggeredAt: alert.triggeredAt,
        acknowledgedAt: alert.acknowledgedAt,
      }
    }),
    items,
  }
}

export async function saveMonthlyBudget({
  userId,
  month,
  year,
  rollover,
  items,
}: {
  userId: string
  month: number
  year: number
  rollover: boolean
  items: BudgetInputItem[]
}) {
  const { start, end } = monthRange(month, year)
  const existing = await findMonthlyBudget(userId, month, year)
  const budget = existing
    ? await prisma.budget.update({
        where: { id: existing.id },
        data: { rolloverEnabled: rollover },
      })
    : await prisma.budget.create({
        data: {
          name: "Monthly budget",
          periodStart: start,
          periodEnd: end,
          periodType: "monthly",
          userId,
          rolloverEnabled: rollover,
        },
      })

  const validItems = items.filter(
    (item) => item.categoryId && Number.isFinite(item.amount) && item.amount > 0
  )

  const rows = await Promise.all(
    validItems.map(async (item) => ({
      name: null,
      amount: item.amount,
      budgetId: budget.id,
      categoryId: item.categoryId,
      currency: item.currency ?? "CZK",
      rolloverAmount: rollover
        ? await calculateRolloverAmount(userId, item.categoryId, month, year)
        : 0,
    }))
  )

  await prisma.$transaction(async (tx) => {
    await tx.budgetAlert.deleteMany({
      where: { budgetItem: { budgetId: budget.id } },
    })
    await tx.budgetItem.deleteMany({ where: { budgetId: budget.id } })

    for (const row of rows) {
      await tx.budgetItem.create({
        data: {
          name: row.name,
          amount: row.amount,
          budgetId: row.budgetId,
          currency: row.currency,
          rolloverAmount: row.rolloverAmount,
          categories: {
            create: { categoryId: row.categoryId },
          },
        },
      })
    }
  })

  return getBudgetProgress({ userId, month, year })
}
