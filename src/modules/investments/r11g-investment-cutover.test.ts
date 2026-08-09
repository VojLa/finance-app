import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

async function source(relativePath: string) {
  return readFile(path.join(process.cwd(), relativePath), "utf8")
}

describe("R11-G manual investment and symbol-detail boundary", () => {
  it("keeps the Next route as an authenticated Python adapter", async () => {
    const route = await source("src/app/api/portfolio/transactions/route.ts")

    expect(route).toContain("createPythonInvestmentApi")
    expect(route).toContain("getServerSession")
    expect(route).not.toMatch(/\bprisma\b/)
    expect(route).not.toContain("createInvestmentEvent")
    expect(route).not.toContain("recalculateHoldings")
    expect(route).not.toContain("createPortfolioSnapshot")
  })

  it("uses typed clients and preserves idempotency on both active pages", async () => {
    const addPage = await source("src/app/portfolio/add/page.tsx")
    const detailPage = await source("src/app/portfolio/[symbol]/page.tsx")

    expect(addPage).toContain("createManualInvestment")
    expect(addPage).toContain("idempotencyKey.current")
    expect(addPage).toContain("conversionFromAmount")
    expect(addPage).not.toContain("parseFloat")
    expect(addPage).not.toContain('fetch("/api/portfolio/transactions"')
    expect(detailPage).toContain("requestSymbolDetail")
    expect(detailPage).not.toContain('fetch("/api/portfolio"')
    expect(detailPage).not.toContain("HoldingWithPrice")
  })

  it("exposes generated Python contracts for both capabilities", async () => {
    const generated = await source("src/generated/python-api.ts")

    expect(generated).toContain('"/api/v1/investments/manual"')
    expect(generated).toContain('"/api/v1/investments/symbols/{symbol}"')
    expect(generated).toContain("ManualInvestmentCreateResponse")
    expect(generated).toContain("SymbolDetailResponse")
  })
})
