import { prisma, toNum } from "@/lib/prisma"
import type { AssetType } from "@prisma/client"

export async function recalculateHoldings(accountId: string): Promise<{ warnings: { symbol: string; quantity: number }[] }> {
  const txs = await prisma.investmentTransaction.findMany({
    where: { accountId, type: { in: ["buy", "sell"] } },
    orderBy: { date: "asc" },
  })

  const positions: Record<string, {
    quantity: number
    totalCost: number
    currency: string
    assetType: AssetType
    name: string | null
  }> = {}

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
    } else if (tx.type === "sell") {
      const avgPrice = pos.quantity > 0 ? pos.totalCost / pos.quantity : 0
      pos.totalCost -= qty * avgPrice
      pos.quantity -= qty
    }
  }

  const warnings: { symbol: string; quantity: number }[] = []
  for (const [symbol, pos] of Object.entries(positions)) {
    if (pos.quantity < -0.000001) warnings.push({ symbol, quantity: pos.quantity })
  }

  await prisma.$transaction(
    Object.entries(positions)
      .filter(([, pos]) => pos.quantity > 0.000001)
      .map(([symbol, pos]) =>
        prisma.holding.upsert({
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
      )
  )

  await prisma.holding.deleteMany({
    where: {
      accountId,
      symbol: { notIn: Object.keys(positions).filter(s => positions[s].quantity > 0.000001) },
    },
  })

  return { warnings }
}
