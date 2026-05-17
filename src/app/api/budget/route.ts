import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"

// GET /api/budget?month=5&year=2026
export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const now = new Date()
  const month = parseInt(req.nextUrl.searchParams.get("month") ?? String(now.getMonth() + 1))
  const year = parseInt(req.nextUrl.searchParams.get("year") ?? String(now.getFullYear()))

  const budget = await prisma.budget.findUnique({
    where: { month_year_userId: { month, year, userId: session.user.id } },
    include: { items: { include: { category: true } } },
  })

  if (budget && budget.items.length > 0) {
    const start = new Date(year, month - 1, 1)
    const end = new Date(year, month, 1)

    const spentRows = await prisma.transaction.groupBy({
      by: ["categoryId"],
      where: {
        account: { userId: session.user.id },
        categoryId: { in: budget.items.map(i => i.categoryId) },
        type: "expense",
        date: { gte: start, lt: end },
      },
      _sum: { amount: true },
    })

    const spentMap = Object.fromEntries(
      spentRows.map(r => [r.categoryId, r._sum.amount ?? 0])
    )

    for (const item of budget.items) {
      item.spent = spentMap[item.categoryId] ?? 0
    }
  }

  return NextResponse.json(budget)
}

// POST /api/budget — vytvořit/aktualizovat budget pro měsíc
export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { month, year, items } = await req.json()
  // items: [{ categoryId, amount }]

  const budget = await prisma.budget.upsert({
    where: { month_year_userId: { month, year, userId: session.user.id } },
    update: {},
    create: { month, year, userId: session.user.id },
  })

  await Promise.all(
    (items ?? []).map((item: { categoryId: string; amount: number }) =>
      prisma.budgetItem.upsert({
        where: { id: `${budget.id}-${item.categoryId}` },
        update: { amount: item.amount },
        create: {
          id: `${budget.id}-${item.categoryId}`,
          amount: item.amount,
          budgetId: budget.id,
          categoryId: item.categoryId,
          currency: "CZK",
        },
      })
    )
  )

  return NextResponse.json({ ok: true })
}
