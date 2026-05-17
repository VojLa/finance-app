import yahooFinance from "yahoo-finance2"

const COINGECKO_IDS: Record<string, string> = {
  BTC: "bitcoin",
  ETH: "ethereum",
  SOL: "solana",
  BNB: "binancecoin",
  ADA: "cardano",
  DOT: "polkadot",
  AVAX: "avalanche-2",
  MATIC: "matic-network",
}

const priceCache: Record<string, { price: number; currency: string; ts: number }> = {}
const CACHE_TTL = 5 * 60 * 1000 // 5 minut

export async function getLivePrice(symbol: string, assetType: string): Promise<{ price: number; currency: string } | null> {
  const cacheKey = `${symbol}:${assetType}`
  const cached = priceCache[cacheKey]
  if (cached && Date.now() - cached.ts < CACHE_TTL) {
    return { price: cached.price, currency: cached.currency }
  }

  try {
    if (assetType === "crypto") {
      const geckoId = COINGECKO_IDS[symbol.toUpperCase()]
      if (!geckoId) return null

      const url = `https://api.coingecko.com/api/v3/simple/price?ids=${geckoId}&vs_currencies=eur`
      const res = await fetch(url, { headers: { Accept: "application/json" } })
      if (!res.ok) return null

      const data = await res.json()
      const price = data[geckoId]?.eur
      if (!price) return null

      priceCache[cacheKey] = { price, currency: "EUR", ts: Date.now() }
      return { price, currency: "EUR" }
    }

    const quote = await yahooFinance.quote(symbol)
    const price = quote.regularMarketPrice
    const currency = quote.currency ?? "USD"
    if (!price) return null

    priceCache[cacheKey] = { price, currency, ts: Date.now() }
    return { price, currency }
  } catch {
    return null
  }
}

export async function getLivePrices(
  symbols: { symbol: string; assetType: string }[]
): Promise<Record<string, { price: number; currency: string } | null>> {
  const results = await Promise.all(
    symbols.map(async ({ symbol, assetType }) => ({
      symbol,
      data: await getLivePrice(symbol, assetType),
    }))
  )

  return Object.fromEntries(results.map(r => [r.symbol, r.data]))
}
