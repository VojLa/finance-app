import type { Prisma } from "@prisma/client"
import { prisma } from "@/lib/prisma"
import type { ParsedInvestmentEvent } from "@/types"
import type { PriceSource } from "@prisma/client"

type Db = Prisma.TransactionClient
type InvestmentEventOptions = {
  importBatchId?: string | null
  source?: "trading212" | "anycoin" | "manual"
}
type AssetListingWithAsset = Prisma.AssetListingGetPayload<{ include: { asset: true } }>

function absOrNull(value: number | null | undefined): number | null {
  if (value == null) return null
  return Math.abs(value)
}

function isAssetAction(row: ParsedInvestmentEvent): boolean {
  return Boolean(row.symbol && row.quantity != null && hasAssetMovement(row))
}

function eventTypeFor(row: ParsedInvestmentEvent) {
  if (row.type === "buy" || row.type === "sell") return "trade"
  if (row.type === "deposit") return isAssetAction(row) ? "asset_transfer" : "cash_deposit"
  if (row.type === "withdrawal") return isAssetAction(row) ? "asset_transfer" : "cash_withdrawal"
  if (row.type === "transfer") return "asset_transfer"
  return row.type
}

function listingProviderForSource(source?: "trading212" | "anycoin" | "manual"): PriceSource {
  if (source === "anycoin") return "exchange"
  return "broker"
}

function listingCurrencyFor(row: ParsedInvestmentEvent, symbol: string) {
  if (row.assetType === "crypto") return symbol
  return row.priceCurrency || row.totalCurrency || symbol
}

function assetCurrencyFor(row: ParsedInvestmentEvent, symbol: string, listingCurrency: string) {
  if (row.assetType === "crypto") return symbol
  return listingCurrency
}

async function findOrCreateAssetListing(
  tx: Db,
  row: ParsedInvestmentEvent,
  source?: "trading212" | "anycoin" | "manual",
  cache?: Map<string, AssetListingWithAsset>
) {
  if (!row.symbol || !row.assetType) return null

  const symbol = row.symbol.toUpperCase()
  const currency = listingCurrencyFor(row, symbol)
  const assetCurrency = assetCurrencyFor(row, symbol, currency)
  const exchange = source ?? "manual"
  const provider = listingProviderForSource(source)
  const providerSymbol = symbol
  const cacheKey = `${provider}:${providerSymbol}:${currency}:${exchange}:${row.assetType}:${row.isin ?? ""}`
  const cached = cache?.get(cacheKey)
  if (cached) return cached

  const remember = (listing: AssetListingWithAsset) => {
    cache?.set(cacheKey, listing)
    return listing
  }

  const existingByProvider = await tx.assetListing.findUnique({
    where: {
      provider_providerSymbol_currency: {
        provider,
        providerSymbol,
        currency,
      },
    },
    include: { asset: true },
  })
  if (existingByProvider) {
    if (existingByProvider.asset.currency !== assetCurrency) {
      await tx.asset.update({
        where: { id: existingByProvider.assetId },
        data: { currency: assetCurrency },
      })
    }

    if (!existingByProvider.exchange || existingByProvider.exchange === "legacy") {
      return remember(
        await tx.assetListing.update({
          where: { id: existingByProvider.id },
          data: { exchange },
          include: { asset: true },
        })
      )
    }

    return remember(existingByProvider)
  }

  const existingListing = await tx.assetListing.findFirst({
    where: {
      symbol,
      exchange,
      currency,
    },
    include: { asset: true },
  })
  if (existingListing) {
    if (existingListing.asset.currency !== assetCurrency) {
      await tx.asset.update({
        where: { id: existingListing.assetId },
        data: { currency: assetCurrency },
      })
    }

    return remember(existingListing)
  }

  const existingAsset = row.isin
    ? await tx.asset.findFirst({ where: { isin: row.isin } })
    : await tx.asset.findFirst({ where: { symbol, assetType: row.assetType } })

  const asset = existingAsset
    ? existingAsset.currency !== assetCurrency
      ? await tx.asset.update({
          where: { id: existingAsset.id },
          data: { currency: assetCurrency },
        })
      : existingAsset
    : await tx.asset.create({
        data: {
          symbol,
          isin: row.isin || null,
          name: row.name || symbol,
          assetType: row.assetType,
          currency: assetCurrency,
        },
      })

  return remember(
    await tx.assetListing.create({
      data: {
        asset: { connect: { id: asset.id } },
        symbol,
        exchange,
        currency,
        provider,
        providerSymbol,
        isPrimary: true,
      },
      include: { asset: true },
    })
  )
}

function movementNote(row: ParsedInvestmentEvent) {
  return row.orderId ? `Order ${row.orderId}` : null
}

function shouldCreateFeeMovement(
  row: ParsedInvestmentEvent,
  source?: "trading212" | "anycoin" | "manual"
) {
  if (row.isPromotional) return false
  if (source === "trading212" && (row.type === "buy" || row.type === "sell")) return false
  return true
}

function hasAssetMovement(row: ParsedInvestmentEvent) {
  return ["buy", "sell", "deposit", "withdrawal", "staking_reward", "airdrop", "transfer"].includes(
    row.type
  )
}

function movementData(
  row: ParsedInvestmentEvent,
  asset: { id: string; assetId: string } | null,
  source?: "trading212" | "anycoin" | "manual"
) {
  const qty = absOrNull(row.quantity)
  const total = absOrNull(row.totalAmount)
  const pricePerUnit = row.pricePerUnit ?? (qty && total ? total / qty : null)
  const priceCurrency = row.priceCurrency || row.totalCurrency || null
  const movements: Prisma.InvestmentMovementCreateWithoutEventInput[] = []

  if (row.symbol && qty != null && qty > 0 && hasAssetMovement(row)) {
    const assetIn = ["buy", "deposit", "staking_reward", "airdrop", "transfer"].includes(row.type)
    movements.push({
      account: { connect: { id: row.accountId } },
      asset: asset ? { connect: { id: asset.assetId } } : undefined,
      listing: asset ? { connect: { id: asset.id } } : undefined,
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
    const cashIn = ["sell", "deposit", "dividend", "interest"].includes(row.type)
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

  const fee = shouldCreateFeeMovement(row, source) ? absOrNull(row.fee) : null
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

async function createInvestmentEventInTransaction(
  tx: Db,
  row: ParsedInvestmentEvent,
  options: InvestmentEventOptions = {},
  listingCache?: Map<string, AssetListingWithAsset>
) {
  const listing = await findOrCreateAssetListing(tx, row, options.source, listingCache)
  const movements = movementData(
    row,
    listing ? { id: listing.id, assetId: listing.assetId } : null,
    options.source
  )

  return tx.investmentEvent.create({
    data: {
      account: { connect: { id: row.accountId } },
      type: eventTypeFor(row),
      date: row.date,
      source: options.source ?? "manual",
      externalId: row.externalId || null,
      orderId: row.orderId || null,
      description: row.name || row.symbol || row.note || row.rawAction || null,
      importBatch: options.importBatchId ? { connect: { id: options.importBatchId } } : undefined,
      realizedPnl: row.realizedPnl ?? null,
      realizedPnlCurrency: row.realizedPnlCurrency || null,
      movements: { create: movements },
    },
    include: { movements: true },
  })
}

export async function createInvestmentEvent(
  row: ParsedInvestmentEvent,
  options: InvestmentEventOptions = {}
) {
  return prisma.$transaction((tx) => createInvestmentEventInTransaction(tx, row, options))
}

export async function createInvestmentEvents(
  rows: ParsedInvestmentEvent[],
  options: InvestmentEventOptions = {}
) {
  if (rows.length === 0) return

  await prisma.$transaction(
    async (tx) => {
      const listingCache = new Map<string, AssetListingWithAsset>()
      for (const row of rows) {
        await createInvestmentEventInTransaction(tx, row, options, listingCache)
      }
    },
    { timeout: 60_000 }
  )
}
