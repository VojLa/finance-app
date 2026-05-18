import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma, serializePrisma } from "@/lib/prisma"

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const symbol = req.nextUrl.searchParams.get("symbol")
  if (!symbol) return NextResponse.json({ error: "Chybí symbol" }, { status: 400 })

  const accounts = await prisma.account.findMany({
    where: { userId: session.user.id },
    select: { id: true },
  })
  const accountIds = accounts.map(a => a.id)

  const transactions = await prisma.investmentTransaction.findMany({
    where: {
      symbol,
      accountId: { in: accountIds },
    },
    orderBy: { date: "desc" },
  })

  return NextResponse.json(serializePrisma(transactions))
}
