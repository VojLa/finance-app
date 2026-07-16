import type { ParsedInvestmentEvent } from "@/types"
import { AssetType } from "@prisma/client"
import { get, normalizeText, type CsvRow } from "../shared/csv"
import { parseNum } from "../shared/number"
import { latestDate, parseIsoDate } from "../shared/date"
import {
  buildStandaloneInvestment,
  parseGroupedInvestmentCsv,
  isFiatCurrency,
  rowsFromBucket,
  sumAmounts,
  type GroupedInvestmentParserDefinition,
  type GroupedInvestmentRows,
  type InvestmentMovementClassification,
  type ParsedInvestmentMovementRow,
} from "../shared/investment"
import type { ParseResult } from "../shared/result"

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
  order: GroupedInvestmentRows<ParsedRow>,
  accountId: string
): ParsedInvestmentEvent | null {
  const payments = rowsFromBucket(order, "payments")
  const fills = rowsFromBucket(order, "fills")
  const refunds = rowsFromBucket(order, "refunds")

  if (payments.length === 0 || fills.length === 0) return null

  const rows = [...payments, ...fills, ...refunds]
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
  const date = latestDate(fills.map((row) => row.date)) ?? latestDate(rows.map((row) => row.date))
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
    externalId: assetRow.externalId || fills[0]?.externalId || payments[0]?.externalId || orderId,
    accountId,
  } satisfies ParsedInvestmentEvent
}

function buildStandalone(row: ParsedRow, accountId: string): ParsedInvestmentEvent | null {
  if (row.type !== "deposit" && row.type !== "withdrawal") return null
  return buildStandaloneInvestment(row, accountId, AssetType.crypto)
}

function classifyRow(row: ParsedRow): InvestmentMovementClassification {
  if (row.type === "trade payment" && row.orderId) {
    return { kind: "grouped", groupId: row.orderId, bucket: "payments" }
  }

  if (row.type === "trade fill" && row.orderId) {
    return { kind: "grouped", groupId: row.orderId, bucket: "fills" }
  }

  if (row.type === "trade refund" && row.orderId) {
    return { kind: "grouped", groupId: row.orderId, bucket: "refunds" }
  }

  if (row.type === "deposit" || row.type === "withdrawal") {
    return { kind: "standalone" }
  }

  if (
    row.type === "payment block" ||
    row.type === "payment block refund" ||
    row.type === "withdrawal_block" ||
    row.type === "withdrawal_unblock"
  ) {
    return {
      kind: "ignored",
      code: "temporary_block",
      message: "Temporary block/unblock row does not change the final position.",
    }
  }

  return {
    kind: "ignored",
    code: "unsupported_anycoin_row",
    message: `Unsupported Anycoin row type: ${row.type || "unknown"}.`,
  }
}

function groupSummary(rows: ParsedRow[]) {
  if (rows.length === 0) return "none"
  return rows
    .map((row) => `${row.type || "unknown"} ${row.amount ?? "?"} ${row.currency ?? "?"}`)
    .join(", ")
}

function isFullyRefundedOrder(rows: GroupedInvestmentRows<ParsedRow>) {
  const payments = rowsFromBucket(rows, "payments")
  const fills = rowsFromBucket(rows, "fills")
  const refunds = rowsFromBucket(rows, "refunds")
  const allRows = [...payments, ...refunds]
  if (payments.length === 0 || refunds.length === 0 || fills.length > 0) return false

  const currencies = new Set(allRows.map((row) => row.currency).filter(Boolean))
  for (const currency of currencies) {
    const net = sumAmounts(allRows.filter((row) => row.currency === currency))
    if (Math.abs(net) > 0.00000001) return false
  }

  return true
}

const PARSER: GroupedInvestmentParserDefinition<ParsedRow> = {
  parserName: "Anycoin",
  parseRow,
  classifyRow,
  buildGroupedTransaction: buildTrade,
  buildStandaloneTransaction: buildStandalone,
  incompleteGroupIssue: (orderId, rows) => {
    if (isFullyRefundedOrder(rows)) return null

    return {
      severity: "warning",
      code: "incomplete_order",
      message:
        `Anycoin order ${orderId} could not be converted to an investment transaction. ` +
        `Payments: ${groupSummary(rowsFromBucket(rows, "payments"))}. ` +
        `Fills: ${groupSummary(rowsFromBucket(rows, "fills"))}. ` +
        `Refunds: ${groupSummary(rowsFromBucket(rows, "refunds"))}.`,
      raw:
        rowsFromBucket(rows, "payments")[0]?.raw ??
        rowsFromBucket(rows, "fills")[0]?.raw ??
        rowsFromBucket(rows, "refunds")[0]?.raw,
    }
  },
}

export function parseAnycoinResult(
  csvText: string,
  accountId: string
): ParseResult<ParsedInvestmentEvent> {
  return parseGroupedInvestmentCsv(csvText, accountId, PARSER)
}

export function parseAnycoin(csvText: string, accountId: string): ParsedInvestmentEvent[] {
  return parseAnycoinResult(csvText, accountId).rows
}
