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
      listingId: string
      symbol: string
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
    if (!asset?.sourceSymbol || !asset.listingId) continue

    const symbol = asset.sourceSymbol
    const key = asset.listingId
    positions[key] ||= {
      listingId: asset.listingId,
      symbol,
      quantity: 0,
      totalCost: 0,
      currency: asset.valueCurrency ?? asset.currency ?? "EUR",
      assetType: asset.sourceAssetType ?? "stock",
      name: event.description,
      assetId: asset.assetId,
      realizedPnl: 0,
      realizedPnlCurrency: asset.valueCurrency ?? null,
    }

    const pos = positions[key]
    const qty = toNum(asset.quantity)
    const cash = cashMovement(event)
    const cashValue = cash ? toNum(cash.quantity) : toNum(asset.valueAmount)
    const price = toNum(asset.pricePerUnit) || (qty > 0 ? cashValue / qty : 0)

    if (asset.direction === "in") {
      if (asset.valueCurrency && price > 0 && pos.totalCost === 0) {
        pos.currency = asset.valueCurrency
        pos.realizedPnlCurrency = asset.valueCurrency
      }
      pos.quantity += qty
      if (price > 0) pos.totalCost += qty * price
      continue
    }

    const avgPrice = pos.quantity > 0 ? pos.totalCost / pos.quantity : 0
    const realizedPnl = event.type === "trade" ? (price - avgPrice) * qty : 0
    if (event.type === "trade") {
      pos.realizedPnl += realizedPnl
      pos.realizedPnlCurrency = asset.valueCurrency ?? pos.currency
    }
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
  for (const pos of Object.values(positions)) {
    if (pos.quantity < -0.000001) warnings.push({ symbol: pos.symbol, quantity: pos.quantity })
  }

  const keepListingIds = Object.keys(positions).filter((id) => positions[id].quantity > 0.000001)

  await prisma.$transaction(async (tx) => {
    for (const [listingId, pos] of Object.entries(positions)) {
      if (pos.quantity > 0.000001) {
        await tx.holding.upsert({
          where: { accountId_listingId: { accountId, listingId } },
          update: {
            quantity: pos.quantity,
            avgBuyPrice: pos.totalCost / pos.quantity,
            currency: pos.currency,
            assetType: pos.assetType,
            name: pos.name,
            assetId: pos.assetId,
            listingId: pos.listingId,
            realizedPnl: pos.realizedPnl,
          },
          create: {
            symbol: pos.symbol,
            name: pos.name,
            quantity: pos.quantity,
            avgBuyPrice: pos.totalCost / pos.quantity,
            currency: pos.currency,
            assetType: pos.assetType,
            assetId: pos.assetId,
            listingId: pos.listingId,
            accountId,
            realizedPnl: pos.realizedPnl,
          },
        })
      }
    }

    await tx.holding.deleteMany({
      where: { accountId, listingId: { notIn: keepListingIds } },
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
