import { readFile } from "node:fs/promises"
import path from "node:path"

import { describe, expect, it } from "vitest"

import { formatSnapshotAmount } from "@/modules/portfolio/snapshot-page-format"
import { dashboardSnapshotFixture } from "@/test/dashboard-snapshot-fixture"

import { buildSnapshotDashboardModel } from "./snapshot-dashboard-model"

async function source(file: string): Promise<string> {
  return readFile(path.join(process.cwd(), file), "utf8")
}

describe("R10-C dashboard deposited presentation", () => {
  it("wires the visible global card to primary summary finance and base currency", async () => {
    const summary = await source("src/modules/dashboard/SnapshotSummaryCards.tsx")

    expect(summary).toContain('["Čisté vklady", model.summary.netDepositsValue]')
    expect(summary).toContain("formatSnapshotAmount(value, model.currency)")
    expect(formatSnapshotAmount("123456.789012", "CZK")).toContain("123 456,789012")
  })

  it("wires every visible account card to presentation finance and account currency", async () => {
    const accounts = await source("src/modules/dashboard/SnapshotAccountCards.tsx")

    expect(accounts).toContain("Čisté vklady")
    expect(accounts).toContain(
      "formatSnapshotAmount(account.netDepositsValue, account.accountCurrency)"
    )
    expect(formatSnapshotAmount("1250.000000", "USD")).toContain("1 250,000000")
  })

  it("keeps negative net withdrawals and exact zero presentable", () => {
    expect(formatSnapshotAmount("-50.000000", "USD")).toContain("-50,000000")
    expect(formatSnapshotAmount("0.000000", "CZK")).toContain("0,000000")
  })

  it("keeps global and account values as distinct immutable server references", () => {
    const before = structuredClone(dashboardSnapshotFixture)
    const model = buildSnapshotDashboardModel(dashboardSnapshotFixture)

    expect(model.summary).toBe(dashboardSnapshotFixture.summary)
    expect(model.accounts).toBe(dashboardSnapshotFixture.accounts)
    expect(model.summary.netDepositsValue).toBe("123456.789012")
    expect(model.accounts[0].netDepositsValue).toBe("1250.000000")
    expect(model.accounts[1].netDepositsValue).toBe("0.000000")
    expect(dashboardSnapshotFixture).toEqual(before)
  })

  it("contains no request, FX, Prisma, legacy fallback, or financial arithmetic", async () => {
    const files = [
      "src/modules/dashboard/SnapshotSummaryCards.tsx",
      "src/modules/dashboard/SnapshotAccountCards.tsx",
      "src/modules/dashboard/snapshot-dashboard-model.ts",
    ]
    const content = (await Promise.all(files.map(source))).join("\n")

    expect(content).not.toMatch(/\b(?:fetch|Prisma|FX|exchangeRate|latest)\b/i)
    expect(content).not.toContain("/api/rates")
    expect(content).not.toMatch(/\b(?:Number|parseFloat|parseInt)\s*\(/)
    expect(content).not.toMatch(/\bMath\./)
    expect(content).not.toContain(".toFixed(")
    expect(content).not.toContain(".reduce(")
  })
})
