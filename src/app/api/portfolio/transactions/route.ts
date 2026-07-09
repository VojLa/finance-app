import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma, serializePrisma, toNum } from "@/lib/prisma"
import { assertAccountAccess, getAccessibleAccountIds } from "@/lib/accountAccess"
import { createInvestmentEvent } from "@/modules/portfolio/ledger/service"
import { recalculateHoldings } from "@/modules/portfolio/positions/calculations"
import { createPortfolioSnapshot } from "@/modules/snapshots"
import type { ParsedInvestmentAction } from "@/types"

type InvestmentEventWithMovements = Awaited<ReturnType<typeof loadSymbolEvents>>[number]

async function loadSymbolEvents(accountIds: string[], symbol: string) {
  return prisma.investmentEvent.findMany({
    where: {
      accountId: { in: accountIds },
      deletedAt: null,
      archivedAt: null,
      movements: { some: { sourceSymbol: symbol } },
    },
    include: { movements: true },
    orderBy: { date: "desc" },
  })
}

function actionFromEvent(event: InvestmentEventWithMovements): ParsedInvestmentAction {
  const asset = event.movements.find((movement) => movement.kind === "asset")

  if (event.type === "trade") return asset?.direction === "out" ? "sell" : "buy"
  if (event.type === "asset_transfer") return asset?.direction === "out" ? "withdrawal" : "deposit"
  if (event.type === "cash_deposit") return "deposit"
  if (event.type === "cash_withdrawal") return "withdrawal"
  if (event.type === "adjustment") return "transfer"
  return event.type
}

function serializeInvestmentEvent(event: InvestmentEventWithMovements) {
  const asset = event.movements.find((movement) => movement.kind === "asset")
  const cash = event.movements.find((movement) => movement.kind === "cash")
  const fee = event.movements.find((movement) => movement.kind === "fee")

  return {
    id: event.id,
    date: event.date,
    type: actionFromEvent(event),
    quantity: asset ? toNum(asset.quantity) : null,
    pricePerUnit: asset?.pricePerUnit != null ? toNum(asset.pricePerUnit) : null,
    priceCurrency: asset?.valueCurrency ?? cash?.currency ?? null,
    totalAmount: cash ? toNum(cash.quantity) : asset?.valueAmount != null ? toNum(asset.valueAmount) : null,
    totalCurrency: cash?.currency ?? asset?.valueCurrency ?? null,
    fee: fee ? toNum(fee.quantity) : null,
    feeCurrency: fee?.currency ?? null,
    realizedPnl: event.realizedPnl != null ? toNum(event.realizedPnl) : null,
    realizedPnlCurrency: event.realizedPnlCurrency,
  }
}

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const symbol = req.nextUrl.searchParams.get("symbol")
  if (!symbol) return NextResponse.json({ error: "Chybi symbol" }, { status: 400 })

  const accountIds = await getAccessibleAccountIds(session.user.id, "viewer")
  const events = await loadSymbolEvents(accountIds, symbol.toUpperCase())

  return NextResponse.json(serializePrisma(events.map(serializeInvestmentEvent)))
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
    return NextResponse.json({ error: "Chybi povinna pole" }, { status: 400 })
  }

  const hasAccess = await assertAccountAccess(accountId, session.user.id, "editor")
  if (!hasAccess) return NextResponse.json({ error: "Ucet nenalezen" }, { status: 404 })

  const event = await createInvestmentEvent({
    date: new Date(date),
    type: type as ParsedInvestmentAction,
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
  })

  if (["buy", "sell", "deposit", "withdrawal"].includes(type)) {
    await recalculateHoldings(accountId)
    await createPortfolioSnapshot({
      userId: session.user.id,
      source: "holdings_recalculation",
      granularity: "minute",
    })
  }

  return NextResponse.json({ ok: true, id: event.id })
}
