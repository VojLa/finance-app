import YahooFinance from "yahoo-finance2"

// yahoo-finance2 exports the class constructor as default; quote is an instance method
const yf = new YahooFinance()

// ─── Ceny aktiv (CoinGecko + Yahoo Finance + Stooq fallback) ──────────────────

const COINGECKO_IDS: Record<string, string> = {
  BTC: "bitcoin",
  ETH: "ethereum",
  SOL: "solana",
  BNB: "binancecoin",
  ADA: "cardano",
  DOT: "polkadot",
  AVAX: "avalanche-2",
  MATIC: "matic-network",
  XRP: "ripple",
  DOGE: "dogecoin",
  LTC: "litecoin",
  LINK: "chainlink",
  UNI: "uniswap",
  ATOM: "cosmos",
}

const priceCache: Record<string, { price: number; currency: string; ts: number }> = {}
const PRICE_TTL = 5 * 60 * 1000 // 5 minut

export function clearPriceCache() {
  for (const key of Object.keys(priceCache)) delete priceCache[key]
}

// Stooq: zdarma CSV data pro akcie/ETF (15-20 min delay)
async function getStooqPrice(symbol: string, currency: string): Promise<{ price: number; currency: string } | null> {
  let suffix: string
  if (currency === "GBP") suffix = ".uk"
  else if (currency === "EUR") suffix = ".de"
  else suffix = ".us"

  try {
    const url = `https://stooq.com/q/l/?s=${symbol.toLowerCase()}${suffix}&f=sd2t2ohlcvn&e=csv`
    const res = await fetch(url)
    if (!res.ok) return null
    const text = await res.text()
    // Format: Symbol,Date,Time,Open,High,Low,Close,Volume,Name
    const parts = text.trim().split(",")
    if (parts.length < 7 || parts[6] === "N/D") return null
    const price = parseFloat(parts[6])
    if (isNaN(price) || price <= 0) return null
    return { price, currency }
  } catch {
    return null
  }
}

export async function getLivePrice(
  symbol: string,
  assetType: string,
  currency: string,
  refresh = false,
): Promise<{ price: number; currency: string } | null> {
  const cacheKey = `${symbol}:${assetType}`
  const cached = priceCache[cacheKey]
  if (!refresh && cached && Date.now() - cached.ts < PRICE_TTL) {
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

    // Akcie/ETF: zkus Yahoo Finance, fallback na Stooq
    const result = await yf.quote(symbol).then(q => {
      const price = q.regularMarketPrice
      const cur = q.currency ?? currency
      if (!price) return null
      return { price, currency: cur }
    }).catch(() => null)

    const finalResult = result ?? await getStooqPrice(symbol, currency)
    if (!finalResult) return null

    priceCache[cacheKey] = { ...finalResult, ts: Date.now() }
    return finalResult
  } catch {
    return null
  }
}

export async function getLivePrices(
  symbols: { symbol: string; assetType: string; currency: string }[],
  refresh = false,
): Promise<Record<string, { price: number; currency: string } | null>> {
  const results = await Promise.all(
    symbols.map(async ({ symbol, assetType, currency }) => ({
      symbol,
      data: await getLivePrice(symbol, assetType, currency, refresh),
    }))
  )
  return Object.fromEntries(results.map(r => [r.symbol, r.data]))
}

// ─── Kurzy měn vůči CZK (ČNB) ────────────────────────────────────────────────

const CNB_URL =
  "https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt"

// Kolik CZK za 1 jednotku cizí měny
type CzkRates = Record<string, number>

let czkRatesCache: { rates: CzkRates; ts: number } | null = null
let czkRatesFetch: Promise<CzkRates> | null = null
const CZK_TTL = 4 * 60 * 60 * 1000 // 4 hodiny (ČNB aktualizuje jednou denně)

export async function getCzkRates(refresh = false): Promise<CzkRates> {
  if (!refresh && czkRatesCache && Date.now() - czkRatesCache.ts < CZK_TTL) {
    return czkRatesCache.rates
  }
  if (czkRatesFetch) return czkRatesFetch
  czkRatesFetch = fetchCzkRates().finally(() => { czkRatesFetch = null })
  return czkRatesFetch
}

async function fetchCzkRates(): Promise<CzkRates> {
  // CZK = CZK za CZK = 1
  const rates: CzkRates = { CZK: 1 }

  try {
    const res = await fetch(CNB_URL)
    if (!res.ok) throw new Error(`ČNB HTTP ${res.status}`)

    const text = await res.text()
    const lines = text.trim().split("\n")
    // Přeskočit řádky 0 (datum) a 1 (hlavička)
    for (const line of lines.slice(2)) {
      const parts = line.split("|")
      if (parts.length < 5) continue
      const quantity = parseFloat(parts[2])
      const code = parts[3].trim()
      const rate = parseFloat(parts[4].replace(",", "."))
      if (code && !isNaN(rate) && !isNaN(quantity) && quantity > 0) {
        rates[code] = rate / quantity
      }
    }

    czkRatesCache = { rates, ts: Date.now() }
  } catch {
    // Při chybě vrátit fallback hodnoty aby app nespadla
    if (!rates["EUR"]) rates["EUR"] = 25.2
    if (!rates["USD"]) rates["USD"] = 23.1
  }

  return rates
}

// Převede částku z cizí měny na CZK
export function toCzk(amount: number, currency: string, czkRates: CzkRates): number {
  if (currency === "CZK") return amount
  const rate = czkRates[currency]
  if (!rate) return amount // neznámá měna — vrátit beze změny
  return amount * rate
}
