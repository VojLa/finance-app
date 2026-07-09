import { prisma, toNum } from "@/lib/prisma"
import { getAccessibleAccountIds as getMembershipAccountIds } from "@/lib/accountAccess"
import {
  getCzkRates,
  getHistoricalCzkRates,
  getHistoricalPrices,
  getLivePrices,
  toCzk,
  type HistoricalPricePoint,
} from "@/modules/portfolio/rates/service"
import type { AssetType, SnapshotGranularity, SnapshotSource } from "@prisma/client"

const BANK_ACCOUNT_TYPES = new Set(["bank", "cash", "savings"])
const LIABILITY_ACCOUNT_TYPES = new Set(["credit_card", "loan", "mortgage"])
const INVESTMENT_ACCOUNT_TYPES = new Set(["broker", "exchange", "crypto_wallet"])

function bucketTimestamp(date: Date, granularity: SnapshotGranularity): Date {
  const bucket = new Date(date)
  bucket.setSeconds(0, 0)

  if (granularity === "hour") bucket.setMinutes(0, 0, 0)
  if (granularity === "day") bucket.setHours(0, 0, 0, 0)
  if (granularity === "week") {
    const day = bucket.getDay() || 7
    bucket.setDate(bucket.getDate() - day + 1)
    bucket.setHours(0, 0, 0, 0)
  }
  if (granularity === "month") {
    bucket.setDate(1)
    bucket.setHours(0, 0, 0, 0)
  }

  return bucket
}

function monthKey(date: Date): string {
  return date.toISOString().slice(0, 7)
}

export type PortfolioHistoryRange = "1W" | "1M" | "3M" | "6M" | "1Y" | "ALL"

type PortfolioHistoryInterval = number

interface HistoricalPosition {
  symbol: string
  accountId: string
  assetType: AssetType
  name: string | null
  quantity: number
  totalCost: number
  currency: string
}

interface SnapshotPosition {
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
  cashValueCzk: number
}

interface LedgerSnapshotEvent {
  accountId: string
  description: string | null
  date: Date
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
  return new Date(date.getFullYear(), date.getMonth(), date.getDate())
}

function endOfDay(date: Date): Date {
  const end = new Date(date)
  end.setHours(23, 59, 59, 999)
  return end
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date)
  next.setDate(next.getDate() + days)
  return next
}

function rangeStart(range: PortfolioHistoryRange, firstDate: Date | null, now = new Date()): Date {
  const start = todayStart(now)

  if (range === "1W") start.setDate(start.getDate() - 7)
  if (range === "1M") start.setMonth(start.getMonth() - 1)
  if (range === "3M") start.setMonth(start.getMonth() - 3)
  if (range === "6M") start.setMonth(start.getMonth() - 6)
  if (range === "1Y") start.setFullYear(start.getFullYear() - 1)

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

function positionKey(accountId: string, symbol: string) {
  return `${accountId}:${symbol}`
}

async function getCachedHistoricalCzkRates(cache: Map<string, Record<string, number>>, date: Date) {
  const key = todayStart(date).toISOString()
  const cached = cache.get(key)
  if (cached) return cached

  const rates = await getHistoricalCzkRates(date)
  cache.set(key, rates)
  return rates
}

function applyInvestmentEventToSnapshotPositions(
  positions: Record<string, SnapshotPosition>,
  event: LedgerSnapshotEvent,
  czkRates: Record<string, number>
) {
  const asset = event.movements.find(
    (movement) => movement.kind === "asset" && movement.sourceSymbol
  )
  if (!asset?.sourceSymbol) return

  const key = positionKey(event.accountId, asset.sourceSymbol)
  positions[key] ||= {
    symbol: asset.sourceSymbol,
    accountId: event.accountId,
    assetId: asset.assetId,
    assetType: asset.sourceAssetType ?? "stock",
    name: event.description,
    quantity: 0,
    totalCost: 0,
    currency: "CZK",
  }

  const position = positions[key]
  const quantity = toNum(asset.quantity as never)
  const price = toNum(asset.pricePerUnit as never)
  const valueAmount = toNum(asset.valueAmount as never)
  const cost = price > 0 ? quantity * price : valueAmount
  const costCzk = toCzk(cost, asset.valueCurrency ?? asset.currency ?? "EUR", czkRates)

  if (asset.direction === "in") {
    position.quantity += quantity
    if (costCzk > 0) position.totalCost += costCzk
    return
  }

  const avgCost = position.quantity > 0 ? position.totalCost / position.quantity : 0
  position.totalCost -= avgCost * quantity
  position.quantity -= quantity
}

function applyInvestmentEventToLedgerSnapshot(
  snapshot: AccountLedgerSnapshot,
  event: LedgerSnapshotEvent,
  czkRates: Record<string, number>
) {
  applyInvestmentEventToSnapshotPositions(snapshot.positions, event, czkRates)

  for (const movement of event.movements) {
    if (!["cash", "fee", "tax"].includes(movement.kind)) continue

    const amount = toNum((movement.valueAmount ?? movement.quantity) as never)
    const currency = movement.valueCurrency ?? movement.currency ?? "CZK"
    const valueCzk = toCzk(amount, currency, czkRates)
    snapshot.cashValueCzk += movement.direction === "in" ? valueCzk : -valueCzk
  }
}

function cashMovementsValueCzk(
  event: {
    movements: Array<{
      kind: string
      direction: string
      valueAmount: unknown
      quantity: unknown
      valueCurrency: string | null
      currency: string | null
    }>
  },
  czkRates: Record<string, number>
) {
  return event.movements
    .filter((movement) => movement.kind === "cash")
    .reduce((sum, movement) => {
      const amount = toNum((movement.valueAmount ?? movement.quantity) as never)
      const currency = movement.valueCurrency ?? movement.currency ?? "CZK"
      const valueCzk = toCzk(amount, currency, czkRates)
      return sum + (movement.direction === "in" ? valueCzk : -valueCzk)
    }, 0)
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

async function calculateAccountValueCzk(accountIds: string[], czkRates: Record<string, number>) {
  if (accountIds.length === 0) return 0

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

  return txs.reduce((sum, tx) => {
    const amountCzk =
      tx.reportingAmount && tx.reportingCurrency === "CZK"
        ? toNum(tx.reportingAmount)
        : toCzk(toNum(tx.amount), tx.currency, czkRates)
    return sum + (tx.type === "income" ? amountCzk : -amountCzk)
  }, 0)
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
      sourceSymbol: string | null
      sourceAssetType: AssetType | null
    }>
    description: string | null
  }
) {
  const asset = event.movements.find(
    (movement) => movement.kind === "asset" && movement.sourceSymbol
  )
  if (!asset?.sourceSymbol) return

  const key = `${event.accountId}:${asset.sourceSymbol}`
  positions[key] ||= {
    symbol: asset.sourceSymbol,
    accountId: event.accountId,
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

  const holdings = accounts.flatMap((account) => account.holdings)
  const prices =
    holdings.length > 0
      ? await getLivePrices(
          holdings.map((holding) => ({
            symbol: holding.symbol,
            assetType: holding.assetType,
            currency: holding.currency,
          }))
        )
      : {}
  const czkRates = await getCzkRates()
  const ratesCache = new Map<string, Record<string, number>>()
  const cashByAccount = new Map<string, number>()
  for (const account of accounts) {
    const ledgerSnapshot = await calculateAccountLedgerSnapshot(account.id, timestamp, ratesCache)
    cashByAccount.set(account.id, ledgerSnapshot.cashValueCzk)
  }

  const items = holdings
    .map((holding) => {
      const price = prices[holding.symbol]
      const quantity = toNum(holding.quantity)
      const pricePerUnit = price?.price ?? toNum(holding.avgBuyPrice)
      const priceCurrency = price?.currency ?? holding.currency
      const value = toCzk(pricePerUnit * quantity, priceCurrency, czkRates)
      const costBasis = toCzk(toNum(holding.avgBuyPrice) * quantity, holding.currency, czkRates)

      return {
        assetId: holding.assetId,
        symbol: holding.symbol,
        accountId: holding.accountId,
        quantity,
        pricePerUnit,
        priceCurrency,
        value,
        costBasis,
        costCurrency: "CZK",
      }
    })
    .filter((item) => item.quantity > 0 && item.value > 0)

  const totalValue =
    items.reduce((sum, item) => sum + item.value, 0) +
    [...cashByAccount.values()].reduce((sum, cashValue) => sum + cashValue, 0)

  await prisma.$transaction(async (tx) => {
    for (const account of accounts) {
      const accountItems = items.filter((item) => item.accountId === account.id)
      const accountValue = accountItems.reduce((sum, item) => sum + item.value, 0)
      const accountCostBasis = accountItems.reduce((sum, item) => sum + item.costBasis, 0)
      const accountCashValue = cashByAccount.get(account.id) ?? 0
      const accountTotalValue = accountCashValue + accountValue
      const snapshot = await tx.accountSnapshot.upsert({
        where: {
          accountId_timestamp_currency_granularity: {
            accountId: account.id,
            timestamp: bucket,
            currency: "CZK",
            granularity,
          },
        },
        update: {
          source,
          cashValue: accountCashValue,
          investmentValue: accountValue,
          investmentCostBasis: accountCostBasis,
          totalValue: accountTotalValue,
          isRecalculated: source === "manual_recalculation",
        },
        create: {
          accountId: account.id,
          timestamp: bucket,
          granularity,
          source,
          currency: "CZK",
          cashValue: accountCashValue,
          investmentValue: accountValue,
          investmentCostBasis: accountCostBasis,
          liabilitiesValue: 0,
          totalValue: accountTotalValue,
          isRecalculated: source === "manual_recalculation",
        },
      })

      await tx.accountSnapshotItem.deleteMany({ where: { snapshotId: snapshot.id } })

      if (accountItems.length > 0) {
        await tx.accountSnapshotItem.createMany({
          data: accountItems.map((item) => ({
            snapshotId: snapshot.id,
            assetId: item.assetId,
            symbol: item.symbol,
            quantity: item.quantity,
            pricePerUnit: item.pricePerUnit,
            priceCurrency: item.priceCurrency,
            value: item.value,
            costBasis: item.costBasis,
            costCurrency: item.costCurrency,
            allocationPct: accountValue > 0 ? (item.value / accountValue) * 100 : 0,
          })),
        })
      }
    }
  })

  return { totalValue }
}

export async function createNetWorthSnapshot({
  userId,
  timestamp = new Date(),
}: {
  userId: string
  timestamp?: Date
}) {
  const bucket = bucketTimestamp(timestamp, "day")
  const czkRates = await getCzkRates()
  const accountIds = await getSnapshotAccountIds(userId)
  const [cashValue, liabilitiesValue, portfolioSnapshot] = await Promise.all([
    calculateAccountValueCzk(accountIds.cash, czkRates),
    calculateAccountValueCzk(accountIds.liabilities, czkRates),
    createPortfolioSnapshot({ userId, source: "scheduled", granularity: "day", timestamp }),
  ])

  const portfolioValue = toNum(portfolioSnapshot.totalValue)

  return prisma.netWorthSnapshot.upsert({
    where: {
      userId_timestamp_currency_granularity: {
        userId,
        timestamp: bucket,
        currency: "CZK",
        granularity: "day",
      },
    },
    update: {
      source: "scheduled",
      cashValue,
      portfolioValue,
      liabilitiesValue,
      totalNetWorth: cashValue + portfolioValue - liabilitiesValue,
    },
    create: {
      userId,
      timestamp: bucket,
      granularity: "day",
      source: "scheduled",
      currency: "CZK",
      cashValue,
      portfolioValue,
      liabilitiesValue,
      totalNetWorth: cashValue + portfolioValue - liabilitiesValue,
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
      }))
  )

  const [pricesBySymbol, assets] = await Promise.all([
    getHistoricalPrices(symbolDefinitions, earliestBucket, latestBucket),
    prisma.asset.findMany({
      where: { symbol: { in: [...new Set(symbolDefinitions.map((item) => item.symbol))] } },
      select: { id: true, symbol: true },
    }),
  ])
  const assetIdBySymbol = new Map(assets.map((asset) => [asset.symbol, asset.id]))

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
        const close = findCloseAtOrBefore(pricesBySymbol[position.symbol] ?? [], bucket)
        const avgPrice = position.quantity > 0 ? position.totalCost / position.quantity : 0
        const pricePerUnit = close?.price ?? avgPrice
        const priceCurrency = close?.currency ?? position.currency
        const valueCzk = toCzk(pricePerUnit * position.quantity, priceCurrency, czkRates)
        const costCzk = toCzk(position.totalCost, position.currency, czkRates)

        return {
          assetId: assetIdBySymbol.get(position.symbol) ?? null,
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
  const accountIdsForHistory = [...new Set(bucketSnapshots.map((snapshot) => snapshot.accountId))]
  const netDepositsBySnapshot = new Map<string, number>()
  const realizedPnlBySnapshot = new Map<string, number>()

  if (accountIdsForHistory.length > 0) {
    const latestSnapshotDate = bucketSnapshots[bucketSnapshots.length - 1]?.timestamp
    const [depositEvents, realizedPnlEvents] = latestSnapshotDate
      ? await Promise.all([
          prisma.investmentEvent.findMany({
            where: {
              accountId: { in: accountIdsForHistory },
              deletedAt: null,
              archivedAt: null,
              type: { in: ["cash_deposit", "cash_withdrawal"] },
              date: { lte: latestSnapshotDate },
            },
            include: { movements: true },
            orderBy: { date: "asc" },
          }),
          prisma.investmentEvent.findMany({
            where: {
              accountId: { in: accountIdsForHistory },
              deletedAt: null,
              archivedAt: null,
              realizedPnl: { not: null },
              date: { lte: latestSnapshotDate },
            },
            select: {
              accountId: true,
              date: true,
              realizedPnl: true,
              realizedPnlCurrency: true,
            },
            orderBy: { date: "asc" },
          }),
        ])
      : [[], []]
    const eventsByAccount = new Map<string, typeof depositEvents>()
    for (const event of depositEvents) {
      const events = eventsByAccount.get(event.accountId) ?? []
      events.push(event)
      eventsByAccount.set(event.accountId, events)
    }
    const realizedEventsByAccount = new Map<string, typeof realizedPnlEvents>()
    for (const event of realizedPnlEvents) {
      const events = realizedEventsByAccount.get(event.accountId) ?? []
      events.push(event)
      realizedEventsByAccount.set(event.accountId, events)
    }

    const eventIndexes = new Map<string, number>()
    const realizedEventIndexes = new Map<string, number>()
    const accountNetDeposits = new Map<string, number>()
    const accountRealizedPnl = new Map<string, number>()
    const ratesCache = new Map<string, Record<string, number>>()

    for (const snapshot of bucketSnapshots) {
      const accountEvents = eventsByAccount.get(snapshot.accountId) ?? []
      const realizedAccountEvents = realizedEventsByAccount.get(snapshot.accountId) ?? []
      let eventIndex = eventIndexes.get(snapshot.accountId) ?? 0
      let realizedEventIndex = realizedEventIndexes.get(snapshot.accountId) ?? 0
      let netDepositsCzk = accountNetDeposits.get(snapshot.accountId) ?? 0
      let realizedPnlCzk = accountRealizedPnl.get(snapshot.accountId) ?? 0

      while (
        eventIndex < accountEvents.length &&
        accountEvents[eventIndex].date <= snapshot.timestamp
      ) {
        const event = accountEvents[eventIndex]
        const czkRates = await getCachedHistoricalCzkRates(ratesCache, event.date)
        netDepositsCzk += cashMovementsValueCzk(event, czkRates)
        eventIndex += 1
      }
      while (
        realizedEventIndex < realizedAccountEvents.length &&
        realizedAccountEvents[realizedEventIndex].date <= snapshot.timestamp
      ) {
        const event = realizedAccountEvents[realizedEventIndex]
        const czkRates = await getCachedHistoricalCzkRates(ratesCache, event.date)
        realizedPnlCzk += toCzk(
          toNum(event.realizedPnl),
          event.realizedPnlCurrency ?? "EUR",
          czkRates
        )
        realizedEventIndex += 1
      }

      eventIndexes.set(snapshot.accountId, eventIndex)
      realizedEventIndexes.set(snapshot.accountId, realizedEventIndex)
      accountNetDeposits.set(snapshot.accountId, netDepositsCzk)
      accountRealizedPnl.set(snapshot.accountId, realizedPnlCzk)
      netDepositsBySnapshot.set(snapshot.id, netDepositsCzk)
      realizedPnlBySnapshot.set(snapshot.id, realizedPnlCzk)
    }
  }

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
      allocations: { symbol: string; accountId: string; valueCzk: number; allocationPct: number }[]
      positions: {
        id: string
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
      allocations: [],
      positions: [],
    }
    if (snapshot.timestamp > current.timestamp) current.timestamp = snapshot.timestamp
    const valueCzk = toNum(snapshot.totalValue)
    const cashCzk = toNum(snapshot.cashValue)
    const investmentValueCzk = toNum(snapshot.investmentValue)
    const investmentCostBasisCzk = toNum(snapshot.investmentCostBasis)
    const investedCzk = snapshot.items.reduce(
      (sum, item) => sum + (item.costBasis != null ? toNum(item.costBasis) : 0),
      0
    )
    const costBasisForPnl = investmentCostBasisCzk > 0 ? investmentCostBasisCzk : investedCzk
    current.valueCzk += valueCzk
    current.cashCzk += cashCzk
    current.investmentCostBasisCzk += investmentCostBasisCzk
    current.investedCzk += investmentCostBasisCzk > 0 ? investmentCostBasisCzk : investedCzk
    current.netDepositsCzk += netDepositsBySnapshot.get(snapshot.id) ?? 0
    current.realizedPnlCzk += realizedPnlBySnapshot.get(snapshot.id) ?? 0
    current.unrealizedPnlCzk += investmentValueCzk - costBasisForPnl
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
          const avgBuyPriceCzk = quantity > 0 ? costBasisCzk / quantity : 0
          const unrealizedPnlCzk = valueCzk - costBasisCzk
          const unrealizedPnlPct = costBasisCzk > 0 ? (unrealizedPnlCzk / costBasisCzk) * 100 : null

          return {
            id: `${snapshot.accountId}:${item.symbol}`,
            symbol: item.symbol,
            name: item.asset?.name ?? null,
            assetType: item.asset?.assetType ?? "stock",
            quantity,
            avgBuyPrice: avgBuyPriceCzk,
            avgBuyPriceCzk,
            currency: item.costCurrency ?? "CZK",
            accountId: snapshot.accountId,
            accountName: snapshot.account.name,
            currentPrice: toNum(item.pricePerUnit),
            currentPriceCurrency: item.priceCurrency ?? "CZK",
            currentValue: valueCzk,
            currentValueCzk: valueCzk,
            unrealizedPnl: null,
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
  ratesCache = new Map<string, Record<string, number>>()
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

  const snapshot: AccountLedgerSnapshot = { positions: {}, cashValueCzk: 0 }

  for (const event of events) {
    const czkRates = await getCachedHistoricalCzkRates(ratesCache, event.date)
    applyInvestmentEventToLedgerSnapshot(snapshot, event, czkRates)
  }

  return snapshot
}

function positionsValue(
  positions: Record<string, SnapshotPosition>,
  czkRates: Record<string, number>
) {
  return Object.values(positions)
    .filter((position) => position.quantity > 0.000001)
    .reduce((sum, position) => sum + toCzk(position.totalCost, position.currency, czkRates), 0)
}

async function writeImportLog(
  importBatchId: string,
  level: "info" | "warning" | "error",
  event: "snapshots_recalculated" | "snapshot_validation_failed" | "failed",
  message: string
) {
  await prisma.importLog.create({
    data: { importBatchId, level, event, message },
  })
}

export async function createDailyAccountSnapshotsFromImport({
  accountId,
  importBatchId,
  importStartDate,
  validationInterval = 0,
}: {
  accountId: string
  importBatchId: string
  importStartDate?: Date | null
  validationInterval?: number
}) {
  const firstImportedEvent = await prisma.investmentEvent.findFirst({
    where: { accountId, importBatchId },
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

  const accountMovements = await prisma.investmentMovement.findMany({
    where: {
      event: { accountId, deletedAt: null, archivedAt: null },
      kind: "asset",
      sourceSymbol: { not: null },
    },
    select: { sourceSymbol: true, sourceAssetType: true, valueCurrency: true, currency: true },
  })
  const symbolMap = new Map<string, { assetType: string; currency: string }>()
  for (const m of accountMovements) {
    if (m.sourceSymbol && !symbolMap.has(m.sourceSymbol)) {
      symbolMap.set(m.sourceSymbol, {
        assetType: m.sourceAssetType ?? "stock",
        currency: m.valueCurrency ?? m.currency ?? "EUR",
      })
    }
  }
  const symbolDefinitions = [...symbolMap.entries()].map(([symbol, def]) => ({
    symbol,
    assetType: def.assetType,
    currency: def.currency,
  }))
  const [pricesBySymbol, events]: [Record<string, HistoricalPricePoint[]>, LedgerSnapshotEvent[]] =
    await Promise.all([
      symbolDefinitions.length > 0
        ? getHistoricalPrices(symbolDefinitions, firstDate, endOfDay(today))
        : Promise.resolve({}),
      prisma.investmentEvent.findMany({
        where: {
          accountId,
          deletedAt: null,
          archivedAt: null,
          date: { lte: endOfDay(today) },
        },
        include: { movements: true },
        orderBy: { date: "asc" },
      }),
    ])

  const ledgerSnapshot: AccountLedgerSnapshot = { positions: {}, cashValueCzk: 0 }
  let eventIndex = 0

  for (let day = start, dayIndex = 1; day <= today; day = addDays(day, 1), dayIndex += 1) {
    const dayEnd = endOfDay(day)
    const czkRates = await getCachedHistoricalCzkRates(ratesCache, day)

    while (eventIndex < events.length && events[eventIndex].date <= dayEnd) {
      const eventRates = await getCachedHistoricalCzkRates(ratesCache, events[eventIndex].date)
      applyInvestmentEventToLedgerSnapshot(ledgerSnapshot, events[eventIndex], eventRates)
      eventIndex += 1
    }

    const { positions } = ledgerSnapshot

    if (validationInterval > 0 && dayIndex % validationInterval === 0) {
      validations += 1
      const expected = positionsValue(positions, czkRates)
      const actualSnapshot = await calculateAccountLedgerSnapshot(accountId, dayEnd, ratesCache)
      const actual = positionsValue(actualSnapshot.positions, czkRates)
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
      const close = findCloseAtOrBefore(pricesBySymbol[position.symbol] ?? [], day)
      const costBasisCzk = position.totalCost
      const avgCostPerUnit = position.quantity > 0 ? costBasisCzk / position.quantity : 0
      const pricePerUnit = close?.price ?? avgCostPerUnit
      const priceCurrency = close?.currency ?? "CZK"
      const valueCzk = toCzk(pricePerUnit * position.quantity, priceCurrency, czkRates)
      return {
        ...position,
        valueCzk,
        costBasisCzk,
        pricePerUnitCzk: position.quantity > 0 ? valueCzk / position.quantity : 0,
      }
    })
    const investmentValue = items.reduce((sum, item) => sum + item.valueCzk, 0)
    const investmentCostBasis = items.reduce((sum, item) => sum + item.costBasisCzk, 0)
    const cashValue = ledgerSnapshot.cashValueCzk
    const totalValue = investmentValue + cashValue

    await prisma.$transaction(async (tx) => {
      const snapshot = await tx.accountSnapshot.upsert({
        where: {
          accountId_timestamp_currency_granularity: {
            accountId,
            timestamp: day,
            currency: "CZK",
            granularity: "day",
          },
        },
        update: {
          source: "import_event",
          cashValue,
          investmentValue,
          investmentCostBasis,
          totalValue,
          isRecalculated: true,
        },
        create: {
          accountId,
          timestamp: day,
          granularity: "day",
          source: "import_event",
          currency: "CZK",
          cashValue,
          investmentValue,
          investmentCostBasis,
          liabilitiesValue: 0,
          totalValue,
          isRecalculated: true,
        },
      })

      await tx.accountSnapshotItem.deleteMany({ where: { snapshotId: snapshot.id } })
      if (items.length > 0) {
        await tx.accountSnapshotItem.createMany({
          data: items.map((position) => ({
            snapshotId: snapshot.id,
            assetId: position.assetId,
            symbol: position.symbol,
            quantity: position.quantity,
            pricePerUnit: position.pricePerUnitCzk,
            priceCurrency: "CZK",
            value: position.valueCzk,
            costBasis: position.costBasisCzk,
            costCurrency: "CZK",
            allocationPct: investmentValue > 0 ? (position.valueCzk / investmentValue) * 100 : 0,
          })),
        })
      }
    })
    snapshots += 1
  }

  await writeImportLog(
    importBatchId,
    "info",
    "snapshots_recalculated",
    `Created or updated ${snapshots} daily account snapshots for ${accountId}; validations: ${validations}.`
  )

  return { snapshots, validations }
}
