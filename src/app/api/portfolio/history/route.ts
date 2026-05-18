import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma, toNum } from "@/lib/prisma"
import { getCzkRates, toCzk } from "@/modules/portfolio/rates/service"

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const filterAccountId = req.nextUrl.searchParams.get("accountId")

  const accounts = await prisma.account.findMany({
    where: { userId: session.user.id },
    select: { id: true },
  })
  const accountIds = accounts.map(a => a.id)
  const effectiveAccountId = filterAccountId && accountIds.includes(filterAccountId)
    ? filterAccountId
    : null

  const buys = await prisma.investmentTransaction.findMany({
    where: {
      accountId: effectiveAccountId ? effectiveAccountId : { in: accountIds },
      type: "buy",
      totalAmount: { not: null },
    },
    orderBy: { date: "asc" },
    select: { date: true, totalAmount: true, totalCurrency: true },
  })

  if (buys.length === 0) return NextResponse.json([])

  const czkRates = await getCzkRates()

  const monthlyMap: Record<string, number> = {}
  for (const tx of buys) {
    const key = tx.date.toISOString().slice(0, 7)
    const amountCzk = toCzk(toNum(tx.totalAmount), tx.totalCurrency ?? "EUR", czkRates)
    monthlyMap[key] = (monthlyMap[key] ?? 0) + amountCzk
  }

  const months = Object.keys(monthlyMap).sort()
  const firstMonth = months[0]
  const lastMonth = new Date().toISOString().slice(0, 7)

  const allMonths: string[] = []
  let cursor = new Date(firstMonth + "-01")
  const end = new Date(lastMonth + "-01")
  while (cursor <= end) {
    allMonths.push(cursor.toISOString().slice(0, 7))
    cursor = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1)
  }

  let cumulative = 0
  const data = allMonths.map(month => {
    cumulative += monthlyMap[month] ?? 0
    return {
      month,
      label: new Date(month + "-15").toLocaleDateString("cs-CZ", { month: "short", year: "numeric" }),
      investedCzk: Math.round(cumulative),
    }
  })

  return NextResponse.json(data)
}
