import type { ParsedInvestmentTransaction } from "@/types"
import type { AssetType, InvestmentType } from "@prisma/client"
import type { CsvRow } from "./csv"

export const FIAT_CURRENCIES = new Set(["CZK", "EUR", "USD", "GBP"])

export function isFiatCurrency(currency: string | null | undefined): boolean {
  return Boolean(currency && FIAT_CURRENCIES.has(currency.toUpperCase()))
}

export interface ParsedInvestmentMovementRow {
  raw: CsvRow
  type: InvestmentType | string
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

export function buildStandaloneInvestment(
  row: ParsedInvestmentMovementRow,
  accountId: string,
  assetType: AssetType
): ParsedInvestmentTransaction | null {
  if (!row.date || row.amount === null || !row.currency) return null

  const currency = row.currency.toUpperCase()
  const quantity = Math.abs(row.amount)
  const type = row.type as InvestmentType

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

export function compactInvestmentTransactions(
  transactions: Array<ParsedInvestmentTransaction | null>
): ParsedInvestmentTransaction[] {
  return transactions.filter(
    (transaction): transaction is ParsedInvestmentTransaction => transaction !== null
  )
}
