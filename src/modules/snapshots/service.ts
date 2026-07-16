import { randomUUID } from "crypto"
import { prisma, toNum } from "@/lib/prisma"
import { getAccessibleAccountIds as getMembershipAccountIds } from "@/lib/accountAccess"
import {
  ensureExchangeRatesForPeriod,
  getExchangeRates,
  getCzkRates,
  getHistoricalExchangeRates,
  getHistoricalCzkRates,
  getHistoricalPrices,
  getLivePrices,
  priceLookupKey,
  toCzk,
  toDisplayCurrency,
  type HistoricalPricePoint,
} from "@/modules/portfolio/rates/service"
import type { AssetType, Prisma, SnapshotGranularity, SnapshotSource } from "@prisma/client"

const BANK_ACCOUNT_TYPES = new Set(["bank", "cash", "savings"])
const LIABILITY_ACCOUNT_TYPES = new Set(["credit_card", "loan", "mortgage"])
const INVESTMENT_ACCOUNT_TYPES = new Set(["broker", "exchange", "crypto_wallet"])
const SNAPSHOT_FLUSH_MS = 300
const SNAPSHOT_FLUSH_COUNT = 250
const SNAPSHOT_ITEM_FLUSH_COUNT = 5000

function bucketTimestamp(date: Date, granularity: SnapshotGranularity): Date {
  const bucket = new Date(date)
  bucket.setUTCSeconds(0, 0)

  if (granularity === "hour") bucket.setUTCMinutes(0, 0, 0)
  if (granularity === "day") bucket.setUTCHours(0, 0, 0, 0)
  if (granularity === "week") {
    const day = bucket.getUTCDay() || 7
    bucket.setUTCDate(bucket.getUTCDate() - day + 1)
    bucket.setUTCHours(0, 0, 0, 0)
  }
  if (granularity === "month") {
    bucket.setUTCDate(1)
    bucket.setUTCHours(0, 0, 0, 0)
  }

  return bucket
}

function monthKey(date: Date): string {
  return date.toISOString().slice(0, 7)
}

export type PortfolioHistoryRange = "1W" | "1M" | "3M" | "6M" | "1Y" | "ALL"

type PortfolioHistoryInterval = number
type CurrencyBreakdown = Record<string, number>

interface HistoricalPosition {
  listingId: string
  symbol: string
  accountId: string
  assetId: string | null
  assetType: AssetType
  name: string | null
  quantity: number
  totalCost: number
  currency: string
}

interface SnapshotPosition {
  listingId: string
  symbol: string
  accountId: string
  assetId: string | null
  assetType: AssetType
  name: string | null
  quantity: number
  totalCost: number
  currency: string
}

interface AccountLedgerSnapshot {
  positions: Record<string, SnapshotPosition>
  cashByCurrency: CurrencyBreakdown
  netDepositsByCurrency: CurrencyBreakdown
  netDepositsValueCzk: number
  realizedPnlByCurrency: CurrencyBreakdown
  feesByCurrency: CurrencyBreakdown
  taxesByCurrency: CurrencyBreakdown
}

interface AssetTransferValuationContext {
  pricesBySymbol: Record<string, HistoricalPricePoint[]>
  date: Date
  rates: Record<string, number>
  displayCurrency: string
}

interface AssetTransferFlow {
  amount: number
  currency: string
  direction: "in" | "out"
}

interface LedgerSnapshotEvent {
  accountId: string
  type: string
  source: string | null
  description: string | null
  date: Date
  realizedPnl?: unknown
  realizedPnlCurrency?: string | null
  movements: Array<{
    kind: string
    direction: string
    quantity: unknown
    pricePerUnit: unknown
    valueAmount: unknown
    valueCurrency: string | null
    currency: string | null
    sourceSymbol: string | null
    sourceAssetType: AssetType | null
    assetId: string | null
    listingId: string | null
  }>
}

interface PortfolioHistoryPoint {
  timestamp: Date
  month: string
  label: string
  investedCzk: number
  netWorthCzk: number
  valueCzk: number
  interval: PortfolioHistoryInterval
  allocations: {
    symbol: string
    accountId: string
    valueCzk: number
    allocationPct: number
  }[]
}

function todayStart(date = new Date()): Date {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()))
}

function endOfDay(date: Date): Date {
  const end = new Date(date)
  end.setUTCHours(23, 59, 59, 999)
  return end
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date)
  next.setUTCDate(next.getUTCDate() + days)
  return next
}

function rangeStart(range: PortfolioHistoryRange, firstDate: Date | null, now = new Date()): Date {
  const start = todayStart(now)

  if (range === "1W") start.setUTCDate(start.getUTCDate() - 7)
  if (range === "1M") start.setUTCMonth(start.getUTCMonth() - 1)
  if (range === "3M") start.setUTCMonth(start.getUTCMonth() - 3)
  if (range === "6M") start.setUTCMonth(start.getUTCMonth() - 6)
  if (range === "1Y") start.setUTCFullYear(start.getUTCFullYear() - 1)

  if (range === "ALL") return firstDate ? todayStart(firstDate) : start
  return start
}

function daysBetween(start: Date, end: Date): number {
  const startDay = todayStart(start).getTime()
  const endDay = todayStart(end).getTime()
  return Math.max(1, Math.ceil((endDay - startDay) / 86_400_000))
}

function intervalDaysForPeriod(start: Date, end: Date): number {
  return Math.max(1, Math.ceil(daysBetween(start, end) * 0.01))
}

function bucketDates(start: Date, end: Date, intervalDays: number): Date[] {
  const buckets: Date[] = []
  let cursor = endOfDay(start)
  const endBucket = endOfDay(end)

  while (cursor <= endBucket) {
    buckets.push(new Date(cursor))
    cursor = endOfDay(addDays(cursor, intervalDays))
  }

  if (buckets.length === 0 || buckets[buckets.length - 1] < endBucket) {
    buckets.push(endBucket)
  }

  return buckets
}

function historyBucketKey(date: Date, start: Date, intervalDays: number): string {
  const bucketIndex = Math.floor(daysBetween(start, date) / intervalDays)
  const bucket = todayStart(addDays(start, bucketIndex * intervalDays))
  return bucket.toISOString()
}

function pointLabel(date: Date, intervalDays: number): string {
  if (intervalDays >= 28) {
    return date.toLocaleDateString("cs-CZ", { month: "short", year: "numeric" })
  }

  return date.toLocaleDateString("cs-CZ", { day: "numeric", month: "short" })
}

function findCloseAtOrBefore(
  prices: HistoricalPricePoint[],
  date: Date
): HistoricalPricePoint | null {
  let result: HistoricalPricePoint | null = null
  for (const price of prices) {
    if (price.date <= date) result = price
    else break
  }
  return result
}

function listingPositionKey(accountId: string, listingId: string) {
  return `${accountId}:${listingId}`
}

function normalizeCurrency(currency: string | null | undefined, fallback = "CZK") {
  return (currency || fallback).toUpperCase()
}

function addCurrencyAmount(
  breakdown: CurrencyBreakdown,
  currency: string | null | undefined,
  amount: number
) {
  const key = normalizeCurrency(currency)
  if (!Number.isFinite(amount) || amount === 0) return
  breakdown[key] = (breakdown[key] ?? 0) + amount
}

function mergeCurrencyBreakdowns(...breakdowns: CurrencyBreakdown[]) {
  const merged: CurrencyBreakdown = {}
  for (const breakdown of breakdowns) {
    for (const [currency, amount] of Object.entries(breakdown)) {
      addCurrencyAmount(merged, currency, amount)
    }
  }
  return merged
}

function subtractCurrencyBreakdowns(
  left: CurrencyBreakdown,
  right: CurrencyBreakdown
): CurrencyBreakdown {
  const result: CurrencyBreakdown = { ...left }
  for (const [currency, amount] of Object.entries(right)) {
    addCurrencyAmount(result, currency, -amount)
  }
  return result
}

function currencyBreakdownCurrencies(...breakdowns: CurrencyBreakdown[]) {
  return [...new Set(breakdowns.flatMap((breakdown) => Object.keys(breakdown)))]
}

function roundCurrencyBreakdown(breakdown: CurrencyBreakdown): CurrencyBreakdown {
  return Object.fromEntries(
    Object.entries(breakdown)
      .filter(([, amount]) => Math.abs(amount) > 0.000001)
      .map(([currency, amount]) => [currency, Number(amount.toFixed(6))])
  )
}

function jsonCurrencyBreakdown(value: unknown): CurrencyBreakdown {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {}

  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .map(([currency, amount]) => [currency, Number(amount)])
      .filter(([, amount]) => Number.isFinite(amount))
  )
}

function convertCurrencyBreakdown(
  breakdown: CurrencyBreakdown,
  rates: Record<string, number>,
  displayCurrency = "CZK"
) {
  return Object.entries(breakdown).reduce(
    (sum, [currency, amount]) =>
      sum + toDisplayCurrency(amount, currency || displayCurrency, rates, displayCurrency),
    0
  )
}

function convertCurrencyAmount(
  amount: number,
  fromCurrency: string,
  toCurrency: string,
  rates: Record<string, number>
) {
  const from = normalizeCurrency(fromCurrency)
  const to = normalizeCurrency(toCurrency)
  if (from === to) return amount

  return toDisplayCurrency(amount, from, rates, to)
}

function eventDisplayValue(
  amount: number,
  currency: string,
  valuation?: Pick<AssetTransferValuationContext, "rates" | "displayCurrency">
) {
  if (!Number.isFinite(amount) || amount === 0) return 0
  return valuation
    ? toDisplayCurrency(amount, currency, valuation.rates, valuation.displayCurrency)
    : amount
}

function snapshotExchangeRates(
  rates: Record<string, number>,
  currencies: string[],
  displayCurrency = "CZK"
) {
  const uniqueCurrencies = new Set(currencies.map((currency) => normalizeCurrency(currency)))
  uniqueCurrencies.delete(displayCurrency)

  return Object.fromEntries(
    [...uniqueCurrencies]
      .map((currency) => [currency, rates[currency]])
      .filter(([, rate]) => Number.isFinite(rate))
  )
}

function emptyLedgerSnapshot(): AccountLedgerSnapshot {
  return {
    positions: {},
    cashByCurrency: {},
    netDepositsByCurrency: {},
    netDepositsValueCzk: 0,
    realizedPnlByCurrency: {},
    feesByCurrency: {},
    taxesByCurrency: {},
  }
}

function cloneLedgerSnapshot(snapshot: AccountLedgerSnapshot): AccountLedgerSnapshot {
  return {
    positions: Object.fromEntries(
      Object.entries(snapshot.positions).map(([key, position]) => [key, { ...position }])
    ),
    cashByCurrency: { ...snapshot.cashByCurrency },
    netDepositsByCurrency: { ...snapshot.netDepositsByCurrency },
    netDepositsValueCzk: snapshot.netDepositsValueCzk,
    realizedPnlByCurrency: { ...snapshot.realizedPnlByCurrency },
    feesByCurrency: { ...snapshot.feesByCurrency },
    taxesByCurrency: { ...snapshot.taxesByCurrency },
  }
}

function snapshotBreakdownOrDisplayValue(
  breakdownValue: unknown,
  displayValue: unknown,
  displayCurrency = "CZK"
): CurrencyBreakdown {
  const breakdown = jsonCurrencyBreakdown(breakdownValue)
  if (Object.keys(breakdown).length > 0) return breakdown

  const amount = toNum(displayValue as never)
  return Math.abs(amount) > 0.000001 ? { [displayCurrency]: amount } : {}
}

function snapshotNeedsLedgerRebuild(snapshot: {
  cashValue: unknown
  cashValueByCurrency: unknown
  netDepositsValue: unknown
  netDepositsByCurrency: unknown
  realizedPnlValue: unknown
  realizedPnlByCurrency: unknown
  feesValue: unknown
  feesByCurrency: unknown
  taxesValue: unknown
  taxesByCurrency: unknown
  items: Array<{
    nativeCostBasis: unknown
    nativeCostCurrency: string | null
  }>
}) {
  const hasLegacyPositions = snapshot.items.some(
    (item) => item.nativeCostBasis == null || !item.nativeCostCurrency
  )
  const missingNonZeroBreakdown = [
    [snapshot.cashValueByCurrency, snapshot.cashValue],
    [snapshot.netDepositsByCurrency, snapshot.netDepositsValue],
    [snapshot.realizedPnlByCurrency, snapshot.realizedPnlValue],
    [snapshot.feesByCurrency, snapshot.feesValue],
    [snapshot.taxesByCurrency, snapshot.taxesValue],
  ].some(([breakdown, value]) => {
    if (breakdown) return false
    return Math.abs(toNum(value as never)) > 0.000001
  })

  return hasLegacyPositions || missingNonZeroBreakdown
}

function restoreLedgerSnapshotFromAccountSnapshot(snapshot: {
  accountId: string
  cashValue: unknown
  cashValueByCurrency: unknown
  netDepositsValue: unknown
  netDepositsByCurrency: unknown
  realizedPnlValue: unknown
  realizedPnlByCurrency: unknown
  feesValue: unknown
  feesByCurrency: unknown
  taxesValue: unknown
  taxesByCurrency: unknown
  items: Array<{
    assetId: string | null
    listingId: string
    symbol: string
    quantity: unknown
    costBasis: unknown
    costCurrency: string | null
    nativeCostBasis: unknown
    nativeCostCurrency: string | null
    asset: { name: string | null; assetType: AssetType; currency: string } | null
  }>
}): AccountLedgerSnapshot {
  const ledgerSnapshot: AccountLedgerSnapshot = {
    positions: {},
    cashByCurrency: snapshotBreakdownOrDisplayValue(
      snapshot.cashValueByCurrency,
      snapshot.cashValue
    ),
    netDepositsByCurrency: snapshotBreakdownOrDisplayValue(
      snapshot.netDepositsByCurrency,
      snapshot.netDepositsValue
    ),
    netDepositsValueCzk: toNum(snapshot.netDepositsValue as never),
    realizedPnlByCurrency: snapshotBreakdownOrDisplayValue(
      snapshot.realizedPnlByCurrency,
      snapshot.realizedPnlValue
    ),
    feesByCurrency: snapshotBreakdownOrDisplayValue(snapshot.feesByCurrency, snapshot.feesValue),
    taxesByCurrency: snapshotBreakdownOrDisplayValue(snapshot.taxesByCurrency, snapshot.taxesValue),
  }

  for (const item of snapshot.items) {
    const quantity = toNum(item.quantity as never)
    if (quantity <= 0.000001) continue

    const currency = normalizeCurrency(
      item.nativeCostCurrency ?? item.costCurrency ?? item.asset?.currency,
      "CZK"
    )
    const totalCost =
      item.nativeCostBasis != null
        ? toNum(item.nativeCostBasis as never)
        : toNum(item.costBasis as never)

    ledgerSnapshot.positions[listingPositionKey(snapshot.accountId, item.listingId)] = {
      listingId: item.listingId,
      symbol: item.symbol,
      accountId: snapshot.accountId,
      assetId: item.assetId,
      assetType: item.asset?.assetType ?? "stock",
      name: item.asset?.name ?? null,
      quantity,
      totalCost,
      currency,
    }
  }

  return ledgerSnapshot
}

async function getImportSnapshotSeed(accountId: string, start: Date, displayCurrency = "CZK") {
  const previousSnapshot = await prisma.accountSnapshot.findFirst({
    where: {
      accountId,
      currency: displayCurrency,
      granularity: "day",
      timestamp: { lt: start },
    },
    include: {
      items: {
        include: {
          asset: {
            select: { name: true, assetType: true, currency: true },
          },
        },
      },
    },
    orderBy: { timestamp: "desc" },
  })

  if (!previousSnapshot) {
    return {
      ledgerSnapshot: emptyLedgerSnapshot(),
      eventCursor: null as Date | null,
      seedSource: "empty" as const,
    }
  }

  const eventCursor = endOfDay(previousSnapshot.timestamp)
  const needsRebuild = snapshotNeedsLedgerRebuild(previousSnapshot)
  const ledgerSnapshot = needsRebuild
    ? await calculateAccountLedgerSnapshot(accountId, eventCursor, displayCurrency)
    : restoreLedgerSnapshotFromAccountSnapshot(previousSnapshot)

  return {
    ledgerSnapshot,
    eventCursor,
    seedSource: needsRebuild ? ("rebuild" as const) : ("snapshot" as const),
  }
}

async function getCachedHistoricalCzkRates(
  cache: Map<string, Record<string, number>>,
  date: Date,
  currencies: string[] = [],
  displayCurrency = "CZK"
) {
  const key = `${displayCurrency}:${todayStart(date).toISOString()}:${currencies.sort().join(",")}`
  const cached = cache.get(key)
  if (cached) return cached

  const rates = await getHistoricalExchangeRates({
    date,
    toCurrency: displayCurrency,
    currencies,
  })
  cache.set(key, rates)
  return rates
}

function applyInvestmentEventToSnapshotPositions(
  positions: Record<string, SnapshotPosition>,
  event: LedgerSnapshotEvent,
  valuation?: AssetTransferValuationContext
): AssetTransferFlow | null {
  const asset = event.movements.find(
    (movement) => movement.kind === "asset" && movement.sourceSymbol
  )
  if (!asset?.sourceSymbol || !asset.listingId) return null

  const key = listingPositionKey(event.accountId, asset.listingId)
  positions[key] ||= {
    listingId: asset.listingId,
    symbol: asset.sourceSymbol,
    accountId: event.accountId,
    assetId: asset.assetId,
    assetType: asset.sourceAssetType ?? "stock",
    name: event.description,
    quantity: 0,
    totalCost: 0,
    currency: normalizeCurrency(asset.valueCurrency ?? asset.currency, "EUR"),
  }

  const position = positions[key]
  const quantity = toNum(asset.quantity as never)
  const price = toNum(asset.pricePerUnit as never)
  const valueAmount = toNum(asset.valueAmount as never)
  const explicitCost = price > 0 ? quantity * price : valueAmount
  const transferFlow =
    event.type === "asset_transfer" ? assetTransferFlow(asset, position, quantity, valuation) : null
  const cost = explicitCost > 0 ? explicitCost : (transferFlow?.amount ?? 0)

  if (asset.direction === "in") {
    const costCurrency = normalizeCurrency(asset.valueCurrency ?? transferFlow?.currency, "")
    if (costCurrency && cost > 0 && position.totalCost === 0) {
      position.currency = costCurrency
    }
    position.quantity += quantity
    if (cost > 0) {
      position.totalCost += convertCurrencyAmount(
        cost,
        costCurrency || position.currency,
        position.currency,
        valuation?.rates ?? {}
      )
    }
    return transferFlow
  }

  const avgCost = position.quantity > 0 ? position.totalCost / position.quantity : 0
  position.totalCost -= avgCost * quantity
  position.quantity -= quantity
  return transferFlow
}

function assetTransferFlow(
  asset: LedgerSnapshotEvent["movements"][number],
  position: SnapshotPosition,
  quantity: number,
  valuation?: AssetTransferValuationContext
): AssetTransferFlow | null {
  if (quantity <= 0) return null

  const explicitValue = toNum(asset.valueAmount as never)
  if (explicitValue > 0 && asset.valueCurrency) {
    return {
      amount: explicitValue,
      currency: normalizeCurrency(asset.valueCurrency),
      direction: asset.direction === "in" ? "in" : "out",
    }
  }

  if (!valuation || !asset.sourceSymbol) return null

  const priceKey = priceLookupKey({
    symbol: asset.sourceSymbol,
    assetType: asset.sourceAssetType ?? position.assetType,
    currency: position.currency,
    listingId: asset.listingId,
  })
  const close = findCloseAtOrBefore(
    valuation.pricesBySymbol[priceKey] ?? valuation.pricesBySymbol[asset.sourceSymbol] ?? [],
    valuation.date
  )

  if (close && close.price > 0) {
    return {
      amount: close.price * quantity,
      currency: normalizeCurrency(close.currency),
      direction: asset.direction === "in" ? "in" : "out",
    }
  }

  const avgCost = position.quantity > 0 ? position.totalCost / position.quantity : 0
  if (avgCost <= 0) return null

  return {
    amount: avgCost * quantity,
    currency: position.currency,
    direction: asset.direction === "in" ? "in" : "out",
  }
}

function applyInvestmentEventToLedgerSnapshot(
  snapshot: AccountLedgerSnapshot,
  event: LedgerSnapshotEvent,
  valuation?: AssetTransferValuationContext
) {
  const assetTransferFlow = applyInvestmentEventToSnapshotPositions(
    snapshot.positions,
    event,
    valuation
  )
  if (assetTransferFlow) {
    const signedAmount =
      assetTransferFlow.direction === "in" ? assetTransferFlow.amount : -assetTransferFlow.amount
    addCurrencyAmount(snapshot.netDepositsByCurrency, assetTransferFlow.currency, signedAmount)
    snapshot.netDepositsValueCzk += eventDisplayValue(
      signedAmount,
      assetTransferFlow.currency,
      valuation
    )
  }

  if (event.realizedPnl != null) {
    addCurrencyAmount(
      snapshot.realizedPnlByCurrency,
      event.realizedPnlCurrency ?? "EUR",
      toNum(event.realizedPnl as never)
    )
  }

  for (const movement of event.movements) {
    if (!["cash", "fee", "tax"].includes(movement.kind)) continue

    const amount = toNum((movement.valueAmount ?? movement.quantity) as never)
    const currency = movement.valueCurrency ?? movement.currency ?? "CZK"
    const signedAmount = movement.direction === "in" ? amount : -amount
    addCurrencyAmount(snapshot.cashByCurrency, currency, signedAmount)

    if (
      event.type &&
      ["cash_deposit", "cash_withdrawal"].includes(event.type) &&
      !isTrading212FreeShareCashDeposit(event)
    ) {
      addCurrencyAmount(snapshot.netDepositsByCurrency, currency, signedAmount)
      snapshot.netDepositsValueCzk += eventDisplayValue(signedAmount, currency, valuation)
    }

    if (movement.kind === "fee") {
      addCurrencyAmount(
        snapshot.feesByCurrency,
        currency,
        movement.direction === "out" ? amount : -amount
      )
    }

    if (movement.kind === "tax") {
      addCurrencyAmount(
        snapshot.taxesByCurrency,
        currency,
        movement.direction === "out" ? amount : -amount
      )
    }
  }
}

function normalizedMarkerText(value: string | null | undefined) {
  return (value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
}

function isTrading212FreeShareCashDeposit(event: {
  source?: string | null
  type?: string | null
  description?: string | null
}) {
  if (event.source !== "trading212" || event.type !== "cash_deposit") return false

  const text = normalizedMarkerText(event.description)
  return (
    text.includes("free share") ||
    text.includes("free shares") ||
    text.includes("free stock") ||
    text.includes("free stocks") ||
    text.includes("bonus share") ||
    text.includes("bonus shares") ||
    text.includes("bonus stock") ||
    text.includes("bonus stocks") ||
    text.includes("referral share") ||
    text.includes("referral shares") ||
    text.includes("promo share") ||
    text.includes("promo shares") ||
    text.includes("promotion share") ||
    text.includes("promotion shares") ||
    text.includes("akcie zdarma")
  )
}

async function getSnapshotAccountIds(userId: string) {
  const accessibleIds = await getMembershipAccountIds(userId, "viewer")
  const accounts = await prisma.account.findMany({
    where: { id: { in: accessibleIds } },
    select: { id: true, type: true },
  })

  return {
    all: accounts.map((account) => account.id),
    cash: accounts
      .filter((account) => BANK_ACCOUNT_TYPES.has(account.type))
      .map((account) => account.id),
    liabilities: accounts
      .filter((account) => LIABILITY_ACCOUNT_TYPES.has(account.type))
      .map((account) => account.id),
    investments: accounts
      .filter((account) => INVESTMENT_ACCOUNT_TYPES.has(account.type))
      .map((account) => account.id),
  }
}

async function calculateAccountValueBreakdown(accountIds: string[]): Promise<CurrencyBreakdown> {
  if (accountIds.length === 0) return {}

  const txs = await prisma.transaction.findMany({
    where: { accountId: { in: accountIds }, type: { in: ["income", "expense"] } },
    select: {
      type: true,
      amount: true,
      reportingAmount: true,
      reportingCurrency: true,
      currency: true,
    },
  })

  const breakdown: CurrencyBreakdown = {}
  for (const tx of txs) {
    addCurrencyAmount(
      breakdown,
      tx.currency,
      tx.type === "income" ? toNum(tx.amount) : -toNum(tx.amount)
    )
  }

  return breakdown
}

function applyInvestmentEvent(
  positions: Record<string, HistoricalPosition>,
  event: {
    accountId: string
    movements: Array<{
      kind: string
      direction: string
      quantity: unknown
      pricePerUnit: unknown
      valueAmount: unknown
      valueCurrency: string | null
      assetId: string | null
      listingId: string | null
      sourceSymbol: string | null
      sourceAssetType: AssetType | null
    }>
    description: string | null
  }
) {
  const asset = event.movements.find(
    (movement) => movement.kind === "asset" && movement.sourceSymbol
  )
  if (!asset?.sourceSymbol || !asset.listingId) return

  const key = listingPositionKey(event.accountId, asset.listingId)
  positions[key] ||= {
    listingId: asset.listingId,
    symbol: asset.sourceSymbol,
    accountId: event.accountId,
    assetId: asset.assetId,
    assetType: asset.sourceAssetType ?? "stock",
    name: event.description,
    quantity: 0,
    totalCost: 0,
    currency: asset.valueCurrency ?? asset.sourceSymbol,
  }

  const position = positions[key]
  const quantity = toNum(asset.quantity as never)
  const price = toNum(asset.pricePerUnit as never)
  const valueAmount = toNum(asset.valueAmount as never)
  const cost = price > 0 ? quantity * price : valueAmount

  if (asset.direction === "in") {
    const costCurrency = asset.valueCurrency ? normalizeCurrency(asset.valueCurrency) : null
    if (costCurrency && cost > 0 && position.totalCost === 0) {
      position.currency = costCurrency
    }
    position.quantity += quantity
    if (cost > 0) position.totalCost += cost
    return
  }

  const avgCost = position.quantity > 0 ? position.totalCost / position.quantity : 0
  position.totalCost -= avgCost * quantity
  position.quantity -= quantity
}

export async function createPortfolioSnapshot({
  userId,
  source,
  granularity = "minute",
  timestamp = new Date(),
}: {
  userId: string
  source: SnapshotSource
  granularity?: SnapshotGranularity
  timestamp?: Date
}) {
  const bucket = bucketTimestamp(timestamp, granularity)
  const accessibleIds = await getMembershipAccountIds(userId, "viewer")
  const accounts = await prisma.account.findMany({
    where: {
      id: { in: accessibleIds },
      type: { in: Array.from(INVESTMENT_ACCOUNT_TYPES) as never },
    },
    include: { holdings: true },
  })

  const ledgerByAccount = new Map<string, AccountLedgerSnapshot>()
  for (const account of accounts) {
    const ledgerSnapshot = await calculateAccountLedgerSnapshotFromLatestSnapshot(
      account.id,
      timestamp,
      normalizeCurrency(account.currency)
    )
    ledgerByAccount.set(account.id, ledgerSnapshot)
  }

  const positions = [...ledgerByAccount.values()].flatMap((ledger) =>
    Object.values(ledger.positions).filter((position) => position.quantity > 0.000001)
  )
  const prices =
    positions.length > 0
      ? await getLivePrices(
          positions.map((position) => ({
            symbol: position.symbol,
            assetType: position.assetType,
            currency: position.currency,
            listingId: position.listingId,
          }))
        )
      : {}

  const items = positions
    .map((position) => {
      const price =
        prices[
          priceLookupKey({
            symbol: position.symbol,
            assetType: position.assetType,
            currency: position.currency,
            listingId: position.listingId,
          })
        ] ?? prices[position.symbol]
      const quantity = position.quantity
      const avgBuyPrice = quantity > 0 ? position.totalCost / quantity : 0
      const pricePerUnit = price?.price ?? avgBuyPrice
      const priceCurrency = price?.currency ?? position.currency
      const nativeValue = pricePerUnit * quantity
      const nativeCostBasis = position.totalCost

      return {
        assetId: position.assetId,
        listingId: position.listingId,
        symbol: position.symbol,
        accountId: position.accountId,
        quantity,
        pricePerUnit,
        priceCurrency,
        nativeValue,
        valueCurrency: priceCurrency,
        nativeCostBasis,
        nativeCostCurrency: position.currency,
      }
    })
    .filter((item) => item.quantity > 0 && item.nativeValue > 0)

  const totalValueByCurrency: CurrencyBreakdown = {}
  for (const item of items) {
    addCurrencyAmount(totalValueByCurrency, item.valueCurrency, item.nativeValue)
  }
  for (const ledger of ledgerByAccount.values()) {
    for (const [currency, amount] of Object.entries(ledger.cashByCurrency)) {
      addCurrencyAmount(totalValueByCurrency, currency, amount)
    }
  }
  const totalValueRates = await getCzkRates()
  const totalValue = convertCurrencyBreakdown(totalValueByCurrency, totalValueRates, "CZK")

  const ratesByCurrency = new Map<string, Record<string, number>>()
  for (const account of accounts) {
    const accountCurrency = normalizeCurrency(account.currency)
    const ledger = ledgerByAccount.get(account.id) ?? emptyLedgerSnapshot()
    const accountItems = items.filter((item) => item.accountId === account.id)
    const currencies = [
      ...accountItems.flatMap((item) => [item.valueCurrency, item.nativeCostCurrency]),
      ...currencyBreakdownCurrencies(
        ledger.cashByCurrency,
        ledger.netDepositsByCurrency,
        ledger.realizedPnlByCurrency,
        ledger.feesByCurrency,
        ledger.taxesByCurrency
      ),
    ]
    ratesByCurrency.set(
      account.id,
      await getExchangeRates({ toCurrency: accountCurrency, currencies })
    )
  }

  await prisma.$transaction(async (tx) => {
    for (const account of accounts) {
      const displayCurrency = normalizeCurrency(account.currency)
      const accountRates = ratesByCurrency.get(account.id) ?? {}
      const accountItems = items
        .filter((item) => item.accountId === account.id)
        .map((item) => ({
          ...item,
          value: toDisplayCurrency(
            item.nativeValue,
            item.valueCurrency,
            accountRates,
            displayCurrency
          ),
          costBasis: toDisplayCurrency(
            item.nativeCostBasis,
            item.nativeCostCurrency,
            accountRates,
            displayCurrency
          ),
          costCurrency: displayCurrency,
        }))
      const ledger = ledgerByAccount.get(account.id) ?? emptyLedgerSnapshot()
      const investmentValueByCurrency: CurrencyBreakdown = {}
      const investmentCostBasisByCurrency: CurrencyBreakdown = {}
      for (const item of accountItems) {
        addCurrencyAmount(investmentValueByCurrency, item.valueCurrency, item.nativeValue)
        addCurrencyAmount(
          investmentCostBasisByCurrency,
          item.nativeCostCurrency,
          item.nativeCostBasis
        )
      }
      const unrealizedPnlByCurrency = subtractCurrencyBreakdowns(
        investmentValueByCurrency,
        investmentCostBasisByCurrency
      )
      const accountValue = convertCurrencyBreakdown(
        investmentValueByCurrency,
        accountRates,
        displayCurrency
      )
      const accountCostBasis = convertCurrencyBreakdown(
        investmentCostBasisByCurrency,
        accountRates,
        displayCurrency
      )
      const accountCashValue = convertCurrencyBreakdown(
        ledger.cashByCurrency,
        accountRates,
        displayCurrency
      )
      const accountTotalValue = accountCashValue + accountValue
      const netDepositsValue = ledger.netDepositsValueCzk
      const realizedPnlValue = convertCurrencyBreakdown(
        ledger.realizedPnlByCurrency,
        accountRates,
        displayCurrency
      )
      const unrealizedPnlValue = accountValue - accountCostBasis
      const feesValue = convertCurrencyBreakdown(
        ledger.feesByCurrency,
        accountRates,
        displayCurrency
      )
      const taxesValue = convertCurrencyBreakdown(
        ledger.taxesByCurrency,
        accountRates,
        displayCurrency
      )
      const ratesForSnapshot = snapshotExchangeRates(
        accountRates,
        currencyBreakdownCurrencies(
          ledger.cashByCurrency,
          investmentValueByCurrency,
          investmentCostBasisByCurrency,
          ledger.netDepositsByCurrency,
          ledger.realizedPnlByCurrency,
          unrealizedPnlByCurrency,
          ledger.feesByCurrency,
          ledger.taxesByCurrency
        ),
        displayCurrency
      )
      const snapshot = await tx.accountSnapshot.upsert({
        where: {
          accountId_timestamp_currency_granularity: {
            accountId: account.id,
            timestamp: bucket,
            currency: displayCurrency,
            granularity,
          },
        },
        update: {
          source,
          cashValue: accountCashValue,
          investmentValue: accountValue,
          investmentCostBasis: accountCostBasis,
          netDepositsValue,
          realizedPnlValue,
          unrealizedPnlValue,
          feesValue,
          taxesValue,
          totalValue: accountTotalValue,
          cashValueByCurrency: roundCurrencyBreakdown(ledger.cashByCurrency),
          investmentValueByCurrency: roundCurrencyBreakdown(investmentValueByCurrency),
          investmentCostBasisByCurrency: roundCurrencyBreakdown(investmentCostBasisByCurrency),
          netDepositsByCurrency: roundCurrencyBreakdown(ledger.netDepositsByCurrency),
          realizedPnlByCurrency: roundCurrencyBreakdown(ledger.realizedPnlByCurrency),
          unrealizedPnlByCurrency: roundCurrencyBreakdown(unrealizedPnlByCurrency),
          feesByCurrency: roundCurrencyBreakdown(ledger.feesByCurrency),
          taxesByCurrency: roundCurrencyBreakdown(ledger.taxesByCurrency),
          exchangeRates: ratesForSnapshot,
          isRecalculated: source === "manual_recalculation",
        },
        create: {
          accountId: account.id,
          timestamp: bucket,
          granularity,
          source,
          currency: displayCurrency,
          cashValue: accountCashValue,
          investmentValue: accountValue,
          investmentCostBasis: accountCostBasis,
          netDepositsValue,
          realizedPnlValue,
          unrealizedPnlValue,
          feesValue,
          taxesValue,
          liabilitiesValue: 0,
          totalValue: accountTotalValue,
          cashValueByCurrency: roundCurrencyBreakdown(ledger.cashByCurrency),
          investmentValueByCurrency: roundCurrencyBreakdown(investmentValueByCurrency),
          investmentCostBasisByCurrency: roundCurrencyBreakdown(investmentCostBasisByCurrency),
          netDepositsByCurrency: roundCurrencyBreakdown(ledger.netDepositsByCurrency),
          realizedPnlByCurrency: roundCurrencyBreakdown(ledger.realizedPnlByCurrency),
          unrealizedPnlByCurrency: roundCurrencyBreakdown(unrealizedPnlByCurrency),
          feesByCurrency: roundCurrencyBreakdown(ledger.feesByCurrency),
          taxesByCurrency: roundCurrencyBreakdown(ledger.taxesByCurrency),
          exchangeRates: ratesForSnapshot,
          isRecalculated: source === "manual_recalculation",
        },
      })

      await tx.accountSnapshotItem.deleteMany({ where: { snapshotId: snapshot.id } })

      if (accountItems.length > 0) {
        await tx.accountSnapshotItem.createMany({
          data: accountItems.map((item) => ({
            snapshotId: snapshot.id,
            assetId: item.assetId,
            listingId: item.listingId,
            symbol: item.symbol,
            quantity: item.quantity,
            pricePerUnit: item.pricePerUnit,
            priceCurrency: item.priceCurrency,
            value: item.value,
            nativeValue: item.nativeValue,
            valueCurrency: item.valueCurrency,
            costBasis: item.costBasis,
            costCurrency: item.costCurrency,
            nativeCostBasis: item.nativeCostBasis,
            nativeCostCurrency: item.nativeCostCurrency,
            allocationPct: accountValue > 0 ? (item.value / accountValue) * 100 : 0,
          })),
        })
      }
    }
  })

  return { totalValue, totalValueByCurrency: roundCurrencyBreakdown(totalValueByCurrency) }
}

export async function createNetWorthSnapshot({
  userId,
  timestamp = new Date(),
}: {
  userId: string
  timestamp?: Date
}) {
  const bucket = bucketTimestamp(timestamp, "day")
  const displayCurrency = "CZK"
  const czkRates = await getCzkRates()
  const accountIds = await getSnapshotAccountIds(userId)
  const [cashValueByCurrency, liabilitiesValueByCurrency, portfolioSnapshot] = await Promise.all([
    calculateAccountValueBreakdown(accountIds.cash),
    calculateAccountValueBreakdown(accountIds.liabilities),
    createPortfolioSnapshot({ userId, source: "scheduled", granularity: "day", timestamp }),
  ])

  const portfolioValueByCurrency = portfolioSnapshot.totalValueByCurrency
  const totalNetWorthByCurrency = subtractCurrencyBreakdowns(
    mergeCurrencyBreakdowns(cashValueByCurrency, portfolioValueByCurrency),
    liabilitiesValueByCurrency
  )
  const cashValue = convertCurrencyBreakdown(cashValueByCurrency, czkRates, displayCurrency)
  const portfolioValue = convertCurrencyBreakdown(
    portfolioValueByCurrency,
    czkRates,
    displayCurrency
  )
  const liabilitiesValue = convertCurrencyBreakdown(
    liabilitiesValueByCurrency,
    czkRates,
    displayCurrency
  )
  const totalNetWorth = cashValue + portfolioValue - liabilitiesValue
  const ratesForSnapshot = snapshotExchangeRates(
    czkRates,
    currencyBreakdownCurrencies(
      cashValueByCurrency,
      portfolioValueByCurrency,
      liabilitiesValueByCurrency,
      totalNetWorthByCurrency
    ),
    displayCurrency
  )

  return prisma.netWorthSnapshot.upsert({
    where: {
      userId_timestamp_currency_granularity: {
        userId,
        timestamp: bucket,
        currency: displayCurrency,
        granularity: "day",
      },
    },
    update: {
      source: "scheduled",
      cashValue,
      portfolioValue,
      liabilitiesValue,
      totalNetWorth,
      cashValueByCurrency: roundCurrencyBreakdown(cashValueByCurrency),
      portfolioValueByCurrency: roundCurrencyBreakdown(portfolioValueByCurrency),
      liabilitiesValueByCurrency: roundCurrencyBreakdown(liabilitiesValueByCurrency),
      totalNetWorthByCurrency: roundCurrencyBreakdown(totalNetWorthByCurrency),
      exchangeRates: ratesForSnapshot,
    },
    create: {
      userId,
      timestamp: bucket,
      granularity: "day",
      source: "scheduled",
      currency: displayCurrency,
      cashValue,
      portfolioValue,
      liabilitiesValue,
      totalNetWorth,
      cashValueByCurrency: roundCurrencyBreakdown(cashValueByCurrency),
      portfolioValueByCurrency: roundCurrencyBreakdown(portfolioValueByCurrency),
      liabilitiesValueByCurrency: roundCurrencyBreakdown(liabilitiesValueByCurrency),
      totalNetWorthByCurrency: roundCurrencyBreakdown(totalNetWorthByCurrency),
      exchangeRates: ratesForSnapshot,
    },
  })
}

export async function getBackfilledPortfolioHistory({
  userId,
  accountId,
  range = "1Y",
}: {
  userId: string
  accountId?: string | null
  range?: PortfolioHistoryRange
}): Promise<PortfolioHistoryPoint[]> {
  const accessibleIds = await getMembershipAccountIds(userId, "viewer")
  const accounts = await prisma.account.findMany({
    where: {
      id: { in: accessibleIds },
      type: { in: Array.from(INVESTMENT_ACCOUNT_TYPES) as never },
      ...(accountId ? { id: accountId } : {}),
    },
    select: { id: true },
  })
  const accountIds = accounts.map((account) => account.id)
  if (accountIds.length === 0) return []

  const firstTx = await prisma.investmentEvent.findFirst({
    where: {
      accountId: { in: accountIds },
      deletedAt: null,
      archivedAt: null,
      movements: { some: { kind: "asset", sourceSymbol: { not: null } } },
    },
    orderBy: { date: "asc" },
    select: { date: true },
  })

  if (!firstTx) return []

  const now = new Date()
  const start = rangeStart(range, firstTx.date, now)
  const intervalDays = intervalDaysForPeriod(start, now)
  const buckets = bucketDates(start, now, intervalDays)
  const earliestBucket = buckets[0] ?? endOfDay(start)
  const latestBucket = buckets[buckets.length - 1] ?? endOfDay(now)

  const txs = await prisma.investmentEvent.findMany({
    where: {
      accountId: { in: accountIds },
      deletedAt: null,
      archivedAt: null,
      movements: { some: { kind: "asset", sourceSymbol: { not: null } } },
      date: { lte: latestBucket },
    },
    orderBy: { date: "asc" },
    select: {
      accountId: true,
      description: true,
      date: true,
      movements: true,
    },
  })

  const symbolDefinitions = txs.flatMap((tx) =>
    tx.movements
      .filter((movement) => movement.kind === "asset" && movement.sourceSymbol)
      .map((movement) => ({
        symbol: movement.sourceSymbol!,
        assetType: movement.sourceAssetType ?? "stock",
        currency: movement.valueCurrency ?? movement.currency,
        listingId: movement.listingId,
      }))
  )

  const pricesBySymbol = await getHistoricalPrices(symbolDefinitions, earliestBucket, latestBucket)

  const positions: Record<string, HistoricalPosition> = {}
  const points: PortfolioHistoryPoint[] = []
  let txIndex = 0

  for (const bucket of buckets) {
    while (txIndex < txs.length && txs[txIndex].date <= bucket) {
      applyInvestmentEvent(positions, txs[txIndex])
      txIndex += 1
    }

    const czkRates = await getHistoricalCzkRates(bucket)
    const items = Object.values(positions)
      .filter((position) => position.quantity > 0.000001)
      .map((position) => {
        const priceKey = priceLookupKey({
          symbol: position.symbol,
          assetType: position.assetType,
          currency: position.currency,
          listingId: position.listingId,
        })
        const close = findCloseAtOrBefore(
          pricesBySymbol[priceKey] ?? pricesBySymbol[position.symbol] ?? [],
          bucket
        )
        const avgPrice = position.quantity > 0 ? position.totalCost / position.quantity : 0
        const pricePerUnit = close?.price ?? avgPrice
        const priceCurrency = close?.currency ?? position.currency
        const valueCzk = toCzk(pricePerUnit * position.quantity, priceCurrency, czkRates)
        const costCzk = toCzk(position.totalCost, position.currency, czkRates)

        return {
          assetId: position.assetId,
          listingId: position.listingId,
          symbol: position.symbol,
          accountId: position.accountId,
          quantity: position.quantity,
          pricePerUnit,
          valueCzk,
          costCzk,
        }
      })
      .filter((item) => item.quantity > 0 && item.valueCzk > 0)

    const valueCzk = items.reduce((sum, item) => sum + item.valueCzk, 0)
    const investedCzk = items.reduce((sum, item) => sum + item.costCzk, 0)
    const allocations = items.map((item) => ({
      symbol: item.symbol,
      accountId: item.accountId,
      valueCzk: item.valueCzk,
      allocationPct: valueCzk > 0 ? (item.valueCzk / valueCzk) * 100 : 0,
    }))

    points.push({
      timestamp: bucket,
      month: monthKey(bucket),
      label: pointLabel(bucket, intervalDays),
      investedCzk: Math.round(investedCzk),
      netWorthCzk: Math.round(valueCzk),
      valueCzk: Math.round(valueCzk),
      interval: intervalDays,
      allocations,
    })

    await prisma.$transaction(async (tx) => {
      for (const account of accountIds) {
        const accountItems = items.filter((item) => item.accountId === account)
        const accountValue = accountItems.reduce((sum, item) => sum + item.valueCzk, 0)
        const accountCostBasis = accountItems.reduce((sum, item) => sum + item.costCzk, 0)
        const snapshot = await tx.accountSnapshot.upsert({
          where: {
            accountId_timestamp_currency_granularity: {
              accountId: account,
              timestamp: bucket,
              currency: "CZK",
              granularity: "day",
            },
          },
          update: {
            source: "manual_recalculation",
            investmentValue: accountValue,
            investmentCostBasis: accountCostBasis,
            totalValue: accountValue,
            isRecalculated: true,
          },
          create: {
            accountId: account,
            timestamp: bucket,
            granularity: "day",
            source: "manual_recalculation",
            currency: "CZK",
            cashValue: 0,
            investmentValue: accountValue,
            investmentCostBasis: accountCostBasis,
            liabilitiesValue: 0,
            totalValue: accountValue,
            isRecalculated: true,
          },
        })

        await tx.accountSnapshotItem.deleteMany({ where: { snapshotId: snapshot.id } })

        if (accountItems.length > 0) {
          await tx.accountSnapshotItem.createMany({
            data: accountItems.map((item) => ({
              snapshotId: snapshot.id,
              assetId: item.assetId,
              listingId: item.listingId,
              symbol: item.symbol,
              quantity: item.quantity,
              pricePerUnit: item.pricePerUnit,
              value: item.valueCzk,
              costBasis: item.costCzk,
              costCurrency: "CZK",
              allocationPct: accountValue > 0 ? (item.valueCzk / accountValue) * 100 : 0,
            })),
          })
        }
      }
    })
  }

  return points
}

export async function getPortfolioSnapshotHistory({
  userId,
  accountId,
  range = "1Y",
}: {
  userId: string
  accountId?: string | null
  range?: PortfolioHistoryRange
}) {
  const accessibleIds = await getMembershipAccountIds(userId, "viewer")
  const now = new Date()
  const start = rangeStart(range, null, now)
  const snapshots = await prisma.accountSnapshot.findMany({
    where: {
      accountId: accountId ? accountId : { in: accessibleIds },
      currency: "CZK",
      granularity: "day",
      ...(range === "ALL" ? {} : { timestamp: { gte: start } }),
    },
    include: {
      account: {
        select: { name: true },
      },
      items: {
        include: {
          asset: {
            select: { name: true, assetType: true, currency: true },
          },
        },
        orderBy: { allocationPct: "desc" },
      },
    },
    orderBy: { timestamp: "asc" },
  })
  const effectiveStart =
    range === "ALL" && snapshots.length > 0 ? todayStart(snapshots[0].timestamp) : start
  const intervalDays = intervalDaysForPeriod(effectiveStart, now)

  const latestByAccountBucket = new Map<string, (typeof snapshots)[number]>()
  for (const snapshot of snapshots) {
    const key = `${historyBucketKey(snapshot.timestamp, effectiveStart, intervalDays)}:${snapshot.accountId}`
    const current = latestByAccountBucket.get(key)
    if (!current || snapshot.timestamp > current.timestamp) {
      latestByAccountBucket.set(key, snapshot)
    }
  }

  const bucketSnapshots = [...latestByAccountBucket.values()].sort(
    (a, b) => a.timestamp.getTime() - b.timestamp.getTime()
  )

  const grouped = new Map<
    string,
    {
      timestamp: Date
      valueCzk: number
      investedCzk: number
      netDepositsCzk: number
      cashCzk: number
      investmentCostBasisCzk: number
      realizedPnlCzk: number
      unrealizedPnlCzk: number
      cashByCurrency: CurrencyBreakdown
      investmentValueByCurrency: CurrencyBreakdown
      investmentCostBasisByCurrency: CurrencyBreakdown
      netDepositsByCurrency: CurrencyBreakdown
      realizedPnlByCurrency: CurrencyBreakdown
      unrealizedPnlByCurrency: CurrencyBreakdown
      feesByCurrency: CurrencyBreakdown
      taxesByCurrency: CurrencyBreakdown
      allocations: { symbol: string; accountId: string; valueCzk: number; allocationPct: number }[]
      positions: {
        id: string
        listingId: string | null
        symbol: string
        name: string | null
        assetType: AssetType
        quantity: number
        avgBuyPrice: number
        avgBuyPriceCzk: number
        currency: string
        accountId: string
        accountName: string | null
        currentPrice: number | null
        currentPriceCurrency: string | null
        currentValue: number | null
        currentValueCzk: number | null
        unrealizedPnl: number | null
        unrealizedPnlCzk: number | null
        unrealizedPnlPct: number | null
      }[]
    }
  >()

  for (const snapshot of bucketSnapshots) {
    const key = historyBucketKey(snapshot.timestamp, effectiveStart, intervalDays)
    const current = grouped.get(key) ?? {
      timestamp: snapshot.timestamp,
      valueCzk: 0,
      investedCzk: 0,
      netDepositsCzk: 0,
      cashCzk: 0,
      investmentCostBasisCzk: 0,
      realizedPnlCzk: 0,
      unrealizedPnlCzk: 0,
      cashByCurrency: {},
      investmentValueByCurrency: {},
      investmentCostBasisByCurrency: {},
      netDepositsByCurrency: {},
      realizedPnlByCurrency: {},
      unrealizedPnlByCurrency: {},
      feesByCurrency: {},
      taxesByCurrency: {},
      allocations: [],
      positions: [],
    }
    if (snapshot.timestamp > current.timestamp) current.timestamp = snapshot.timestamp
    const valueCzk = toNum(snapshot.totalValue)
    const cashCzk = toNum(snapshot.cashValue)
    const investmentValueCzk = toNum(snapshot.investmentValue)
    const investmentCostBasisCzk = toNum(snapshot.investmentCostBasis)
    const cashByCurrency = jsonCurrencyBreakdown(snapshot.cashValueByCurrency)
    const investmentValueByCurrency = jsonCurrencyBreakdown(snapshot.investmentValueByCurrency)
    const investmentCostBasisByCurrency = jsonCurrencyBreakdown(
      snapshot.investmentCostBasisByCurrency
    )
    const netDepositsByCurrency = jsonCurrencyBreakdown(snapshot.netDepositsByCurrency)
    const realizedPnlByCurrency = jsonCurrencyBreakdown(snapshot.realizedPnlByCurrency)
    const unrealizedPnlByCurrency = jsonCurrencyBreakdown(snapshot.unrealizedPnlByCurrency)
    const feesByCurrency = jsonCurrencyBreakdown(snapshot.feesByCurrency)
    const taxesByCurrency = jsonCurrencyBreakdown(snapshot.taxesByCurrency)
    const investedCzk = snapshot.items.reduce(
      (sum, item) => sum + (item.costBasis != null ? toNum(item.costBasis) : 0),
      0
    )
    const costBasisForPnl = investmentCostBasisCzk > 0 ? investmentCostBasisCzk : investedCzk
    current.valueCzk += valueCzk
    current.cashCzk += cashCzk
    current.investmentCostBasisCzk += investmentCostBasisCzk
    current.investedCzk += investmentCostBasisCzk > 0 ? investmentCostBasisCzk : investedCzk
    current.netDepositsCzk += toNum(snapshot.netDepositsValue)
    current.realizedPnlCzk += toNum(snapshot.realizedPnlValue)
    current.unrealizedPnlCzk +=
      toNum(snapshot.unrealizedPnlValue) || investmentValueCzk - costBasisForPnl
    current.cashByCurrency = mergeCurrencyBreakdowns(current.cashByCurrency, cashByCurrency)
    current.investmentValueByCurrency = mergeCurrencyBreakdowns(
      current.investmentValueByCurrency,
      investmentValueByCurrency
    )
    current.investmentCostBasisByCurrency = mergeCurrencyBreakdowns(
      current.investmentCostBasisByCurrency,
      investmentCostBasisByCurrency
    )
    current.netDepositsByCurrency = mergeCurrencyBreakdowns(
      current.netDepositsByCurrency,
      netDepositsByCurrency
    )
    current.realizedPnlByCurrency = mergeCurrencyBreakdowns(
      current.realizedPnlByCurrency,
      realizedPnlByCurrency
    )
    current.unrealizedPnlByCurrency = mergeCurrencyBreakdowns(
      current.unrealizedPnlByCurrency,
      unrealizedPnlByCurrency
    )
    current.feesByCurrency = mergeCurrencyBreakdowns(current.feesByCurrency, feesByCurrency)
    current.taxesByCurrency = mergeCurrencyBreakdowns(current.taxesByCurrency, taxesByCurrency)
    current.allocations.push(
      ...snapshot.items.map((item) => ({
        symbol: item.symbol,
        accountId: snapshot.accountId,
        valueCzk: toNum(item.value),
        allocationPct: toNum(item.allocationPct),
      }))
    )
    current.positions.push(
      ...snapshot.items
        .map((item) => {
          const quantity = toNum(item.quantity)
          const valueCzk = toNum(item.value)
          const costBasisCzk = item.costBasis != null ? toNum(item.costBasis) : 0
          const nativeValue = item.nativeValue != null ? toNum(item.nativeValue) : valueCzk
          const nativeValueCurrency = item.valueCurrency ?? item.priceCurrency ?? "CZK"
          const nativeCostBasis =
            item.nativeCostBasis != null ? toNum(item.nativeCostBasis) : costBasisCzk
          const nativeCostCurrency = item.nativeCostCurrency ?? item.costCurrency ?? "CZK"
          const avgBuyPriceCzk = quantity > 0 ? costBasisCzk / quantity : 0
          const avgBuyPrice = quantity > 0 ? nativeCostBasis / quantity : 0
          const unrealizedPnlCzk = valueCzk - costBasisCzk
          const unrealizedPnl =
            nativeValueCurrency === nativeCostCurrency ? nativeValue - nativeCostBasis : null
          const unrealizedPnlPct = costBasisCzk > 0 ? (unrealizedPnlCzk / costBasisCzk) * 100 : null

          return {
            id: `${snapshot.accountId}:${item.symbol}`,
            listingId: item.listingId,
            symbol: item.symbol,
            name: item.asset?.name ?? null,
            assetType: item.asset?.assetType ?? "stock",
            quantity,
            avgBuyPrice,
            avgBuyPriceCzk,
            currency: nativeCostCurrency,
            accountId: snapshot.accountId,
            accountName: snapshot.account.name,
            currentPrice: toNum(item.pricePerUnit),
            currentPriceCurrency: item.priceCurrency ?? nativeValueCurrency,
            currentValue: nativeValue,
            currentValueCzk: valueCzk,
            unrealizedPnl,
            unrealizedPnlCzk,
            unrealizedPnlPct,
          }
        })
        .filter((position) => position.quantity > 0)
    )
    grouped.set(key, current)
  }

  return [...grouped.values()].map((snapshot) => ({
    timestamp: snapshot.timestamp,
    month: monthKey(snapshot.timestamp),
    label: snapshot.timestamp.toLocaleDateString("cs-CZ", {
      month: "short",
      year: "numeric",
    }),
    valueCzk: Math.round(snapshot.valueCzk),
    investedCzk: Math.round(snapshot.investedCzk),
    netDepositsCzk: Math.round(snapshot.netDepositsCzk),
    cashCzk: Math.round(snapshot.cashCzk),
    investmentCostBasisCzk: Math.round(snapshot.investmentCostBasisCzk),
    realizedPnlCzk: Math.round(snapshot.realizedPnlCzk),
    unrealizedPnlCzk: Math.round(snapshot.unrealizedPnlCzk),
    cashByCurrency: roundCurrencyBreakdown(snapshot.cashByCurrency),
    investmentValueByCurrency: roundCurrencyBreakdown(snapshot.investmentValueByCurrency),
    investmentCostBasisByCurrency: roundCurrencyBreakdown(snapshot.investmentCostBasisByCurrency),
    netDepositsByCurrency: roundCurrencyBreakdown(snapshot.netDepositsByCurrency),
    realizedPnlByCurrency: roundCurrencyBreakdown(snapshot.realizedPnlByCurrency),
    unrealizedPnlByCurrency: roundCurrencyBreakdown(snapshot.unrealizedPnlByCurrency),
    feesByCurrency: roundCurrencyBreakdown(snapshot.feesByCurrency),
    taxesByCurrency: roundCurrencyBreakdown(snapshot.taxesByCurrency),
    netWorthCzk: Math.round(snapshot.valueCzk),
    allocations: snapshot.allocations.map((item) => ({
      ...item,
      allocationPct: snapshot.valueCzk > 0 ? (item.valueCzk / snapshot.valueCzk) * 100 : 0,
    })),
    positions: snapshot.positions.sort(
      (a, b) => (b.currentValueCzk ?? 0) - (a.currentValueCzk ?? 0)
    ),
  }))
}

export async function getNetWorthSnapshotHistory({
  userId,
  accountId,
}: {
  userId: string
  accountId?: string | null
}) {
  if (accountId) return []

  let snapshots = await prisma.netWorthSnapshot.findMany({
    where: { userId, currency: "CZK" },
    orderBy: { timestamp: "asc" },
  })

  if (snapshots.length === 0) {
    await createNetWorthSnapshot({ userId })
    snapshots = await prisma.netWorthSnapshot.findMany({
      where: { userId, currency: "CZK" },
      orderBy: { timestamp: "asc" },
    })
  }

  return snapshots.map((snapshot) => ({
    month: monthKey(snapshot.timestamp),
    label: snapshot.timestamp.toLocaleDateString("cs-CZ", {
      month: "short",
      year: "numeric",
    }),
    cashCzk: Math.round(toNum(snapshot.cashValue)),
    investedCzk: Math.round(toNum(snapshot.portfolioValue)),
    netWorthCzk: Math.round(toNum(snapshot.totalNetWorth)),
  }))
}

async function calculateAccountLedgerSnapshot(
  accountId: string,
  until: Date,
  displayCurrency = "CZK"
): Promise<AccountLedgerSnapshot> {
  const events = await prisma.investmentEvent.findMany({
    where: {
      accountId,
      deletedAt: null,
      archivedAt: null,
      date: { lte: until },
    },
    include: { movements: true },
    orderBy: { date: "asc" },
  })

  const snapshot = emptyLedgerSnapshot()

  for (const event of events) {
    const currencies = [
      event.realizedPnlCurrency,
      ...event.movements.flatMap((movement) => [movement.valueCurrency, movement.currency]),
      ...Object.values(snapshot.positions).map((position) => position.currency),
    ].filter((currency): currency is string => Boolean(currency))
    const rates = await getHistoricalExchangeRates({
      date: event.date,
      toCurrency: displayCurrency,
      currencies,
    })
    applyInvestmentEventToLedgerSnapshot(snapshot, event, {
      pricesBySymbol: {},
      date: event.date,
      rates,
      displayCurrency,
    })
  }

  return snapshot
}

async function calculateAccountLedgerSnapshotFromLatestSnapshot(
  accountId: string,
  until: Date,
  displayCurrency = "CZK"
): Promise<AccountLedgerSnapshot> {
  const seed = await getImportSnapshotSeed(accountId, todayStart(until), displayCurrency)
  const snapshot = cloneLedgerSnapshot(seed.ledgerSnapshot)

  const events: LedgerSnapshotEvent[] = await prisma.investmentEvent.findMany({
    where: {
      accountId,
      deletedAt: null,
      archivedAt: null,
      date: {
        ...(seed.eventCursor ? { gt: seed.eventCursor } : {}),
        lte: until,
      },
    },
    include: { movements: true },
    orderBy: { date: "asc" },
  })

  const assetMovements = events.flatMap((event) =>
    event.movements
      .filter((movement) => movement.kind === "asset" && movement.sourceSymbol)
      .map((movement) => ({
        symbol: movement.sourceSymbol!,
        assetType: movement.sourceAssetType ?? "stock",
        currency: movement.valueCurrency ?? movement.currency ?? "EUR",
        listingId: movement.listingId,
      }))
  )
  const seedPositions = Object.values(snapshot.positions).map((position) => ({
    symbol: position.symbol,
    assetType: position.assetType,
    currency: position.currency,
    listingId: position.listingId,
  }))
  const priceDefinitions = [...assetMovements, ...seedPositions].filter(
    (definition, index, all) =>
      all.findIndex((item) => priceLookupKey(item) === priceLookupKey(definition)) === index
  )
  const pricesBySymbol =
    priceDefinitions.length > 0
      ? await getHistoricalPrices(priceDefinitions, seed.eventCursor ?? until, until)
      : {}

  for (const event of events) {
    const currencies = [
      event.realizedPnlCurrency,
      ...event.movements.flatMap((movement) => [
        movement.valueCurrency,
        movement.currency,
        movement.kind === "asset" ? (movement.valueCurrency ?? movement.currency) : null,
      ]),
      ...Object.values(snapshot.positions).map((position) => position.currency),
    ].filter((currency): currency is string => Boolean(currency))
    const eventRates = await getHistoricalExchangeRates({
      date: event.date,
      toCurrency: displayCurrency,
      currencies,
    })

    applyInvestmentEventToLedgerSnapshot(snapshot, event, {
      pricesBySymbol,
      date: event.date,
      rates: eventRates,
      displayCurrency,
    })
  }

  return snapshot
}

function positionsValue(
  positions: Record<string, SnapshotPosition>,
  rates: Record<string, number>,
  displayCurrency = "CZK"
) {
  return Object.values(positions)
    .filter((position) => position.quantity > 0.000001)
    .reduce(
      (sum, position) =>
        sum + toDisplayCurrency(position.totalCost, position.currency, rates, displayCurrency),
      0
    )
}

async function writeImportLog(
  importBatchId: string | null | undefined,
  level: "info" | "warning" | "error",
  event: "snapshots_recalculated" | "snapshot_validation_failed" | "failed",
  message: string
) {
  if (!importBatchId) return

  await prisma.importLog.create({
    data: { importBatchId, level, event, message },
  })
}

async function flushAccountSnapshotChunk({
  accountId,
  snapshots,
  items,
}: {
  accountId: string
  snapshots: Prisma.AccountSnapshotCreateManyInput[]
  items: Prisma.AccountSnapshotItemCreateManyInput[]
}) {
  if (snapshots.length === 0) return

  const timestamps = snapshots.map((snapshot) => snapshot.timestamp as Date)
  await prisma.$transaction(async (tx) => {
    await tx.accountSnapshot.deleteMany({
      where: {
        accountId,
        currency: "CZK",
        granularity: "day",
        timestamp: { in: timestamps },
      },
    })
    await tx.accountSnapshot.createMany({ data: snapshots })
    if (items.length > 0) {
      await tx.accountSnapshotItem.createMany({ data: items })
    }
  })
}

export async function createDailyAccountSnapshotsFromImport({
  accountId,
  importBatchId,
  importStartDate,
  validationInterval = 0,
}: {
  accountId: string
  importBatchId?: string | null
  importStartDate?: Date | null
  validationInterval?: number
}) {
  const account = await prisma.account.findUnique({
    where: { id: accountId },
    select: { currency: true },
  })
  const displayCurrency = normalizeCurrency(account?.currency, "CZK")
  const firstImportedEvent = await prisma.investmentEvent.findFirst({
    where: importBatchId
      ? { accountId, importBatchId }
      : { accountId, deletedAt: null, archivedAt: null },
    orderBy: { date: "asc" },
    select: { date: true },
  })

  if (!firstImportedEvent && !importStartDate) return { snapshots: 0, validations: 0 }

  const firstDate = todayStart(firstImportedEvent?.date ?? importStartDate!)
  const today = todayStart()
  const start = firstDate

  let snapshots = 0
  let validations = 0
  const ratesCache = new Map<string, Record<string, number>>()
  const seed = await getImportSnapshotSeed(accountId, start, displayCurrency)

  const accountMovements = await prisma.investmentMovement.findMany({
    where: {
      event: { accountId, deletedAt: null, archivedAt: null },
      kind: "asset",
      sourceSymbol: { not: null },
    },
    select: {
      sourceSymbol: true,
      sourceAssetType: true,
      valueCurrency: true,
      currency: true,
      listingId: true,
    },
  })
  const symbolMap = new Map<
    string,
    { symbol: string; assetType: string; currency: string; listingId: string | null }
  >()
  for (const m of accountMovements) {
    const key = m.listingId ?? m.sourceSymbol
    if (m.sourceSymbol && key && !symbolMap.has(key)) {
      symbolMap.set(key, {
        symbol: m.sourceSymbol,
        assetType: m.sourceAssetType ?? "stock",
        currency: m.valueCurrency ?? m.currency ?? "EUR",
        listingId: m.listingId,
      })
    }
  }
  for (const position of Object.values(seed.ledgerSnapshot.positions)) {
    const key = position.listingId
    if (!symbolMap.has(key)) {
      symbolMap.set(key, {
        symbol: position.symbol,
        assetType: position.assetType,
        currency: position.currency,
        listingId: position.listingId,
      })
    }
  }
  const symbolDefinitions = [...symbolMap.values()].map((def) => ({
    symbol: def.symbol,
    assetType: def.assetType,
    currency: def.currency,
    listingId: def.listingId,
  }))
  const events: LedgerSnapshotEvent[] = await prisma.investmentEvent.findMany({
    where: {
      accountId,
      deletedAt: null,
      archivedAt: null,
      date: {
        ...(seed.eventCursor ? { gt: seed.eventCursor } : {}),
        lte: endOfDay(today),
      },
    },
    include: { movements: true },
    orderBy: { date: "asc" },
  })
  const eventCurrencies = events.flatMap((event) => [
    event.realizedPnlCurrency,
    ...event.movements.flatMap((movement) => [
      movement.valueCurrency,
      movement.kind === "asset" ? null : movement.currency,
    ]),
  ])
  const rateCurrencies = [
    ...symbolDefinitions.map((symbol) => symbol.currency),
    ...eventCurrencies,
    ...currencyBreakdownCurrencies(
      seed.ledgerSnapshot.cashByCurrency,
      seed.ledgerSnapshot.netDepositsByCurrency,
      seed.ledgerSnapshot.realizedPnlByCurrency,
      seed.ledgerSnapshot.feesByCurrency,
      seed.ledgerSnapshot.taxesByCurrency
    ),
    ...Object.values(seed.ledgerSnapshot.positions).map((position) => position.currency),
  ].filter((currency): currency is string => Boolean(currency))

  await ensureExchangeRatesForPeriod({
    currencies: rateCurrencies,
    toCurrency: displayCurrency,
    start: firstDate,
    end: today,
  })

  const pricesBySymbol =
    symbolDefinitions.length > 0
      ? await getHistoricalPrices(symbolDefinitions, firstDate, endOfDay(today))
      : {}
  const priceCurrencies = Object.values(pricesBySymbol).flatMap((prices) =>
    prices.map((price) => price.currency)
  )
  const allRateCurrencies = [...new Set([...rateCurrencies, ...priceCurrencies])]
  if (priceCurrencies.length > 0) {
    await ensureExchangeRatesForPeriod({
      currencies: allRateCurrencies,
      toCurrency: displayCurrency,
      start: firstDate,
      end: today,
    })
  }

  const ledgerSnapshot = seed.ledgerSnapshot
  let eventIndex = 0
  let pendingSnapshots: Prisma.AccountSnapshotCreateManyInput[] = []
  let pendingItems: Prisma.AccountSnapshotItemCreateManyInput[] = []
  let lastFlushAt = Date.now()

  const flushPendingSnapshots = async () => {
    await flushAccountSnapshotChunk({
      accountId,
      snapshots: pendingSnapshots,
      items: pendingItems,
    })
    pendingSnapshots = []
    pendingItems = []
    lastFlushAt = Date.now()
  }

  for (let day = start, dayIndex = 1; day <= today; day = addDays(day, 1), dayIndex += 1) {
    const dayEnd = endOfDay(day)
    const rates = await getCachedHistoricalCzkRates(
      ratesCache,
      day,
      allRateCurrencies,
      displayCurrency
    )

    while (eventIndex < events.length && events[eventIndex].date <= dayEnd) {
      applyInvestmentEventToLedgerSnapshot(ledgerSnapshot, events[eventIndex], {
        pricesBySymbol,
        date: day,
        rates,
        displayCurrency,
      })
      eventIndex += 1
    }

    const { positions } = ledgerSnapshot

    if (validationInterval > 0 && dayIndex % validationInterval === 0) {
      validations += 1
      const expected = positionsValue(positions, rates, displayCurrency)
      const actualSnapshot = await calculateAccountLedgerSnapshot(accountId, dayEnd)
      const actual = positionsValue(actualSnapshot.positions, rates, displayCurrency)
      if (Math.abs(expected - actual) > 0.01) {
        const message = `Snapshot validation failed for ${accountId} at ${day.toISOString()}: expected ${expected}, actual ${actual}.`
        await writeImportLog(importBatchId, "error", "snapshot_validation_failed", message)
        throw new Error(message)
      }
    }

    const activePositions = Object.values(positions).filter(
      (position) => position.quantity > 0.000001
    )
    const items = activePositions.map((position) => {
      const priceKey = priceLookupKey({
        symbol: position.symbol,
        assetType: position.assetType,
        currency: position.currency,
        listingId: position.listingId,
      })
      const close = findCloseAtOrBefore(
        pricesBySymbol[priceKey] ?? pricesBySymbol[position.symbol] ?? [],
        day
      )
      const nativeCostBasis = position.totalCost
      const avgCostPerUnit = position.quantity > 0 ? nativeCostBasis / position.quantity : 0
      const pricePerUnit = close?.price ?? avgCostPerUnit
      const priceCurrency = normalizeCurrency(close?.currency ?? position.currency)
      const nativeValue = pricePerUnit * position.quantity
      const value = toDisplayCurrency(nativeValue, priceCurrency, rates, displayCurrency)
      const costBasis = toDisplayCurrency(
        nativeCostBasis,
        position.currency,
        rates,
        displayCurrency
      )
      return {
        ...position,
        valueCzk: value,
        nativeValue,
        valueCurrency: priceCurrency,
        costBasisCzk: costBasis,
        nativeCostBasis,
        nativeCostCurrency: position.currency,
        pricePerUnit,
      }
    })
    const investmentValueByCurrency: CurrencyBreakdown = {}
    const investmentCostBasisByCurrency: CurrencyBreakdown = {}
    for (const item of items) {
      addCurrencyAmount(investmentValueByCurrency, item.valueCurrency, item.nativeValue)
      addCurrencyAmount(
        investmentCostBasisByCurrency,
        item.nativeCostCurrency,
        item.nativeCostBasis
      )
    }
    const unrealizedPnlByCurrency = subtractCurrencyBreakdowns(
      investmentValueByCurrency,
      investmentCostBasisByCurrency
    )
    const investmentValue = convertCurrencyBreakdown(
      investmentValueByCurrency,
      rates,
      displayCurrency
    )
    const investmentCostBasis = convertCurrencyBreakdown(
      investmentCostBasisByCurrency,
      rates,
      displayCurrency
    )
    const cashValue = convertCurrencyBreakdown(
      ledgerSnapshot.cashByCurrency,
      rates,
      displayCurrency
    )
    const netDepositsValue = ledgerSnapshot.netDepositsValueCzk
    const realizedPnlValue = convertCurrencyBreakdown(
      ledgerSnapshot.realizedPnlByCurrency,
      rates,
      displayCurrency
    )
    const unrealizedPnlValue = investmentValue - investmentCostBasis
    const feesValue = convertCurrencyBreakdown(
      ledgerSnapshot.feesByCurrency,
      rates,
      displayCurrency
    )
    const taxesValue = convertCurrencyBreakdown(
      ledgerSnapshot.taxesByCurrency,
      rates,
      displayCurrency
    )
    const totalValue = investmentValue + cashValue
    const ratesForSnapshot = snapshotExchangeRates(
      rates,
      currencyBreakdownCurrencies(
        ledgerSnapshot.cashByCurrency,
        investmentValueByCurrency,
        investmentCostBasisByCurrency,
        ledgerSnapshot.netDepositsByCurrency,
        ledgerSnapshot.realizedPnlByCurrency,
        unrealizedPnlByCurrency,
        ledgerSnapshot.feesByCurrency,
        ledgerSnapshot.taxesByCurrency
      ),
      displayCurrency
    )

    const snapshotId = randomUUID()
    pendingSnapshots.push({
      id: snapshotId,
      accountId,
      timestamp: day,
      granularity: "day",
      source: "import_event",
      currency: displayCurrency,
      cashValue,
      investmentValue,
      investmentCostBasis,
      netDepositsValue,
      realizedPnlValue,
      unrealizedPnlValue,
      feesValue,
      taxesValue,
      liabilitiesValue: 0,
      totalValue,
      cashValueByCurrency: roundCurrencyBreakdown(ledgerSnapshot.cashByCurrency),
      investmentValueByCurrency: roundCurrencyBreakdown(investmentValueByCurrency),
      investmentCostBasisByCurrency: roundCurrencyBreakdown(investmentCostBasisByCurrency),
      netDepositsByCurrency: roundCurrencyBreakdown(ledgerSnapshot.netDepositsByCurrency),
      realizedPnlByCurrency: roundCurrencyBreakdown(ledgerSnapshot.realizedPnlByCurrency),
      unrealizedPnlByCurrency: roundCurrencyBreakdown(unrealizedPnlByCurrency),
      feesByCurrency: roundCurrencyBreakdown(ledgerSnapshot.feesByCurrency),
      taxesByCurrency: roundCurrencyBreakdown(ledgerSnapshot.taxesByCurrency),
      exchangeRates: ratesForSnapshot,
      isRecalculated: true,
    })
    pendingItems.push(
      ...items.map((position) => ({
        snapshotId,
        assetId: position.assetId,
        listingId: position.listingId,
        symbol: position.symbol,
        quantity: position.quantity,
        pricePerUnit: position.pricePerUnit,
        priceCurrency: position.valueCurrency,
        value: position.valueCzk,
        nativeValue: position.nativeValue,
        valueCurrency: position.valueCurrency,
        costBasis: position.costBasisCzk,
        costCurrency: displayCurrency,
        nativeCostBasis: position.nativeCostBasis,
        nativeCostCurrency: position.nativeCostCurrency,
        allocationPct: investmentValue > 0 ? (position.valueCzk / investmentValue) * 100 : 0,
      }))
    )
    snapshots += 1

    if (
      Date.now() - lastFlushAt >= SNAPSHOT_FLUSH_MS ||
      pendingSnapshots.length >= SNAPSHOT_FLUSH_COUNT ||
      pendingItems.length >= SNAPSHOT_ITEM_FLUSH_COUNT
    ) {
      await flushPendingSnapshots()
    }
  }

  await flushPendingSnapshots()

  await writeImportLog(
    importBatchId,
    "info",
    "snapshots_recalculated",
    `Created or updated ${snapshots} daily account snapshots for ${accountId}; validations: ${validations}; seed: ${seed.seedSource}.`
  )

  return { snapshots, validations }
}
