import { NextRequest, NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma } from "@/lib/prisma"
import { getLivePrices, getCzkRates, toCzk } from "@/lib/rates"
import type { HoldingWithPrice, PortfolioSummary } from "@/types"

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const filterAccountId = req.nextUrl.searchParams.get("accountId")

  const [allAccounts, czkRates] = await Promise.all([
    prisma.account.findMany({
      where: { userId: session.user.id },
      include: { holdings: true },
      orderBy: { createdAt: "asc" },
    }),
    getCzkRates(),
  ])

  const accounts = filterAccountId
    ? allAccounts.filter(a => a.id === filterAccountId)
    : allAccounts

  const accountNameMap = Object.fromEntries(allAccounts.map(a => [a.id, a.name]))
  const accountsList = allAccounts.map(a => ({ id: a.id, name: a.name, type: a.type as string }))

  const allHoldings = accounts.flatMap(a => a.holdings)

  if (allHoldings.length === 0) {
    const summary: PortfolioSummary = {
      totalValueCzk: 0,
      totalCostCzk: 0,
      totalUnrealizedPnlCzk: 0,
      totalUnrealizedPnlPct: 0,
      czkRates,
      holdings: [],
      accounts: accountsList,
      warnings: [],
    }
    return NextResponse.json(summary)
  }

  const symbols = allHoldings.map(h => ({ symbol: h.symbol, assetType: h.assetType, currency: h.currency }))
  const prices = await getLivePrices(symbols)

  let totalCostCzkAcc = 0
  const holdings: HoldingWithPrice[] = allHoldings.map(h => {
    const liveData = prices[h.symbol]
    const currentPrice = liveData?.price ?? null
    const priceCurrency = liveData?.currency ?? null

    const currentValue = currentPrice !== null ? currentPrice * h.quantity : null
    const currentValueCzk = currentValue !== null && priceCurrency
      ? toCzk(currentValue, priceCurrency, czkRates)
      : null

    const costInOrigCurrency = h.avgBuyPrice * h.quantity
    const costCzk = toCzk(costInOrigCurrency, h.currency, czkRates)
    totalCostCzkAcc += costCzk
    const avgBuyPriceCzk = toCzk(h.avgBuyPrice, h.currency, czkRates)

    const unrealizedPnl = currentValue !== null ? currentValue - costInOrigCurrency : null
    const unrealizedPnlCzk = currentValueCzk !== null ? currentValueCzk - costCzk : null
    const unrealizedPnlPct =
      unrealizedPnlCzk !== null && costCzk > 0
        ? (unrealizedPnlCzk / costCzk) * 100
        : null

    return {
      id: h.id,
      symbol: h.symbol,
      name: h.name,
      assetType: h.assetType,
      quantity: h.quantity,
      avgBuyPrice: h.avgBuyPrice,
      avgBuyPriceCzk,
      currency: h.currency,
      accountId: h.accountId,
      accountName: accountNameMap[h.accountId] ?? null,
      currentPrice,
      currentPriceCurrency: priceCurrency,
      currentValue,
      currentValueCzk,
      unrealizedPnl,
      unrealizedPnlCzk,
      unrealizedPnlPct,
    }
  })

  const totalValueCzk = holdings.reduce((sum, h) => sum + (h.currentValueCzk ?? 0), 0)
  const totalCostCzk = totalCostCzkAcc
  const totalUnrealizedPnlCzk = totalValueCzk - totalCostCzk
  const totalUnrealizedPnlPct = totalCostCzk > 0 ? (totalUnrealizedPnlCzk / totalCostCzk) * 100 : 0

  const warnings = [
    ...(totalValueCzk < 0 ? [{ symbol: "portfolio", issue: "Celková hodnota portfolia je záporná — zkontroluj data" }] : []),
    ...holdings
      .filter(h => h.avgBuyPrice < 0)
      .map(h => ({ symbol: h.symbol, issue: "Záporná průměrná nákupní cena — pravděpodobně chyba v importu" })),
  ]

  const summary: PortfolioSummary = {
    totalValueCzk,
    totalCostCzk,
    totalUnrealizedPnlCzk,
    totalUnrealizedPnlPct,
    czkRates,
    holdings: holdings.sort((a, b) => (b.currentValueCzk ?? 0) - (a.currentValueCzk ?? 0)),
    accounts: accountsList,
    warnings,
  }

  return NextResponse.json(summary)
}
