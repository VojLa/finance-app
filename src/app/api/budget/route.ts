import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"
import { getBudgetProgress, saveMonthlyBudget } from "@/modules/budgets"

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const now = new Date()
  const month = parseInt(req.nextUrl.searchParams.get("month") ?? String(now.getMonth() + 1))
  const year = parseInt(req.nextUrl.searchParams.get("year") ?? String(now.getFullYear()))
  const sharedUserId = req.nextUrl.searchParams.get("sharedUserId")

  if (sharedUserId) {
    const hasAccess = await prisma.accountShare.findFirst({
      where: { sharedWithId: session.user.id, ownerId: sharedUserId, role: "editor" },
    })
    if (!hasAccess) return NextResponse.json({ error: "Přístup odepřen" }, { status: 403 })
    return NextResponse.json(await getBudgetProgress({ userId: sharedUserId, month, year }))
  }

  return NextResponse.json(await getBudgetProgress({ userId: session.user.id, month, year }))
}

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const { month, year, rollover = false, items = [], sharedUserId } = await req.json()

  let targetUserId = session.user.id
  if (sharedUserId) {
    const hasAccess = await prisma.accountShare.findFirst({
      where: { sharedWithId: session.user.id, ownerId: sharedUserId, role: "editor" },
    })
    if (!hasAccess) return NextResponse.json({ error: "Přístup odepřen" }, { status: 403 })
    targetUserId = sharedUserId
  }

  const budget = await saveMonthlyBudget({
    userId: targetUserId,
    month,
    year,
    rollover,
    items,
  })

  return NextResponse.json(budget)
}
