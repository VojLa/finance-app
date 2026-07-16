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

  it("parses the newer Time (UTC) export column", () => {
    const csv = [
      "Action,Time (UTC),ID,Total,Currency (Total)",
      "Deposit,2026-01-01 02:03:12+00:00,dep-utc-1,100,EUR",
    ].join("\n")

    const result = parseTrading212Result(csv, "account-1")

    expect(result.rows).toHaveLength(1)
    expect(result.rows[0]).toMatchObject({
      type: "deposit",
      totalAmount: 100,
      totalCurrency: "EUR",
      externalId: "dep-utc-1",
    })
    expect(result.rows[0].date.toISOString()).toBe("2026-01-01T02:03:12.000Z")
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

  it("parses card debit rows as withdrawals with linked expense transactions", () => {
    const csv = [
      "Action,Time,ID,Total,Currency (Total),Merchant name,Card category",
      "Card debit,2025-01-04 11:08:21,d0978cbd-47b5-4d97-bf6d-005154408f14,-19.70,EUR,ZISCHGALM,HOTELS",
    ].join("\n")

    const result = parseTrading212Result(csv, "account-1")

    expect(result.rows).toHaveLength(1)
    expect(result.rows[0]).toMatchObject({
      type: "withdrawal",
      rawAction: "Card debit",
      totalAmount: 19.7,
      totalCurrency: "EUR",
      externalId: "d0978cbd-47b5-4d97-bf6d-005154408f14",
      linkedTransactionType: "expense",
      linkedTransactionDescription: "Card debit: ZISCHGALM",
      linkedTransactionCounterparty: "ZISCHGALM",
      linkedTransactionNote: "HOTELS",
    })
  })

  it("parses additional Trading 212 cash and dividend actions", () => {
    const csv = [
      "Action,Time,ID,Total,Currency (Total),Name,Merchant name,Card category",
      "Spending cashback,2026-01-01T10:00:00.000Z,cashback-1,1.23,EUR,,,",
      "Dividend (Dividend manufactured payment),2026-01-02T10:00:00.000Z,div-manufactured-1,2.34,USD,Apple,,",
      "Dividend (Dividend),2026-01-03T10:00:00.000Z,div-1,3.45,USD,Microsoft,,",
      "Dividend (Tax exempted),2026-01-04T10:00:00.000Z,div-tax-exempted-1,4.56,EUR,Vanguard,,",
      "New card cost,2026-01-05T10:00:00.000Z,new-card-1,-5.00,EUR,,Trading 212,CARDS",
    ].join("\n")

    const result = parseTrading212Result(csv, "account-1")

    expect(result.issues).toEqual([])
    expect(result.rows).toHaveLength(5)
    expect(result.rows.map((row) => row.type)).toEqual([
      "interest",
      "dividend",
      "dividend",
      "dividend",
      "withdrawal",
    ])
    expect(result.rows[0]).toMatchObject({
      type: "interest",
      totalAmount: 1.23,
      totalCurrency: "EUR",
    })
    expect(result.rows[4]).toMatchObject({
      type: "withdrawal",
      totalAmount: 5,
      totalCurrency: "EUR",
      linkedTransactionType: "expense",
      linkedTransactionDescription: "New card cost: Trading 212",
      linkedTransactionCounterparty: "Trading 212",
      linkedTransactionNote: "CARDS",
    })
  })

  it("does not treat dividend withholding tax as a cash fee", () => {
    const csv = [
      "Action,Time,ID,Name,Total,Currency (Total),Withholding tax,Currency (Withholding tax)",
      "Dividend (Dividend),2026-01-03T10:00:00.000Z,div-tax-1,Apple,0.28,EUR,0.09,USD",
    ].join("\n")

    const result = parseTrading212Result(csv, "account-1")

    expect(result.issues).toEqual([])
    expect(result.rows).toHaveLength(1)
    expect(result.rows[0]).toMatchObject({
      type: "dividend",
      totalAmount: 0.28,
      totalCurrency: "EUR",
      fee: null,
      feeCurrency: "USD",
    })
  })

  it("parses free share asset rows as promotional airdrops without fees", () => {
    const csv = [
      "Action,Time,ISIN,Ticker,Name,Notes,No. of shares,Price / share,Currency (Price / share),Total,Currency (Total),Currency conversion fee,Currency (Currency conversion fee),ID",
      "Free share,2026-05-03T10:00:00.000Z,US0378331005,AAPL,Apple,Free share promo,0.05,200,USD,10,USD,0.02,USD,free-1",
    ].join("\n")

    const result = parseTrading212Result(csv, "account-1")

    expect(result.rows).toHaveLength(1)
    expect(result.rows[0]).toMatchObject({
      type: "airdrop",
      symbol: "AAPL",
      quantity: 0.05,
      totalAmount: 10,
      fee: null,
      feeCurrency: null,
      isPromotional: true,
    })
  })

  it("marks free share cash deposits as promotional and ignores their fees", () => {
    const csv = [
      "Action,Time,Notes,Total,Currency (Total),Currency conversion fee,Currency (Currency conversion fee),ID",
      "Deposit,2026-05-03T10:00:00.000Z,Free share bonus,10,EUR,0.02,EUR,free-cash-1",
      "Free share,2026-05-04T10:00:00.000Z,,12,EUR,0.03,EUR,free-cash-2",
    ].join("\n")

    const result = parseTrading212Result(csv, "account-1")

    expect(result.rows).toHaveLength(2)
    expect(result.rows[0]).toMatchObject({
      type: "deposit",
      note: "Free share bonus",
      totalAmount: 10,
      totalCurrency: "EUR",
      fee: null,
      feeCurrency: null,
      isPromotional: true,
    })
    expect(result.rows[1]).toMatchObject({
      type: "deposit",
      rawAction: "Free share",
      totalAmount: 12,
      totalCurrency: "EUR",
      fee: null,
      feeCurrency: null,
      isPromotional: true,
    })
  })
})
