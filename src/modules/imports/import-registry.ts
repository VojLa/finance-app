import { prisma } from "@/lib/prisma"
import type { ImportSource } from "@prisma/client"
import type { ParsedInvestmentEvent } from "@/types"
import { autoCategorize } from "@/modules/wallet/transactions/categorize"
import { createInvestmentEvents } from "@/modules/portfolio/ledger/service"
import { recalculateHoldings } from "@/modules/portfolio/positions/calculations"
import { createDailyAccountSnapshotsFromImport, createNetWorthSnapshot } from "@/modules/snapshots"
import { parseRaiffeisenbankResult, type RaiffeisenRow } from "./parsers/banks/raiffeisenbank"
import { parseTrading212Result } from "./parsers/brokers/trading212"
import { parseAnycoinResult } from "./parsers/exchanges/anycoin"
import type { ParseResult } from "./parsers/shared/result"

type ImportRow = ParsedInvestmentEvent | RaiffeisenRow

interface ImportCompletedContext {
  userId: string
  accountId: string
  importBatchId: string
  importStartDate?: Date | null
}

interface ImportDefinition<T extends ImportRow> {
  source: ImportSource
  parse: (content: string, accountId: string) => ParseResult<T>
  fetchExistingIds: (accountId: string) => Promise<Array<{ externalId: string | null }>>
  saveRows: (rows: T[], importBatchId: string) => Promise<void>
  postProcess?: (
    accountId: string
  ) => Promise<{ warnings?: { symbol: string; quantity: number }[] } | void>
  afterCompleted?: (context: ImportCompletedContext) => Promise<unknown>
}

type AnyImportDefinition = ImportDefinition<ImportRow>

function investmentDefinition(
  source: "trading212" | "anycoin",
  parse: (content: string, accountId: string) => ParseResult<ParsedInvestmentEvent>
): ImportDefinition<ParsedInvestmentEvent> {
  return {
    source,
    parse,
    fetchExistingIds: (accountId) =>
      prisma.investmentEvent.findMany({
        where: { accountId, externalId: { not: null } },
        select: { externalId: true },
      }),
    saveRows: async (rows, importBatchId) => {
      await createInvestmentEvents(rows, { importBatchId, source })
    },
    postProcess: (accountId) => recalculateHoldings(accountId),
    afterCompleted: async ({ userId, accountId, importBatchId, importStartDate }) => {
      await createDailyAccountSnapshotsFromImport({ accountId, importBatchId, importStartDate })
      await createNetWorthSnapshot({ userId })
    },
  }
}

export const importDefinitions = {
  trading212: investmentDefinition("trading212", parseTrading212Result),
  anycoin: investmentDefinition("anycoin", parseAnycoinResult),
  raiffeisenbank: {
    source: "raiffeisenbank",
    parse: parseRaiffeisenbankResult,
    fetchExistingIds: (accountId: string) =>
      prisma.transaction.findMany({
        where: { accountId, externalId: { not: null } },
        select: { externalId: true },
      }),
    saveRows: async (rows: RaiffeisenRow[], importBatchId: string) => {
      await prisma.transaction.createMany({
        data: rows.map((row) => ({
          date: row.date,
          amount: row.amount,
          currency: row.currency,
          type: row.type,
          description: row.description || null,
          counterparty: row.counterparty || null,
          externalId: row.externalId || null,
          accountId: row.accountId,
          importBatchId,
        })),
      })
    },
    postProcess: (accountId: string) => autoCategorize(accountId),
    afterCompleted: ({ userId }) => createNetWorthSnapshot({ userId }),
  } satisfies ImportDefinition<RaiffeisenRow>,
  manual: null,
} as Record<ImportSource, AnyImportDefinition | null>

export function getImportDefinition(source: ImportSource): AnyImportDefinition {
  const definition = importDefinitions[source]
  if (!definition) throw new Error(`Unsupported import source: ${source}`)
  return definition
}
