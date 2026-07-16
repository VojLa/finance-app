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

type LivePrice = {
  price: number
  currency: string
  source: PriceSource
  providerSymbol?: string | null
  listingId?: string | null
}
type PublicPrice = { price: number; currency: string }
export type HistoricalPricePoint = {
  date: Date
  price: number
  currency: string
  source: PriceSource
  providerSymbol?: string | null
}
type CzkRates = Record<string, number>
type ProviderAliases = Partial<Record<AssetAliasProvider, string[]>>
type PriceLookupInput = {
  symbol: string
  assetType: string
  currency: string
  listingId?: string | null
}

const PRICE_TTL = 15 * 60 * 1000
const FX_TTL = 4 * 60 * 60 * 1000
const YAHOO_EXCHANGE_RATE_SOURCE: ExchangeRateSource = "yahoo_finance"
const DEFAULT_FX_CURRENCIES = [
  "EUR",
  "USD",
  "GBP",
  "CHF",
  "PLN",
  "HUF",
  "AUD",
  "CAD",
  "JPY",
  "SEK",
  "NOK",
  "DKK",
]

const priceCache: Record<
  string,
  {
    price: number
    currency: string
    source: PriceSource
    providerSymbol?: string | null
    listingId?: string | null
    ts: number
  }
> = {}
let czkRatesCache: { rates: CzkRates; ts: number } | null = null
let czkRatesFetch: Promise<CzkRates> | null = null

export function clearPriceCache() {
  for (const key of Object.keys(priceCache)) delete priceCache[key]
}

function todayStart(date = new Date()): Date {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()))
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date)
  next.setUTCDate(next.getUTCDate() + days)
  return next
}

function cacheKey(symbol: string, assetType: string): string {
  return `${symbol.toUpperCase()}:${assetType}`
}

export function priceLookupKey(input: PriceLookupInput): string {
  return input.listingId ?? `${input.symbol.toUpperCase()}:${input.assetType}:${input.currency}`
}

function unique(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))]
}

async function getAssetAliases(symbol: string): Promise<ProviderAliases> {
  const asset = await prisma.asset.findFirst({
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
  const normalizedSymbol = symbol.toUpperCase()
  const existing = await prisma.asset.findFirst({
    where: { symbol: normalizedSymbol, assetType: assetType as AssetType },
  })
  if (existing) return existing

  return prisma.asset.create({
    data: {
      symbol: normalizedSymbol,
      assetType: assetType as AssetType,
      currency,
    },
  })
}

async function ensureAssetListing(
  assetId: string,
  symbol: string,
  currency: string,
  source: PriceSource,
  providerSymbol?: string | null
) {
  const normalizedSymbol = symbol.toUpperCase()
  const normalizedProviderSymbol = (providerSymbol ?? symbol).toUpperCase()
  const findExisting = async () => {
    const byProvider = await prisma.assetListing.findUnique({
      where: {
        provider_providerSymbol_currency: {
          provider: source,
          providerSymbol: normalizedProviderSymbol,
          currency,
        },
      },
    })
    if (byProvider) return byProvider

    const byAssetIdentity = await prisma.assetListing.findFirst({
      where: {
        assetId,
        symbol: normalizedSymbol,
        exchange: source,
        currency,
      },
    })
    if (byAssetIdentity) return byAssetIdentity

    return prisma.assetListing.findFirst({
      where: {
        symbol: normalizedSymbol,
        exchange: source,
        currency,
      },
      orderBy: [{ isPrimary: "desc" }, { updatedAt: "desc" }],
    })
  }

  const existing = await findExisting()
  if (existing) return existing

  try {
    return await prisma.assetListing.create({
      data: {
        assetId,
        symbol: normalizedSymbol,
        exchange: source,
        currency,
        provider: source,
        providerSymbol: normalizedProviderSymbol,
        isPrimary: true,
      },
    })
  } catch (error) {
    if (typeof error === "object" && error !== null && "code" in error && error.code === "P2002") {
      const existingAfterRace = await findExisting()
      if (existingAfterRace) return existingAfterRace
    }

    throw error
  }
}

async function findPriceListing(input: PriceLookupInput) {
  if (input.listingId) {
    return prisma.assetListing.findUnique({
      where: { id: input.listingId },
      include: { asset: true },
    })
  }

  const symbol = input.symbol.toUpperCase()
  return prisma.assetListing.findFirst({
    where: {
      currency: input.currency,
      asset: { assetType: input.assetType as AssetType },
      OR: [{ symbol }, { providerSymbol: symbol }],
    },
    include: { asset: true },
    orderBy: [{ isPrimary: "desc" }, { updatedAt: "desc" }],
  })
}

async function getStoredLivePrice(
  input: PriceLookupInput,
  maxAgeMs: number
): Promise<LivePrice | null> {
  const listing = await findPriceListing(input)
  if (!listing) return null
  const minTimestamp = new Date(Date.now() - maxAgeMs)
  const snapshot = await prisma.priceSnapshot.findFirst({
    where: input.listingId
      ? {
          OR: [{ listingId: listing.id }, { assetId: listing.assetId }],
          timestamp: { gte: minTimestamp },
        }
      : {
          currency: input.currency,
          OR: [{ listingId: listing.id }, { assetId: listing.assetId }],
          timestamp: { gte: minTimestamp },
        },
    orderBy: { timestamp: "desc" },
  })

  if (!snapshot) return null

  return {
    price: toNum(snapshot.price),
    currency: snapshot.currency,
    source: snapshot.source,
    providerSymbol: listing.providerSymbol,
    listingId: listing.id,
  }
}

async function storePriceSnapshot(
  symbol: string,
  assetType: string,
  fallbackCurrency: string,
  data: LivePrice,
  listingId?: string | null
): Promise<LivePrice> {
  const existingListing = listingId
    ? await prisma.assetListing.findUnique({ where: { id: listingId }, include: { asset: true } })
    : null
  const asset =
    existingListing?.asset ??
    (await ensureAsset(symbol, assetType, data.currency || fallbackCurrency))
  const listing =
    existingListing ??
    (await ensureAssetListing(
      asset.id,
      data.providerSymbol ?? symbol,
      data.currency,
      data.source,
      data.providerSymbol
    ))

  const timestamp = new Date()
  await prisma.priceSnapshot.upsert({
    where: {
      listingId_timestamp_source: {
        listingId: listing.id,
        timestamp,
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
      timestamp,
    },
  })

  return { ...data, listingId: listing.id }
}

async function storePriceSnapshotAt(
  symbol: string,
  assetType: string,
  fallbackCurrency: string,
  data: HistoricalPricePoint,
  listingId?: string | null
): Promise<void> {
  const existingListing = listingId
    ? await prisma.assetListing.findUnique({ where: { id: listingId }, include: { asset: true } })
    : null
  const asset =
    existingListing?.asset ??
    (await ensureAsset(symbol, assetType, data.currency || fallbackCurrency))
  const listing =
    existingListing ??
    (await ensureAssetListing(
      asset.id,
      data.providerSymbol ?? symbol,
      data.currency,
      data.source,
      data.providerSymbol
    ))

  await prisma.priceSnapshot.upsert({
    where: {
      listingId_timestamp_source: {
        listingId: listing.id,
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

      return { price, currency, source: "stooq" as const, providerSymbol: candidate }
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

      return { price, currency: "EUR", source: "coingecko", providerSymbol: geckoId }
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
      providerSymbol: symbol,
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
          providerSymbol: candidate,
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
            providerSymbol: geckoId,
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
  input: PriceLookupInput,
  start: Date,
  end: Date
): Promise<HistoricalPricePoint[]> {
  const listing = await findPriceListing(input)
  if (!listing) return []

  const snapshots = await prisma.priceSnapshot.findMany({
    where: input.listingId
      ? {
          OR: [{ listingId: listing.id }, { assetId: listing.assetId }],
          timestamp: { gte: start, lte: end },
        }
      : {
          currency: input.currency,
          OR: [{ listingId: listing.id }, { assetId: listing.assetId }],
          timestamp: { gte: start, lte: end },
        },
    orderBy: { timestamp: "asc" },
  })

  return snapshots.map((snapshot) => ({
    date: snapshot.timestamp,
    price: toNum(snapshot.price),
    currency: snapshot.currency,
    source: snapshot.source,
    providerSymbol: listing.providerSymbol,
  }))
}

async function updateHoldingMarketValues(input: PriceLookupInput, data: LivePrice): Promise<void> {
  const holdings = await prisma.holding.findMany({
    where: input.listingId
      ? { listingId: input.listingId }
      : data.listingId
        ? { listingId: data.listingId }
        : { symbol: input.symbol.toUpperCase(), assetType: input.assetType as AssetType },
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
  refresh = false,
  listingId?: string | null
): Promise<PublicPrice | null> {
  const input = { symbol, assetType, currency, listingId }
  const key = listingId ?? cacheKey(symbol, `${assetType}:${currency}`)
  const cached = priceCache[key]

  if (!refresh && cached && Date.now() - cached.ts < PRICE_TTL) {
    return { price: cached.price, currency: cached.currency }
  }

  const stored = !refresh ? await getStoredLivePrice(input, FX_TTL) : null
  if (stored) {
    priceCache[key] = { ...stored, ts: Date.now() }
    await updateHoldingMarketValues(input, stored)
    return { price: stored.price, currency: stored.currency }
  }

  const aliases = await getAssetAliases(symbol)
  const fetched =
    assetType === "crypto"
      ? await getCoinGeckoPrice(symbol, aliases)
      : ((await getYahooPrice(symbol, currency, aliases)) ??
        (await getStooqPrice(symbol, currency, aliases)))

  if (!fetched) return null

  const priced = await storePriceSnapshot(symbol, assetType, currency, fetched, listingId)
  priceCache[key] = { ...priced, ts: Date.now() }
  await updateHoldingMarketValues(input, priced)

  return { price: priced.price, currency: priced.currency }
}

export async function getLivePrices(
  symbols: PriceLookupInput[],
  refresh = false
): Promise<Record<string, PublicPrice | null>> {
  const uniqueSymbols = symbols.filter(
    (item, index, arr) =>
      arr.findIndex((other) => priceLookupKey(other) === priceLookupKey(item)) === index
  )

  const results = await Promise.all(
    uniqueSymbols.map(async ({ symbol, assetType, currency, listingId }) => ({
      key: priceLookupKey({ symbol, assetType, currency, listingId }),
      symbol,
      data: await getLivePrice(symbol, assetType, currency, refresh, listingId),
    }))
  )

  const output: Record<string, PublicPrice | null> = {}
  for (const result of results) {
    output[result.key] = result.data
    output[result.symbol] ??= result.data
  }
  return output
}

export async function getHistoricalPrices(
  symbols: PriceLookupInput[],
  start: Date,
  end: Date
): Promise<Record<string, HistoricalPricePoint[]>> {
  const uniqueSymbols = symbols.filter(
    (item, index, arr) =>
      arr.findIndex((other) => priceLookupKey(other) === priceLookupKey(item)) === index
  )

  const results = await Promise.all(
    uniqueSymbols.map(async ({ symbol, assetType, currency, listingId }) => {
      const input = { symbol, assetType, currency, listingId }
      const stored = await getStoredHistoricalPrices(input, start, end)
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
        fetched.map((point) => storePriceSnapshotAt(symbol, assetType, currency, point, listingId))
      )

      return {
        key: priceLookupKey(input),
        symbol,
        data: [...mergedByDay.values()].sort((a, b) => a.date.getTime() - b.date.getTime()),
      }
    })
  )

  const output: Record<string, HistoricalPricePoint[]> = {}
  for (const result of results) {
    output[result.key] = result.data
    output[result.symbol] ??= result.data
  }
  return output
}

function normalizeCurrencyList(currencies: Array<string | null | undefined>, baseCurrency: string) {
  const normalizedBaseCurrency = baseCurrency.toUpperCase()
  return [
    ...new Set(
      currencies
        .map((currency) => currency?.toUpperCase())
        .filter(
          (currency): currency is string => Boolean(currency) && currency !== normalizedBaseCurrency
        )
    ),
  ]
}

async function loadStoredExchangeRates({
  date,
  toCurrency = "CZK",
  currencies = DEFAULT_FX_CURRENCIES,
}: {
  date?: Date
  toCurrency?: string
  currencies?: string[]
} = {}): Promise<CzkRates | null> {
  const whereDate = date ? todayStart(date) : undefined
  const normalizedToCurrency = toCurrency.toUpperCase()
  const normalizedCurrencies = normalizeCurrencyList(currencies, normalizedToCurrency)

  const rows = await prisma.exchangeRate.findMany({
    where: {
      toCurrency: normalizedToCurrency,
      ...(normalizedCurrencies.length > 0 ? { fromCurrency: { in: normalizedCurrencies } } : {}),
      ...(whereDate ? { date: { lte: whereDate } } : {}),
    },
    orderBy: [{ date: "desc" }, { source: "desc" }],
  })

  if (rows.length === 0 && normalizedCurrencies.length > 0) return null

  const rates: CzkRates = { [normalizedToCurrency]: 1 }
  for (const row of rows) {
    if (!rates[row.fromCurrency]) {
      rates[row.fromCurrency] = toNum(row.rate)
    }
  }

  return rates
}

async function fetchYahooHistoricalExchangeRates(
  currencies: string[],
  toCurrency: string,
  start: Date,
  end: Date
): Promise<CzkRates> {
  const normalizedToCurrency = toCurrency.toUpperCase()
  const normalizedCurrencies = normalizeCurrencyList(currencies, normalizedToCurrency)
  const period1 = Math.floor(todayStart(start).getTime() / 1000)
  const period2 = Math.floor(addDays(todayStart(end), 1).getTime() / 1000)
  const latestRates: CzkRates = { [normalizedToCurrency]: 1 }

  await Promise.all(
    normalizedCurrencies.map(async (fromCurrency) => {
      const pair = `${fromCurrency}${normalizedToCurrency}=X`
      try {
        const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(
          pair
        )}?period1=${period1}&period2=${period2}&interval=1d`
        const res = await fetch(url, { headers: { Accept: "application/json" } })
        if (!res.ok) return

        const data = await res.json()
        const result = data.chart?.result?.[0]
        const timestamps: number[] = result?.timestamp ?? []
        const closes: Array<number | null> = result?.indicators?.quote?.[0]?.close ?? []
        const writes: Array<Promise<unknown>> = []

        timestamps.forEach((timestamp, index) => {
          const rate = closes[index]
          if (!Number.isFinite(rate) || rate === null || rate <= 0) return

          const date = todayStart(new Date(timestamp * 1000))
          latestRates[fromCurrency] = rate

          writes.push(
            prisma.exchangeRate.upsert({
              where: {
                fromCurrency_toCurrency_date_source: {
                  fromCurrency,
                  toCurrency: normalizedToCurrency,
                  date,
                  source: YAHOO_EXCHANGE_RATE_SOURCE,
                },
              },
              update: { rate },
              create: {
                fromCurrency,
                toCurrency: normalizedToCurrency,
                date,
                source: YAHOO_EXCHANGE_RATE_SOURCE,
                rate,
              },
            })
          )
        })

        await Promise.all(writes)
      } catch {
        return
      }
    })
  )

  return latestRates
}

async function fetchYahooLatestExchangeRates(
  currencies: string[],
  toCurrency: string
): Promise<CzkRates> {
  const today = todayStart()
  return fetchYahooHistoricalExchangeRates(currencies, toCurrency, addDays(today, -10), today)
}

export async function ensureExchangeRatesForPeriod({
  currencies,
  toCurrency = "CZK",
  start,
  end,
}: {
  currencies: string[]
  toCurrency?: string
  start: Date
  end: Date
}) {
  const normalizedToCurrency = toCurrency.toUpperCase()
  const normalizedCurrencies = normalizeCurrencyList(currencies, normalizedToCurrency)
  if (normalizedCurrencies.length === 0) return

  await fetchYahooHistoricalExchangeRates(
    normalizedCurrencies,
    normalizedToCurrency,
    todayStart(start),
    todayStart(end)
  )
}

export async function getExchangeRates({
  toCurrency = "CZK",
  currencies = DEFAULT_FX_CURRENCIES,
  refresh = false,
}: {
  toCurrency?: string
  currencies?: string[]
  refresh?: boolean
} = {}): Promise<CzkRates> {
  const normalizedToCurrency = toCurrency.toUpperCase()
  const normalizedCurrencies = normalizeCurrencyList(currencies, normalizedToCurrency)
  const cacheKey = normalizedToCurrency === "CZK" ? "czk" : null

  if (cacheKey === "czk" && !refresh && czkRatesCache && Date.now() - czkRatesCache.ts < FX_TTL) {
    return czkRatesCache.rates
  }

  if (cacheKey === "czk" && czkRatesFetch) return czkRatesFetch

  const fetchRates = (async () => {
    if (!refresh) {
      const stored = await loadStoredExchangeRates({
        toCurrency: normalizedToCurrency,
        currencies: normalizedCurrencies,
      })
      const hasRequiredRates = normalizedCurrencies.every((currency) => stored?.[currency])
      if (stored && hasRequiredRates) {
        if (cacheKey === "czk") czkRatesCache = { rates: stored, ts: Date.now() }
        return stored
      }
    }

    const fetched = await fetchYahooLatestExchangeRates(normalizedCurrencies, normalizedToCurrency)
    const stored = await loadStoredExchangeRates({
      toCurrency: normalizedToCurrency,
      currencies: normalizedCurrencies,
    })
    const fallback = stored ?? fetched

    if (cacheKey === "czk") czkRatesCache = { rates: fallback, ts: Date.now() }
    return fallback
  })()

  if (cacheKey === "czk") {
    czkRatesFetch = fetchRates.finally(() => {
      czkRatesFetch = null
    })
    return czkRatesFetch
  }

  return fetchRates
}

export async function getCzkRates(refresh = false): Promise<CzkRates> {
  return getExchangeRates({ toCurrency: "CZK", refresh })
}

export async function getHistoricalExchangeRates({
  date,
  toCurrency = "CZK",
  currencies = DEFAULT_FX_CURRENCIES,
}: {
  date: Date
  toCurrency?: string
  currencies?: string[]
}): Promise<CzkRates> {
  const normalizedToCurrency = toCurrency.toUpperCase()
  const normalizedCurrencies = normalizeCurrencyList(currencies, normalizedToCurrency)
  const day = todayStart(date)
  let stored = await loadStoredExchangeRates({
    date: day,
    toCurrency: normalizedToCurrency,
    currencies: normalizedCurrencies,
  })
  const missing = normalizedCurrencies.filter((currency) => !stored?.[currency])

  if (missing.length > 0) {
    await fetchYahooHistoricalExchangeRates(missing, normalizedToCurrency, addDays(day, -14), day)
    stored = await loadStoredExchangeRates({
      date: day,
      toCurrency: normalizedToCurrency,
      currencies: normalizedCurrencies,
    })
  }

  return stored ?? (await getExchangeRates({ toCurrency: normalizedToCurrency, currencies }))
}

export async function getHistoricalCzkRates(
  date: Date,
  currencies = DEFAULT_FX_CURRENCIES
): Promise<CzkRates> {
  return getHistoricalExchangeRates({ date, toCurrency: "CZK", currencies })
}

export function toCzk(amount: number, currency: string, czkRates: CzkRates): number {
  return toDisplayCurrency(amount, currency, czkRates, "CZK")
}

export function toDisplayCurrency(
  amount: number,
  currency: string,
  rates: CzkRates,
  displayCurrency = "CZK"
): number {
  if (currency === displayCurrency) return amount

  const rate = rates[currency]
  if (!rate) return amount

  return amount * rate
}
