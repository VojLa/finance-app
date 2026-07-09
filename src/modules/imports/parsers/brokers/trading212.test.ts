import { describe, expect, it } from "vitest"
import { parseTrading212Result } from "./trading212"

describe("parseTrading212Result", () => {
  it("parses investment rows and reports unsupported rows", () => {
    const csv = [
      "Action,Time,ISIN,Ticker,Name,No. of shares,Price / share,Currency (Price / share),Total,Currency (Total),Currency conversion fee,Currency (Currency conversion fee),ID",
      "Market buy,2026-06-14T10:00:00.000Z,IE00B4L5Y983,VWCE,Vanguard FTSE All-World,2,100.50,EUR,201,EUR,1,EUR,tx-1",
      "Something else,2026-06-14T11:00:00.000Z,,,,,,,,,,,tx-2",
    ].join("\n")

    const result = parseTrading212Result(csv, "account-1")

    expect(result.rowsTotal).toBe(2)
    expect(result.rows).toHaveLength(1)
    expect(result.rows[0]).toMatchObject({
      type: "buy",
      isin: "IE00B4L5Y983",
      symbol: "VWCE",
      quantity: 2,
      pricePerUnit: 100.5,
      fee: 1,
      accountId: "account-1",
    })
    expect(result.issues).toHaveLength(1)
    expect(result.issues[0]).toMatchObject({
      rowNumber: 2,
      severity: "ignored",
      code: "unsupported_action",
    })
  })

  it("parses currency conversion amounts", () => {
    const csv = [
      "Action,Time,ID,Currency conversion from amount,Currency (Currency conversion from amount),Currency conversion to amount,Currency (Currency conversion to amount),Currency conversion fee,Currency (Currency conversion fee)",
      "Currency conversion,2026-05-26T13:31:10.000Z,fx-1,100,USD,86.50,EUR,0.15,EUR",
    ].join("\n")

    const result = parseTrading212Result(csv, "account-1")

    expect(result.rows).toHaveLength(1)
    expect(result.rows[0]).toMatchObject({
      type: "currency_conversion",
      conversionFromAmount: 100,
      conversionFromCurrency: "USD",
      conversionToAmount: 86.5,
      conversionToCurrency: "EUR",
      fee: 0.15,
      feeCurrency: "EUR",
    })
  })

  it("parses cash deposits and withdrawals without asset identity", () => {
    const csv = [
      "Action,Time,ID,Total,Currency (Total)",
      "Deposit,2026-05-01T10:00:00.000Z,dep-1,100,EUR",
      "Withdrawal,2026-05-02T10:00:00.000Z,wd-1,25,EUR",
    ].join("\n")

    const result = parseTrading212Result(csv, "account-1")

    expect(result.rows).toHaveLength(2)
    expect(result.rows[0]).toMatchObject({
      type: "deposit",
      totalAmount: 100,
      totalCurrency: "EUR",
      externalId: "dep-1",
    })
    expect(result.rows[1]).toMatchObject({
      type: "withdrawal",
      totalAmount: 25,
      totalCurrency: "EUR",
      externalId: "wd-1",
    })
  })
})
