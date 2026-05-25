import type { ParsedInvestmentTransaction } from "@/types"
import { AssetType } from "@prisma/client"
import { get, normalizeText, parseCsvRows, type CsvRow } from "../shared/csv"
import { parseNum } from "../shared/number"
import { latestDate, parseIsoDate } from "../shared/date"
import {
  compactInvestmentTransactions,
  getOrCreateOrder,
  isFiatCurrency,
  sumAmounts,
  type OrderRows,
  type ParsedInvestmentMovementRow,
} from "../shared/investment"
import { createParseResult, type ParseIssue, type ParseResult } from "../shared/result"

type ParsedRow = ParsedInvestmentMovementRow

function parseRow(row: CsvRow): ParsedRow {
  return {
    raw: row,
    type: normalizeText(get(row, ["Type", "Operation", "Transaction type"])),
    orderId: get(row, ["Order ID", "Order id", "OrderId", "Order"]) || null,
    date: parseIsoDate(get(row, ["Date", "Time", "Created at"])),
    amount: parseNum(get(row, ["Amount", "Quantity"])),
    currency: get(row, ["Currency", "Asset"])?.toUpperCase() || null,
    externalId: get(row, ["anycoin TX ID", "Transaction ID", "TX ID"]) || null,
  }
}

function buildTrade(
  orderId: string,
  order: OrderRows<ParsedRow>,
  accountId: string
): ParsedInvestmentTransaction | null {
  if (order.payments.length === 0 || order.fills.length === 0) return null

  const rows = [...order.payments, ...order.fills, ...order.refunds]
  const assetRows = rows.filter((row) => row.currency && !isFiatCurrency(row.currency))
  const cashRows = rows.filter((row) => row.currency && isFiatCurrency(row.currency))
  if (assetRows.length === 0 || cashRows.length === 0) return null

  const assetNet = sumAmounts(assetRows)
  const cashNet = sumAmounts(cashRows)
  const quantity = Math.abs(assetNet)
  const totalAmount = Math.abs(cashNet)
  if (quantity === 0 || totalAmount === 0) return null

  const assetRow = assetRows.find((row) => row.amount && row.amount !== 0) ?? assetRows[0]
  const cashRow = cashRows.find((row) => row.amount && row.amount !== 0) ?? cashRows[0]
  const date =
    latestDate(order.fills.map((row) => row.date)) ?? latestDate(rows.map((row) => row.date))
  if (!assetRow.currency || !cashRow.currency || !date) return null

  return {
    date,
    type: assetNet > 0 ? "buy" : "sell",
    symbol: assetRow.currency,
    assetType: "crypto",
    quantity,
    pricePerUnit: totalAmount / quantity,
    priceCurrency: cashRow.currency,
    totalAmount,
    totalCurrency: cashRow.currency,
    orderId,
    externalId:
      assetRow.externalId || order.fills[0]?.externalId || order.payments[0]?.externalId || orderId,
    accountId,
  } satisfies ParsedInvestmentTransaction
}

function buildStandalone(row: ParsedRow, accountId: string): ParsedInvestmentTransaction | null {
  if (row.type !== "deposit" && row.type !== "withdrawal") return null
  if (!row.date || row.amount === null || !row.currency) return null

  const currency = row.currency.toUpperCase()
  const quantity = Math.abs(row.amount)

  if (isFiatCurrency(currency)) {
    return {
      date: row.date,
      type: row.type,
      totalAmount: quantity,
      totalCurrency: currency,
      externalId: row.externalId,
      accountId,
    }
  }

  return {
    date: row.date,
    type: row.type,
    symbol: currency,
    assetType: AssetType.crypto,
    quantity,
    externalId: row.externalId,
    accountId,
  }
}

export function parseAnycoinResult(
  csvText: string,
  accountId: string
): ParseResult<ParsedInvestmentTransaction> {
  const rawRows = parseCsvRows(csvText)
  const orders: Record<string, OrderRows<ParsedRow>> = {}
  const standalone: ParsedRow[] = []
  const issues: ParseIssue[] = []

  rawRows.forEach((rawRow, index) => {
    const rowNumber = index + 1
    const row = parseRow(rawRow)

    if (row.type === "trade payment" && row.orderId) {
      getOrCreateOrder(orders, row.orderId).payments.push(row)
    } else if (row.type === "trade fill" && row.orderId) {
      getOrCreateOrder(orders, row.orderId).fills.push(row)
    } else if (row.type === "deposit" || row.type === "withdrawal") {
      standalone.push(row)
    } else if (row.type === "trade refund" && row.orderId) {
      getOrCreateOrder(orders, row.orderId).refunds.push(row)
    } else if (
      row.type === "payment block" ||
      row.type === "payment block refund" ||
      row.type === "withdrawal_block" ||
      row.type === "withdrawal_unblock"
    ) {
      issues.push({
        severity: "ignored",
        code: "temporary_block",
        message: "Temporary block/unblock row does not change the final position.",
        rowNumber,
        raw: rawRow,
      })
    } else {
      issues.push({
        severity: "ignored",
        code: "unsupported_anycoin_row",
        message: `Unsupported Anycoin row type: ${row.type || "unknown"}.`,
        rowNumber,
        raw: rawRow,
      })
    }
  })

  const trades: Array<ParsedInvestmentTransaction | null> = []
  for (const [orderId, order] of Object.entries(orders)) {
    const trade = buildTrade(orderId, order, accountId)
    if (trade) {
      trades.push(trade)
    } else {
      issues.push({
        severity: "warning",
        code: "incomplete_order",
        message: `Anycoin order ${orderId} could not be converted to an investment transaction.`,
      })
    }
  }

  const standaloneResult: Array<ParsedInvestmentTransaction | null> = []
  for (const row of standalone) {
    standaloneResult.push(buildStandalone(row, accountId))
  }

  return createParseResult(
    compactInvestmentTransactions([...trades, ...standaloneResult]),
    rawRows.length,
    issues
  )
}

export function parseAnycoin(csvText: string, accountId: string): ParsedInvestmentTransaction[] {
  return parseAnycoinResult(csvText, accountId).rows
}
