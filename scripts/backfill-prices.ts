import { prisma } from "@/lib/prisma"
import { getHistoricalPrices, priceLookupKey } from "@/modules/portfolio/rates/service"

function todayEnd(date = new Date()) {
  const end = new Date(date)
  end.setHours(23, 59, 59, 999)
  return end
}

async function main() {
  const movements = await prisma.investmentMovement.findMany({
    where: {
      kind: "asset",
      sourceSymbol: { not: null },
      event: { deletedAt: null, archivedAt: null },
    },
    select: {
      sourceSymbol: true,
      sourceAssetType: true,
      valueCurrency: true,
      currency: true,
      listingId: true,
      event: { select: { date: true } },
    },
    orderBy: { event: { date: "asc" } },
  })

  const bySymbol = new Map<
    string,
    { symbol: string; assetType: string; currency: string; listingId: string | null; start: Date }
  >()

  for (const movement of movements) {
    if (!movement.sourceSymbol) continue

    const symbol = movement.sourceSymbol.toUpperCase()
    const key = movement.listingId ?? symbol
    const existing = bySymbol.get(key)
    const start = movement.event.date
    if (existing && existing.start <= start) continue

    bySymbol.set(key, {
      symbol,
      assetType: movement.sourceAssetType ?? "stock",
      currency: movement.valueCurrency ?? movement.currency,
      listingId: movement.listingId,
      start,
    })
  }

  const symbols = [...bySymbol.values()]
  console.log(`Backfilling historical prices for ${symbols.length} symbols...`)

  for (const item of symbols) {
    const result = await getHistoricalPrices(
      [
        {
          symbol: item.symbol,
          assetType: item.assetType,
          currency: item.currency,
          listingId: item.listingId,
        },
      ],
      item.start,
      todayEnd()
    )
    console.log(`${item.symbol}: ${result[priceLookupKey(item)]?.length ?? 0} price points`)
  }
}

main()
  .catch((error) => {
    console.error(error)
    process.exitCode = 1
  })
  .finally(() => prisma.$disconnect())
