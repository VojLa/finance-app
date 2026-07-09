import type { Prisma } from "@prisma/client"
import { prisma } from "@/lib/prisma"
import type { ParsedInvestmentEvent } from "@/types"

type Db = Prisma.TransactionClient

function absOrNull(value: number | null | undefined): number | null {
  if (value == null) return null
  return Math.abs(value)
}

function isAssetAction(row: ParsedInvestmentEvent): boolean {
  return Boolean(row.symbol && row.quantity != null)
}

function eventTypeFor(row: ParsedInvestmentEvent) {
  if (row.type === "buy" || row.type === "sell") return "trade"
  if (row.type === "deposit") return isAssetAction(row) ? "asset_transfer" : "cash_deposit"
  if (row.type === "withdrawal") return isAssetAction(row) ? "asset_transfer" : "cash_withdrawal"
  if (row.type === "transfer") return "asset_transfer"
  return row.type
}

async function findOrCreateAsset(tx: Db, row: ParsedInvestmentEvent) {
  if (!row.symbol || !row.assetType) return null

  const symbol = row.symbol.toUpperCase()
  const existing = await tx.asset.findUnique({ where: { symbol } })
  if (existing) return existing

  return tx.asset.create({
    data: {
      symbol,
      isin: row.isin || null,
      name: row.name || symbol,
      assetType: row.assetType,
      currency: row.priceCurrency || row.totalCurrency || symbol,
      listings: row.priceCurrency
        ? {
            create: {
              symbol,
              currency: row.priceCurrency,
              isPrimary: true,
            },
          }
        : undefined,
    },
  })
}

function movementNote(row: ParsedInvestmentEvent) {
  return row.orderId ? `Order ${row.orderId}` : null
}

function movementData(row: ParsedInvestmentEvent, assetId: string | null) {
  const qty = absOrNull(row.quantity)
  const total = absOrNull(row.totalAmount)
  const pricePerUnit = row.pricePerUnit ?? (qty && total ? total / qty : null)
  const priceCurrency = row.priceCurrency || row.totalCurrency || null
  const movements: Prisma.InvestmentMovementCreateWithoutEventInput[] = []

  if (row.symbol && qty != null && qty > 0) {
    const assetIn = ["buy", "deposit", "staking_reward", "airdrop", "transfer"].includes(row.type)
    movements.push({
      account: { connect: { id: row.accountId } },
      asset: assetId ? { connect: { id: assetId } } : undefined,
      kind: "asset",
      direction: assetIn ? "in" : "out",
      quantity: qty,
      currency: row.symbol.toUpperCase(),
      pricePerUnit,
      valueAmount: total,
      valueCurrency: row.totalCurrency || priceCurrency,
      sourceSymbol: row.symbol.toUpperCase(),
      sourceAssetType: row.assetType || undefined,
      note: movementNote(row),
    })
  }

  if (total != null && total > 0 && row.totalCurrency) {
    const cashIn = ["sell", "deposit", "dividend", "interest", "staking_reward", "airdrop"].includes(
      row.type
    )
    const cashOut = ["buy", "withdrawal", "fee"].includes(row.type)

    if (cashIn || cashOut) {
      movements.push({
        account: { connect: { id: row.accountId } },
        kind: row.type === "fee" ? "fee" : "cash",
        direction: cashIn ? "in" : "out",
        quantity: total,
        currency: row.totalCurrency,
        valueAmount: total,
        valueCurrency: row.totalCurrency,
        note: movementNote(row),
      })
    }
  }

  if (
    row.type === "currency_conversion" &&
    row.conversionFromAmount != null &&
    row.conversionFromAmount > 0 &&
    row.conversionFromCurrency &&
    row.conversionToAmount != null &&
    row.conversionToAmount > 0 &&
    row.conversionToCurrency
  ) {
    movements.push(
      {
        account: { connect: { id: row.accountId } },
        kind: "cash",
        direction: "out",
        quantity: row.conversionFromAmount,
        currency: row.conversionFromCurrency,
        valueAmount: row.conversionFromAmount,
        valueCurrency: row.conversionFromCurrency,
        note: movementNote(row),
      },
      {
        account: { connect: { id: row.accountId } },
        kind: "cash",
        direction: "in",
        quantity: row.conversionToAmount,
        currency: row.conversionToCurrency,
        valueAmount: row.conversionToAmount,
        valueCurrency: row.conversionToCurrency,
        note: movementNote(row),
      }
    )
  }

  const fee = absOrNull(row.fee)
  if (fee != null && fee > 0 && row.feeCurrency) {
    movements.push({
      account: { connect: { id: row.accountId } },
      kind: "fee",
      direction: "out",
      quantity: fee,
      currency: row.feeCurrency,
      valueAmount: fee,
      valueCurrency: row.feeCurrency,
      note: movementNote(row),
    })
  }

  return movements
}

export async function createInvestmentEvent(
  row: ParsedInvestmentEvent,
  options: { importBatchId?: string | null; source?: "trading212" | "anycoin" | "manual" } = {}
) {
  return prisma.$transaction(async (tx) => {
    const asset = await findOrCreateAsset(tx, row)
    const movements = movementData(row, asset?.id ?? null)

    return tx.investmentEvent.create({
      data: {
        account: { connect: { id: row.accountId } },
        type: eventTypeFor(row),
        date: row.date,
        source: options.source ?? "manual",
        externalId: row.externalId || null,
        orderId: row.orderId || null,
        description: row.name || row.symbol || null,
        importBatch: options.importBatchId
          ? { connect: { id: options.importBatchId } }
          : undefined,
        realizedPnl: row.realizedPnl ?? null,
        realizedPnlCurrency: row.realizedPnlCurrency || null,
        movements: { create: movements },
      },
      include: { movements: true },
    })
  })
}

export async function createInvestmentEvents(
  rows: ParsedInvestmentEvent[],
  options: { importBatchId?: string | null; source?: "trading212" | "anycoin" | "manual" } = {}
) {
  for (const row of rows) {
    await createInvestmentEvent(row, options)
  }
}
