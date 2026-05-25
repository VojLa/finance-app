import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma, serializePrisma } from "@/lib/prisma"
import { recalculateHoldings } from "@/modules/portfolio/positions/calculations"
import { createPortfolioSnapshot } from "@/modules/snapshots"

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const symbol = req.nextUrl.searchParams.get("symbol")
  if (!symbol) return NextResponse.json({ error: "Chybí symbol" }, { status: 400 })

  const accounts = await prisma.account.findMany({
    where: { userId: session.user.id },
    select: { id: true },
  })
  const accountIds = accounts.map((a) => a.id)

  const transactions = await prisma.investmentTransaction.findMany({
    where: {
      symbol,
      accountId: { in: accountIds },
    },
    orderBy: { date: "desc" },
  })

  return NextResponse.json(serializePrisma(transactions))
}

export async function POST(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const body = await req.json()
  const {
    accountId,
    date,
    type,
    symbol,
    name,
    assetType,
    quantity,
    pricePerUnit,
    priceCurrency,
    totalAmount,
    totalCurrency,
    fee,
    feeCurrency,
  } = body

  if (!accountId || !date || !type) {
    return NextResponse.json({ error: "Chybí povinná pole" }, { status: 400 })
  }

  const account = await prisma.account.findFirst({
    where: { id: accountId, userId: session.user.id },
  })
  if (!account) return NextResponse.json({ error: "Účet nenalezen" }, { status: 404 })

  const tx = await prisma.investmentTransaction.create({
    data: {
      date: new Date(date),
      type,
      symbol: symbol || null,
      name: name || null,
      assetType: assetType || null,
      quantity: quantity != null ? quantity : null,
      pricePerUnit: pricePerUnit != null ? pricePerUnit : null,
      priceCurrency: priceCurrency || null,
      totalAmount: totalAmount != null ? totalAmount : null,
      totalCurrency: totalCurrency || null,
      fee: fee != null ? fee : null,
      feeCurrency: feeCurrency || null,
      accountId,
    },
  })

  if (["buy", "sell"].includes(type)) {
    await recalculateHoldings(accountId)
    await createPortfolioSnapshot({
      userId: session.user.id,
      source: "holdings_recalculation",
      granularity: "minute",
    })
  }

  return NextResponse.json({ ok: true, id: tx.id })
}
