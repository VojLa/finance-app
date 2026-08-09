import fs from "node:fs"
import path from "node:path"

import { describe, expect, it } from "vitest"

const servicePath = path.join(process.cwd(), "src/modules/portfolio/rates/service.ts")

describe("R11 FX containment", () => {
  it("keeps the compatibility reader source-qualified and incapable of Yahoo FX writes", () => {
    const source = fs.readFileSync(servicePath, "utf8")

    expect(source).toContain('const APPROVED_EXCHANGE_RATE_SOURCE = "cnb"')
    expect(source).toContain("source: APPROVED_EXCHANGE_RATE_SOURCE")
    expect(source).not.toContain("fetchYahooHistoricalExchangeRates")
    expect(source).not.toContain("fetchYahooLatestExchangeRates")
    expect(source).not.toContain("YAHOO_EXCHANGE_RATE_SOURCE")
    expect(source).not.toContain("prisma.exchangeRate.upsert")
  })

  it("fails closed instead of treating an unavailable conversion as identity", () => {
    const source = fs.readFileSync(servicePath, "utf8")

    expect(source).not.toContain("if (!rate) return amount")
    expect(source).toContain("Approved exchange-rate evidence is unavailable")
  })
})
