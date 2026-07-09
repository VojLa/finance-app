import { describe, expect, it } from "vitest"
import {
  buildStandaloneInvestment,
  parseGroupedInvestmentCsv,
  rowsFromBucket,
  type ParsedInvestmentMovementRow,
} from "./investment"
import { get, normalizeText, type CsvRow } from "./csv"
import { parseIsoDate } from "./date"
import { parseNum } from "./number"

function parseMovement(row: CsvRow): ParsedInvestmentMovementRow {
  return {
    raw: row,
    type: normalizeText(get(row, ["Type"])),
    orderId: get(row, ["Order ID"]) || null,
    date: parseIsoDate(get(row, ["Date"])),
    amount: parseNum(get(row, ["Amount"])),
    currency: get(row, ["Currency"])?.toUpperCase() || null,
    externalId: get(row, ["ID"]) || null,
  }
}

describe("parseGroupedInvestmentCsv", () => {
  it("parses grouped, standalone, and ignored movement rows", () => {
    const csv = [
      "Type,Order ID,Date,Amount,Currency,ID",
      "payment,order-1,2026-06-14T10:00:00.000Z,-100,CZK,payment-1",
      "fill,order-1,2026-06-14T10:01:00.000Z,2,ABC,fill-1",
      "deposit,,2026-06-14T10:02:00.000Z,50,CZK,deposit-1",
      "temporary,,2026-06-14T10:03:00.000Z,10,CZK,temp-1",
    ].join("\n")

    const result = parseGroupedInvestmentCsv(csv, "account-1", {
      parserName: "GroupedTest",
      parseRow: parseMovement,
      classifyRow: (row) => {
        if (row.type === "payment" && row.orderId) {
          return { kind: "grouped", groupId: row.orderId, bucket: "payments" }
        }
        if (row.type === "fill" && row.orderId) {
          return { kind: "grouped", groupId: row.orderId, bucket: "fills" }
        }
        if (row.type === "deposit") return { kind: "standalone" }
        return { kind: "ignored", code: "ignored_test_row", message: "Ignored test row." }
      },
      buildGroupedTransaction: (groupId, rows, accountId) => {
        const payment = rowsFromBucket(rows, "payments")[0]
        const fill = rowsFromBucket(rows, "fills")[0]
        if (!payment?.date || payment.amount === null || !fill?.currency || fill.amount === null) {
          return null
        }

        return {
          date: payment.date,
          type: "buy",
          symbol: fill.currency,
          assetType: "crypto",
          quantity: Math.abs(fill.amount),
          totalAmount: Math.abs(payment.amount),
          totalCurrency: payment.currency,
          orderId: groupId,
          externalId: fill.externalId,
          accountId,
        }
      },
      buildStandaloneTransaction: (row, accountId) =>
        buildStandaloneInvestment(row, accountId, "crypto"),
    })

    expect(result.rowsTotal).toBe(4)
    expect(result.rows).toHaveLength(2)
    expect(result.rows[0]).toMatchObject({
      type: "buy",
      symbol: "ABC",
      quantity: 2,
      totalAmount: 100,
      orderId: "order-1",
    })
    expect(result.rows[1]).toMatchObject({
      type: "deposit",
      totalAmount: 50,
      totalCurrency: "CZK",
    })
    expect(result.issues[0]).toMatchObject({
      rowNumber: 4,
      code: "ignored_test_row",
    })
  })
})
