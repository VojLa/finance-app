import { describe, expect, it } from "vitest"
import { parseRaiffeisenbankResult } from "./raiffeisenbank"

describe("parseRaiffeisenbankResult", () => {
  it("parses account statement rows", () => {
    const csv = [
      "Datum provedení;Zaúčtovaná částka;Měna účtu;Typ transakce;Zpráva;Poznámka;Vlastní poznámka;Název protiúčtu;Id transakce",
      "14. 6. 2026;-123,45;CZK;Odchozí platba;Lunch;Card;;Restaurant;rb-1",
    ].join("\n")

    const result = parseRaiffeisenbankResult(csv, "account-1")

    expect(result.issues).toEqual([])
    expect(result.rows).toEqual([
      {
        date: new Date("2026-06-14T00:00:00.000Z"),
        amount: 123.45,
        currency: "CZK",
        type: "expense",
        description: "Lunch | Card",
        counterparty: "Restaurant",
        externalId: "rb-1",
        accountId: "account-1",
      },
    ])
  })

  it("parses card statement rows", () => {
    const csv = [
      "Číslo kreditní karty;Datum transakce;Zaúčtovaná částka;Měna zaúčtování;Typ transakce;Název Obchodníka;Popis/Místo transakce;Město;Vlastní poznámka",
      "1234;14. 6. 2026 12:05;-50;CZK;Platba kartou;Coffee Shop;Terminal;Praha;",
    ].join("\n")

    const result = parseRaiffeisenbankResult(csv, "account-1")

    expect(result.issues).toEqual([])
    expect(result.rows[0]).toMatchObject({
      date: new Date("2026-06-14T12:05:00.000Z"),
      amount: 50,
      currency: "CZK",
      type: "expense",
      description: "Terminal | Coffee Shop | Praha | Platba kartou",
      counterparty: "Coffee Shop",
      accountId: "account-1",
    })
    expect(result.rows[0].externalId).toContain("rb-card")
  })
})
