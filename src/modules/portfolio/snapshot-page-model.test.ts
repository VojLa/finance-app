import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

import { portfolioSnapshotFixture } from "@/test/portfolio-snapshot-fixture"
import { buildPortfolioPageModel, selectPortfolioAccountView } from "./snapshot-page-model"

function deepFreeze(value: unknown): void {
  if (typeof value !== "object" || value === null || Object.isFrozen(value)) return
  Object.freeze(value)
  for (const child of Object.values(value)) deepFreeze(child)
}

describe("snapshot portfolio page model", () => {
  it("uses the aggregate server summary and unchanged account position evidence", () => {
    const data = portfolioSnapshotFixture()
    const model = buildPortfolioPageModel(data)

    expect(model.aggregate.summary).toBe(data.summary)
    expect(model.aggregate.summary.totalValue).toBe("777.123456")
    expect(model.aggregate.summary.totalValue).not.toBe("163.456789")
    expect(model.aggregate.positions).toHaveLength(2)
    expect(model.aggregate.positions[0]?.position).toBe(data.accounts[0]?.positions[0])
    expect(model.aggregate.positions[0]?.position.allocationPct).toBe("60.000000")
    expect(model.aggregate.hasServerAllocation).toBe(false)
  })

  it("selects the exact account-local server summary without a backend selector", () => {
    const data = portfolioSnapshotFixture()
    const model = buildPortfolioPageModel(data)
    const selected = selectPortfolioAccountView(model, "account-a")

    expect(selected?.accountId).toBe("account-a")
    expect(selected?.accountCurrency).toBe("CZK")
    expect(selected?.summary).toBe(data.accounts[0]?.summary)
    expect(selected?.positions[0]?.accountId).toBe("account-a")
    expect(selected?.positions[0]?.position).toBe(data.accounts[0]?.positions[0])
    expect(selected?.hasServerAllocation).toBe(true)
    expect(selectPortfolioAccountView(model, "unknown-account")).toBeNull()
  })

  it("preserves every Decimal string byte-for-byte without fallbacks or FX", () => {
    const data = portfolioSnapshotFixture()
    const model = buildPortfolioPageModel(data)
    const account = selectPortfolioAccountView(model, "account-a")

    expect(model.aggregate.summary.liabilitiesValue).toBe("-123.450000")
    expect(model.aggregate.summary.investmentValue).toBe("999999999999.999999")
    expect(model.aggregate.summary.totalValue).toBe("777.123456")
    expect(model.accounts[1]?.summary.totalValue).toBe("-57.660000")
    expect(account?.summary.investmentCostBasis).toBe("100.000001")
    expect(account?.positions[0]?.position.quantity).toBe("1.0000000000")
    expect(account?.positions[0]?.position.value).toBe("123.456789")
    expect(account?.positions[0]?.position.costBasis).toBe("100.000001")
    expect(account?.positions[0]?.position.costBasis).not.toBe(
      account?.positions[0]?.position.value
    )
    expect(account?.positions[0]?.position.allocationPct).toBe("60.000000")
  })

  it("is deterministic and does not mutate or financially aggregate its input", () => {
    const data = portfolioSnapshotFixture()
    const before = JSON.stringify(data)
    deepFreeze(data)

    const first = buildPortfolioPageModel(data)
    const second = buildPortfolioPageModel(data)

    expect(second).toEqual(first)
    expect(JSON.stringify(data)).toBe(before)
    expect(first.aggregate.summary).toBe(data.summary)
  })

  it("contains no calculation, FX, price fallback, fetch, Prisma, or latest lookup", async () => {
    const source = await readFile(
      path.join(process.cwd(), "src/modules/portfolio/snapshot-page-model.ts"),
      "utf8"
    )

    expect(source).not.toMatch(/\b(?:Number|parseFloat|parseInt)\s*\(/)
    expect(source).not.toMatch(/\bMath\./)
    expect(source).not.toContain(".toFixed(")
    expect(source).not.toMatch(/\b(?:reduce|fetch|Prisma|latest)\b/)
    expect(source).not.toMatch(/\b(?:FX|exchange rate|price fallback)\b/i)
    expect(source).not.toContain("investmentValue +")
    expect(source).not.toContain("totalValue -")
  })
})
