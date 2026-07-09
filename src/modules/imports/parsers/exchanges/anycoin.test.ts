import { describe, expect, it } from "vitest"
import { parseAnycoinResult } from "./anycoin"

describe("parseAnycoinResult", () => {
  it("combines trade payment and fill rows into one investment transaction", () => {
    const csv = [
      "Type,Order ID,Date,Amount,Currency,anycoin TX ID",
      "trade payment,order-1,2026-06-14T10:00:00.000Z,-1000,CZK,payment-1",
      "trade fill,order-1,2026-06-14T10:01:00.000Z,0.01,BTC,fill-1",
    ].join("\n")

    const result = parseAnycoinResult(csv, "account-1")

    expect(result.issues).toEqual([])
    expect(result.rows).toHaveLength(1)
    expect(result.rows[0]).toMatchObject({
      type: "buy",
      symbol: "BTC",
      assetType: "crypto",
      quantity: 0.01,
      pricePerUnit: 100000,
      totalAmount: 1000,
      totalCurrency: "CZK",
      orderId: "order-1",
      externalId: "fill-1",
      accountId: "account-1",
    })
  })

  it("parses standalone deposits and ignores temporary blocks", () => {
    const csv = [
      "Type,Order ID,Date,Amount,Currency,anycoin TX ID",
      "deposit,,2026-06-14T10:00:00.000Z,500,CZK,deposit-1",
      "payment block,order-1,2026-06-14T10:01:00.000Z,-500,CZK,block-1",
    ].join("\n")

    const result = parseAnycoinResult(csv, "account-1")

    expect(result.rows).toEqual([
      {
        date: new Date("2026-06-14T10:00:00.000Z"),
        type: "deposit",
        totalAmount: 500,
        totalCurrency: "CZK",
        externalId: "deposit-1",
        accountId: "account-1",
      },
    ])
    expect(result.issues).toHaveLength(1)
    expect(result.issues[0]).toMatchObject({
      severity: "ignored",
      code: "temporary_block",
      rowNumber: 2,
    })
  })
})
