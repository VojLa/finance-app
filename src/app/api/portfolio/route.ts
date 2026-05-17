import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"
import { getLivePrices } from "@/lib/rates"
import type { HoldingWithPrice, PortfolioSummary } from "@/types"

export async function GET() {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const accounts = await prisma.account.findMany({
    where: { userId: session.user.id },
    include: { holdings: true },
  })

  const allHoldings = accounts.flatMap(a => a.holdings)

  if (allHoldings.length === 0) {
    const summary: PortfolioSummary = {
      totalValue: 0,
      totalCost: 0,
      totalUnrealizedPnl: 0,
      totalUnrealizedPnlPct: 0,
      holdings: [],
    }
    return NextResponse.json(summary)
  }

  const symbols = allHoldings.map(h => ({ symbol: h.symbol, assetType: h.assetType }))
  const prices = await getLivePrices(symbols)

  const holdings: HoldingWithPrice[] = allHoldings.map(h => {
    const liveData = prices[h.symbol]
    const currentPrice = liveData?.price ?? null
    const currentValue = currentPrice !== null ? currentPrice * h.quantity : null
    const cost = h.avgBuyPrice * h.quantity
    const unrealizedPnl = currentValue !== null ? currentValue - cost : null
    const unrealizedPnlPct = unrealizedPnl !== null && cost > 0 ? (unrealizedPnl / cost) * 100 : null

    return {
      id: h.id,
      symbol: h.symbol,
      name: h.name,
      assetType: h.assetType,
      quantity: h.quantity,
      avgBuyPrice: h.avgBuyPrice,
      currency: h.currency,
      accountId: h.accountId,
      currentPrice,
      currentPriceCurrency: liveData?.currency ?? null,
      currentValue,
      unrealizedPnl,
      unrealizedPnlPct,
    }
  })

  const totalValue = holdings.reduce((sum, h) => sum + (h.currentValue ?? 0), 0)
  const totalCost = holdings.reduce((sum, h) => sum + h.avgBuyPrice * h.quantity, 0)
  const totalUnrealizedPnl = totalValue - totalCost
  const totalUnrealizedPnlPct = totalCost > 0 ? (totalUnrealizedPnl / totalCost) * 100 : 0

  const summary: PortfolioSummary = {
    totalValue,
    totalCost,
    totalUnrealizedPnl,
    totalUnrealizedPnlPct,
    holdings: holdings.sort((a, b) => (b.currentValue ?? 0) - (a.currentValue ?? 0)),
  }

  return NextResponse.json(summary)
}
