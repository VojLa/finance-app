import { prisma, toNum } from "@/lib/prisma"
import { getCzkRates, getLivePrices, toCzk } from "@/modules/portfolio/rates/service"
import type { PortfolioSnapshotSource, SnapshotGranularity } from "@prisma/client"

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

async function getAccessibleAccountIds(userId: string) {
  const accounts = await prisma.account.findMany({
    where: { userId },
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
    select: { type: true, amount: true, amountCzk: true, currency: true },
  })

  return txs.reduce((sum, tx) => {
    const amountCzk = tx.amountCzk
      ? toNum(tx.amountCzk)
      : toCzk(toNum(tx.amount), tx.currency, czkRates)
    return sum + (tx.type === "income" ? amountCzk : -amountCzk)
  }, 0)
}

export async function createPortfolioSnapshot({
  userId,
  source,
  granularity = "minute",
  timestamp = new Date(),
}: {
  userId: string
  source: PortfolioSnapshotSource
  granularity?: SnapshotGranularity
  timestamp?: Date
}) {
  const bucket = bucketTimestamp(timestamp, granularity)
  const accounts = await prisma.account.findMany({
    where: { userId, type: { in: Array.from(INVESTMENT_ACCOUNT_TYPES) as never } },
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

  const items = holdings
    .map((holding) => {
      const price = prices[holding.symbol]
      const quantity = toNum(holding.quantity)
      const pricePerUnit = price?.price ?? toNum(holding.avgBuyPrice)
      const priceCurrency = price?.currency ?? holding.currency
      const value = toCzk(pricePerUnit * quantity, priceCurrency, czkRates)

      return {
        assetId: holding.assetId,
        symbol: holding.symbol,
        accountId: holding.accountId,
        quantity,
        pricePerUnit,
        value,
      }
    })
    .filter((item) => item.quantity > 0 && item.value > 0)

  const totalValue = items.reduce((sum, item) => sum + item.value, 0)

  const snapshot = await prisma.$transaction(async (tx) => {
    const saved = await tx.portfolioSnapshot.upsert({
      where: {
        userId_timestamp_currency_granularity: {
          userId,
          timestamp: bucket,
          currency: "CZK",
          granularity,
        },
      },
      update: {
        source,
        totalValue,
        isRecalculated: source === "manual_recalculation",
      },
      create: {
        userId,
        timestamp: bucket,
        granularity,
        source,
        currency: "CZK",
        totalValue,
        isRecalculated: source === "manual_recalculation",
      },
    })

    await tx.portfolioSnapshotItem.deleteMany({ where: { snapshotId: saved.id } })

    if (items.length > 0) {
      await tx.portfolioSnapshotItem.createMany({
        data: items.map((item) => ({
          snapshotId: saved.id,
          assetId: item.assetId,
          symbol: item.symbol,
          accountId: item.accountId,
          quantity: item.quantity,
          pricePerUnit: item.pricePerUnit,
          value: item.value,
          allocationPct: totalValue > 0 ? (item.value / totalValue) * 100 : 0,
        })),
      })
    }

    return saved
  })

  return snapshot
}

export async function createNetWorthSnapshot({
  userId,
  timestamp = new Date(),
}: {
  userId: string
  timestamp?: Date
}) {
  const date = bucketTimestamp(timestamp, "day")
  const czkRates = await getCzkRates()
  const accountIds = await getAccessibleAccountIds(userId)
  const [cashValue, liabilitiesValue, portfolioSnapshot] = await Promise.all([
    calculateAccountValueCzk(accountIds.cash, czkRates),
    calculateAccountValueCzk(accountIds.liabilities, czkRates),
    createPortfolioSnapshot({ userId, source: "scheduled", granularity: "day", timestamp }),
  ])

  const portfolioValue = toNum(portfolioSnapshot.totalValue)

  return prisma.netWorthSnapshot.upsert({
    where: { userId_date_currency: { userId, date, currency: "CZK" } },
    update: {
      cashValue,
      portfolioValue,
      liabilitiesValue,
      totalNetWorth: cashValue + portfolioValue - liabilitiesValue,
    },
    create: {
      userId,
      date,
      currency: "CZK",
      cashValue,
      portfolioValue,
      liabilitiesValue,
      totalNetWorth: cashValue + portfolioValue - liabilitiesValue,
    },
  })
}

export async function getPortfolioSnapshotHistory({
  userId,
  accountId,
}: {
  userId: string
  accountId?: string | null
}) {
  let snapshots = await prisma.portfolioSnapshot.findMany({
    where: { userId, currency: "CZK" },
    include: {
      items: {
        where: accountId ? { accountId } : undefined,
        orderBy: { allocationPct: "desc" },
      },
    },
    orderBy: { timestamp: "asc" },
  })

  if (snapshots.length === 0) {
    await createPortfolioSnapshot({ userId, source: "manual_recalculation", granularity: "minute" })
    snapshots = await prisma.portfolioSnapshot.findMany({
      where: { userId, currency: "CZK" },
      include: {
        items: {
          where: accountId ? { accountId } : undefined,
          orderBy: { allocationPct: "desc" },
        },
      },
      orderBy: { timestamp: "asc" },
    })
  }

  return snapshots.map((snapshot) => {
    const valueCzk = accountId
      ? snapshot.items.reduce((sum, item) => sum + toNum(item.value), 0)
      : toNum(snapshot.totalValue)

    return {
      timestamp: snapshot.timestamp,
      month: monthKey(snapshot.timestamp),
      label: snapshot.timestamp.toLocaleDateString("cs-CZ", {
        month: "short",
        year: "numeric",
      }),
      valueCzk: Math.round(valueCzk),
      allocations: snapshot.items.map((item) => ({
        symbol: item.symbol,
        accountId: item.accountId,
        valueCzk: toNum(item.value),
        allocationPct: toNum(item.allocationPct),
      })),
    }
  })
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
    orderBy: { date: "asc" },
  })

  if (snapshots.length === 0) {
    await createNetWorthSnapshot({ userId })
    snapshots = await prisma.netWorthSnapshot.findMany({
      where: { userId, currency: "CZK" },
      orderBy: { date: "asc" },
    })
  }

  return snapshots.map((snapshot) => ({
    month: monthKey(snapshot.date),
    label: snapshot.date.toLocaleDateString("cs-CZ", {
      month: "short",
      year: "numeric",
    }),
    cashCzk: Math.round(toNum(snapshot.cashValue)),
    investedCzk: Math.round(toNum(snapshot.portfolioValue)),
    netWorthCzk: Math.round(toNum(snapshot.totalNetWorth)),
  }))
}
