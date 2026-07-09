import type { ParsedInvestmentEvent } from "@/types"
import type { ParsedInvestmentAction } from "@/types"
import type { AssetType } from "@prisma/client"
import { parseCsvRows, type CsvRow, type ParseCsvRowsOptions } from "./csv"
import {
  createParseResult,
  type ParseIssue,
  type ParseIssueSeverity,
  type ParseResult,
} from "./result"

export const FIAT_CURRENCIES = new Set(["CZK", "EUR", "USD", "GBP"])

export function isFiatCurrency(currency: string | null | undefined): boolean {
  return Boolean(currency && FIAT_CURRENCIES.has(currency.toUpperCase()))
}

export interface ParsedInvestmentMovementRow {
  raw: CsvRow
  type: ParsedInvestmentAction | string
  orderId: string | null
  date: Date | null
  amount: number | null
  currency: string | null
  externalId: string | null
}

export interface OrderRows<T extends ParsedInvestmentMovementRow = ParsedInvestmentMovementRow> {
  payments: T[]
  fills: T[]
  refunds: T[]
}

export type GroupedInvestmentRows<T extends ParsedInvestmentMovementRow> = Record<string, T[]>

export type InvestmentMovementClassification =
  | { kind: "grouped"; groupId: string; bucket: string }
  | { kind: "standalone" }
  | {
      kind: "ignored"
      code: string
      message: string
      severity?: ParseIssueSeverity
    }

export interface GroupedInvestmentParserDefinition<T extends ParsedInvestmentMovementRow> {
  parserName: string
  csv?: ParseCsvRowsOptions
  parseRow: (row: CsvRow) => T
  classifyRow: (row: T) => InvestmentMovementClassification
  buildGroupedTransaction: (
    groupId: string,
    rows: GroupedInvestmentRows<T>,
    accountId: string
  ) => ParsedInvestmentEvent | null
  buildStandaloneTransaction?: (row: T, accountId: string) => ParsedInvestmentEvent | null
  incompleteGroupIssue?: (groupId: string, rows: GroupedInvestmentRows<T>) => ParseIssue
}

export function getOrCreateOrder<T extends ParsedInvestmentMovementRow>(
  orders: Record<string, OrderRows<T>>,
  orderId: string
): OrderRows<T> {
  orders[orderId] ||= { payments: [], fills: [], refunds: [] }
  return orders[orderId]
}

export function sumAmounts(rows: Array<{ amount: number | null }>): number {
  return rows.reduce((sum, row) => sum + (row.amount ?? 0), 0)
}

export function rowsFromBucket<T extends ParsedInvestmentMovementRow>(
  rows: GroupedInvestmentRows<T>,
  bucket: string
): T[] {
  return rows[bucket] ?? []
}

export function buildStandaloneInvestment(
  row: ParsedInvestmentMovementRow,
  accountId: string,
  assetType: AssetType
): ParsedInvestmentEvent | null {
  if (!row.date || row.amount === null || !row.currency) return null

  const currency = row.currency.toUpperCase()
  const quantity = Math.abs(row.amount)
  const type = row.type as ParsedInvestmentAction

  if (isFiatCurrency(currency)) {
    return {
      date: row.date,
      type,
      totalAmount: quantity,
      totalCurrency: currency,
      externalId: row.externalId,
      accountId,
    }
  }

  return {
    date: row.date,
    type,
    symbol: currency,
    assetType,
    quantity,
    externalId: row.externalId,
    accountId,
  }
}

export function compactInvestmentEvents(
  events: Array<ParsedInvestmentEvent | null>
): ParsedInvestmentEvent[] {
  return events.filter((event): event is ParsedInvestmentEvent => event !== null)
}

export function parseGroupedInvestmentCsv<T extends ParsedInvestmentMovementRow>(
  csvText: string,
  accountId: string,
  definition: GroupedInvestmentParserDefinition<T>
): ParseResult<ParsedInvestmentEvent> {
  const rawRows = parseCsvRows(csvText, definition.csv)
  const groups: Record<string, GroupedInvestmentRows<T>> = {}
  const standalone: T[] = []
  const issues: ParseIssue[] = []

  rawRows.forEach((rawRow, index) => {
    const rowNumber = index + 1
    const row = definition.parseRow(rawRow)
    const classification = definition.classifyRow(row)

    if (classification.kind === "grouped") {
      groups[classification.groupId] ||= {}
      groups[classification.groupId][classification.bucket] ||= []
      groups[classification.groupId][classification.bucket].push(row)
      return
    }

    if (classification.kind === "standalone") {
      standalone.push(row)
      return
    }

    issues.push({
      severity: classification.severity ?? "ignored",
      code: classification.code,
      message: classification.message,
      rowNumber,
      raw: rawRow,
    })
  })

  const groupedTransactions = Object.entries(groups).map(([groupId, rows]) => {
    const transaction = definition.buildGroupedTransaction(groupId, rows, accountId)
    if (transaction) return transaction

    issues.push(
      definition.incompleteGroupIssue?.(groupId, rows) ?? {
        severity: "warning",
        code: "incomplete_group",
        message: `${definition.parserName} group ${groupId} could not be converted to an investment transaction.`,
      }
    )

    return null
  })

  const standaloneTransactions = definition.buildStandaloneTransaction
    ? standalone.map((row) => definition.buildStandaloneTransaction?.(row, accountId) ?? null)
    : []

  return createParseResult(
    compactInvestmentEvents([...groupedTransactions, ...standaloneTransactions]),
    rawRows.length,
    issues
  )
}
