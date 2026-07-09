import { describe, expect, it } from "vitest"
import { parseInvestmentRow, parseSingleRowInvestmentCsv, type InvestmentFieldKeys } from "./parser"

const keys: InvestmentFieldKeys = {
  type: ["Action"],
  date: ["Time"],
  isin: ["ISIN"],
  symbol: ["Ticker"],
  name: ["Name"],
  assetType: ["Asset type"],
  quantity: ["Quantity"],
  pricePerUnit: ["Price"],
  priceCurrency: ["Price currency"],
  totalAmount: ["Total"],
  totalCurrency: ["Total currency"],
  feeCurrency: ["Fee currency"],
  externalId: ["ID"],
}

describe("parseInvestmentRow", () => {
  it("parses a valid buy row", () => {
    const result = parseInvestmentRow(
      {
        Action: "Market buy",
        Time: "2026-06-14T10:00:00.000Z",
        ISIN: "IE00B4L5Y983",
        Ticker: "VWCE",
        Name: "Vanguard FTSE All-World",
        Quantity: "2",
        Price: "100,50",
        "Price currency": "EUR",
        Total: "201",
        "Total currency": "EUR",
        ID: "tx-1",
      },
      { parserName: "TestBroker", accountId: "account-1", keys }
    )

    expect(result.issues).toBeUndefined()
    expect(result.row).toMatchObject({
      type: "buy",
      isin: "IE00B4L5Y983",
      symbol: "VWCE",
      assetType: "etf",
      quantity: 2,
      pricePerUnit: 100.5,
      totalAmount: 201,
      accountId: "account-1",
    })
  })

  it("ignores unsupported actions", () => {
    const result = parseInvestmentRow(
      { Action: "Unknown thing", Time: "2026-06-14T10:00:00.000Z" },
      { parserName: "TestBroker", accountId: "account-1", keys }
    )

    expect(result.row).toBeNull()
    expect(result.issues?.[0]).toMatchObject({
      severity: "ignored",
      code: "unsupported_action",
    })
  })

  it("drops rows with fatal validation issues", () => {
    const result = parseInvestmentRow(
      { Action: "Buy", Time: "2026-06-14T10:00:00.000Z", Quantity: "not-a-number" },
      { parserName: "TestBroker", accountId: "account-1", keys }
    )

    expect(result.row).toBeNull()
    expect(result.issues?.map((issue) => issue.code)).toEqual(
      expect.arrayContaining(["invalid_quantity", "missing_asset_identity"])
    )
  })

  it("sums configured fee fields when no explicit fee field is mapped", () => {
    const result = parseInvestmentRow(
      {
        Action: "Sell",
        Time: "2026-06-14T10:00:00.000Z",
        Ticker: "AAPL",
        Quantity: "1",
        "Currency conversion fee": "-1.25",
        "Stamp duty reserve tax": "0.75",
      },
      { parserName: "TestBroker", accountId: "account-1", keys }
    )

    expect(result.row?.fee).toBe(2)
  })

  it("detects fiat symbols as cash assets", () => {
    const result = parseInvestmentRow(
      {
        Action: "Deposit",
        Time: "2026-06-14T10:00:00.000Z",
        Ticker: "EUR",
        Quantity: "100",
      },
      { parserName: "TestBroker", accountId: "account-1", keys }
    )

    expect(result.row?.assetType).toBe("cash")
  })
})

describe("parseSingleRowInvestmentCsv", () => {
  it("maps every CSV row through the shared single-row parser", () => {
    const csv = [
      "Action,Time,Ticker,Quantity,ID",
      "Deposit,2026-06-14T10:00:00.000Z,EUR,100,deposit-1",
      "Unsupported,2026-06-14T10:01:00.000Z,EUR,100,ignored-1",
    ].join("\n")

    const result = parseSingleRowInvestmentCsv(csv, "account-1", {
      parserName: "TestBroker",
      keys,
    })

    expect(result.rowsTotal).toBe(2)
    expect(result.rows).toHaveLength(1)
    expect(result.rows[0]).toMatchObject({
      type: "deposit",
      symbol: "EUR",
      assetType: "cash",
      externalId: "deposit-1",
      accountId: "account-1",
    })
    expect(result.issues[0]).toMatchObject({
      rowNumber: 2,
      code: "unsupported_action",
    })
  })
})
