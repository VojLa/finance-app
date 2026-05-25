import YahooFinance from "yahoo-finance2"
import { prisma, toNum } from "@/lib/prisma"
import type { AssetType, ExchangeRateSource, PriceSource } from "@prisma/client"

const yf = new YahooFinance()

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

type LivePrice = { price: number; currency: string; source: PriceSource }
type PublicPrice = { price: number; currency: string }
type CzkRates = Record<string, number>

const PRICE_TTL = 15 * 60 * 1000
const FX_TTL = 4 * 60 * 60 * 1000

const priceCache: Record<
  string,
  { price: number; currency: string; source: PriceSource; ts: number }
> = {}
let czkRatesCache: { rates: CzkRates; ts: number } | null = null
let czkRatesFetch: Promise<CzkRates> | null = null

const CNB_URL =
  "https://www.cnb.cz/cs/financni-trhy/devizovy-trh/kurzy-devizoveho-trhu/kurzy-devizoveho-trhu/denni_kurz.txt"

export function clearPriceCache() {
  for (const key of Object.keys(priceCache)) delete priceCache[key]
}

function todayStart(date = new Date()): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

function cacheKey(symbol: string, assetType: string): string {
  return `${symbol.toUpperCase()}:${assetType}`
}

async function ensureAsset(symbol: string, assetType: string, currency: string) {
  return prisma.asset.upsert({
    where: { symbol: symbol.toUpperCase() },
    update: {
      assetType: assetType as AssetType,
      currency,
    },
    create: {
      symbol: symbol.toUpperCase(),
      assetType: assetType as AssetType,
      currency,
    },
  })
}

async function getStoredLivePrice(
  symbol: string,
  assetType: string,
  maxAgeMs: number
): Promise<LivePrice | null> {
  const asset = await prisma.asset.findUnique({
    where: { symbol: symbol.toUpperCase() },
    select: { id: true },
  })
  if (!asset) return null

  const minTimestamp = new Date(Date.now() - maxAgeMs)
  const snapshot = await prisma.priceSnapshot.findFirst({
    where: {
      assetId: asset.id,
      timestamp: { gte: minTimestamp },
    },
    orderBy: { timestamp: "desc" },
  })

  if (!snapshot) return null

  return {
    price: toNum(snapshot.price),
    currency: snapshot.currency,
    source: snapshot.source,
  }
}

async function storePriceSnapshot(
  symbol: string,
  assetType: string,
  fallbackCurrency: string,
  data: LivePrice
): Promise<void> {
  const asset = await ensureAsset(symbol, assetType, data.currency || fallbackCurrency)

  await prisma.priceSnapshot.create({
    data: {
      assetId: asset.id,
      price: data.price,
      currency: data.currency,
      source: data.source,
      timestamp: new Date(),
    },
  })
}

async function getStooqPrice(symbol: string, currency: string): Promise<LivePrice | null> {
  let suffix: string
  if (currency === "GBP") suffix = ".uk"
  else if (currency === "EUR") suffix = ".de"
  else suffix = ".us"

  try {
    const url = `https://stooq.com/q/l/?s=${symbol.toLowerCase()}${suffix}&f=sd2t2ohlcvn&e=csv`
    const res = await fetch(url)
    if (!res.ok) return null

    const text = await res.text()
    const parts = text.trim().split(",")
    if (parts.length < 7 || parts[6] === "N/D") return null

    const price = Number.parseFloat(parts[6])
    if (!Number.isFinite(price) || price <= 0) return null

    return { price, currency, source: "stooq" as const }
  } catch {
    return null
  }
}

async function getCoinGeckoPrice(symbol: string): Promise<LivePrice | null> {
  const geckoId = COINGECKO_IDS[symbol.toUpperCase()]
  if (!geckoId) return null

  try {
    const url = `https://api.coingecko.com/api/v3/simple/price?ids=${geckoId}&vs_currencies=eur`
    const res = await fetch(url, { headers: { Accept: "application/json" } })
    if (!res.ok) return null

    const data = await res.json()
    const price = data[geckoId]?.eur
    if (!Number.isFinite(price) || price <= 0) return null

    return { price, currency: "EUR", source: "coingecko" }
  } catch {
    return null
  }
}

async function getYahooPrice(symbol: string, fallbackCurrency: string): Promise<LivePrice | null> {
  return yf
    .quote(symbol)
    .then((quote) => {
      const price = quote.regularMarketPrice
      if (!Number.isFinite(price) || !price) return null

      return {
        price,
        currency: quote.currency ?? fallbackCurrency,
        source: "yahoo_finance" as const,
      }
    })
    .catch(() => null)
}

export async function getLivePrice(
  symbol: string,
  assetType: string,
  currency: string,
  refresh = false
): Promise<PublicPrice | null> {
  const key = cacheKey(symbol, assetType)
  const cached = priceCache[key]

  if (!refresh && cached && Date.now() - cached.ts < PRICE_TTL) {
    return { price: cached.price, currency: cached.currency }
  }

  const stored = !refresh ? await getStoredLivePrice(symbol, assetType, FX_TTL) : null
  if (stored) {
    priceCache[key] = { ...stored, ts: Date.now() }
    return { price: stored.price, currency: stored.currency }
  }

  const fetched =
    assetType === "crypto"
      ? await getCoinGeckoPrice(symbol)
      : ((await getYahooPrice(symbol, currency)) ?? (await getStooqPrice(symbol, currency)))

  if (!fetched) return null

  priceCache[key] = { ...fetched, ts: Date.now() }
  await storePriceSnapshot(symbol, assetType, currency, fetched)

  return { price: fetched.price, currency: fetched.currency }
}

export async function getLivePrices(
  symbols: { symbol: string; assetType: string; currency: string }[],
  refresh = false
): Promise<Record<string, PublicPrice | null>> {
  const uniqueSymbols = symbols.filter(
    (item, index, arr) =>
      arr.findIndex(
        (other) => other.symbol === item.symbol && other.assetType === item.assetType
      ) === index
  )

  const results = await Promise.all(
    uniqueSymbols.map(async ({ symbol, assetType, currency }) => ({
      symbol,
      data: await getLivePrice(symbol, assetType, currency, refresh),
    }))
  )

  return Object.fromEntries(results.map((r) => [r.symbol, r.data]))
}

function parseCnbDate(header: string): Date {
  const match = header.match(/(\d{2})\.(\d{2})\.(\d{4})/)
  if (!match) return todayStart()

  const [, day, month, year] = match
  return new Date(Number(year), Number(month) - 1, Number(day))
}

async function storeExchangeRates(
  rates: CzkRates,
  date: Date,
  source: ExchangeRateSource
): Promise<void> {
  await Promise.all(
    Object.entries(rates)
      .filter(([currency]) => currency !== "CZK")
      .map(([fromCurrency, rate]) =>
        prisma.exchangeRate.upsert({
          where: {
            fromCurrency_toCurrency_date_source: {
              fromCurrency,
              toCurrency: "CZK",
              date,
              source,
            },
          },
          update: { rate },
          create: {
            fromCurrency,
            toCurrency: "CZK",
            date,
            source,
            rate,
          },
        })
      )
  )
}

async function loadStoredCzkRates(date?: Date): Promise<CzkRates | null> {
  const whereDate = date ? todayStart(date) : undefined

  const rows = await prisma.exchangeRate.findMany({
    where: {
      toCurrency: "CZK",
      ...(whereDate ? { date: { lte: whereDate } } : {}),
    },
    orderBy: { date: "desc" },
  })

  if (rows.length === 0) return null

  const rates: CzkRates = { CZK: 1 }
  for (const row of rows) {
    if (!rates[row.fromCurrency]) {
      rates[row.fromCurrency] = toNum(row.rate)
    }
  }

  return rates
}

async function fetchCnbRates(): Promise<CzkRates> {
  const rates: CzkRates = { CZK: 1 }

  const res = await fetch(CNB_URL)
  if (!res.ok) throw new Error(`CNB HTTP ${res.status}`)

  const text = await res.text()
  const lines = text.trim().split("\n")
  const rateDate = parseCnbDate(lines[0] ?? "")

  for (const line of lines.slice(2)) {
    const parts = line.split("|")
    if (parts.length < 5) continue

    const quantity = Number.parseFloat(parts[2])
    const code = parts[3].trim()
    const rate = Number.parseFloat(parts[4].replace(",", "."))

    if (code && Number.isFinite(rate) && Number.isFinite(quantity) && quantity > 0) {
      rates[code] = rate / quantity
    }
  }

  await storeExchangeRates(rates, todayStart(rateDate), "cnb")
  return rates
}

export async function getCzkRates(refresh = false): Promise<CzkRates> {
  if (!refresh && czkRatesCache && Date.now() - czkRatesCache.ts < FX_TTL) {
    return czkRatesCache.rates
  }

  if (czkRatesFetch) return czkRatesFetch

  czkRatesFetch = (async () => {
    if (!refresh) {
      const stored = await loadStoredCzkRates()
      if (stored && stored.EUR && stored.USD) {
        czkRatesCache = { rates: stored, ts: Date.now() }
        return stored
      }
    }

    try {
      const fetched = await fetchCnbRates()
      czkRatesCache = { rates: fetched, ts: Date.now() }
      return fetched
    } catch {
      const stored = await loadStoredCzkRates()
      const fallback = stored ?? { CZK: 1, EUR: 25.2, USD: 23.1 }
      czkRatesCache = { rates: fallback, ts: Date.now() }
      return fallback
    }
  })().finally(() => {
    czkRatesFetch = null
  })

  return czkRatesFetch
}

export async function getHistoricalCzkRates(date: Date): Promise<CzkRates> {
  return (await loadStoredCzkRates(date)) ?? (await getCzkRates())
}

export function toCzk(amount: number, currency: string, czkRates: CzkRates): number {
  if (currency === "CZK") return amount

  const rate = czkRates[currency]
  if (!rate) return amount

  return amount * rate
}
