import crypto from "crypto"
import { prisma } from "@/lib/prisma"
import type { ImportSource } from "@prisma/client"
import { parseTrading212 } from "./parsers/brokers/trading212"
import { parseRaiffeisenbank } from "./parsers/banks/raiffeisenbank"
import { parseAnycoin } from "./parsers/exchanges/anycoin"
import { recalculateHoldings } from "@/modules/portfolio/positions/calculations"
import { autoCategorize } from "@/modules/wallet/transactions/categorize"

export class DuplicateImportError extends Error {
  constructor(message = "Tento soubor byl již importován") {
    super(message)
    this.name = "DuplicateImportError"
  }
}

export interface ImportResult {
  imported: number
  skipped: number
  warnings: { symbol: string; quantity: number }[]
}

export async function importCsv({
  content,
  filename,
  accountId,
  userId,
  source,
}: {
  content: string
  filename: string
  accountId: string
  userId: string
  source: ImportSource
}): Promise<ImportResult> {
  const checksum = crypto.createHash("sha256").update(content).digest("hex")

  const existing = await prisma.importBatch.findUnique({ where: { checksum } })
  if (existing) throw new DuplicateImportError()

  let result: ImportResult

  switch (source) {
    case "trading212":
      result = await importTrading212(content, accountId)
      break
    case "raiffeisenbank":
      result = await importRaiffeisenbank(content, accountId)
      break
    case "anycoin":
      result = await importAnycoin(content, accountId)
      break
    default:
      throw new Error(`Nepodporovaný zdroj: ${source}`)
  }

  await prisma.importBatch.create({
    data: {
      checksum,
      filename,
      source,
      accountId,
      userId,
      rowCount: result.imported + result.skipped,
    },
  })

  return result
}

async function importTrading212(csvText: string, accountId: string): Promise<ImportResult> {
  const transactions = parseTrading212(csvText, accountId)

  const existingIds = new Set(
    (await prisma.investmentTransaction.findMany({
      where: { accountId, externalId: { not: null } },
      select: { externalId: true },
    })).map(t => t.externalId)
  )

  const newTransactions = transactions.filter(
    t => !t.externalId || !existingIds.has(t.externalId)
  )

  let warnings: { symbol: string; quantity: number }[] = []
  if (newTransactions.length > 0) {
    await prisma.investmentTransaction.createMany({ data: newTransactions })
    const result = await recalculateHoldings(accountId)
    warnings = result.warnings
  }

  return {
    imported: newTransactions.length,
    skipped: transactions.length - newTransactions.length,
    warnings,
  }
}

async function importRaiffeisenbank(csvText: string, accountId: string): Promise<ImportResult> {
  const rows = parseRaiffeisenbank(csvText, accountId)

  const existingRefs = new Set(
    (await prisma.transaction.findMany({
      where: { accountId, transactionRef: { not: null } },
      select: { transactionRef: true },
    })).map(t => t.transactionRef)
  )

  const newRows = rows.filter(r => !r.transactionRef || !existingRefs.has(r.transactionRef))

  if (newRows.length > 0) {
    await prisma.transaction.createMany({
      data: newRows.map(r => ({
        date: r.date,
        amount: r.amount,
        currency: r.currency,
        type: r.type,
        description: r.description || null,
        counterparty: r.counterparty || null,
        transactionRef: r.transactionRef || null,
        accountId: r.accountId,
      })),
    })
    await autoCategorize(accountId)
  }

  return {
    imported: newRows.length,
    skipped: rows.length - newRows.length,
    warnings: [],
  }
}

async function importAnycoin(csvText: string, accountId: string): Promise<ImportResult> {
  const transactions = parseAnycoin(csvText, accountId)

  const existingIds = new Set(
    (await prisma.investmentTransaction.findMany({
      where: { accountId, externalId: { not: null } },
      select: { externalId: true },
    })).map(t => t.externalId)
  )

  const newTransactions = transactions.filter(
    t => !t.externalId || !existingIds.has(t.externalId)
  )

  let warnings: { symbol: string; quantity: number }[] = []
  if (newTransactions.length > 0) {
    await prisma.investmentTransaction.createMany({ data: newTransactions })
    const result = await recalculateHoldings(accountId)
    warnings = result.warnings
  }

  return {
    imported: newTransactions.length,
    skipped: transactions.length - newTransactions.length,
    warnings,
  }
}
