import type { NextRequest } from "next/server"
import { NextResponse } from "next/server"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"
import { prisma, toNum } from "@/lib/prisma"
import {
  getLivePrices,
  getCzkRates,
  priceLookupKey,
  toCzk,
} from "@/modules/portfolio/rates/service"
import { getAccessibleAccountIds } from "@/lib/accountAccess"
import type { HoldingWithPrice, PortfolioSummary } from "@/types"

export async function GET(req: NextRequest) {
  const session = await getServerSession(authOptions)
  if (!session) return NextResponse.json({ error: "Unauthorized" }, { status: 401 })

  const filterAccountId = req.nextUrl.searchParams.get("accountId")

  const accessibleIds = await getAccessibleAccountIds(session.user.id, "viewer")
  const [allAccounts, czkRates] = await Promise.all([
    prisma.account.findMany({
      where: { id: { in: accessibleIds } },
      include: { holdings: true },
      orderBy: { createdAt: "asc" },
    }),
    getCzkRates(),
  ])

  const accounts = filterAccountId
    ? allAccounts.filter((a) => a.id === filterAccountId)
    : allAccounts

  const accountNameMap = Object.fromEntries(allAccounts.map((a) => [a.id, a.name]))
  const accountsList = allAccounts.map((a) => ({ id: a.id, name: a.name, type: a.type as string }))

  const allHoldings = accounts.flatMap((a) => a.holdings)
  const allAccountIds = accounts.map((a) => a.id)

  const realizedPnlRows = await prisma.investmentEvent.findMany({
    where: {
      accountId: { in: allAccountIds },
      deletedAt: null,
      archivedAt: null,
      realizedPnl: { not: null },
    },
    select: { realizedPnl: true, realizedPnlCurrency: true },
  })
  const totalRealizedPnlCzk = realizedPnlRows.reduce(
    (sum, row) => sum + toCzk(toNum(row.realizedPnl), row.realizedPnlCurrency ?? "EUR", czkRates),
    0
  )

  if (allHoldings.length === 0) {
    const summary: PortfolioSummary = {
      totalValueCzk: 0,
      totalCostCzk: 0,
      totalUnrealizedPnlCzk: 0,
      totalUnrealizedPnlPct: 0,
      totalRealizedPnlCzk,
      czkRates,
      holdings: [],
      accounts: accountsList,
      warnings: [],
    }
    return NextResponse.json(summary)
  }

  const symbols = allHoldings.map((h) => ({
    symbol: h.symbol,
    assetType: h.assetType,
    currency: h.currency,
    listingId: h.listingId,
  }))
  const prices = await getLivePrices(symbols)

  let totalCostCzkAcc = 0
  let pricedCostCzkAcc = 0
  const missingPriceWarnings: { symbol: string; issue: string }[] = []

  const holdings: HoldingWithPrice[] = allHoldings.map((h) => {
    const liveData =
      prices[
        priceLookupKey({
          symbol: h.symbol,
          assetType: h.assetType,
          currency: h.currency,
          listingId: h.listingId,
        })
      ] ?? prices[h.symbol]
    const currentPrice = liveData?.price ?? null
    const priceCurrency = liveData?.currency ?? null

    const qty = toNum(h.quantity)
    const avgBuy = toNum(h.avgBuyPrice)

    const currentValue = currentPrice !== null ? currentPrice * qty : null
    const currentValueCzk =
      currentValue !== null && priceCurrency ? toCzk(currentValue, priceCurrency, czkRates) : null

    const costInOrigCurrency = avgBuy * qty
    const costCzk = toCzk(costInOrigCurrency, h.currency, czkRates)
    totalCostCzkAcc += costCzk
    const avgBuyPriceCzk = toCzk(avgBuy, h.currency, czkRates)
    const currentValueCzkWithFallback = currentValueCzk ?? costCzk

    const unrealizedPnl =
      currentValue !== null && priceCurrency === h.currency
        ? currentValue - costInOrigCurrency
        : null

    const unrealizedPnlCzk = currentValueCzk !== null ? currentValueCzk - costCzk : null
    const unrealizedPnlPct =
      unrealizedPnlCzk !== null && costCzk > 0 ? (unrealizedPnlCzk / costCzk) * 100 : null

    if (currentValueCzk !== null) {
      pricedCostCzkAcc += costCzk
    } else {
      missingPriceWarnings.push({
        symbol: h.symbol,
        issue: "Chybi live cena - pro celkovou hodnotu je docasne pouzita nakupni hodnota",
      })
    }

    return {
      id: h.id,
      symbol: h.symbol,
      name: h.name,
      assetType: h.assetType,
      quantity: qty,
      avgBuyPrice: avgBuy,
      avgBuyPriceCzk,
      currency: h.currency,
      listingId: h.listingId,
      accountId: h.accountId,
      accountName: accountNameMap[h.accountId] ?? null,
      currentPrice,
      currentPriceCurrency: priceCurrency,
      currentValue,
      currentValueCzk: currentValueCzkWithFallback,
      unrealizedPnl,
      unrealizedPnlCzk,
      unrealizedPnlPct,
    }
  })

  const totalValueCzk = holdings.reduce((sum, h) => sum + (h.currentValueCzk ?? 0), 0)
  const totalPricedValueCzk = holdings.reduce(
    (sum, h) => (h.unrealizedPnlCzk !== null ? sum + (h.currentValueCzk ?? 0) : sum),
    0
  )
  const totalCostCzk = totalCostCzkAcc
  const totalUnrealizedPnlCzk = totalPricedValueCzk - pricedCostCzkAcc
  const totalUnrealizedPnlPct =
    pricedCostCzkAcc > 0 ? (totalUnrealizedPnlCzk / pricedCostCzkAcc) * 100 : 0

  const warnings = [
    ...(totalValueCzk < 0
      ? [{ symbol: "portfolio", issue: "Celková hodnota portfolia je záporná — zkontroluj data" }]
      : []),
    ...missingPriceWarnings,
    ...holdings
      .filter((h) => h.avgBuyPrice < 0)
      .map((h) => ({
        symbol: h.symbol,
        issue: "Záporná průměrná nákupní cena — pravděpodobně chyba v importu",
      })),
  ]

  const summary: PortfolioSummary = {
    totalValueCzk,
    totalCostCzk,
    totalUnrealizedPnlCzk,
    totalUnrealizedPnlPct,
    totalRealizedPnlCzk,
    czkRates,
    holdings: holdings.sort((a, b) => (b.currentValueCzk ?? 0) - (a.currentValueCzk ?? 0)),
    accounts: accountsList,
    warnings,
  }

  return NextResponse.json(summary)
}
