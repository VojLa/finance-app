import { prisma, toNum } from "@/lib/prisma"
import type { AssetAliasProvider, AssetType, ExchangeRateSource, PriceSource } from "@prisma/client"

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

const DEFAULT_PRICE_ALIASES: Record<string, Partial<Record<AssetAliasProvider, string[]>>> = {
  CSPX: { yahoo_finance: ["CSPX.L"], stooq: ["cspx.uk"] },
  EUNL: { yahoo_finance: ["EUNL.DE"], stooq: ["eunl.de"] },
  IWDA: { yahoo_finance: ["IWDA.AS", "IWDA.L"], stooq: ["iwda.nl", "iwda.uk"] },
  SXR8: { yahoo_finance: ["SXR8.DE"], stooq: ["sxr8.de"] },
  VUAA: {
    yahoo_finance: ["VUAA.DE", "VUAA.L", "VUAA.MI"],
    stooq: ["vuaa.de", "vuaa.uk", "vuaa.it"],
  },
  VWCE: { yahoo_finance: ["VWCE.DE"], stooq: ["vwce.de"] },
}

type LivePrice = { price: number; currency: string; source: PriceSource }
type PublicPrice = { price: number; currency: string }
export type HistoricalPricePoint = {
  date: Date
  price: number
  currency: string
  source: PriceSource
}
type CzkRates = Record<string, number>
type ProviderAliases = Partial<Record<AssetAliasProvider, string[]>>

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

function addDays(date: Date, days: number): Date {
  const next = new Date(date)
  next.setDate(next.getDate() + days)
  return next
}

function cacheKey(symbol: string, assetType: string): string {
  return `${symbol.toUpperCase()}:${assetType}`
}

function unique(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))]
}

async function getAssetAliases(symbol: string): Promise<ProviderAliases> {
  const asset = await prisma.asset.findUnique({
    where: { symbol: symbol.toUpperCase() },
    include: { aliases: true },
  })

  const aliases: ProviderAliases = {}
  for (const alias of asset?.aliases ?? []) {
    aliases[alias.provider] ||= []
    aliases[alias.provider]?.push(alias.externalId)
  }

  const defaults = DEFAULT_PRICE_ALIASES[symbol.toUpperCase()] ?? {}
  for (const [provider, providerAliases] of Object.entries(defaults) as Array<
    [AssetAliasProvider, string[]]
  >) {
    aliases[provider] = unique([...(aliases[provider] ?? []), ...providerAliases])
  }

  return aliases
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

async function ensureAssetListing(
  assetId: string,
  symbol: string,
  currency: string,
  source: PriceSource
) {
  return prisma.assetListing.upsert({
    where: {
      assetId_symbol_exchange_currency: {
        assetId,
        symbol: symbol.toUpperCase(),
        exchange: source,
        currency,
      },
    },
    update: {
      provider: source,
      providerSymbol: symbol.toUpperCase(),
    },
    create: {
      assetId,
      symbol: symbol.toUpperCase(),
      exchange: source,
      currency,
      provider: source,
      providerSymbol: symbol.toUpperCase(),
      isPrimary: true,
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
  const listing = await ensureAssetListing(asset.id, symbol, data.currency, data.source)

  await prisma.priceSnapshot.create({
    data: {
      assetId: asset.id,
      listingId: listing.id,
      price: data.price,
      currency: data.currency,
      source: data.source,
      timestamp: new Date(),
    },
  })
}

async function storePriceSnapshotAt(
  symbol: string,
  assetType: string,
  fallbackCurrency: string,
  data: HistoricalPricePoint
): Promise<void> {
  const asset = await ensureAsset(symbol, assetType, data.currency || fallbackCurrency)
  const listing = await ensureAssetListing(asset.id, symbol, data.currency, data.source)

  await prisma.priceSnapshot.upsert({
    where: {
      assetId_timestamp_source: {
        assetId: asset.id,
        timestamp: data.date,
        source: data.source,
      },
    },
    update: {
      price: data.price,
      currency: data.currency,
    },
    create: {
      assetId: asset.id,
      listingId: listing.id,
      price: data.price,
      currency: data.currency,
      source: data.source,
      timestamp: data.date,
    },
  })
}

function stooqCandidates(symbol: string, currency: string, aliases: ProviderAliases): string[] {
  let suffix: string
  if (currency === "GBP") suffix = ".uk"
  else if (currency === "EUR") suffix = ".de"
  else suffix = ".us"

  return unique([
    ...(aliases.stooq ?? []),
    symbol.includes(".") ? symbol.toLowerCase() : `${symbol.toLowerCase()}${suffix}`,
    `${symbol.toLowerCase()}.de`,
    `${symbol.toLowerCase()}.us`,
    `${symbol.toLowerCase()}.uk`,
  ])
}

async function getStooqPrice(
  symbol: string,
  currency: string,
  aliases: ProviderAliases
): Promise<LivePrice | null> {
  const candidates = stooqCandidates(symbol, currency, aliases)

  try {
    for (const candidate of candidates) {
      const url = `https://stooq.com/q/l/?s=${candidate}&f=sd2t2ohlcvn&e=csv`
      const res = await fetch(url)
      if (!res.ok) continue

      const text = await res.text()
      const parts = text.trim().split(",")
      if (parts.length < 7 || parts[6] === "N/D") continue

      const price = Number.parseFloat(parts[6])
      if (!Number.isFinite(price) || price <= 0) continue

      return { price, currency, source: "stooq" as const }
    }

    return null
  } catch {
    return null
  }
}

async function getCoinGeckoPrice(
  symbol: string,
  aliases: ProviderAliases
): Promise<LivePrice | null> {
  const candidates = unique([...(aliases.coingecko ?? []), COINGECKO_IDS[symbol.toUpperCase()]])
  if (candidates.length === 0) return null

  try {
    const url = `https://api.coingecko.com/api/v3/simple/price?ids=${candidates.join(",")}&vs_currencies=eur`
    const res = await fetch(url, { headers: { Accept: "application/json" } })
    if (!res.ok) return null

    const data = await res.json()
    for (const geckoId of candidates) {
      const price = data[geckoId]?.eur
      if (!Number.isFinite(price) || price <= 0) continue

      return { price, currency: "EUR", source: "coingecko" }
    }

    return null
  } catch {
    return null
  }
}

async function getYahooPrice(
  symbol: string,
  fallbackCurrency: string,
  aliases: ProviderAliases
): Promise<LivePrice | null> {
  const candidates = unique([
    ...(aliases.yahoo_finance ?? []),
    symbol,
    `${symbol}.DE`,
    `${symbol}.AS`,
    `${symbol}.L`,
    `${symbol}.MI`,
    `${symbol}.PA`,
  ])

  for (const candidate of candidates) {
    const chartPrice = await getYahooChartPrice(candidate, fallbackCurrency)
    if (chartPrice) return chartPrice
  }

  return null
}

async function getYahooChartPrice(
  symbol: string,
  fallbackCurrency: string
): Promise<LivePrice | null> {
  try {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(
      symbol
    )}?range=1d&interval=1d`
    const res = await fetch(url, { headers: { Accept: "application/json" } })
    if (!res.ok) return null

    const data = await res.json()
    const result = data.chart?.result?.[0]
    const price = result?.meta?.regularMarketPrice
    if (!Number.isFinite(price) || price <= 0) return null

    return {
      price,
      currency: result?.meta?.currency ?? fallbackCurrency,
      source: "yahoo_finance",
    }
  } catch {
    return null
  }
}

async function getYahooHistoricalPrices(
  symbol: string,
  fallbackCurrency: string,
  aliases: ProviderAliases,
  start: Date,
  end: Date
): Promise<HistoricalPricePoint[]> {
  const candidates = unique([
    ...(aliases.yahoo_finance ?? []),
    symbol,
    `${symbol}.DE`,
    `${symbol}.AS`,
    `${symbol}.L`,
    `${symbol}.MI`,
    `${symbol}.PA`,
  ])

  const period1 = Math.floor(start.getTime() / 1000)
  const period2 = Math.floor(end.getTime() / 1000)

  for (const candidate of candidates) {
    try {
      const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(
        candidate
      )}?period1=${period1}&period2=${period2}&interval=1d`
      const res = await fetch(url, { headers: { Accept: "application/json" } })
      if (!res.ok) continue

      const data = await res.json()
      const result = data.chart?.result?.[0]
      const timestamps: number[] = result?.timestamp ?? []
      const closes: Array<number | null> = result?.indicators?.quote?.[0]?.close ?? []
      const currency = result?.meta?.currency ?? fallbackCurrency

      const prices: HistoricalPricePoint[] = []
      timestamps.forEach((timestamp, index) => {
        const price = closes[index]
        if (!Number.isFinite(price) || price === null || price <= 0) return

        prices.push({
          date: todayStart(new Date(timestamp * 1000)),
          price,
          currency,
          source: "yahoo_finance",
        })
      })

      if (prices.length > 0) return prices
    } catch {
      continue
    }
  }

  return []
}

async function getCoinGeckoHistoricalPrices(
  symbol: string,
  aliases: ProviderAliases,
  start: Date,
  end: Date
): Promise<HistoricalPricePoint[]> {
  const candidates = unique([...(aliases.coingecko ?? []), COINGECKO_IDS[symbol.toUpperCase()]])
  if (candidates.length === 0) return []

  for (const geckoId of candidates) {
    const mergedByDay = new Map<string, HistoricalPricePoint>()
    let cursor = todayStart(start)

    while (cursor <= end) {
      const chunkEnd = new Date(Math.min(addDays(cursor, 365).getTime(), end.getTime()))
      const from = Math.floor(cursor.getTime() / 1000)
      const to = Math.floor(chunkEnd.getTime() / 1000)

      try {
        const url = `https://api.coingecko.com/api/v3/coins/${geckoId}/market_chart/range?vs_currency=eur&from=${from}&to=${to}`
        const res = await fetch(url, { headers: { Accept: "application/json" } })
        if (!res.ok) break

        const data = await res.json()
        const prices = ((data.prices ?? []) as Array<[number, number]>)
          .map(([timestamp, price]) => ({
            date: todayStart(new Date(timestamp)),
            price,
            currency: "EUR",
            source: "coingecko" as const,
          }))
          .filter((point) => Number.isFinite(point.price) && point.price > 0)

        for (const price of prices) {
          mergedByDay.set(price.date.toISOString().slice(0, 10), price)
        }
      } catch {
        break
      }

      cursor = addDays(chunkEnd, 1)
    }

    if (mergedByDay.size > 0) {
      return [...mergedByDay.values()].sort((a, b) => a.date.getTime() - b.date.getTime())
    }
  }

  return []
}

async function getStoredHistoricalPrices(
  symbol: string,
  start: Date,
  end: Date
): Promise<HistoricalPricePoint[]> {
  const asset = await prisma.asset.findUnique({
    where: { symbol: symbol.toUpperCase() },
    select: { id: true },
  })
  if (!asset) return []

  const snapshots = await prisma.priceSnapshot.findMany({
    where: {
      assetId: asset.id,
      timestamp: { gte: start, lte: end },
    },
    orderBy: { timestamp: "asc" },
  })

  return snapshots.map((snapshot) => ({
    date: snapshot.timestamp,
    price: toNum(snapshot.price),
    currency: snapshot.currency,
    source: snapshot.source,
  }))
}

async function updateHoldingMarketValues(
  symbol: string,
  assetType: string,
  data: LivePrice
): Promise<void> {
  const holdings = await prisma.holding.findMany({
    where: { symbol: symbol.toUpperCase(), assetType: assetType as AssetType },
    select: { id: true, quantity: true, avgBuyPrice: true, currency: true },
  })

  if (holdings.length === 0) return

  await Promise.all(
    holdings.map((holding) => {
      const quantity = toNum(holding.quantity)
      const currentValue = quantity * data.price
      const cost = quantity * toNum(holding.avgBuyPrice)
      const unrealizedPnl = data.currency === holding.currency ? currentValue - cost : null

      return prisma.holding.update({
        where: { id: holding.id },
        data: {
          currentPrice: data.price,
          currentValue,
          unrealizedPnl,
        },
      })
    })
  )
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
    await updateHoldingMarketValues(symbol, assetType, stored)
    return { price: stored.price, currency: stored.currency }
  }

  const aliases = await getAssetAliases(symbol)
  const fetched =
    assetType === "crypto"
      ? await getCoinGeckoPrice(symbol, aliases)
      : ((await getYahooPrice(symbol, currency, aliases)) ??
        (await getStooqPrice(symbol, currency, aliases)))

  if (!fetched) return null

  priceCache[key] = { ...fetched, ts: Date.now() }
  await storePriceSnapshot(symbol, assetType, currency, fetched)
  await updateHoldingMarketValues(symbol, assetType, fetched)

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

export async function getHistoricalPrices(
  symbols: { symbol: string; assetType: string; currency: string }[],
  start: Date,
  end: Date
): Promise<Record<string, HistoricalPricePoint[]>> {
  const uniqueSymbols = symbols.filter(
    (item, index, arr) =>
      arr.findIndex(
        (other) => other.symbol === item.symbol && other.assetType === item.assetType
      ) === index
  )

  const results = await Promise.all(
    uniqueSymbols.map(async ({ symbol, assetType, currency }) => {
      const stored = await getStoredHistoricalPrices(symbol, start, end)
      const aliases = await getAssetAliases(symbol)
      let fetched: HistoricalPricePoint[]
      if (assetType === "crypto") {
        fetched = await getCoinGeckoHistoricalPrices(symbol, aliases, start, end)
        if (fetched.length === 0) {
          fetched = await getYahooHistoricalPrices(
            symbol,
            "EUR",
            {
              ...aliases,
              yahoo_finance: unique([
                ...(aliases.yahoo_finance ?? []),
                `${symbol.toUpperCase()}-EUR`,
              ]),
            },
            start,
            end
          )
        }
      } else {
        fetched = await getYahooHistoricalPrices(symbol, currency, aliases, start, end)
      }

      const mergedByDay = new Map<string, HistoricalPricePoint>()
      for (const point of [...stored, ...fetched]) {
        mergedByDay.set(point.date.toISOString().slice(0, 10), point)
      }

      await Promise.all(
        fetched.map((point) => storePriceSnapshotAt(symbol, assetType, currency, point))
      )

      return {
        symbol,
        data: [...mergedByDay.values()].sort((a, b) => a.date.getTime() - b.date.getTime()),
      }
    })
  )

  return Object.fromEntries(results.map((result) => [result.symbol, result.data]))
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
