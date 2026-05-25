import { prisma, toNum } from "@/lib/prisma"
import type { AssetType } from "@prisma/client"

export async function recalculateHoldings(
  accountId: string
): Promise<{ warnings: { symbol: string; quantity: number }[] }> {
  const txs = await prisma.investmentTransaction.findMany({
    where: { accountId, type: { in: ["buy", "sell", "deposit", "withdrawal"] } },
    orderBy: { date: "asc" },
  })

  const positions: Record<
    string,
    {
      quantity: number
      totalCost: number
      currency: string
      assetType: AssetType
      name: string | null
    }
  > = {}

  const realizedPnlUpdates: { id: string; realizedPnl: number; currency: string }[] = []

  for (const tx of txs) {
    if (!tx.symbol) continue

    if (!positions[tx.symbol]) {
      positions[tx.symbol] = {
        quantity: 0,
        totalCost: 0,
        currency: tx.priceCurrency ?? "EUR",
        assetType: tx.assetType ?? "stock",
        name: tx.name,
      }
    }

    const pos = positions[tx.symbol]
    const qty = toNum(tx.quantity)
    const price = toNum(tx.pricePerUnit)

    if (tx.type === "buy") {
      pos.quantity += qty
      pos.totalCost += qty * price
    } else if (tx.type === "deposit") {
      pos.quantity += qty
      if (price > 0) pos.totalCost += qty * price
    } else if (tx.type === "sell") {
      const avgPrice = pos.quantity > 0 ? pos.totalCost / pos.quantity : 0
      realizedPnlUpdates.push({
        id: tx.id,
        realizedPnl: (price - avgPrice) * qty,
        currency: tx.priceCurrency ?? pos.currency,
      })
      pos.totalCost -= qty * avgPrice
      pos.quantity -= qty
    } else if (tx.type === "withdrawal") {
      const avgPrice = pos.quantity > 0 ? pos.totalCost / pos.quantity : 0
      pos.totalCost -= qty * avgPrice
      pos.quantity -= qty
    }
  }

  const warnings: { symbol: string; quantity: number }[] = []
  for (const [symbol, pos] of Object.entries(positions)) {
    if (pos.quantity < -0.000001) warnings.push({ symbol, quantity: pos.quantity })
  }

  const keepSymbols = Object.keys(positions).filter((s) => positions[s].quantity > 0.000001)

  await prisma.$transaction(async (tx) => {
    for (const [symbol, pos] of Object.entries(positions)) {
      if (pos.quantity > 0.000001) {
        await tx.holding.upsert({
          where: { symbol_accountId: { symbol, accountId } },
          update: {
            quantity: pos.quantity,
            avgBuyPrice: pos.totalCost / pos.quantity,
            currency: pos.currency,
            assetType: pos.assetType,
            name: pos.name,
          },
          create: {
            symbol,
            name: pos.name,
            quantity: pos.quantity,
            avgBuyPrice: pos.totalCost / pos.quantity,
            currency: pos.currency,
            assetType: pos.assetType,
            accountId,
          },
        })
      }
    }

    await tx.holding.deleteMany({
      where: { accountId, symbol: { notIn: keepSymbols } },
    })

    for (const upd of realizedPnlUpdates) {
      await tx.investmentTransaction.update({
        where: { id: upd.id },
        data: { realizedPnl: upd.realizedPnl, realizedPnlCurrency: upd.currency },
      })
    }
  })

  return { warnings }
}
