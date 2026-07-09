import { prisma, toNum } from "@/lib/prisma"
import type { AssetType } from "@prisma/client"

type LedgerEvent = Awaited<ReturnType<typeof loadLedgerEvents>>[number]

async function loadLedgerEvents(accountId: string) {
  return prisma.investmentEvent.findMany({
    where: { accountId, deletedAt: null, archivedAt: null },
    include: { movements: true },
    orderBy: { date: "asc" },
  })
}

function assetMovement(event: LedgerEvent) {
  return event.movements.find((movement) => movement.kind === "asset" && movement.sourceSymbol)
}

function cashMovement(event: LedgerEvent) {
  return event.movements.find((movement) => movement.kind === "cash")
}

export async function recalculateHoldings(
  accountId: string
): Promise<{ warnings: { symbol: string; quantity: number }[] }> {
  const events = await loadLedgerEvents(accountId)

  const positions: Record<
    string,
    {
      quantity: number
      totalCost: number
      currency: string
      assetType: AssetType
      name: string | null
      assetId: string | null
      realizedPnl: number
      realizedPnlCurrency: string | null
    }
  > = {}

  const realizedPnlUpdates: { id: string; realizedPnl: number; currency: string }[] = []

  for (const event of events) {
    const asset = assetMovement(event)
    if (!asset?.sourceSymbol) continue

    const symbol = asset.sourceSymbol
    positions[symbol] ||= {
      quantity: 0,
      totalCost: 0,
      currency: asset.valueCurrency ?? asset.currency ?? "EUR",
      assetType: asset.sourceAssetType ?? "stock",
      name: event.description,
      assetId: asset.assetId,
      realizedPnl: 0,
      realizedPnlCurrency: asset.valueCurrency ?? null,
    }

    const pos = positions[symbol]
    const qty = toNum(asset.quantity)
    const cash = cashMovement(event)
    const cashValue = cash ? toNum(cash.quantity) : toNum(asset.valueAmount)
    const price = toNum(asset.pricePerUnit) || (qty > 0 ? cashValue / qty : 0)

    if (asset.direction === "in") {
      pos.quantity += qty
      if (price > 0) pos.totalCost += qty * price
      continue
    }

    const avgPrice = pos.quantity > 0 ? pos.totalCost / pos.quantity : 0
    const realizedPnl = (price - avgPrice) * qty
    pos.realizedPnl += realizedPnl
    pos.realizedPnlCurrency = asset.valueCurrency ?? pos.currency
    pos.totalCost -= qty * avgPrice
    pos.quantity -= qty

    if (event.type === "trade") {
      realizedPnlUpdates.push({
        id: event.id,
        realizedPnl,
        currency: asset.valueCurrency ?? pos.currency,
      })
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
            assetId: pos.assetId,
            realizedPnl: pos.realizedPnl,
          },
          create: {
            symbol,
            name: pos.name,
            quantity: pos.quantity,
            avgBuyPrice: pos.totalCost / pos.quantity,
            currency: pos.currency,
            assetType: pos.assetType,
            assetId: pos.assetId,
            accountId,
            realizedPnl: pos.realizedPnl,
          },
        })
      }
    }

    await tx.holding.deleteMany({
      where: { accountId, symbol: { notIn: keepSymbols } },
    })

    for (const upd of realizedPnlUpdates) {
      await tx.investmentEvent.update({
        where: { id: upd.id },
        data: { realizedPnl: upd.realizedPnl, realizedPnlCurrency: upd.currency },
      })
    }
  })

  return { warnings }
}
